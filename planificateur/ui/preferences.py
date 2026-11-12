"""Écran des préférences : horaires flexibles, pauses, repos, limites."""

from __future__ import annotations

from datetime import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from .commun import (
    JOURS,
    EditeurPlages,
    EditeurPlagesHebdo,
    champ_heure,
    champ_minutes,
    depuis_qtime,
    tableau,
    vers_qtime,
)


def _nombre(valeur: int, minimum: int, maximum: int, suffixe: str) -> QSpinBox:
    champ = QSpinBox()
    champ.setRange(minimum, maximum)
    champ.setValue(valeur)
    champ.setSuffix(suffixe)
    return champ


class DialoguePauses(QDialog):
    """Pauses d'un jour particulier."""

    def __init__(self, jour: str, pauses: list[m.Plage], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Pauses du {jour.lower()}")
        self.setMinimumWidth(420)
        self.editeur = EditeurPlages(pauses)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        disposition = QVBoxLayout(self)
        disposition.addWidget(QLabel("Repas, sieste, repos… aucune séance n'y sera placée."))
        disposition.addWidget(self.editeur)
        disposition.addWidget(boutons)
        self.pauses = pauses

    def _valider(self) -> None:
        try:
            self.pauses = self.editeur.valeurs()
        except ValueError as erreur:
            QMessageBox.warning(self, "Saisie incorrecte", str(erreur))
            return
        self.accept()


class _LigneJour:
    """Une ligne du tableau des jours particuliers."""

    def __init__(self, page: PagePreferences, jour: int) -> None:
        self.page = page
        self.jour = jour
        self.particulier = QCheckBox()
        self.travaille = QCheckBox("travail")
        self.debut = champ_heure(time(7))
        self.fin = champ_heure(time(23))
        self.limite = champ_minutes(360, 1440)
        self.bouton_pauses = QPushButton()
        self.pauses: list[m.Plage] = []
        self.particulier.toggled.connect(self._basculer)
        self.travaille.toggled.connect(self._actualiser)
        self.bouton_pauses.clicked.connect(self._editer_pauses)

    def widgets(self):
        return [self.particulier, self.travaille, self.debut, self.fin, self.limite, self.bouton_pauses]

    def definir(self, reglage: m.ReglageJour | None) -> None:
        self.particulier.blockSignals(True)
        self.particulier.setChecked(reglage is not None)
        self.particulier.blockSignals(False)
        self._remplir(reglage or self.page.reglage_general())

    def _remplir(self, reglage: m.ReglageJour) -> None:
        self.travaille.setChecked(reglage.travaille)
        self.debut.setTime(vers_qtime(reglage.debut))
        self.fin.setTime(vers_qtime(reglage.fin))
        self.limite.setValue(reglage.max_minutes)
        self.pauses = list(reglage.pauses)
        self._actualiser()

    def _basculer(self, particulier: bool) -> None:
        if particulier:  # on part du réglage général
            try:
                self._remplir(self.page.reglage_general())
            except ValueError:
                pass
        self._actualiser()

    def _actualiser(self) -> None:
        actif = self.particulier.isChecked()
        self.travaille.setEnabled(actif)
        detail = actif and self.travaille.isChecked()
        for w in (self.debut, self.fin, self.limite, self.bouton_pauses):
            w.setEnabled(detail)
        self.bouton_pauses.setText(f"Pauses ({len(self.pauses)})…")

    def _editer_pauses(self) -> None:
        dialogue = DialoguePauses(JOURS[self.jour], self.pauses, self.page)
        if dialogue.exec():
            self.pauses = dialogue.pauses
            self._actualiser()

    def reglage(self) -> m.ReglageJour | None:
        if not self.particulier.isChecked():
            return None
        debut, fin = depuis_qtime(self.debut.time()), depuis_qtime(self.fin.time())
        if self.travaille.isChecked() and fin <= debut:
            raise ValueError(f"{JOURS[self.jour]} : la journée doit finir après avoir commencé")
        if not self.travaille.isChecked():
            return m.ReglageJour(travaille=False)
        return m.ReglageJour(True, debut, fin, self.limite.value(), list(self.pauses))


class PagePreferences(QWidget):
    preferences_enregistrees = Signal()

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base

        titre = QLabel("Préférences")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        aide = QLabel(
            "Rien n'est imposé : adaptez les horaires, les pauses et les limites à votre rythme. "
            "Un jour particulier remplace la journée type pour ce jour de la semaine."
        )
        aide.setWordWrap(True)
        aide.setStyleSheet("color: gray;")

        # Séances
        self.duree_min = champ_minutes(45, 240, minimum=15, pas=5)
        self.duree_max = champ_minutes(90, 480, minimum=15, pas=5)
        self.pause_min = champ_minutes(10, 120, pas=5)
        seances = QGroupBox("Séances")
        f = QFormLayout(seances)
        f.addRow("Durée minimale", self.duree_min)
        f.addRow("Durée maximale", self.duree_max)
        f.addRow("Pause entre deux séances", self.pause_min)

        # Journée type
        self.debut_journee = champ_heure(time(7))
        self.fin_journee = champ_heure(time(23))
        self.max_jour = champ_minutes(360, 1440, minimum=15)
        self.pauses = EditeurPlages()
        journee = QGroupBox("Journée type")
        f = QFormLayout(journee)
        horaires = QHBoxLayout()
        for w in (QLabel("de"), self.debut_journee, QLabel("à"), self.fin_journee):
            horaires.addWidget(w)
        horaires.addStretch()
        f.addRow("Travail possible", horaires)
        f.addRow("Au plus, par jour", self.max_jour)
        f.addRow("Pauses de chaque jour", self.pauses)

        # Jours particuliers
        self.table_jours = tableau(["Jour", "Particulier", "Travail", "Début", "Fin", "Limite", "Pauses"])
        self.table_jours.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_jours.setRowCount(7)
        self.lignes_jours = []
        for jour in range(7):
            ligne = _LigneJour(self, jour)
            self.table_jours.setItem(jour, 0, QTableWidgetItem(JOURS[jour]))
            for colonne, widget in enumerate(ligne.widgets(), start=1):
                self.table_jours.setCellWidget(jour, colonne, widget)
            self.lignes_jours.append(ligne)
        self.table_jours.setMinimumHeight(260)
        jours = QGroupBox("Jours particuliers (ex. samedi plus court, dimanche de repos)")
        QVBoxLayout(jours).addWidget(self.table_jours)

        # Moments préférés / évités
        self.preferees = EditeurPlagesHebdo()
        self.evitees = EditeurPlagesHebdo()
        moments = QGroupBox("Moments préférés et moments à éviter")
        f = QFormLayout(moments)
        f.addRow("Préférés", self.preferees)
        f.addRow("À éviter (si possible)", self.evitees)

        # Échéances et révisions
        self.revisions = champ_minutes(300, 3000)
        self.repos_epreuve = champ_minutes(180, 1440)
        self.max_jour_epreuve = champ_minutes(120, 1440)
        self.marge = _nombre(12, 0, 168, " h")
        self.horizon = _nombre(3, 1, 12, " semaines")
        echeances = QGroupBox("Échéances et révisions")
        f = QFormLayout(echeances)
        f.addRow("Révisions régulières par semaine", self.revisions)
        f.addRow("Repos avant une épreuve", self.repos_epreuve)
        f.addRow("Au plus, le jour d'une épreuve", self.max_jour_epreuve)
        f.addRow("Finir un travail à rendre", _avec_texte(self.marge, "avant l'échéance"))
        f.addRow("Planifier sur", self.horizon)

        # Boutons
        enregistrer = QPushButton("Enregistrer")
        enregistrer.setDefault(True)
        enregistrer.clicked.connect(self.enregistrer)
        annuler = QPushButton("Annuler les modifications")
        annuler.clicked.connect(self.recharger)
        defaut = QPushButton("Valeurs par défaut")
        defaut.clicked.connect(lambda: self.charger(m.Preferences()))
        boutons = QHBoxLayout()
        for b in (enregistrer, annuler, defaut):
            boutons.addWidget(b)
        boutons.addStretch()

        contenu = QWidget()
        colonne = QVBoxLayout(contenu)
        for w in (titre, aide, seances, journee, jours, moments, echeances):
            colonne.addWidget(w)
        colonne.addLayout(boutons)
        colonne.addStretch()
        defilement = QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setWidget(contenu)
        QVBoxLayout(self).addWidget(defilement)

        self.recharger()

    def reglage_general(self) -> m.ReglageJour:
        return m.ReglageJour(
            True,
            depuis_qtime(self.debut_journee.time()),
            depuis_qtime(self.fin_journee.time()),
            self.max_jour.value(),
            self.pauses.valeurs(),
        )

    def charger(self, p: m.Preferences) -> None:
        self.duree_min.setValue(p.duree_min_seance)
        self.duree_max.setValue(p.duree_max_seance)
        self.pause_min.setValue(p.pause_min)
        self.debut_journee.setTime(vers_qtime(p.debut_journee))
        self.fin_journee.setTime(vers_qtime(p.fin_journee))
        self.max_jour.setValue(p.max_minutes_jour)
        self.pauses.definir(p.pauses_quotidiennes)
        for ligne in self.lignes_jours:
            ligne.definir(p.reglages_jour.get(ligne.jour))
        self.preferees.definir(p.plages_preferees)
        self.evitees.definir(p.plages_evitees)
        self.revisions.setValue(p.minutes_revision_semaine)
        self.repos_epreuve.setValue(p.repos_avant_epreuve_min)
        self.max_jour_epreuve.setValue(p.max_minutes_jour_epreuve)
        self.marge.setValue(p.marge_echeance_heures)
        self.horizon.setValue(p.horizon_semaines)

    def lire(self) -> m.Preferences:
        if self.duree_max.value() < self.duree_min.value():
            raise ValueError("La durée maximale d'une séance doit dépasser la durée minimale")
        general = self.reglage_general()
        if general.fin <= general.debut:
            raise ValueError("La journée type doit finir après avoir commencé")
        reglages = {}
        for ligne in self.lignes_jours:
            reglage = ligne.reglage()
            if reglage is not None:
                reglages[ligne.jour] = reglage
        return m.Preferences(
            duree_min_seance=self.duree_min.value(),
            duree_max_seance=self.duree_max.value(),
            pause_min=self.pause_min.value(),
            debut_journee=general.debut,
            fin_journee=general.fin,
            max_minutes_jour=general.max_minutes,
            pauses_quotidiennes=general.pauses,
            reglages_jour=reglages,
            plages_preferees=self.preferees.valeurs(),
            plages_evitees=self.evitees.valeurs(),
            marge_echeance_heures=self.marge.value(),
            horizon_semaines=self.horizon.value(),
            minutes_revision_semaine=self.revisions.value(),
            repos_avant_epreuve_min=self.repos_epreuve.value(),
            max_minutes_jour_epreuve=self.max_jour_epreuve.value(),
        )

    def recharger(self) -> None:
        self.charger(self.base.preferences())

    def enregistrer(self) -> bool:
        try:
            preferences = self.lire()
        except ValueError as erreur:
            QMessageBox.warning(self, "Préférences incorrectes", str(erreur))
            return False
        self.base.enregistrer_preferences(preferences)
        self.preferences_enregistrees.emit()
        return True


def _avec_texte(champ: QWidget, texte: str) -> QWidget:
    conteneur = QWidget()
    disposition = QHBoxLayout(conteneur)
    disposition.setContentsMargins(0, 0, 0, 0)
    disposition.addWidget(champ)
    disposition.addWidget(QLabel(texte))
    disposition.addStretch()
    return conteneur
