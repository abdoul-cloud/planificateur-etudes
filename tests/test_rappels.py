"""Rappels, notifications, démarrage avec Windows, instance unique, premier lancement."""

import sys
from datetime import date, datetime, time, timedelta

import pytest

from planificateur import modeles as m
from planificateur import rappels, systeme
from planificateur.base import Base
from planificateur.rappels import ReglagesRappels, rappels_dus

JEUDI = date(2026, 11, 19)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "r.db")
    yield b
    b.fermer()


@pytest.fixture
def remplie(base):
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 18, 20), datetime(2026, 11, 18, 21, 30),
                                  matiere_id=maths.id))
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))
    base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 120))
    return base


def cles(liste):
    return [r.cle.split(":")[0] for r in liste]


# --- Calcul des rappels -------------------------------------------------------------


def test_rappel_avant_une_seance(remplie):
    assert cles(rappels_dus(remplie, datetime(2026, 11, 18, 19, 49), deja=set())) == []
    [rappel] = rappels_dus(remplie, datetime(2026, 11, 18, 19, 50), deja=set())
    assert rappel.titre == "Séance dans 10 min" and "Maths à 20:00" in rappel.texte and "1 h 30" in rappel.texte
    assert rappels_dus(remplie, datetime(2026, 11, 18, 20, 15), deja=set()) == []  # trop tard : on n'insiste pas


def test_rappel_la_veille_d_une_epreuve(remplie):
    [rappel] = rappels_dus(remplie, datetime(2026, 11, 18, 19, 5), deja=set())
    assert rappel.titre == "Épreuve demain" and "demain à 14:00" in rappel.texte and rappel.ecran == "Épreuves"


def test_rappel_avant_un_travail(remplie):
    [rappel] = rappels_dus(remplie, datetime(2026, 11, 18, 18, 0), deja=set())
    assert rappel.titre == "À rendre dans 2 jours" and "Rapport" in rappel.texte and "vendredi" in rappel.texte
    travail = remplie.travaux.lister()[0]
    travail.etat = m.EtatTravail.RENDU
    remplie.travaux.modifier(travail)
    assert rappels_dus(remplie, datetime(2026, 11, 18, 18, 0), deja=set()) == []


def test_point_du_soir_seulement_s_il_reste_a_pointer(remplie):
    soir = datetime(2026, 11, 18, 22, 30)
    assert "bilan" in cles(rappels_dus(remplie, soir, deja=set()))
    seance = remplie.seances.lister()[0]
    seance.statut = m.StatutSeance.TERMINEE
    remplie.seances.modifier(seance)
    assert "bilan" not in cles(rappels_dus(remplie, soir, deja=set()))


def test_jamais_deux_fois_le_meme_rappel(remplie):
    instant = datetime(2026, 11, 18, 19, 50)
    premier = rappels_dus(remplie, instant)
    rappels.marquer_envoyes(remplie, [r.cle for r in premier], instant)
    assert premier and rappels_dus(remplie, instant + timedelta(minutes=1)) == []


def test_rappels_desactives(remplie):
    assert rappels_dus(remplie, datetime(2026, 11, 18, 19, 50), ReglagesRappels(actif=False), set()) == []
    assert rappels_dus(remplie, datetime(2026, 11, 18, 19, 50), ReglagesRappels(seance_minutes=0), set()) == []


def test_reglages_enregistres(base):
    assert rappels.charger(base) == ReglagesRappels()
    reglages = ReglagesRappels(seance_minutes=15, heure_veille=time(20, 30), bilan_soir=False, arriere_plan=False)
    rappels.enregistrer(base, reglages)
    assert rappels.charger(base) == reglages


def test_memoire_des_envois_limitee_a_trois_jours(base):
    rappels.marquer_envoyes(base, ["ancien"], datetime(2026, 11, 10, 8))
    rappels.marquer_envoyes(base, ["recent"], datetime(2026, 11, 18, 8))
    assert rappels.deja_envoyes(base) == {"recent"}


# --- Démarrage avec Windows (faux registre : rien n'est écrit sur l'ordinateur) -------------


class FauxRegistre:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.valeurs = {}

    class _Cle:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def OpenKey(self, racine, chemin):
        return self._Cle()

    CreateKey = OpenKey

    def QueryValueEx(self, cle, nom):
        if nom not in self.valeurs:
            raise OSError("absent")
        return self.valeurs[nom], 1

    def SetValueEx(self, cle, nom, reserve, type_, valeur):
        self.valeurs[nom] = valeur

    def DeleteValue(self, cle, nom):
        self.valeurs.pop(nom)


def test_demarrage_avec_windows(monkeypatch):
    faux = FauxRegistre()
    monkeypatch.setattr(systeme, "winreg", faux)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Programmes\PlanificateurEtudes.exe")
    assert systeme.definir_demarrage(True)
    assert faux.valeurs["PlanificateurEtudes"] == r'"C:\Programmes\PlanificateurEtudes.exe" --arriere-plan'
    assert not systeme.definir_demarrage(False) and faux.valeurs == {}


def test_pas_de_demarrage_automatique_depuis_le_code_source(monkeypatch):
    monkeypatch.setattr(systeme, "winreg", FauxRegistre())
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert systeme.commande_demarrage() is None
    with pytest.raises(RuntimeError):
        systeme.definir_demarrage(True)


@pytest.mark.skipif(sys.platform != "win32", reason="propre à Windows")
def test_une_seule_application_ouverte():
    nom = f"PlanificateurEtudesTest{datetime.now():%H%M%S%f}"
    premiere, seconde = systeme.InstanceUnique(nom), systeme.InstanceUnique(nom)
    assert premiere.premiere and not seconde.premiere
    assert not premiere.a_ete_reveillee()
    seconde.reveiller_l_autre()
    assert premiere.a_ete_reveillee() and not premiere.a_ete_reveillee()  # une seule fois


# --- Interface ------------------------------------------------------------------------------


def test_notificateur_envoie_et_retient(application, remplie):
    from planificateur.ui.notifications import Notificateur

    notificateur = Notificateur(remplie)
    notificateur.maintenant = datetime(2026, 11, 18, 19, 52)
    envoyes = notificateur.verifier()
    assert [r.titre for r in envoyes] == ["Séance dans 10 min"] and notificateur.envoyes == envoyes
    assert notificateur.verifier() == []  # déjà envoyé, même après redémarrage (mémorisé dans la base)


def test_section_rappels(application, base):
    from planificateur.ui.preferences import SectionRappels

    section = SectionRappels(base)
    section.seance_minutes.setValue(20)
    section.veille.setChecked(False)
    reglages = rappels.charger(base)
    assert reglages.seance_minutes == 20 and reglages.veille_epreuve is False
    section.actif.setChecked(False)
    assert rappels.charger(base).actif is False and not section.seance.isEnabled()
    if systeme.commande_demarrage() is None:
        assert not section.demarrage.isEnabled()  # depuis le code source


def test_premier_lancement_enregistre_horaires_et_matieres(application, base):
    from planificateur.ui.premier_lancement import DialoguePremierLancement, besoin_premier_lancement
    from planificateur.ui.commun import vers_qtime

    assert besoin_premier_lancement(base)
    dialogue = DialoguePremierLancement(base)
    dialogue.lever.setTime(vers_qtime(time(6, 30)))
    dialogue.coucher.setTime(vers_qtime(time(22)))
    dialogue.soirees.setChecked(False)
    for nom in ("Mathématiques", "Physique", "mathématiques"):  # le doublon est ignoré
        dialogue.nom_matiere.setText(nom)
        dialogue.ajouter_matiere()
    dialogue.nom_matiere.setText("Anglais")  # tapée sans cliquer sur Ajouter : comptée quand même
    dialogue.aller(2)
    dialogue.terminer("grille")
    preferences = base.preferences()
    assert preferences.debut_journee == time(6, 30) and preferences.fin_journee == time(22)
    assert preferences.plages_garanties == []
    assert sorted(x.nom for x in base.matieres.lister()) == ["Anglais", "Mathématiques", "Physique"]
    assert dialogue.choix_emploi == "grille" and not besoin_premier_lancement(base)


def test_premier_lancement_passe(application, base):
    from planificateur.ui.premier_lancement import DialoguePremierLancement, besoin_premier_lancement

    dialogue = DialoguePremierLancement(base)
    dialogue.terminer(None)
    assert not besoin_premier_lancement(base) and dialogue.choix_emploi is None
    assert base.preferences().plages_garanties  # soirées garanties gardées par défaut


def test_premier_lancement_pas_propose_avec_des_donnees(application, base):
    from planificateur.ui.premier_lancement import besoin_premier_lancement

    base.matieres.ajouter(m.Matiere("Maths"))
    assert not besoin_premier_lancement(base)


def test_fenetre_version_et_lien_de_retour(application, base):
    from PySide6.QtWidgets import QLabel, QPushButton

    from planificateur import __version__
    from planificateur.ui.fenetre import URL_PROBLEME, FenetrePrincipale

    fenetre = FenetrePrincipale(base)
    textes = [w.text() for w in fenetre.findChildren(QLabel)]
    assert any(f"Version {__version__}" in t for t in textes)
    assert any("Signaler" in b.text() for b in fenetre.findChildren(QPushButton))
    assert URL_PROBLEME.startswith("https://github.com/abdoul-cloud/planificateur-etudes/issues")
    assert fenetre.pages["Préférences"].section_rappels.notificateur is fenetre.notificateur
    if not fenetre.notificateur.disponible:
        assert not fenetre.notificateur.garder_en_arriere_plan()  # sans icône possible, fermer quitte vraiment
