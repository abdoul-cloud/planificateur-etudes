"""Matière terminée : plus de révisions ; suppression guidée d'une matière utilisée."""

import sqlite3
from datetime import date, datetime, time, timedelta

import pytest

from planificateur import modeles as m
from planificateur.base import VERSION_SCHEMA, Base
from planificateur.moteur.placement import planifier

LUNDI = date(2026, 11, 16)
DIMANCHE = LUNDI + timedelta(days=6)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "t.db")
    yield b
    b.fermer()


def test_matiere_terminee_ne_recoit_plus_de_revisions():
    filtre = m.Matiere("Filtre N", terminee=True, id=1)
    anglais = m.Matiere("Anglais", id=2)
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), [filtre, anglais])
    assert res.seances, "les autres matières sont toujours révisées"
    assert not [s for s in res.seances if s.matiere_id == filtre.id]


def test_echeance_d_une_matiere_terminee_reste_preparee():
    # Cas rare (épreuve encore à venir) : la date compte plus que l'état.
    filtre = m.Matiere("Filtre N", terminee=True, id=1)
    epreuve = m.Epreuve(1, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16), minutes_preparation=90, id=1)
    res = planifier(LUNDI, DIMANCHE, m.Preferences(), [filtre], epreuves=[epreuve])
    assert sum(s.minutes for s in res.seances if s.epreuve_id == 1) == 90
    assert not [s for s in res.seances if s.type is m.TypeSeance.REVISION]


def test_etat_enregistre_et_relu(base):
    matiere = base.matieres.ajouter(m.Matiere("Filtre N"))
    assert base.matieres.obtenir(matiere.id).terminee is False
    matiere.terminee = True
    base.matieres.modifier(matiere)
    assert base.matieres.obtenir(matiere.id).terminee is True


def test_migration_vers_la_version_3(tmp_path):
    chemin = tmp_path / "v2.db"
    ancienne = Base(chemin)
    ancienne.matieres.ajouter(m.Matiere("Filtre N"))
    ancienne._cx.execute("ALTER TABLE matieres DROP COLUMN terminee")
    ancienne._cx.execute("PRAGMA user_version = 2")
    ancienne._cx.commit()
    ancienne.fermer()
    base = Base(chemin)
    assert base.version == VERSION_SCHEMA == 3
    assert base.matieres.lister()[0].terminee is False
    base.fermer()


# --- Interface ----------------------------------------------------------------


@pytest.fixture
def remplie(base):
    filtre = base.matieres.ajouter(m.Matiere("Filtre N"))
    base.epreuves.ajouter(m.Epreuve(filtre.id, datetime(2026, 11, 14, 14), datetime(2026, 11, 14, 16)))
    base.activites.ajouter(m.ActiviteFixe("Filtre N", time(8), time(10), jour_semaine=1, matiere_id=filtre.id))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 17, 20), datetime(2026, 11, 17, 21),
                                  matiere_id=filtre.id))
    base.matieres.ajouter(m.Matiere("Anglais"))
    return base, filtre


def _page(application, base):
    from planificateur.ui.pages import PageMatieres

    page = PageMatieres(base)
    page.rafraichir()
    return page


def _selectionner(page, nom):
    ligne = next(n for n, x in enumerate(page.objets) if x.nom == nom)
    page.table.selectRow(ligne)


def test_suppression_d_une_matiere_utilisee_propose_de_la_terminer(application, remplie):
    base, filtre = remplie
    page = _page(application, base)
    vu = {}
    page.choisir_suppression = lambda matiere, usages: vu.update(usages) or "terminer"
    _selectionner(page, "Filtre N")
    page.supprimer()
    assert vu == {"épreuve(s)": 1, "cours / activité(s)": 1, "séance(s)": 1}
    assert base.matieres.obtenir(filtre.id).terminee is True
    assert base.epreuves.lister()  # l'historique reste
    assert page.objets[-1].nom == "Filtre N"  # les matières terminées passent en bas de la liste
    assert page.table.item(len(page.objets) - 1, 5).text().startswith("Terminée")


def test_tout_supprimer(application, remplie):
    base, filtre = remplie
    page = _page(application, base)
    page.choisir_suppression = lambda matiere, usages: "tout"
    _selectionner(page, "Filtre N")
    page.supprimer()
    assert base.matieres.obtenir(filtre.id) is None
    assert base.epreuves.lister() == [] and base.activites.lister() == [] and base.seances.lister() == []
    assert [x.nom for x in base.matieres.lister()] == ["Anglais"]


def test_annuler_ne_change_rien(application, remplie):
    base, filtre = remplie
    page = _page(application, base)
    page.choisir_suppression = lambda matiere, usages: None
    _selectionner(page, "Filtre N")
    page.supprimer()
    assert base.matieres.obtenir(filtre.id).terminee is False


def test_formulaire_coche_terminee(application):
    from planificateur.ui.formulaires import FormulaireMatiere

    formulaire = FormulaireMatiere(m.Matiere("Filtre N", id=3))
    formulaire.terminee.setChecked(True)
    assert formulaire.valeur().terminee is True
    assert FormulaireMatiere(m.Matiere("Filtre N", terminee=True, id=3)).valeur().terminee is True


def test_regenerer_retire_les_revisions_d_une_matiere_terminee(application, remplie):
    from planificateur.ui.calendrier import enregistrer_resultat, generer

    base, filtre = remplie
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    assert [s for s in base.seances.lister() if s.matiere_id == filtre.id and s.debut >= datetime(2026, 11, 16)]
    filtre.terminee = True
    base.matieres.modifier(filtre)
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    assert not [s for s in base.seances.lister() if s.matiere_id == filtre.id and s.debut >= datetime(2026, 11, 16)
                and s.origine is m.Origine.AUTO]
