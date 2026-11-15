"""Fenêtre principale : barre latérale et écrans."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..base import Base
from ..suivi import mettre_a_jour_etats
from . import theme
from .accueil import PageAccueil
from .bilan import PageBilan
from .donnees import PageDonnees
from .calendrier import PagePlanning, generer  # noqa: F401  (generer réexporté)
from .emploi_grille import PageEmploi
from .pages import PageEpreuves, PageMatieres, PageTravaux
from .preferences import PagePreferences
from .theme import icone

# (nom, icône, section)
ECRANS = [
    ("Accueil", "accueil", "ORGANISER"),
    ("Planning", "planning", "ORGANISER"),
    ("Bilan", "bilan", "ORGANISER"),
    ("Emploi du temps", "emploi", "MES DONNÉES"),
    ("Matières", "matieres", "MES DONNÉES"),
    ("Épreuves", "epreuves", "MES DONNÉES"),
    ("Travaux à rendre", "travaux", "MES DONNÉES"),
    ("Préférences", "preferences", "RÉGLAGES"),
    ("Sauvegarde", "sauvegarde", "RÉGLAGES"),
]


class FenetrePrincipale(QMainWindow):
    ECRANS = [nom for nom, _, _ in ECRANS]

    def __init__(self, base: Base) -> None:
        super().__init__()
        self.base = base
        mettre_a_jour_etats(base)
        self.setWindowTitle("Planificateur d'études")
        self.resize(1280, 820)
        self.setMinimumSize(1000, 640)

        self.pages = {
            "Accueil": PageAccueil(base),
            "Planning": PagePlanning(base),
            "Bilan": PageBilan(base),
            "Emploi du temps": PageEmploi(base),
            "Matières": PageMatieres(base),
            "Épreuves": PageEpreuves(base),
            "Travaux à rendre": PageTravaux(base),
            "Préférences": PagePreferences(base),
            "Sauvegarde": PageDonnees(base),
        }
        self.pile = QStackedWidget()
        for nom in self.ECRANS:
            self.pile.addWidget(self.pages[nom])

        # Barre latérale
        barre = QFrame()
        barre.setObjectName("barreLaterale")
        barre.setFixedWidth(232)
        colonne = QVBoxLayout(barre)
        colonne.setContentsMargins(14, 22, 14, 16)
        colonne.setSpacing(2)
        marque = QHBoxLayout()
        pastille = QLabel()
        pastille.setFixedSize(36, 36)
        pastille.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pastille.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 10px;")
        pastille.setPixmap(theme.pixmap_icone("epreuves", "#FFFFFF", 20))
        noms = QVBoxLayout()
        noms.setSpacing(0)
        logo = QLabel("Planificateur")
        logo.setObjectName("logo")
        sous = QLabel("Mes études, organisées")
        sous.setObjectName("logoSous")
        noms.addWidget(logo)
        noms.addWidget(sous)
        marque.addWidget(pastille)
        marque.addSpacing(6)
        marque.addLayout(noms, 1)
        colonne.addLayout(marque)
        colonne.addSpacing(14)

        self.boutons: dict[str, QPushButton] = {}
        groupe = QButtonGroup(self)
        groupe.setExclusive(True)
        section = None
        for nom, icone_nom, sa_section in ECRANS:
            if sa_section != section:
                section = sa_section
                titre = QLabel(section)
                titre.setObjectName("sectionNav")
                colonne.addWidget(titre)
            bouton = QPushButton(icone(icone_nom, theme.BARRE_TEXTE, "#FFFFFF"), f"  {nom}")
            bouton.setObjectName("nav")
            bouton.setCheckable(True)
            bouton.setIconSize(QSize(18, 18))
            bouton.setCursor(Qt.CursorShape.PointingHandCursor)
            bouton.clicked.connect(lambda _=False, n=nom: self.afficher(n))
            groupe.addButton(bouton)
            colonne.addWidget(bouton)
            self.boutons[nom] = bouton
        colonne.addStretch()
        pied = QLabel("Hors ligne · données sur cet ordinateur")
        pied.setObjectName("piedNav")
        pied.setWordWrap(True)
        colonne.addWidget(pied)

        centre = QWidget()
        centre.setObjectName("contenu")
        disposition = QHBoxLayout(centre)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(0)
        disposition.addWidget(barre)
        disposition.addWidget(self.pile, 1)
        self.setCentralWidget(centre)
        self.statusBar().showMessage(f"  Données enregistrées dans {base.chemin}")

        # Liens entre écrans
        for page in self.pages.values():
            if hasattr(page, "donnees_modifiees"):
                page.donnees_modifiees.connect(self.rafraichir_tout)
        self.pages["Préférences"].preferences_enregistrees.connect(self.rafraichir_tout)
        self.pages["Accueil"].aller_a.connect(self.afficher)
        planning = self.pages["Planning"]
        # Une donnée saisie ailleurs change : le planning propose de se mettre à jour.
        for nom in ("Emploi du temps", "Matières", "Épreuves", "Travaux à rendre"):
            self.pages[nom].donnees_modifiees.connect(planning.signaler_changement)
        self.pages["Préférences"].preferences_enregistrees.connect(planning.signaler_changement)
        self.pages["Accueil"].replanifier.connect(self._replanifier_depuis_accueil)
        self.pages["Sauvegarde"].donnees_restaurees.connect(self._apres_restauration)
        self.afficher("Accueil")

    def _replanifier_depuis_accueil(self) -> None:
        planning = self.pages["Planning"]
        resultat = planning.generer()
        planning.informer("Séance manquée : le planning a été recalculé"
                          + ("" if resultat.faisable else " — tout ne tient plus, voir l'alerte"))

    def _apres_restauration(self) -> None:
        mettre_a_jour_etats(self.base)
        self.pages["Préférences"].recharger()
        self.pages["Planning"].dernier_resultat = None
        self.rafraichir_tout()

    def rafraichir_tout(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "rafraichir"):
                page.rafraichir()

    def afficher(self, nom: str) -> None:
        self.boutons[nom].setChecked(True)
        page = self.pages[nom]
        if hasattr(page, "rafraichir") and nom in ("Accueil", "Planning", "Bilan", "Sauvegarde"):
            page.rafraichir()
        self.pile.setCurrentWidget(page)
