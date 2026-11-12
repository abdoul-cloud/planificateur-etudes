from datetime import date, datetime, time

from planificateur import modeles as m
from planificateur.moteur.creneaux import (
    Intervalle,
    creneaux_libres,
    fusionner,
    periodes_occupees,
)

LUNDI = date(2026, 11, 16)
DIMANCHE = date(2026, 11, 22)
# Préférences neutres pour les tests génériques : journée 8 h – 21 h, sans repas.
PREFS = m.Preferences(
    debut_journee=time(8),
    fin_journee=time(21),
    dejeuner_debut=None,
    dejeuner_fin=None,
    diner_debut=None,
    diner_fin=None,
)


def h(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute))


def cours(nom, jour_semaine, debut, fin, **options) -> m.ActiviteFixe:
    return m.ActiviteFixe(nom, time(debut), time(fin), jour_semaine=jour_semaine, **options)


def test_journee_vide_entierement_libre():
    assert creneaux_libres(LUNDI, LUNDI, PREFS) == [Intervalle(h(LUNDI, 8), h(LUNDI, 21))]


def test_un_cours_coupe_la_journee_en_deux():
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [cours("Algèbre", 0, 10, 12)])
    assert libres == [
        Intervalle(h(LUNDI, 8), h(LUNDI, 10)),
        Intervalle(h(LUNDI, 12), h(LUNDI, 21)),
    ]


def test_aucun_creneau_ne_chevauche_un_cours_ou_une_epreuve():
    activites = [
        cours("Algèbre", 0, 8, 10),
        cours("Physique", 0, 10, 12),
        cours("TP", 2, 14, 18, marge_avant_min=30),
        cours("Sport", 4, 18, 20),
    ]
    epreuve = m.Epreuve(1, h(date(2026, 11, 19), 14), h(date(2026, 11, 19), 16))
    occupes = periodes_occupees(LUNDI, DIMANCHE, activites, epreuves=[epreuve])
    libres = creneaux_libres(LUNDI, DIMANCHE, PREFS, activites, epreuves=[epreuve])
    assert libres
    assert not any(l.chevauche(o) for l in libres for o in occupes)


def test_les_marges_de_deplacement_sont_bloquees():
    activite = cours("TP", 0, 14, 16, marge_avant_min=30, marge_apres_min=15)
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [activite])
    assert libres == [
        Intervalle(h(LUNDI, 8), h(LUNDI, 13, 30)),
        Intervalle(h(LUNDI, 16, 15), h(LUNDI, 21)),
    ]


def test_un_cours_annule_libere_son_creneau():
    activite = cours("Algèbre", 0, 10, 12)
    activite.id = 7
    exception = m.ExceptionActivite(7, LUNDI)
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [activite], [exception])
    assert libres == [Intervalle(h(LUNDI, 8), h(LUNDI, 21))]


def test_la_recurrence_respecte_ses_dates_de_validite():
    activite = cours("Algèbre", 0, 10, 12, valide_au=date(2026, 11, 20))
    suivant = date(2026, 11, 23)
    assert len(creneaux_libres(LUNDI, LUNDI, PREFS, [activite])) == 2
    assert len(creneaux_libres(suivant, suivant, PREFS, [activite])) == 1


def test_activite_ponctuelle_ne_bloque_que_sa_date():
    rdv = m.ActiviteFixe("Médecin", time(9), time(10), date=LUNDI)
    mardi = date(2026, 11, 17)
    assert len(creneaux_libres(LUNDI, LUNDI, PREFS, [rdv])) == 2
    assert len(creneaux_libres(mardi, mardi, PREFS, [rdv])) == 1


def test_creneau_trop_court_ecarte():
    # 30 minutes libres entre deux cours : moins que la séance minimale (45 min).
    activites = [
        cours("A", 0, 8, 10),
        m.ActiviteFixe("B", time(10, 30), time(21), jour_semaine=0),
    ]
    assert creneaux_libres(LUNDI, LUNDI, PREFS, activites) == []


def test_jour_de_repos_exclu():
    prefs = m.Preferences(jours_repos=[6])
    assert creneaux_libres(DIMANCHE, DIMANCHE, prefs) == []


def test_seance_existante_bloque_son_creneau():
    seance = m.Seance(m.TypeSeance.REVISION, h(LUNDI, 9), h(LUNDI, 10, 30), verrouillee=True)
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, seances=[seance])
    assert libres == [
        Intervalle(h(LUNDI, 8), h(LUNDI, 9)),
        Intervalle(h(LUNDI, 10, 30), h(LUNDI, 21)),
    ]


def test_rien_avant_maintenant_et_alignement_sur_la_grille():
    maintenant = h(LUNDI, 15, 7)
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, a_partir_de=maintenant)
    assert libres == [Intervalle(h(LUNDI, 15, 15), h(LUNDI, 21))]


def test_horaires_hors_grille_arrondis_vers_l_interieur():
    activite = m.ActiviteFixe("Cours", time(10, 5), time(11, 50), jour_semaine=0)
    libres = creneaux_libres(LUNDI, LUNDI, PREFS, [activite])
    assert libres == [
        Intervalle(h(LUNDI, 8), h(LUNDI, 10)),
        Intervalle(h(LUNDI, 12), h(LUNDI, 21)),
    ]


def test_fusion_des_intervalles_contigus_ou_superposes():
    a = Intervalle(h(LUNDI, 8), h(LUNDI, 10))
    b = Intervalle(h(LUNDI, 10), h(LUNDI, 12))
    c = Intervalle(h(LUNDI, 11), h(LUNDI, 11, 30))
    d = Intervalle(h(LUNDI, 14), h(LUNDI, 15))
    assert fusionner([d, c, a, b]) == [Intervalle(h(LUNDI, 8), h(LUNDI, 12)), d]


def test_semaine_complete_total_coherent():
    # Cours du lundi au vendredi de 8 h à 12 h : il reste 9 h par jour ouvré, 13 h le week-end.
    activites = [cours("Cours", j, 8, 12) for j in range(5)]
    libres = creneaux_libres(LUNDI, DIMANCHE, PREFS, activites)
    assert sum(l.minutes for l in libres) == (5 * 9 + 2 * 13) * 60
