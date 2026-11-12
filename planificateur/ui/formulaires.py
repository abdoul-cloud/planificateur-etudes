"""Fenêtres de saisie : matière, activité fixe, épreuve, travail à rendre."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..moteur.placement import minutes_preparation
from .commun import (
    JOURS,
    LIBELLES,
    champ_date,
    champ_date_heure,
    champ_echelle,
    champ_heure,
    champ_minutes,
    depuis_qdate,
    depuis_qdatetime,
    depuis_qtime,
    texte_duree,
)


def _liste_enum(enum, valeur=None) -> QComboBox:
    choix = QComboBox()
    for membre in enum:
        choix.addItem(LIBELLES[membre], membre)
    if valeur is not None:
        choix.setCurrentIndex(choix.findData(valeur))
    return choix


def _liste_matieres(matieres: list[m.Matiere], valeur: int | None, facultative: bool) -> QComboBox:
    choix = QComboBox()
    if facultative:
        choix.addItem("— Aucune —", None)
    for matiere in matieres:
        choix.addItem(matiere.nom, matiere.id)
    index = choix.findData(valeur)
    choix.setCurrentIndex(index if index >= 0 else 0)
    return choix


def _ligne(*widgets) -> QWidget:
    conteneur = QWidget()
    disposition = QHBoxLayout(conteneur)
    disposition.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        if isinstance(w, str):
            disposition.addWidget(QLabel(w))
        else:
            disposition.addWidget(w)
    disposition.addStretch()
    return conteneur


class Formulaire(QDialog):
    """Fenêtre de saisie : le modèle est validé avant la fermeture."""

    def __init__(self, titre: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(titre)
        self.setMinimumWidth(460)
        self.form = QFormLayout()
        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText("Enregistrer")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        disposition = QVBoxLayout(self)
        disposition.addLayout(self.form)
        disposition.addWidget(boutons)
        self.resultat = None

    def valeur(self):
        raise NotImplementedError

    def _valider(self) -> None:
        try:
            self.resultat = self.valeur()
        except ValueError as erreur:
            QMessageBox.warning(self, "Saisie incomplète ou incorrecte", str(erreur))
            return
        self.accept()


# --------------------------------------------------------------------------


class FormulaireMatiere(Formulaire):
    def __init__(self, matiere: m.Matiere | None = None, parent=None) -> None:
        super().__init__("Matière", parent)
        nouvelle = matiere is None
        matiere = matiere or m.Matiere("?")
        self._id = matiere.id
        self.nom = QLineEdit("" if nouvelle else matiere.nom)
        self.nom.setPlaceholderText("ex. Mathématiques")
        self.code = QLineEdit(matiere.code)
        self.coefficient = QDoubleSpinBox()
        self.coefficient.setRange(0.5, 50)
        self.coefficient.setSingleStep(0.5)
        self.coefficient.setValue(matiere.coefficient)
        self.difficulte = champ_echelle(matiere.difficulte)
        self.maitrise = champ_echelle(matiere.maitrise)
        self.couleur = matiere.couleur
        self.bouton_couleur = QPushButton()
        self.bouton_couleur.clicked.connect(self._choisir_couleur)
        self._afficher_couleur()
        self.notes = QPlainTextEdit(matiere.notes)
        self.notes.setPlaceholderText("Chapitres, remarques…")
        self.notes.setFixedHeight(70)

        self.form.addRow("Nom *", self.nom)
        self.form.addRow("Code", self.code)
        self.form.addRow("Coefficient", self.coefficient)
        self.form.addRow("Difficulté ressentie", _ligne(self.difficulte, "1 = facile, 5 = très difficile"))
        self.form.addRow("Maîtrise actuelle", _ligne(self.maitrise, "1 = pas du tout, 5 = très bien"))
        self.form.addRow("Couleur", _ligne(self.bouton_couleur))
        self.form.addRow("Notes", self.notes)

    def _afficher_couleur(self) -> None:
        self.bouton_couleur.setText(self.couleur)
        self.bouton_couleur.setStyleSheet(f"background-color: {self.couleur}; color: white; padding: 4px 12px;")

    def _choisir_couleur(self) -> None:
        couleur = QColorDialog.getColor(QColor(self.couleur), self, "Couleur de la matière")
        if couleur.isValid():
            self.couleur = couleur.name()
            self._afficher_couleur()

    def valeur(self) -> m.Matiere:
        return m.Matiere(
            nom=self.nom.text().strip(),
            code=self.code.text().strip(),
            coefficient=self.coefficient.value(),
            difficulte=self.difficulte.value(),
            maitrise=self.maitrise.value(),
            couleur=self.couleur,
            notes=self.notes.toPlainText().strip(),
            id=self._id,
        )


# --------------------------------------------------------------------------


class FormulaireActivite(Formulaire):
    def __init__(self, matieres: list[m.Matiere], activite: m.ActiviteFixe | None = None, parent=None) -> None:
        super().__init__("Activité de l'emploi du temps", parent)
        nouvelle = activite is None
        activite = activite or m.ActiviteFixe("", time(8), time(10), jour_semaine=0)
        self._id = activite.id

        self.nom = QLineEdit(activite.nom)
        self.nom.setPlaceholderText("ex. Cours d'algèbre, Sport, Trajet…")
        self.type = _liste_enum(m.TypeActivite, activite.type)
        self.matiere = _liste_matieres(matieres, activite.matiere_id, facultative=True)

        self.chaque_semaine = QRadioButton("Chaque semaine")
        self.une_fois = QRadioButton("Une seule fois")
        groupe = QButtonGroup(self)
        groupe.addButton(self.chaque_semaine)
        groupe.addButton(self.une_fois)
        (self.chaque_semaine if activite.recurrente else self.une_fois).setChecked(True)
        self.jour = QComboBox()
        self.jour.addItems(JOURS)
        self.jour.setCurrentIndex(activite.jour_semaine or 0)
        self.date = champ_date(activite.date)
        self.debut = champ_heure(activite.heure_debut)
        self.fin = champ_heure(activite.heure_fin)

        self.limiter = QCheckBox("Seulement entre le")
        self.limiter.setChecked(activite.valide_du is not None or activite.valide_au is not None)
        self.valide_du = champ_date(activite.valide_du)
        self.valide_au = champ_date(activite.valide_au)
        self.marge_avant = champ_minutes(activite.marge_avant_min, 240, pas=5)
        self.marge_apres = champ_minutes(activite.marge_apres_min, 240, pas=5)

        self.form.addRow("Nom *", self.nom)
        self.form.addRow("Type", self.type)
        self.form.addRow("Matière", self.matiere)
        self.form.addRow("Répétition", _ligne(self.chaque_semaine, self.une_fois))
        self.form.addRow("Jour", self.jour)
        self.form.addRow("Date", self.date)
        self.form.addRow("Horaire", _ligne("de", self.debut, "à", self.fin))
        self.form.addRow("Période", _ligne(self.limiter, self.valide_du, "et le", self.valide_au))
        self.form.addRow("Trajet / marge", _ligne("avant", self.marge_avant, "après", self.marge_apres))

        self.chaque_semaine.toggled.connect(self._actualiser)
        self.limiter.toggled.connect(self._actualiser)
        if nouvelle:
            self.type.currentIndexChanged.connect(self._actualiser)
        self._actualiser()

    def _actualiser(self) -> None:
        recurrente = self.chaque_semaine.isChecked()
        self.jour.setEnabled(recurrente)
        self.date.setEnabled(not recurrente)
        self.limiter.setEnabled(recurrente)
        self.valide_du.setEnabled(recurrente and self.limiter.isChecked())
        self.valide_au.setEnabled(recurrente and self.limiter.isChecked())

    def valeur(self) -> m.ActiviteFixe:
        if not self.nom.text().strip():
            raise ValueError("Donnez un nom à l'activité")
        recurrente = self.chaque_semaine.isChecked()
        limiter = recurrente and self.limiter.isChecked()
        valide_du = depuis_qdate(self.valide_du.date()) if limiter else None
        valide_au = depuis_qdate(self.valide_au.date()) if limiter else None
        if limiter and valide_au < valide_du:
            raise ValueError("La fin de la période doit suivre son début")
        return m.ActiviteFixe(
            nom=self.nom.text().strip(),
            heure_debut=depuis_qtime(self.debut.time()),
            heure_fin=depuis_qtime(self.fin.time()),
            type=self.type.currentData(),
            jour_semaine=self.jour.currentIndex() if recurrente else None,
            date=None if recurrente else depuis_qdate(self.date.date()),
            valide_du=valide_du,
            valide_au=valide_au,
            marge_avant_min=self.marge_avant.value(),
            marge_apres_min=self.marge_apres.value(),
            matiere_id=self.matiere.currentData(),
            id=self._id,
        )


# --------------------------------------------------------------------------


class FormulaireEpreuve(Formulaire):
    def __init__(self, matieres: list[m.Matiere], epreuve: m.Epreuve | None = None, parent=None) -> None:
        super().__init__("Épreuve (interrogation, devoir, composition, examen)", parent)
        if not matieres:
            raise ValueError("Ajoutez d'abord une matière")
        if epreuve is None:
            debut = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
            epreuve = m.Epreuve(matieres[0].id, debut, debut.replace(hour=10))
        self._id = epreuve.id

        self.matiere = _liste_matieres(matieres, epreuve.matiere_id, facultative=False)
        self.type = _liste_enum(m.TypeEpreuve, epreuve.type)
        self.intitule = QLineEdit(epreuve.intitule)
        self.intitule.setPlaceholderText("facultatif, ex. Composition du 1er trimestre")
        self.date = champ_date(epreuve.debut.date())
        self.debut = champ_heure(epreuve.debut.time())
        self.fin = champ_heure(epreuve.fin.time())
        self.chapitres = QPlainTextEdit(epreuve.chapitres)
        self.chapitres.setPlaceholderText("Chapitres ou contenu à préparer")
        self.chapitres.setFixedHeight(60)
        self.importance = champ_echelle(epreuve.importance)
        self.difficulte = champ_echelle(epreuve.difficulte)
        self.preparation = champ_echelle(epreuve.preparation)
        self.etat = _liste_enum(m.EtatEpreuve, epreuve.etat)
        self.temps_libre = QCheckBox("Je choisis moi-même :")
        self.temps_libre.setChecked(epreuve.minutes_preparation is not None)
        self.temps = champ_minutes(epreuve.minutes_preparation or 120, 3000, minimum=15)
        self.estimation = QLabel()

        self.form.addRow("Matière *", self.matiere)
        self.form.addRow("Type", self.type)
        self.form.addRow("Intitulé", self.intitule)
        self.form.addRow("Date", self.date)
        self.form.addRow("Horaire", _ligne("de", self.debut, "à", self.fin))
        self.form.addRow("Contenu", self.chapitres)
        self.form.addRow("Importance", self.importance)
        self.form.addRow("Difficulté", self.difficulte)
        self.form.addRow("Préparation actuelle", _ligne(self.preparation, "1 = rien fait, 5 = prêt"))
        self.form.addRow("État", self.etat)
        self.form.addRow("Temps de préparation", self.estimation)
        self.form.addRow("", _ligne(self.temps_libre, self.temps))

        for champ in (self.importance, self.difficulte, self.preparation):
            champ.valueChanged.connect(self._actualiser)
        self.temps_libre.toggled.connect(self._actualiser)
        self._actualiser()

    def _actualiser(self) -> None:
        self.temps.setEnabled(self.temps_libre.isChecked())
        estime = minutes_preparation(
            m.Epreuve(
                1, datetime(2000, 1, 1, 8), datetime(2000, 1, 1, 9),
                importance=self.importance.value(),
                difficulte=self.difficulte.value(),
                preparation=self.preparation.value(),
            )
        )
        self.estimation.setText(f"estimation automatique : {texte_duree(estime)}")

    def valeur(self) -> m.Epreuve:
        jour = depuis_qdate(self.date.date())
        debut = datetime.combine(jour, depuis_qtime(self.debut.time()))
        fin = datetime.combine(jour, depuis_qtime(self.fin.time()))
        if fin <= debut:
            raise ValueError("L'épreuve doit finir après avoir commencé")
        return m.Epreuve(
            matiere_id=self.matiere.currentData(),
            debut=debut,
            fin=fin,
            type=self.type.currentData(),
            intitule=self.intitule.text().strip(),
            chapitres=self.chapitres.toPlainText().strip(),
            importance=self.importance.value(),
            difficulte=self.difficulte.value(),
            preparation=self.preparation.value(),
            etat=self.etat.currentData(),
            minutes_preparation=self.temps.value() if self.temps_libre.isChecked() else None,
            id=self._id,
        )


# --------------------------------------------------------------------------


class FormulaireTravail(Formulaire):
    TYPES = ["Devoir", "TD à préparer", "Exercices", "Rapport", "Projet", "Exposé", "Compte rendu"]

    def __init__(self, matieres: list[m.Matiere], travail: m.Travail | None = None, parent=None) -> None:
        super().__init__("Travail à rendre", parent)
        if not matieres:
            raise ValueError("Ajoutez d'abord une matière")
        if travail is None:
            echeance = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
            travail = m.Travail("?", matieres[0].id, echeance, 120)
            travail.intitule = ""
        self._id = travail.id

        self.intitule = QLineEdit(travail.intitule)
        self.intitule.setPlaceholderText("ex. Rapport de TP n° 3")
        self.matiere = _liste_matieres(matieres, travail.matiere_id, facultative=False)
        self.type = QComboBox()
        self.type.setEditable(True)
        self.type.addItems(self.TYPES)
        self.type.setCurrentText(travail.type.capitalize() if travail.type == "devoir" else travail.type)
        self.echeance = champ_date_heure(travail.echeance)
        self.avec_cible = QCheckBox("Je veux avoir fini avant le")
        self.avec_cible.setChecked(travail.date_cible is not None)
        self.cible = champ_date_heure(travail.date_cible or travail.echeance)
        self.estime = champ_minutes(travail.minutes_estimees, 6000, minimum=15)
        self.commence = QCheckBox("Déjà commencé, il reste :")
        self.commence.setChecked(travail.minutes_restantes != travail.minutes_estimees)
        self.restant = champ_minutes(travail.minutes_restantes, 6000)
        self.importance = champ_echelle(travail.importance)
        self.etat = _liste_enum(m.EtatTravail, travail.etat)
        self.notes = QPlainTextEdit(travail.notes)
        self.notes.setFixedHeight(60)

        self.form.addRow("Intitulé *", self.intitule)
        self.form.addRow("Matière *", self.matiere)
        self.form.addRow("Type", self.type)
        self.form.addRow("À rendre le", self.echeance)
        self.form.addRow("Date personnelle", _ligne(self.avec_cible, self.cible))
        self.form.addRow("Temps estimé", self.estime)
        self.form.addRow("", _ligne(self.commence, self.restant))
        self.form.addRow("Importance", self.importance)
        self.form.addRow("État", self.etat)
        self.form.addRow("Notes", self.notes)

        self.avec_cible.toggled.connect(self._actualiser)
        self.commence.toggled.connect(self._actualiser)
        self.estime.valueChanged.connect(self._actualiser)
        self._actualiser()

    def _actualiser(self) -> None:
        self.cible.setEnabled(self.avec_cible.isChecked())
        self.restant.setEnabled(self.commence.isChecked())
        if not self.commence.isChecked():
            self.restant.setValue(self.estime.value())

    def valeur(self) -> m.Travail:
        if not self.intitule.text().strip():
            raise ValueError("Donnez un intitulé au travail")
        restant = self.restant.value() if self.commence.isChecked() else self.estime.value()
        if restant > self.estime.value():
            raise ValueError("Le temps restant ne peut pas dépasser le temps estimé")
        return m.Travail(
            intitule=self.intitule.text().strip(),
            matiere_id=self.matiere.currentData(),
            echeance=depuis_qdatetime(self.echeance.dateTime()),
            minutes_estimees=self.estime.value(),
            minutes_restantes=restant,
            type=self.type.currentText().strip() or "Devoir",
            date_cible=depuis_qdatetime(self.cible.dateTime()) if self.avec_cible.isChecked() else None,
            importance=self.importance.value(),
            etat=self.etat.currentData(),
            notes=self.notes.toPlainText().strip(),
            id=self._id,
        )


class FormulaireAnnulation(Formulaire):
    """Annule une occurrence d'une activité hebdomadaire (férié, cours annulé)."""

    def __init__(self, activite: m.ActiviteFixe, parent=None) -> None:
        super().__init__("Annuler une séance", parent)
        self.activite = activite
        aujourd_hui = date.today()
        prochaine = aujourd_hui + timedelta(days=(activite.jour_semaine - aujourd_hui.weekday()) % 7)
        self.date = champ_date(prochaine)
        self.form.addRow(QLabel(f"« {activite.nom} » du {JOURS[activite.jour_semaine].lower()} n'aura pas lieu le :"))
        self.form.addRow("Date", self.date)

    def valeur(self) -> m.ExceptionActivite:
        jour = depuis_qdate(self.date.date())
        if jour.weekday() != self.activite.jour_semaine:
            nom_jour = JOURS[self.activite.jour_semaine].lower()
            raise ValueError(f"Cette activité a lieu le {nom_jour} : choisissez un {nom_jour}")
        return m.ExceptionActivite(self.activite.id, jour)
