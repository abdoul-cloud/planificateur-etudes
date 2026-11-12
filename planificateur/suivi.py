"""Suivi des séances (cahier des charges, sections 5.6, 6.5 et 9).

- Pointer une séance : faite, faite en partie, manquée, ou remise à prévue.
- Le temps restant d'un travail à rendre suit ce qui a réellement été fait.
- Les épreuves passées sont marquées comme telles.
- Bilan d'une période : prévu, réalisé, manqué, par matière.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from . import modeles as m
from .base import Base


def minutes_faites(seance: m.Seance) -> int:
    """Temps réellement travaillé pendant une séance pointée."""
    if seance.statut is m.StatutSeance.TERMINEE:
        return seance.minutes_effectuees if seance.minutes_effectuees is not None else seance.minutes
    if seance.statut is m.StatutSeance.PARTIELLE:
        return seance.minutes_effectuees or 0
    return 0


def marquer(base: Base, seance: m.Seance, statut: m.StatutSeance, minutes: int | None = None) -> m.Seance:
    """Change le statut d'une séance et répercute le temps fait sur son travail.

    - TERMINEE : `minutes` facultatif (par défaut, la durée prévue).
    - PARTIELLE : `minutes` obligatoire, entre 1 et la durée prévue − 1.
    - MANQUEE / PREVUE : aucun temps compté.
    Une séance pointée n'est plus déplacée par le recalcul.
    """
    if statut is m.StatutSeance.TERMINEE:
        minutes = seance.minutes if minutes is None else minutes
        if minutes <= 0:
            raise ValueError("Le temps effectué doit être positif")
    elif statut is m.StatutSeance.PARTIELLE:
        if minutes is None or not 0 < minutes < seance.minutes:
            raise ValueError(f"Indiquez un temps entre 1 et {seance.minutes - 1} minutes")
    else:
        minutes = None

    avant = minutes_faites(seance)
    nouvelle = replace(seance, statut=statut, minutes_effectuees=minutes)
    base.seances.modifier(nouvelle)

    if seance.travail_id is not None:
        travail = base.travaux.obtenir(seance.travail_id)
        if travail is not None:
            ecart = minutes_faites(nouvelle) - avant
            travail.minutes_restantes = max(0, min(travail.minutes_estimees, travail.minutes_restantes - ecart))
            if travail.etat is not m.EtatTravail.RENDU:
                if travail.minutes_restantes == 0:
                    travail.etat = m.EtatTravail.TERMINE
                elif travail.minutes_restantes < travail.minutes_estimees:
                    travail.etat = m.EtatTravail.EN_COURS
                else:
                    travail.etat = m.EtatTravail.A_FAIRE
            base.travaux.modifier(travail)
    return nouvelle


def mettre_a_jour_etats(base: Base, maintenant: datetime | None = None) -> int:
    """Marque « passée » toute épreuve terminée. Renvoie le nombre de changements."""
    maintenant = maintenant or datetime.now()
    changements = 0
    for epreuve in base.epreuves.lister():
        if epreuve.fin <= maintenant and epreuve.etat is not m.EtatEpreuve.PASSEE:
            epreuve.etat = m.EtatEpreuve.PASSEE
            base.epreuves.modifier(epreuve)
            changements += 1
    return changements


def a_pointer(base: Base, maintenant: datetime | None = None, jours: int = 7) -> list[m.Seance]:
    """Séances terminées dans le temps mais pas encore pointées (les plus récentes d'abord)."""
    maintenant = maintenant or datetime.now()
    depuis = (maintenant - timedelta(days=jours)).isoformat(timespec="minutes")
    seances = base.seances.lister(
        "statut = ? AND fin <= ? AND fin >= ?",
        (m.StatutSeance.PREVUE.value, maintenant.isoformat(timespec="minutes"), depuis),
        ordre="debut DESC",
    )
    return seances


@dataclass
class LigneBilan:
    prevu: int = 0
    fait: int = 0
    manque: int = 0


@dataclass
class Bilan:
    du: date
    au: date
    prevu: int = 0  # minutes prévues sur la période, séances manquées comprises
    fait: int = 0
    manque: int = 0
    a_venir: int = 0  # séances prévues pas encore passées
    non_pointe: int = 0  # séances passées pas encore pointées
    par_matiere: dict[int | None, LigneBilan] = field(default_factory=dict)
    manquees: list[m.Seance] = field(default_factory=list)

    @property
    def taux(self) -> float | None:
        """Part du temps réalisé sur le temps prévu des séances passées et pointées."""
        pointe = self.prevu - self.a_venir - self.non_pointe
        return None if pointe <= 0 else min(1.0, self.fait / pointe)


def bilan(base: Base, du: date, au: date, maintenant: datetime | None = None) -> Bilan:
    maintenant = maintenant or datetime.now()
    seances = base.seances.lister(
        "debut >= ? AND debut < ?",
        (datetime.combine(du, time.min).isoformat(timespec="minutes"),
         datetime.combine(au + timedelta(days=1), time.min).isoformat(timespec="minutes")),
        ordre="debut",
    )
    resultat = Bilan(du, au)
    lignes: dict[int | None, LigneBilan] = defaultdict(LigneBilan)
    for s in seances:
        if s.statut is m.StatutSeance.REPORTEE:
            continue
        ligne = lignes[s.matiere_id]
        resultat.prevu += s.minutes
        ligne.prevu += s.minutes
        fait = minutes_faites(s)
        resultat.fait += fait
        ligne.fait += fait
        if s.statut is m.StatutSeance.MANQUEE:
            resultat.manque += s.minutes
            ligne.manque += s.minutes
            resultat.manquees.append(s)
        elif s.statut is m.StatutSeance.PREVUE:
            if s.fin > maintenant:
                resultat.a_venir += s.minutes
            else:
                resultat.non_pointe += s.minutes
    resultat.par_matiere = dict(lignes)
    return resultat
