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
from .import_edt import JOURS, associer_matiere, lire_heure

LIBELLES_TYPE = {
    m.TypeSeance.REVISION: "révision", m.TypeSeance.PREPARATION: "préparation", m.TypeSeance.TRAVAIL: "travail",
}
STATUTS = {"prevue": "prévue", "terminee": "faite", "partielle": "faite en partie", "manquee": "manquée",
           "reportee": "reportée"}

INSTRUCTION = """Tu es l'assistant intégré au « Planificateur d'études » d'un étudiant. Réponds en français, \
de façon brève, claire et bienveillante.

Tu disposes ci-dessous des données de son planificateur. Utilise-les pour répondre : n'invente ni cours, ni \
épreuve, ni séance. Si une information nécessaire manque (heure, matière, date), pose la question au lieu \
de deviner.

Tu ne modifies rien toi-même. Pour ajouter ou changer quelque chose, appelle la fonction adaptée : \
l'étudiant verra chaque proposition et décidera de l'appliquer. Une indisponibilité ponctuelle (sortie, \
rendez-vous, sport…) s'ajoute avec « ajouter_activite » de type « personnel » à une date précise. Après des \
changements qui touchent le planning, propose aussi « regenerer_planning ». Les noms de matière doivent être \
pris dans la liste fournie. Dates au format AAAA-MM-JJ, heures au format HH:MM.

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
        "jour": {"type": "string", "enum": JOURS, "description": "Pour une activité chaque semaine (sans date)"},
        "debut": {**_TEXTE, "description": "HH:MM"},
        "fin": {**_TEXTE, "description": "HH:MM"},
        "matiere": {**_TEXTE, "description": "Matière liée, s'il s'agit d'un cours"},
    }, ["nom", "type", "debut", "fin"]),
    _f("pointer_seance", "Indique ce qui a été fait pendant une séance du planning (par son numéro).", {
        "seance_id": {"type": "integer", "description": "Numéro de la séance (#…) dans les données"},
        "statut": {"type": "string", "enum": ["faite", "partielle", "manquee"]},
        "minutes": {"type": "integer", "description": "Minutes réellement travaillées si « partielle »"},
    }, ["seance_id", "statut"]),
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
              "", "Matières :"]
    for x in matieres.values():
        lignes.append(f"- {x.nom}" + (" (terminée)" if x.terminee else ""))

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

    lignes += ["", "Séances du planning (3 derniers jours et 7 prochains) :"]
    debut = datetime.combine(aujourd_hui - timedelta(days=3), time.min)
    fin = datetime.combine(aujourd_hui + timedelta(days=8), time.min)
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
        raise ValueError(f"Matière inconnue : « {nom} ».")
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
        if a.get("matiere"):
            matiere_id = _matiere(base, a.get("matiere")).id
        jour_unique = _date(a["date"]) if a.get("date") else None
        jour_semaine = None
        if jour_unique is None:
            if str(a.get("jour", "")).lower() not in JOURS:
                raise ValueError("Indiquez une date ou un jour de la semaine.")
            jour_semaine = JOURS.index(str(a["jour"]).lower())
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
    return "Recalculer le planning"


def preparer(base: Base, appels) -> tuple[list[Action], list[str]]:
    actions, erreurs = [], []
    for appel in appels:
        try:
            actions.append(Action(appel.nom, appel.arguments, decrire(base, appel.nom, appel.arguments)))
        except (ValueError, TypeError, KeyError) as erreur:
            erreurs.append(f"Proposition ignorée ({appel.nom}) : {erreur}")
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
    elif action.nom == "regenerer_planning":
        from ..ui.calendrier import enregistrer_resultat, generer

        resultat = generer(base, maintenant)
        enregistrer_resultat(base, resultat)
        return "Planning recalculé" + ("" if resultat.faisable else " — attention, tout ne tient pas")
    return "Fait : " + action.description[0].lower() + action.description[1:]


# --- Conversation ---------------------------------------------------------------


def preparer_envoi(base: Base, historique: list[tuple[str, str]], message: str,
                   maintenant: datetime | None = None) -> str:
    """Texte complet envoyé à Gemini (à construire dans le fil principal : il lit la base)."""
    maintenant = maintenant or datetime.now()
    morceaux = ["Données du planificateur :", contexte(base, maintenant), ""]
    if historique:
        morceaux.append("Échanges précédents :")
        for qui, texte in historique[-8:]:
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
    if not texte and not actions:
        raise ErreurGemini("Gemini n'a rien répondu. Reformulez votre demande.")
    return texte, actions, erreurs


def repondre(client: ClientGemini, base: Base, historique: list[tuple[str, str]], message: str,
             maintenant: datetime | None = None) -> tuple[str, list[Action], list[str]]:
    """Envoie la question avec le contexte ; renvoie (texte, actions proposées, erreurs)."""
    reponse = demander(client, preparer_envoi(base, historique, message, maintenant))
    return interpreter_reponse(base, reponse)
