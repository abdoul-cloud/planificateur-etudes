import sqlite3
from datetime import date, datetime, time

import pytest

from planificateur import modeles as m
from planificateur.base import VERSION_SCHEMA, Base


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "test.db")
    yield b
    b.fermer()


def test_schema_cree_a_la_bonne_version(base):
    assert base.version == VERSION_SCHEMA


def test_les_donnees_survivent_a_un_redemarrage(tmp_path):
    chemin = tmp_path / "donnees.db"
    b = Base(chemin)
    maths = b.matieres.ajouter(m.Matiere("Mathématiques", "MAT", 4, 5, 2))
    b.epreuves.ajouter(
        m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16))
    )
    b.fermer()

    b = Base(chemin)
    assert b.matieres.lister() == [maths]
    epreuve = b.epreuves.lister()[0]
    assert epreuve.debut == datetime(2026, 11, 19, 14)
    assert epreuve.type is m.TypeEpreuve.COMPOSITION
    b.fermer()


def test_modifier_et_supprimer(base):
    physique = base.matieres.ajouter(m.Matiere("Physique"))
    physique.maitrise = 5
    base.matieres.modifier(physique)
    assert base.matieres.obtenir(physique.id).maitrise == 5
    base.matieres.supprimer(physique.id)
    assert base.matieres.obtenir(physique.id) is None


def test_activite_recurrente_et_exception(base):
    cours = base.activites.ajouter(
        m.ActiviteFixe("Algèbre", time(8), time(10), jour_semaine=0, marge_avant_min=20)
    )
    base.exceptions.ajouter(m.ExceptionActivite(cours.id, date(2026, 11, 16)))
    relu = base.activites.obtenir(cours.id)
    assert relu == cours and relu.recurrente
    assert base.exceptions.lister()[0].date == date(2026, 11, 16)
    base.activites.supprimer(cours.id)
    assert base.exceptions.lister() == []


def test_travail_ne_garde_que_le_temps_restant(base):
    mat = base.matieres.ajouter(m.Matiere("Info"))
    travail = base.travaux.ajouter(
        m.Travail("Rapport", mat.id, datetime(2026, 11, 20, 18), 240)
    )
    assert travail.minutes_restantes == 240
    travail.minutes_restantes = 90
    base.travaux.modifier(travail)
    assert base.travaux.obtenir(travail.id).minutes_restantes == 90


def test_seance_verrouillee_et_statut_conserves(base):
    mat = base.matieres.ajouter(m.Matiere("Chimie"))
    seance = base.seances.ajouter(
        m.Seance(
            m.TypeSeance.REVISION,
            datetime(2026, 11, 17, 18),
            datetime(2026, 11, 17, 19, 30),
            matiere_id=mat.id,
            origine=m.Origine.MANUELLE,
            verrouillee=True,
        )
    )
    relue = base.seances.obtenir(seance.id)
    assert relue.verrouillee is True
    assert relue.origine is m.Origine.MANUELLE
    assert relue.minutes == 90


def test_matiere_utilisee_non_supprimable(base):
    mat = base.matieres.ajouter(m.Matiere("Histoire"))
    base.epreuves.ajouter(
        m.Epreuve(mat.id, datetime(2026, 11, 21, 9), datetime(2026, 11, 21, 11))
    )
    with pytest.raises(sqlite3.IntegrityError):
        base.matieres.supprimer(mat.id)


def test_supprimer_une_epreuve_supprime_ses_seances(base):
    mat = base.matieres.ajouter(m.Matiere("Anglais"))
    epreuve = base.epreuves.ajouter(
        m.Epreuve(mat.id, datetime(2026, 11, 21, 9), datetime(2026, 11, 21, 11))
    )
    base.seances.ajouter(
        m.Seance(
            m.TypeSeance.PREPARATION,
            datetime(2026, 11, 20, 17),
            datetime(2026, 11, 20, 18),
            epreuve_id=epreuve.id,
        )
    )
    base.epreuves.supprimer(epreuve.id)
    assert base.seances.lister() == []


def test_preferences_par_defaut_puis_enregistrees(base):
    assert base.preferences() == m.Preferences()
    prefs = m.Preferences(max_minutes_jour=300, jours_repos=[6], fin_journee=time(22))
    base.enregistrer_preferences(prefs)
    assert base.preferences() == prefs


@pytest.mark.parametrize(
    "fabrique",
    [
        lambda: m.Matiere("Maths", difficulte=6),
        lambda: m.Matiere(""),
        lambda: m.ActiviteFixe("Cours", time(10), time(8), jour_semaine=1),
        lambda: m.ActiviteFixe("Cours", time(8), time(10)),
        lambda: m.Epreuve(1, datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 9)),
        lambda: m.Travail("TD", 1, datetime(2026, 1, 1), 0),
        lambda: m.Seance(
            m.TypeSeance.PREPARATION, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10)
        ),
        lambda: m.Preferences(duree_min_seance=120, duree_max_seance=90),
    ],
)
def test_donnees_invalides_refusees(fabrique):
    with pytest.raises(ValueError):
        fabrique()
