"""Assistant : répond aux questions sur le planning et propose des actions.

Le modèle ne modifie jamais les données lui-même : il propose des actions
(appels de fonction) que l'utilisateur applique ou refuse une par une.
Le calcul du planning reste celui du moteur de l'application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import Intervalle, occurrences
from ..moteur.placement import minutes_preparation
from ..suivi import marquer
from .gemini import ClientGemini, ErreurGemini
from .import_edt import JOURS, _normaliser, associer_matiere, lire_heure

LIBELLES_TYPE = {
    m.TypeSeance.REVISION: "révision", m.TypeSeance.PREPARATION: "préparation", m.TypeSeance.TRAVAIL: "travail",
}
STATUTS = {"prevue": "prévue", "terminee": "faite", "partielle": "faite en partie", "manquee": "manquée",
           "reportee": "reportée"}

INSTRUCTION = """Tu es l'assistant intégré au « Planificateur d'études » d'un étudiant : à la fois \
l'organisateur de son planning et un coach d'études bienveillant. Réponds en français, clairement, avec une \
longueur adaptée à la question (bref pour une question simple, plus détaillé pour une explication). Tu peux \
utiliser la mise en forme Markdown simple (gras, listes, titres courts).

Au-delà du planning, tu peux l'aider pour ses études : expliquer une notion de cours, proposer une méthode \
de révision ou des exercices, faire un petit quiz, donner un plan de travail pour une épreuve, l'aider à \
gérer le stress ou la motivation. Appuie-toi sur ses matières, ses épreuves et ses résultats ci-dessous pour \
personnaliser tes conseils. Pour une question sans lien avec ses études, réponds brièvement et poliment.

Tu disposes ci-dessous des données de son planificateur et de la conversation en cours. Utilise-les pour \
répondre : n'invente ni cours, ni épreuve, ni séance. Si une information nécessaire manque (heure, matière, date), pose la question au lieu \
de deviner.

Tu ne modifies rien toi-même. Pour ajouter ou changer quelque chose, appelle la fonction adaptée : \
l'étudiant verra chaque proposition et décidera de l'appliquer. Une indisponibilité ponctuelle (sortie, \
rendez-vous, sport…) s'ajoute avec « ajouter_activite » de type « personnel » à une date précise. Une activité qui revient chaque semaine sur plusieurs jours s'ajoute en un seul appel, \navec tous ses jours dans « jours » (sans date). Après des \
changements qui touchent le planning, propose aussi « regenerer_planning ». Les noms de matière doivent être \
pris dans la liste fournie ; si une matière manque, propose d'abord « ajouter_matiere » (dans la même \
réponse, avant les propositions qui l'utilisent). Dates au format AAAA-MM-JJ, heures au format HH:MM.

Règles du planning (pour expliquer ses choix) : les cours et épreuves ne bougent jamais ; les échéances les \
plus proches passent d'abord, étalées sur plusieurs jours ; aucune séance dans les heures qui précèdent une \
épreuve ni après elle le même jour ; les plages garanties (par défaut 20 h – 23 h du lundi au vendredi) sont \
toujours remplies ; les autres moments libres de la semaine reçoivent des séances espacées ; un cours se \
révise de préférence la veille, sinon l'avant-veille ; une matière terminée n'est plus révisée."""


def _f(nom, description, proprietes, requis):
    return {"type": "function", "name": nom, "description": description,
            "parameters": {"type": "object", "properties": proprietes, "required": requis}}


_TEXTE = {"type": "string"}
OUTILS = [
    _f("ajouter_epreuve", "Ajoute une épreuve (interrogation, devoir surveillé, composition, examen) à date fixe.", {
        "matiere": {**_TEXTE, "description": "Nom exact d'une matière de la liste"},
        "type": {"type": "string", "enum": ["interrogation", "devoir_surveille", "composition", "examen"]},
        "date": {**_TEXTE, "description": "AAAA-MM-JJ"},
        "debut": {**_TEXTE, "description": "HH:MM"},
        "fin": {**_TEXTE, "description": "HH:MM"},
        "chapitres": {**_TEXTE, "description": "Contenu à préparer, si connu"},
    }, ["matiere", "type", "date", "debut", "fin"]),
    _f("ajouter_travail", "Ajoute un travail à rendre (devoir, rapport, exposé…) avec une échéance.", {
        "intitule": _TEXTE,
        "matiere": {**_TEXTE, "description": "Nom exact d'une matière de la liste"},
        "echeance_date": {**_TEXTE, "description": "AAAA-MM-JJ"},
        "echeance_heure": {**_TEXTE, "description": "HH:MM (18:00 si non précisé)"},
        "minutes_estimees": {"type": "integer", "description": "Temps de travail estimé en minutes"},
    }, ["intitule", "matiere", "echeance_date", "minutes_estimees"]),
    _f("ajouter_activite", "Ajoute un cours ou une activité à horaire fixe, ou une indisponibilité (type personnel).", {
        "nom": _TEXTE,
        "type": {"type": "string", "enum": ["cours", "td", "tp", "personnel", "deplacement", "autre"]},
        "date": {**_TEXTE, "description": "AAAA-MM-JJ pour une seule fois"},
        "jours": {"type": "array", "items": {"type": "string", "enum": JOURS},
                  "description": "Pour une activité chaque semaine (sans date) : un ou plusieurs jours"},
        "debut": {**_TEXTE, "description": "HH:MM"},
        "fin": {**_TEXTE, "description": "HH:MM"},
        "matiere": {**_TEXTE, "description": "Matière liée, s'il s'agit d'un cours"},
    }, ["nom", "type", "debut", "fin"]),
    _f("pointer_seance", "Indique ce qui a été fait pendant une séance du planning (par son numéro).", {
        "seance_id": {"type": "integer", "description": "Numéro de la séance (#…) dans les données"},
        "statut": {"type": "string", "enum": ["faite", "partielle", "manquee"]},
        "minutes": {"type": "integer", "description": "Minutes réellement travaillées si « partielle »"},
    }, ["seance_id", "statut"]),
    _f("ajouter_matiere", "Ajoute une nouvelle matière à la liste de l'étudiant (avant d'y rattacher cours, "
       "épreuves ou travaux).", {
        "nom": {**_TEXTE, "description": "Nom de la matière, tel que l'étudiant le dit"},
        "coefficient": {"type": "number", "description": "Coefficient (1 si inconnu)"},
        "difficulte": {"type": "integer", "description": "Difficulté ressentie, de 1 (facile) à 5 (très difficile)"},
        "maitrise": {"type": "integer", "description": "Maîtrise actuelle, de 1 (pas du tout) à 5 (très bonne)"},
        "code": {**_TEXTE, "description": "Code de l'UE, si connu"},
    }, ["nom"]),
    _f("marquer_matiere_terminee", "Marque une matière comme terminée : elle ne sera plus révisée.", {
        "matiere": {**_TEXTE, "description": "Nom exact d'une matière de la liste"},
    }, ["matiere"]),
    _f("regenerer_planning", "Recalcule le planning avec les données actuelles.", {}, []),
]


# --- Contexte envoyé ------------------------------------------------------------


def _jour(d: date) -> str:
    return f"{JOURS[d.weekday()][:3]} {d:%d/%m}"


def contexte(base: Base, maintenant: datetime) -> str:
    """Résumé texte des données utiles, et rien d'autre (pas de chemin, pas de fichier)."""
    aujourd_hui = maintenant.date()
    matieres = {x.id: x for x in base.matieres.lister(ordre="nom")}
    preferences = base.preferences()
    lignes = [f"Aujourd'hui : {JOURS[aujourd_hui.weekday()]} {aujourd_hui:%d/%m/%Y}, {maintenant:%H:%M}.",
              f"Journée type : lever {preferences.debut_journee:%H:%M}, coucher {preferences.fin_journee:%H:%M}.",
              f"Réglages : séances de {preferences.duree_min_seance} à {preferences.duree_max_seance} min, "
              f"au plus {preferences.max_minutes_jour} min de travail par jour, révisions régulières visées "
              f"{preferences.minutes_revision_semaine} min par semaine, repos de {preferences.repos_avant_epreuve_min} "
              "min avant une épreuve.",
              "Plages garanties : " + (", ".join(
                  f"{'/'.join(JOURS[j][:3] for j in p.jours)} {p.debut:%H:%M}–{p.fin:%H:%M}"
                  for p in preferences.plages_garanties) or "aucune")
              + " ; à éviter : " + (", ".join(
                  f"{'/'.join(JOURS[j][:3] for j in p.jours)} {p.debut:%H:%M}–{p.fin:%H:%M}"
                  for p in preferences.plages_evitees) or "aucune") + ".",
              "", "Matières (coefficient, difficulté ressentie et maîtrise sur 5) :"]
    for x in matieres.values():
        lignes.append(f"- {x.nom}" + (f" [{x.code}]" if x.code else "")
                      + f" : coef {x.coefficient:g}, difficulté {x.difficulte}/5, maîtrise {x.maitrise}/5"
                      + (" (terminée : plus révisée)" if x.terminee else "")
                      + (f" — notes : {x.notes}" if x.notes else ""))

    lignes += ["", "Emploi du temps (14 prochains jours) :"]
    activites = base.activites.lister()
    for activite, horaire in occurrences(activites, aujourd_hui, aujourd_hui + timedelta(days=13), base.exceptions.lister()):
        matiere = matieres.get(activite.matiere_id)
        lignes.append(f"- {_jour(horaire.debut.date())} {horaire.debut:%H:%M}–{horaire.fin:%H:%M} {activite.nom} "
                      f"({activite.type.value}{', ' + matiere.nom if matiere and matiere.nom != activite.nom else ''})")

    lignes += ["", "Épreuves à venir :"]
    for e in base.epreuves.lister(ordre="debut"):
        if e.fin >= maintenant:
            nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else "?"
            lignes.append(f"- {_jour(e.debut.date())} {e.debut:%H:%M}–{e.fin:%H:%M} {e.type.value} de {nom}"
                          f" (préparation visée {minutes_preparation(e)} min)" + (f", chapitres : {e.chapitres}" if e.chapitres else ""))

    lignes += ["", "Travaux à rendre :"]
    for t in base.travaux.lister(ordre="echeance"):
        if t.etat is not m.EtatTravail.RENDU and t.echeance >= maintenant - timedelta(days=1):
            nom = matieres[t.matiere_id].nom if t.matiere_id in matieres else "?"
            lignes.append(f"- {t.intitule} ({nom}) pour le {_jour(t.echeance.date())} {t.echeance:%H:%M}, "
                          f"reste {t.minutes_restantes} min sur {t.minutes_estimees}")

    lignes += ["", "Épreuves passées (30 derniers jours) :"]
    for e in base.epreuves.lister(ordre="debut"):
        if maintenant - timedelta(days=30) <= e.fin < maintenant:
            nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else "?"
            lignes.append(f"- {_jour(e.debut.date())} {e.type.value} de {nom}")

    from ..suivi import bilan

    resultat = bilan(base, aujourd_hui - timedelta(days=27), aujourd_hui, maintenant)
    taux = "—" if resultat.taux is None else f"{round(100 * resultat.taux)} %"
    lignes += ["", f"Bilan des 4 dernières semaines : {resultat.fait} min faites sur {resultat.prevu} min prévues "
               f"(taux de réalisation {taux}), {resultat.manque} min manquées, {resultat.non_pointe} min non pointées."]
    for matiere_id, ligne in sorted(resultat.par_matiere.items(), key=lambda kv: -kv[1].prevu):
        nom = matieres[matiere_id].nom if matiere_id in matieres else "sans matière"
        lignes.append(f"- {nom} : {ligne.fait} min faites / {ligne.prevu} prévues, {ligne.manque} manquées")
    try:
        from ..conseils import conseils

        observations = [c for c in conseils(base, maintenant) if c.cle not in ("attente", "rien")]
    except Exception:  # noqa: BLE001 — un conseil impossible ne doit pas empêcher de répondre
        observations = []
    if observations:
        lignes += ["Observations de l'application :"] + [f"- {c.titre} : {c.texte}" for c in observations]

    lignes += ["", "Séances du planning (7 derniers jours et 14 prochains) :"]
    debut = datetime.combine(aujourd_hui - timedelta(days=7), time.min)
    fin = datetime.combine(aujourd_hui + timedelta(days=15), time.min)
    for s in base.seances.lister("debut >= ? AND debut < ?", (debut.isoformat(timespec="minutes"),
                                                             fin.isoformat(timespec="minutes")), ordre="debut"):
        matiere = matieres.get(s.matiere_id)
        lignes.append(f"- #{s.id} {_jour(s.debut.date())} {s.debut:%H:%M}–{s.fin:%H:%M} {LIBELLES_TYPE[s.type]} "
                      f"{matiere.nom if matiere else ''} ({STATUTS.get(s.statut.value, s.statut.value)})")
    return "\n".join(lignes)


# --- Actions proposées -------------------------------------------------------


@dataclass
class Action:
    nom: str
    arguments: dict
    description: str


def _matiere(base: Base, nom) -> m.Matiere:
    matieres = base.matieres.lister()
    identifiant = associer_matiere(str(nom or ""), matieres)
    if identifiant is None:
        raise ValueError(f"Matière inconnue : « {nom} ». Si elle vient d'être proposée, appliquez d'abord "
                         "la proposition « Ajouter la matière ».")
    return base.matieres.obtenir(identifiant)


def _date(texte) -> date:
    try:
        return date.fromisoformat(str(texte)[:10])
    except ValueError:
        raise ValueError(f"Date illisible : « {texte} ».") from None


def _heure(texte, defaut: time | None = None) -> time:
    heure = lire_heure(texte) if texte else defaut
    if heure is None:
        raise ValueError(f"Heure illisible : « {texte} ».")
    return heure


def construire(base: Base, nom: str, a: dict):
    """Objet à créer (ou à modifier) pour une action, après vérification de ses arguments."""
    if nom == "ajouter_epreuve":
        matiere = _matiere(base, a.get("matiere"))
        jour = _date(a.get("date"))
        return m.Epreuve(matiere.id, datetime.combine(jour, _heure(a.get("debut"))),
                         datetime.combine(jour, _heure(a.get("fin"))), type=m.TypeEpreuve(a.get("type", "composition")),
                         chapitres=str(a.get("chapitres", "") or ""))
    if nom == "ajouter_travail":
        matiere = _matiere(base, a.get("matiere"))
        echeance = datetime.combine(_date(a.get("echeance_date")), _heure(a.get("echeance_heure"), time(18)))
        return m.Travail(str(a.get("intitule", "")).strip() or "Travail", matiere.id, echeance,
                         int(a.get("minutes_estimees") or 60))
    if nom == "ajouter_activite":
        matiere_id = None
        if a.get("matiere"):  # facultative pour une activité : un nom inconnu (ex. « Coursera ») n'empêche rien
            matiere_id = associer_matiere(str(a["matiere"]), base.matieres.lister())
        jour_unique = _date(a["date"]) if a.get("date") else None
        jour_semaine = None
        if jour_unique is None:
            jours = jours_de(a)
            if not jours:
                raise ValueError("Indiquez une date ou un jour de la semaine.")
            jour_semaine = jours[0]
        return m.ActiviteFixe(str(a.get("nom", "")).strip() or "Activité", _heure(a.get("debut")), _heure(a.get("fin")),
                              type=m.TypeActivite(a.get("type", "autre")), jour_semaine=jour_semaine,
                              date=jour_unique, matiere_id=matiere_id)
    if nom == "pointer_seance":
        seance = base.seances.obtenir(int(a.get("seance_id", 0)))
        if seance is None:
            raise ValueError(f"Séance #{a.get('seance_id')} introuvable.")
        return seance
    if nom == "marquer_matiere_terminee":
        return _matiere(base, a.get("matiere"))
    if nom == "ajouter_matiere":
        nom_matiere = " ".join(str(a.get("nom", "")).split())
        if not nom_matiere:
            raise ValueError("Indiquez le nom de la matière.")
        if any(_normaliser(x.nom) == _normaliser(nom_matiere) for x in base.matieres.lister()):
            raise ValueError(f"La matière « {nom_matiere} » existe déjà.")

        def entre(valeur, bas, haut, defaut):
            try:
                return max(bas, min(haut, type(defaut)(valeur)))
            except (TypeError, ValueError):
                return defaut

        return m.Matiere(nom_matiere, code=str(a.get("code") or "").strip(),
                         coefficient=entre(a.get("coefficient", 1.0), 0.5, 50.0, 1.0),
                         difficulte=entre(a.get("difficulte", 3), 1, 5, 3), maitrise=entre(a.get("maitrise", 3), 1, 5, 3),
                         couleur=m.couleur_libre([x.couleur for x in base.matieres.lister()]))
    if nom == "regenerer_planning":
        return None
    raise ValueError(f"Action inconnue : {nom}")


def decrire(base: Base, nom: str, a: dict) -> str:
    objet = construire(base, nom, a)
    if nom == "ajouter_epreuve":
        matiere = base.matieres.obtenir(objet.matiere_id).nom
        libelle = {"interrogation": "interrogation", "devoir_surveille": "devoir surveillé",
                   "composition": "composition", "examen": "examen"}[objet.type.value]
        return f"Ajouter l'épreuve : {libelle} de {matiere}, {_jour(objet.debut.date())} {objet.debut:%H:%M}–{objet.fin:%H:%M}"
    if nom == "ajouter_travail":
        matiere = base.matieres.obtenir(objet.matiere_id).nom
        return f"Ajouter le travail : « {objet.intitule} » ({matiere}), pour le {_jour(objet.echeance.date())} {objet.echeance:%H:%M}, environ {objet.minutes_estimees} min"
    if nom == "ajouter_activite":
        quand = _jour(objet.date) if objet.date else f"chaque {JOURS[objet.jour_semaine]}"
        return f"Ajouter à l'emploi du temps : « {objet.nom} » ({objet.type.value}), {quand} {objet.heure_debut:%H:%M}–{objet.heure_fin:%H:%M}"
    if nom == "pointer_seance":
        statut = {"faite": "faite", "partielle": "faite en partie", "manquee": "manquée"}.get(a.get("statut"), a.get("statut"))
        return f"Marquer la séance du {_jour(objet.debut.date())} {objet.debut:%H:%M} comme {statut}"
    if nom == "marquer_matiere_terminee":
        return f"Marquer « {objet.nom} » comme terminée (plus de révisions)"
    if nom == "ajouter_matiere":
        return (f"Ajouter la matière « {objet.nom} » (coefficient {objet.coefficient:g}, difficulté "
                f"{objet.difficulte}/5, maîtrise {objet.maitrise}/5)")
    return "Recalculer le planning"


_NOMS_JOURS = {
    **{nom: n for n, nom in enumerate(JOURS)},
    **{nom[:3]: n for n, nom in enumerate(JOURS)},
    **{nom: n for n, nom in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])},
}


def jours_de(arguments: dict) -> list[int]:
    """Jours de la semaine (0 = lundi) dans une proposition, quelle que soit leur forme.

    Accepte « jours » ou « jour » (et variantes), une liste ou un texte comme
    « Lundi et Mardi », les abréviations, l'anglais ou un numéro.
    """
    import re
    import unicodedata

    valeurs = []
    for cle in ("jours", "jour", "jour_semaine", "jours_semaine", "days", "day"):
        valeur = arguments.get(cle)
        if valeur is None or valeur == "":
            continue
        valeurs += valeur if isinstance(valeur, list) else [valeur]
    jours: list[int] = []
    for valeur in valeurs:
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            numero = int(valeur)
            candidats = [min(numero, 6)] if numero >= 0 else []
        else:
            texte = unicodedata.normalize("NFD", str(valeur).lower())
            texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
            candidats = [_NOMS_JOURS[mot] for mot in re.findall(r"[a-z]+", texte) if mot in _NOMS_JOURS]
        for jour in candidats:
            if jour not in jours:
                jours.append(jour)
    return jours


def _developper(appel) -> list:
    """Une activité hebdomadaire sur plusieurs jours devient une proposition par jour."""
    from .gemini import Appel

    if appel.nom != "ajouter_activite" or appel.arguments.get("date"):
        return [appel]
    jours = jours_de(appel.arguments)
    if len(jours) <= 1:
        return [appel]
    base_args = {k: v for k, v in appel.arguments.items()
                 if k not in ("jours", "jour", "jour_semaine", "jours_semaine", "days", "day")}
    return [Appel(appel.nom, {**base_args, "jour": JOURS[j]}) for j in jours]


def _decrire_en_attente(nom: str, a: dict, matiere: str) -> str:
    """Description d'une proposition dont la matière sera créée par une autre proposition de la même réponse."""
    if nom == "ajouter_epreuve":
        return (f"Ajouter l'épreuve : {str(a.get('type', 'épreuve')).replace('_', ' ')} de {matiere}, "
                f"{a.get('date', '?')} {a.get('debut', '?')}–{a.get('fin', '?')} (après l'ajout de la matière)")
    if nom == "ajouter_travail":
        return (f"Ajouter le travail : « {a.get('intitule', 'Travail')} » ({matiere}), pour le "
                f"{a.get('echeance_date', '?')} (après l'ajout de la matière)")
    if nom == "marquer_matiere_terminee":
        return f"Marquer « {matiere} » comme terminée (après l'ajout de la matière)"
    raise ValueError(f"Matière inconnue : « {matiere} ».")


def preparer(base: Base, appels) -> tuple[list[Action], list[str]]:
    actions, erreurs = [], []
    liste = [a for brut in appels for a in _developper(brut)]
    # Les matières à créer passent en premier ; leurs noms sont acceptés par les autres propositions
    liste.sort(key=lambda a: a.nom != "ajouter_matiere")
    en_attente = {_normaliser(str(a.arguments.get("nom", ""))): str(a.arguments.get("nom", ""))
                  for a in liste if a.nom == "ajouter_matiere"}
    for appel in liste:
        try:
            matiere = str(appel.arguments.get("matiere") or "")
            if (appel.nom != "ajouter_matiere" and matiere and _normaliser(matiere) in en_attente
                    and associer_matiere(matiere, base.matieres.lister()) is None):
                if appel.nom == "ajouter_activite":  # la matière d'une activité est facultative
                    description = decrire(base, appel.nom, appel.arguments)
                else:
                    description = _decrire_en_attente(appel.nom, appel.arguments, en_attente[_normaliser(matiere)])
                actions.append(Action(appel.nom, appel.arguments, description))
                continue
            actions.append(Action(appel.nom, appel.arguments, decrire(base, appel.nom, appel.arguments)))
        except (ValueError, TypeError, KeyError) as erreur:
            recu = ", ".join(f"{k}={v!r}" for k, v in appel.arguments.items())
            erreurs.append(f"Proposition ignorée ({appel.nom}) : {erreur} [reçu : {recu}]")
    return actions, erreurs


def _chevauche(base: Base, activite: m.ActiviteFixe) -> str | None:
    debut = activite.date or date.today()
    fin = debut + timedelta(days=0 if activite.date else 6)
    exceptions = base.exceptions.lister()
    miennes = [i for _, i in occurrences([activite], debut, fin, exceptions)]
    for autre, horaire in occurrences(base.activites.lister(), debut, fin, exceptions):
        if any(horaire.chevauche(i) for i in miennes):
            return autre.nom
    return None


def appliquer(base: Base, action: Action, maintenant: datetime | None = None) -> str:
    """Exécute une action acceptée par l'utilisateur. Renvoie un message de confirmation."""
    objet = construire(base, action.nom, action.arguments)
    if action.nom == "ajouter_epreuve":
        base.epreuves.ajouter(objet)
    elif action.nom == "ajouter_travail":
        base.travaux.ajouter(objet)
    elif action.nom == "ajouter_activite":
        conflit = _chevauche(base, objet)
        if conflit:
            raise ValueError(f"Ce moment chevauche « {conflit} » dans l'emploi du temps.")
        base.activites.ajouter(objet)
    elif action.nom == "pointer_seance":
        statut = {"faite": m.StatutSeance.TERMINEE, "partielle": m.StatutSeance.PARTIELLE,
                  "manquee": m.StatutSeance.MANQUEE}[action.arguments.get("statut")]
        marquer(base, objet, statut, action.arguments.get("minutes"))
    elif action.nom == "marquer_matiere_terminee":
        objet.terminee = True
        base.matieres.modifier(objet)
    elif action.nom == "ajouter_matiere":
        from ..suivi import relier_activites

        matiere = base.matieres.ajouter(objet)
        reliees = relier_activites(base, matiere)
        message = f"Matière « {matiere.nom} » ajoutée"
        if reliees:
            message += f" ; {reliees} cours de l'emploi du temps lui sont maintenant rattachés"
        return message + "."
    elif action.nom == "regenerer_planning":
        from ..suivi import relier_activites
        from ..ui.calendrier import enregistrer_resultat, generer

        relier_activites(base)
        resultat = generer(base, maintenant)
        enregistrer_resultat(base, resultat)
        return "Planning recalculé" + ("" if resultat.faisable else " — attention, tout ne tient pas")
    return "Fait : " + action.description[0].lower() + action.description[1:]


# --- Conversation ---------------------------------------------------------------


MEMOIRE_MESSAGES = 40  # messages de la conversation transmis à Gemini
MEMOIRE_PAR_MESSAGE = 4000
MEMOIRE_CARACTERES = 24000


def preparer_envoi(base: Base, historique: list[tuple[str, str]], message: str,
                   maintenant: datetime | None = None) -> str:
    """Texte complet envoyé à Gemini (à construire dans le fil principal : il lit la base)."""
    maintenant = maintenant or datetime.now()
    morceaux = ["Données du planificateur :", contexte(base, maintenant), ""]
    if historique:
        retenus, taille = [], 0
        for qui, texte in reversed(historique[-MEMOIRE_MESSAGES:]):  # les plus récents d'abord
            texte = texte if len(texte) <= MEMOIRE_PAR_MESSAGE else texte[:MEMOIRE_PAR_MESSAGE] + "…"
            if taille + len(texte) > MEMOIRE_CARACTERES:
                break
            retenus.append((qui, texte))
            taille += len(texte)
        morceaux.append("Conversation en cours (du plus ancien au plus récent)"
                        + (" — début omis :" if len(retenus) < len(historique) else " :"))
        for qui, texte in reversed(retenus):
            morceaux.append(f"{'Étudiant' if qui == 'utilisateur' else 'Assistant'} : {texte}")
        morceaux.append("")
    morceaux.append(f"Nouveau message de l'étudiant : {message}")
    return "\n".join(morceaux)


def demander(client: ClientGemini, entree: str):
    """Appel réseau seul (peut tourner en arrière-plan)."""
    return client.interagir(entree, instruction=INSTRUCTION, outils=OUTILS)


def interpreter_reponse(base: Base, reponse) -> tuple[str, list[Action], list[str]]:
    actions, erreurs = preparer(base, reponse.appels)
    texte = reponse.texte
    if not texte and actions:
        texte = "Voici ce que je propose :"
    if not texte and erreurs:
        texte = "Je n'ai pas pu formuler une proposition valable :"
    if not texte and not actions:
        raise ErreurGemini("Gemini n'a rien répondu. Reformulez votre demande.")
    return texte, actions, erreurs


def repondre(client: ClientGemini, base: Base, historique: list[tuple[str, str]], message: str,
             maintenant: datetime | None = None) -> tuple[str, list[Action], list[str]]:
    """Envoie la question avec le contexte ; renvoie (texte, actions proposées, erreurs)."""
    reponse = demander(client, preparer_envoi(base, historique, message, maintenant))
    return interpreter_reponse(base, reponse)
