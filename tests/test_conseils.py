"""Conseils du Bilan, à partir des séances pointées."""

from datetime import datetime, time, timedelta

import pytest

from planificateur import conseils as c
from planificateur import modeles as m
from planificateur.base import Base

MAINTENANT = datetime(2026, 11, 30, 9, 0)  # un lundi matin


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "c.db")
    yield b
    b.fermer()


def seance(base, jour, heure, statut, matiere_id=None, minutes=60, effectuees=None):
    debut = datetime.combine(jour, time(heure))
    return base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, debut, debut + timedelta(minutes=minutes),
                                         matiere_id=matiere_id, statut=statut, minutes_effectuees=effectuees))


def lundis(n):
    return [(MAINTENANT - timedelta(weeks=k + 1)).date() for k in range(n)]


def cles(liste):
    return [x.cle.split(":")[0] for x in liste]


def test_trop_peu_de_seances(base):
    seance(base, lundis(1)[0], 20, m.StatutSeance.TERMINEE)
    [conseil] = c.conseils(base, MAINTENANT)
    assert conseil.cle == "attente" and "1 sur 6" in conseil.texte and conseil.appliquer is None


def test_creneau_souvent_manque_et_reglage_applique(base):
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    for jour in lundis(3):  # lundi soir : 3 manquées sur 3
        seance(base, jour, 20, m.StatutSeance.MANQUEE, maths.id, minutes=90)
    for jour in lundis(3):  # mardi après-midi : faites
        seance(base, jour + timedelta(days=1), 14, m.StatutSeance.TERMINEE, maths.id)
    conseil = next(x for x in c.conseils(base, MAINTENANT) if x.cle.startswith("creneau"))
    assert conseil.cle == "creneau:0:2" and "lundi soir" in conseil.titre and "3 séances sur 3" in conseil.texte
    assert conseil.action == "Éviter le lundi 20:00 – 22:00"
    # Les soirées 20 h – 23 h sont garanties par défaut : le lundi doit en sortir, sinon il serait rempli quand même
    message = conseil.appliquer(base)
    preferences = base.preferences()
    assert m.PlageHebdo([0], time(20), time(22)) in preferences.plages_evitees
    assert all(0 not in p.jours for p in preferences.plages_garanties)
    assert [1, 2, 3, 4] == preferences.plages_garanties[0].jours
    assert "n'est plus garanti" in message


def test_seances_trop_longues(base):
    for n, jour in enumerate(lundis(4)):
        seance(base, jour, 14, m.StatutSeance.PARTIELLE, minutes=90, effectuees=50)
        seance(base, jour + timedelta(days=2), 14, m.StatutSeance.TERMINEE, minutes=90)
    conseil = next(x for x in c.conseils(base, MAINTENANT) if x.cle == "duree")
    assert "50 min" in conseil.texte and conseil.action == "Séances de 45 min au plus"
    conseil.appliquer(base)
    assert base.preferences().duree_max_seance == 45 and base.preferences().duree_min_seance == 45


def test_rythme_trop_charge(base):
    for n, jour in enumerate(lundis(4)):
        seance(base, jour, 9, m.StatutSeance.MANQUEE)
        seance(base, jour + timedelta(days=n % 3 + 1), 15, m.StatutSeance.MANQUEE)
    seance(base, lundis(1)[0] + timedelta(days=4), 17, m.StatutSeance.TERMINEE)
    conseil = next(x for x in c.conseils(base, MAINTENANT) if x.cle == "rythme")
    assert conseil.ton == "attention"
    conseil.appliquer(base)
    assert base.preferences().minutes_revision_semaine == 225  # 300 min - 25 %


def test_bravo_quand_tout_est_fait(base):
    for jour in lundis(4):
        for decalage in range(3):
            seance(base, jour + timedelta(days=decalage), 18, m.StatutSeance.TERMINEE)
    liste = c.conseils(base, MAINTENANT)
    assert cles(liste) == ["bravo"] and liste[0].ton == "bravo"


def test_seances_a_pointer(base):
    for jour in lundis(2):
        for decalage in range(3):
            seance(base, jour + timedelta(days=decalage), 18, m.StatutSeance.PREVUE)
    assert cles(c.conseils(base, MAINTENANT))[0] == "pointer"


def test_matiere_laissee_de_cote(base):
    physique = base.matieres.ajouter(m.Matiere("Physique"))
    maths = base.matieres.ajouter(m.Matiere("Maths"))
    for n, jour in enumerate(lundis(4)):
        seance(base, jour + timedelta(days=n), 9 + 4 * n % 12, m.StatutSeance.MANQUEE, physique.id)
        seance(base, jour + timedelta(days=4), 17, m.StatutSeance.TERMINEE, maths.id)
    conseil = next(x for x in c.conseils(base, MAINTENANT) if x.cle.startswith("matiere"))
    assert "Physique" in conseil.titre and conseil.ecran == "Matières"


def test_ne_plus_proposer(base):
    for jour in lundis(3):
        seance(base, jour, 20, m.StatutSeance.MANQUEE)
        seance(base, jour + timedelta(days=1), 14, m.StatutSeance.TERMINEE)
    cle = next(x.cle for x in c.conseils(base, MAINTENANT) if x.cle.startswith("creneau"))
    c.ignorer(base, cle)
    assert cle not in [x.cle for x in c.conseils(base, MAINTENANT)]
    assert cle in [x.cle for x in c.conseils(base, MAINTENANT, avec_ignores=True)]


def test_carte_du_bilan(application, base):
    from planificateur.ui.bilan import PageBilan

    for jour in lundis(3):
        seance(base, jour, 20, m.StatutSeance.MANQUEE)
        seance(base, jour + timedelta(days=1), 14, m.StatutSeance.TERMINEE)
    page = PageBilan(base)
    page.maintenant = MAINTENANT
    signaux = []
    page.reglages_modifies.connect(lambda: signaux.append(True))
    page.rafraichir()
    carte = page.carte_conseils
    ligne = next(l for l in carte.lignes if l.conseil.cle.startswith("creneau"))
    carte.appliquer(ligne.conseil, ligne)
    assert signaux and "à éviter" in ligne.confirmation.text() and all(b.isHidden() for b in ligne.boutons)
    page.rafraichir()  # appliqué : n'est plus proposé
    assert not any(l.conseil.cle.startswith("creneau") for l in page.carte_conseils.lignes)
