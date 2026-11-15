"""Suivi des séances et replanification (cahier des charges, sections 6.5 et 11)."""

from datetime import date, datetime, time, timedelta

import pytest

from planificateur import modeles as m
from planificateur.base import Base
from planificateur.moteur.placement import planifier
from planificateur.suivi import a_pointer, bilan, marquer, mettre_a_jour_etats, minutes_faites
from planificateur.ui.calendrier import enregistrer_resultat, generer

LUNDI = date(2026, 11, 16)
SANS_REVISION = m.Preferences(minutes_revision_semaine=0, plages_garanties=[])


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "suivi.db")
    b.enregistrer_preferences(SANS_REVISION)
    yield b
    b.fermer()


@pytest.fixture
def maths(base):
    return base.matieres.ajouter(m.Matiere("Maths"))


def seance_travail(base, travail, jour=LUNDI, heure=19, minutes=90):
    debut = datetime.combine(jour, time(heure))
    return base.seances.ajouter(
        m.Seance(m.TypeSeance.TRAVAIL, debut, debut + timedelta(minutes=minutes), matiere_id=travail.matiere_id, travail_id=travail.id)
    )


# --- Pointer une séance ---------------------------------------------------


def test_seance_faite_diminue_le_temps_restant(base, maths):
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 240))
    seance = seance_travail(base, travail)
    marquer(base, seance, m.StatutSeance.TERMINEE)
    travail = base.travaux.obtenir(travail.id)
    assert travail.minutes_restantes == 150
    assert travail.etat is m.EtatTravail.EN_COURS


def test_seance_partielle_compte_le_temps_reel(base, maths):
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 240))
    seance = seance_travail(base, travail)
    marquer(base, seance, m.StatutSeance.PARTIELLE, 30)
    assert base.travaux.obtenir(travail.id).minutes_restantes == 210
    assert minutes_faites(base.seances.obtenir(seance.id)) == 30


def test_changer_d_avis_retablit_le_temps(base, maths):
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 240))
    seance = seance_travail(base, travail)
    seance = marquer(base, seance, m.StatutSeance.TERMINEE)
    seance = marquer(base, seance, m.StatutSeance.PARTIELLE, 45)
    assert base.travaux.obtenir(travail.id).minutes_restantes == 195
    marquer(base, seance, m.StatutSeance.PREVUE)
    travail = base.travaux.obtenir(travail.id)
    assert travail.minutes_restantes == 240
    assert travail.etat is m.EtatTravail.A_FAIRE


def test_travail_fini_passe_a_termine(base, maths):
    travail = base.travaux.ajouter(m.Travail("TD", maths.id, datetime(2026, 11, 20, 18), 90))
    marquer(base, seance_travail(base, travail), m.StatutSeance.TERMINEE)
    travail = base.travaux.obtenir(travail.id)
    assert travail.minutes_restantes == 0
    assert travail.etat is m.EtatTravail.TERMINE


def test_travail_rendu_garde_son_etat(base, maths):
    travail = base.travaux.ajouter(m.Travail("TD", maths.id, datetime(2026, 11, 20, 18), 90, etat=m.EtatTravail.RENDU))
    marquer(base, seance_travail(base, travail), m.StatutSeance.TERMINEE)
    assert base.travaux.obtenir(travail.id).etat is m.EtatTravail.RENDU


def test_partielle_sans_temps_valide_refusee(base, maths):
    travail = base.travaux.ajouter(m.Travail("TD", maths.id, datetime(2026, 11, 20, 18), 90))
    seance = seance_travail(base, travail)
    for minutes in (None, 0, 90, 120):
        with pytest.raises(ValueError):
            marquer(base, seance, m.StatutSeance.PARTIELLE, minutes)


# --- Replanification ------------------------------------------------------


def test_seance_manquee_veille_d_echeance_replanifiee(base, maths):
    """Scénario du cahier : une séance manquée la veille d'une échéance."""
    epreuve = base.epreuves.ajouter(
        m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16), minutes_preparation=180)
    )
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    prevues = [s for s in base.seances.lister() if s.epreuve_id == epreuve.id]
    assert sum(s.minutes for s in prevues) == 180
    veille = max(prevues, key=lambda s: s.debut)

    marquer(base, veille, m.StatutSeance.MANQUEE)
    maintenant = veille.fin
    resultat = generer(base, maintenant)
    enregistrer_resultat(base, resultat)

    actives = [s for s in base.seances.lister()
               if s.epreuve_id == epreuve.id and s.statut is not m.StatutSeance.MANQUEE]
    assert sum(s.minutes for s in actives) == 180  # le temps manqué est replacé
    assert all(s.fin <= epreuve.debut for s in actives)
    assert all(s.debut >= maintenant for s in actives if s.id not in {p.id for p in prevues})
    assert base.seances.obtenir(veille.id).statut is m.StatutSeance.MANQUEE  # gardée dans l'historique


def test_seance_terminee_jamais_deplacee(base, maths):
    base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 14), datetime(2026, 11, 19, 16)))
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    premiere = min(base.seances.lister(), key=lambda s: s.debut)
    faite = marquer(base, premiere, m.StatutSeance.TERMINEE)
    enregistrer_resultat(base, generer(base, datetime(2026, 11, 16)))
    assert base.seances.obtenir(faite.id) == faite


def test_seance_de_travail_non_pointee_supposee_faite(base, maths):
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 180))
    passee = seance_travail(base, travail, jour=LUNDI, heure=19, minutes=90)
    resultat = generer(base, datetime(2026, 11, 17, 8))
    assert sum(s.minutes for s in resultat.seances if s.travail_id == travail.id) == 90
    assert passee in resultat.conservees


def test_nouvelle_activite_sur_une_seance_manuelle_signalee(base, maths):
    """Scénario du cahier : une activité fixe ajoutée après la génération."""
    debut = datetime(2026, 11, 17, 19)
    manuelle = base.seances.ajouter(m.Seance(
        m.TypeSeance.REVISION, debut, debut + timedelta(hours=1), matiere_id=maths.id,
        origine=m.Origine.MANUELLE, verrouillee=True,
    ))
    base.activites.ajouter(m.ActiviteFixe("Réunion", time(18, 30), time(20), date=debut.date()))
    resultat = generer(base, datetime(2026, 11, 16))
    assert [s.id for s in resultat.conflits] == [manuelle.id]
    assert manuelle.id in {s.id for s in resultat.conservees}  # signalée, pas déplacée


def test_conflits_calcules_par_le_moteur():
    seance = m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 16, 19), datetime(2026, 11, 16, 20),
                      origine=m.Origine.MANUELLE, id=1)
    cours = m.ActiviteFixe("Cours du soir", time(19), time(21), jour_semaine=0)
    resultat = planifier(LUNDI, LUNDI, SANS_REVISION, activites=[cours], seances_existantes=[seance])
    assert resultat.conflits == [seance]


# --- États, séances à pointer, bilan ---------------------------------------


def test_epreuves_passees_marquees(base, maths):
    passee = base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 10, 8), datetime(2026, 11, 10, 10)))
    a_venir = base.epreuves.ajouter(m.Epreuve(maths.id, datetime(2026, 11, 19, 8), datetime(2026, 11, 19, 10)))
    assert mettre_a_jour_etats(base, datetime(2026, 11, 16)) == 1
    assert base.epreuves.obtenir(passee.id).etat is m.EtatEpreuve.PASSEE
    assert base.epreuves.obtenir(a_venir.id).etat is m.EtatEpreuve.A_PREPARER


def test_seances_a_pointer(base, maths):
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 20, 18), 300))
    hier = seance_travail(base, travail, jour=LUNDI)
    demain = seance_travail(base, travail, jour=LUNDI + timedelta(days=2))
    vieille = seance_travail(base, travail, jour=LUNDI - timedelta(days=10))
    attente = a_pointer(base, datetime(2026, 11, 17, 12))
    assert [s.id for s in attente] == [hier.id]
    marquer(base, hier, m.StatutSeance.TERMINEE)
    assert a_pointer(base, datetime(2026, 11, 17, 12)) == []
    assert demain and vieille


def test_bilan_de_la_semaine(base, maths):
    physique = base.matieres.ajouter(m.Matiere("Physique"))
    travail = base.travaux.ajouter(m.Travail("Rapport", maths.id, datetime(2026, 11, 22, 18), 600))
    faite = seance_travail(base, travail, jour=LUNDI)  # 90 min
    partielle = seance_travail(base, travail, jour=LUNDI + timedelta(days=1))  # 90 min
    manquee = seance_travail(base, travail, jour=LUNDI + timedelta(days=2))  # 90 min
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 20, 19), datetime(2026, 11, 20, 20),
                                  matiere_id=physique.id))  # à venir, 60 min
    marquer(base, faite, m.StatutSeance.TERMINEE)
    marquer(base, partielle, m.StatutSeance.PARTIELLE, 30)
    marquer(base, manquee, m.StatutSeance.MANQUEE)

    resultat = bilan(base, LUNDI, LUNDI + timedelta(days=6), datetime(2026, 11, 19, 12))
    assert resultat.prevu == 330
    assert resultat.fait == 120
    assert resultat.manque == 90
    assert resultat.a_venir == 60
    assert resultat.taux == pytest.approx(120 / 270)
    assert resultat.par_matiere[maths.id].fait == 120
    assert resultat.par_matiere[physique.id].prevu == 60
    assert [s.id for s in resultat.manquees] == [manquee.id]


def test_bilan_vide(base):
    resultat = bilan(base, LUNDI, LUNDI + timedelta(days=6))
    assert resultat.prevu == 0 and resultat.taux is None
