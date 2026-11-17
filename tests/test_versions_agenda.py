"""Nouvelles versions (GitHub simulé : aucun accès réseau) et export agenda .ics."""

import json
from datetime import date, datetime, timedelta

import pytest

from planificateur import __version__
from planificateur import mises_a_jour as mj
from planificateur import modeles as m
from planificateur.base import Base
from planificateur.export_ics import generer_ics, plier

MAINTENANT = datetime(2026, 11, 17, 9, 0)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "v.db")
    yield b
    b.fermer()


def faux_github(tag="v9.0.0", exe=True, erreur=None):
    demandes = []

    def transport(url):
        demandes.append(url)
        if erreur:
            raise mj.ErreurMiseAJour(erreur)
        assets = [{"name": f"Installer-PlanificateurEtudes-{tag[1:]}.exe",
                   "browser_download_url": f"https://github.com/x/releases/download/{tag}/setup.exe"}] if exe else []
        return json.dumps({"tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}",
                           "assets": assets, "body": "Nouveautés"}).encode()

    transport.demandes = demandes
    return transport


# --- Versions -----------------------------------------------------------------------------


def test_comparaison_des_numeros():
    assert mj.numero("v0.10.2") == (0, 10, 2)
    assert mj.plus_recente("0.10.0", "0.9.9") and mj.plus_recente("v1.0", "0.6.1")
    assert not mj.plus_recente("0.6.1", "0.6.1") and not mj.plus_recente("0.6.0", "0.6.1")
    assert not mj.plus_recente("pas-une-version", "0.1.0")


def test_nouvelle_version_trouvee(base):
    transport = faux_github("v9.0.0")
    version = mj.verifier(base, MAINTENANT, transport)
    assert version.numero == "9.0.0" and version.telechargement.endswith("setup.exe")
    assert transport.demandes == [mj.URL_DERNIERE]  # une seule question, à GitHub
    assert mj.charger(base).derniere_verification == MAINTENANT


def test_sans_installateur_on_propose_la_page(base):
    version = mj.verifier(base, MAINTENANT, faux_github("v9.0.0", exe=False))
    assert version.telechargement == version.page


def test_deja_a_jour(base):
    assert mj.verifier(base, MAINTENANT, faux_github(f"v{__version__}")) is None


def test_au_plus_une_fois_par_jour_et_desactivable(base):
    assert mj.a_verifier(base, MAINTENANT)
    mj.verifier(base, MAINTENANT, faux_github(f"v{__version__}"))
    assert not mj.a_verifier(base, MAINTENANT + timedelta(hours=3))
    assert mj.a_verifier(base, MAINTENANT + timedelta(hours=21))
    reglages = mj.charger(base)
    reglages.actif = False
    mj.enregistrer(base, reglages)
    assert not mj.a_verifier(base, MAINTENANT + timedelta(days=5))


def test_version_ignoree(base):
    mj.ignorer(base, "9.0.0")
    assert mj.verifier(base, MAINTENANT, faux_github("v9.0.0")) is None
    assert mj.verifier(base, MAINTENANT, faux_github("v9.0.0"), forcer=True) is not None  # « Vérifier maintenant »
    assert mj.verifier(base, MAINTENANT, faux_github("v9.1.0")).numero == "9.1.0"


def test_reponse_illisible(base):
    with pytest.raises(mj.ErreurMiseAJour):
        mj.verifier(base, MAINTENANT, lambda url: b"<html>")


def test_fenetre_bandeau_et_preferences(application, base, monkeypatch):
    from planificateur.ui import fond
    from planificateur.ui.fenetre import FenetrePrincipale

    monkeypatch.setattr(fond, "SYNCHRONE", True)
    fenetre = FenetrePrincipale(base)
    fenetre._transport_maj = {"transport": faux_github("v9.0.0")}
    fenetre.verifier_mises_a_jour()
    bandeau = fenetre.pages["Accueil"].bandeau_version
    assert not bandeau.isHidden() and "9.0.0" in bandeau.texte.text()
    bandeau.ignorer()
    assert bandeau.isHidden() and mj.charger(base).version_ignoree == "9.0.0"

    resultats = []
    section = fenetre.pages["Préférences"].section_versions
    section.verificateur = lambda forcer, rapport: fenetre.verifier_mises_a_jour(forcer, rapport)
    fenetre._transport_maj = {"transport": faux_github(erreur="Pas de connexion à Internet")}
    section.afficher_resultat = lambda v, e="": resultats.append((v, e))
    section.verifier_maintenant()
    assert resultats == [(None, "Pas de connexion à Internet")]
    section.actif.setChecked(False)
    assert mj.charger(base).actif is False
    fenetre._quitter_vraiment = True
    fenetre.close()


def test_verification_automatique_silencieuse_sans_internet(application, base, monkeypatch):
    from planificateur.ui import fond
    from planificateur.ui.fenetre import FenetrePrincipale

    monkeypatch.setattr(fond, "SYNCHRONE", True)
    fenetre = FenetrePrincipale(base)
    fenetre._transport_maj = {"transport": faux_github(erreur="Pas de connexion à Internet")}
    fenetre.verifier_mises_a_jour()  # aucune fenêtre d'erreur, aucun bandeau
    assert fenetre.pages["Accueil"].bandeau_version.isHidden()
    fenetre._quitter_vraiment = True
    fenetre.close()


# --- Agenda .ics ----------------------------------------------------------------------------


@pytest.fixture
def remplie(base):
    reseaux = base.matieres.ajouter(m.Matiere("Réseaux, informatique"))
    ds = base.epreuves.ajouter(m.Epreuve(reseaux.id, datetime(2026, 11, 21, 14), datetime(2026, 11, 21, 17),
                                         type=m.TypeEpreuve.DEVOIR_SURVEILLE, chapitres="TCP; IP"))
    base.seances.ajouter(m.Seance(m.TypeSeance.PREPARATION, datetime(2026, 11, 19, 20), datetime(2026, 11, 19, 21, 30),
                                  matiere_id=reseaux.id, epreuve_id=ds.id))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 18, 20), datetime(2026, 11, 18, 21),
                                  matiere_id=reseaux.id, statut=m.StatutSeance.MANQUEE))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 12, 30, 20), datetime(2026, 12, 30, 21),
                                  matiere_id=reseaux.id))  # hors période
    return base


def test_export_ics(remplie):
    texte, nombre = generer_ics(remplie, date(2026, 11, 16), date(2026, 11, 29), MAINTENANT)
    assert nombre == 2  # la préparation et le DS ; ni la séance manquée, ni celle hors période
    assert texte.startswith("BEGIN:VCALENDAR\r\n") and texte.endswith("END:VCALENDAR\r\n")
    deplie = texte.replace("\r\n ", "")
    assert "DTSTART:20261119T200000" in deplie and "DTEND:20261119T213000" in deplie
    assert "SUMMARY:Préparation · Réseaux\\, informatique" in deplie
    assert "SUMMARY:⚑ Devoir surveillé · Réseaux\\, informatique" in deplie
    assert "Chapitres : TCP\\; IP" in deplie
    assert deplie.count("BEGIN:VEVENT") == 2 and deplie.count("BEGIN:VALARM") == 2
    assert "DTSTAMP:" in deplie and "Z\r\n" in deplie
    uids = [l for l in deplie.split("\r\n") if l.startswith("UID:")]
    assert len(set(uids)) == 2 and all(u.endswith("@planificateur-etudes") for u in uids)
    for ligne in texte.split("\r\n"):
        assert len(ligne.encode("utf-8")) <= 75


def test_pliage_sans_couper_un_accent():
    long = "DESCRIPTION:" + "é" * 100
    plie = plier(long)
    assert plie.replace("\r\n ", "") == long
    assert all(len(l.encode("utf-8")) <= 75 for l in plie.split("\r\n"))


def test_export_depuis_le_planning(application, remplie, tmp_path):
    from planificateur.ui.calendrier import PagePlanning

    page = PagePlanning(remplie)
    chemin = tmp_path / "agenda.ics"
    nombre = page.exporter_agenda(chemin)
    assert chemin.exists() and nombre == len([x for x in chemin.read_text(encoding="utf-8").split("\n")
                                              if x.startswith("BEGIN:VEVENT")])
