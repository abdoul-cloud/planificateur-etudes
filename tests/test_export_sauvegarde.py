"""Export PDF/PNG, sauvegarde et restauration (cahier des charges, sections 10 et 11)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re  # noqa: E402
import sqlite3  # noqa: E402
from datetime import date, datetime, time  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtGui import QImage  # noqa: E402

from planificateur import modeles as m  # noqa: E402
from planificateur.base import VERSION_SCHEMA, Base, verifier_sauvegarde  # noqa: E402
from planificateur.ui.calendrier import PagePlanning, enregistrer_resultat, generer  # noqa: E402
from planificateur.ui.donnees import PageDonnees  # noqa: E402
from planificateur.ui.export import exporter_pdf, exporter_png  # noqa: E402

LUNDI = date(2026, 11, 16)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "donnees" / "donnees.db")
    yield b
    b.fermer()


@pytest.fixture
def remplie(base):
    maths = base.matieres.ajouter(m.Matiere("Maths", couleur="#4F5BD5"))
    base.activites.ajouter(m.ActiviteFixe("Algèbre", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))
    base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 120))
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    return base


# --- Export ----------------------------------------------------------------


def test_pdf_a4_paysage_une_page(application, remplie, tmp_path):
    chemin = exporter_pdf(remplie, LUNDI, tmp_path / "planning.pdf")
    contenu = chemin.read_bytes()
    assert contenu.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", contenu)) == 1
    # A4 paysage : 842 × 595 points
    boite = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", contenu)
    largeur, hauteur = float(boite.group(1)), float(boite.group(2))
    assert largeur == pytest.approx(842, abs=1) and hauteur == pytest.approx(595, abs=1)


def test_png_a4_paysage(application, remplie, tmp_path):
    chemin = exporter_png(remplie, LUNDI, tmp_path / "planning.png", dpi=100)
    image = QImage(str(chemin))
    assert not image.isNull()
    assert image.width() == int(297 / 25.4 * 100) and image.height() == int(210 / 25.4 * 100)


def test_export_d_une_semaine_vide(application, base, tmp_path):
    assert exporter_pdf(base, LUNDI, tmp_path / "vide.pdf").stat().st_size > 0


def test_bouton_exporter_de_la_page_planning(application, remplie, tmp_path):
    page = PagePlanning(remplie)
    page.avertir = lambda *args: None
    page.lundi = LUNDI
    assert page.exporter(tmp_path / "semaine.pdf", ouvrir=False).exists()
    assert page.exporter(tmp_path / "semaine.png", ouvrir=False).exists()
    assert "semaine.png" in page.message.text()


# --- Sauvegarde et restauration ---------------------------------------------


def test_sauvegarde_puis_restauration(remplie, tmp_path):
    copie = remplie.sauvegarder(tmp_path / "copie.db")
    assert copie.comptes["matieres"] == 1 and copie.comptes["seances"] > 0
    nombre_seances = copie.comptes["seances"]

    # Les données changent après la sauvegarde…
    remplie.matieres.ajouter(m.Matiere("Physique"))
    for s in remplie.seances.lister():
        remplie.seances.supprimer(s.id)

    securite = remplie.restaurer(tmp_path / "copie.db")
    assert [x.nom for x in remplie.matieres.lister()] == ["Maths"]
    assert len(remplie.seances.lister()) == nombre_seances
    # …et l'état d'avant la restauration est gardé
    assert securite.exists()
    assert verifier_sauvegarde(securite).comptes["matieres"] == 2


def test_donnees_restaurees_survivent_a_un_redemarrage(remplie, tmp_path):
    remplie.sauvegarder(tmp_path / "copie.db")
    remplie.matieres.ajouter(m.Matiere("Physique"))
    remplie.restaurer(tmp_path / "copie.db")
    chemin = remplie.chemin
    remplie.fermer()
    rouverte = Base(chemin)
    assert [x.nom for x in rouverte.matieres.lister()] == ["Maths"]
    rouverte.fermer()


def test_fichier_endommage_refuse_sans_toucher_aux_donnees(remplie, tmp_path):
    abime = tmp_path / "abime.db"
    abime.write_bytes(b"ceci n'est pas une base" * 100)
    with pytest.raises(ValueError, match="lisible"):
        remplie.restaurer(abime)
    assert len(remplie.matieres.lister()) == 1
    assert not list(remplie.dossier_sauvegardes.glob("avant-restauration*"))


def test_autre_base_sqlite_refusee(tmp_path):
    autre = tmp_path / "autre.db"
    cx = sqlite3.connect(autre)
    cx.execute("CREATE TABLE clients (id INTEGER)")
    cx.commit()
    cx.close()
    with pytest.raises(ValueError, match="pas une sauvegarde du planificateur"):
        verifier_sauvegarde(autre)


def test_sauvegarde_plus_recente_refusee(remplie, tmp_path):
    copie = tmp_path / "future.db"
    remplie.sauvegarder(copie)
    cx = sqlite3.connect(copie)
    cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA + 1}")
    cx.commit()
    cx.close()
    with pytest.raises(ValueError, match="plus récente"):
        verifier_sauvegarde(copie)


def test_sauvegarde_ancienne_mise_a_niveau(remplie, tmp_path):
    """Une sauvegarde au schéma 1 est restaurée puis migrée."""
    ancienne = tmp_path / "v1.db"
    cx = sqlite3.connect(ancienne)
    cx.executescript((Path(__file__).parents[1] / "planificateur" / "schema.sql").read_text(encoding="utf-8"))
    cx.execute("INSERT INTO matieres (nom) VALUES ('Histoire')")
    cx.execute("PRAGMA user_version = 1")
    cx.commit()
    cx.close()
    remplie.restaurer(ancienne)
    assert remplie.version == VERSION_SCHEMA
    assert [x.nom for x in remplie.matieres.lister()] == ["Histoire"]


def test_refus_de_sauvegarder_sur_le_fichier_en_cours(remplie):
    with pytest.raises(ValueError):
        remplie.sauvegarder(remplie.chemin)
    with pytest.raises(ValueError):
        remplie.restaurer(remplie.chemin)


def test_sauvegardes_automatiques_une_par_jour_dix_gardees(base):
    for n in range(12):
        base.sauvegarde_automatique(aujourd_hui=date(2026, 11, 1 + n))
    assert base.sauvegarde_automatique(aujourd_hui=date(2026, 11, 12)) is None  # déjà faite ce jour
    copies = sorted(f.name for f in base.dossier_sauvegardes.glob("auto_*.db"))
    assert len(copies) == 10
    assert copies[0] == "auto_2026-11-03.db" and copies[-1] == "auto_2026-11-12.db"


def test_page_sauvegarde(application, remplie, tmp_path):
    page = PageDonnees(remplie)
    page.avertir = lambda *args: None
    page.confirmer = lambda titre, texte: True
    recu = []
    page.donnees_restaurees.connect(lambda: recu.append(True))
    assert page.sauvegarder_vers(tmp_path / "cle_usb" / "sauvegarde")  # l'extension .db est ajoutée
    assert (tmp_path / "cle_usb" / "sauvegarde.db").exists()
    remplie.matieres.ajouter(m.Matiere("Physique"))
    assert page.restaurer_depuis(tmp_path / "cle_usb" / "sauvegarde.db")
    assert recu and len(remplie.matieres.lister()) == 1
    assert "restaurées" in page.message.text()
    page.confirmer = lambda titre, texte: False
    assert not page.restaurer_depuis(tmp_path / "cle_usb" / "sauvegarde.db")  # annulée par l'utilisateur


# --- Hors ligne ----------------------------------------------------------------


def test_aucun_acces_reseau_dans_le_code():
    """Le cahier des charges exige qu'aucune donnée ne quitte l'ordinateur."""
    interdits = re.compile(r"^\s*(import|from)\s+(socket|urllib|http|requests|ftplib|smtplib|ssl|PySide6\.QtNetwork)\b", re.M)
    for fichier in (Path(__file__).parents[1] / "planificateur").rglob("*.py"):
        assert not interdits.search(fichier.read_text(encoding="utf-8")), fichier.name
