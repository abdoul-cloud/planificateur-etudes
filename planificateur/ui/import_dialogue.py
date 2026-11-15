"""Vérification des cours lus par Gemini avant de les ajouter à l'emploi du temps."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..ia.import_edt import Proposition
from .commun import JOURS, LIBELLES, champ_date, champ_heure, depuis_qdate, depuis_qtime, tableau
from .theme import bouton_role

COLONNES = ["", "Intitulé", "Matière", "Type", "Jour", "Répétition", "Date", "Début", "Fin"]


class _Ligne:
    def __init__(self, table, rang: int, proposition: Proposition, matieres: list[m.Matiere]) -> None:
        self.inclure = QCheckBox()
        self.inclure.setChecked(True)
        self.nom = QLineEdit(proposition.nom)
        self.matiere = QComboBox()
        self.matiere.addItem("— Aucune —", None)
        for x in matieres:
            self.matiere.addItem(x.nom, x.id)
        index = self.matiere.findData(proposition.matiere_id)
        self.matiere.setCurrentIndex(max(0, index))
        if proposition.matiere_id is None:
            self.matiere.setToolTip("Matière non reconnue : choisissez-la si c'est un cours")
            self.matiere.setStyleSheet("QComboBox { border: 1px solid #D97706; }")
        self.type = QComboBox()
        for membre in m.TypeActivite:
            self.type.addItem(LIBELLES[membre], membre)
        self.type.setCurrentIndex(self.type.findData(proposition.type))
        self.jour = QComboBox()
        self.jour.addItems(JOURS)
        self.jour.setCurrentIndex(proposition.jour_semaine or 0)
        self.repetition = QComboBox()
        self.repetition.addItems(["Chaque semaine", "Une seule fois"])
        self.repetition.setCurrentIndex(1 if proposition.date else 0)
        self.date = champ_date(proposition.date or date.today())
        self.debut = champ_heure(proposition.debut)
        self.fin = champ_heure(proposition.fin)
        self.repetition.currentIndexChanged.connect(self._actualiser)
        self.date.dateChanged.connect(self._actualiser)
        centre = QWidget()
        case = QHBoxLayout(centre)
        case.setContentsMargins(8, 0, 0, 0)
        case.addWidget(self.inclure)
        widgets = [centre, self.nom, self.matiere, self.type, self.jour, self.repetition, self.date, self.debut, self.fin]
        for colonne, widget in enumerate(widgets):
            table.setCellWidget(rang, colonne, widget)
        self._actualiser()

    def _actualiser(self) -> None:
        une_fois = self.repetition.currentIndex() == 1
        self.date.setEnabled(une_fois)
        self.jour.setEnabled(not une_fois)
        if une_fois:
            self.jour.setCurrentIndex(depuis_qdate(self.date.date()).weekday())

    def activite(self, valide_au: date | None) -> m.ActiviteFixe | None:
        if not self.inclure.isChecked():
            return None
        une_fois = self.repetition.currentIndex() == 1
        nom = self.nom.text().strip()
        if not nom:
            raise ValueError("Un cours coché n'a pas d'intitulé.")
        debut, fin = depuis_qtime(self.debut.time()), depuis_qtime(self.fin.time())
        if fin <= debut:
            raise ValueError(f"« {nom} » finit avant de commencer.")
        return m.ActiviteFixe(
            nom=nom, heure_debut=debut, heure_fin=fin, type=m.TypeActivite(self.type.currentData()),
            jour_semaine=None if une_fois else self.jour.currentIndex(),
            date=depuis_qdate(self.date.date()) if une_fois else None,
            valide_au=None if une_fois else valide_au,
            matiere_id=self.matiere.currentData(),
        )


class DialogueImport(QDialog):
    def __init__(self, propositions: list[Proposition], matieres: list[m.Matiere], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vérifier l'emploi du temps lu par Gemini")
        self.resize(1400, 620)
        matieres = [x for x in matieres if not x.terminee]
        aide = QLabel(
            f"Gemini a reconnu {len(propositions)} cours. Vérifiez chaque ligne : corrigez ce qui est faux, "
            "décochez ce qu'il ne faut pas ajouter. Les matières non reconnues sont entourées en orange. "
            "Rien n'est enregistré avant « Ajouter »."
        )
        aide.setWordWrap(True)
        self.table = tableau(COLONNES)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        entete = self.table.horizontalHeader()
        for colonne, largeur in ((2, 220), (3, 120), (4, 150), (5, 185), (6, 140), (7, 105), (8, 105)):
            entete.setSectionResizeMode(colonne, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(colonne, largeur)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(propositions))
        self.lignes = [_Ligne(self.table, n, p, matieres) for n, p in enumerate(propositions)]

        self.limiter = QCheckBox("Cours hebdomadaires valables jusqu'au")
        self.jusqu_au = champ_date(date.today().replace(month=6, day=30) if date.today().month < 6
                                   else date(date.today().year + 1, 6, 30))
        self.jusqu_au.setEnabled(False)
        self.limiter.toggled.connect(self.jusqu_au.setEnabled)
        ligne_periode = QHBoxLayout()
        ligne_periode.addWidget(self.limiter)
        ligne_periode.addWidget(self.jusqu_au)
        ligne_periode.addStretch()

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bouton_role(boutons.button(QDialogButtonBox.StandardButton.Ok), "primaire").setText("Ajouter les cours cochés")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(22, 20, 22, 18)
        disposition.setSpacing(12)
        disposition.addWidget(aide)
        disposition.addWidget(self.table, 1)
        disposition.addLayout(ligne_periode)
        disposition.addWidget(boutons)
        self.resultat: list[m.ActiviteFixe] = []

    def valeurs(self) -> list[m.ActiviteFixe]:
        valide_au = depuis_qdate(self.jusqu_au.date()) if self.limiter.isChecked() else None
        return [a for a in (ligne.activite(valide_au) for ligne in self.lignes) if a is not None]

    def _valider(self) -> None:
        try:
            self.resultat = self.valeurs()
        except ValueError as erreur:
            QMessageBox.warning(self, "À corriger", str(erreur))
            return
        self.accept()
