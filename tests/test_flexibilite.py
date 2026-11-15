"""Horaires flexibles : réglage par jour, repos, indisponibilités, préférences."""

from datetime import date, datetime, time

import pytest

from planificateur import modeles as m
from planificateur.base import Base
from planificateur.moteur.creneaux import (
    EVITEE,
    NEUTRE,
    PREFEREE,
    Intervalle,
    creneaux_libres,
    niveau_preference,
)

LUNDI = date(2026, 11, 16)
MERCREDI = date(2026, 11, 18)
SAMEDI = date(2026, 11, 21)
DIMANCHE = date(2026, 11, 22)


def h(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute))


def test_samedi_avec_ses_propres_horaires():
    samedi = m.ReglageJour(
        debut=time(9), fin=time(17), max_minutes=180,
        pauses=[m.Plage(time(12, 30), time(14), "Déjeuner")],
    )
    prefs = m.Preferences(reglages_jour={5: samedi})
    assert creneaux_libres(SAMEDI, SAMEDI, prefs) == [
        Intervalle(h(SAMEDI, 9), h(SAMEDI, 12, 30)),
        Intervalle(h(SAMEDI, 14), h(SAMEDI, 17)),
    ]
    # Les autres jours gardent le réglage général (7 h – 23 h, repas 12 h et 18 h).
    assert creneaux_libres(LUNDI, LUNDI, prefs)[0] == Intervalle(h(LUNDI, 7), h(LUNDI, 12))


def test_dimanche_jour_de_repos():
    prefs = m.Preferences(reglages_jour={6: m.ReglageJour(travaille=False)})
    assert creneaux_libres(DIMANCHE, DIMANCHE, prefs) == []


def test_limite_zero_equivaut_a_un_jour_sans_travail():
    prefs = m.Preferences(reglages_jour={6: m.ReglageJour(max_minutes=0)})
    assert creneaux_libres(DIMANCHE, DIMANCHE, prefs) == []


def test_mercredi_apres_midi_de_repos_chaque_semaine():
    mercredi = m.ReglageJour(
        pauses=[m.Plage(time(12), time(13), "Déjeuner"), m.Plage(time(14), time(23), "Repos")]
    )
    prefs = m.Preferences(reglages_jour={2: mercredi})
    assert creneaux_libres(MERCREDI, MERCREDI, prefs) == [
        Intervalle(h(MERCREDI, 7), h(MERCREDI, 12)),
        Intervalle(h(MERCREDI, 13), h(MERCREDI, 14)),
    ]


def test_sieste_ajoutee_au_reglage_general():
    prefs = m.Preferences(
        pauses_quotidiennes=[
            m.Plage(time(12), time(13), "Déjeuner"),
            m.Plage(time(13), time(14), "Sieste"),
            m.Plage(time(18), time(19), "Dîner"),
        ]
    )
    assert Intervalle(h(LUNDI, 14), h(LUNDI, 18)) in creneaux_libres(LUNDI, LUNDI, prefs)


def test_soiree_indisponible_ponctuelle():
    sortie = m.ActiviteFixe(
        "Anniversaire", time(19), time(23), type=m.TypeActivite.PERSONNEL, date=SAMEDI
    )
    prefs = m.Preferences()
    libres = creneaux_libres(SAMEDI, SAMEDI, prefs, [sortie])
    assert all(l.fin <= h(SAMEDI, 18) for l in libres)
    # La semaine suivante n'est pas touchée.
    samedi_suivant = date(2026, 11, 28)
    assert creneaux_libres(samedi_suivant, samedi_suivant, prefs, [sortie])[-1] == Intervalle(
        h(samedi_suivant, 19), h(samedi_suivant, 23)
    )


def test_journee_entiere_indisponible():
    conge = m.ActiviteFixe(
        "Journée en famille", time(0), time(23, 59), type=m.TypeActivite.PERSONNEL, date=SAMEDI
    )
    assert creneaux_libres(SAMEDI, SAMEDI, m.Preferences(), [conge]) == []


def test_niveaux_de_preference():
    prefs = m.Preferences(
        plages_preferees=[m.PlageHebdo([0, 1, 2, 3, 4], time(19), time(22))],
        plages_evitees=[m.PlageHebdo([0, 1, 2, 3, 4], time(21, 30), time(23))],
        plages_garanties=[],
    )
    assert niveau_preference(Intervalle(h(LUNDI, 19), h(LUNDI, 20, 30)), prefs) == PREFEREE
    assert niveau_preference(Intervalle(h(LUNDI, 15), h(LUNDI, 16)), prefs) == NEUTRE
    # Déborde de la plage préférée : neutre.
    assert niveau_preference(Intervalle(h(LUNDI, 18, 30), h(LUNDI, 19, 30)), prefs) == NEUTRE
    # Touche une plage évitée : évitée, même si elle est aussi préférée.
    assert niveau_preference(Intervalle(h(LUNDI, 20, 30), h(LUNDI, 22)), prefs) == EVITEE
    # Le samedi n'est concerné par aucune des deux plages.
    assert niveau_preference(Intervalle(h(SAMEDI, 21, 30), h(SAMEDI, 23)), prefs) == NEUTRE


def test_toutes_les_preferences_survivent_a_l_enregistrement(tmp_path):
    prefs = m.Preferences(
        duree_min_seance=30,
        pauses_quotidiennes=[m.Plage(time(12, 15), time(13, 15), "Déjeuner")],
        reglages_jour={
            5: m.ReglageJour(debut=time(9), fin=time(17), max_minutes=180, pauses=[]),
            6: m.ReglageJour(travaille=False),
        },
        plages_preferees=[m.PlageHebdo([0, 2, 4], time(19), time(22))],
        plages_evitees=[m.PlageHebdo([5, 6], time(7), time(9))],
    )
    base = Base(tmp_path / "prefs.db")
    base.enregistrer_preferences(prefs)
    base.fermer()
    base = Base(tmp_path / "prefs.db")
    assert base.preferences() == prefs
    base.fermer()


@pytest.mark.parametrize(
    "fabrique",
    [
        lambda: m.Plage(time(14), time(13)),
        lambda: m.ReglageJour(debut=time(20), fin=time(8)),
        lambda: m.ReglageJour(max_minutes=-10),
        lambda: m.PlageHebdo([7], time(8), time(9)),
        lambda: m.PlageHebdo([], time(8), time(9)),
        lambda: m.Preferences(reglages_jour={7: m.ReglageJour()}),
    ],
)
def test_reglages_invalides_refuses(fabrique):
    with pytest.raises(ValueError):
        fabrique()
