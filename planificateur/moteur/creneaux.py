"""Calcul des créneaux libres (cahier des charges, phase 2).

Principe : pour chaque jour travaillé, on part de la plage
[début de journée, fin de journée] et on en retire tout ce qui est occupé
(activités fixes avec leurs marges, épreuves, séances déjà placées).
Les trous restants, alignés sur une grille de 15 minutes et assez longs pour
une séance, sont les créneaux libres.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..modeles import ActiviteFixe, Epreuve, ExceptionActivite, Preferences, Seance

GRILLE_MIN = 15


@dataclass(frozen=True, order=True)
class Intervalle:
    debut: datetime
    fin: datetime

    @property
    def minutes(self) -> int:
        return int((self.fin - self.debut).total_seconds() // 60)

    def chevauche(self, autre: Intervalle) -> bool:
        return self.debut < autre.fin and autre.debut < self.fin


def _jours(du: date, au: date) -> Iterable[date]:
    for n in range((au - du).days + 1):
        yield du + timedelta(days=n)


def _arrondir(instant: datetime, vers_le_haut: bool) -> datetime:
    base = instant.replace(
        minute=instant.minute - instant.minute % GRILLE_MIN, second=0, microsecond=0
    )
    if vers_le_haut and base < instant:
        base += timedelta(minutes=GRILLE_MIN)
    return base


def fusionner(intervalles: Iterable[Intervalle]) -> list[Intervalle]:
    """Trie et réunit les intervalles qui se touchent ou se chevauchent."""
    resultat: list[Intervalle] = []
    for i in sorted(intervalles):
        if resultat and i.debut <= resultat[-1].fin:
            if i.fin > resultat[-1].fin:
                resultat[-1] = Intervalle(resultat[-1].debut, i.fin)
        else:
            resultat.append(i)
    return resultat


def occurrences(
    activites: Iterable[ActiviteFixe],
    du: date,
    au: date,
    exceptions: Iterable[ExceptionActivite] = (),
) -> list[tuple[ActiviteFixe, Intervalle]]:
    """Occurrences datées des activités fixes entre deux dates incluses.

    L'intervalle renvoyé est l'horaire réel, sans les marges.
    """
    annulees = {(e.activite_id, e.date) for e in exceptions}
    resultat = []
    for jour in _jours(du, au):
        for a in activites:
            if a.recurrente:
                if a.jour_semaine != jour.weekday():
                    continue
                if a.valide_du and jour < a.valide_du:
                    continue
                if a.valide_au and jour > a.valide_au:
                    continue
                if (a.id, jour) in annulees:
                    continue
            elif a.date != jour:
                continue
            resultat.append(
                (
                    a,
                    Intervalle(
                        datetime.combine(jour, a.heure_debut),
                        datetime.combine(jour, a.heure_fin),
                    ),
                )
            )
    return resultat


def periodes_occupees(
    du: date,
    au: date,
    activites: Iterable[ActiviteFixe] = (),
    exceptions: Iterable[ExceptionActivite] = (),
    epreuves: Iterable[Epreuve] = (),
    seances: Iterable[Seance] = (),
) -> list[Intervalle]:
    """Tout ce qui bloque le calendrier, marges de déplacement comprises."""
    occupes = [
        Intervalle(
            i.debut - timedelta(minutes=a.marge_avant_min),
            i.fin + timedelta(minutes=a.marge_apres_min),
        )
        for a, i in occurrences(activites, du, au, exceptions)
    ]
    occupes += [Intervalle(e.debut, e.fin) for e in epreuves]
    occupes += [Intervalle(s.debut, s.fin) for s in seances]
    return fusionner(occupes)


def creneaux_libres(
    du: date,
    au: date,
    preferences: Preferences,
    activites: Iterable[ActiviteFixe] = (),
    exceptions: Iterable[ExceptionActivite] = (),
    epreuves: Iterable[Epreuve] = (),
    seances: Iterable[Seance] = (),
    a_partir_de: datetime | None = None,
) -> list[Intervalle]:
    """Créneaux utilisables pour des séances, du `du` au `au` inclus.

    - Les repas définis dans les préférences sont bloqués chaque jour.
    - `seances` : séances déjà placées à préserver (terminées, verrouillées…).
    - `a_partir_de` : rien n'est proposé avant cet instant (« maintenant »).
    - Les créneaux plus courts que la durée minimale de séance sont écartés.
    """
    repas = [
        Intervalle(datetime.combine(jour, debut), datetime.combine(jour, fin))
        for jour in _jours(du, au)
        for debut, fin in preferences.repas
    ]
    occupes = fusionner(
        [*periodes_occupees(du, au, activites, exceptions, epreuves, seances), *repas]
    )
    libres: list[Intervalle] = []

    for jour in _jours(du, au):
        if jour.weekday() in preferences.jours_repos:
            continue
        curseur = datetime.combine(jour, preferences.debut_journee)
        fin_journee = datetime.combine(jour, preferences.fin_journee)
        if a_partir_de is not None:
            curseur = max(curseur, a_partir_de)

        bornes = [o for o in occupes if o.fin > curseur and o.debut < fin_journee]
        for occupe in [*bornes, Intervalle(fin_journee, fin_journee)]:
            debut = _arrondir(curseur, vers_le_haut=True)
            fin = _arrondir(min(occupe.debut, fin_journee), vers_le_haut=False)
            if (fin - debut) >= timedelta(minutes=preferences.duree_min_seance):
                libres.append(Intervalle(debut, fin))
            curseur = max(curseur, occupe.fin)

    return libres
