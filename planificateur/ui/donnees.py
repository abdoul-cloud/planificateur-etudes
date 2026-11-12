"""Écran Sauvegarde : copie, restauration vérifiée et sauvegardes automatiques."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..base import Base, verifier_sauvegarde
from . import theme
from .theme import bouton_role, carte, en_tete, icone, vider

FILTRE = "Sauvegarde du planificateur (*.db)"


def _taille(octets: int) -> str:
    return f"{octets / 1024:.0f} Ko" if octets < 1024 * 1024 else f"{octets / 1024 / 1024:.1f} Mo"


def ouvrir_dossier(dossier: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(dossier)))


class PageDonnees(QWidget):
    donnees_restaurees = Signal()

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        # Remplaçables dans les tests (aucune fenêtre bloquante)
        self.avertir = QMessageBox.warning
        self.confirmer = lambda titre, texte: QMessageBox.question(self, titre, texte) == QMessageBox.StandardButton.Yes

        entete, _ = en_tete(
            "Sauvegarde",
            "Vos données restent uniquement sur cet ordinateur. Une copie automatique est faite chaque jour ; "
            "gardez aussi de temps en temps une sauvegarde sur une clé USB ou un autre disque.",
        )
        self.message = QLabel()
        self.message.setObjectName("pastille")
        self.message.setWordWrap(True)
        self.message.hide()

        # Fichier de données
        fichier = self._carte("Fichier de données")
        self.chemin = QLabel(str(base.chemin))
        self.chemin.setObjectName("doux")
        self.chemin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bouton_dossier = QPushButton(icone("dossier"), " Ouvrir le dossier")
        bouton_dossier.clicked.connect(lambda: ouvrir_dossier(self.base.chemin.parent))
        ligne = QHBoxLayout()
        ligne.addWidget(self.chemin, 1)
        ligne.addWidget(bouton_dossier)
        fichier.layout().addLayout(ligne)

        # Sauvegarder / restaurer côte à côte
        sauver = self._carte("Créer une sauvegarde")
        texte = QLabel("Enregistre une copie complète de vos données dans le fichier de votre choix "
                       "(par exemple sur une clé USB).")
        texte.setWordWrap(True)
        texte.setObjectName("doux")
        bouton_sauver = bouton_role(QPushButton(icone("sauvegarde", "#FFFFFF"), " Sauvegarder…"), "primaire")
        bouton_sauver.clicked.connect(self.choisir_sauvegarde)
        sauver.layout().addWidget(texte)
        sauver.layout().addWidget(bouton_sauver, 0, Qt.AlignmentFlag.AlignLeft)

        restaurer = self._carte("Restaurer une sauvegarde")
        texte = QLabel("Remplace vos données actuelles par celles d'une sauvegarde. Le fichier est vérifié "
                       "avant, et une copie de vos données actuelles est gardée au cas où.")
        texte.setWordWrap(True)
        texte.setObjectName("doux")
        bouton_restaurer = QPushButton(icone("restaurer"), " Restaurer…")
        bouton_restaurer.clicked.connect(self.choisir_restauration)
        restaurer.layout().addWidget(texte)
        restaurer.layout().addWidget(bouton_restaurer, 0, Qt.AlignmentFlag.AlignLeft)

        actions = QHBoxLayout()
        actions.setSpacing(16)
        actions.addWidget(sauver, 1)
        actions.addWidget(restaurer, 1)

        # Sauvegardes automatiques et copies de sécurité
        self.historique = self._carte("Copies dans le dossier des sauvegardes")
        entete_hist = QHBoxLayout()
        aide = QLabel("Une copie par jour à l'ouverture (les 10 dernières), plus une copie avant chaque restauration.")
        aide.setObjectName("doux")
        aide.setWordWrap(True)
        bouton_hist = QPushButton(icone("dossier"), " Ouvrir le dossier")
        bouton_hist.clicked.connect(lambda: ouvrir_dossier(self.base.dossier_sauvegardes))
        entete_hist.addWidget(aide, 1)
        entete_hist.addWidget(bouton_hist)
        self.historique.layout().addLayout(entete_hist)
        self.liste = QVBoxLayout()
        self.liste.setSpacing(4)
        self.historique.layout().addLayout(self.liste)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(16)
        disposition.addWidget(entete)
        disposition.addWidget(self.message, 0, Qt.AlignmentFlag.AlignLeft)
        disposition.addWidget(fichier)
        disposition.addLayout(actions)
        disposition.addWidget(self.historique)
        disposition.addStretch(1)
        self.rafraichir()

    def _carte(self, titre: str):
        cadre = carte()
        colonne = QVBoxLayout(cadre)
        colonne.setContentsMargins(20, 16, 20, 16)
        colonne.setSpacing(10)
        libelle = QLabel(titre)
        libelle.setObjectName("titreCarte")
        colonne.addWidget(libelle)
        return cadre

    def informer(self, texte: str) -> None:
        self.message.setText(f"✓  {texte}")
        self.message.show()
        QTimer.singleShot(6000, self.message.hide)

    def rafraichir(self) -> None:
        vider(self.liste)
        copies = sorted(self.base.dossier_sauvegardes.glob("*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not copies:
            vide = QLabel("Aucune copie pour l'instant.")
            vide.setObjectName("pale")
            self.liste.addWidget(vide)
        for copie in copies[:8]:
            quand = datetime.fromtimestamp(copie.stat().st_mtime)
            nature = "Avant restauration" if copie.name.startswith("avant-restauration") else "Automatique"
            ligne = QLabel(f"{nature} · {quand:%d/%m/%Y à %H:%M} · {_taille(copie.stat().st_size)}")
            ligne.setToolTip(str(copie))
            self.liste.addWidget(ligne)

    # --- Actions ----------------------------------------------------------------

    def choisir_sauvegarde(self) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        propose = str(Path(documents) / f"Planificateur-sauvegarde-{date.today().isoformat()}.db")
        chemin, _ = QFileDialog.getSaveFileName(self, "Enregistrer une sauvegarde", propose, FILTRE)
        if chemin:
            self.sauvegarder_vers(Path(chemin))

    def sauvegarder_vers(self, chemin: Path) -> bool:
        if chemin.suffix.lower() != ".db":
            chemin = chemin.with_suffix(".db")
        try:
            info = self.base.sauvegarder(chemin)
        except (ValueError, OSError) as erreur:
            self.avertir(self, "Sauvegarde impossible", str(erreur))
            return False
        self.informer(f"Sauvegarde enregistrée et vérifiée : {chemin.name} ({info.resume()})")
        return True

    def choisir_restauration(self) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        chemin, _ = QFileDialog.getOpenFileName(self, "Choisir une sauvegarde", documents, FILTRE)
        if chemin:
            self.restaurer_depuis(Path(chemin))

    def restaurer_depuis(self, chemin: Path) -> bool:
        try:
            info = verifier_sauvegarde(chemin)
        except ValueError as erreur:
            self.avertir(self, "Restauration impossible", str(erreur))
            return False
        modifie = datetime.fromtimestamp(chemin.stat().st_mtime)
        question = (f"Cette sauvegarde du {modifie:%d/%m/%Y à %H:%M} contient :\n{info.resume()}.\n\n"
                    "Elle va remplacer toutes vos données actuelles. Une copie de vos données actuelles "
                    "sera gardée dans le dossier des sauvegardes.\n\nContinuer ?")
        if not self.confirmer("Restaurer cette sauvegarde ?", question):
            return False
        try:
            securite = self.base.restaurer(chemin)
        except (ValueError, OSError) as erreur:
            self.avertir(self, "Restauration impossible", str(erreur))
            return False
        self.rafraichir()
        self.informer(f"Données restaurées. Vos anciennes données sont gardées dans « {securite.name} ».")
        self.donnees_restaurees.emit()
        return True
