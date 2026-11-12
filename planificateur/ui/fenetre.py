"""Fenêtre principale : navigation entre les écrans."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..base import Base
from ..moteur.placement import Resultat, planifier
from .commun import LIBELLES, tableau, texte_date, texte_date_heure, texte_duree
from .pages import PageEmploiDuTemps, PageEpreuves, PageMatieres, PageTravaux
from .preferences import PagePreferences


def generer(base: Base, maintenant: datetime | None = None) -> Resultat:
    """Calcule le planning à partir de toutes les données enregistrées."""
    maintenant = maintenant or datetime.now().replace(second=0, microsecond=0)
    preferences = base.preferences()
    du = maintenant.date()
    au = du + timedelta(weeks=preferences.horizon_semaines) - timedelta(days=1)
    return planifier(
        du, au, preferences,
        matieres=base.matieres.lister(),
        activites=base.activites.lister(),
        exceptions=base.exceptions.lister(),
        epreuves=base.epreuves.lister(),
        travaux=base.travaux.lister(),
        seances_existantes=base.seances.lister(),
        maintenant=maintenant,
    )


class PageApercu(QWidget):
    """Aperçu du planning calculé, sans rien enregistrer.

    Le calendrier hebdomadaire, l'édition et l'enregistrement viendront à
    l'étape 5 ; cet écran sert à vérifier que les données saisies donnent
    un planning sensé.
    """

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        titre = QLabel("Aperçu du planning")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        aide = QLabel(
            "Calcule les séances à partir de vos données, sans rien enregistrer. "
            "Le calendrier modifiable arrive à l'étape suivante."
        )
        aide.setWordWrap(True)
        aide.setStyleSheet("color: gray;")
        bouton = QPushButton("Calculer le planning")
        bouton.clicked.connect(self.calculer)
        self.resume = QLabel()
        self.resume.setWordWrap(True)
        self.table = tableau(["Jour", "Horaire", "Durée", "Type", "Matière"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.manques = QLabel()
        self.manques.setWordWrap(True)
        self.manques.setStyleSheet("color: #b00020;")

        haut = QHBoxLayout()
        haut.addWidget(bouton)
        haut.addStretch()
        disposition = QVBoxLayout(self)
        for w in (titre, aide):
            disposition.addWidget(w)
        disposition.addLayout(haut)
        disposition.addWidget(self.resume)
        disposition.addWidget(self.manques)
        disposition.addWidget(self.table)

    def calculer(self, maintenant: datetime | None = None) -> Resultat:
        resultat = generer(self.base, maintenant if isinstance(maintenant, datetime) else None)
        matieres = {x.id: x for x in self.base.matieres.lister()}
        self.table.setRowCount(len(resultat.seances))
        for n, s in enumerate(resultat.seances):
            matiere = matieres.get(s.matiere_id)
            valeurs = [
                texte_date(s.debut.date()), f"{s.debut:%H:%M} – {s.fin:%H:%M}", texte_duree(s.minutes),
                LIBELLES[s.type], matiere.nom if matiere else "",
            ]
            for c, texte in enumerate(valeurs):
                cellule = QTableWidgetItem(texte)
                if c == 4 and matiere:
                    cellule.setData(Qt.ItemDataRole.DecorationRole, QColor(matiere.couleur))
                self.table.setItem(n, c, cellule)

        total = sum(s.minutes for s in resultat.seances)
        self.resume.setText(f"{len(resultat.seances)} séances, {texte_duree(total)} de travail au total.")
        if resultat.non_places:
            lignes = []
            for d in resultat.non_places:
                quand = f" (échéance {texte_date_heure(d.echeance)})" if d.echeance else ""
                retard = " — en retard" if d.en_retard else ""
                lignes.append(f"• {d.intitule} : {texte_duree(d.minutes)} non placées{quand}{retard}")
            entete = "Tout ne tient pas dans le temps disponible :" if not resultat.faisable else "Révisions non placées faute de place :"
            self.manques.setText(entete + "\n" + "\n".join(lignes))
        else:
            self.manques.setText("")
        return resultat


class FenetrePrincipale(QMainWindow):
    ECRANS = ["Matières", "Emploi du temps", "Épreuves", "Travaux à rendre", "Préférences", "Aperçu du planning"]

    def __init__(self, base: Base) -> None:
        super().__init__()
        self.base = base
        self.setWindowTitle("Planificateur d'études")
        self.resize(1100, 720)

        self.pages = {
            "Matières": PageMatieres(base),
            "Emploi du temps": PageEmploiDuTemps(base),
            "Épreuves": PageEpreuves(base),
            "Travaux à rendre": PageTravaux(base),
            "Préférences": PagePreferences(base),
            "Aperçu du planning": PageApercu(base),
        }
        self.pile = QStackedWidget()
        self.menu = QListWidget()
        self.menu.setFixedWidth(190)
        self.menu.setStyleSheet("QListWidget { font-size: 14px; } QListWidget::item { padding: 8px; }")
        for nom in self.ECRANS:
            self.menu.addItem(nom)
            self.pile.addWidget(self.pages[nom])
        self.menu.currentRowChanged.connect(self.pile.setCurrentIndex)
        self.menu.setCurrentRow(0)

        # Une modification sur un écran met à jour les autres (noms de matières…).
        for page in self.pages.values():
            if hasattr(page, "donnees_modifiees"):
                page.donnees_modifiees.connect(self.rafraichir_tout)

        centre = QWidget()
        disposition = QHBoxLayout(centre)
        disposition.addWidget(self.menu)
        disposition.addWidget(self.pile, 1)
        self.setCentralWidget(centre)
        self.statusBar().showMessage(f"Données enregistrées dans {base.chemin}")

    def rafraichir_tout(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "rafraichir"):
                page.rafraichir()

    def afficher(self, nom: str) -> None:
        self.menu.setCurrentRow(self.ECRANS.index(nom))
