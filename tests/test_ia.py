"""Assistant IA (Gemini) : clé chiffrée, client, import d'emploi du temps, assistant, écrans.

Aucune requête réelle : un faux transport joue le rôle de Gemini.
"""

import json
import sys
from datetime import date, datetime, time, timedelta

import pytest

from planificateur import modeles as m
from planificateur.base import Base
from planificateur.ia import cle as cle_ia
from planificateur.ia.assistant import OUTILS, appliquer, contexte, preparer, repondre
from planificateur.ia.gemini import Appel, ClientGemini, ErreurGemini, _message_http, bloc_fichier, json_de, lire_reponse
from planificateur.ia.import_edt import associer_matiere, extraire, interpreter, lire_heure

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

CLE = "AIzaSy-cle-de-test-pas-reelle-0123456789"
windows = pytest.mark.skipif(sys.platform != "win32", reason="chiffrement DPAPI propre à Windows")


class FauxGemini:
    """Transport simulé : enregistre chaque envoi et renvoie la réponse préparée."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.envois = []

    def __call__(self, url, corps, entetes):
        self.envois.append((url, json.loads(corps), entetes))
        reponse = self.reponses.pop(0) if self.reponses else {"steps": []}
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def texte(t):
    return {"id": "v1_x", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": t}]}]}


def appel(nom_fonction, **arguments):
    return {"type": "function_call", "id": "c1", "name": nom_fonction, "arguments": arguments}


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "ia.db")
    yield b
    b.fermer()


@pytest.fixture
def remplie(base):
    base.matieres.ajouter(m.Matiere("Traitement de signal"))
    base.matieres.ajouter(m.Matiere("Réseaux Informatiques"))
    return base


# --- Clé -----------------------------------------------------------------------


@windows
def test_cle_chiffree_jamais_en_clair(base):
    cle_ia.enregistrer_cle(base, CLE)
    assert cle_ia.lire_cle(base) == CLE
    assert CLE not in base.parametre(cle_ia.CLE_PARAMETRE)
    assert cle_ia.est_actif(base)
    cle_ia.definir_actif(base, False)
    assert not cle_ia.est_actif(base)
    cle_ia.effacer_cle(base)
    assert cle_ia.lire_cle(base) is None and not cle_ia.est_actif(base)


def test_cle_invalide_refusee(base):
    with pytest.raises(ValueError):
        cle_ia.enregistrer_cle(base, "trop courte")


@windows
def test_cle_illisible_ailleurs(base):
    base.definir_parametre(cle_ia.CLE_PARAMETRE, "AAAAAAAA")  # chiffrée sur un autre ordinateur
    assert cle_ia.lire_cle(base) is None


def test_modele_par_defaut_et_reglable(base):
    assert cle_ia.modele(base) == cle_ia.MODELE_PAR_DEFAUT
    cle_ia.definir_modele(base, "gemini-3.8-flash")
    assert cle_ia.modele(base) == "gemini-3.8-flash"


# --- Client --------------------------------------------------------------------


def test_requete_envoyee(tmp_path):
    faux = FauxGemini(texte("OK"))
    client = ClientGemini(CLE, "gemini-flash-latest", faux)
    assert client.tester() == "OK"
    url, corps, entetes = faux.envois[0]
    assert url.endswith("/v1beta/interactions")
    assert entetes["x-goog-api-key"] == CLE and entetes["Api-Revision"]
    assert corps["model"] == "gemini-flash-latest" and corps["store"] is False
    assert CLE not in json.dumps(client.dernier_envoi)  # la clé n'apparaît pas dans « ce qui est envoyé »


def test_fichier_joint_et_format_impose(tmp_path):
    image = tmp_path / "edt.png"
    image.write_bytes(b"\x89PNG" + b"0" * 5000)
    faux = FauxGemini(texte('{"cours": []}'))
    client = ClientGemini(CLE, "m", faux)
    client.interagir([bloc_fichier(image)], schema={"type": "object"})
    corps = faux.envois[0][1]
    assert corps["input"][0]["type"] == "image" and corps["input"][0]["mime_type"] == "image/png"
    assert corps["response_format"]["mime_type"] == "application/json"
    assert "Ko" in client.dernier_envoi["input"][0]["data"]  # le contenu du fichier n'est pas recopié


def test_formats_de_fichiers(tmp_path):
    pdf = tmp_path / "edt.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert bloc_fichier(pdf)["type"] == "document"
    texte_brut = tmp_path / "edt.txt"
    texte_brut.write_text("x")
    with pytest.raises(ErreurGemini):
        bloc_fichier(texte_brut)


def test_lecture_des_reponses():
    reponse = lire_reponse({"steps": [
        {"type": "thought", "content": [{"type": "text", "text": "je réfléchis"}]},
        {"type": "model_output", "content": [{"type": "text", "text": "Bonjour"}]},
        {"type": "function_call", "name": "regenerer_planning", "arguments": "{}"},
    ]})
    assert reponse.texte == "Bonjour"
    assert [a.nom for a in reponse.appels] == ["regenerer_planning"]
    with pytest.raises(ErreurGemini):
        lire_reponse({"error": {"message": "clé invalide"}})


def test_messages_d_erreur_en_francais():
    assert "Clé API refusée" in _message_http(403, "")
    assert "Limite" in _message_http(429, "quota")
    assert "Modèle introuvable" in _message_http(404, "")


def test_json_dans_un_bloc_de_code():
    assert json_de('```json\n{"cours": [1]}\n```') == {"cours": [1]}
    with pytest.raises(ErreurGemini):
        json_de("pas du json")


# --- Import d'emploi du temps ---------------------------------------------------


def test_association_des_matieres_abregees():
    matieres = [m.Matiere("Traitement de signal", id=1), m.Matiere("Réseaux Informatiques", id=2),
                m.Matiere("CAN/CNA", id=3), m.Matiere("Filtre N", terminee=True, id=4)]
    assert associer_matiere("Trait. signal", matieres) == 1
    assert associer_matiere("TP de Traitement", matieres) == 1
    assert associer_matiere("Réseaux info", matieres) == 2
    assert associer_matiere("can/cna", matieres) == 3
    assert associer_matiere("Mathématiques", matieres) is None


def test_lecture_des_heures():
    assert lire_heure("8h") == time(8) and lire_heure("08:30") == time(8, 30) and lire_heure("14h15") == time(14, 15)
    assert lire_heure("25:00") is None and lire_heure("") is None


def test_interpretation_des_cours():
    matieres = [m.Matiere("Traitement de signal", id=1), m.Matiere("Anglais", id=2)]
    donnees = {"cours": [
        {"nom": "Trait. signal", "matiere": "Traitement de signal", "type": "tp", "chaque_semaine": True,
         "jour": "mercredi", "debut": "7h", "fin": "12h"},
        {"nom": "Anglais", "matiere": "", "type": "cours", "chaque_semaine": False, "date": "2026-11-19",
         "debut": "14:00", "fin": "18:00"},
        {"nom": "Illisible", "type": "cours", "chaque_semaine": True, "debut": "?", "fin": "12:00"},
        {"nom": "Inversé", "type": "cours", "chaque_semaine": True, "jour": "lundi", "debut": "12:00", "fin": "10:00"},
    ]}
    tp, anglais = interpreter(donnees, matieres)
    assert tp.jour_semaine == 2 and tp.date is None and tp.matiere_id == 1 and tp.type is m.TypeActivite.TP
    assert anglais.date == date(2026, 11, 19) and anglais.jour_semaine == 3 and anglais.matiere_id == 2
    assert anglais.activite().date == date(2026, 11, 19)


def test_extraire_avec_un_faux_gemini(tmp_path):
    pdf = tmp_path / "edt.pdf"
    pdf.write_bytes(b"%PDF-1.4 emploi du temps")
    reponse = json.dumps({"cours": [{"nom": "Anglais", "type": "cours", "chaque_semaine": True, "jour": "lundi",
                                     "debut": "07:00", "fin": "12:00"}]})
    faux = FauxGemini(texte(reponse))
    [proposition] = extraire(ClientGemini(CLE, "m", faux), pdf, [m.Matiere("Anglais", id=5)], date(2026, 11, 15))
    assert proposition.matiere_id == 5
    corps = faux.envois[0][1]
    assert corps["input"][0]["type"] == "document"
    assert "Anglais" in corps["input"][1]["text"]  # la liste des matières aide à les reconnaître
    with pytest.raises(ErreurGemini):
        extraire(ClientGemini(CLE, "m", FauxGemini(texte('{"cours": []}'))), pdf, [], date(2026, 11, 15))


# --- Assistant -----------------------------------------------------------------


def test_contexte_contient_les_donnees_utiles_et_rien_d_autre(remplie):
    reseaux = remplie.matieres.lister(ordre="nom")[0]
    remplie.epreuves.ajouter(m.Epreuve(reseaux.id, datetime(2026, 11, 21, 14), datetime(2026, 11, 21, 17),
                                       type=m.TypeEpreuve.DEVOIR_SURVEILLE))
    seance = remplie.seances.ajouter(m.Seance(m.TypeSeance.REVISION, datetime(2026, 11, 17, 20), datetime(2026, 11, 17, 21),
                                              matiere_id=reseaux.id))
    texte_contexte = contexte(remplie, datetime(2026, 11, 16, 10))
    assert "Réseaux Informatiques" in texte_contexte and "devoir_surveille" in texte_contexte
    assert f"#{seance.id}" in texte_contexte
    assert str(remplie.chemin) not in texte_contexte and "AppData" not in texte_contexte


def test_outils_declares():
    noms = {o["name"] for o in OUTILS}
    assert {"ajouter_epreuve", "ajouter_travail", "ajouter_activite", "pointer_seance",
            "marquer_matiere_terminee", "regenerer_planning"} <= noms
    assert all(o["type"] == "function" and o["parameters"]["type"] == "object" for o in OUTILS)


def test_propositions_verifiees_avant_affichage(remplie):
    actions, erreurs = preparer(remplie, [
        Appel("ajouter_epreuve", {"matiere": "Réseaux info", "type": "devoir_surveille", "date": "2026-11-21",
                                  "debut": "14:00", "fin": "17:00"}),
        Appel("ajouter_epreuve", {"matiere": "Chimie", "type": "examen", "date": "2026-11-21", "debut": "8:00", "fin": "10:00"}),
        Appel("action_inconnue", {}),
    ])
    assert len(actions) == 1 and "Réseaux Informatiques" in actions[0].description
    assert len(erreurs) == 2 and "Chimie" in erreurs[0]
    assert remplie.epreuves.lister() == []  # rien n'est appliqué sans accord


def test_appliquer_chaque_action(remplie):
    def action(nom_action, **arguments):
        [a], _ = preparer(remplie, [Appel(nom_action, arguments)])
        return appliquer(remplie, a, datetime(2026, 11, 16))

    action("ajouter_epreuve", matiere="Réseaux Informatiques", type="devoir_surveille", date="2026-11-21",
           debut="14:00", fin="17:00")
    action("ajouter_travail", intitule="Compte rendu TP", matiere="Traitement de signal",
           echeance_date="2026-11-20", minutes_estimees=120)
    action("ajouter_activite", nom="Sport", type="personnel", date="2026-11-19", debut="18:00", fin="19:00")
    assert len(remplie.epreuves.lister()) == 1 and remplie.travaux.lister()[0].echeance.hour == 18
    assert remplie.activites.lister()[0].date == date(2026, 11, 19)
    with pytest.raises(ValueError, match="chevauche"):
        action("ajouter_activite", nom="Rendez-vous", type="personnel", date="2026-11-19", debut="18:30", fin="19:30")
    message = action("regenerer_planning")
    assert "recalculé" in message and remplie.seances.lister()
    seance = remplie.seances.lister()[0]
    action("pointer_seance", seance_id=seance.id, statut="faite")
    assert remplie.seances.obtenir(seance.id).statut is m.StatutSeance.TERMINEE
    action("marquer_matiere_terminee", matiere="Traitement de signal")
    assert [x.terminee for x in remplie.matieres.lister(ordre="nom")] == [False, True]


def test_conversation_complete(remplie):
    faux = FauxGemini({"steps": [
        {"type": "model_output", "content": [{"type": "text", "text": "Je l'ajoute."}]},
        appel("ajouter_epreuve", matiere="Réseaux Informatiques", type="devoir_surveille", date="2026-11-21",
              debut="14:00", fin="17:00"),
    ]})
    reponse, actions, erreurs = repondre(ClientGemini(CLE, "m", faux), remplie, [("utilisateur", "Bonjour"), ("assistant", "Salut")],
                                         "J'ai un DS de réseaux samedi de 14 h à 17 h", datetime(2026, 11, 16, 10))
    assert reponse == "Je l'ajoute." and len(actions) == 1 and not erreurs
    corps = faux.envois[0][1]
    assert "Nouveau message de l'étudiant : J'ai un DS" in corps["input"]
    assert "Échanges précédents" in corps["input"] and corps["tools"] and corps["system_instruction"]


# --- Écrans ------------------------------------------------------------------------


@pytest.fixture
def synchrone(monkeypatch):
    from planificateur.ui import fond

    monkeypatch.setattr(fond, "SYNCHRONE", True)


@windows
def test_preferences_cle_et_test(application, base, synchrone):
    from planificateur.ui.preferences import SectionAssistant

    section = SectionAssistant(base)
    section.champ_cle.setText(CLE)
    assert section.enregistrer_cle()
    assert section.champ_cle.text() == ""  # la clé ne reste pas affichée
    assert "chiffrée" in section.etat.text() and section.actif.isChecked()
    section.client_test = ClientGemini(CLE, "m", FauxGemini(texte("OK")))
    section.tester()
    assert section.resultat.text().startswith("✓ Connexion réussie")
    section.client_test = ClientGemini(CLE, "m", FauxGemini(ErreurGemini("Clé API refusée")))
    section.tester()
    assert "refusée" in section.resultat.text()
    section.effacer_cle()
    assert not section.actif.isEnabled()


def test_import_depuis_l_ecran_emploi_du_temps(application, remplie, synchrone, tmp_path):
    from planificateur.ui.emploi_grille import PageEmploi

    image = tmp_path / "edt.jpg"
    image.write_bytes(b"\xff\xd8" + b"0" * 2000)
    reponse = json.dumps({"cours": [
        {"nom": "Trait. signal", "matiere": "Traitement de signal", "type": "tp", "chaque_semaine": True,
         "jour": "mercredi", "debut": "07:00", "fin": "12:00"},
        {"nom": "Réseaux", "matiere": "Réseaux Informatiques", "type": "cours", "chaque_semaine": True,
         "jour": "jeudi", "debut": "14:00", "fin": "18:00"},
    ]})
    page = PageEmploi(remplie)
    page.avertir = lambda *args: None
    page.client_ia = ClientGemini(CLE, "m", FauxGemini(texte(reponse)))
    page.choisir_fichier = lambda: str(image)
    vus = []

    def verifier(dialogue):
        vus.append(len(dialogue.lignes))
        dialogue.lignes[1].inclure.setChecked(False)  # l'utilisateur décoche le 2e cours
        dialogue.resultat = dialogue.valeurs()
        return True

    page.ouvrir_dialogue = verifier
    page.importer()
    assert vus == [2]
    [activite] = remplie.activites.lister()
    assert activite.nom == "Trait. signal" and activite.jour_semaine == 2 and activite.matiere_id is not None


def test_import_sans_cle_explique_quoi_faire(application, base):
    from planificateur.ui.emploi_grille import PageEmploi

    page = PageEmploi(base)
    messages = []
    page.avertir = lambda parent, titre, texte: messages.append(texte)
    page.choisir_fichier = lambda: pytest.fail("ne doit pas demander de fichier sans clé")
    page.importer()
    assert "Préférences" in messages[0]


def test_ecran_assistant(application, remplie, synchrone):
    from planificateur.ui.assistant_page import PageAssistant

    page = PageAssistant(remplie)
    assert page.inactif.isVisibleTo(page)  # sans clé : explication, pas de conversation
    faux = FauxGemini({"steps": [
        {"type": "model_output", "content": [{"type": "text", "text": "D'accord, je propose ceci."}]},
        appel("ajouter_activite", nom="Sport", type="personnel", date="2026-11-19", debut="18:00", fin="19:00"),
    ]})
    page.client = ClientGemini(CLE, "m", faux)
    page.maintenant = datetime(2026, 11, 16, 10)
    page.rafraichir()
    assert page.zone_active.isVisibleTo(page)
    modifie = []
    page.donnees_modifiees.connect(lambda: modifie.append(True))
    page.envoyer("Ajoute du sport jeudi de 18 h à 19 h")
    assert len(page.cartes) == 1 and remplie.activites.lister() == []  # proposé, pas appliqué
    assert page.cartes[0].appliquer()
    assert remplie.activites.lister()[0].nom == "Sport" and modifie
    assert page.voir_envoi.isEnabled() and "Ajoute du sport" in json.dumps(page.dernier_envoi, ensure_ascii=False)
    page.montrer_envoi()
    page.dialogue_envoi.close()


def test_ecran_assistant_erreur_affichee(application, remplie, synchrone):
    from planificateur.ui.assistant_page import PageAssistant

    page = PageAssistant(remplie)
    page.client = ClientGemini(CLE, "m", FauxGemini(ErreurGemini("Limite de la formule gratuite atteinte.")))
    page.rafraichir()
    page.envoyer("Bonjour")
    textes = [w.text() for w in page.fil.findChildren(type(page.attente))]
    assert any("Limite" in t for t in textes)
    assert page.bouton_envoyer.isEnabled()


def test_erreur_de_cle_renvoyee_par_google(monkeypatch):
    """Google enveloppe l'erreur dans une liste : on l'explique quand même clairement."""
    import io
    import urllib.error
    import urllib.request

    from planificateur.ia import gemini

    corps = json.dumps([{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                   "details": [{"reason": "API_KEY_INVALID"}]}}]).encode()

    def refuser(requete, timeout):
        raise urllib.error.HTTPError(requete.full_url, 400, "Bad Request", {}, io.BytesIO(corps))

    monkeypatch.setattr(urllib.request, "urlopen", refuser)
    with pytest.raises(ErreurGemini, match="Clé API invalide"):
        gemini.ClientGemini(CLE, "m").tester()


# --- Surcharge passagère (503) ------------------------------------------------------


def surcharge():
    return ErreurGemini("Gemini est très sollicité en ce moment.", 503)


def test_nouvel_essai_apres_une_surcharge():
    attentes = []
    faux = FauxGemini(surcharge(), texte("OK"))
    client = ClientGemini(CLE, "gemini-flash-latest", faux, attendre=attentes.append)
    assert client.tester() == "OK"
    assert attentes == [2] and client.modele_utilise == "gemini-flash-latest"


def test_bascule_vers_un_modele_de_secours():
    faux = FauxGemini(surcharge(), surcharge(), surcharge(), texte("OK"))
    client = ClientGemini(CLE, "gemini-flash-latest", faux, secours=["gemini-3.6-flash"], attendre=lambda s: None)
    assert client.tester() == "OK"
    modeles = [corps["model"] for _, corps, _ in faux.envois]
    assert modeles == ["gemini-flash-latest"] * 3 + ["gemini-3.6-flash"]
    assert client.modele_utilise == "gemini-3.6-flash"


def test_modele_de_secours_inexistant_saute():
    faux = FauxGemini(surcharge(), surcharge(), surcharge(), ErreurGemini("Modèle introuvable", 404), texte("OK"))
    client = ClientGemini(CLE, "gemini-flash-latest", faux, secours=["modele-disparu", "gemini-3.5-flash-lite"],
                          attendre=lambda s: None)
    assert client.tester() == "OK" and client.modele_utilise == "gemini-3.5-flash-lite"


def test_surcharge_persistante_expliquee():
    faux = FauxGemini(*[surcharge() for _ in range(10)])
    client = ClientGemini(CLE, "gemini-flash-latest", faux, secours=["gemini-3.6-flash"], attendre=lambda s: None)
    with pytest.raises(ErreurGemini, match="sollicité"):
        client.tester()
    assert len(faux.envois) == 4  # 3 essais sur le modèle choisi + 1 sur le secours, pas plus


def test_cle_refusee_jamais_reessayee():
    faux = FauxGemini(ErreurGemini("Clé API invalide", 400), texte("OK"))
    client = ClientGemini(CLE, "gemini-flash-latest", faux, attendre=lambda s: pytest.fail("pas d'attente"))
    with pytest.raises(ErreurGemini, match="invalide"):
        client.tester()
    assert len(faux.envois) == 1


def test_message_de_surcharge_en_francais():
    assert "très sollicité" in _message_http(503, "high demand")


@windows
def test_preferences_indiquent_le_modele_de_secours(application, base, synchrone):
    from planificateur.ui.preferences import SectionAssistant

    section = SectionAssistant(base)
    section.champ_cle.setText(CLE)
    section.enregistrer_cle()
    faux = FauxGemini(surcharge(), surcharge(), surcharge(), texte("OK"))
    section.client_test = ClientGemini(CLE, "gemini-flash-latest", faux, secours=["gemini-3.6-flash"],
                                       attendre=lambda s: None)
    section.tester()
    assert "gemini-3.6-flash" in section.resultat.text() and "surchargé" in section.resultat.text()
    section.choix_modele.setCurrentText("gemini-3.8-flash")
    assert cle_ia.modele(base) == "gemini-3.8-flash"  # le choix est enregistré aussitôt


# --- Propositions sur plusieurs jours (cas réel : cours Coursera lundi et mardi matin) ---------


@pytest.mark.parametrize("forme_du_jour", [
    {"jours": ["lundi", "mardi"]},
    {"jour": "Lundi et Mardi"},
    {"jour": ["Lundi", "Mardi"]},
    {"jour_semaine": "lun, mar"},
    {"days": ["Monday", "Tuesday"]},
    {"jours": [0, 1]},
])
def test_activite_sur_plusieurs_jours_quelle_que_soit_la_forme(remplie, forme_du_jour):
    arguments = {"nom": "Cours en ligne Coursera", "type": "cours", "debut": "08:00", "fin": "12:00",
                 "matiere": "Coursera", **forme_du_jour}
    actions, erreurs = preparer(remplie, [Appel("ajouter_activite", arguments)])
    assert not erreurs
    assert [a.description.split(",")[1].split()[1] for a in actions] == ["lundi", "mardi"]
    for action in actions:
        appliquer(remplie, action)
    activites = remplie.activites.lister()
    assert sorted(a.jour_semaine for a in activites) == [0, 1]
    assert all(a.matiere_id is None and a.heure_debut == time(8) for a in activites)  # « Coursera » n'est pas une matière


def test_proposition_invalide_expliquee_au_lieu_de_rien_repondu(remplie):
    faux = FauxGemini({"steps": [appel("ajouter_activite", nom="Coursera", type="cours", debut="08:00", fin="12:00")]})
    texte_reponse, actions, erreurs = repondre(ClientGemini(CLE, "m", faux), remplie, [], "Ajoute Coursera")
    assert not actions and texte_reponse.startswith("Je n'ai pas pu")
    assert "jour" in erreurs[0] and "reçu" in erreurs[0]  # on voit ce que Gemini a envoyé


def test_gemini_est_informe_des_propositions_et_resultats(application, remplie, synchrone):
    from planificateur.ui.assistant_page import PageAssistant

    faux = FauxGemini(
        {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Je propose ceci."}]},
                   appel("ajouter_activite", nom="Coursera", type="cours", jours=["lundi"], debut="08:00", fin="12:00")]},
        texte("C'est fait."),
    )
    page = PageAssistant(remplie)
    page.client = ClientGemini(CLE, "m", faux)
    page.rafraichir()
    page.envoyer("Mets mon cours Coursera du lundi matin")
    page.cartes[0].appliquer()
    page.envoyer("Merci")
    second_envoi = faux.envois[1][1]["input"]
    assert "Propositions faites" in second_envoi and "Résultat pour" in second_envoi
    assert "Réponse reçue" not in json.dumps(page.dernier_envoi)  # l'envoi reste l'envoi
    page.montrer_envoi()
    assert "Réponse reçue de Gemini" in page.dialogue_envoi.findChild(type(page.saisie)).toPlainText()
    page.dialogue_envoi.close()


# --- Emploi du temps joint dans l'Assistant ---------------------------------------------


def _reponse_emploi():
    return texte(json.dumps({"cours": [
        {"nom": "Trait. signal", "matiere": "Traitement de signal", "type": "tp", "chaque_semaine": True,
         "jour": "mercredi", "debut": "07:00", "fin": "12:00"},
        {"nom": "Réseaux", "matiere": "Réseaux Informatiques", "type": "cours", "chaque_semaine": True,
         "jour": "jeudi", "debut": "14:00", "fin": "18:00"},
    ]}))


def _page_assistant(base, faux):
    from planificateur.ui.assistant_page import PageAssistant

    page = PageAssistant(base)
    page.client = ClientGemini(CLE, "m", faux)
    page.avertir = lambda *args: None
    page.rafraichir()
    return page


def test_emploi_du_temps_joint_lu_verifie_et_ajoute(application, remplie, synchrone, tmp_path):
    pdf = tmp_path / "emploi.pdf"
    pdf.write_bytes(b"%PDF-1.4 emploi du temps")
    faux = FauxGemini(_reponse_emploi())
    page = _page_assistant(remplie, faux)
    vus = []

    def verifier(dialogue):
        vus.append(len(dialogue.lignes))
        dialogue.resultat = dialogue.valeurs()
        return True

    page.ouvrir_dialogue = verifier
    modifie = []
    page.donnees_modifiees.connect(lambda: modifie.append(True))
    assert page.joindre(pdf) and page.piece_jointe.isVisibleTo(page)
    page.envoyer("seulement le semestre 2")
    assert vus == [2]
    assert sorted(a.jour_semaine for a in remplie.activites.lister()) == [2, 3]
    assert modifie and page.document is None and not page.piece_jointe.isVisibleTo(page)
    corps = faux.envois[0][1]
    assert corps["input"][0]["type"] == "document"
    assert "semestre 2" in corps["input"][1]["text"]  # la remarque accompagne la lecture
    assert page.cartes[-1].action.nom == "regenerer_planning"  # propose de recalculer
    assert page.cartes[-1].appliquer() and remplie.seances.lister()


def test_emploi_du_temps_joint_annule(application, remplie, synchrone, tmp_path):
    image = tmp_path / "emploi.png"
    image.write_bytes(b"\x89PNG" + b"0" * 500)
    page = _page_assistant(remplie, FauxGemini(_reponse_emploi()))
    page.ouvrir_dialogue = lambda dialogue: False
    page.joindre(image)
    page.envoyer("")  # un document seul suffit, sans texte
    assert remplie.activites.lister() == [] and not page.cartes


def test_emploi_du_temps_joint_chevauchement_signale(application, remplie, synchrone, tmp_path):
    remplie.activites.ajouter(m.ActiviteFixe("Sport", time(8), time(9), jour_semaine=2))
    image = tmp_path / "emploi.jpg"
    image.write_bytes(b"\xff\xd8" + b"0" * 500)
    page = _page_assistant(remplie, FauxGemini(_reponse_emploi()))
    page.ouvrir_dialogue = lambda dialogue: setattr(dialogue, "resultat", dialogue.valeurs()) or True
    page.joindre(image)
    page.envoyer("")
    noms = sorted(a.nom for a in remplie.activites.lister())
    assert noms == ["Réseaux", "Sport"]  # le TP du mercredi chevauchait le sport
    textes = [w.text() for w in page.fil.findChildren(QtWidgets.QLabel)]
    assert any("déjà occupé" in t and "Sport" in t for t in textes)


def test_format_joint_refuse(application, remplie, tmp_path):
    fichier = tmp_path / "emploi.docx"
    fichier.write_bytes(b"x")
    page = _page_assistant(remplie, FauxGemini())
    messages = []
    page.avertir = lambda parent, titre, texte_message: messages.append(texte_message)
    assert not page.joindre(fichier) and page.document is None and "PDF" in messages[0]


def test_lecture_impossible_expliquee(application, remplie, synchrone, tmp_path):
    pdf = tmp_path / "flou.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    page = _page_assistant(remplie, FauxGemini(texte('{"cours": []}')))
    page.joindre(pdf)
    page.envoyer("")
    textes = [w.text() for w in page.fil.findChildren(QtWidgets.QLabel)]
    assert any("Aucun cours n'a été reconnu" in t for t in textes)
    assert page.bouton_envoyer.isEnabled()


# --- Design de l'écran Assistant ------------------------------------------------------


def test_accueil_puis_conversation(application, remplie, synchrone):
    from planificateur.ui.assistant_page import _Tuile

    faux = FauxGemini({"steps": [
        {"type": "model_output", "content": [{"type": "text", "text": "Voici votre semaine."}]},
        appel("ajouter_activite", nom="Sport", type="personnel", date="2026-11-19", debut="18:00", fin="19:00"),
        appel("regenerer_planning"),
    ]})
    page = _page_assistant(remplie, faux)
    assert page.accueil.isVisibleTo(page) and not page.defilement.isVisibleTo(page)
    assert "connecté" in page.etat_connexion.text()
    page.findChildren(_Tuile)[1].clique.emit()  # tuile « Résume ma semaine »
    assert faux.envois and "Résume ma semaine" in faux.envois[0][1]["input"]
    assert page.defilement.isVisibleTo(page) and not page.accueil.isVisibleTo(page)
    assert page._ligne_attente is None  # l'indicateur « Gemini réfléchit » a disparu
    sport, recalcul = page.cartes
    sport.appliquer()
    recalcul.ignorer()
    assert sport.objectName() == "carteActionOk" and sport.etiquette.text() == "APPLIQUÉ"
    assert recalcul.objectName() == "carteActionIgnoree" and not recalcul.appliquer_bouton.isVisibleTo(page)
    page.recommencer()
    assert page.accueil.isVisibleTo(page) and page.cartes == [] and page.historique == []


def test_carte_en_echec(application, remplie, synchrone):
    remplie.activites.ajouter(m.ActiviteFixe("Cours", time(18), time(20), date=date(2026, 11, 19)))
    faux = FauxGemini({"steps": [appel("ajouter_activite", nom="Sport", type="personnel", date="2026-11-19",
                                       debut="18:00", fin="19:00")]})
    page = _page_assistant(remplie, faux)
    page.envoyer("Ajoute du sport jeudi à 18 h")
    assert not page.cartes[0].appliquer()
    assert page.cartes[0].objectName() == "carteActionEchec" and "chevauche" in page.cartes[0].texte.text()


def test_tuile_ajouter_une_epreuve_prepare_la_saisie(application, remplie):
    from planificateur.ui.assistant_page import _Tuile

    faux = FauxGemini()
    page = _page_assistant(remplie, faux)
    page.findChildren(_Tuile)[-1].clique.emit()
    assert page.saisie.toPlainText().startswith("J'ai une épreuve") and not faux.envois
