"""Placement des séances : scénarios du cahier des charges (section 11)."""

from datetime import date, datetime, time, timedelta

from planificateur import modeles as m
from planificateur.moteur.creneaux import (
    EVITEE,
    PREFEREE,
    Intervalle,
    niveau_preference,
    periodes_occupees,
)
from planificateur.moteur.placement import (
    minutes_preparation,
    planifier,
    repartir_revisions,
)

DIMANCHE_AVANT = date(2026, 11, 15)


def sans_garantie(**options) -> m.Preferences:
    """Préférences de test sans plages garanties ni moments libres occupés
    (testés à part dans test_garanties.py et test_remplissage.py)."""
    options.setdefault("plages_garanties", [])
    options.setdefault("remplissage_jours", [])
    return m.Preferences(**options)

LUNDI, MARDI, MERCREDI, JEUDI, VENDREDI, SAMEDI, DIMANCHE = (
    date(2026, 11, 16) + timedelta(days=n) for n in range(7)
)

MATHS = m.Matiere("Maths", coefficient=4, difficulte=4, maitrise=2, id=1)
PHYSIQUE = m.Matiere("Physique", coefficient=3, difficulte=3, maitrise=3, id=2)
ANGLAIS = m.Matiere("Anglais", coefficient=2, difficulte=2, maitrise=4, id=3)
MATIERES = [MATHS, PHYSIQUE, ANGLAIS]

# Préférences par défaut (7 h – 23 h, repas 12 h et 18 h, 6 h/jour) sans révisions
# régulières, pour observer seules les échéances.
SANS_REVISION = sans_garantie(minutes_revision_semaine=0)


def h(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute))


def cours(matiere: m.Matiere, jour: int, debut: int, fin: int) -> m.ActiviteFixe:
    return m.ActiviteFixe(matiere.nom, time(debut), time(fin), jour_semaine=jour, matiere_id=matiere.id)


# Semaine type : lundi et vendredi chargés, mardi coupé, mercredi matin, jeudi après-midi.
SEMAINE = [
    cours(MATHS, 0, 7, 12), cours(PHYSIQUE, 0, 13, 18),
    cours(PHYSIQUE, 1, 7, 12), cours(ANGLAIS, 1, 14, 18),
    cours(MATHS, 2, 7, 12),
    cours(PHYSIQUE, 3, 14, 18),
    cours(ANGLAIS, 4, 7, 12), cours(MATHS, 4, 13, 18),
]


def compo_maths(**options) -> m.Epreuve:
    return m.Epreuve(MATHS.id, h(JEUDI, 14), h(JEUDI, 16), id=1, **options)


def verifier_contraintes(res, prefs, activites=SEMAINE, epreuves=()):
    """Invariants qui doivent toujours tenir, quel que soit le scénario."""
    occupes = periodes_occupees(DIMANCHE_AVANT, DIMANCHE + timedelta(days=7), activites, epreuves=epreuves)
    for s in res.seances:
        seance = Intervalle(s.debut, s.fin)
        reglage = prefs.jour(s.debut.weekday())
        assert not any(seance.chevauche(o) for o in occupes), f"chevauchement : {s}"
        for p in reglage.pauses:
            pause = Intervalle(datetime.combine(s.debut.date(), p.debut), datetime.combine(s.debut.date(), p.fin))
            assert not seance.chevauche(pause), f"séance pendant {p.nom} : {s}"
        assert reglage.debut <= s.debut.time() and s.fin.time() <= reglage.fin
        assert s.minutes <= prefs.duree_max_seance
        assert s.origine is m.Origine.AUTO
    suite = sorted([*res.conservees, *res.seances], key=lambda s: s.debut)
    for a, b in zip(suite, suite[1:]):
        assert b.debut >= a.fin + timedelta(minutes=prefs.pause_min), f"pause manquante : {a} / {b}"
    for jour, minutes in res.charge_par_jour().items():
        assert minutes <= prefs.jour(jour.weekday()).max_minutes, f"limite dépassée le {jour}"


def seances_de(res, **filtre):
    return [s for s in res.seances if all(getattr(s, k) == v for k, v in filtre.items())]


# --- Épreuves -------------------------------------------------------------


def test_preparation_placee_avant_l_epreuve_et_etalee():
    epreuve = compo_maths()
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, epreuves=[epreuve])
    prep = seances_de(res, epreuve_id=1)
    assert sum(s.minutes for s in prep) == minutes_preparation(epreuve) == 210
    assert all(s.fin <= epreuve.debut for s in prep)
    assert len({s.debut.date() for s in prep}) == len(prep)  # un passage par jour
    assert len(prep) >= 3  # pas tout la veille
    assert res.faisable and not res.non_places
    verifier_contraintes(res, SANS_REVISION, epreuves=[epreuve])


def test_composition_jeudi_et_samedi():
    jeudi = compo_maths()
    samedi = m.Epreuve(PHYSIQUE.id, h(SAMEDI, 9), h(SAMEDI, 11), id=2)
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, epreuves=[jeudi, samedi])
    for epreuve in (jeudi, samedi):
        prep = seances_de(res, epreuve_id=epreuve.id)
        assert sum(s.minutes for s in prep) == 210
        assert all(s.fin <= epreuve.debut for s in prep)
    assert res.faisable
    verifier_contraintes(res, SANS_REVISION, epreuves=[jeudi, samedi])


def test_temps_de_preparation():
    assert minutes_preparation(compo_maths()) == 210  # moyenne, peu préparée
    assert minutes_preparation(compo_maths(preparation=3)) == 120
    assert minutes_preparation(compo_maths(importance=1, difficulte=1, preparation=5)) == 60
    assert minutes_preparation(compo_maths(importance=5, difficulte=5, preparation=1)) == 480
    assert minutes_preparation(compo_maths(minutes_preparation=150)) == 150  # saisi à la main


def test_epreuves_ignorees_hors_horizon_preparees_ou_passees():
    lointaine = m.Epreuve(MATHS.id, h(MARDI + timedelta(days=7), 8), h(MARDI + timedelta(days=7), 10), id=1)
    preparee = m.Epreuve(MATHS.id, h(JEUDI, 14), h(JEUDI, 16), etat=m.EtatEpreuve.PREPAREE, id=2)
    passee = m.Epreuve(MATHS.id, h(DIMANCHE_AVANT, 9), h(DIMANCHE_AVANT, 11), id=3)
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, epreuves=[lointaine, preparee, passee])
    assert res.seances == [] and res.non_places == []


# --- Travaux à rendre -----------------------------------------------------


def rapport(**options) -> m.Travail:
    valeurs = dict(intitule="Rapport de TP", matiere_id=ANGLAIS.id, echeance=h(VENDREDI, 18), minutes_estimees=240, id=1)
    valeurs.update(options)
    return m.Travail(**valeurs)


def test_travail_reparti_avant_l_echeance_avec_marge():
    travail = rapport()
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=[travail])
    seances = seances_de(res, travail_id=1)
    assert sum(s.minutes for s in seances) == 240
    marge = travail.echeance - timedelta(hours=SANS_REVISION.marge_echeance_heures)
    assert all(s.fin <= marge for s in seances)
    verifier_contraintes(res, SANS_REVISION)


def test_date_cible_personnelle_respectee():
    travail = rapport(minutes_estimees=120, date_cible=h(MERCREDI, 12))
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=[travail])
    seances = seances_de(res, travail_id=1)
    assert sum(s.minutes for s in seances) == 120
    assert all(s.fin <= h(MERCREDI, 12) for s in seances)


def test_travail_partiellement_fait_ne_recoit_que_le_reste():
    travail = rapport(minutes_estimees=300, minutes_restantes=90)
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=[travail])
    assert sum(s.minutes for s in seances_de(res, travail_id=1)) == 90


def test_pas_de_reste_trop_court():
    # 100 min → arrondi à 105 sur la grille de 15 min → 60 + 45, pas 90 + 15.
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=[rapport(minutes_estimees=100)])
    assert sorted(s.minutes for s in res.seances) == [45, 60]


def test_travail_en_retard_signale():
    travail = rapport(echeance=h(DIMANCHE_AVANT, 18), minutes_estimees=120)
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=[travail])
    assert res.seances == []
    assert len(res.non_places) == 1
    assert res.non_places[0].en_retard and res.non_places[0].minutes == 120


def test_devoir_et_composition_la_meme_semaine():
    epreuve, travail = compo_maths(), rapport()
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, epreuves=[epreuve], travaux=[travail])
    assert sum(s.minutes for s in seances_de(res, epreuve_id=1)) == 210
    assert sum(s.minutes for s in seances_de(res, travail_id=1)) == 240
    assert res.faisable
    verifier_contraintes(res, SANS_REVISION, epreuves=[epreuve])


# --- Surcharge et créneaux trop courts ------------------------------------


def test_semaine_irrealisable_signalee_sans_surcharger():
    prefs = sans_garantie(max_minutes_jour=60, minutes_revision_semaine=0)
    epreuve = m.Epreuve(MATHS.id, h(MARDI, 14), h(MARDI, 16), minutes_preparation=480, id=1)
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, epreuves=[epreuve])
    place = sum(s.minutes for s in res.seances)
    assert place == 60  # lundi soir seulement : mardi midi est dans le repos avant l'épreuve
    assert not res.faisable
    assert res.non_places[0].minutes == 480 - place
    verifier_contraintes(res, prefs, epreuves=[epreuve])


def test_creneau_trop_court_non_utilise():
    stage = m.ActiviteFixe("Stage", time(7), time(22, 30), jour_semaine=0)  # reste 22 h 30 – 23 h
    epreuve = m.Epreuve(MATHS.id, h(MARDI, 7), h(MARDI, 9), minutes_preparation=60, id=1)
    res = planifier(LUNDI, MARDI, SANS_REVISION, MATIERES, [stage], epreuves=[epreuve])
    assert res.seances == []
    assert res.non_places[0].minutes == 60


# --- Séances existantes ---------------------------------------------------


def test_seances_terminees_et_manuelles_conservees():
    epreuve = compo_maths()
    manuelle = m.Seance(
        m.TypeSeance.PREPARATION, h(MARDI, 19), h(MARDI, 20, 30), matiere_id=1, epreuve_id=1,
        origine=m.Origine.MANUELLE, verrouillee=True,
    )
    ancienne_auto = m.Seance(m.TypeSeance.PREPARATION, h(MERCREDI, 13), h(MERCREDI, 14), epreuve_id=1)
    terminee = m.Seance(
        m.TypeSeance.PREPARATION, h(DIMANCHE_AVANT, 15), h(DIMANCHE_AVANT, 16), epreuve_id=1,
        statut=m.StatutSeance.TERMINEE, minutes_effectuees=60,
    )
    res = planifier(
        LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, epreuves=[epreuve],
        seances_existantes=[manuelle, ancienne_auto, terminee],
    )
    assert any(s is manuelle for s in res.conservees)
    assert any(s is terminee for s in res.conservees)
    assert res.retirees == [ancienne_auto]
    nouvelles = seances_de(res, epreuve_id=1)
    assert sum(s.minutes for s in nouvelles) == 210 - 90 - 60  # seul le reste est ajouté
    assert all(s.debut.date() != MARDI for s in nouvelles)  # mardi déjà servi
    verifier_contraintes(res, SANS_REVISION, epreuves=[epreuve])


# --- Préférences ----------------------------------------------------------


def test_plages_preferees_choisies_d_abord():
    prefs = sans_garantie(
        minutes_revision_semaine=0,
        plages_preferees=[m.PlageHebdo([0, 1, 2, 3, 4], time(19), time(22))],
    )
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, travaux=[rapport(minutes_estimees=90, echeance=h(SAMEDI, 12))])
    [seance] = res.seances
    assert niveau_preference(Intervalle(seance.debut, seance.fin), prefs) == PREFEREE
    assert seance.debut == h(VENDREDI, 19)


def test_plages_evitees_en_dernier_recours():
    evite_la_journee = sans_garantie(
        minutes_revision_semaine=0, plages_evitees=[m.PlageHebdo(list(range(7)), time(7), time(19))]
    )
    travail = rapport(minutes_estimees=90, echeance=h(MERCREDI, 23))  # à finir avant mercredi 11 h
    [seance] = planifier(LUNDI, DIMANCHE, evite_la_journee, MATIERES, SEMAINE, travaux=[travail]).seances
    assert seance.debut == h(MARDI, 19)  # le soir plutôt que mardi midi

    tout_evite = sans_garantie(
        minutes_revision_semaine=0, plages_evitees=[m.PlageHebdo(list(range(7)), time(7), time(23))]
    )
    res = planifier(LUNDI, DIMANCHE, tout_evite, MATIERES, SEMAINE, travaux=[travail])
    assert res.faisable  # placé quand même, faute de mieux
    assert niveau_preference(Intervalle(res.seances[0].debut, res.seances[0].fin), tout_evite) == EVITEE


def test_horaires_flexibles_respectes():
    prefs = sans_garantie(
        minutes_revision_semaine=0,
        reglages_jour={
            2: m.ReglageJour(pauses=[m.Plage(time(12), time(13)), m.Plage(time(14), time(23), "Repos")]),
            5: m.ReglageJour(travaille=False),
            6: m.ReglageJour(travaille=False),
        },
    )
    epreuve = m.Epreuve(PHYSIQUE.id, h(DIMANCHE, 9), h(DIMANCHE, 11), minutes_preparation=480, id=1)
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, epreuves=[epreuve])
    assert all(s.debut.date() not in (SAMEDI, DIMANCHE) for s in res.seances)
    assert all(not (s.debut.date() == MERCREDI and s.fin > h(MERCREDI, 14)) for s in res.seances)
    verifier_contraintes(res, prefs, epreuves=[epreuve])


# --- Révisions régulières -------------------------------------------------


def test_repartition_des_revisions_selon_le_poids():
    # Poids : maths 4×4×4 = 64, physique 3×3×3 = 27, anglais 2×2×2 = 8.
    assert repartir_revisions(6, MATIERES) == {1: 4, 2: 2, 3: 0}


def test_semaine_sans_epreuve_revisions_dans_le_budget():
    prefs = sans_garantie()  # 300 min par semaine → 6 séances de 45 min
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE)
    revisions = seances_de(res, type=m.TypeSeance.REVISION)
    assert sum(s.minutes for s in revisions) == 270
    assert len(seances_de(res, matiere_id=MATHS.id)) == 4
    assert len(seances_de(res, matiere_id=PHYSIQUE.id)) == 2
    for matiere in MATIERES:  # pas deux fois la même matière le même jour
        jours = [s.debut.date() for s in seances_de(res, matiere_id=matiere.id)]
        assert len(jours) == len(set(jours))
    assert res.non_places == []
    verifier_contraintes(res, prefs)


def test_revision_placee_la_veille_ou_l_avant_veille_du_cours():
    # Cours le vendredi : on le révise le jeudi, sinon le mercredi (pas le lundi d'après).
    prefs = sans_garantie(minutes_revision_semaine=90)  # 2 séances
    res = planifier(LUNDI, DIMANCHE, prefs, [MATHS], [cours(MATHS, 4, 7, 12)])
    assert {s.debut.date() for s in res.seances} == {MERCREDI, JEUDI}


def test_revisions_ne_prennent_pas_la_place_des_echeances():
    prefs = sans_garantie(minutes_revision_semaine=3000, max_minutes_jour=180)
    epreuve = compo_maths()
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, epreuves=[epreuve])
    assert sum(s.minutes for s in seances_de(res, epreuve_id=1)) == 210
    assert res.faisable  # les révisions manquantes ne rendent pas la semaine irréalisable
    assert any(d.type is m.TypeSeance.REVISION for d in res.non_places)
    verifier_contraintes(res, prefs, epreuves=[epreuve])


def test_aucune_revision_dans_le_passe():
    prefs = sans_garantie()
    maintenant = h(JEUDI, 15)
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, maintenant=maintenant)
    assert res.seances and all(s.debut >= maintenant for s in res.seances)


def test_resultat_identique_a_chaque_appel():
    arguments = (LUNDI, DIMANCHE, sans_garantie(), MATIERES, SEMAINE)
    options = dict(epreuves=[compo_maths()], travaux=[rapport()])
    assert planifier(*arguments, **options).seances == planifier(*arguments, **options).seances


# --- Repos avant épreuve et équilibre de la semaine ------------------------


def test_repos_avant_chaque_epreuve_et_jour_d_epreuve_allege():
    prefs = sans_garantie()  # 3 h de repos avant, 2 h maximum le jour même
    jeudi, samedi = compo_maths(), m.Epreuve(PHYSIQUE.id, h(SAMEDI, 9), h(SAMEDI, 11), id=2)
    res = planifier(LUNDI, DIMANCHE, prefs, MATIERES, SEMAINE, epreuves=[jeudi, samedi], travaux=[rapport()])
    for e in (jeudi, samedi):
        repos = Intervalle(e.debut - timedelta(minutes=prefs.repos_avant_epreuve_min), e.debut)
        assert not any(Intervalle(s.debut, s.fin).chevauche(repos) for s in res.seances)
        assert res.charge_par_jour().get(e.debut.date(), 0) <= prefs.max_minutes_jour_epreuve
    assert res.faisable
    verifier_contraintes(res, prefs, epreuves=[jeudi, samedi])


def test_reglages_du_repos_avant_epreuve():
    sans_repos = sans_garantie(minutes_revision_semaine=0, repos_avant_epreuve_min=0, max_minutes_jour_epreuve=360)
    epreuve = m.Epreuve(MATHS.id, h(MARDI, 14), h(MARDI, 16), minutes_preparation=120, id=1)
    res = planifier(LUNDI, DIMANCHE, sans_repos, MATIERES, SEMAINE, epreuves=[epreuve])
    assert any(s.debut == h(MARDI, 13) for s in res.seances)  # mardi midi redevient possible


def test_charge_repartie_sur_la_semaine():
    # Deux rapports pour vendredi : ils ne doivent pas s'entasser sur les mêmes jours.
    rapports = [rapport(minutes_estimees=180), rapport(intitule="Exposé", minutes_estimees=180, id=2)]
    res = planifier(LUNDI, DIMANCHE, SANS_REVISION, MATIERES, SEMAINE, travaux=rapports)
    assert {LUNDI, MARDI, MERCREDI, JEUDI} <= {s.debut.date() for s in res.seances}
    assert max(res.charge_par_jour().values()) <= 150
    verifier_contraintes(res, SANS_REVISION)


def test_plage_preferee_au_milieu_d_un_creneau_libre():
    # Vendredi, libre de 19 h à 23 h : la séance doit commencer à 20 h, début de la plage préférée.
    preferences = sans_garantie(
        minutes_revision_semaine=0, plages_preferees=[m.PlageHebdo([4], time(20), time(22))]
    )
    travail = rapport(minutes_estimees=90, echeance=h(SAMEDI, 12))
    [seance] = planifier(LUNDI, DIMANCHE, preferences, MATIERES, SEMAINE, travaux=[travail]).seances
    assert seance.debut == h(VENDREDI, 20)
    assert niveau_preference(Intervalle(seance.debut, seance.fin), preferences) == PREFEREE
