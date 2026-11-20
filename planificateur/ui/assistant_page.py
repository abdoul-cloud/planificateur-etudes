"""Écran Assistant : conversation avec Gemini, actions appliquées seulement sur accord."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..base import Base
from ..ia import cle as cle_ia
from ..ia.assistant import Action, _chevauche, appliquer, demander, interpreter_reponse, preparer_envoi
from ..ia.gemini import TYPES_FICHIERS, ClientGemini, ErreurGemini
from . import theme
from .fond import en_fond
from .theme import bouton_role, carte, en_tete, icone, pixmap_icone, vider

LARGEUR_FIL = 860  # largeur maximale de la conversation, centrée

SUGGESTIONS = [  # (libellé du bouton, message envoyé)
    ("Résume ma semaine", "Résume ma semaine"),
    ("Qu'est-ce qui est urgent ?", "Qu'est-ce qui est urgent ?"),
    ("Pas de travail ce soir", "Je ne peux pas travailler ce soir"),
    ("Prêt pour ma prochaine épreuve ?", "Suis-je prêt pour ma prochaine épreuve ?"),
]

# Tuiles de l'accueil : (icône, titre, sous-titre, message ; None = joindre un document)
TUILES = [
    ("importer", "Charger mon emploi du temps", "Image ou PDF : je le lis, vous vérifiez", None),
    ("planning", "Résume ma semaine", "Cours, épreuves et séances prévues", "Résume ma semaine"),
    ("alerte", "Qu'est-ce qui est urgent ?", "Les échéances qui approchent", "Qu'est-ce qui est urgent ?"),
    ("annuler", "Pas de travail ce soir", "Je replanifie la soirée", "Je ne peux pas travailler ce soir"),
    ("epreuves", "Prêt pour ma prochaine épreuve ?", "Où en est la préparation", "Suis-je prêt pour ma prochaine épreuve ?"),
    ("drapeau", "Charger mes épreuves", "Calendrier d'examens en image ou PDF", "@epreuves"),
]

ICONES_ACTIONS = {
    "ajouter_epreuve": "drapeau", "ajouter_travail": "travaux", "ajouter_activite": "emploi",
    "pointer_seance": "coche", "marquer_matiere_terminee": "matieres", "regenerer_planning": "generer",
}


def _avatar() -> QLabel:
    pastille = QLabel()
    pastille.setObjectName("avatarIA")
    pastille.setFixedSize(32, 32)
    pastille.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pastille.setPixmap(pixmap_icone("assistant", "#FFFFFF", 16))
    return pastille


class _Bulle(QFrame):
    def __init__(self, texte: str, de_moi: bool, parent=None, heure_texte: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("bulleMoi" if de_moi else "bulleIA")
        self.texte_brut = texte
        self.de_moi = de_moi
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(16, 11, 16, 8)
        disposition.setSpacing(4)
        if de_moi:  # ce que l'utilisateur a tapé reste tel quel
            libelle = QLabel(texte)
            libelle.setTextFormat(Qt.TextFormat.PlainText)
        else:  # réponse de Gemini : gras, listes… (texte échappé, aucune balise interprétée)
            from ..ia.mise_en_forme import markdown_vers_html

            libelle = QLabel(markdown_vers_html(texte))
            libelle.setTextFormat(Qt.TextFormat.RichText)
        self.libelle = libelle
        libelle.setWordWrap(True)
        libelle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.heure_texte = heure_texte or datetime.now().strftime("%H:%M")
        heure = QLabel(self.heure_texte)
        heure.setObjectName("heureBulle")
        heure.setAlignment(Qt.AlignmentFlag.AlignRight)
        disposition.addWidget(libelle)
        disposition.addWidget(heure)
        self.setMaximumWidth(620)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)


class _CarteAction(QFrame):
    def __init__(self, page: "PageAssistant", action: Action, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("carteAction")
        self.page = page
        self.action = action
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(14, 12, 12, 12)
        disposition.setSpacing(12)
        self.pictogramme = QLabel()
        self.pictogramme.setObjectName("pictoAction")
        self.pictogramme.setFixedSize(36, 36)
        self.pictogramme.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pictogramme.setPixmap(pixmap_icone(ICONES_ACTIONS.get(action.nom, "generer"), theme.ACCENT, 18))
        textes = QVBoxLayout()
        textes.setSpacing(2)
        self.etiquette = QLabel("PROPOSITION")
        self.etiquette.setObjectName("etiquetteAction")
        self.texte = QLabel(action.description)
        self.texte.setObjectName("texteAction")
        self.texte.setWordWrap(True)
        textes.addWidget(self.etiquette)
        textes.addWidget(self.texte)
        self.appliquer_bouton = bouton_role(QPushButton(icone("coche", "#FFFFFF"), " Appliquer"), "primaire")
        self.ignorer_bouton = QPushButton("Ignorer")
        self.appliquer_bouton.clicked.connect(self.appliquer)
        self.ignorer_bouton.clicked.connect(self.ignorer)
        disposition.addWidget(self.pictogramme, 0, Qt.AlignmentFlag.AlignTop)
        disposition.addLayout(textes, 1)
        disposition.addWidget(self.appliquer_bouton)
        disposition.addWidget(self.ignorer_bouton)
        self.setMaximumWidth(680)

    def _terminer(self, texte: str, etat: str, etiquette: str, icone_nom: str, couleur: str) -> None:
        self.appliquer_bouton.hide()
        self.ignorer_bouton.hide()
        self.texte.setText(texte)
        self.etiquette.setText(etiquette)
        self.pictogramme.setPixmap(pixmap_icone(icone_nom, couleur, 18))
        self.setObjectName(etat)
        self.style().unpolish(self)
        self.style().polish(self)
        for enfant in (self.etiquette, self.texte, self.pictogramme):
            enfant.style().unpolish(enfant)
            enfant.style().polish(enfant)
        self.page.historique.append(("assistant", f"[Résultat pour « {self.action.description} » : {texte}]"))
        if getattr(self, "message", None) is not None:
            self.message.texte = texte
            self.message.etat = {"carteActionOk": "appliquee", "carteActionIgnoree": "ignoree"}.get(etat, "echec")
            self.page.sauver_conversation()

    def appliquer(self) -> bool:
        try:
            message = appliquer(self.page.base, self.action, self.page.maintenant)
        except (ValueError, ErreurGemini) as erreur:
            self._terminer(f"⚠ Non appliqué : {erreur}", "carteActionEchec", "NON APPLIQUÉ", "alerte", theme.DANGER)
            return False
        self._terminer(f"✓ {message}", "carteActionOk", "APPLIQUÉ", "coche", theme.SUCCES)
        self.page.donnees_modifiees.emit()
        return True

    def ignorer(self) -> None:
        self._terminer(f"Ignoré : {self.action.description}", "carteActionIgnoree", "IGNORÉ", "annuler", theme.TEXTE_PALE)


class _CarteHistorique(QFrame):
    """Proposition d'une conversation passée : son résultat, sans bouton (l'action n'est plus applicable)."""

    ETATS = {
        "appliquee": ("carteActionOk", "APPLIQUÉ", "coche", theme.SUCCES),
        "ignoree": ("carteActionIgnoree", "IGNORÉ", "annuler", theme.TEXTE_PALE),
        "echec": ("carteActionEchec", "NON APPLIQUÉ", "alerte", theme.DANGER),
        "proposee": ("carteActionIgnoree", "NON TRAITÉE", "annuler", theme.TEXTE_PALE),
    }

    def __init__(self, message, parent=None) -> None:
        super().__init__(parent)
        etat, etiquette, icone_nom, couleur = self.ETATS.get(message.etat, self.ETATS["proposee"])
        self.setObjectName(etat)
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(14, 10, 12, 10)
        disposition.setSpacing(12)
        pictogramme = QLabel()
        pictogramme.setObjectName("pictoAction")
        pictogramme.setFixedSize(36, 36)
        pictogramme.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pictogramme.setPixmap(pixmap_icone(icone_nom, couleur, 18))
        textes = QVBoxLayout()
        textes.setSpacing(2)
        haut = QLabel(etiquette)
        haut.setObjectName("etiquetteAction")
        texte = QLabel(message.texte)
        texte.setObjectName("texteAction")
        texte.setWordWrap(True)
        textes.addWidget(haut)
        textes.addWidget(texte)
        disposition.addWidget(pictogramme, 0, Qt.AlignmentFlag.AlignTop)
        disposition.addLayout(textes, 1)
        self.setMaximumWidth(680)


class _PanneauConversations(QFrame):
    """Liste des conversations passées, la plus récente en haut (comme dans les applis de chat)."""

    ouvrir = Signal(int)
    nouvelle = Signal()

    def __init__(self, page: "PageAssistant") -> None:
        super().__init__()
        self.page = page
        self.setObjectName("panneauConversations")
        self.setFixedWidth(240)
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(10, 12, 10, 10)
        colonne.setSpacing(8)
        bouton = bouton_role(QPushButton(icone("ajouter", "#FFFFFF"), " Nouvelle conversation"), "primaire")
        bouton.clicked.connect(self.nouvelle)
        titre = QLabel("HISTORIQUE")
        titre.setObjectName("sectionHistorique")
        self.liste = QListWidget()
        self.liste.setObjectName("listeConversations")
        self.liste.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu)
        self.liste.itemClicked.connect(lambda item: self.ouvrir.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.vide = QLabel("Vos conversations apparaîtront ici. Elles restent sur cet ordinateur.")
        self.vide.setObjectName("pale")
        self.vide.setWordWrap(True)
        effacer = bouton_role(QPushButton("Tout effacer"), "discret")
        effacer.clicked.connect(self.tout_effacer)
        self.bouton_effacer = effacer
        colonne.addWidget(bouton)
        colonne.addSpacing(4)
        colonne.addWidget(titre)
        colonne.addWidget(self.vide)
        colonne.addWidget(self.liste, 1)
        colonne.addWidget(effacer, 0, Qt.AlignmentFlag.AlignLeft)

    def rafraichir(self, actuelle: int | None) -> None:
        from ..conversations import lister, texte_quand

        resumes = lister(self.page.base)
        maintenant = datetime.now()
        self.liste.blockSignals(True)
        self.liste.clear()
        for r in resumes:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, r.id)
            item.setToolTip(r.titre)
            bloc = QWidget()
            bloc.setObjectName("elementConversation")
            textes = QVBoxLayout(bloc)
            textes.setContentsMargins(10, 7, 8, 7)
            textes.setSpacing(1)
            titre = QLabel(r.titre)
            titre.setObjectName("titreConversation")
            quand = QLabel(texte_quand(r.modifiee, maintenant))
            quand.setObjectName("dateConversation")
            textes.addWidget(titre)
            textes.addWidget(quand)
            item.setSizeHint(bloc.sizeHint())
            self.liste.addItem(item)
            self.liste.setItemWidget(item, bloc)
            if r.id == actuelle:
                item.setSelected(True)
                self.liste.setCurrentItem(item)
        self.liste.blockSignals(False)
        self.vide.setVisible(not resumes)
        self.liste.setVisible(bool(resumes))
        self.bouton_effacer.setVisible(bool(resumes))

    def _menu(self, position) -> None:
        item = self.liste.itemAt(position)
        if item is None:
            return
        identifiant = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        renommer = menu.addAction(icone("modifier"), "Renommer…")
        supprimer = menu.addAction(icone("supprimer", theme.DANGER), "Supprimer")
        choix = menu.exec(self.liste.viewport().mapToGlobal(position))
        if choix is renommer:
            self.page.renommer_conversation(identifiant)
        elif choix is supprimer:
            self.page.supprimer_conversation(identifiant)

    def tout_effacer(self) -> None:
        self.page.effacer_historique()


class _Tuile(QFrame):
    """Suggestion de l'accueil : icône, titre et sous-titre, cliquable."""

    clique = Signal()

    def __init__(self, icone_nom: str, titre: str, sous_titre: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tuile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(14, 12, 14, 12)
        disposition.setSpacing(12)
        pictogramme = QLabel()
        pictogramme.setObjectName("pictoAction")
        pictogramme.setFixedSize(38, 38)
        pictogramme.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pictogramme.setPixmap(pixmap_icone(icone_nom, theme.ACCENT, 18))
        textes = QVBoxLayout()
        textes.setSpacing(1)
        libelle = QLabel(titre)
        libelle.setObjectName("titreTuile")
        detail = QLabel(sous_titre)
        detail.setObjectName("detailTuile")
        textes.addWidget(libelle)
        textes.addWidget(detail)
        disposition.addWidget(pictogramme, 0, Qt.AlignmentFlag.AlignTop)
        disposition.addLayout(textes, 1)

    def mouseReleaseEvent(self, evenement) -> None:
        if evenement.button() == Qt.MouseButton.LeftButton:
            self.clique.emit()


class PageAssistant(QWidget):
    donnees_modifiees = Signal()
    aller_a = Signal(str)

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.client: ClientGemini | None = None  # injectable dans les tests
        self.maintenant: datetime | None = None
        from ..conversations import Conversation

        self.discussion = Conversation()
        self.historique: list[tuple[str, str]] = self.discussion.memoire  # mémoire transmise à Gemini
        self._restauration = False
        self.demander_texte = self._demander_texte  # remplaçables dans les tests
        self.confirmer = lambda titre, texte: QMessageBox.question(self, titre, texte) == QMessageBox.StandardButton.Yes
        self.dernier_envoi: dict | None = None
        self.derniere_reponse: dict | None = None
        self.cartes: list[_CarteAction] = []
        self.document: Path | None = None
        self.genre_document = "emploi"  # « emploi » (emploi du temps) ou « epreuves » (calendrier d'examens)
        self._ligne_attente: QWidget | None = None
        self._texte_attente = ""
        self._points = 0
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(450)
        self._minuteur.timeout.connect(self._animer_attente)
        # Remplaçables dans les tests (aucune fenêtre bloquante)
        self.ouvrir_dialogue = lambda dialogue: dialogue.exec()
        self.avertir = QMessageBox.warning
        self.setAcceptDrops(True)

        # --- En-tête ---
        entete, actions = en_tete(
            "Assistant",
            "Demandez en langage naturel. Rien n'est modifié sans votre accord.",
        )
        self.etat_connexion = QLabel()
        self.etat_connexion.setObjectName("pastille")
        self.voir_envoi = QPushButton("Voir ce qui est envoyé")
        self.voir_envoi.setToolTip("Voir exactement ce qui a été envoyé à Google lors du dernier message")
        self.voir_envoi.clicked.connect(self.montrer_envoi)
        nouvelle = bouton_role(QPushButton(icone("ajouter"), " Nouvelle conversation"), "discret")
        nouvelle.setToolTip("Nouvelle conversation (la précédente reste dans l'historique)")
        self.bouton_nouvelle = nouvelle
        nouvelle.clicked.connect(self.recommencer)
        self.bouton_historique = bouton_role(QPushButton(icone("bilan"), " Historique"), "discret")
        self.bouton_historique.setCheckable(True)
        self.bouton_historique.setToolTip("Afficher ou masquer la liste des conversations")
        self.bouton_historique.toggled.connect(lambda visible: self.panneau.setVisible(visible))
        actions.addWidget(self.etat_connexion, 0, Qt.AlignmentFlag.AlignVCenter)
        actions.addWidget(self.bouton_historique)
        actions.addWidget(nouvelle)
        actions.addWidget(self.voir_envoi)

        # --- Assistant non activé ---
        self.inactif = carte()
        colonne = QVBoxLayout(self.inactif)
        colonne.setContentsMargins(28, 26, 28, 26)
        colonne.setSpacing(10)
        colonne.addWidget(_avatar(), 0, Qt.AlignmentFlag.AlignLeft)
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

        # --- Accueil (avant le premier message) ---
        interieur_accueil = QWidget()
        interieur_accueil.setObjectName("defile")
        self.accueil = QScrollArea()  # défilable : les tuiles ne sont jamais écrasées dans une petite fenêtre
        self.accueil.setObjectName("filAssistant")
        self.accueil.setWidgetResizable(True)
        self.accueil.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.accueil.setWidget(interieur_accueil)
        accueil = QVBoxLayout(interieur_accueil)
        accueil.setContentsMargins(24, 30, 24, 10)
        accueil.setSpacing(6)
        grand_avatar = QLabel()
        grand_avatar.setObjectName("grandAvatar")
        grand_avatar.setFixedSize(64, 64)
        grand_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grand_avatar.setPixmap(pixmap_icone("assistant", "#FFFFFF", 30))
        bonjour = QLabel("Bonjour ! Comment puis-je vous aider ?")
        bonjour.setObjectName("titreAccueil")
        bonjour.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presentation = QLabel(
            "Je connais votre emploi du temps, vos épreuves, vos travaux et votre planning. "
            "Je propose, vous décidez."
        )
        presentation.setObjectName("doux")
        presentation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presentation.setWordWrap(True)
        grille = QGridLayout()
        grille.setSpacing(12)
        for n, (icone_nom, titre_tuile, detail, message) in enumerate(TUILES):
            tuile = _Tuile(icone_nom, titre_tuile, detail)
            if message is None:
                tuile.clique.connect(lambda: self.choisir_document("emploi"))
            elif message == "@epreuves":
                tuile.clique.connect(lambda: self.choisir_document("epreuves"))
            elif message == "":
                tuile.clique.connect(lambda: self._preparer_saisie("J'ai une épreuve de … le … de … h à … h"))
            else:
                tuile.clique.connect(lambda m=message: self.envoyer(m))
            grille.addWidget(tuile, n // 2, n % 2)
        grille.setColumnStretch(0, 1)
        grille.setColumnStretch(1, 1)
        bloc_grille = QWidget()
        bloc_grille.setMaximumWidth(LARGEUR_FIL - 100)
        bloc_grille.setLayout(grille)
        accueil.addStretch(1)
        accueil.addWidget(grand_avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        accueil.addSpacing(8)
        accueil.addWidget(bonjour)
        accueil.addWidget(presentation)
        accueil.addSpacing(18)
        ligne_grille = QHBoxLayout()
        ligne_grille.addStretch(1)
        ligne_grille.addWidget(bloc_grille, 100)
        ligne_grille.addStretch(1)
        accueil.addLayout(ligne_grille)
        accueil.addStretch(2)

        # --- Fil de la conversation, centré ---
        self.fil = QWidget()
        self.fil.setObjectName("defile")
        self.fil.setMaximumWidth(LARGEUR_FIL)
        self.messages = QVBoxLayout(self.fil)
        self.messages.setContentsMargins(8, 18, 8, 18)
        self.messages.setSpacing(14)
        self.messages.addStretch()
        centrage = QWidget()
        centrage.setObjectName("defile")
        ligne_centrage = QHBoxLayout(centrage)
        ligne_centrage.setContentsMargins(0, 0, 0, 0)
        ligne_centrage.addStretch()
        ligne_centrage.addWidget(self.fil, 100)
        ligne_centrage.addStretch()
        self.defilement = QScrollArea()
        self.defilement.setObjectName("filAssistant")
        self.defilement.setWidgetResizable(True)
        self.defilement.setWidget(centrage)
        self.defilement.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.conversation = QFrame()
        self.conversation.setObjectName("conversation")
        disposition_conversation = QVBoxLayout(self.conversation)
        disposition_conversation.setContentsMargins(4, 4, 4, 4)
        disposition_conversation.addWidget(self.accueil, 1)
        disposition_conversation.addWidget(self.defilement, 1)

        # --- Suggestions rapides (une fois la conversation lancée) ---
        self.barre_suggestions = QWidget()
        self.suggestions = QHBoxLayout(self.barre_suggestions)
        self.suggestions.setContentsMargins(0, 0, 0, 0)
        bouton_charger = QPushButton(icone("importer"), " Charger mon emploi du temps")
        bouton_charger.setObjectName("segment")
        bouton_charger.setToolTip("Joindre une image ou un PDF : Gemini le lit, vous vérifiez avant tout ajout")
        bouton_charger.clicked.connect(self.choisir_document)
        self.suggestions.addWidget(bouton_charger)
        for libelle, message in SUGGESTIONS:
            bouton = QPushButton(libelle)
            bouton.setObjectName("segment")
            bouton.setToolTip(message)
            bouton.clicked.connect(lambda _=False, t=message: self.envoyer(t))
            self.suggestions.addWidget(bouton)
        self.suggestions.addStretch()

        # --- Zone de saisie ---
        self.attente = QLabel()  # texte de l'indicateur « Gemini réfléchit… »
        self.piece_jointe = QWidget()
        ligne_piece = QHBoxLayout(self.piece_jointe)
        ligne_piece.setContentsMargins(0, 0, 0, 0)
        self.nom_piece = QLabel()
        self.nom_piece.setObjectName("pieceJointe")
        retirer = bouton_role(QPushButton("✕"), "discret")
        retirer.setToolTip("Retirer le document")
        retirer.clicked.connect(self.retirer_document)
        self.genre_emploi = QPushButton("Emploi du temps")
        self.genre_epreuves = QPushButton("Calendrier d'épreuves")
        for bouton, genre in ((self.genre_emploi, "emploi"), (self.genre_epreuves, "epreuves")):
            bouton.setObjectName("segment")
            bouton.setCheckable(True)
            bouton.setAutoExclusive(True)
            bouton.clicked.connect(lambda _=False, g=genre: self._choisir_genre(g))
        self.genre_emploi.setChecked(True)
        ligne_piece.addWidget(self.nom_piece)
        ligne_piece.addWidget(QLabel("à lire comme :"))
        ligne_piece.addWidget(self.genre_emploi)
        ligne_piece.addWidget(self.genre_epreuves)
        ligne_piece.addWidget(retirer)
        ligne_piece.addStretch()
        self.piece_jointe.hide()

        self.saisie = QPlainTextEdit()
        self.saisie.setObjectName("saisieAssistant")
        self.saisie.setPlaceholderText("Écrivez votre message… (ex. « J'ai un DS de réseaux samedi de 14 h à 17 h »)")
        self.saisie.setFixedHeight(64)
        QShortcut(QKeySequence("Ctrl+Return"), self.saisie, activated=lambda: self.envoyer(self.saisie.toPlainText()))
        self.bouton_joindre = bouton_role(QPushButton(icone("importer"), " Joindre"), "discret")
        self.bouton_joindre.setToolTip("Joindre une image ou un PDF : emploi du temps ou calendrier d'épreuves")
        self.bouton_joindre.clicked.connect(lambda: self.choisir_document())
        astuce = QLabel("Ctrl+Entrée pour envoyer · glissez ici une image ou un PDF")
        astuce.setObjectName("pale")
        self.bouton_envoyer = bouton_role(QPushButton(icone("envoyer", "#FFFFFF"), " Envoyer"), "primaire")
        self.bouton_envoyer.setObjectName("boutonEnvoyer")
        bouton_role(self.bouton_envoyer, "primaire")
        self.bouton_envoyer.clicked.connect(lambda: self.envoyer(self.saisie.toPlainText()))
        barre_saisie = QHBoxLayout()
        barre_saisie.addWidget(self.bouton_joindre)
        barre_saisie.addWidget(astuce)
        barre_saisie.addStretch()
        barre_saisie.addWidget(self.bouton_envoyer)

        self.composeur = QFrame()
        self.composeur.setObjectName("composeur")
        disposition_composeur = QVBoxLayout(self.composeur)
        disposition_composeur.setContentsMargins(14, 10, 10, 10)
        disposition_composeur.setSpacing(6)
        disposition_composeur.addWidget(self.piece_jointe)
        disposition_composeur.addWidget(self.saisie)
        disposition_composeur.addLayout(barre_saisie)

        colonne_chat = QWidget()
        zone = QVBoxLayout(colonne_chat)
        zone.setContentsMargins(0, 0, 0, 0)
        zone.setSpacing(10)
        zone.addWidget(self.conversation, 1)
        zone.addWidget(self.barre_suggestions)
        zone.addWidget(self.composeur)
        self.panneau = _PanneauConversations(self)
        self.panneau.ouvrir.connect(self.ouvrir_conversation)
        self.panneau.nouvelle.connect(self.recommencer)
        self.zone_active = QWidget()
        cote_a_cote = QHBoxLayout(self.zone_active)
        cote_a_cote.setContentsMargins(0, 0, 0, 0)
        cote_a_cote.setSpacing(14)
        cote_a_cote.addWidget(self.panneau)
        cote_a_cote.addWidget(colonne_chat, 1)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(14)
        disposition.addWidget(entete)
        disposition.addWidget(self.inactif)
        disposition.addWidget(self.zone_active, 1)
        disposition.addStretch(0)  # assistant non activé : la carte reste en haut au lieu de s'étirer
        self._etirement = disposition.count() - 1
        self._disposition = disposition
        self.panneau.rafraichir(None)
        self.bouton_historique.setChecked(True)
        self.rafraichir()

    # --- État -------------------------------------------------------------------

    def actif(self) -> bool:
        return self.client is not None or cle_ia.est_actif(self.base)

    def _conversation_commencee(self) -> bool:
        return self.messages.count() > 1

    def rafraichir(self) -> None:
        actif = self.actif()
        self.inactif.setVisible(not actif)
        if hasattr(self, "_disposition"):
            self._disposition.setStretch(self._etirement, 0 if actif else 1)
        self.zone_active.setVisible(actif)
        self.voir_envoi.setEnabled(self.dernier_envoi is not None)
        modele = self.client.modele if self.client else cle_ia.modele(self.base)
        self.etat_connexion.setText("●  Gemini connecté" if actif else "○  Gemini désactivé")
        self.etat_connexion.setToolTip(f"Modèle : {modele} (modifiable dans Préférences)" if actif else
                                       "Ajoutez votre clé dans Préférences > Assistant IA")
        self.etat_connexion.setObjectName("pastille" if actif else "pastilleDanger")
        self.etat_connexion.style().unpolish(self.etat_connexion)
        self.etat_connexion.style().polish(self.etat_connexion)
        commencee = self._conversation_commencee()
        self.accueil.setVisible(not commencee)
        self.defilement.setVisible(commencee)
        self.barre_suggestions.setVisible(commencee)

    def recommencer(self) -> None:
        from ..conversations import Conversation

        self._minuteur.stop()
        self._ligne_attente = None
        self.discussion = Conversation()
        self.historique = self.discussion.memoire
        self.cartes.clear()
        vider(self.messages)
        self.messages.addStretch()
        self.bouton_envoyer.setEnabled(True)
        self.panneau.rafraichir(None)
        self.rafraichir()

    # --- Historique des conversations ------------------------------------------------------

    def ouvrir_conversation(self, identifiant: int) -> bool:
        from ..conversations import charger

        conversation = charger(self.base, identifiant)
        if conversation is None:
            return False
        self.recommencer()
        self.discussion = conversation
        self.historique = conversation.memoire
        self._restauration = True
        try:
            for message in conversation.messages:
                if message.qui == "proposition":
                    self._ajouter(_CarteHistorique(message))
                else:
                    self._ajouter(_Bulle(message.texte, message.qui == "utilisateur", heure_texte=message.heure))
        finally:
            self._restauration = False
        self.panneau.rafraichir(conversation.id)
        self.rafraichir()
        return True

    def _demander_texte(self, titre: str, question: str, valeur: str) -> str | None:
        texte, ok = QInputDialog.getText(self, titre, question, text=valeur)
        return texte if ok else None

    def renommer_conversation(self, identifiant: int) -> None:
        from ..conversations import charger, renommer

        conversation = charger(self.base, identifiant)
        if conversation is None:
            return
        titre = self.demander_texte("Renommer la conversation", "Nouveau titre :", conversation.titre)
        if titre and titre.strip():
            renommer(self.base, identifiant, titre)
            if self.discussion.id == identifiant:
                self.discussion.titre = " ".join(titre.split())[:80]
            self.panneau.rafraichir(self.discussion.id)

    def supprimer_conversation(self, identifiant: int) -> None:
        from ..conversations import supprimer

        if not self.confirmer("Supprimer la conversation", "Supprimer définitivement cette conversation ?"):
            return
        supprimer(self.base, identifiant)
        if self.discussion.id == identifiant:
            self.recommencer()
        else:
            self.panneau.rafraichir(self.discussion.id)

    def effacer_historique(self) -> None:
        from ..conversations import tout_supprimer

        if not self.confirmer("Effacer l'historique", "Supprimer définitivement toutes les conversations ?"):
            return
        tout_supprimer(self.base)
        self.recommencer()

    def _ajuster_suggestions(self) -> None:
        boutons = [self.suggestions.itemAt(i).widget() for i in range(self.suggestions.count())
                   if self.suggestions.itemAt(i).widget() is not None]
        place = self.barre_suggestions.width() or self.width()
        utilise = 0
        for bouton in boutons:
            largeur = bouton.sizeHint().width() + self.suggestions.spacing()
            bouton.setVisible(utilise + largeur <= place)
            utilise += largeur if bouton.isVisibleTo(self.barre_suggestions) else 0

    def resizeEvent(self, evenement) -> None:
        super().resizeEvent(evenement)
        QTimer.singleShot(0, self._ajuster_suggestions)
        large = self.width() >= 1000  # fenêtre étroite : la liste se replie (bouton « Historique »)
        if getattr(self, "_large", None) != large:
            self._large = large
            # Fenêtre étroite : boutons de l'en-tête en icônes seules (info-bulles conservées)
            self.bouton_historique.setText(" Historique" if large else "")
            self.bouton_nouvelle.setText(" Nouvelle conversation" if large else "")
            self.voir_envoi.setText("Voir ce qui est envoyé" if large else "Envoi")
            self.bouton_historique.setChecked(large)
            self.panneau.setVisible(large)

    def _preparer_saisie(self, texte: str) -> None:
        self.saisie.setPlainText(texte)
        self.saisie.setFocus()

    def _memoriser(self, widget: QWidget) -> None:
        from ..conversations import Message, titre_automatique

        if self._restauration:
            return
        if isinstance(widget, _Bulle):
            qui = "utilisateur" if widget.de_moi else "assistant"
            self.discussion.messages.append(Message(qui, widget.texte_brut, widget.heure_texte))
            if qui == "utilisateur" and self.discussion.titre == "Nouvelle conversation":
                self.discussion.titre = titre_automatique(widget.texte_brut.replace("📎", "").strip())
        elif isinstance(widget, _CarteAction):
            widget.message = Message("proposition", widget.action.description, datetime.now().strftime("%H:%M"),
                                     "proposee")
            self.discussion.messages.append(widget.message)
        else:
            return
        self.sauver_conversation()

    def sauver_conversation(self) -> None:
        from ..conversations import enregistrer

        enregistrer(self.base, self.discussion)
        self.panneau.rafraichir(self.discussion.id)

    def _ajouter(self, widget: QWidget) -> None:
        """Ajoute un message : à droite pour l'étudiant, à gauche avec l'avatar pour l'assistant."""
        self._memoriser(widget)
        ligne = QHBoxLayout()
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.setSpacing(10)
        if widget.objectName() == "bulleMoi":
            ligne.addStretch()
            ligne.addWidget(widget)
        else:
            if isinstance(widget, _Bulle) or widget.objectName() == "ligneAttente":
                ligne.addWidget(_avatar(), 0, Qt.AlignmentFlag.AlignTop)
            else:
                ligne.addSpacing(42)  # carte de proposition alignée sous les bulles de l'assistant
            ligne.addWidget(widget)
            ligne.addStretch()
        conteneur = QWidget()
        conteneur.setLayout(ligne)
        position = self.messages.count() - 1
        if self._ligne_attente is not None and widget is not self._ligne_attente:
            index = self.messages.indexOf(self._ligne_attente.parentWidget()) if self._ligne_attente.parentWidget() else -1
            if index >= 0:
                position = index
        self.messages.insertWidget(position, conteneur)
        self.rafraichir()
        QTimer.singleShot(0, self._defiler_en_bas)

    def _defiler_en_bas(self) -> None:
        try:
            barre = self.defilement.verticalScrollBar()
            barre.setValue(barre.maximum())
        except RuntimeError:
            pass  # écran déjà fermé

    # --- Indicateur « Gemini réfléchit… » ---------------------------------------------

    def _debut_attente(self, texte: str) -> None:
        self.bouton_envoyer.setEnabled(False)
        bulle = QFrame()
        bulle.setObjectName("ligneAttente")
        disposition = QHBoxLayout(bulle)
        disposition.setContentsMargins(16, 10, 16, 10)
        self.attente = QLabel(texte)
        self.attente.setObjectName("texteAttente")
        disposition.addWidget(self.attente)
        self._texte_attente = texte
        self._points = 0
        self._ligne_attente = bulle
        self._ajouter(bulle)
        self._minuteur.start()

    def _animer_attente(self) -> None:
        self._points = (self._points + 1) % 4
        try:
            self.attente.setText(self._texte_attente + "  " + "•" * self._points)
        except RuntimeError:
            self._minuteur.stop()

    def _fin_attente(self) -> None:
        self._minuteur.stop()
        if self._ligne_attente is not None:
            conteneur = self._ligne_attente.parentWidget()
            self._ligne_attente = None
            if conteneur is not None:
                self.messages.removeWidget(conteneur)
                conteneur.hide()
                conteneur.setParent(None)
                conteneur.deleteLater()
        self.bouton_envoyer.setEnabled(True)
        self.voir_envoi.setEnabled(self.dernier_envoi is not None)

    # --- Document joint (emploi du temps en image ou PDF) ------------------------------

    def choisir_document(self, genre: str | None = None) -> None:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QFileDialog

        titre = "Joindre votre calendrier d'épreuves" if genre == "epreuves" else "Joindre un document"
        dossier = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        chemin, _ = QFileDialog.getOpenFileName(self, titre, dossier, "Image ou PDF (*.pdf *.png *.jpg *.jpeg *.webp)")
        if chemin:
            self.joindre(Path(chemin), genre)

    def _choisir_genre(self, genre: str) -> None:
        self.genre_document = genre
        (self.genre_epreuves if genre == "epreuves" else self.genre_emploi).setChecked(True)
        if self.document is not None:
            self.nom_piece.setText(f"📎  {self.document.name}")

    def joindre(self, chemin: Path, genre: str | None = None) -> bool:
        chemin = Path(chemin)
        if chemin.suffix.lower() not in TYPES_FICHIERS:
            self.avertir(self, "Format non pris en charge", "Joignez un PDF ou une image (PNG, JPG, WEBP).")
            return False
        self.document = chemin
        if genre is None:  # devine d'après le nom du fichier ; modifiable d'un clic
            nom = chemin.stem.lower()
            mots = ("exam", "epreuve", "épreuve", "compo", "partiel", "devoir", "session", "calendrier")
            genre = "epreuves" if any(mot in nom for mot in mots) else "emploi"
        self._choisir_genre(genre)
        self.piece_jointe.show()
        self.saisie.setPlaceholderText("Ajoutez une remarque si besoin (ex. « seulement le semestre 2 »), puis envoyez")
        self.saisie.setFocus()
        return True

    def retirer_document(self) -> None:
        self.document = None
        self.piece_jointe.hide()
        self.saisie.setPlaceholderText("Écrivez votre message… (ex. « J'ai un DS de réseaux samedi de 14 h à 17 h »)")

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
        from ..ia.import_epreuves import extraire_epreuves

        chemin = self.document
        epreuves = self.genre_document == "epreuves"
        self.retirer_document()
        self._ajouter(_Bulle(f"📎 {chemin.name}" + (f"\n{remarque}" if remarque else ""), de_moi=True))
        self.historique.append(("utilisateur", f"[Document joint : {chemin.name}] {remarque}".strip()))
        client = self.client or ClientGemini(cle_ia.lire_cle(self.base), cle_ia.modele(self.base))
        matieres = self.base.matieres.lister(ordre="nom")
        self._debut_attente("Gemini lit votre calendrier d'épreuves" if epreuves else "Gemini lit votre emploi du temps")

        def lu(propositions):
            self.dernier_envoi = client.dernier_envoi
            self._fin_attente()
            if epreuves:
                self._verifier_import_epreuves(propositions)
            else:
                self._verifier_import(propositions)

        def echec(message):
            self.dernier_envoi = client.dernier_envoi
            self._fin_attente()
            self._ajouter(_Bulle(f"⚠ {message}", de_moi=False))

        lecture = extraire_epreuves if epreuves else extraire
        en_fond(lambda: lecture(client, chemin, matieres, date.today(), remarque), lu, echec)

    def _verifier_import_epreuves(self, propositions) -> None:
        from .import_dialogue import DialogueImportEpreuves

        nombre = len(propositions)
        self._ajouter(_Bulle(f"J'ai reconnu **{nombre} épreuve{'s' if nombre > 1 else ''}**. Vérifiez-les dans la "
                             "fenêtre qui s'ouvre : rien n'est ajouté sans votre accord.", de_moi=False))
        dialogue = DialogueImportEpreuves(propositions, self.base.matieres.lister(ordre="nom"),
                                          self.base.epreuves.lister(), self)
        if not self.ouvrir_dialogue(dialogue):
            self._ajouter(_Bulle("Import annulé : aucune épreuve n'a été ajoutée.", de_moi=False))
            self.historique.append(("assistant", "[Import d'épreuves annulé par l'étudiant]"))
            return
        ajoutees = dialogue.resultat or dialogue.valeurs()
        for epreuve in ajoutees:
            self.base.epreuves.ajouter(epreuve)
        if ajoutees:
            premiere = min(e.debut for e in ajoutees)
            pluriel = "s" if len(ajoutees) > 1 else ""
            bilan = (f"C'est fait : **{len(ajoutees)} épreuve{pluriel}** ajoutée{pluriel}, la première le "
                     f"{premiere:%d/%m}. Leur préparation sera planifiée avant chacune.")
        else:
            bilan = "Aucune épreuve ajoutée."
        self._ajouter(_Bulle(bilan, de_moi=False))
        self.historique.append(("assistant", f"[Import d'épreuves : {bilan}]"))
        if ajoutees:
            self.donnees_modifiees.emit()
            carte_action = _CarteAction(self, Action("regenerer_planning", {}, "Recalculer le planning avec ces épreuves"))
            self.cartes.append(carte_action)
            self._ajouter(carte_action)

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
        self._debut_attente("Gemini réfléchit")

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
