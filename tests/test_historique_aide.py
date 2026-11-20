"""Historique des conversations de l'assistant, contexte élargi envoyé à Gemini, guide intégré."""

from datetime import date, datetime, time, timedelta

import pytest

from planificateur import conversations as cv
from planificateur import modeles as m
from planificateur.base import Base

MAINTENANT = datetime(2026, 11, 20, 18, 0)


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "h.db")
    yield b
    b.fermer()


# --- Enregistrement ---------------------------------------------------------------------------


def test_conversation_enregistree_relue_renommee_supprimee(base):
    vide = cv.enregistrer(base, cv.Conversation())
    assert vide.id is None and cv.lister(base) == []  # une conversation vide n'est pas gardée
    c = cv.Conversation("Réviser la physique", [cv.Message("utilisateur", "Bonjour", "18:00"),
                                                cv.Message("assistant", "**Salut**", "18:00"),
                                                cv.Message("proposition", "Ajouter un DS", "18:01", "appliquee")],
                        [("utilisateur", "Bonjour"), ("assistant", "Salut")])
    cv.enregistrer(base, c, MAINTENANT)
    relue = cv.charger(base, c.id)
    assert relue.messages == c.messages and relue.memoire == c.memoire and relue.titre == "Réviser la physique"
    cv.enregistrer(base, cv.Conversation("Plus récente", [cv.Message("utilisateur", "x")]), MAINTENANT + timedelta(hours=1))
    assert [r.titre for r in cv.lister(base)] == ["Plus récente", "Réviser la physique"]
    cv.renommer(base, c.id, "  DS   de physique ")
    assert cv.charger(base, c.id).titre == "DS de physique"
    cv.supprimer(base, c.id)
    assert cv.charger(base, c.id) is None and len(cv.lister(base)) == 1
    assert cv.tout_supprimer(base) == 1 and cv.lister(base) == []


def test_titre_automatique():
    assert cv.titre_automatique("  Bonjour  ") == "Bonjour"
    long = cv.titre_automatique("Peux-tu m'expliquer comment réviser efficacement la thermodynamique avant samedi ?")
    assert len(long) <= cv.LONGUEUR_TITRE + 1 and long.endswith("…") and not long.endswith(" …")


def test_dates_de_la_liste():
    assert cv.texte_quand(MAINTENANT.replace(hour=9), MAINTENANT) == "aujourd'hui 09:00"
    assert cv.texte_quand(MAINTENANT - timedelta(days=1), MAINTENANT) == "hier"
    assert cv.texte_quand(MAINTENANT - timedelta(days=3), MAINTENANT) == "mardi"
    assert cv.texte_quand(MAINTENANT - timedelta(days=30), MAINTENANT) == "21/10/2026"


# --- Écran de l'assistant -----------------------------------------------------------------------


def _page(base, faux):
    from planificateur.ia.gemini import ClientGemini
    from planificateur.ui.assistant_page import PageAssistant

    page = PageAssistant(base)
    page.client = ClientGemini("cle-de-test", "m", faux)
    page.avertir = lambda *a: None
    page.rafraichir()
    return page


def _reponse(texte):
    return {"id": "x", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": texte}]}]}


class Faux:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.envois = []

    def __call__(self, url, corps, entetes):
        import json

        self.envois.append(json.loads(corps))
        return self.reponses.pop(0)


def test_echanges_enregistres_puis_rouverts(application, base, monkeypatch):
    from planificateur.ui import fond

    monkeypatch.setattr(fond, "SYNCHRONE", True)
    faux = Faux(_reponse("Votre DS est **samedi**."), _reponse("Oui, 3 séances."), _reponse("Bonne question !"))
    page = _page(base, faux)
    page.envoyer("Quand est mon DS de maths ?")
    page.envoyer("Et combien de séances avant ?")
    [resume] = cv.lister(base)
    assert resume.titre == "Quand est mon DS de maths ?" and resume.nombre == 4
    assert page.panneau.liste.count() == 1
    premiere = page.discussion.id

    page.recommencer()  # nouvelle conversation : la précédente reste dans l'historique
    assert page.discussion.id is None and page.historique == []
    page.envoyer("Autre sujet")
    assert len(cv.lister(base)) == 2

    assert page.ouvrir_conversation(premiere)
    from planificateur.ui.assistant_page import _Bulle

    textes = [b.texte_brut for b in page.fil.findChildren(_Bulle)]
    assert "Votre DS est **samedi**." in textes and "Autre sujet" not in textes
    assert [qui for qui, _ in page.historique] == ["utilisateur", "assistant", "utilisateur", "assistant"]
    # La suite de la conversation rouverte part à Gemini avec ses échanges précédents
    faux.reponses.append(_reponse("Je m'en souviens."))
    page.envoyer("Rappelle-moi la date ?")
    assert "Quand est mon DS de maths ?" in faux.envois[-1]["input"]
    assert cv.charger(base, premiere).messages[-1].texte == "Je m'en souviens."


def test_renommer_supprimer_effacer_depuis_l_ecran(application, base):
    page = _page(base, Faux())
    c = cv.enregistrer(base, cv.Conversation("Ancienne", [cv.Message("utilisateur", "x", "10:00")]), MAINTENANT)
    page.panneau.rafraichir(None)
    page.demander_texte = lambda titre, question, valeur: "Nouveau titre"
    page.renommer_conversation(c.id)
    assert cv.charger(base, c.id).titre == "Nouveau titre"
    page.confirmer = lambda titre, texte: False
    page.supprimer_conversation(c.id)
    assert cv.charger(base, c.id) is not None  # refusé : rien n'est supprimé
    page.confirmer = lambda titre, texte: True
    page.effacer_historique()
    assert cv.lister(base) == [] and page.panneau.liste.count() == 0


def test_proposition_et_son_resultat_dans_l_historique(application, base, monkeypatch):
    from planificateur.ui import fond

    monkeypatch.setattr(fond, "SYNCHRONE", True)
    base.matieres.ajouter(m.Matiere("Maths"))
    appel = {"type": "function_call", "id": "c1", "name": "ajouter_activite",
             "arguments": {"nom": "Sport", "type": "personnel", "date": "2026-11-26", "debut": "18:00", "fin": "19:00"}}
    page = _page(base, Faux({"id": "x", "status": "completed", "steps": [appel]}))
    page.envoyer("Ajoute du sport jeudi 18 h")
    page.cartes[0].appliquer()
    proposition = cv.charger(base, page.discussion.id).messages[-1]
    assert proposition.qui == "proposition" and proposition.etat == "appliquee"
    page.ouvrir_conversation(page.discussion.id)  # rouverte : carte figée, sans bouton
    from planificateur.ui.assistant_page import _CarteHistorique

    assert len(page.fil.findChildren(_CarteHistorique)) == 1


# --- Contexte élargi -------------------------------------------------------------------------------


def test_contexte_plus_large(base):
    from planificateur.ia.assistant import INSTRUCTION, contexte, preparer_envoi

    maths = base.matieres.ajouter(m.Matiere("Maths", coefficient=4, difficulte=5, maitrise=2, notes="chapitre 3 dur"))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, MAINTENANT - timedelta(days=6), MAINTENANT - timedelta(days=6, hours=-1),
                                  matiere_id=maths.id, statut=m.StatutSeance.TERMINEE))
    base.seances.ajouter(m.Seance(m.TypeSeance.REVISION, MAINTENANT + timedelta(days=12),
                                  MAINTENANT + timedelta(days=12, hours=1), matiere_id=maths.id))
    base.epreuves.ajouter(m.Epreuve(maths.id, MAINTENANT - timedelta(days=10), MAINTENANT - timedelta(days=10, hours=-2)))
    texte = contexte(base, MAINTENANT)
    assert "coef 4, difficulté 5/5, maîtrise 2/5" in texte and "chapitre 3 dur" in texte
    assert "Plages garanties : lun/mar/mer/jeu/ven 20:00–23:00" in texte
    assert "Épreuves passées" in texte and "Bilan des 4 dernières semaines : 60 min faites" in texte
    assert texte.count("révision Maths") == 2  # 7 jours en arrière et 14 en avant
    assert "coach d'études" in INSTRUCTION and "quiz" in INSTRUCTION
    longue = [("utilisateur" if n % 2 == 0 else "assistant", f"message {n}") for n in range(30)]
    envoi = preparer_envoi(base, longue, "Et maintenant ?", MAINTENANT)
    assert "message 0" in envoi and "message 29" in envoi  # bien plus que les 8 derniers d'avant
    tres_longue = [("utilisateur", "x" * 3900)] * 20
    envoi = preparer_envoi(base, tres_longue, "?", MAINTENANT)
    assert "début omis" in envoi and envoi.count("x" * 3900) <= 6  # dans la limite de taille


# --- Guide intégré ---------------------------------------------------------------------------------


def test_guide_integre(application, base):
    from planificateur.ui.aide import SECTIONS, html_du_guide
    from planificateur.ui.fenetre import FenetrePrincipale

    html = html_du_guide()
    assert all(f"name='{ancre}'" in html for ancre, _, _ in SECTIONS) and "Ctrl+M" in html
    fenetre = FenetrePrincipale(base)
    fenetre.montrer_aide("raccourcis")
    assert fenetre.pile.currentWidget() is fenetre.page_aide
    assert not any(b.isChecked() for b in fenetre.boutons.values())
    fenetre.page_aide.aller_a.emit("Accueil")
    assert fenetre.ecran_courant() == "Accueil"
    fenetre._quitter_vraiment = True
    fenetre.close()
