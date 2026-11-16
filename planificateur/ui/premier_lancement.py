"""Premier lancement : trois écrans pour démarrer (horaires, matières, emploi du temps).

Proposé une seule fois, quand l'application est vide. Tout se modifie
ensuite dans les Préférences et les écrans habituels.
"""

from __future__ import annotations

from datetime import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from .commun import champ_heure, depuis_qtime
from .theme import bouton_role, icone, pixmap_icone

PARAMETRE_FAIT = "premier_lancement_fait"


def besoin_premier_lancement(base: Base) -> bool:
    return (base.parametre(PARAMETRE_FAIT) is None and not base.matieres.lister()
            and not base.activites.lister())


def proposer_premier_lancement(fenetre) -> None:
    """Ouvre l'assistant de démarrage si l'application est vide (appelé au lancement)."""
    if not besoin_premier_lancement(fenetre.base):
        return
    dialogue = DialoguePremierLancement(fenetre.base, fenetre)
    dialogue.exec()
    fenetre.pages["Préférences"].recharger()
    fenetre.rafraichir_tout()
    if dialogue.choix_emploi == "grille":
        fenetre.afficher("Emploi du temps")
    elif dialogue.choix_emploi == "document":
        fenetre.afficher("Assistant")


def _titre(texte: str, sous_titre: str) -> QWidget:
    bloc = QWidget()
    colonne = QVBoxLayout(bloc)
    colonne.setContentsMargins(0, 0, 0, 0)
    colonne.setSpacing(4)
    libelle = QLabel(texte)
    libelle.setObjectName("titreAccueil")
    detail = QLabel(sous_titre)
    detail.setObjectName("doux")
    detail.setWordWrap(True)
    colonne.addWidget(libelle)
    colonne.addWidget(detail)
    return bloc


class _Choix(QFrame):
    """Grande option cliquable (tuile)."""

    def __init__(self, icone_nom: str, titre: str, detail: str, action, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tuile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action = action
        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(16, 14, 16, 14)
        ligne.setSpacing(14)
        pictogramme = QLabel()
        pictogramme.setObjectName("pictoAction")
        pictogramme.setFixedSize(42, 42)
        pictogramme.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pictogramme.setPixmap(pixmap_icone(icone_nom, "#4F5BD5", 20))
        textes = QVBoxLayout()
        textes.setSpacing(2)
        libelle = QLabel(titre)
        libelle.setObjectName("titreTuile")
        explication = QLabel(detail)
        explication.setObjectName("detailTuile")
        explication.setWordWrap(True)
        textes.addWidget(libelle)
        textes.addWidget(explication)
        ligne.addWidget(pictogramme, 0, Qt.AlignmentFlag.AlignTop)
        ligne.addLayout(textes, 1)

    def mouseReleaseEvent(self, evenement) -> None:
        if evenement.button() == Qt.MouseButton.LeftButton:
            self.action()


class DialoguePremierLancement(QDialog):
    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.choix_emploi: str | None = None  # « grille », « document » ou None (plus tard)
        self.setWindowTitle("Bienvenue dans le Planificateur d'études")
        self.resize(720, 600)
        preferences = base.preferences()

        # --- 1. Horaires ---
        page_horaires = QWidget()
        f = QFormLayout()
        f.setSpacing(12)
        self.lever = champ_heure(preferences.debut_journee)
        self.coucher = champ_heure(preferences.fin_journee)
        dejeuner = next((p for p in preferences.pauses_quotidiennes if "jeuner" in p.nom.lower()), None)
        diner = next((p for p in preferences.pauses_quotidiennes if "ner" in p.nom.lower() and p is not dejeuner), None)
        self.dejeuner_debut = champ_heure(dejeuner.debut if dejeuner else time(12))
        self.dejeuner_fin = champ_heure(dejeuner.fin if dejeuner else time(13))
        self.diner_debut = champ_heure(diner.debut if diner else time(18))
        self.diner_fin = champ_heure(diner.fin if diner else time(19))
        garantie = preferences.plages_garanties[0] if preferences.plages_garanties else None
        self.soirees = QCheckBox("Réserver une plage de travail chaque soir de semaine, de")
        self.soirees.setChecked(garantie is not None)
        self.soir_debut = champ_heure(garantie.debut if garantie else time(20))
        self.soir_fin = champ_heure(garantie.fin if garantie else time(23))
        f.addRow("Je me lève vers", self._ligne(self.lever))
        f.addRow("Je me couche vers", self._ligne(self.coucher))
        f.addRow("Déjeuner (repas + pause)", self._ligne(self.dejeuner_debut, "à", self.dejeuner_fin))
        f.addRow("Dîner", self._ligne(self.diner_debut, "à", self.diner_fin))
        f.addRow(self._ligne(self.soirees, self.soir_debut, "à", self.soir_fin))
        colonne = QVBoxLayout(page_horaires)
        colonne.addWidget(_titre("Bienvenue ! 👋", "En trois étapes, le planificateur s'adapte à vous. "
                                 "D'abord, votre rythme : aucune séance ne sera prévue pendant votre sommeil ni vos repas."))
        colonne.addSpacing(10)
        colonne.addLayout(f)
        colonne.addStretch()
        astuce = QLabel("Tout se modifie plus tard dans Préférences (jours particuliers, moments à éviter…).")
        astuce.setObjectName("pale")
        colonne.addWidget(astuce)

        # --- 2. Matières ---
        page_matieres = QWidget()
        self.nom_matiere = QLineEdit()
        self.nom_matiere.setPlaceholderText("Nom d'une matière, puis Entrée (ex. Mathématiques)")
        self.nom_matiere.returnPressed.connect(self.ajouter_matiere)
        ajouter = bouton_role(QPushButton(icone("ajouter", "#FFFFFF"), " Ajouter"), "primaire")
        ajouter.clicked.connect(self.ajouter_matiere)
        retirer = QPushButton("Retirer la sélection")
        retirer.clicked.connect(lambda: [self.liste.takeItem(self.liste.row(i)) for i in self.liste.selectedItems()])
        self.liste = QListWidget()
        ligne_ajout = QHBoxLayout()
        ligne_ajout.addWidget(self.nom_matiere, 1)
        ligne_ajout.addWidget(ajouter)
        colonne = QVBoxLayout(page_matieres)
        colonne.addWidget(_titre("Vos matières", "Ajoutez les matières que vous étudiez. Vous préciserez plus tard, "
                                 "dans l'écran Matières, leur coefficient, leur difficulté et votre niveau."))
        colonne.addSpacing(10)
        colonne.addLayout(ligne_ajout)
        colonne.addWidget(self.liste, 1)
        colonne.addWidget(retirer, 0, Qt.AlignmentFlag.AlignLeft)

        # --- 3. Emploi du temps ---
        page_emploi = QWidget()
        colonne = QVBoxLayout(page_emploi)
        colonne.addWidget(_titre("Votre emploi du temps", "Comment voulez-vous le saisir ? Vos cours sont la base "
                                 "du planning : les révisions se placent autour, et la veille de chaque cours."))
        colonne.addSpacing(12)
        colonne.addWidget(_Choix("emploi", "Je le dessine sur la grille",
                                 "Cliquez-glissez sur les heures de chaque cours. Une option « copier sur d'autres jours » "
                                 "fait gagner du temps.", lambda: self.terminer("grille")))
        colonne.addWidget(_Choix("importer", "J'ai une photo ou un PDF",
                                 "L'assistant IA le lit pour vous (clé Gemini gratuite à ajouter dans Préférences), "
                                 "puis vous vérifiez chaque cours.", lambda: self.terminer("document")))
        colonne.addWidget(_Choix("planning", "Plus tard", "Vous pourrez le remplir à tout moment depuis l'écran "
                                 "Emploi du temps.", lambda: self.terminer(None)))
        colonne.addStretch()

        self.pile = QStackedWidget()
        for page in (page_horaires, page_matieres, page_emploi):
            self.pile.addWidget(page)

        self.etape = QLabel()
        self.etape.setObjectName("pastille")
        self.passer = bouton_role(QPushButton("Passer"), "discret")
        self.passer.clicked.connect(lambda: self.terminer(None))
        self.retour = QPushButton("Retour")
        self.retour.clicked.connect(lambda: self.aller(self.pile.currentIndex() - 1))
        self.suivant = bouton_role(QPushButton("Suivant"), "primaire")
        self.suivant.clicked.connect(lambda: self.aller(self.pile.currentIndex() + 1))
        bas = QHBoxLayout()
        bas.addWidget(self.etape)
        bas.addStretch()
        for bouton in (self.passer, self.retour, self.suivant):
            bas.addWidget(bouton)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 26, 28, 20)
        disposition.setSpacing(16)
        disposition.addWidget(self.pile, 1)
        disposition.addLayout(bas)
        self.aller(0)

    @staticmethod
    def _ligne(*elements) -> QWidget:
        bloc = QWidget()
        ligne = QHBoxLayout(bloc)
        ligne.setContentsMargins(0, 0, 0, 0)
        for element in elements:
            ligne.addWidget(QLabel(element) if isinstance(element, str) else element)
        ligne.addStretch()
        return bloc

    def aller(self, index: int) -> None:
        index = max(0, min(index, self.pile.count() - 1))
        self.pile.setCurrentIndex(index)
        self.etape.setText(f"Étape {index + 1} sur {self.pile.count()}")
        self.retour.setEnabled(index > 0)
        self.suivant.setVisible(index < self.pile.count() - 1)

    def ajouter_matiere(self) -> None:
        nom = self.nom_matiere.text().strip()
        existants = {self.liste.item(i).text().lower() for i in range(self.liste.count())}
        if nom and nom.lower() not in existants:
            self.liste.addItem(nom)
        self.nom_matiere.clear()
        self.nom_matiere.setFocus()

    def matieres(self) -> list[str]:
        return [self.liste.item(i).text() for i in range(self.liste.count())]

    def terminer(self, choix: str | None) -> None:
        """Enregistre horaires et matières, retient le choix pour l'emploi du temps, puis ferme."""
        self.ajouter_matiere()  # une matière tapée mais pas encore ajoutée compte aussi
        preferences = self.base.preferences()
        lever, coucher = depuis_qtime(self.lever.time()), depuis_qtime(self.coucher.time())
        if coucher > lever:
            preferences.debut_journee, preferences.fin_journee = lever, coucher
        pauses = []
        for nom, debut, fin in (("Déjeuner", self.dejeuner_debut, self.dejeuner_fin),
                                ("Dîner", self.diner_debut, self.diner_fin)):
            d, f = depuis_qtime(debut.time()), depuis_qtime(fin.time())
            if f > d:
                pauses.append(m.Plage(d, f, nom))
        preferences.pauses_quotidiennes = pauses
        d, f = depuis_qtime(self.soir_debut.time()), depuis_qtime(self.soir_fin.time())
        preferences.plages_garanties = [m.PlageHebdo([0, 1, 2, 3, 4], d, f)] if self.soirees.isChecked() and f > d else []
        self.base.enregistrer_preferences(preferences)
        existantes = {x.nom.lower() for x in self.base.matieres.lister()}
        for n, nom in enumerate(self.matieres()):
            if nom.lower() not in existantes:
                self.base.matieres.ajouter(m.Matiere(nom, couleur=m.couleur_libre([x.couleur for x in self.base.matieres.lister()])))
        self.base.definir_parametre(PARAMETRE_FAIT, "1")
        self.choix_emploi = choix
        self.accept()
