"""Affichage : petits écrans (portable 1366 × 768 zoomé à 125 %), couleurs des matières, titres courts."""

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea, QTableWidget

from planificateur import modeles as m
from planificateur.base import Base

# Les mesures de largeur demandent les vraies polices : sans affichage (« offscreen »), elles sont fausses.
# Pour les lancer :  set QT_QPA_PLATFORM=windows  puis  pytest tests/test_affichage.py
mesures_reelles = pytest.mark.skipif(
    __import__("os").environ.get("QT_QPA_PLATFORM") == "offscreen",
    reason="mesures de taille : lancer avec QT_QPA_PLATFORM=windows",
)


@pytest.fixture
def fenetre(application, tmp_path):
    from planificateur.ui.fenetre import FenetrePrincipale

    base = Base(tmp_path / "a.db")
    maths = base.matieres.ajouter(m.Matiere("Mathématiques appliquées", code="MATH-201"))
    base.epreuves.ajouter(m.Epreuve(maths.id, __import__("datetime").datetime(2026, 12, 5, 8),
                                    __import__("datetime").datetime(2026, 12, 5, 10), intitule="Composition de fin de semestre"))
    f = FenetrePrincipale(base)
    yield f
    f._quitter_vraiment = True  # fermeture réelle (pas d'icône près de l'horloge pendant les tests)
    f.close()
    base.fermer()


@mesures_reelles
def test_tient_dans_un_petit_ecran(fenetre):
    # 1366 × 768 à 125 % : environ 1093 × 580 utilisables
    taille = fenetre.minimumSizeHint().expandedTo(fenetre.minimumSize())
    assert taille.width() <= 1000 and taille.height() <= 580


@mesures_reelles
@pytest.mark.parametrize("largeur", [960, 1280, 1600])
def test_aucun_defilement_horizontal(fenetre, largeur):
    fenetre.resize(largeur, 640)
    fenetre.show()
    for nom in fenetre.ECRANS:
        fenetre.afficher(nom)
        QApplication.processEvents()
        for zone in fenetre._cadres[nom].findChildren(QScrollArea) + (
                [fenetre._cadres[nom]] if isinstance(fenetre._cadres[nom], QScrollArea) else []):
            if zone.isVisible():
                assert zone.horizontalScrollBar().maximum() == 0, (largeur, nom)
        for table in fenetre._cadres[nom].findChildren(QTableWidget):
            if table.isVisible() and table.rowCount():
                assert table.horizontalScrollBar().maximum() == 0, (largeur, nom, "tableau")


def test_preferences_sur_une_ou_deux_colonnes(fenetre):
    from PySide6.QtWidgets import QBoxLayout

    page = fenetre.pages["Préférences"]
    fenetre.show()
    fenetre.afficher("Préférences")
    fenetre.resize(960, 600)
    QApplication.processEvents()
    assert page._grille.direction() is QBoxLayout.Direction.TopToBottom
    fenetre.resize(1400, 800)
    QApplication.processEvents()
    assert page._grille.direction() is QBoxLayout.Direction.LeftToRight


def test_couleur_differente_pour_chaque_nouvelle_matiere():
    assert m.couleur_libre([]) == m.COULEURS_MATIERES[0]
    assert m.couleur_libre([m.COULEURS_MATIERES[0].lower()]) == m.COULEURS_MATIERES[1]
    toutes = list(m.COULEURS_MATIERES)
    assert m.couleur_libre(toutes) in m.COULEURS_MATIERES  # palette épuisée : on recommence


def test_formulaire_nouvelle_matiere_propose_une_couleur_libre(application, tmp_path):
    from planificateur.ui.pages import PageMatieres

    base = Base(tmp_path / "c.db")
    base.matieres.ajouter(m.Matiere("Maths", couleur=m.COULEURS_MATIERES[0]))
    page = PageMatieres(base)
    assert page.formulaire().couleur == m.COULEURS_MATIERES[1]
    base.fermer()


def test_titre_de_semaine_court():
    from planificateur.ui.calendrier import texte_semaine

    assert texte_semaine(date(2026, 11, 16), court=True) == "16 – 22 nov. 2026"
    assert texte_semaine(date(2026, 12, 28), court=True) == "28 déc. – 3 janv. 2027"
    assert texte_semaine(date(2026, 11, 16)) == "16 – 22 novembre 2026"


def test_epreuve_dessinee_sans_remplissage_parasite(application, tmp_path):
    """Le bloc d'une épreuve reste rose pâle, même après le rond bleu « aujourd'hui »."""
    from datetime import datetime, timedelta

    from planificateur.ui.calendrier import PagePlanning, lundi_de

    base = Base(tmp_path / "e.db")
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    lundi = lundi_de(date.today())
    jour = lundi + timedelta(days=5)
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime.combine(jour, datetime.min.time()).replace(hour=14),
                                    datetime.combine(jour, datetime.min.time()).replace(hour=17)))
    page = PagePlanning(base)
    page.resize(1100, 900)
    page.show()
    page.rafraichir()
    QApplication.processEvents()
    calendrier = page.calendrier
    image = calendrier.grab().toImage()
    rect = calendrier._rect(datetime.combine(jour, datetime.min.time()).replace(hour=15),
                            datetime.combine(jour, datetime.min.time()).replace(hour=16, minute=30))
    point = rect.center().toPoint() * image.devicePixelRatio()
    couleur = image.pixelColor(int(point.x()), int(point.y()))
    assert couleur.red() > 230 and couleur.blue() > 200 and couleur.green() > 200  # rose très pâle, pas bleu
    base.fermer()
