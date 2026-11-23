"""Retours d'utilisation : période planifiée respectée, molette, export par période, matière créée par
l'assistant, barres du Bilan au même niveau."""

from datetime import date, datetime, time, timedelta

import pytest

from planificateur import modeles as m
from planificateur.base import Base

JEUDI = datetime(2026, 11, 26, 9, 0)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "p.db")
    yield b
    b.fermer()


# --- Période planifiée -----------------------------------------------------------------------


def test_fin_de_periode_en_semaines_du_calendrier():
    assert m.fin_de_periode(date(2026, 11, 26), 1) == date(2026, 11, 29)  # jeudi → dimanche
    assert m.fin_de_periode(date(2026, 11, 29), 1) == date(2026, 12, 6)  # dimanche → toute la semaine suivante
    assert m.fin_de_periode(date(2026, 11, 23), 2) == date(2026, 12, 6)


def test_planning_limite_a_la_semaine_et_nettoye(base):
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    base.activites.ajouter(m.ActiviteFixe("Maths", time(8), time(10), jour_semaine=0, matiere_id=maths.id))
    from planificateur.ui.calendrier import enregistrer_resultat, generer

    preferences = base.preferences()
    preferences.horizon_semaines = 12
    base.enregistrer_preferences(preferences)
    enregistrer_resultat(base, generer(base, JEUDI))
    assert max(s.debut for s in base.seances.lister()).date() > date(2027, 1, 1)
    preferences.horizon_semaines = 1
    base.enregistrer_preferences(preferences)
    enregistrer_resultat(base, generer(base, JEUDI))  # les séances au-delà de la semaine disparaissent
    assert max(s.debut for s in base.seances.lister()).date() <= date(2026, 11, 29)


def test_epreuve_juste_apres_la_periode_preparee_avant(base):
    from planificateur.ui.calendrier import generer

    maths = base.matieres.ajouter(m.Matiere("Maths"))
    lundi_suivant = datetime(2026, 11, 30, 8, 0)
    base.epreuves.ajouter(m.Epreuve(maths.id, lundi_suivant, lundi_suivant + timedelta(hours=2)))
    preferences = base.preferences()
    preferences.horizon_semaines = 1
    base.enregistrer_preferences(preferences)
    resultat = generer(base, JEUDI)
    preparations = [s for s in resultat.seances if s.type is m.TypeSeance.PREPARATION]
    assert preparations and all(s.debut.date() <= date(2026, 11, 29) for s in preparations)
    assert not [d for d in resultat.non_places if d.type is m.TypeSeance.PREPARATION]  # pas de fausse alerte


def test_molette_sans_clic_ne_change_rien(application, base):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from planificateur.ui.preferences import PagePreferences
    from planificateur.ui.theme import appliquer_theme

    appliquer_theme(QApplication.instance())
    page = PagePreferences(base)
    page.show()
    from PySide6.QtWidgets import QLineEdit, QScrollArea

    page.resize(900, 500)
    QApplication.processEvents()
    defilement = page.findChildren(QScrollArea)[0].verticalScrollBar()
    defilement.setValue(defilement.maximum() // 2)
    position = defilement.value()
    avant = (page.horizon.currentIndex(), page.revisions.value())
    for champ in (page.horizon, page.revisions, page.revisions.findChild(QLineEdit)):
        for _ in range(10):
            evenement = QWheelEvent(QPointF(5, 5), QPointF(champ.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                                    QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(champ, evenement)
    assert (page.horizon.currentIndex(), page.revisions.value()) == avant
    assert defilement.value() != position  # la molette fait défiler la page à la place


def test_choix_de_la_periode_dans_les_preferences(application, base):
    from planificateur.ui.preferences import PagePreferences

    preferences = base.preferences()
    preferences.horizon_semaines = 5  # valeur d'une ancienne version
    base.enregistrer_preferences(preferences)
    page = PagePreferences(base)
    assert page.horizon.currentData() == 4 and "jusqu'au" in page.fin_horizon.text()
    page.horizon.setCurrentIndex(page.horizon.findData(1))
    assert page.lire().horizon_semaines == 1


def test_export_de_la_semaine_affichee(application, base, tmp_path):
    from planificateur.ui.calendrier import PagePlanning, lundi_de

    maths = base.matieres.ajouter(m.Matiere("Maths"))
    lundi = lundi_de(date.today())
    for semaine in range(12):
        debut = datetime.combine(lundi + timedelta(weeks=semaine, days=2), time(20))
        base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, debut, debut + timedelta(hours=1), matiere_id=maths.id))
    page = PagePlanning(base)
    page.lundi = lundi + timedelta(weeks=1)  # semaine suivante affichée
    libelle, du, au = page.periodes_export()[0]
    assert libelle.startswith("Semaine affichée") and du == page.lundi and au == page.lundi + timedelta(days=6)
    assert any(p[0].startswith("Cette semaine") for p in page.periodes_export())
    nombre = page.exporter_agenda(tmp_path / "semaine.ics", matieres_choisies=None)
    assert nombre == 1  # une seule semaine, pas trois mois


# --- Matière créée par l'assistant -----------------------------------------------------------


def _appel(fonction, **arguments):
    from planificateur.ia.gemini import Appel

    return Appel(fonction, arguments)


def test_assistant_cree_une_matiere_et_s_en_sert(base):
    from planificateur.ia.assistant import appliquer, preparer

    base.activites.ajouter(m.ActiviteFixe("Automatique", time(8), time(10), date=date(2026, 11, 24)))
    actions, erreurs = preparer(base, [
        _appel("ajouter_epreuve", matiere="Automatique", type="examen", date="2026-12-10", debut="08:00", fin="10:00"),
        _appel("ajouter_matiere", nom="Automatique", coefficient=2, difficulte=9, maitrise=2),
    ])
    assert not erreurs and [a.nom for a in actions] == ["ajouter_matiere", "ajouter_epreuve"]
    assert "difficulté 5/5" in actions[0].description  # bornée à 5
    with pytest.raises(ValueError, match="appliquez d'abord"):
        appliquer(base, actions[1])  # la matière n'existe pas encore
    message = appliquer(base, actions[0])
    assert "1 cours de l'emploi du temps" in message
    matiere = next(x for x in base.matieres.lister() if x.nom == "Automatique")
    assert base.activites.lister()[0].matiere_id == matiere.id
    appliquer(base, actions[1])
    assert base.epreuves.lister()[0].matiere_id == matiere.id


def test_matiere_deja_existante_refusee(base):
    from planificateur.ia.assistant import OUTILS, preparer

    base.matieres.ajouter(m.Matiere("Économie"))
    actions, erreurs = preparer(base, [_appel("ajouter_matiere", nom="economie")])
    assert not actions and "existe déjà" in erreurs[0]
    assert "ajouter_matiere" in {o["name"] for o in OUTILS}


def test_cours_relies_quand_on_genere(application, base):
    from planificateur.ui.calendrier import PagePlanning, generer

    base.activites.ajouter(m.ActiviteFixe("TD Physique", time(8), time(10), type=m.TypeActivite.TD,
                                          date=date(2026, 11, 27)))
    base.activites.ajouter(m.ActiviteFixe("Sport", time(18), time(19), type=m.TypeActivite.PERSONNEL, jour_semaine=1))
    physique = base.matieres.ajouter(m.Matiere("Physique"))
    generer(base, JEUDI)  # calcul seul (Bilan) : ne modifie rien
    assert all(a.matiere_id is None for a in base.activites.lister())
    PagePlanning(base).generer(JEUDI)  # bouton « Générer le planning »
    liens = {a.nom: a.matiere_id for a in base.activites.lister()}
    assert liens == {"TD Physique": physique.id, "Sport": None}


# --- Bilan --------------------------------------------------------------------------------------


def test_barres_du_bilan_par_nom(application, base):
    from planificateur.ui.bilan import PageBilan

    zeta, alpha = base.matieres.ajouter(m.Matiere("Zêta")), base.matieres.ajouter(m.Matiere("Alpha"))
    base.matieres.ajouter(m.Matiere("Rien"))
    for matiere, minutes in ((zeta, 300), (alpha, 60)):
        debut = datetime.combine(date.today(), time(6))
        base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, debut, debut + timedelta(minutes=minutes),
                                      matiere_id=matiere.id))
    page = PageBilan(base)
    page.rafraichir()
    assert [ligne[0] for ligne in page.barres.lignes] == ["Alpha", "Zêta"]  # ordre alphabétique, sans « Rien »


def test_ecrans_a_jour_apres_un_ajout_de_l_assistant(application, base):
    from planificateur.ia.assistant import Action
    from planificateur.ui.assistant_page import _CarteAction
    from planificateur.ui.fenetre import FenetrePrincipale

    fenetre = FenetrePrincipale(base)
    assistant = fenetre.pages["Assistant"]
    carte = _CarteAction(assistant, Action("ajouter_matiere", {"nom": "Automatique"}, "Ajouter la matière"))
    assert carte.appliquer()
    matieres = fenetre.pages["Matières"]
    assert [x.nom for x in matieres.objets] == ["Automatique"]
    fenetre._quitter_vraiment = True
    fenetre.close()
