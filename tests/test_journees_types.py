"""Journées types de l'utilisateur, avec les préférences par défaut.

Rythme : journée de 7 h à 23 h, déjeuner (repas + petite pause) de 12 h à 13 h,
dîner de 18 h à 19 h. Une séance dure au moins 45 minutes.
"""

from datetime import date, datetime, time

from planificateur import modeles as m
from planificateur.moteur.creneaux import Intervalle, creneaux_libres

LUNDI = date(2026, 11, 16)
PREFS = m.Preferences()


def h(heure: int, minute: int = 0) -> datetime:
    return datetime.combine(LUNDI, time(heure, minute))


def cours(debut: int, fin: int) -> m.ActiviteFixe:
    return m.ActiviteFixe("Cours", time(debut), time(fin), jour_semaine=0)


def test_cours_toute_la_journee_revision_le_soir_seulement():
    # Cours de 7 h à 18 h sans interruption.
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [cours(7, 18)])
    assert libres == [Intervalle(h(19), h(23))]


def test_cours_matin_et_apres_midi_revision_a_midi_et_le_soir():
    # Cours 7 h – 12 h et 14 h – 18 h : repas + pause de 12 h à 13 h,
    # révision de 13 h à 14 h, puis de 19 h à 23 h.
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [cours(7, 12), cours(14, 18)])
    assert libres == [Intervalle(h(13), h(14)), Intervalle(h(19), h(23))]


def test_journee_libre_revision_en_pleine_journee():
    libres = creneaux_libres(LUNDI, LUNDI, PREFS)
    assert libres == [
        Intervalle(h(7), h(12)),
        Intervalle(h(13), h(18)),
        Intervalle(h(19), h(23)),
    ]


def test_cours_le_matin_seulement_apres_midi_libre():
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [cours(7, 12)])
    assert libres == [Intervalle(h(13), h(18)), Intervalle(h(19), h(23))]


def test_cours_l_apres_midi_seulement_matin_libre():
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [cours(14, 18)])
    assert libres == [
        Intervalle(h(7), h(12)),
        Intervalle(h(13), h(14)),
        Intervalle(h(19), h(23)),
    ]


def test_aucune_revision_pendant_les_repas():
    libres = creneaux_libres(LUNDI, LUNDI, PREFS)
    repas = [Intervalle(h(12), h(13)), Intervalle(h(18), h(19))]
    assert not any(l.chevauche(r) for l in libres for r in repas)


def test_horaires_des_repas_modifiables():
    prefs = m.Preferences(dejeuner_debut=time(12, 30), dejeuner_fin=time(13, 30))
    libres = creneaux_libres(LUNDI, LUNDI, prefs, [cours(7, 12), cours(14, 18)])
    # Il ne reste que 30 minutes entre le déjeuner et le cours : trop court.
    assert libres == [Intervalle(h(19), h(23))]


def test_preferences_avec_repas_survivent_a_l_enregistrement(tmp_path):
    from planificateur.base import Base

    base = Base(tmp_path / "prefs.db")
    prefs = m.Preferences(diner_debut=time(18, 30), diner_fin=time(19, 15))
    base.enregistrer_preferences(prefs)
    assert base.preferences() == prefs
    sans_diner = m.Preferences(diner_debut=None, diner_fin=None)
    base.enregistrer_preferences(sans_diner)
    assert base.preferences() == sans_diner
    base.fermer()
