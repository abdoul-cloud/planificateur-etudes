"""Icône près de l'horloge Windows et notifications de rappel."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..base import Base
from ..rappels import Rappel, charger, deja_envoyes, marquer_envoyes, prochaine_seance, rappels_dus
from .theme import IMAGES

INTERVALLE_MS = 60_000  # vérification des rappels chaque minute


class Notificateur(QObject):
    ouvrir = Signal(str)  # écran à afficher
    commencer = Signal()  # lancer le minuteur sur la séance du moment
    quitter = Signal()

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.maintenant: datetime | None = None  # pour les tests
        self.envoyes: list[Rappel] = []  # historique de la session (utile aux tests)
        self._ecran_du_message = "Planning"
        self.icone: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icone = QSystemTrayIcon(QIcon(f"{IMAGES}/icone.png"), self)
            self.icone.setToolTip("Planificateur d'études")
            menu = QMenu()
            ouvrir = QAction("Ouvrir le planificateur", menu)
            ouvrir.triggered.connect(lambda: self.ouvrir.emit(""))
            self.action_prochaine = QAction("", menu)
            self.action_prochaine.setEnabled(False)
            planning = QAction("Planning de la semaine", menu)
            planning.triggered.connect(lambda: self.ouvrir.emit("Planning"))
            quitter = QAction("Quitter (plus de rappels)", menu)
            quitter.triggered.connect(self.quitter.emit)
            for action in (ouvrir, planning):
                menu.addAction(action)
            menu.addSeparator()
            menu.addAction(self.action_prochaine)
            self.action_commencer = QAction("▶  Commencer la séance (minuteur)", menu)
            self.action_commencer.triggered.connect(self.commencer.emit)
            menu.addAction(self.action_commencer)
            menu.addSeparator()
            menu.addAction(quitter)
            menu.aboutToShow.connect(self._actualiser_menu)
            self._menu = menu
            self.icone.setContextMenu(menu)
            self.icone.activated.connect(self._clic)
            self.icone.messageClicked.connect(lambda: self.ouvrir.emit(self._ecran_du_message))
            self.icone.show()
        self.minuteur = QTimer(self)
        self.minuteur.setInterval(INTERVALLE_MS)
        self.minuteur.timeout.connect(self.verifier)

    @property
    def disponible(self) -> bool:
        return self.icone is not None

    def demarrer(self) -> None:
        self.minuteur.start()
        QTimer.singleShot(5_000, self.verifier)

    def _clic(self, raison) -> None:
        if raison in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.ouvrir.emit("")

    def _actualiser_menu(self) -> None:
        from ..minuteur import seance_a_lancer

        self.action_commencer.setEnabled(seance_a_lancer(self.base, self.maintenant or datetime.now()) is not None)
        seance = prochaine_seance(self.base, self.maintenant or datetime.now())
        if seance is None:
            self.action_prochaine.setText("Aucune séance prévue")
        else:
            jour = "aujourd'hui" if seance.debut.date() == datetime.now().date() else seance.debut.strftime("%d/%m")
            self.action_prochaine.setText(f"Prochaine séance : {jour} à {seance.debut:%H:%M}")

    def verifier(self) -> list[Rappel]:
        """Envoie les rappels dus maintenant ; renvoie ceux envoyés."""
        maintenant = self.maintenant or datetime.now()
        dus = rappels_dus(self.base, maintenant, charger(self.base), deja_envoyes(self.base))
        for rappel in dus:
            self.notifier(rappel)
        if dus:
            marquer_envoyes(self.base, [r.cle for r in dus], maintenant)
        return dus

    def notifier(self, rappel: Rappel) -> None:
        self.envoyes.append(rappel)
        self._ecran_du_message = rappel.ecran
        if self.icone is not None:
            self.icone.showMessage(rappel.titre, rappel.texte, QIcon(f"{IMAGES}/icone.png"), 12_000)
        else:
            QApplication.beep()

    def garder_en_arriere_plan(self) -> bool:
        return self.disponible and charger(self.base).actif and charger(self.base).arriere_plan

    def cacher(self) -> None:
        if self.icone is not None:
            self.icone.hide()
