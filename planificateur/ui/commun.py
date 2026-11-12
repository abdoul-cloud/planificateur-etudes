"""Conversions et champs de saisie partagés par les écrans."""

from __future__ import annotations

from datetime import date, datetime, time

from PySide6.QtCore import QDate, QDateTime, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDateTimeEdit,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
JOURS_COURTS = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"]

LIBELLES = {
    m.TypeActivite.COURS: "Cours",
    m.TypeActivite.TD: "TD",
    m.TypeActivite.TP: "TP",
    m.TypeActivite.DEPLACEMENT: "Déplacement",
    m.TypeActivite.PERSONNEL: "Personnel / repos",
    m.TypeActivite.AUTRE: "Autre",
    m.TypeEpreuve.INTERROGATION: "Interrogation",
    m.TypeEpreuve.DEVOIR_SURVEILLE: "Devoir surveillé",
    m.TypeEpreuve.COMPOSITION: "Composition",
    m.TypeEpreuve.EXAMEN: "Examen",
    m.EtatEpreuve.A_PREPARER: "À préparer",
    m.EtatEpreuve.PREPAREE: "Préparée",
    m.EtatEpreuve.PASSEE: "Passée",
    m.EtatTravail.A_FAIRE: "À faire",
    m.EtatTravail.EN_COURS: "En cours",
    m.EtatTravail.TERMINE: "Terminé",
    m.EtatTravail.RENDU: "Rendu",
    m.TypeSeance.REVISION: "Révision",
    m.TypeSeance.PREPARATION: "Préparation",
    m.TypeSeance.TRAVAIL: "Travail à rendre",
}


# --- Conversions Qt <-> Python --------------------------------------------


def vers_qtime(t: time) -> QTime:
    return QTime(t.hour, t.minute)


def depuis_qtime(q: QTime) -> time:
    return time(q.hour(), q.minute())


def vers_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def depuis_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def vers_qdatetime(dt: datetime) -> QDateTime:
    return QDateTime(vers_qdate(dt.date()), vers_qtime(dt.time()))


def depuis_qdatetime(q: QDateTime) -> datetime:
    return datetime.combine(depuis_qdate(q.date()), depuis_qtime(q.time()))


# --- Affichage -------------------------------------------------------------


def texte_duree(minutes: int) -> str:
    heures, reste = divmod(int(minutes), 60)
    if not heures:
        return f"{reste} min"
    return f"{heures} h {reste:02d}" if reste else f"{heures} h"


def texte_heure(t: time) -> str:
    return t.strftime("%H:%M")


def texte_date(d: date) -> str:
    return f"{JOURS[d.weekday()].lower()} {d:%d/%m/%Y}"


def texte_date_heure(dt: datetime) -> str:
    return f"{texte_date(dt.date())} à {dt:%H:%M}"


# --- Champs de saisie ------------------------------------------------------


def champ_heure(valeur: time | None = None) -> QTimeEdit:
    champ = QTimeEdit()
    champ.setDisplayFormat("HH:mm")
    if valeur is not None:
        champ.setTime(vers_qtime(valeur))
    return champ


def champ_date(valeur: date | None = None) -> QDateEdit:
    champ = QDateEdit()
    champ.setCalendarPopup(True)
    champ.setDisplayFormat("dd/MM/yyyy")
    champ.setDate(vers_qdate(valeur or date.today()))
    return champ


def champ_date_heure(valeur: datetime | None = None) -> QDateTimeEdit:
    champ = QDateTimeEdit()
    champ.setCalendarPopup(True)
    champ.setDisplayFormat("dd/MM/yyyy HH:mm")
    champ.setDateTime(vers_qdatetime(valeur or datetime.now().replace(second=0, microsecond=0)))
    return champ


def champ_echelle(valeur: int = 3) -> QSpinBox:
    champ = QSpinBox()
    champ.setRange(1, 5)
    champ.setValue(valeur)
    champ.setSuffix(" / 5")
    return champ


def champ_minutes(valeur: int, maximum: int = 1440, minimum: int = 0, pas: int = 15) -> QSpinBox:
    champ = QSpinBox()
    champ.setRange(minimum, maximum)
    champ.setSingleStep(pas)
    champ.setSuffix(" min")
    champ.setValue(valeur)
    return champ


def tableau(colonnes: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(colonnes))
    table.setHorizontalHeaderLabels(colonnes)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


# --- Éditeurs de plages ----------------------------------------------------


class EditeurPlages(QWidget):
    """Liste de plages horaires nommées (pauses, repas, repos)."""

    def __init__(self, plages: list[m.Plage] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.table = tableau(["Nom", "Début", "Fin"])
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setMaximumHeight(190)
        ajouter = QPushButton("+ Ajouter")
        retirer = QPushButton("− Retirer")
        ajouter.clicked.connect(lambda: self._ajouter_ligne(m.Plage(time(12), time(13), "Pause")))
        retirer.clicked.connect(self._retirer_ligne)
        boutons = QHBoxLayout()
        boutons.addWidget(ajouter)
        boutons.addWidget(retirer)
        boutons.addStretch()
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addWidget(self.table)
        disposition.addLayout(boutons)
        self.definir(plages or [])

    def _ajouter_ligne(self, plage: m.Plage) -> None:
        from PySide6.QtWidgets import QLineEdit

        ligne = self.table.rowCount()
        self.table.insertRow(ligne)
        self.table.setCellWidget(ligne, 0, QLineEdit(plage.nom))
        self.table.setCellWidget(ligne, 1, champ_heure(plage.debut))
        self.table.setCellWidget(ligne, 2, champ_heure(plage.fin))

    def _retirer_ligne(self) -> None:
        ligne = self.table.currentRow()
        if ligne < 0:
            ligne = self.table.rowCount() - 1
        if ligne >= 0:
            self.table.removeRow(ligne)

    def definir(self, plages: list[m.Plage]) -> None:
        self.table.setRowCount(0)
        for plage in plages:
            self._ajouter_ligne(plage)

    def valeurs(self) -> list[m.Plage]:
        plages = []
        for ligne in range(self.table.rowCount()):
            nom = self.table.cellWidget(ligne, 0).text().strip()
            debut = depuis_qtime(self.table.cellWidget(ligne, 1).time())
            fin = depuis_qtime(self.table.cellWidget(ligne, 2).time())
            if fin <= debut:
                raise ValueError(f"La plage « {nom or ligne + 1} » finit avant de commencer")
            plages.append(m.Plage(debut, fin, nom))
        return sorted(plages, key=lambda p: p.debut)


class _ChoixJours(QWidget):
    def __init__(self, jours: list[int], parent=None) -> None:
        super().__init__(parent)
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(2, 0, 2, 0)
        self.cases = []
        for n, nom in enumerate(JOURS_COURTS):
            case = QCheckBox(nom)
            case.setChecked(n in jours)
            case.setToolTip(JOURS[n])
            self.cases.append(case)
            disposition.addWidget(case)

    def jours(self) -> list[int]:
        return [n for n, case in enumerate(self.cases) if case.isChecked()]


class EditeurPlagesHebdo(QWidget):
    """Plages répétées certains jours (moments préférés ou à éviter)."""

    def __init__(self, plages: list[m.PlageHebdo] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.table = tableau(["Jours", "Début", "Fin"])
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setMaximumHeight(190)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ajouter = QPushButton("+ Ajouter")
        retirer = QPushButton("− Retirer")
        ajouter.clicked.connect(
            lambda: self._ajouter_ligne(m.PlageHebdo([0, 1, 2, 3, 4], time(19), time(22)))
        )
        retirer.clicked.connect(self._retirer_ligne)
        boutons = QHBoxLayout()
        boutons.addWidget(ajouter)
        boutons.addWidget(retirer)
        boutons.addStretch()
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.addWidget(self.table)
        disposition.addLayout(boutons)
        self.definir(plages or [])

    def _ajouter_ligne(self, plage: m.PlageHebdo) -> None:
        ligne = self.table.rowCount()
        self.table.insertRow(ligne)
        self.table.setCellWidget(ligne, 0, _ChoixJours(plage.jours))
        self.table.setCellWidget(ligne, 1, champ_heure(plage.debut))
        self.table.setCellWidget(ligne, 2, champ_heure(plage.fin))
        self.table.resizeRowsToContents()

    def _retirer_ligne(self) -> None:
        ligne = self.table.currentRow()
        if ligne < 0:
            ligne = self.table.rowCount() - 1
        if ligne >= 0:
            self.table.removeRow(ligne)

    def definir(self, plages: list[m.PlageHebdo]) -> None:
        self.table.setRowCount(0)
        for plage in plages:
            self._ajouter_ligne(plage)

    def valeurs(self) -> list[m.PlageHebdo]:
        plages = []
        for ligne in range(self.table.rowCount()):
            jours = self.table.cellWidget(ligne, 0).jours()
            debut = depuis_qtime(self.table.cellWidget(ligne, 1).time())
            fin = depuis_qtime(self.table.cellWidget(ligne, 2).time())
            if not jours:
                raise ValueError(f"Cochez au moins un jour pour la plage n° {ligne + 1}")
            if fin <= debut:
                raise ValueError(f"La plage n° {ligne + 1} finit avant de commencer")
            plages.append(m.PlageHebdo(jours, debut, fin))
        return plages
