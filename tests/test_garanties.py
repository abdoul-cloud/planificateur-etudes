"""Plages garanties : du lundi au vendredi, 20 h – 23 h, toujours du travail personnel."""

from datetime import date, datetime, time, timedelta

from planificateur import modeles as m
from planificateur.base import Base
from planificateur.moteur.creneaux import GARANTIE, Intervalle, fusionner, niveau_preference, periodes_occupees
from planificateur.moteur.placement import planifier

LUNDI = date(2026, 11, 16)
SEMAINE_JOURS = [LUNDI + timedelta(days=n) for n in range(7)]
MATHS = m.Matiere("Maths", coefficient=4, difficulte=4, maitrise=2, id=1)
PHYSIQUE = m.Matiere("Physique", coefficient=3, difficulte=3, maitrise=3, id=2)
MATIERES = [MATHS, PHYSIQUE]


def cours(matiere, jour, debut, fin):
    return m.ActiviteFixe(matiere.nom, time(debut), time(fin), jour_semaine=jour, matiere_id=matiere.id)


# Semaine chargée : cours de 7 h à 18 h du lundi au vendredi
SEMAINE = [cours(MATHS, j, 7, 12) for j in range(5)] + [cours(PHYSIQUE, j, 13, 18) for j in range(5)]


def plus_grand_trou(res, jour: date, debut: time, fin: time, activites=SEMAINE) -> int:
    """Plus long moment libre (en minutes) dans la plage, une fois le planning fait."""
    zone = Intervalle(datetime.combine(jour, debut), datetime.combine(jour, fin))
    occupe = periodes_occupees(jour, jour, activites)
    occupe += [Intervalle(s.debut, s.fin) for s in res.seances]
    curseur, trou = zone.debut, 0
    for o in fusionner(occupe):
        if o.fin <= zone.debut or o.debut >= zone.fin:
            continue
        trou = max(trou, int((max(o.debut, zone.debut) - curseur).total_seconds() // 60))
        curseur = max(curseur, o.fin)
    return max(trou, int((zone.fin - curseur).total_seconds() // 60))


def minutes_dans(res, jour: date, debut: time, fin: time) -> int:
    zone = Intervalle(datetime.combine(jour, debut), datetime.combine(jour, fin))
    return sum(
        int((min(s.fin, zone.fin) - max(s.debut, zone.debut)).total_seconds() // 60)
        for s in res.seances if Intervalle(s.debut, s.fin).chevauche(zone)
    )


def test_soirs_de_semaine_toujours_remplis():
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), MATIERES, SEMAINE)
    for jour in SEMAINE_JOURS[:5]:
        assert plus_grand_trou(res, jour, time(20), time(23)) < 45, f"soirée du {jour} pas remplie"
        assert minutes_dans(res, jour, time(20), time(23)) >= 165  # 3 h moins une pause


def test_week_end_pas_concerne():
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(minutes_revision_semaine=0), MATIERES, SEMAINE)
    assert all(s.debut.weekday() < 5 for s in res.seances)


def test_une_activite_le_soir_passe_avant():
    sport = m.ActiviteFixe("Sport", time(20), time(21), jour_semaine=2)
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), MATIERES, SEMAINE + [sport])
    mercredi = SEMAINE_JOURS[2]
    assert minutes_dans(res, mercredi, time(20), time(21)) == 0
    assert plus_grand_trou(res, mercredi, time(21), time(23), SEMAINE + [sport]) < 45


def test_heure_de_coucher_respectee():
    couche_tot = m.Preferences(fin_journee=time(22))
    res = planifier(LUNDI, SEMAINE_JOURS[-1], couche_tot, MATIERES, SEMAINE)
    assert all(s.fin.time() <= time(22) for s in res.seances if s.fin.date() == s.debut.date())
    assert minutes_dans(res, LUNDI, time(20), time(22)) >= 105


def test_echeances_placees_d_abord_dans_les_soirees():
    travail = m.Travail("Rapport", MATHS.id, datetime(2026, 11, 20, 18), 90, id=1)
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), MATIERES, SEMAINE, travaux=[travail])
    seances = [s for s in res.seances if s.travail_id == 1]
    assert sum(s.minutes for s in seances) == 90
    assert all(niveau_preference(Intervalle(s.debut, s.fin), m.Preferences()) == GARANTIE for s in seances)


def test_soirees_remplies_meme_au_dela_de_la_limite_du_jour():
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(max_minutes_jour=60), MATIERES, SEMAINE)
    assert minutes_dans(res, LUNDI, time(20), time(23)) >= 165


def test_soirees_servent_d_abord_ce_qui_manque_aux_echeances():
    # La limite du jour (15 min) empêche toute séance normale : seules les soirées garanties restent.
    epreuve = m.Epreuve(MATHS.id, datetime(2026, 11, 20, 8), datetime(2026, 11, 20, 10), minutes_preparation=240, id=1)
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(max_minutes_jour=15), MATIERES, SEMAINE, epreuves=[epreuve])
    prep = [s for s in res.seances if s.epreuve_id == 1]
    assert sum(s.minutes for s in prep) == 240
    assert all(s.fin <= epreuve.debut for s in prep)
    assert res.faisable


def test_repos_avant_une_epreuve_du_soir():
    epreuve = m.Epreuve(MATHS.id, datetime(2026, 11, 19, 21), datetime(2026, 11, 19, 22), id=1)
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), MATIERES, SEMAINE, epreuves=[epreuve])
    repos = Intervalle(datetime(2026, 11, 19, 18), datetime(2026, 11, 19, 22))
    assert not any(Intervalle(s.debut, s.fin).chevauche(repos) for s in res.seances)


def test_revisions_equilibrees_et_variees():
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), MATIERES, SEMAINE)
    revisions = [s for s in res.seances if s.type is m.TypeSeance.REVISION]
    par_matiere = {mid: sum(s.minutes for s in revisions if s.matiere_id == mid) for mid in (1, 2)}
    assert par_matiere[1] > par_matiere[2] > 0  # maths pèse plus, physique n'est pas oubliée
    for jour in SEMAINE_JOURS[:5]:
        du_soir = [s.matiere_id for s in revisions if s.debut.date() == jour]
        assert len(du_soir) == len(set(du_soir)), "deux révisions de la même matière le même soir"


def test_sans_matiere_rien_n_est_invente():
    res = planifier(LUNDI, SEMAINE_JOURS[-1], m.Preferences(), [], SEMAINE)
    assert res.seances == []


def test_plages_garanties_enregistrees(tmp_path):
    base = Base(tmp_path / "g.db")
    preferences = m.Preferences(plages_garanties=[m.PlageHebdo([0, 2, 4], time(19, 30), time(22, 30))])
    base.enregistrer_preferences(preferences)
    assert base.preferences() == preferences
    base.enregistrer_preferences(m.Preferences(plages_garanties=[]))
    assert base.preferences().plages_garanties == []
    base.fermer()


def test_valeur_par_defaut():
    [plage] = m.Preferences().plages_garanties
    assert plage.jours == [0, 1, 2, 3, 4] and plage.debut == time(20) and plage.fin == time(23)
