"""Fenêtre principale : barre latérale et écrans."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..base import Base
from ..suivi import mettre_a_jour_etats
from . import theme
from .accueil import PageAccueil
from .assistant_page import PageAssistant
from .bilan import PageBilan
from .donnees import PageDonnees
from .calendrier import PagePlanning, generer  # noqa: F401  (generer réexporté)
from .emploi_grille import PageEmploi
from .notifications import Notificateur
from .pages import PageEpreuves, PageMatieres, PageTravaux
from .preferences import PagePreferences
from .theme import bouton_role, icone

URL_PROJET = "https://github.com/abdoul-cloud/planificateur-etudes"
URL_PROBLEME = URL_PROJET + "/issues/new/choose"

# (nom, icône, section)
ECRANS = [
    ("Accueil", "accueil", "ORGANISER"),
    ("Planning", "planning", "ORGANISER"),
    ("Bilan", "bilan", "ORGANISER"),
    ("Assistant", "assistant", "ORGANISER"),
    ("Emploi du temps", "emploi", "MES DONNÉES"),
    ("Matières", "matieres", "MES DONNÉES"),
    ("Épreuves", "epreuves", "MES DONNÉES"),
    ("Travaux à rendre", "travaux", "MES DONNÉES"),
    ("Préférences", "preferences", "RÉGLAGES"),
    ("Sauvegarde", "sauvegarde", "RÉGLAGES"),
]


class FenetrePrincipale(QMainWindow):
    ECRANS = [nom for nom, _, _ in ECRANS]
    ECRANS_DEFILANTS = ("Bilan", "Sauvegarde")

    def __init__(self, base: Base) -> None:
        super().__init__()
        self.base = base
        mettre_a_jour_etats(base)
        self.setWindowTitle("Planificateur d'études")
        ecran = QApplication.primaryScreen()
        if ecran is not None:  # jamais plus grande que l'écran (portables, zoom Windows à 125-150 %)
            place = ecran.availableGeometry()
            self.resize(min(1280, int(place.width() * 0.94)), min(820, int(place.height() * 0.92)))
        else:
            self.resize(1280, 820)
        self.setMinimumSize(940, 560)

        self.pages = {
            "Accueil": PageAccueil(base),
            "Planning": PagePlanning(base),
            "Bilan": PageBilan(base),
            "Assistant": PageAssistant(base),
            "Emploi du temps": PageEmploi(base),
            "Matières": PageMatieres(base),
            "Épreuves": PageEpreuves(base),
            "Travaux à rendre": PageTravaux(base),
            "Préférences": PagePreferences(base),
            "Sauvegarde": PageDonnees(base),
        }
        self.pile = QStackedWidget()
        self._cadres: dict[str, QWidget] = {}
        for nom in self.ECRANS:
            cadre = self.pages[nom]
            if nom in self.ECRANS_DEFILANTS:  # pages « tableau de bord » : défilent au lieu d'être écrasées
                cadre = QScrollArea()
                cadre.setWidgetResizable(True)
                cadre.setFrameShape(QFrame.Shape.NoFrame)
                cadre.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.pages[nom].setObjectName("defile")
                cadre.setWidget(self.pages[nom])
            self._cadres[nom] = cadre
            self.pile.addWidget(cadre)

        # Barre latérale
        barre = QFrame()
        barre.setObjectName("barreLaterale")
        barre.setFixedWidth(232)
        # Contenu défilable : sur un petit écran (portable 768 px zoomé), le menu ne force pas la hauteur
        interieur = QWidget()
        interieur.setObjectName("barreInterieur")
        colonne = QVBoxLayout(interieur)
        colonne.setContentsMargins(14, 22, 14, 16)
        colonne.setSpacing(2)
        marque = QHBoxLayout()
        pastille = QLabel()
        pastille.setFixedSize(36, 36)
        pastille.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from .theme import IMAGES

        icone_appli = QPixmap(f"{IMAGES}/icone.png")
        if icone_appli.isNull():
            pastille.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 10px;")
            pastille.setPixmap(theme.pixmap_icone("epreuves", "#FFFFFF", 20))
        else:
            pastille.setPixmap(icone_appli.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
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
        signaler = bouton_role(QPushButton(icone("alerte", theme.BARRE_TEXTE), "  Signaler un problème"), "discret")
        signaler.setObjectName("lienNav")
        signaler.setCursor(Qt.CursorShape.PointingHandCursor)
        signaler.setToolTip("Un problème ou une idée ? Ouvre la page de retours du projet sur GitHub (dans votre navigateur)")
        signaler.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(URL_PROBLEME)))
        colonne.addWidget(signaler)
        pied = QLabel(f"Version {__version__} · données sur cet ordinateur")
        pied.setObjectName("piedNav")
        pied.setWordWrap(True)
        colonne.addWidget(pied)

        centre = QWidget()
        centre.setObjectName("contenu")
        disposition = QHBoxLayout(centre)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(0)
        defile_barre = QScrollArea()
        defile_barre.setObjectName("barreDefile")
        defile_barre.setWidgetResizable(True)
        defile_barre.setFrameShape(QFrame.Shape.NoFrame)
        defile_barre.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        defile_barre.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # molette seulement
        defile_barre.setWidget(interieur)
        enveloppe_barre = QVBoxLayout(barre)
        enveloppe_barre.setContentsMargins(0, 0, 0, 0)
        enveloppe_barre.addWidget(defile_barre)
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
        self.pages["Assistant"].aller_a.connect(self.afficher)
        self.pages["Bilan"].aller_a.connect(self.afficher)
        self.pages["Bilan"].reglages_modifies.connect(planning.signaler_changement)
        self.pages["Bilan"].reglages_modifies.connect(self.pages["Préférences"].recharger)
        # Épreuves : importer un calendrier d'examens (lu par l'assistant)
        page_epreuves = self.pages["Épreuves"]
        importer = QPushButton(icone("importer"), " Importer…")
        importer.setToolTip("Calendrier d'examens en image ou PDF : l'assistant le lit, vous vérifiez avant l'ajout")
        importer.clicked.connect(self.importer_epreuves)
        page_epreuves.actions.insertWidget(0, importer)
        page_epreuves.bouton_importer = importer
        self.pages["Assistant"].donnees_modifiees.connect(planning.signaler_changement)
        self.pages["Préférences"].section_ia.reglages_changes.connect(self.pages["Assistant"].rafraichir)

        # Rappels : icône près de l'horloge et notifications
        self.notificateur = Notificateur(base, self)
        self.notificateur.ouvrir.connect(self.montrer)
        self.notificateur.quitter.connect(self.quitter)
        section_rappels = self.pages["Préférences"].section_rappels
        section_rappels.notificateur = self.notificateur
        section_rappels.rafraichir()

        # Minuteur de séance
        from .minuteur import GestionnaireMinuteur

        self.minuteur = GestionnaireMinuteur(
            base, lambda rappel: self.notificateur.disponible and self.notificateur.notifier(rappel), self)
        self.minuteur.seance_pointee.connect(self.rafraichir_tout)
        self._installer_raccourcis()
        self.minuteur.change.connect(self.pages["Accueil"].rafraichir)
        self.pages["Accueil"].minuteur_actif = lambda: self.minuteur.etat.seance_id if self.minuteur.etat else None
        self.pages["Accueil"].commencer.connect(self.commencer_seance)
        planning.commencer.connect(self.commencer_seance)
        self.notificateur.commencer.connect(self.commencer_seance_du_moment)
        self.pages["Préférences"].section_versions.verificateur = self.verifier_mises_a_jour
        self._quitter_vraiment = False
        self._prevenu_arriere_plan = False
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

    # --- Fenêtre, icône près de l'horloge -------------------------------------------

    def montrer(self, ecran: str = "") -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if ecran:
            self.afficher(ecran)

    def quitter(self) -> None:
        self._quitter_vraiment = True
        self.notificateur.cacher()
        self.close()
        QApplication.quit()

    def closeEvent(self, evenement) -> None:
        if not self._quitter_vraiment and self.notificateur.garder_en_arriere_plan():
            evenement.ignore()
            self.hide()
            if not self._prevenu_arriere_plan:
                self._prevenu_arriere_plan = True
                from ..rappels import Rappel

                self.notificateur.notifier(Rappel(
                    "info-arriere-plan", "Toujours là pour vos rappels",
                    "Le planificateur reste près de l'horloge. Clic droit sur son icône pour le quitter.", ""))
            return
        self.notificateur.cacher()
        evenement.accept()
        QApplication.quit()

    # --- Raccourcis clavier ----------------------------------------------------------------

    RACCOURCIS = [
        ("Ctrl+1 … Ctrl+0", "Aller à un écran (dans l'ordre du menu)"),
        ("Ctrl+G", "Générer le planning"),
        ("Ctrl+N", "Ajouter (matière, épreuve, travail : selon l'écran)"),
        ("Ctrl+← / Ctrl+→", "Semaine précédente / suivante (Planning, Emploi du temps)"),
        ("Ctrl+T", "Revenir à cette semaine"),
        ("Ctrl+P", "Imprimer : planning de la semaine, ou liste des épreuves"),
        ("Ctrl+M", "Commencer la séance du moment (minuteur)"),
        ("F1", "Afficher ces raccourcis"),
    ]

    def _installer_raccourcis(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        def raccourci(touches: str, action) -> None:
            QShortcut(QKeySequence(touches), self, activated=action)

        for n, nom in enumerate(self.ECRANS[:10]):
            raccourci(f"Ctrl+{(n + 1) % 10}", lambda nom=nom: self.afficher(nom))
            self.boutons[nom].setToolTip(f"Ctrl+{(n + 1) % 10}")
        raccourci("Ctrl+G", self.raccourci_generer)
        raccourci("Ctrl+N", self.raccourci_ajouter)
        raccourci("Ctrl+Left", lambda: self.raccourci_semaine(-1))
        raccourci("Ctrl+Right", lambda: self.raccourci_semaine(1))
        raccourci("Ctrl+T", lambda: self.raccourci_semaine(0))
        raccourci("Ctrl+P", self.raccourci_imprimer)
        raccourci("Ctrl+M", self.commencer_seance_du_moment)
        raccourci("F1", self.montrer_raccourcis)

    def ecran_courant(self) -> str:
        return next((nom for nom, cadre in self._cadres.items() if cadre is self.pile.currentWidget()), "")

    def raccourci_generer(self) -> None:
        self.afficher("Planning")
        self.pages["Planning"].generer()

    def raccourci_ajouter(self) -> None:
        page = self.pages.get(self.ecran_courant())
        if hasattr(page, "ajouter") and hasattr(page, "bouton_ajouter"):
            page.ajouter()

    def raccourci_semaine(self, sens: int) -> None:
        page = self.pages.get(self.ecran_courant())
        if self.ecran_courant() in ("Planning", "Emploi du temps"):
            page.aller(sens) if sens else page.aujourd_hui()

    def raccourci_imprimer(self) -> None:
        ecran = self.ecran_courant()
        if ecran == "Épreuves":
            self.pages["Épreuves"].choisir_impression()
        else:
            self.afficher("Planning")
            self.pages["Planning"].choisir_export_pdf()

    def montrer_raccourcis(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        lignes = "".join(f"<tr><td style='padding:3px 16px 3px 0'><b>{touches}</b></td><td>{effet}</td></tr>"
                         for touches, effet in self.RACCOURCIS)
        boite = QMessageBox(self)
        boite.setWindowTitle("Raccourcis clavier")
        boite.setTextFormat(Qt.TextFormat.RichText)
        boite.setText(f"<table>{lignes}</table>")
        boite.exec()

    def commencer_seance(self, seance) -> bool:
        return self.minuteur.lancer(seance)

    def commencer_seance_du_moment(self) -> bool:
        from datetime import datetime

        from ..minuteur import seance_a_lancer

        seance = seance_a_lancer(self.base, datetime.now())
        return seance is not None and self.minuteur.lancer(seance)

    def copie_externe_si_due(self) -> None:
        """Copie automatique vers la clé USB / OneDrive si la fréquence choisie est atteinte.

        Dossier absent (clé débranchée) : une notification par jour au plus, puis nouvel essai plus tard.
        """
        from datetime import datetime

        from .. import rappels
        from .. import sauvegarde_externe as se

        maintenant = datetime.now()
        if not se.copie_due(self.base, maintenant):
            return
        try:
            se.faire_copie(self.base, maintenant)
        except se.DossierIndisponible as erreur:
            cle = f"copie-externe:{maintenant:%Y-%m-%d}"
            if self.notificateur.disponible and cle not in rappels.deja_envoyes(self.base):
                self.notificateur.notifier(rappels.Rappel(cle, "Copie de sauvegarde en attente", str(erreur),
                                                          "Sauvegarde"))
                rappels.marquer_envoyes(self.base, [cle], maintenant)
        self.pages["Sauvegarde"].rafraichir()

    def importer_epreuves(self) -> None:
        assistant = self.pages["Assistant"]
        self.afficher("Assistant")
        if assistant.actif():
            assistant.choisir_document("epreuves")

    # --- Nouvelles versions ------------------------------------------------------------

    def verifier_mises_a_jour(self, forcer: bool = False, rapport=None) -> None:
        """Demande à GitHub la dernière version (en arrière-plan, au plus une fois par jour sauf si `forcer`).

        `rapport(version_ou_None, erreur="")` est appelé à la fin (écran Préférences).
        """
        from datetime import datetime

        from .. import mises_a_jour
        from .fond import en_fond

        maintenant = datetime.now().replace(second=0, microsecond=0)
        if not forcer and not mises_a_jour.a_verifier(self.base, maintenant):
            return

        def reussite(version) -> None:
            if version is not None:
                self.signaler_nouvelle_version(version)
            if rapport is not None:
                rapport(version)
            else:
                self.pages["Préférences"].section_versions.rafraichir()

        def echec(message: str) -> None:
            if rapport is not None:  # vérification automatique : silencieuse si pas d'Internet
                rapport(None, message)

        en_fond(lambda: mises_a_jour.verifier(self.base, maintenant, forcer=forcer, **self._transport_maj),
                reussite, echec)

    _transport_maj: dict = {}  # les tests y placent un faux transport (aucun accès réseau)

    def signaler_nouvelle_version(self, version) -> None:
        from datetime import datetime

        from .. import rappels

        self.pages["Accueil"].bandeau_version.montrer(version)
        cle = f"version:{version.numero}"
        # Notification Windows tous les 3 jours au plus (mémoire des rappels), jamais de bip
        if self.notificateur.disponible and cle not in rappels.deja_envoyes(self.base):
            self.notificateur.notifier(rappels.Rappel(
                cle, f"Version {version.numero} disponible",
                "Une nouvelle version du planificateur est disponible : ouvrez l'Accueil pour la télécharger.",
                "Accueil"))
            rappels.marquer_envoyes(self.base, [cle], datetime.now())

    def rafraichir_tout(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "rafraichir"):
                page.rafraichir()

    def afficher(self, nom: str) -> None:
        self.boutons[nom].setChecked(True)
        page = self.pages[nom]
        if hasattr(page, "rafraichir") and nom in ("Accueil", "Planning", "Bilan", "Sauvegarde", "Assistant"):
            page.rafraichir()
        self.pile.setCurrentWidget(self._cadres[nom])
