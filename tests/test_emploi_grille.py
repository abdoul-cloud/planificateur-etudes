"""Emploi du temps en grille : saisie à la souris, déplacement, durée, copie, annulation."""

from datetime import date, datetime, time, timedelta

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from planificateur import modeles as m  # noqa: E402
from planificateur.base import Base  # noqa: E402
from planificateur.ui.emploi_grille import FormulaireRapide, PageEmploi  # noqa: E402

LUNDI = date(2026, 11, 16)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "grille.db")
    yield b
    b.fermer()


@pytest.fixture
def maths(base):
    return base.matieres.ajouter(m.Matiere("Maths"))


@pytest.fixture
def page(application, base):
    p = PageEmploi(base)
    p.avertir = lambda *args: None
    p.confirmer = lambda *args: True
    p.lundi = LUNDI
    p.resize(1300, 1000)
    p.show()
    p.rafraichir()
    application.processEvents()
    p.grille.repaint()
    yield p
    p.close()


def point(grille, jour: int, heure: int, minute: int = 0) -> QPoint:
    x = grille._x(jour) + grille._largeur_jour() / 2
    y = grille._y(time(heure, minute))
    return QPointF(x, y).toPoint()


def glisser(widget, depart: QPoint, arrivee: QPoint) -> None:
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=depart)
    QTest.mouseMove(widget, arrivee)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=arrivee)


# --- Gestes ----------------------------------------------------------------


def test_cliquer_glisser_demande_une_creation(page):
    recu = []
    page.grille.creation_demandee.disconnect()
    page.grille.creation_demandee.connect(lambda d, f: recu.append((d, f)))
    glisser(page.grille, point(page.grille, 1, 7), point(page.grille, 1, 12))
    assert recu == [(datetime(2026, 11, 17, 7), datetime(2026, 11, 17, 12))]


def test_simple_clic_propose_une_heure(page):
    recu = []
    page.grille.creation_demandee.disconnect()
    page.grille.creation_demandee.connect(lambda d, f: recu.append((d, f)))
    depart = point(page.grille, 3, 14)
    QTest.mouseClick(page.grille, Qt.MouseButton.LeftButton, pos=depart)
    assert recu == [(datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 15))]


def test_glisser_un_bloc_le_deplace(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(8), time(10), jour_semaine=0, matiere_id=maths.id))
    page.grille.repaint()
    recu = []
    page.grille.activite_deplacee.disconnect()
    page.grille.activite_deplacee.connect(lambda a, h, d, f: recu.append((d, f)))
    glisser(page.grille, point(page.grille, 0, 9), point(page.grille, 2, 10))  # lundi → mercredi, +1 h
    assert recu == [(datetime(2026, 11, 18, 9), datetime(2026, 11, 18, 11))]


def test_tirer_le_bord_bas_change_la_duree(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(8), time(10), jour_semaine=0, matiere_id=maths.id))
    page.grille.repaint()
    rect = page.grille._blocs_activites[0][0]
    bord = QPointF(rect.center().x(), rect.bottom() - 2).toPoint()
    recu = []
    page.grille.activite_deplacee.disconnect()
    page.grille.activite_deplacee.connect(lambda a, h, d, f: recu.append((d, f)))
    glisser(page.grille, bord, point(page.grille, 0, 12))
    assert recu == [(datetime(2026, 11, 16, 8), datetime(2026, 11, 16, 12))]


# --- Saisie rapide ------------------------------------------------------------


def test_saisie_rapide_reconnait_la_matiere(application, maths):
    formulaire = FormulaireRapide([maths], datetime(2026, 11, 16, 7), datetime(2026, 11, 16, 12))
    activite = formulaire.valeur()
    assert activite.nom == "Maths" and activite.matiere_id == maths.id
    assert activite.type is m.TypeActivite.COURS
    assert activite.jour_semaine == 0 and activite.heure_debut == time(7) and activite.heure_fin == time(12)


def test_saisie_rapide_activite_personnelle_une_seule_fois(application, maths):
    formulaire = FormulaireRapide([maths], datetime(2026, 11, 18, 20), datetime(2026, 11, 18, 21))
    formulaire.quoi.setEditText("Sport")
    formulaire.une_fois.setChecked(True)
    activite = formulaire.valeur()
    assert activite.type is m.TypeActivite.PERSONNEL and activite.matiere_id is None
    assert activite.date == date(2026, 11, 18) and activite.jour_semaine is None


def test_saisie_rapide_sans_nom_refusee(application):
    formulaire = FormulaireRapide([], datetime(2026, 11, 18, 20), datetime(2026, 11, 18, 21))
    with pytest.raises(ValueError):
        formulaire.valeur()


# --- Règles de la page -------------------------------------------------------


def test_creer_et_afficher_dans_la_grille(page, base, maths):
    assert page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    page.grille.repaint()
    assert len(base.activites.lister()) == 1
    assert len(page.grille._blocs_activites) == 1
    assert page.liste.table.rowCount() == 1  # la vue liste suit


def test_chevauchement_refuse(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    assert not page.creer(m.ActiviteFixe("Sport", time(11), time(13), jour_semaine=0))
    assert not page.creer(m.ActiviteFixe("Médecin", time(9), time(10), date=LUNDI + timedelta(weeks=2)))
    assert len(base.activites.lister()) == 1


def test_changer_horaire_toutes_les_semaines(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    activite = base.activites.lister()[0]
    horaire = page.grille.activites[0][1]
    assert page.changer_horaire(activite, horaire, datetime(2026, 11, 18, 8), datetime(2026, 11, 18, 11))
    modifiee = base.activites.obtenir(activite.id)
    assert modifiee.jour_semaine == 2 and modifiee.heure_debut == time(8) and modifiee.heure_fin == time(11)


def test_deplacement_sur_une_autre_activite_refuse(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    page.creer(m.ActiviteFixe("Sport", time(18), time(19), jour_semaine=1))
    sport = [a for a in base.activites.lister() if a.nom == "Sport"][0]
    horaire = [i for a, i in page.grille.activites if a.id == sport.id][0]
    assert not page.changer_horaire(sport, horaire, datetime(2026, 11, 16, 11), datetime(2026, 11, 16, 12))
    assert base.activites.obtenir(sport.id).jour_semaine == 1


def test_copier_sur_d_autres_jours(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    page.creer(m.ActiviteFixe("Sport", time(8), time(9), jour_semaine=3))
    maths_lundi = [a for a in base.activites.lister() if a.nom == "Maths"][0]
    assert page.copier(maths_lundi, [1, 2, 3, 4]) == 3  # jeudi déjà occupé par le sport
    jours = sorted(a.jour_semaine for a in base.activites.lister() if a.nom == "Maths")
    assert jours == [0, 1, 2, 4]


def test_annuler_un_seul_jour(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    activite = base.activites.lister()[0]
    page.annuler_occurrence(activite, LUNDI)
    assert page.grille.activites == []  # plus affichée cette semaine
    page.aller(1)
    assert len(page.grille.activites) == 1  # toujours là la semaine suivante


def test_supprimer(page, base, maths):
    page.creer(m.ActiviteFixe("Maths", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    page.supprimer(base.activites.lister()[0])
    assert base.activites.lister() == []


def test_vue_liste_et_grille(page):
    page.vue("Liste")
    assert page.pile.currentWidget() is page.liste
    page.vue("Grille")
    assert page.pile.currentWidget() is page.cadre_grille
