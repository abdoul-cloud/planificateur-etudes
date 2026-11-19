"""Conseils du Bilan, tirés des séances réellement pointées (4 dernières semaines).

Chaque conseil explique ce qui a été observé et, quand c'est utile, propose un réglage à appliquer d'un clic.
Rien n'est modifié sans l'accord de l'étudiant ; un conseil peut aussi être ignoré définitivement.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from typing import Callable

from . import modeles as m
from .base import Base

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
PERIODES = [("matin", time(5), time(12)), ("après-midi", time(12), time(18)), ("soir", time(18), time(23, 59))]
FENETRE_JOURS = 28
MINIMUM_SEANCES = 6  # en dessous, trop peu de recul pour conseiller
PARAMETRE_IGNORES = "conseils_ignores"

POINTEES = (m.StatutSeance.TERMINEE, m.StatutSeance.PARTIELLE, m.StatutSeance.MANQUEE)


@dataclass
class Conseil:
    cle: str  # identifiant stable, pour « Ne plus proposer »
    titre: str
    texte: str
    ton: str = "info"  # « info », « attention » ou « bravo »
    action: str = ""  # libellé du bouton, vide si rien à appliquer
    appliquer: Callable[[Base], str] | None = field(default=None, repr=False)  # renvoie un message de confirmation
    ecran: str = ""  # sinon, écran à ouvrir


def _periode(instant: datetime) -> int:
    for n, (_, debut, fin) in enumerate(PERIODES):
        if debut <= instant.time() < fin:
            return n
    return 0


def _pluriel(n: int, mot: str) -> str:
    return f"{n} {mot}{'s' if n > 1 else ''}"


def ignores(base: Base) -> set[str]:
    try:
        return set(json.loads(base.parametre(PARAMETRE_IGNORES) or "[]"))
    except ValueError:
        return set()


def ignorer(base: Base, cle: str) -> None:
    base.definir_parametre(PARAMETRE_IGNORES, json.dumps(sorted(ignores(base) | {cle})))


# --- Réglages appliqués -------------------------------------------------------------------------


def _eviter_creneau(jour: int, debut: time, fin: time) -> Callable[[Base], str]:
    def appliquer(base: Base) -> str:
        preferences = base.preferences()
        retire = False
        garanties = []
        for plage in preferences.plages_garanties:  # une soirée garantie serait remplie quand même
            if jour in plage.jours and plage.debut < fin and debut < plage.fin:
                retire = True
                jours = [j for j in plage.jours if j != jour]
                if jours:
                    garanties.append(replace(plage, jours=jours))
            else:
                garanties.append(plage)
        preferences.plages_garanties = garanties
        preferences.plages_evitees = preferences.plages_evitees + [m.PlageHebdo([jour], debut, fin)]
        base.enregistrer_preferences(preferences)
        message = f"Le {JOURS[jour]} de {debut:%H:%M} à {fin:%H:%M} est maintenant « à éviter »"
        return message + (" et n'est plus garanti." if retire else ".") + " Recalculez le planning pour l'appliquer."
    return appliquer


def _reduire_budget(minutes: int) -> Callable[[Base], str]:
    def appliquer(base: Base) -> str:
        preferences = base.preferences()
        preferences.minutes_revision_semaine = minutes
        base.enregistrer_preferences(preferences)
        return f"Révisions régulières ramenées à {minutes // 60} h {minutes % 60:02d} par semaine."
    return appliquer


def _raccourcir_seances(minutes: int) -> Callable[[Base], str]:
    def appliquer(base: Base) -> str:
        preferences = base.preferences()
        preferences.duree_max_seance = minutes
        preferences.duree_min_seance = min(preferences.duree_min_seance, minutes)
        base.enregistrer_preferences(preferences)
        return f"Les séances dureront au plus {minutes} min. Recalculez le planning pour l'appliquer."
    return appliquer


# --- Analyse ----------------------------------------------------------------------------------


def conseils(base: Base, maintenant: datetime | None = None, avec_ignores: bool = False) -> list[Conseil]:
    maintenant = maintenant or datetime.now()
    depuis = maintenant - timedelta(days=FENETRE_JOURS)
    passees = [s for s in base.seances.lister() if depuis <= s.debut and s.fin <= maintenant]
    pointees = [s for s in passees if s.statut in POINTEES]
    resultat: list[Conseil] = []

    non_pointees = [s for s in passees if s.statut is m.StatutSeance.PREVUE]
    if len(non_pointees) >= 5:
        resultat.append(Conseil(
            "pointer", f"{_pluriel(len(non_pointees), 'séance')} à pointer",
            "Sans pointage, le bilan et ces conseils ne reflètent pas ce que vous avez vraiment fait. "
            "Un clic par séance suffit (faite, en partie, manquée), depuis l'Accueil ou le Planning.",
            "attention", ecran="Accueil"))

    if len(pointees) < MINIMUM_SEANCES:
        resultat.append(Conseil(
            "attente", "Des conseils bientôt",
            f"Ils apparaîtront après quelques séances pointées ({len(pointees)} sur {MINIMUM_SEANCES} pour l'instant) : "
            "créneaux souvent manqués, séances trop longues, rythme trop chargé…"))
        return _filtrer(base, resultat, avec_ignores)

    # 1. Créneaux souvent manqués (même jour, même moment de la journée)
    groupes: dict[tuple[int, int], list[m.Seance]] = defaultdict(list)
    for s in pointees:
        groupes[(s.debut.weekday(), _periode(s.debut))].append(s)
    for (jour, periode), seances in sorted(groupes.items()):
        manquees = [s for s in seances if s.statut is m.StatutSeance.MANQUEE]
        if len(seances) >= 3 and len(manquees) >= 2 and len(manquees) / len(seances) >= 0.6:
            debut = min(s.debut.time() for s in manquees).replace(minute=0)
            fin_max = max(s.fin for s in manquees)
            heure_fin = fin_max.hour + (1 if fin_max.minute else 0)  # arrondie à l'heure supérieure
            fin = time(heure_fin) if heure_fin < 24 else time(23, 59)
            nom = f"{JOURS[jour]} {PERIODES[periode][0]}"
            resultat.append(Conseil(
                f"creneau:{jour}:{periode}", f"Le {nom}, ça coince",
                f"Vous avez manqué {len(manquees)} séances sur {len(seances)} le {nom} ces dernières semaines. "
                f"Mieux vaut éviter ce moment ({debut:%H:%M} – {fin:%H:%M}) et placer ces séances ailleurs.",
                "attention", f"Éviter le {JOURS[jour]} {debut:%H:%M} – {fin:%H:%M}", _eviter_creneau(jour, debut, fin)))

    # 2. Séances souvent faites en partie : trop longues ?
    partielles = [s for s in pointees if s.statut is m.StatutSeance.PARTIELLE and s.minutes_effectuees]
    if len(partielles) >= 3 and len(partielles) / len(pointees) >= 0.3:
        moyenne = sum(s.minutes_effectuees for s in partielles) / len(partielles)
        cible = max(30, int(moyenne // 15 * 15))
        if cible < base.preferences().duree_max_seance:
            resultat.append(Conseil(
                "duree", "Des séances un peu longues",
                f"{_pluriel(len(partielles), 'séance')} sur {len(pointees)} n'ont été faites qu'en partie, "
                f"en moyenne {round(moyenne)} min. Des séances plus courtes seraient plus faciles à tenir.",
                "info", f"Séances de {cible} min au plus", _raccourcir_seances(cible)))

    # 3. Rythme global
    faites = sum(1 for s in pointees if s.statut is m.StatutSeance.TERMINEE)
    taux = (faites + 0.5 * len(partielles)) / len(pointees)
    budget = base.preferences().minutes_revision_semaine
    if taux < 0.5 and budget > 120:
        nouveau = max(120, int(budget * 0.75) // 15 * 15)
        resultat.append(Conseil(
            "rythme", "Un rythme trop chargé ?",
            f"Seulement {round(100 * taux)} % des séances prévues ont été faites. Un planning plus léger mais "
            "tenu vaut mieux qu'un planning ambitieux qu'on abandonne.",
            "attention", f"Réviser {nouveau // 60} h {nouveau % 60:02d} par semaine", _reduire_budget(nouveau)))
    elif taux >= 0.85 and len(pointees) >= 10:
        resultat.append(Conseil(
            f"bravo:{maintenant:%Y-%W}", "Très régulier, bravo",
            f"{round(100 * taux)} % des séances faites sur les 4 dernières semaines. Continuez comme ça !", "bravo"))

    # 4. Matière souvent laissée de côté
    par_matiere: dict[int, list[m.Seance]] = defaultdict(list)
    for s in pointees:
        if s.matiere_id is not None:
            par_matiere[s.matiere_id].append(s)
    noms = {x.id: x.nom for x in base.matieres.lister()}
    for matiere_id, seances in par_matiere.items():
        manquees = sum(1 for s in seances if s.statut is m.StatutSeance.MANQUEE)
        if len(seances) >= 3 and manquees / len(seances) >= 0.6 and matiere_id in noms:
            resultat.append(Conseil(
                f"matiere:{matiere_id}", f"{noms[matiere_id]} laissée de côté",
                f"{manquees} séances manquées sur {len(seances)} en {noms[matiere_id]}. Si elle vous paraît difficile, "
                "indiquez-le (difficulté plus haute, maîtrise plus basse) : le planning lui donnera des séances "
                "plus courtes et mieux réparties.", "info", ecran="Matières"))

    if not [c for c in resultat if c.ton != "bravo" and c.cle != "pointer"] and not any(c.ton == "bravo" for c in resultat):
        resultat.append(Conseil("rien", "Rien à signaler",
                                "Votre planning semble bien adapté à votre rythme pour l'instant."))
    return _filtrer(base, resultat, avec_ignores)


def _filtrer(base: Base, liste: list[Conseil], avec_ignores: bool) -> list[Conseil]:
    if avec_ignores:
        return liste
    caches = ignores(base)
    return [c for c in liste if c.cle not in caches]
