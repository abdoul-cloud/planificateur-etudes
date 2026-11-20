"""Petite fenêtre du minuteur de séance, toujours visible en bas à droite de l'écran."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import minuteur as mt
from .. import modeles as m
from ..base import Base
from ..rappels import Rappel
from . import theme
from .commun import LIBELLES
from .theme import bouton_role, icone


class FenetreMinuteur(QWidget):
    pause = Signal()
    reprise = Signal()
    fin = Signal()
    abandon = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Séance en cours")
        self.setObjectName("fenetreMinuteur")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(320)
        self.setStyleSheet(STYLE)
        self.titre = QLabel()
        self.titre.setObjectName("titreCarte")
        self.titre.setWordWrap(True)
        self.sous_titre = QLabel()
        self.sous_titre.setObjectName("doux")
        self.temps = QLabel("00:00")
        self.temps.setObjectName("grandChiffre")
        self.objectif = QLabel()
        self.objectif.setObjectName("doux")
        self.barre = QProgressBar()
        self.barre.setTextVisible(False)
        self.barre.setFixedHeight(8)
        self.etat = QLabel()
        self.etat.setObjectName("doux")
        self.etat.setWordWrap(True)
        self.bouton_pause = QPushButton("Pause")
        self.bouton_pause.clicked.connect(self._basculer)
        self.bouton_fin = bouton_role(QPushButton(icone("coche", "#FFFFFF"), " Terminer"), "primaire")
        self.bouton_fin.setToolTip("Arrête le minuteur et pointe la séance avec le temps réellement travaillé")
        self.bouton_fin.clicked.connect(self.fin)
        abandon = bouton_role(QPushButton("Annuler"), "discret")
        abandon.setToolTip("Arrête sans rien pointer")
        abandon.clicked.connect(self.abandon)
        ligne_temps = QHBoxLayout()
        ligne_temps.addWidget(self.temps)
        ligne_temps.addStretch()
        ligne_temps.addWidget(self.objectif, 0, Qt.AlignmentFlag.AlignBottom)
        boutons = QHBoxLayout()
        boutons.addWidget(abandon)
        boutons.addStretch()
        boutons.addWidget(self.bouton_pause)
        boutons.addWidget(self.bouton_fin)
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(18, 14, 18, 14)
        colonne.setSpacing(6)
        colonne.addWidget(self.titre)
        colonne.addWidget(self.sous_titre)
        colonne.addLayout(ligne_temps)
        colonne.addWidget(self.barre)
        colonne.addWidget(self.etat)
        colonne.addLayout(boutons)
        self.en_pause = False

    def _basculer(self) -> None:
        (self.reprise if self.en_pause else self.pause).emit()

    def afficher(self, seance: m.Seance, nom: str, secondes: int, en_pause: bool) -> None:
        self.en_pause = en_pause
        self.titre.setText(nom)
        self.sous_titre.setText(f"{LIBELLES[seance.type]} · prévue {seance.debut:%H:%M} – {seance.fin:%H:%M}")
        self.temps.setText(mt.texte_duree(secondes))
        self.objectif.setText(f"sur {seance.minutes} min")
        self.barre.setMaximum(max(1, seance.minutes * 60))
        self.barre.setValue(min(secondes, seance.minutes * 60))
        self.bouton_pause.setText("Reprendre" if en_pause else "Pause")
        if en_pause:
            self.etat.setText("⏸ En pause : le temps de pause n'est pas compté.")
        elif secondes >= seance.minutes * 60:
            self.etat.setText("✓ Temps prévu atteint. Terminez quand vous voulez.")
        else:
            reste = seance.minutes * 60 - secondes
            self.etat.setText(f"Encore {mt.texte_duree(reste)} · pause proposée toutes les {mt.CONCENTRATION_MIN} min")

    def placer(self) -> None:
        ecran = QApplication.primaryScreen()
        self.adjustSize()
        if ecran is not None:
            zone = ecran.availableGeometry()
            self.move(zone.right() - self.width() - 24, zone.bottom() - self.height() - 24)


class GestionnaireMinuteur(QObject):
    """Lance, suit et termine le minuteur ; prévient la fenêtre principale quand une séance est pointée."""

    seance_pointee = Signal()
    change = Signal()  # démarré ou arrêté (pour griser les boutons « Commencer »)

    def __init__(self, base: Base, notifier: Callable[[Rappel], None] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.notifier = notifier
        self.horloge: Callable[[], datetime] = datetime.now  # remplaçable dans les tests
        self.confirmer: Callable[[str, str], bool] = self._confirmer
        self.etat: mt.EtatMinuteur | None = None
        self.seance: m.Seance | None = None
        self.fenetre: FenetreMinuteur | None = None
        self.dernier_message = ""
        self.tic = QTimer(self)
        self.tic.timeout.connect(self.actualiser)

    # --- Cycle de vie ---------------------------------------------------------------

    def actif(self) -> bool:
        return self.etat is not None

    def reprendre_si_besoin(self) -> bool:
        """Au démarrage : un minuteur resté ouvert reprend là où il en était."""
        etat = mt.charger(self.base)
        if etat is None:
            return False
        self.etat, self.seance = etat, self.base.seances.obtenir(etat.seance_id)
        self._ouvrir()
        return True

    def lancer(self, seance: m.Seance) -> bool:
        if self.etat is not None:
            if self.etat.seance_id == seance.id:
                self._ouvrir()
                return True
            if not self.confirmer("Une séance est déjà en cours",
                                  "Terminer la séance en cours (elle sera pointée) et commencer celle-ci ?"):
                return False
            self.terminer()
        self.seance = seance
        self.etat = mt.demarrer(self.base, seance, self.horloge())
        self._ouvrir()
        self.change.emit()
        return True

    def _ouvrir(self) -> None:
        if self.fenetre is None:
            self.fenetre = FenetreMinuteur()
            self.fenetre.pause.connect(self.mettre_en_pause)
            self.fenetre.reprise.connect(self.reprendre)
            self.fenetre.fin.connect(self.terminer)
            self.fenetre.abandon.connect(self.annuler)
        self.actualiser()
        self.fenetre.placer()
        self.fenetre.show()
        self.fenetre.raise_()
        self.tic.start(1000)

    def _fermer(self) -> None:
        self.tic.stop()
        if self.fenetre is not None:
            self.fenetre.hide()
        self.etat, self.seance = None, None
        self.change.emit()

    # --- Actions ----------------------------------------------------------------------

    def nom(self) -> str:
        matiere = self.base.matieres.obtenir(self.seance.matiere_id) if self.seance and self.seance.matiere_id else None
        return matiere.nom if matiere else "Séance de travail"

    def actualiser(self) -> None:
        if self.etat is None or self.seance is None:
            return
        maintenant = self.horloge()
        if self.etat.pause_a_proposer(maintenant):
            mt.enregistrer(self.base, self.etat)
            self._notifier("Petite pause ?", f"{mt.CONCENTRATION_MIN} min de concentration : {mt.PAUSE_MIN} min de "
                                             "pause vous aideront à tenir. Cliquez sur Pause dans le minuteur.")
        if self.etat.fin_a_annoncer(self.seance, maintenant):
            mt.enregistrer(self.base, self.etat)
            self._notifier("Temps prévu atteint", f"{self.nom()} : bravo ! Cliquez sur Terminer pour pointer la séance.")
        if self.fenetre is not None:
            self.fenetre.afficher(self.seance, self.nom(), self.etat.secondes_travaillees(maintenant),
                                  self.etat.en_pause())

    def mettre_en_pause(self) -> None:
        if self.etat is not None:
            self.etat.mettre_en_pause(self.horloge())
            mt.enregistrer(self.base, self.etat)
            self.actualiser()

    def reprendre(self) -> None:
        if self.etat is not None:
            self.etat.reprendre(self.horloge())
            mt.enregistrer(self.base, self.etat)
            self.actualiser()

    def terminer(self) -> str:
        if self.etat is None:
            return ""
        nom = self.nom()
        seance, minutes = mt.terminer(self.base, self.etat, self.horloge())
        if seance is None:
            message = f"Moins de {mt.MINIMUM_POINTE} min travaillées : rien n'a été pointé."
        elif seance.statut is m.StatutSeance.TERMINEE:
            message = f"{nom} : séance faite ({minutes} min). Bravo !"
        else:
            message = f"{nom} : faite en partie ({minutes} min sur {seance.minutes})."
        self.dernier_message = message
        self._fermer()
        self._notifier("Séance pointée" if seance else "Minuteur arrêté", message)
        if seance is not None:
            self.seance_pointee.emit()
        return message

    def annuler(self) -> None:
        if self.etat is not None and not self.confirmer("Annuler le minuteur", "Arrêter sans pointer la séance ?"):
            return
        mt.annuler(self.base)
        self._fermer()

    def _notifier(self, titre: str, texte: str) -> None:
        if self.notifier is not None:
            self.notifier(Rappel(f"minuteur:{titre}", titre, texte, ""))

    def _confirmer(self, titre: str, texte: str) -> bool:
        parent = self.fenetre if self.fenetre is not None and self.fenetre.isVisible() else None
        return QMessageBox.question(parent, titre, texte) == QMessageBox.StandardButton.Yes


STYLE = f"""
QWidget#fenetreMinuteur {{ background: white; border: 1px solid #D5D9E3; border-radius: 14px; }}
QWidget#fenetreMinuteur QProgressBar {{ background: #EEF0F6; border: none; border-radius: 4px; }}
QWidget#fenetreMinuteur QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 4px; }}
"""
