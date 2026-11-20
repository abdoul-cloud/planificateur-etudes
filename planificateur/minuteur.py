"""Minuteur de séance : on lance une séance, on fait des pauses, et elle se pointe toute seule à la fin.

L'état est enregistré dans la base : si l'application est fermée pendant une séance, le minuteur
reprend à la réouverture (le temps écoulé entre-temps compte comme du travail, sauf en pause).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from . import modeles as m
from .base import Base
from .suivi import marquer

PARAMETRE = "minuteur"
CONCENTRATION_MIN = 25  # une pause est proposée toutes les 25 minutes de travail
PAUSE_MIN = 5
MINIMUM_POINTE = 5  # en dessous, rien n'est pointé
SEUIL_FAITE = 0.9  # 90 % du temps prévu = séance faite


@dataclass
class EtatMinuteur:
    seance_id: int
    debut: datetime
    pauses_secondes: int = 0  # total des pauses terminées
    pause_depuis: datetime | None = None  # en pause en ce moment
    pauses_proposees: int = 0  # nombre de rappels de pause déjà faits
    fin_annoncee: bool = False

    # --- Mesures --------------------------------------------------------------------

    def en_pause(self) -> bool:
        return self.pause_depuis is not None

    def secondes_travaillees(self, maintenant: datetime) -> int:
        total = (maintenant - self.debut).total_seconds() - self.pauses_secondes
        if self.pause_depuis is not None:
            total -= (maintenant - self.pause_depuis).total_seconds()
        return max(0, int(total))

    def minutes_travaillees(self, maintenant: datetime) -> int:
        return self.secondes_travaillees(maintenant) // 60

    # --- Actions --------------------------------------------------------------------

    def mettre_en_pause(self, maintenant: datetime) -> None:
        if self.pause_depuis is None:
            self.pause_depuis = maintenant

    def reprendre(self, maintenant: datetime) -> None:
        if self.pause_depuis is not None:
            self.pauses_secondes += int((maintenant - self.pause_depuis).total_seconds())
            self.pause_depuis = None

    def pause_a_proposer(self, maintenant: datetime) -> bool:
        """Vrai une fois par tranche de 25 min de travail (jamais pendant une pause)."""
        if self.en_pause():
            return False
        tranches = self.minutes_travaillees(maintenant) // CONCENTRATION_MIN
        if tranches > self.pauses_proposees:
            self.pauses_proposees = tranches
            return True
        return False

    def fin_a_annoncer(self, seance: m.Seance, maintenant: datetime) -> bool:
        if not self.fin_annoncee and self.minutes_travaillees(maintenant) >= seance.minutes:
            self.fin_annoncee = True
            return True
        return False

    # --- Enregistrement -------------------------------------------------------------

    def vers_json(self) -> str:
        donnees = asdict(self)
        donnees["debut"] = self.debut.isoformat(timespec="seconds")
        donnees["pause_depuis"] = self.pause_depuis.isoformat(timespec="seconds") if self.pause_depuis else None
        return json.dumps(donnees)

    @classmethod
    def depuis_json(cls, texte: str) -> EtatMinuteur:
        donnees = json.loads(texte)
        donnees["debut"] = datetime.fromisoformat(donnees["debut"])
        if donnees.get("pause_depuis"):
            donnees["pause_depuis"] = datetime.fromisoformat(donnees["pause_depuis"])
        return cls(**donnees)


def charger(base: Base) -> EtatMinuteur | None:
    texte = base.parametre(PARAMETRE)
    if not texte:
        return None
    try:
        etat = EtatMinuteur.depuis_json(texte)
    except (ValueError, KeyError, TypeError):
        base.supprimer_parametre(PARAMETRE)
        return None
    if base.seances.obtenir(etat.seance_id) is None:  # séance supprimée entre-temps
        base.supprimer_parametre(PARAMETRE)
        return None
    return etat


def enregistrer(base: Base, etat: EtatMinuteur | None) -> None:
    if etat is None:
        base.supprimer_parametre(PARAMETRE)
    else:
        base.definir_parametre(PARAMETRE, etat.vers_json())


def demarrer(base: Base, seance: m.Seance, maintenant: datetime) -> EtatMinuteur:
    etat = EtatMinuteur(seance.id, maintenant.replace(microsecond=0))
    enregistrer(base, etat)
    return etat


def statut_final(seance: m.Seance, minutes: int) -> tuple[m.StatutSeance, int] | None:
    """Ce que le pointage automatique enregistrera, ou None si trop court pour compter."""
    if minutes < MINIMUM_POINTE:
        return None
    if minutes >= seance.minutes * SEUIL_FAITE:
        return m.StatutSeance.TERMINEE, minutes
    return m.StatutSeance.PARTIELLE, min(minutes, seance.minutes - 1)


def terminer(base: Base, etat: EtatMinuteur, maintenant: datetime) -> tuple[m.Seance | None, int]:
    """Arrête le minuteur et pointe la séance d'après le temps réellement travaillé."""
    etat.reprendre(maintenant)
    minutes = etat.minutes_travaillees(maintenant)
    enregistrer(base, None)
    seance = base.seances.obtenir(etat.seance_id)
    if seance is None:
        return None, minutes
    decision = statut_final(seance, minutes)
    if decision is None:
        return None, minutes
    statut, compte = decision
    return marquer(base, seance, statut, compte), minutes


def annuler(base: Base) -> None:
    enregistrer(base, None)


def seance_a_lancer(base: Base, maintenant: datetime) -> m.Seance | None:
    """Séance en cours, sinon la prochaine du jour (au plus 2 h avant), encore « prévue »."""
    fin_jour = datetime.combine(maintenant.date(), datetime.max.time())
    candidates = [s for s in base.seances.lister() if s.statut is m.StatutSeance.PREVUE
                  and s.fin > maintenant and s.debut <= fin_jour and s.debut.date() == maintenant.date()]
    candidates.sort(key=lambda s: s.debut)
    for s in candidates:
        if s.debut <= maintenant or s.debut - maintenant <= timedelta(hours=2):
            return s
    return None


def texte_duree(secondes: int) -> str:
    heures, reste = divmod(max(0, secondes), 3600)
    minutes, secondes = divmod(reste, 60)
    return f"{heures}:{minutes:02d}:{secondes:02d}" if heures else f"{minutes:02d}:{secondes:02d}"
