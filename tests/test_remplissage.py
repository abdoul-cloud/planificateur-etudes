"""Moments libres occupés en semaine et révision la veille du cours."""

from datetime import date, datetime, time, timedelta

from planificateur import modeles as m
from planificateur.base import Base
from planificateur.moteur.creneaux import Intervalle
from planificateur.moteur.placement import planifier

LUNDI = date(2026, 11, 16)
JOURS = [LUNDI + timedelta(days=n) for n in range(7)]
DIMANCHE = JOURS[-1]
MATHS = m.Matiere("Maths", coefficient=3, difficulte=3, maitrise=3, id=1)
PHYSIQUE = m.Matiere("Physique", coefficient=3, difficulte=3, maitrise=3, id=2)
MATIERES = [MATHS, PHYSIQUE]


def cours(nom, jour, debut, fin, matiere=None):
    return m.ActiviteFixe(nom, time(debut), time(fin), jour_semaine=jour, matiere_id=matiere.id if matiere else None)


# Cours de 7 h à 10 h et de 14 h à 16 h du lundi au vendredi : moments libres
# 10 h – 12 h, 13 h – 14 h, 16 h – 18 h, 19 h – 20 h, puis la soirée garantie.
SEMAINE = [cours("Cours", j, 7, 10) for j in range(5)] + [cours("TD", j, 14, 16) for j in range(5)]
MOMENTS = [(time(10), time(12)), (time(13), time(14)), (time(16), time(18)), (time(19), time(20))]


def dans(res, jour, debut, fin):
    zone = Intervalle(datetime.combine(jour, debut), datetime.combine(jour, fin))
    return [s for s in res.seances if Intervalle(s.debut, s.fin).chevauche(zone)]


def test_chaque_moment_libre_de_la_semaine_recoit_une_seance():
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), MATIERES, SEMAINE)
    for jour in JOURS[:5]:
        for debut, fin in MOMENTS:
            seances = dans(res, jour, debut, fin)
            assert len(seances) == 1, f"{jour} {debut}–{fin} : {len(seances)} séance(s)"
            assert seances[0].minutes <= 45  # sans entasser


def test_week_end_pas_rempli():
    res = planifier(LUNDI, DIMANCHE, m.Preferences(minutes_revision_semaine=0), MATIERES, SEMAINE)
    assert not [s for s in res.seances if s.debut.weekday() >= 5]


def test_duree_reglable():
    res = planifier(LUNDI, DIMANCHE, m.Preferences(remplissage_minutes=60), MATIERES, SEMAINE)
    assert dans(res, LUNDI, time(16), time(18))[0].minutes == 60


def test_jours_reglables():
    preferences = m.Preferences(remplissage_jours=[0, 2])  # lundi et mercredi seulement
    res = planifier(LUNDI, DIMANCHE, preferences, MATIERES, SEMAINE)
    assert dans(res, LUNDI, time(10), time(12))
    assert not dans(res, JOURS[1], time(10), time(12))


def test_limite_du_jour_respectee_hors_soirees_garanties():
    res = planifier(LUNDI, DIMANCHE, m.Preferences(max_minutes_jour=240), MATIERES, SEMAINE)
    for jour in JOURS[:5]:
        en_journee = [s for s in res.seances if s.debut.date() == jour and s.debut.time() < time(20)]
        assert len(en_journee) <= 1  # la soirée (≈ 3 h) prend déjà presque toute la limite


def test_revision_la_veille_du_cours_puis_l_avant_veille():
    # Maths : cours le vendredi ; physique : cours le mardi.
    activites = SEMAINE + [cours("Maths", 4, 18, 19, MATHS), cours("Physique", 1, 18, 19, PHYSIQUE)]
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), MATIERES, activites)

    def premiere_revision(jour):
        return min((s for s in res.seances if s.debut.date() == jour), key=lambda s: s.debut).matiere_id

    def soiree(jour):
        return min((s for s in dans(res, jour, time(20), time(23))), key=lambda s: s.debut).matiere_id

    assert soiree(JOURS[3]) == MATHS.id  # jeudi soir : veille du cours de maths
    assert soiree(JOURS[2]) == MATHS.id  # mercredi : avant-veille
    assert soiree(LUNDI) == PHYSIQUE.id  # lundi : veille du cours de physique
    assert premiere_revision(JOURS[3]) == MATHS.id


def test_activite_reliee_a_la_matiere_par_son_nom():
    # « TP de Maths » n'a pas de matière choisie : son nom suffit.
    activites = SEMAINE + [m.ActiviteFixe("TP de Maths", time(18), time(19), jour_semaine=4)]
    preferences = m.Preferences(plages_garanties=[], remplissage_jours=[], minutes_revision_semaine=45)
    res = planifier(LUNDI, DIMANCHE, preferences, MATIERES, activites)
    [seance] = [s for s in res.seances if s.matiere_id == MATHS.id]
    assert seance.debut.date() == JOURS[3]  # jeudi


def test_devoir_du_samedi_prepare_sur_toute_la_semaine():
    devoir = m.Epreuve(MATHS.id, datetime(2026, 11, 21, 9), datetime(2026, 11, 21, 11),
                       type=m.TypeEpreuve.DEVOIR_SURVEILLE, minutes_preparation=300, id=1)
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), MATIERES, SEMAINE, epreuves=[devoir])
    prep = [s for s in res.seances if s.epreuve_id == 1]
    assert sum(s.minutes for s in prep) == 300
    assert len({s.debut.date() for s in prep}) >= 4  # étalée, pas tout la veille
    assert all(s.fin <= devoir.debut for s in prep)


def test_reglages_enregistres(tmp_path):
    base = Base(tmp_path / "r.db")
    preferences = m.Preferences(remplissage_jours=[0, 1, 2], remplissage_minutes=60)
    base.enregistrer_preferences(preferences)
    assert base.preferences() == preferences
    base.fermer()


def test_long_moment_libre_occupe_sans_entasser():
    # Lundi sans cours : le matin (7 h – 12 h) et l'après-midi (13 h – 18 h) sont libres.
    activites = [a for a in SEMAINE if a.jour_semaine != 0]
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), MATIERES, activites)
    matin = sorted(dans(res, LUNDI, time(7), time(12)), key=lambda s: s.debut)
    apres_midi = sorted(dans(res, LUNDI, time(13), time(18)), key=lambda s: s.debut)
    assert matin and apres_midi  # chaque moment libre reçoit quelque chose
    total = sum(s.minutes for s in res.seances if s.debut.date() == LUNDI)
    assert total <= m.Preferences().max_minutes_jour  # 6 h au plus, soirée garantie comprise


def test_plusieurs_seances_espacees_quand_la_limite_le_permet():
    activites = [a for a in SEMAINE if a.jour_semaine != 0]
    res = planifier(LUNDI, DIMANCHE, m.Preferences(max_minutes_jour=600), MATIERES, activites)
    for debut, fin in ((time(7), time(12)), (time(13), time(18))):
        suite = sorted(dans(res, LUNDI, debut, fin), key=lambda s: s.debut)
        assert len(suite) >= 2
        for a, b in zip(suite, suite[1:]):
            assert b.debut - a.fin >= timedelta(minutes=60)  # respiration entre deux séances
            assert a.minutes <= 45


def test_respiration_reglable():
    activites = [a for a in SEMAINE if a.jour_semaine != 0]
    serre = planifier(LUNDI, DIMANCHE, m.Preferences(remplissage_espace=15, max_minutes_jour=900), MATIERES, activites)
    large = planifier(LUNDI, DIMANCHE, m.Preferences(remplissage_espace=120, max_minutes_jour=900), MATIERES, activites)
    assert len(dans(serre, LUNDI, time(7), time(12))) > len(dans(large, LUNDI, time(7), time(12)))
