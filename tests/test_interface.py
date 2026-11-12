"""Interface : formulaires, listes et préférences, sans afficher de fenêtre."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, time, timedelta  # noqa: E402

import pytest  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from planificateur import modeles as m  # noqa: E402
from planificateur.base import Base  # noqa: E402
from planificateur.ui.commun import (  # noqa: E402
    EditeurPlages,
    EditeurPlagesHebdo,
    texte_duree,
    vers_qdate,
    vers_qtime,
)
from planificateur.ui.fenetre import FenetrePrincipale, generer  # noqa: E402
from planificateur.ui.formulaires import (  # noqa: E402
    FormulaireActivite,
    FormulaireAnnulation,
    FormulaireEpreuve,
    FormulaireMatiere,
    FormulaireTravail,
)
from planificateur.ui.preferences import PagePreferences  # noqa: E402
from planificateur.ui.accueil import PageAccueil  # noqa: E402
from planificateur.ui.calendrier import PagePlanning  # noqa: E402

LUNDI = date(2026, 11, 16)


@pytest.fixture(scope="module")
def application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "ui.db")
    yield b
    b.fermer()


@pytest.fixture
def maths(base):
    return base.matieres.ajouter(m.Matiere("Maths", coefficient=4, difficulte=4, maitrise=2))


# --- Formulaires -----------------------------------------------------------


def test_formulaire_matiere_aller_retour(application):
    origine = m.Matiere("Physique", "PHY", 3, 4, 2, "#aa3300", "Mécanique", id=5)
    assert FormulaireMatiere(origine).valeur() == origine


def test_formulaire_matiere_nouvelle_sans_nom_refusee(application):
    formulaire = FormulaireMatiere()
    assert formulaire.nom.text() == ""
    with pytest.raises(ValueError):
        formulaire.valeur()
    formulaire.nom.setText("Chimie")
    assert formulaire.valeur().nom == "Chimie"


def test_formulaire_activite_hebdomadaire_et_ponctuelle(application, maths):
    hebdo = m.ActiviteFixe(
        "Algèbre", time(7), time(12), jour_semaine=0, matiere_id=maths.id,
        valide_du=date(2026, 9, 1), valide_au=date(2027, 1, 31), marge_avant_min=20, id=3,
    )
    assert FormulaireActivite([maths], hebdo).valeur() == hebdo

    ponctuelle = m.ActiviteFixe("Médecin", time(9), time(10), type=m.TypeActivite.PERSONNEL, date=LUNDI, id=4)
    assert FormulaireActivite([maths], ponctuelle).valeur() == ponctuelle


def test_formulaire_activite_horaire_inverse_refuse(application, maths):
    formulaire = FormulaireActivite([maths])
    formulaire.nom.setText("Cours")
    formulaire.debut.setTime(vers_qtime(time(12)))
    formulaire.fin.setTime(vers_qtime(time(10)))
    with pytest.raises(ValueError):
        formulaire.valeur()


def test_formulaire_epreuve_aller_retour_et_estimation(application, maths):
    epreuve = m.Epreuve(
        maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16),
        type=m.TypeEpreuve.EXAMEN, intitule="Partiel", chapitres="Ch. 1 à 4",
        importance=5, difficulte=4, preparation=2, id=7,
    )
    formulaire = FormulaireEpreuve([maths], epreuve)
    assert formulaire.valeur() == epreuve
    assert "estimation automatique" in formulaire.estimation.text()
    formulaire.temps_libre.setChecked(True)
    formulaire.temps.setValue(150)
    assert formulaire.valeur().minutes_preparation == 150


def test_formulaire_epreuve_sans_matiere_impossible(application):
    with pytest.raises(ValueError):
        FormulaireEpreuve([])


def test_formulaire_travail_temps_restant(application, maths):
    formulaire = FormulaireTravail([maths])
    formulaire.intitule.setText("Rapport")
    formulaire.estime.setValue(240)
    assert formulaire.valeur().minutes_restantes == 240  # rien de fait
    formulaire.commence.setChecked(True)
    formulaire.restant.setValue(90)
    assert formulaire.valeur().minutes_restantes == 90
    formulaire.restant.setValue(300)
    with pytest.raises(ValueError):
        formulaire.valeur()


def test_formulaire_travail_aller_retour(application, maths):
    travail = m.Travail(
        "Exposé", maths.id, datetime(2026, 11, 20, 18), 300, minutes_restantes=120, type="Exposé",
        date_cible=datetime(2026, 11, 19, 12), importance=4, etat=m.EtatTravail.EN_COURS, notes="Slides", id=2,
    )
    assert FormulaireTravail([maths], travail).valeur() == travail


def test_annulation_doit_tomber_le_bon_jour(application):
    cours = m.ActiviteFixe("Algèbre", time(7), time(12), jour_semaine=0, id=3)
    formulaire = FormulaireAnnulation(cours)
    formulaire.date.setDate(vers_qdate(LUNDI + timedelta(days=1)))
    with pytest.raises(ValueError):
        formulaire.valeur()
    formulaire.date.setDate(vers_qdate(LUNDI))
    assert formulaire.valeur() == m.ExceptionActivite(3, LUNDI)


# --- Éditeurs de plages et préférences ------------------------------------


def test_editeurs_de_plages(application):
    pauses = [m.Plage(time(12), time(13), "Déjeuner"), m.Plage(time(18), time(19), "Dîner")]
    assert EditeurPlages(pauses).valeurs() == pauses
    hebdo = [m.PlageHebdo([0, 2, 4], time(19), time(22))]
    assert EditeurPlagesHebdo(hebdo).valeurs() == hebdo


def test_preferences_aller_retour_complet(application, base):
    preferences = m.Preferences(
        duree_min_seance=30, duree_max_seance=120, pause_min=15,
        debut_journee=time(8), fin_journee=time(22, 30), max_minutes_jour=300,
        pauses_quotidiennes=[m.Plage(time(12, 30), time(13, 30), "Déjeuner")],
        reglages_jour={
            5: m.ReglageJour(True, time(9), time(17), 180, [m.Plage(time(12), time(14), "Repas")]),
            6: m.ReglageJour(travaille=False),
        },
        plages_preferees=[m.PlageHebdo([0, 1, 2, 3, 4], time(19), time(22))],
        plages_evitees=[m.PlageHebdo([5, 6], time(7), time(9))],
        marge_echeance_heures=24, horizon_semaines=4, minutes_revision_semaine=240,
        repos_avant_epreuve_min=120, max_minutes_jour_epreuve=90,
    )
    page = PagePreferences(base)
    page.charger(preferences)
    assert page.lire() == preferences
    assert page.enregistrer()
    assert base.preferences() == preferences


def test_preferences_par_defaut_affichees(application, base):
    assert PagePreferences(base).lire() == m.Preferences()


def test_jour_particulier_part_du_reglage_general(application, base):
    page = PagePreferences(base)
    samedi = page.lignes_jours[5]
    samedi.particulier.setChecked(True)
    samedi.limite.setValue(120)
    preferences = page.lire()
    assert preferences.reglages_jour[5].max_minutes == 120
    assert preferences.reglages_jour[5].pauses == m.Preferences().pauses_quotidiennes


# --- Fenêtre et pages -----------------------------------------------------


def test_fenetre_et_pages_affichent_les_donnees(application, base, maths):
    base.activites.ajouter(m.ActiviteFixe("Algèbre", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))
    base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 240))
    fenetre = FenetrePrincipale(base)
    for nom in FenetrePrincipale.ECRANS:
        fenetre.afficher(nom)
        assert fenetre.pile.currentWidget() is fenetre.pages[nom]
    assert fenetre.pages["Matières"].table.item(0, 0).text() == "Maths"
    assert fenetre.pages["Emploi du temps"].table.item(0, 2).text() == "Chaque lundi"
    assert fenetre.pages["Épreuves"].table.item(0, 1).text() == "Maths"
    assert fenetre.pages["Travaux à rendre"].table.item(0, 3).text() == "4 h sur 4 h"


def test_modification_d_une_matiere_rafraichit_les_autres_pages(application, base, maths):
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))
    fenetre = FenetrePrincipale(base)
    maths.nom = "Mathématiques"
    base.matieres.modifier(maths)
    fenetre.pages["Matières"]._modifie()
    assert fenetre.pages["Épreuves"].table.item(0, 1).text() == "Mathématiques"


def test_annulation_affichee_dans_l_emploi_du_temps(application, base):
    cours = base.activites.ajouter(m.ActiviteFixe("Algèbre", time(7), time(12), jour_semaine=0))
    base.exceptions.ajouter(m.ExceptionActivite(cours.id, LUNDI))
    fenetre = FenetrePrincipale(base)
    assert fenetre.pages["Emploi du temps"].table.item(0, 5).text() == "16/11"


def _semaine_type(base, maths):
    base.activites.ajouter(m.ActiviteFixe("Algèbre", time(7), time(18), jour_semaine=0, matiere_id=maths.id))
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))


def _page_planning(base):
    page = PagePlanning(base)
    page.avertir = lambda *args: None  # pas de fenêtre bloquante pendant les tests
    page.lundi = LUNDI
    return page


def test_generer_enregistre_les_seances(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    resultat = page.generer(datetime(2026, 11, 16))
    assert resultat.seances
    assert len(base.seances.lister()) == len(resultat.seances)
    assert page.calendrier.seances  # affichées dans la semaine
    assert len(generer(base, datetime(2026, 11, 16)).retirees) == len(resultat.seances)  # remplacées, pas ajoutées
    page.generer(datetime(2026, 11, 16))  # régénérer ne duplique pas
    assert len(base.seances.lister()) == len(resultat.seances)


def test_deplacer_une_seance_la_verrouille(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    seance = page.calendrier.seances[0]
    debut = datetime.combine(seance.debut.date(), time(21))
    assert page.deplacer(seance, debut, debut + (seance.fin - seance.debut))
    deplacee = base.seances.obtenir(seance.id)
    assert deplacee.debut == debut
    assert deplacee.verrouillee and deplacee.origine is m.Origine.MANUELLE


def test_deplacement_sur_un_cours_refuse(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    seance = page.calendrier.seances[0]
    pendant_le_cours = datetime(2026, 11, 16, 9)
    assert not page.deplacer(seance, pendant_le_cours, pendant_le_cours + timedelta(hours=1))
    assert base.seances.obtenir(seance.id).debut == seance.debut


def test_conflit_signale_apres_ajout_d_un_cours(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    seance = page.calendrier.seances[0]
    base.activites.ajouter(m.ActiviteFixe("Rattrapage", seance.debut.time(), seance.fin.time(), date=seance.debut.date()))
    page.rafraichir()
    assert seance.id in page.calendrier.conflits


def test_verrou_et_suppression(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    seance = page.calendrier.seances[0]
    page.basculer_verrou(seance)
    assert base.seances.obtenir(seance.id).verrouillee
    page.supprimer(seance)
    assert base.seances.obtenir(seance.id) is None


def test_calendrier_se_dessine(application, base, maths):
    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    page.resize(1200, 800)
    assert not page.grab().isNull()
    assert page.titre_semaine.text() == "16 – 22 novembre 2026"


def test_navigation_entre_semaines(application, base):
    page = _page_planning(base)
    page.aller(1)
    assert page.lundi == LUNDI + timedelta(weeks=1)
    page.aujourd_hui()
    assert page.lundi.weekday() == 0


def test_accueil_resume_la_journee(application, base, maths):
    _semaine_type(base, maths)
    PagePlanning(base).generer(datetime(2026, 11, 16))
    accueil = PageAccueil(base)
    accueil.maintenant = datetime(2026, 11, 16, 8)
    accueil.rafraichir()
    assert accueil.stat_epreuve.valeur.text() == "Dans 3 jours"
    assert not accueil.premiers_pas.isVisible() or base.activites.lister()


def test_accueil_vide_propose_les_premiers_pas(application, base):
    accueil = PageAccueil(base)
    fenetre = FenetrePrincipale(base)
    fenetre.show()
    assert fenetre.pages["Accueil"].premiers_pas.isVisible()
    fenetre.close()
    assert accueil.stat_jour.valeur.text() == "Libre"


def test_texte_duree():
    assert texte_duree(45) == "45 min"
    assert texte_duree(60) == "1 h"
    assert texte_duree(210) == "3 h 30"


def test_glisser_deposer_a_la_souris(application, base, maths):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    _semaine_type(base, maths)
    page = _page_planning(base)
    page.generer(datetime(2026, 11, 16))
    page.resize(1200, 900)
    page.show()
    calendrier = page.calendrier
    application.processEvents()
    calendrier.repaint()
    bloc = calendrier._blocs[0]
    recu = []
    calendrier.seance_deplacee.disconnect()
    calendrier.seance_deplacee.connect(lambda s, d, f: recu.append((s, d, f)))
    depart = bloc.rect.center().toPoint()
    arrivee = depart + QPoint(0, calendrier.PX_HEURE)  # une heure plus tard
    QTest.mousePress(calendrier, Qt.MouseButton.LeftButton, pos=depart)
    QTest.mouseMove(calendrier, arrivee)
    QTest.mouseRelease(calendrier, Qt.MouseButton.LeftButton, pos=arrivee)
    page.close()
    assert recu, "le déplacement n'a pas été signalé"
    seance, debut, fin = recu[0]
    assert seance is bloc.seance
    assert debut - seance.debut == timedelta(hours=1)
    assert fin - debut == seance.fin - seance.debut
