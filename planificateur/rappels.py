"""Rappels : avant une séance, la veille d'une épreuve, avant un travail à rendre, point du soir.

Logique pure (sans interface) : on calcule les rappels dus à un instant
donné ; l'interface les affiche en notifications Windows. Entièrement hors
ligne.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, time, timedelta

from . import modeles as m
from .base import Base
from .suivi import a_pointer

PARAMETRE_REGLAGES = "rappels"
PARAMETRE_ENVOYES = "rappels_envoyes"
GRACE = timedelta(minutes=20)  # un rappel manqué de plus de 20 min n'est plus envoyé (pas d'avalanche au démarrage)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TYPES_SEANCE = {m.TypeSeance.REVISION: "Révision", m.TypeSeance.PREPARATION: "Préparation",
                m.TypeSeance.TRAVAIL: "Travail"}
TYPES_EPREUVE = {m.TypeEpreuve.INTERROGATION: "Interrogation", m.TypeEpreuve.DEVOIR_SURVEILLE: "Devoir surveillé",
                 m.TypeEpreuve.COMPOSITION: "Composition", m.TypeEpreuve.EXAMEN: "Examen"}


@dataclass
class ReglagesRappels:
    actif: bool = True
    seance_minutes: int = 10  # avant chaque séance ; 0 = pas de rappel
    veille_epreuve: bool = True
    heure_veille: time = time(19, 0)
    travail_jours: int = 2  # jours avant l'échéance ; 0 = pas de rappel
    heure_travail: time = time(18, 0)
    bilan_soir: bool = True
    heure_bilan: time = time(22, 30)
    arriere_plan: bool = True  # fermer la fenêtre laisse l'application près de l'horloge


@dataclass(frozen=True)
class Rappel:
    cle: str  # identifiant unique, pour ne jamais envoyer deux fois le même rappel
    titre: str
    texte: str
    ecran: str = "Planning"  # écran ouvert quand on clique sur la notification


def charger(base: Base) -> ReglagesRappels:
    brut = base.parametre(PARAMETRE_REGLAGES)
    if not brut:
        return ReglagesRappels()
    donnees = json.loads(brut)
    reglages = ReglagesRappels()
    for champ in fields(ReglagesRappels):
        if champ.name not in donnees:
            continue
        valeur = donnees[champ.name]
        defaut = getattr(reglages, champ.name)
        if isinstance(defaut, time):
            valeur = time.fromisoformat(valeur)
        elif isinstance(defaut, bool):
            valeur = bool(valeur)
        setattr(reglages, champ.name, valeur)
    return reglages


def enregistrer(base: Base, reglages: ReglagesRappels) -> None:
    donnees = {k: (v.strftime("%H:%M") if isinstance(v, time) else v) for k, v in asdict(reglages).items()}
    base.definir_parametre(PARAMETRE_REGLAGES, json.dumps(donnees))


def deja_envoyes(base: Base) -> set[str]:
    brut = base.parametre(PARAMETRE_ENVOYES)
    return set(json.loads(brut).keys()) if brut else set()


def marquer_envoyes(base: Base, cles: list[str], maintenant: datetime) -> None:
    """Retient les rappels envoyés (les 3 derniers jours suffisent)."""
    brut = base.parametre(PARAMETRE_ENVOYES)
    envoyes = json.loads(brut) if brut else {}
    limite = (maintenant - timedelta(days=3)).isoformat()
    envoyes = {cle: quand for cle, quand in envoyes.items() if quand >= limite}
    for cle in cles:
        envoyes[cle] = maintenant.isoformat()
    base.definir_parametre(PARAMETRE_ENVOYES, json.dumps(envoyes))


def _duree(minutes: int) -> str:
    heures, reste = divmod(int(minutes), 60)
    return f"{reste} min" if not heures else (f"{heures} h {reste:02d}" if reste else f"{heures} h")


def rappels_dus(base: Base, maintenant: datetime, reglages: ReglagesRappels | None = None,
                deja: set[str] | None = None) -> list[Rappel]:
    """Rappels à envoyer maintenant (et pas encore envoyés)."""
    reglages = reglages or charger(base)
    deja = deja_envoyes(base) if deja is None else deja
    if not reglages.actif:
        return []

    def du(instant: datetime) -> bool:
        return instant <= maintenant < instant + GRACE

    matieres = {x.id: x.nom for x in base.matieres.lister()}
    rappels: list[Rappel] = []

    if reglages.seance_minutes > 0:
        avance = timedelta(minutes=reglages.seance_minutes)
        fenetre = (maintenant.isoformat(timespec="minutes"), (maintenant + avance + GRACE).isoformat(timespec="minutes"))
        for s in base.seances.lister("statut = ? AND debut >= ? AND debut <= ?",
                                     (m.StatutSeance.PREVUE.value, *fenetre), ordre="debut"):
            if du(s.debut - avance):
                matiere = matieres.get(s.matiere_id, "")
                rappels.append(Rappel(
                    f"seance:{s.id}:{s.debut.isoformat(timespec='minutes')}",
                    f"Séance dans {reglages.seance_minutes} min" if reglages.seance_minutes < 60 else "Séance bientôt",
                    f"{TYPES_SEANCE[s.type]} de {matiere} à {s.debut:%H:%M} ({_duree(s.minutes)})".replace(" de  à", " à"),
                    "Planning",
                ))

    if reglages.veille_epreuve:
        for e in base.epreuves.lister("debut >= ?", (maintenant.isoformat(timespec="minutes"),), ordre="debut"):
            veille = datetime.combine(e.debut.date() - timedelta(days=1), reglages.heure_veille)
            if du(veille):
                rappels.append(Rappel(
                    f"epreuve:{e.id}:{e.debut.date().isoformat()}",
                    "Épreuve demain",
                    f"{TYPES_EPREUVE[e.type]} de {matieres.get(e.matiere_id, '')} demain à {e.debut:%H:%M}. "
                    "Une dernière révision légère, puis du repos !",
                    "Épreuves",
                ))

    if reglages.travail_jours > 0:
        for t in base.travaux.lister("echeance >= ?", (maintenant.isoformat(timespec="minutes"),), ordre="echeance"):
            if t.etat in (m.EtatTravail.TERMINE, m.EtatTravail.RENDU):
                continue
            instant = datetime.combine(t.echeance.date() - timedelta(days=reglages.travail_jours), reglages.heure_travail)
            if du(instant):
                pluriel = "s" if reglages.travail_jours > 1 else ""
                rappels.append(Rappel(
                    f"travail:{t.id}:{t.echeance.date().isoformat()}",
                    f"À rendre dans {reglages.travail_jours} jour{pluriel}",
                    f"« {t.intitule} » pour {JOURS[t.echeance.weekday()]} {t.echeance:%H:%M} — "
                    f"il reste environ {_duree(t.minutes_restantes)} de travail.",
                    "Travaux à rendre",
                ))

    if reglages.bilan_soir:
        instant = datetime.combine(maintenant.date(), reglages.heure_bilan)
        if du(instant):
            du_jour = [s for s in a_pointer(base, maintenant, jours=1) if s.debut.date() == maintenant.date()]
            if du_jour:
                rappels.append(Rappel(
                    f"bilan:{maintenant.date().isoformat()}",
                    "Point du soir",
                    f"{len(du_jour)} séance{'s' if len(du_jour) > 1 else ''} d'aujourd'hui à pointer : "
                    "faite, en partie ou manquée ?",
                    "Accueil",
                ))

    return [r for r in rappels if r.cle not in deja]


def prochaine_seance(base: Base, maintenant: datetime) -> m.Seance | None:
    seances = base.seances.lister("statut = ? AND debut >= ?",
                                  (m.StatutSeance.PREVUE.value, maintenant.isoformat(timespec="minutes")), ordre="debut")
    return seances[0] if seances else None

