"""Minuteur de séance, copie automatique vers une clé USB / OneDrive, finitions (raccourcis, impression, agenda)."""

import string
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from planificateur import minuteur as mt
from planificateur import modeles as m
from planificateur import sauvegarde_externe as se
from planificateur.base import Base

DEBUT = datetime(2026, 11, 20, 20, 0)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "donnees" / "m.db")
    yield b
    b.fermer()


@pytest.fixture
def seance(base):
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    return base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, DEBUT, DEBUT + timedelta(minutes=60),
                                         matiere_id=maths.id))


class Horloge:
    def __init__(self, instant):
        self.instant = instant

    def __call__(self):
        return self.instant

    def avancer(self, minutes):
        self.instant += timedelta(minutes=minutes)


# --- Minuteur : logique ------------------------------------------------------------------------


def test_temps_travaille_sans_les_pauses(base, seance):
    etat = mt.demarrer(base, seance, DEBUT)
    etat.mettre_en_pause(DEBUT + timedelta(minutes=20))
    assert etat.minutes_travaillees(DEBUT + timedelta(minutes=30)) == 20  # en pause : le temps est figé
    etat.reprendre(DEBUT + timedelta(minutes=30))
    assert etat.minutes_travaillees(DEBUT + timedelta(minutes=45)) == 35


def test_pause_proposee_toutes_les_25_minutes(base, seance):
    etat = mt.demarrer(base, seance, DEBUT)
    assert not etat.pause_a_proposer(DEBUT + timedelta(minutes=24))
    assert etat.pause_a_proposer(DEBUT + timedelta(minutes=25))
    assert not etat.pause_a_proposer(DEBUT + timedelta(minutes=30))  # une seule fois par tranche
    assert etat.pause_a_proposer(DEBUT + timedelta(minutes=50))
    assert etat.fin_a_annoncer(seance, DEBUT + timedelta(minutes=60)) and not etat.fin_a_annoncer(seance, DEBUT)


def test_reprend_apres_fermeture(base, seance):
    etat = mt.demarrer(base, seance, DEBUT)
    etat.mettre_en_pause(DEBUT + timedelta(minutes=10))
    mt.enregistrer(base, etat)
    relu = mt.charger(base)
    assert relu == etat and relu.en_pause()
    base.seances.supprimer(seance.id)
    assert mt.charger(base) is None  # séance supprimée : minuteur oublié


@pytest.mark.parametrize("minutes, attendu", [
    (3, None), (30, (m.StatutSeance.PARTIELLE, 30)), (54, (m.StatutSeance.TERMINEE, 54)),
    (75, (m.StatutSeance.TERMINEE, 75)),
])
def test_pointage_selon_le_temps_travaille(seance, minutes, attendu):
    assert mt.statut_final(seance, minutes) == attendu


def test_terminer_pointe_la_seance(base, seance):
    etat = mt.demarrer(base, seance, DEBUT)
    pointee, minutes = mt.terminer(base, etat, DEBUT + timedelta(minutes=40))
    assert minutes == 40 and pointee.statut is m.StatutSeance.PARTIELLE and pointee.minutes_effectuees == 40
    assert mt.charger(base) is None


def test_seance_a_lancer(base, seance):
    assert mt.seance_a_lancer(base, DEBUT - timedelta(hours=3)) is None  # trop tôt
    assert mt.seance_a_lancer(base, DEBUT - timedelta(minutes=30)).id == seance.id
    assert mt.seance_a_lancer(base, DEBUT + timedelta(minutes=20)).id == seance.id  # en cours
    assert mt.seance_a_lancer(base, DEBUT + timedelta(minutes=61)) is None  # finie


# --- Minuteur : fenêtre --------------------------------------------------------------------------


def test_gestionnaire_complet(application, base, seance):
    from planificateur.ui.minuteur import GestionnaireMinuteur

    notifications = []
    gestionnaire = GestionnaireMinuteur(base, notifications.append)
    horloge = Horloge(DEBUT)
    gestionnaire.horloge = horloge
    pointees = []
    gestionnaire.seance_pointee.connect(lambda: pointees.append(True))
    assert gestionnaire.lancer(seance) and gestionnaire.fenetre.isVisible()
    horloge.avancer(25)
    gestionnaire.actualiser()
    assert [n.titre for n in notifications] == ["Petite pause ?"]
    gestionnaire.mettre_en_pause()
    horloge.avancer(5)
    gestionnaire.reprendre()
    horloge.avancer(35)
    gestionnaire.actualiser()
    assert "Temps prévu atteint" in [n.titre for n in notifications]
    assert gestionnaire.fenetre.temps.text() == "1:00:00"
    message = gestionnaire.terminer()
    assert "séance faite (60 min)" in message and pointees and not gestionnaire.fenetre.isVisible()
    assert base.seances.obtenir(seance.id).statut is m.StatutSeance.TERMINEE


def test_gestionnaire_reprise_et_annulation(application, base, seance):
    from planificateur.ui.minuteur import GestionnaireMinuteur

    mt.demarrer(base, seance, DEBUT)
    gestionnaire = GestionnaireMinuteur(base)
    gestionnaire.horloge = Horloge(DEBUT + timedelta(minutes=12))
    assert gestionnaire.reprendre_si_besoin() and gestionnaire.fenetre.temps.text() == "12:00"
    gestionnaire.confirmer = lambda titre, texte: True
    gestionnaire.annuler()
    assert not gestionnaire.actif() and mt.charger(base) is None
    assert base.seances.obtenir(seance.id).statut is m.StatutSeance.PREVUE  # rien de pointé


def test_bandeau_commencer_sur_l_accueil(application, base, seance):
    from planificateur.ui.fenetre import FenetrePrincipale

    fenetre = FenetrePrincipale(base)
    accueil = fenetre.pages["Accueil"]
    accueil.maintenant = DEBUT - timedelta(minutes=15)
    accueil.rafraichir()
    bandeau = accueil.bandeau_seance
    assert not bandeau.isHidden() and "Maths" in bandeau.texte.text() and "dans 15 min" in bandeau.texte.text()
    bandeau.bouton.click()
    assert fenetre.minuteur.actif() and "en cours" in bandeau.texte.text()
    fenetre.minuteur.confirmer = lambda *a: True
    fenetre.minuteur.annuler()
    fenetre._quitter_vraiment = True
    fenetre.close()


# --- Copie vers une clé USB / OneDrive -------------------------------------------------------


def test_copie_externe(base, tmp_path):
    cle = tmp_path / "CLE_USB" / "Sauvegardes"
    se.enregistrer(base, se.Reglages(str(cle), 7))
    assert se.copie_due(base, DEBUT)
    for jours in range(7):
        se.faire_copie(base, DEBUT + timedelta(days=jours, minutes=jours))
    copies = se.copies(cle)
    assert len(copies) == se.GARDER and copies[-1].name.startswith("PlanificateurEtudes_2026-11-26")
    assert not se.copie_due(base, DEBUT + timedelta(days=9))
    assert se.copie_due(base, DEBUT + timedelta(days=14))
    assert not se.en_retard(base, DEBUT + timedelta(days=14)) and se.en_retard(base, DEBUT + timedelta(days=21))
    assert "Dernière copie" in se.etat_texte(base, DEBUT + timedelta(days=7))


def test_cle_usb_debranchee(base):
    libre = next(f"{l}:\\" for l in reversed(string.ascii_uppercase) if not Path(f"{l}:\\").exists())
    se.enregistrer(base, se.Reglages(libre + "Sauvegardes", 7))
    with pytest.raises(se.DossierIndisponible, match="branchez"):
        se.faire_copie(base, DEBUT)
    assert se.charger(base).derniere is None  # sera retentée


def test_ecran_sauvegarde_copie_externe(application, base, tmp_path):
    from planificateur.ui.donnees import PageDonnees

    page = PageDonnees(base)
    messages = []
    page.avertir = lambda parent, titre, texte: messages.append(texte)
    page.definir_dossier_externe(base.chemin.parent)  # même dossier que les données : refusé
    assert messages and not se.charger(base).actif
    page.definir_dossier_externe(tmp_path / "USB")
    assert len(se.copies(tmp_path / "USB")) == 1 and "aujourd'hui" in page.etat_externe.text()
    page.frequence.setCurrentIndex(page.frequence.findData(1))
    assert se.charger(base).frequence_jours == 1
    page.definir_dossier_externe(None)
    assert not se.charger(base).actif and not page.bouton_copier.isEnabled()


# --- Finitions -------------------------------------------------------------------------------


def test_agenda_seulement_certaines_matieres(base, seance):
    from planificateur.export_ics import generer_ics

    physique = base.matieres.ajouter(m.Matiere("Physique"))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, DEBUT + timedelta(days=1), DEBUT + timedelta(days=1, hours=1),
                                  matiere_id=physique.id))
    base.epreuves.ajouter(m.Epreuve(physique.id, DEBUT + timedelta(days=2), DEBUT + timedelta(days=2, hours=2)))
    _, tout = generer_ics(base, DEBUT.date(), DEBUT.date() + timedelta(days=7), DEBUT)
    texte, physique_seule = generer_ics(base, DEBUT.date(), DEBUT.date() + timedelta(days=7), DEBUT,
                                        matieres_choisies={physique.id}, avec_epreuves=False, avec_alarmes=False)
    assert tout == 3 and physique_seule == 1 and "Maths" not in texte and "VALARM" not in texte


def test_impression_des_epreuves(application, base, seance, tmp_path):
    from planificateur.ui.export import exporter_epreuves_pdf

    base.epreuves.ajouter(m.Epreuve(seance.matiere_id, DEBUT + timedelta(days=3), DEBUT + timedelta(days=3, hours=2),
                                    intitule="Partiel"))
    base.epreuves.ajouter(m.Epreuve(seance.matiere_id, DEBUT - timedelta(days=3), DEBUT - timedelta(days=3, hours=-2)))
    chemin, nombre = exporter_epreuves_pdf(base, tmp_path / "epreuves.pdf", depuis=DEBUT.date())
    assert nombre == 1 and chemin.read_bytes().startswith(b"%PDF") and chemin.stat().st_size > 1000


def test_raccourcis_clavier(application, base, seance):
    from planificateur.ui.fenetre import FenetrePrincipale

    fenetre = FenetrePrincipale(base)
    fenetre.afficher("Planning")
    lundi = fenetre.pages["Planning"].lundi
    fenetre.raccourci_semaine(1)
    assert fenetre.pages["Planning"].lundi == lundi + timedelta(weeks=1)
    fenetre.raccourci_semaine(0)
    assert fenetre.pages["Planning"].lundi == lundi
    ajouts = []
    fenetre.pages["Épreuves"].ajouter = lambda: ajouts.append(True)
    fenetre.afficher("Épreuves")
    assert fenetre.ecran_courant() == "Épreuves"
    fenetre.raccourci_ajouter()
    assert ajouts == [True]
    assert fenetre.boutons["Accueil"].toolTip() == "Ctrl+1" and fenetre.boutons["Sauvegarde"].toolTip() == "Ctrl+0"
    fenetre._quitter_vraiment = True
    fenetre.close()
