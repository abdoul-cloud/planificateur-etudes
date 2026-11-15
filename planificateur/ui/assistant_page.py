"""Écran Assistant : conversation avec Gemini, actions appliquées seulement sur accord."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..base import Base
from ..ia import cle as cle_ia
from ..ia.assistant import Action, _chevauche, appliquer, demander, interpreter_reponse, preparer_envoi
from ..ia.gemini import TYPES_FICHIERS
from ..ia.gemini import ClientGemini, ErreurGemini
from . import theme
from .fond import en_fond
from .theme import bouton_role, carte, en_tete, icone, vider

SUGGESTIONS = [  # (libellé du bouton, message envoyé)
    ("Résume ma semaine", "Résume ma semaine"),
    ("Qu'est-ce qui est urgent ?", "Qu'est-ce qui est urgent ?"),
    ("Pas de travail ce soir", "Je ne peux pas travailler ce soir"),
    ("Prêt pour ma prochaine épreuve ?", "Suis-je prêt pour ma prochaine épreuve ?"),
]


class _Bulle(QFrame):
    def __init__(self, texte: str, de_moi: bool, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("bulleMoi" if de_moi else "bulleIA")
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(14, 10, 14, 10)
        libelle = QLabel(texte)
        libelle.setWordWrap(True)
        libelle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        libelle.setTextFormat(Qt.TextFormat.PlainText)
        disposition.addWidget(libelle)
        self.setMaximumWidth(720)


class _CarteAction(QFrame):
    def __init__(self, page: "PageAssistant", action: Action, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("carteAction")
        self.page = page
        self.action = action
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(14, 10, 10, 10)
        self.texte = QLabel(f"Proposition : {action.description}")
        self.texte.setWordWrap(True)
        self.appliquer_bouton = bouton_role(QPushButton(icone("coche", "#FFFFFF"), " Appliquer"), "primaire")
        self.ignorer_bouton = QPushButton("Ignorer")
        self.appliquer_bouton.clicked.connect(self.appliquer)
        self.ignorer_bouton.clicked.connect(self.ignorer)
        disposition.addWidget(self.texte, 1)
        disposition.addWidget(self.appliquer_bouton)
        disposition.addWidget(self.ignorer_bouton)
        self.setMaximumWidth(760)

    def _terminer(self, texte: str) -> None:
        self.appliquer_bouton.hide()
        self.ignorer_bouton.hide()
        self.texte.setText(texte)
        self.page.historique.append(("assistant", f"[Résultat pour « {self.action.description} » : {texte}]"))

    def appliquer(self) -> bool:
        try:
            message = appliquer(self.page.base, self.action, self.page.maintenant)
        except (ValueError, ErreurGemini) as erreur:
            self._terminer(f"⚠ Non appliqué : {erreur}")
            return False
        self._terminer(f"✓ {message}")
        self.page.donnees_modifiees.emit()
        return True

    def ignorer(self) -> None:
        self._terminer(f"Ignoré : {self.action.description}")


class PageAssistant(QWidget):
    donnees_modifiees = Signal()
    aller_a = Signal(str)

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.client: ClientGemini | None = None  # injectable dans les tests
        self.maintenant: datetime | None = None
        self.historique: list[tuple[str, str]] = []
        self.dernier_envoi: dict | None = None
        self.derniere_reponse: dict | None = None
        self.cartes: list[_CarteAction] = []
        self.document: Path | None = None
        # Remplaçables dans les tests (aucune fenêtre bloquante)
        self.ouvrir_dialogue = lambda dialogue: dialogue.exec()
        self.avertir = QMessageBox.warning
        self.setAcceptDrops(True)

        entete, actions = en_tete(
            "Assistant",
            "Posez une question ou demandez un changement en langage naturel. "
            "Rien n'est modifié sans votre accord : chaque proposition s'applique d'un clic.",
        )
        self.voir_envoi = QPushButton("Voir ce qui est envoyé")
        self.voir_envoi.clicked.connect(self.montrer_envoi)
        nouvelle = bouton_role(QPushButton("Nouvelle conversation"), "discret")
        nouvelle.clicked.connect(self.recommencer)
        actions.addWidget(nouvelle)
        actions.addWidget(self.voir_envoi)

        # Carte affichée quand l'assistant n'est pas activé
        self.inactif = carte()
        colonne = QVBoxLayout(self.inactif)
        colonne.setContentsMargins(24, 20, 24, 20)
        titre = QLabel("L'assistant n'est pas encore activé")
        titre.setObjectName("titreCarte")
        explication = QLabel(
            "Ajoutez votre clé Gemini gratuite dans Préférences > Assistant IA. Tant qu'aucune clé n'est "
            "enregistrée, rien n'est envoyé sur Internet."
        )
        explication.setWordWrap(True)
        explication.setObjectName("doux")
        aller = bouton_role(QPushButton("Ouvrir les préférences"), "primaire")
        aller.clicked.connect(lambda: self.aller_a.emit("Préférences"))
        colonne.addWidget(titre)
        colonne.addWidget(explication)
        colonne.addWidget(aller, 0, Qt.AlignmentFlag.AlignLeft)

        # Conversation
        self.fil = QWidget()
        self.fil.setObjectName("defile")
        self.messages = QVBoxLayout(self.fil)
        self.messages.setContentsMargins(4, 4, 12, 4)
        self.messages.setSpacing(10)
        self.messages.addStretch()
        self.defilement = QScrollArea()
        self.defilement.setWidgetResizable(True)
        self.defilement.setWidget(self.fil)
        self.defilement.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.suggestions = QHBoxLayout()
        for libelle, message in SUGGESTIONS:
            bouton = QPushButton(libelle)
            bouton.setObjectName("segment")
            bouton.setToolTip(message)
            bouton.clicked.connect(lambda _=False, t=message: self.envoyer(t))
            self.suggestions.addWidget(bouton)
        self.suggestions.addStretch()

        bouton_charger = QPushButton(icone("importer"), " Charger mon emploi du temps")
        bouton_charger.setObjectName("segment")
        bouton_charger.setToolTip("Joindre une image ou un PDF : Gemini le lit, vous vérifiez avant tout ajout")
        bouton_charger.clicked.connect(self.choisir_document)
        self.suggestions.insertWidget(0, bouton_charger)

        self.saisie = QPlainTextEdit()
        self.saisie.setPlaceholderText("Ex. : « J'ai un DS de réseaux samedi de 14 h à 17 h » — Ctrl+Entrée pour envoyer. "
                                       "Vous pouvez aussi glisser ici une image ou un PDF de votre emploi du temps.")
        self.saisie.setFixedHeight(76)
        self.bouton_envoyer = bouton_role(QPushButton(icone("envoyer", "#FFFFFF"), " Envoyer"), "primaire")
        self.bouton_envoyer.clicked.connect(lambda: self.envoyer(self.saisie.toPlainText()))
        QShortcut(QKeySequence("Ctrl+Return"), self.saisie, activated=lambda: self.envoyer(self.saisie.toPlainText()))
        self.attente = QLabel("⏳  Gemini réfléchit…")
        self.attente.setObjectName("pastille")
        self.attente.hide()
        self.bouton_joindre = QPushButton(icone("importer"), "")
        self.bouton_joindre.setToolTip("Joindre une image ou un PDF de votre emploi du temps")
        self.bouton_joindre.clicked.connect(self.choisir_document)
        self.piece_jointe = QWidget()
        ligne_piece = QHBoxLayout(self.piece_jointe)
        ligne_piece.setContentsMargins(0, 0, 0, 0)
        self.nom_piece = QLabel()
        self.nom_piece.setObjectName("pastille")
        retirer = bouton_role(QPushButton("✕"), "discret")
        retirer.setToolTip("Retirer le document")
        retirer.clicked.connect(self.retirer_document)
        ligne_piece.addWidget(self.nom_piece)
        ligne_piece.addWidget(retirer)
        ligne_piece.addStretch()
        self.piece_jointe.hide()
        boutons_saisie = QVBoxLayout()
        boutons_saisie.addStretch()
        boutons_saisie.addWidget(self.bouton_joindre)
        boutons_saisie.addWidget(self.bouton_envoyer)
        ligne_saisie = QHBoxLayout()
        ligne_saisie.addWidget(self.saisie, 1)
        ligne_saisie.addLayout(boutons_saisie)

        self.zone_active = QWidget()
        zone = QVBoxLayout(self.zone_active)
        zone.setContentsMargins(0, 0, 0, 0)
        zone.setSpacing(10)
        zone.addWidget(self.defilement, 1)
        zone.addWidget(self.attente, 0, Qt.AlignmentFlag.AlignLeft)
        zone.addLayout(self.suggestions)
        zone.addWidget(self.piece_jointe)
        zone.addLayout(ligne_saisie)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(14)
        disposition.addWidget(entete)
        disposition.addWidget(self.inactif)
        disposition.addWidget(self.zone_active, 1)
        self.rafraichir()

    # --- État -------------------------------------------------------------------

    def actif(self) -> bool:
        return self.client is not None or cle_ia.est_actif(self.base)

    def rafraichir(self) -> None:
        actif = self.actif()
        self.inactif.setVisible(not actif)
        self.zone_active.setVisible(actif)
        self.voir_envoi.setEnabled(self.dernier_envoi is not None)
        if actif and self.messages.count() == 1:
            self._ajouter(_Bulle(
                "Bonjour ! Je connais votre emploi du temps, vos épreuves, vos travaux et votre planning. "
                "Demandez-moi un résumé, une explication, ou dites-moi un imprévu : je vous proposerai les "
                "changements, et vous déciderez.", de_moi=False))

    def recommencer(self) -> None:
        self.historique.clear()
        self.cartes.clear()
        vider(self.messages)
        self.messages.addStretch()
        self.rafraichir()

    def _ajouter(self, widget: QWidget) -> None:
        ligne = QHBoxLayout()
        if widget.objectName() == "bulleMoi":
            ligne.addStretch()
            ligne.addWidget(widget)
        else:
            ligne.addWidget(widget)
            ligne.addStretch()
        conteneur = QWidget()
        conteneur.setLayout(ligne)
        ligne.setContentsMargins(0, 0, 0, 0)
        self.messages.insertWidget(self.messages.count() - 1, conteneur)
        QTimer.singleShot(0, self._defiler_en_bas)

    def _defiler_en_bas(self) -> None:
        try:
            barre = self.defilement.verticalScrollBar()
            barre.setValue(barre.maximum())
        except RuntimeError:
            pass  # écran déjà fermé

    # --- Conversation -------------------------------------------------------------

    # --- Document joint (emploi du temps en image ou PDF) ------------------------------

    def choisir_document(self) -> None:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QFileDialog

        dossier = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Joindre votre emploi du temps", dossier, "Emploi du temps (*.pdf *.png *.jpg *.jpeg *.webp)"
        )
        if chemin:
            self.joindre(Path(chemin))

    def joindre(self, chemin: Path) -> bool:
        chemin = Path(chemin)
        if chemin.suffix.lower() not in TYPES_FICHIERS:
            self.avertir(self, "Format non pris en charge", "Joignez un PDF ou une image (PNG, JPG, WEBP).")
            return False
        self.document = chemin
        self.nom_piece.setText(f"📎  {chemin.name} — sera lu comme emploi du temps")
        self.piece_jointe.show()
        self.saisie.setFocus()
        return True

    def retirer_document(self) -> None:
        self.document = None
        self.piece_jointe.hide()

    def dragEnterEvent(self, evenement) -> None:
        urls = evenement.mimeData().urls() if evenement.mimeData().hasUrls() else []
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in TYPES_FICHIERS and self.actif():
            evenement.acceptProposedAction()

    def dropEvent(self, evenement) -> None:
        urls = evenement.mimeData().urls()
        if urls:
            self.joindre(Path(urls[0].toLocalFile()))
            evenement.acceptProposedAction()

    def _lire_document(self, remarque: str) -> None:
        from datetime import date

        from ..ia.import_edt import extraire

        chemin = self.document
        self.retirer_document()
        self._ajouter(_Bulle(f"📎 {chemin.name}" + (f"\n{remarque}" if remarque else ""), de_moi=True))
        self.historique.append(("utilisateur", f"[Document joint : {chemin.name}] {remarque}".strip()))
        client = self.client or ClientGemini(cle_ia.lire_cle(self.base), cle_ia.modele(self.base))
        matieres = self.base.matieres.lister(ordre="nom")
        self.bouton_envoyer.setEnabled(False)
        self.attente.setText("⏳  Gemini lit votre emploi du temps…")
        self.attente.show()

        def lu(propositions):
            self.dernier_envoi = client.dernier_envoi
            self._fin_attente()
            self._verifier_import(propositions)

        def echec(message):
            self.dernier_envoi = client.dernier_envoi
            self._fin_attente()
            self._ajouter(_Bulle(f"⚠ {message}", de_moi=False))

        en_fond(lambda: extraire(client, chemin, matieres, date.today(), remarque), lu, echec)

    def _verifier_import(self, propositions) -> None:
        from .import_dialogue import DialogueImport

        self._ajouter(_Bulle(f"J'ai reconnu {len(propositions)} cours. Vérifiez-les dans la fenêtre qui s'ouvre : "
                             "rien n'est ajouté sans votre accord.", de_moi=False))
        dialogue = DialogueImport(propositions, self.base.matieres.lister(ordre="nom"), self)
        if not self.ouvrir_dialogue(dialogue):
            self._ajouter(_Bulle("Import annulé : rien n'a été ajouté à votre emploi du temps.", de_moi=False))
            self.historique.append(("assistant", "[Import annulé par l'étudiant]"))
            return
        ajoutes, refus = [], []
        for activite in dialogue.resultat or dialogue.valeurs():
            conflit = _chevauche(self.base, activite)
            if conflit:
                refus.append(f"{activite.nom} (chevauche « {conflit} »)")
                continue
            self.base.activites.ajouter(activite)
            ajoutes.append(activite.nom)
        bilan = f"C'est fait : {len(ajoutes)} cours ajouté{'s' if len(ajoutes) > 1 else ''} à votre emploi du temps."
        if refus:
            bilan += "\nNon ajoutés car le moment est déjà occupé : " + ", ".join(refus) + "."
        if not ajoutes:
            bilan = "Aucun cours ajouté." + (("\n" + "Déjà occupés : " + ", ".join(refus) + ".") if refus else "")
        self._ajouter(_Bulle(bilan, de_moi=False))
        self.historique.append(("assistant", f"[Import du document : {bilan}]"))
        if ajoutes:
            self.donnees_modifiees.emit()
            carte_action = _CarteAction(self, Action("regenerer_planning", {}, "Recalculer le planning avec ces cours"))
            self.cartes.append(carte_action)
            self._ajouter(carte_action)

    # --- Conversation -------------------------------------------------------------

    def envoyer(self, texte: str) -> None:
        texte = texte.strip()
        if self.document is not None and self.actif() and self.bouton_envoyer.isEnabled():
            self.saisie.clear()
            self._lire_document(texte)
            return
        if not texte or not self.actif() or not self.bouton_envoyer.isEnabled():
            return
        self.saisie.clear()
        self._ajouter(_Bulle(texte, de_moi=True))
        client = self.client or ClientGemini(cle_ia.lire_cle(self.base), cle_ia.modele(self.base))
        entree = preparer_envoi(self.base, self.historique, texte, self.maintenant)
        self.historique.append(("utilisateur", texte))
        self.bouton_envoyer.setEnabled(False)
        self.attente.show()

        def recu(reponse):
            self.dernier_envoi = client.dernier_envoi
            self.derniere_reponse = getattr(reponse, "brut", None)
            self._fin_attente()
            try:
                reponse_texte, actions, erreurs = interpreter_reponse(self.base, reponse)
            except ErreurGemini as erreur:
                self._ajouter(_Bulle(f"⚠ {erreur}", de_moi=False))
                return
            memo = reponse_texte
            if actions:
                memo += " [Propositions faites : " + " ; ".join(a.description for a in actions) + "]"
            if erreurs:
                memo += " [Propositions refusées par l'application : " + " ; ".join(erreurs) + "]"
            self.historique.append(("assistant", memo))
            self._ajouter(_Bulle(reponse_texte, de_moi=False))
            for action in actions:
                carte_action = _CarteAction(self, action)
                self.cartes.append(carte_action)
                self._ajouter(carte_action)
            for erreur in erreurs:
                self._ajouter(_Bulle(f"⚠ {erreur}", de_moi=False))

        def echec(message):
            self.dernier_envoi = client.dernier_envoi
            self._fin_attente()
            self._ajouter(_Bulle(f"⚠ {message}", de_moi=False))

        en_fond(lambda: demander(client, entree), recu, echec)

    def _fin_attente(self) -> None:
        self.attente.hide()
        self.attente.setText("⏳  Gemini réfléchit…")
        self.bouton_envoyer.setEnabled(True)
        self.voir_envoi.setEnabled(self.dernier_envoi is not None)

    def montrer_envoi(self) -> None:
        if self.dernier_envoi is None:
            return
        dialogue = QDialog(self)
        dialogue.setWindowTitle("Dernier échange avec Gemini")
        dialogue.resize(860, 640)
        explication = QLabel(
            "Voici exactement ce qui a été envoyé à Google lors du dernier message (la clé API n'y figure pas : "
            "elle voyage à part, chiffrée par la connexion HTTPS)."
        )
        explication.setWordWrap(True)
        texte = json.dumps(self.dernier_envoi, ensure_ascii=False, indent=2)
        if self.derniere_reponse is not None:
            texte += "\n\n───── Réponse reçue de Gemini ─────\n" + json.dumps(self.derniere_reponse, ensure_ascii=False, indent=2)
        contenu = QPlainTextEdit(texte)
        contenu.setReadOnly(True)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        boutons.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        boutons.rejected.connect(dialogue.reject)
        disposition = QVBoxLayout(dialogue)
        disposition.addWidget(explication)
        disposition.addWidget(contenu, 1)
        disposition.addWidget(boutons)
        self.dialogue_envoi = dialogue
        dialogue.open()
