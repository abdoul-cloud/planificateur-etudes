"""Écran des préférences : horaires flexibles, pauses, repos, limites."""

from __future__ import annotations

from datetime import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QComboBox,
    QLineEdit,
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
from ..ia import cle as cle_ia
from .theme import bouton_role, en_tete, icone
from .commun import (
    _ChoixJours,
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
        self.travaille = QCheckBox()
        self.travaille.setToolTip("Décochez pour un jour sans travail")
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

        entete, actions = en_tete(
            "Préférences",
            "Rien n'est imposé : adaptez les horaires, les pauses et les limites à votre rythme. "
            "Un jour particulier remplace la journée type pour ce jour de la semaine.",
        )

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
        journee = QGroupBox("Journée type et sommeil")
        f = QFormLayout(journee)
        f.addRow("Lever", self.debut_journee)
        f.addRow("Coucher", self.fin_journee)
        f.addRow("Au plus, par jour", self.max_jour)
        f.addRow("Pauses", self.pauses)

        # Jours particuliers
        self.table_jours = tableau(["Jour", "Particulier", "Travail", "Lever", "Coucher", "Limite", "Pauses"])
        self.table_jours.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_jours.setRowCount(7)
        self.lignes_jours = []
        for jour in range(7):
            ligne = _LigneJour(self, jour)
            self.table_jours.setItem(jour, 0, QTableWidgetItem(JOURS[jour]))
            for colonne, widget in enumerate(ligne.widgets(), start=1):
                self.table_jours.setCellWidget(jour, colonne, widget)
            self.lignes_jours.append(ligne)
        self.table_jours.verticalHeader().setDefaultSectionSize(44)
        self.table_jours.setMinimumHeight(7 * 44 + 46)
        jours = QGroupBox("Jours particuliers (ex. samedi plus court, dimanche de repos)")
        QVBoxLayout(jours).addWidget(self.table_jours)

        # Moments préférés / évités
        self.preferees = EditeurPlagesHebdo()
        self.evitees = EditeurPlagesHebdo()
        self.garanties = EditeurPlagesHebdo()
        self.jours_libres = _ChoixJours([0, 1, 2, 3, 4])
        self.minutes_libres = champ_minutes(45, 240, minimum=15, pas=15)
        self.espace_libres = champ_minutes(60, 480, pas=15)
        moments = QGroupBox("Moments de travail : garantis, préférés, à éviter")
        disposition_moments = QVBoxLayout(moments)
        disposition_moments.setSpacing(14)
        libres = QFormLayout()
        libres.addRow("Autres moments libres : séances de", _avec_texte(self.minutes_libres, ""))
        libres.addRow("espacées d'au moins", _avec_texte(self.espace_libres, ""))
        libres.addRow("les jours", self.jours_libres)
        disposition_moments.addLayout(libres)
        for libelle, editeur in (("Garantis : toujours remplis de travail (sauf activité, pause ou sommeil) — par défaut du lundi au vendredi, 20 h – 23 h", self.garanties),
                                 ("Préférés : choisis en premier", self.preferees),
                                 ("À éviter : utilisés seulement si nécessaire", self.evitees)):
            bloc = QVBoxLayout()
            titre_bloc = QLabel(libelle)
            titre_bloc.setWordWrap(True)
            bloc.addWidget(titre_bloc)
            bloc.addWidget(editeur)
            disposition_moments.addLayout(bloc, 1)

        # Échéances et révisions
        self.revisions = champ_minutes(300, 3000)
        self.repos_epreuve = champ_minutes(180, 1440)
        self.max_jour_epreuve = champ_minutes(120, 1440)
        self.libre_apres = QCheckBox("Soirée libre (rien jusqu'au lendemain)")
        self.marge = _nombre(12, 0, 168, " h")
        self.horizon = _nombre(3, 1, 12, " semaines")
        echeances = QGroupBox("Échéances et révisions")
        f = QFormLayout(echeances)
        f.addRow("Révisions régulières par semaine", self.revisions)
        f.addRow("Repos avant une épreuve", self.repos_epreuve)
        f.addRow("Au plus, le jour d'une épreuve", self.max_jour_epreuve)
        f.addRow("Après une épreuve", self.libre_apres)
        f.addRow("Finir un travail à rendre", _avec_texte(self.marge, "avant l'échéance"))
        f.addRow("Planifier sur", self.horizon)

        # Boutons
        enregistrer = bouton_role(QPushButton(icone("coche", "#FFFFFF"), " Enregistrer"), "primaire")
        enregistrer.clicked.connect(self.enregistrer)
        annuler = QPushButton("Annuler les modifications")
        annuler.clicked.connect(self.recharger)
        defaut = bouton_role(QPushButton("Valeurs par défaut"), "discret")
        defaut.clicked.connect(lambda: self.charger(m.Preferences()))
        for b in (defaut, annuler, enregistrer):
            actions.addWidget(b)
        self.confirmation = QLabel("")
        self.confirmation.setObjectName("pastille")
        self.confirmation.hide()

        contenu = QWidget()
        contenu.setObjectName("defile")
        colonne = QVBoxLayout(contenu)
        colonne.setContentsMargins(0, 0, 12, 12)
        colonne.setSpacing(4)
        # Deux colonnes si la place le permet, une seule dans une fenêtre étroite (voir resizeEvent)
        grille = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        grille.setSpacing(16)
        self._grille = grille
        gauche, droite = QVBoxLayout(), QVBoxLayout()
        for w in (seances, echeances):
            gauche.addWidget(w)
        gauche.addStretch()
        droite.addWidget(journee)
        droite.addStretch()
        grille.addLayout(gauche, 1)
        grille.addLayout(droite, 1)
        colonne.addLayout(grille)
        colonne.addWidget(jours)
        colonne.addWidget(moments)
        self.section_rappels = SectionRappels(base)
        colonne.addWidget(self.section_rappels)
        self.section_ia = SectionAssistant(base)
        colonne.addWidget(self.section_ia)
        colonne.addStretch()
        defilement = QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        defilement.setWidget(contenu)
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 16, 8)
        disposition.setSpacing(12)
        disposition.addWidget(entete)
        disposition.addWidget(self.confirmation)
        disposition.addWidget(defilement, 1)

        # Champs numériques à taille raisonnable (au lieu de s'étirer sur toute la largeur)
        for champ in contenu.findChildren(QAbstractSpinBox):
            champ.setMaximumWidth(min(champ.maximumWidth(), 220))
        self.recharger()

    LARGEUR_DEUX_COLONNES = 960

    def resizeEvent(self, evenement) -> None:
        super().resizeEvent(evenement)
        sens = (QBoxLayout.Direction.LeftToRight if self.width() >= self.LARGEUR_DEUX_COLONNES
                else QBoxLayout.Direction.TopToBottom)
        if self._grille.direction() != sens:
            self._grille.setDirection(sens)

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
        self.garanties.definir(p.plages_garanties)
        for n, case in enumerate(self.jours_libres.cases):
            case.setChecked(n in p.remplissage_jours)
        self.minutes_libres.setValue(p.remplissage_minutes)
        self.espace_libres.setValue(p.remplissage_espace)
        self.revisions.setValue(p.minutes_revision_semaine)
        self.repos_epreuve.setValue(p.repos_avant_epreuve_min)
        self.max_jour_epreuve.setValue(p.max_minutes_jour_epreuve)
        self.libre_apres.setChecked(p.libre_apres_epreuve)
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
            plages_garanties=self.garanties.valeurs(),
            remplissage_jours=self.jours_libres.jours(),
            remplissage_minutes=self.minutes_libres.value(),
            remplissage_espace=self.espace_libres.value(),
            marge_echeance_heures=self.marge.value(),
            horizon_semaines=self.horizon.value(),
            minutes_revision_semaine=self.revisions.value(),
            repos_avant_epreuve_min=self.repos_epreuve.value(),
            max_minutes_jour_epreuve=self.max_jour_epreuve.value(),
            libre_apres_epreuve=self.libre_apres.isChecked(),
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
        self.confirmation.setText("✓  Préférences enregistrées")
        self.confirmation.show()
        QTimer.singleShot(2500, self.confirmation.hide)
        self.preferences_enregistrees.emit()
        return True


class SectionRappels(QGroupBox):
    """Rappels et notifications (enregistrés tout de suite)."""

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__("Rappels et notifications", parent)
        self.base = base
        self.notificateur = None  # fourni par la fenêtre principale
        aide = QLabel(
            "Des notifications Windows, entièrement hors ligne. Pour les recevoir, l'application doit rester "
            "ouverte : en fermant la fenêtre, elle reste discrètement près de l'horloge (clic droit sur son icône "
            "pour la quitter)."
        )
        aide.setWordWrap(True)
        aide.setObjectName("doux")
        self.actif = QCheckBox("Activer les rappels")
        self.seance = QCheckBox("Avant chaque séance :")
        self.seance_minutes = champ_minutes(10, 120, minimum=5, pas=5)
        self.veille = QCheckBox("La veille d'une épreuve, à")
        self.heure_veille = champ_heure(time(19))
        self.travail = QCheckBox("Avant un travail à rendre :")
        self.travail_jours = _nombre(2, 1, 14, " jour(s) avant")
        self.heure_travail = champ_heure(time(18))
        self.bilan = QCheckBox("Point du soir (séances à pointer), à")
        self.heure_bilan = champ_heure(time(22, 30))
        self.arriere_plan = QCheckBox("Garder l'application près de l'horloge quand je ferme la fenêtre")
        self.demarrage = QCheckBox("Démarrer avec Windows (discrètement, pour ne manquer aucun rappel)")
        tester = QPushButton("Tester une notification")
        tester.clicked.connect(self.tester)
        self.message = QLabel()
        self.message.setObjectName("doux")
        self.message.setWordWrap(True)

        colonne = QVBoxLayout(self)
        colonne.addWidget(aide)
        colonne.addWidget(self.actif)
        f = QFormLayout()
        f.addRow(_avec_texte(self.seance, ""), _avec_texte(self.seance_minutes, ""))
        f.addRow(_avec_texte(self.veille, ""), _avec_texte(self.heure_veille, ""))
        ligne_travail = QHBoxLayout()
        ligne_travail.addWidget(self.travail_jours)
        ligne_travail.addWidget(QLabel("à"))
        ligne_travail.addWidget(self.heure_travail)
        ligne_travail.addStretch()
        f.addRow(_avec_texte(self.travail, ""), ligne_travail)
        f.addRow(_avec_texte(self.bilan, ""), _avec_texte(self.heure_bilan, ""))
        colonne.addLayout(f)
        colonne.addWidget(self.arriere_plan)
        colonne.addWidget(self.demarrage)
        ligne_test = QHBoxLayout()
        ligne_test.addWidget(tester)
        ligne_test.addWidget(self.message, 1)
        colonne.addLayout(ligne_test)

        self._chargement = False
        for case in (self.actif, self.seance, self.veille, self.travail, self.bilan, self.arriere_plan):
            case.toggled.connect(self.enregistrer)
        for champ in (self.seance_minutes, self.travail_jours):
            champ.valueChanged.connect(self.enregistrer)
        for champ in (self.heure_veille, self.heure_travail, self.heure_bilan):
            champ.timeChanged.connect(self.enregistrer)
        self.demarrage.toggled.connect(self._basculer_demarrage)
        self.rafraichir()

    def rafraichir(self) -> None:
        from ..rappels import charger
        from ..systeme import commande_demarrage, demarrage_actif

        self._chargement = True
        r = charger(self.base)
        self.actif.setChecked(r.actif)
        self.seance.setChecked(r.seance_minutes > 0)
        self.seance_minutes.setValue(r.seance_minutes or 10)
        self.veille.setChecked(r.veille_epreuve)
        self.heure_veille.setTime(vers_qtime(r.heure_veille))
        self.travail.setChecked(r.travail_jours > 0)
        self.travail_jours.setValue(r.travail_jours or 2)
        self.heure_travail.setTime(vers_qtime(r.heure_travail))
        self.bilan.setChecked(r.bilan_soir)
        self.heure_bilan.setTime(vers_qtime(r.heure_bilan))
        self.arriere_plan.setChecked(r.arriere_plan)
        self.demarrage.blockSignals(True)
        self.demarrage.setChecked(demarrage_actif())
        self.demarrage.blockSignals(False)
        possible = commande_demarrage() is not None
        self.demarrage.setEnabled(possible)
        self.demarrage.setToolTip("" if possible else "Disponible dans l'application installée")
        if self.notificateur is not None and not self.notificateur.disponible:
            self.message.setText("⚠ Les notifications Windows ne sont pas disponibles sur cet ordinateur.")
        self._actualiser()
        self._chargement = False

    def _actualiser(self) -> None:
        actif = self.actif.isChecked()
        for w in (self.seance, self.veille, self.travail, self.bilan, self.arriere_plan):
            w.setEnabled(actif)
        self.seance_minutes.setEnabled(actif and self.seance.isChecked())
        self.heure_veille.setEnabled(actif and self.veille.isChecked())
        self.travail_jours.setEnabled(actif and self.travail.isChecked())
        self.heure_travail.setEnabled(actif and self.travail.isChecked())
        self.heure_bilan.setEnabled(actif and self.bilan.isChecked())

    def lire(self):
        from ..rappels import ReglagesRappels

        return ReglagesRappels(
            actif=self.actif.isChecked(),
            seance_minutes=self.seance_minutes.value() if self.seance.isChecked() else 0,
            veille_epreuve=self.veille.isChecked(),
            heure_veille=depuis_qtime(self.heure_veille.time()),
            travail_jours=self.travail_jours.value() if self.travail.isChecked() else 0,
            heure_travail=depuis_qtime(self.heure_travail.time()),
            bilan_soir=self.bilan.isChecked(),
            heure_bilan=depuis_qtime(self.heure_bilan.time()),
            arriere_plan=self.arriere_plan.isChecked(),
        )

    def enregistrer(self, *_):
        from ..rappels import enregistrer

        self._actualiser()
        if self._chargement:
            return
        enregistrer(self.base, self.lire())
        self.message.setText("✓ Réglages des rappels enregistrés.")

    def _basculer_demarrage(self, actif: bool) -> None:
        from ..systeme import definir_demarrage

        try:
            obtenu = definir_demarrage(actif)
        except (RuntimeError, OSError) as erreur:
            self.message.setText(f"⚠ {erreur}")
            obtenu = False
        self.demarrage.blockSignals(True)
        self.demarrage.setChecked(obtenu)
        self.demarrage.blockSignals(False)
        if obtenu:
            self.message.setText("✓ Le planificateur démarrera avec Windows, discrètement près de l'horloge.")
        elif not actif:
            self.message.setText("Le planificateur ne démarrera plus avec Windows.")

    def tester(self) -> None:
        from ..rappels import Rappel

        if self.notificateur is None:
            return
        self.notificateur.notifier(Rappel("test", "Ceci est un test", "Les rappels du planificateur fonctionnent.", ""))
        self.message.setText("Notification envoyée : elle apparaît en bas à droite de l'écran."
                             if self.notificateur.disponible else "⚠ Notifications Windows indisponibles.")


class SectionAssistant(QGroupBox):
    """Clé Gemini, modèle, activation et test de connexion (enregistrés tout de suite)."""

    reglages_changes = Signal()

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__("Assistant IA (Gemini) — facultatif", parent)
        self.base = base
        self.client_test = None  # remplaçable dans les tests
        aide = QLabel(
            "L'assistant et l'import d'emploi du temps (image ou PDF) utilisent Gemini, avec votre propre clé. "
            "Quand vous vous en servez, seuls votre message, les données utiles du planificateur et le fichier "
            "joint sont envoyés à Google — rien d'autre de votre ordinateur. Sans clé, tout reste hors ligne. "
            "<a href=\"https://aistudio.google.com/apikey\">Obtenir une clé gratuite (Google AI Studio)</a>"
        )
        aide.setWordWrap(True)
        aide.setOpenExternalLinks(True)
        aide.setObjectName("doux")
        self.etat = QLabel()
        self.etat.setObjectName("pastille")
        self.champ_cle = QLineEdit()
        self.champ_cle.setEchoMode(QLineEdit.EchoMode.Password)
        self.champ_cle.setPlaceholderText("Collez votre clé API ici")
        enregistrer = bouton_role(QPushButton("Enregistrer la clé"), "primaire")
        enregistrer.clicked.connect(self.enregistrer_cle)
        effacer = bouton_role(QPushButton("Effacer la clé"), "danger")
        effacer.clicked.connect(self.effacer_cle)
        from ..ia.gemini import MODELES_PROPOSES

        self.choix_modele = QComboBox()
        self.choix_modele.setEditable(True)
        self.choix_modele.addItems(MODELES_PROPOSES)
        self.choix_modele.setToolTip("Choisissez un modèle proposé, ou tapez un autre nom de modèle Gemini")
        self.champ_modele = self.choix_modele.lineEdit()
        self.champ_modele.editingFinished.connect(lambda: cle_ia.definir_modele(self.base, self.champ_modele.text()))
        self.choix_modele.currentTextChanged.connect(lambda texte: cle_ia.definir_modele(self.base, texte))
        self.tester_bouton = QPushButton("Tester la connexion")
        self.tester_bouton.clicked.connect(self.tester)
        self.actif = QCheckBox("Activer l'assistant et l'import par IA")
        self.actif.toggled.connect(self._basculer)
        self.resultat = QLabel()
        self.resultat.setWordWrap(True)

        colonne_ia = QVBoxLayout(self)
        colonne_ia.addWidget(aide)
        f = QFormLayout()
        colonne_ia.addLayout(f)
        self.champ_cle.setMinimumWidth(160)
        self.choix_modele.setMinimumWidth(160)
        f.addRow("État", _avec_texte(self.etat, ""))
        ligne_cle = QHBoxLayout()
        for w in (self.champ_cle, enregistrer, effacer):
            ligne_cle.addWidget(w)
        f.addRow("Clé API", ligne_cle)
        ligne_modele = QHBoxLayout()
        ligne_modele.addWidget(self.choix_modele, 1)
        ligne_modele.addWidget(self.tester_bouton)
        f.addRow("Modèle", ligne_modele)
        f.addRow("", self.actif)
        f.addRow("", self.resultat)
        self.rafraichir()

    def rafraichir(self) -> None:
        presente = cle_ia.lire_cle(self.base) is not None
        self.etat.setText("Clé enregistrée (chiffrée)" if presente else "Aucune clé : assistant désactivé")
        self.choix_modele.blockSignals(True)
        self.choix_modele.setEditText(cle_ia.modele(self.base))
        self.choix_modele.blockSignals(False)
        self.actif.blockSignals(True)
        self.actif.setChecked(cle_ia.est_actif(self.base))
        self.actif.setEnabled(presente)
        self.actif.blockSignals(False)
        self.tester_bouton.setEnabled(presente)

    def _basculer(self, actif: bool) -> None:
        cle_ia.definir_actif(self.base, actif)
        self.reglages_changes.emit()

    def enregistrer_cle(self) -> bool:
        try:
            cle_ia.enregistrer_cle(self.base, self.champ_cle.text())
        except (ValueError, RuntimeError, OSError) as erreur:
            self.resultat.setText(f"⚠ {erreur}")
            return False
        self.champ_cle.clear()
        cle_ia.definir_actif(self.base, True)
        self.resultat.setText("Clé enregistrée. Vous pouvez tester la connexion.")
        self.rafraichir()
        self.reglages_changes.emit()
        return True

    def effacer_cle(self) -> None:
        cle_ia.effacer_cle(self.base)
        self.resultat.setText("Clé effacée : plus rien n'est envoyé à Gemini.")
        self.rafraichir()
        self.reglages_changes.emit()

    def tester(self) -> None:
        from ..ia.gemini import ClientGemini
        from .fond import en_fond

        cle_ia.definir_modele(self.base, self.champ_modele.text())
        cle = cle_ia.lire_cle(self.base)
        if not cle:
            self.resultat.setText("⚠ Enregistrez d'abord une clé.")
            return
        client = self.client_test or ClientGemini(cle, cle_ia.modele(self.base))
        self.tester_bouton.setEnabled(False)
        self.resultat.setText("Test en cours…")

        def reussi(texte):
            self.tester_bouton.setEnabled(True)
            if client.modele_utilise != client.modele:
                self.resultat.setText(f"✓ Connexion réussie. « {client.modele} » était surchargé : "
                                      f"« {client.modele_utilise} » a répondu à sa place (cela se fera automatiquement).")
            else:
                self.resultat.setText(f"✓ Connexion réussie avec « {client.modele} ».")

        def echoue(message):
            self.tester_bouton.setEnabled(True)
            self.resultat.setText(f"⚠ {message}")

        en_fond(client.tester, reussi, echoue)


def _avec_texte(champ: QWidget, texte: str) -> QWidget:
    conteneur = QWidget()
    disposition = QHBoxLayout(conteneur)
    disposition.setContentsMargins(0, 0, 0, 0)
    disposition.addWidget(champ)
    disposition.addWidget(QLabel(texte))
    disposition.addStretch()
    return conteneur
