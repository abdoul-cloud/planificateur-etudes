"""Emploi du temps en grille : on le remplit directement à la souris.

- Cliquer-glisser sur un moment libre : ajoute un cours ou une activité.
- Glisser un bloc : le déplace (autre jour, autre heure).
- Tirer le bord bas d'un bloc : change sa durée.
- Cliquer sur un bloc : modifier, copier sur d'autres jours, annuler ce jour-là, supprimer.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import Intervalle, occurrences
from . import theme
from .calendrier import CalendrierSemaine, lundi_de, texte_semaine
from .commun import JOURS, LIBELLES, champ_heure, depuis_qtime
from .formulaires import Formulaire, FormulaireActivite, _ligne
from .pages import PageEmploiDuTemps
from .theme import bouton_role, carte, en_tete, icone

PAS = 15
SUGGESTIONS = [("Sport", m.TypeActivite.PERSONNEL), ("Repos", m.TypeActivite.PERSONNEL),
               ("Trajet", m.TypeActivite.DEPLACEMENT), ("Travail (job)", m.TypeActivite.AUTRE)]


# --------------------------------------------------------------------------
# Grille
# --------------------------------------------------------------------------


class GrilleEmploi(CalendrierSemaine):
    creation_demandee = Signal(object, object)  # début, fin
    activite_deplacee = Signal(object, object, object, object)  # activité, horaire d'origine, début, fin
    activite_cliquee = Signal(object, object, object)  # activité, horaire, position écran

    BORD = 7  # zone (px) du bord bas qui sert à changer la durée

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocs_activites: list[tuple[QRectF, m.ActiviteFixe, Intervalle]] = []
        self._mode: str | None = None
        self._ancre: datetime | None = None
        self._cible: tuple[QRectF, m.ActiviteFixe, Intervalle] | None = None
        self._decalage = QPointF()
        self._apercu: tuple[datetime, datetime] | None = None
        self._depart = QPointF()

    # --- Repères -------------------------------------------------------------

    def _minutes_a(self, y: float) -> int:
        minutes = (y - self.HAUT_ENTETE) * 60 / self.PX_HEURE + self.heure_min * 60
        minutes = round(minutes / PAS) * PAS
        return int(max(self.heure_min * 60, min(minutes, self.heure_max * 60)))

    def _jour_a(self, x: float) -> int | None:
        jour = int((x - self.MARGE_HEURES) // self._largeur_jour())
        return jour if 0 <= jour <= 6 else None

    def bloc_activite(self, point: QPointF):
        for bloc in reversed(self._blocs_activites):
            if bloc[0].contains(point):
                return bloc
        return None

    # --- Dessin --------------------------------------------------------------

    def _dessiner_activite(self, p: QPainter, activite: m.ActiviteFixe, intervalle: Intervalle) -> None:
        super()._dessiner_activite(p, activite, intervalle)
        rect = self._rect(intervalle.debut, intervalle.fin, retrait=2)
        self._blocs_activites.append((rect, activite, intervalle))
        if self._cible is not None and self._cible[1].id == activite.id and self._apercu:
            p.fillRect(rect, QColor(255, 255, 255, 150))  # l'original pâlit pendant le déplacement

    def paintEvent(self, evenement) -> None:
        self._blocs_activites = []
        super().paintEvent(evenement)
        if not self._apercu:
            return
        debut, fin = self._apercu
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._rect(debut, fin, retrait=2)
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, 6, 6)
        fond = QColor(theme.ACCENT)
        fond.setAlpha(45)
        p.fillPath(chemin, fond)
        p.strokePath(chemin, QPen(QColor(theme.ACCENT), 1.6, Qt.PenStyle.DashLine))
        police = QFont(self.font())
        police.setBold(True)
        police.setPointSizeF(9)
        p.setFont(police)
        p.setPen(QColor(theme.ACCENT_FONCE))
        texte = f"{debut:%H:%M} – {fin:%H:%M}"
        if self._mode == "selection":
            texte = f"+ {texte}"
        p.drawText(rect.adjusted(8, 4, -4, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, texte)
        p.end()

    # --- Souris --------------------------------------------------------------

    def mousePressEvent(self, evenement) -> None:
        if evenement.button() != Qt.MouseButton.LeftButton:
            return
        pos = evenement.position()
        self._depart = pos
        bloc = self.bloc_activite(pos)
        if bloc:
            self._cible = bloc
            self._mode = "duree" if pos.y() >= bloc[0].bottom() - self.BORD else "deplacement"
            self._decalage = pos - bloc[0].topLeft()
            return
        jour = self._jour_a(pos.x())
        if jour is None or pos.y() < self.HAUT_ENTETE:
            return
        self._mode = "selection"
        self._ancre = datetime.combine(self.lundi + timedelta(days=jour), time.min) + timedelta(minutes=self._minutes_a(pos.y()))
        self._apercu = (self._ancre, self._ancre + timedelta(minutes=PAS))
        self.update()

    def mouseMoveEvent(self, evenement) -> None:
        pos = evenement.position()
        if self._mode is None:
            bloc = self.bloc_activite(pos)
            if bloc and pos.y() >= bloc[0].bottom() - self.BORD:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif bloc:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.setToolTip(f"{bloc[1].nom} — glisser pour déplacer, cliquer pour les options")
            else:
                self.setCursor(Qt.CursorShape.CrossCursor if pos.y() > self.HAUT_ENTETE else Qt.CursorShape.ArrowCursor)
                self.setToolTip("")
            return
        if self._mode == "selection":
            jour = self._ancre.date()
            point = datetime.combine(jour, time.min) + timedelta(minutes=self._minutes_a(pos.y()))
            debut, fin = sorted((self._ancre, point))
            if fin - debut < timedelta(minutes=PAS):
                fin = debut + timedelta(minutes=PAS)
            self._apercu = (debut, fin)
        elif self._mode == "deplacement":
            rect, _, horaire = self._cible
            jour = self._jour_a(pos.x() - self._decalage.x() + rect.width() / 2)
            if jour is None:
                return
            duree = horaire.fin - horaire.debut
            minutes = self._minutes_a(pos.y() - self._decalage.y())
            debut = datetime.combine(self.lundi + timedelta(days=jour), time.min) + timedelta(minutes=minutes)
            if (debut + duree).date() != debut.date():
                return
            self._apercu = (debut, debut + duree)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._mode == "duree":
            _, _, horaire = self._cible
            fin = datetime.combine(horaire.debut.date(), time.min) + timedelta(minutes=self._minutes_a(pos.y()))
            fin = max(fin, horaire.debut + timedelta(minutes=PAS))
            self._apercu = (horaire.debut, fin)
        self.update()

    def mouseReleaseEvent(self, evenement) -> None:
        mode, apercu, cible = self._mode, self._apercu, self._cible
        self._mode, self._apercu, self._cible, self._ancre = None, None, None, None
        self.update()
        if mode == "selection" and apercu:
            debut, fin = apercu
            if fin - debut <= timedelta(minutes=PAS):  # simple clic : une heure par défaut
                fin = min(debut + timedelta(hours=1), datetime.combine(debut.date(), time(23, 59)))
            self.creation_demandee.emit(debut, fin)
        elif mode in ("deplacement", "duree") and cible:
            _, activite, horaire = cible
            bouge = (evenement.position() - self._depart).manhattanLength() > 4
            if apercu and bouge and (apercu[0], apercu[1]) != (horaire.debut, horaire.fin):
                self.activite_deplacee.emit(activite, horaire, apercu[0], apercu[1])
            else:
                self.activite_cliquee.emit(activite, horaire, evenement.globalPosition().toPoint())

    def contextMenuEvent(self, evenement) -> None:
        bloc = self.bloc_activite(QPointF(evenement.pos()))
        if bloc:
            self.activite_cliquee.emit(bloc[1], bloc[2], evenement.globalPos())


# --------------------------------------------------------------------------
# Saisie rapide
# --------------------------------------------------------------------------


class FormulaireRapide(Formulaire):
    """Ajout en quelques secondes : quoi, type, horaire, chaque semaine ou une fois."""

    def __init__(self, matieres: list[m.Matiere], debut: datetime, fin: datetime, parent=None) -> None:
        super().__init__("Ajouter à l'emploi du temps", parent)
        self.setMinimumWidth(420)
        self.matieres = matieres
        self.jour = debut.date()
        self.plus_d_options = False

        self.quoi = QComboBox()
        self.quoi.setEditable(True)
        self.quoi.lineEdit().setPlaceholderText("Matière, ou ex. Sport, Trajet…")
        for matiere in matieres:
            self.quoi.addItem(matiere.nom)
        for nom, _ in SUGGESTIONS:
            self.quoi.addItem(nom)
        self.quoi.setCurrentIndex(0 if matieres else -1)
        if not matieres:
            self.quoi.setEditText("")
        self.type = QComboBox()
        for membre in m.TypeActivite:
            self.type.addItem(LIBELLES[membre], membre)
        self.debut = champ_heure(debut.time())
        self.fin = champ_heure(fin.time())
        self.chaque_semaine = QRadioButton(f"Chaque {JOURS[self.jour.weekday()].lower()}")
        self.une_fois = QRadioButton(f"Seulement le {self.jour:%d/%m}")
        groupe = QButtonGroup(self)
        groupe.addButton(self.chaque_semaine)
        groupe.addButton(self.une_fois)
        self.chaque_semaine.setChecked(True)
        plus = bouton_role(QPushButton("Plus d'options (période, trajet)…"), "discret")
        plus.clicked.connect(self._plus)

        self.form.addRow("Quoi ?", self.quoi)
        self.form.addRow("Type", self.type)
        self.form.addRow(JOURS[self.jour.weekday()], _ligne("de", self.debut, "à", self.fin))
        self.form.addRow("Répétition", _ligne(self.chaque_semaine, self.une_fois))
        self.form.addRow("", plus)
        self.quoi.currentTextChanged.connect(self._deviner_type)
        self._deviner_type(self.quoi.currentText())
        self.quoi.setFocus()

    def _deviner_type(self, texte: str) -> None:
        texte = texte.strip().lower()
        if any(x.nom.lower() == texte for x in self.matieres):
            self.type.setCurrentIndex(self.type.findData(m.TypeActivite.COURS))
            return
        for nom, type_activite in SUGGESTIONS:
            if nom.lower() == texte:
                self.type.setCurrentIndex(self.type.findData(type_activite))

    def _plus(self) -> None:
        self.plus_d_options = True
        self._valider()

    def valeur(self) -> m.ActiviteFixe:
        nom = self.quoi.currentText().strip()
        if not nom:
            raise ValueError("Indiquez ce que c'est (une matière, « Sport »…).")
        debut, fin = depuis_qtime(self.debut.time()), depuis_qtime(self.fin.time())
        if fin <= debut:
            raise ValueError("L'activité doit finir après avoir commencé.")
        matiere = next((x for x in self.matieres if x.nom.lower() == nom.lower()), None)
        recurrente = self.chaque_semaine.isChecked()
        return m.ActiviteFixe(
            nom=nom,
            heure_debut=debut,
            heure_fin=fin,
            type=m.TypeActivite(self.type.currentData()),
            jour_semaine=self.jour.weekday() if recurrente else None,
            date=None if recurrente else self.jour,
            matiere_id=matiere.id if matiere else None,
        )


class DialogueJours(QDialog):
    """Choix des autres jours où copier une activité hebdomadaire."""

    def __init__(self, activite: m.ActiviteFixe, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Copier sur d'autres jours")
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(22, 20, 22, 18)
        disposition.addWidget(QLabel(f"« {activite.nom} », {activite.heure_debut:%H:%M} – {activite.heure_fin:%H:%M}, aussi le :"))
        self.cases = []
        ligne = QHBoxLayout()
        for n, nom in enumerate(JOURS):
            case = QCheckBox(nom[:3])
            case.setToolTip(nom)
            if n == activite.jour_semaine:
                case.setChecked(True)
                case.setEnabled(False)
            self.cases.append(case)
            ligne.addWidget(case)
        disposition.addLayout(ligne)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bouton_role(boutons.button(QDialogButtonBox.StandardButton.Ok), "primaire").setText("Copier")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)
        self.activite = activite

    def jours(self) -> list[int]:
        return [n for n, c in enumerate(self.cases) if c.isChecked() and c.isEnabled()]


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


class PageEmploi(QWidget):
    donnees_modifiees = Signal()
    LARGEUR_LARGE = 1000

    def resizeEvent(self, evenement) -> None:
        super().resizeEvent(evenement)
        if hasattr(self, "bouton_import"):
            large = self.width() >= self.LARGEUR_LARGE
            self.bouton_import.setText(" Importer une image ou un PDF…" if large else " Importer…")
            self.titre_semaine.setText(f"Semaine du {texte_semaine(self.lundi, court=not large)}")

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.lundi = lundi_de(date.today())
        self.avertir = QMessageBox.warning
        self.confirmer = lambda titre, texte: QMessageBox.question(self, titre, texte) == QMessageBox.StandardButton.Yes
        # Import par IA : remplaçables dans les tests
        self.client_ia = None
        self.choisir_fichier = self._choisir_fichier
        self.ouvrir_dialogue = lambda dialogue: dialogue.exec()

        entete, actions = en_tete(
            "Emploi du temps",
            "Cliquez-glissez sur la grille pour ajouter un cours ou une activité. Glissez un bloc pour le "
            "déplacer, tirez son bord bas pour changer sa durée, cliquez dessus pour le modifier.",
        )
        self.boutons_vue = {}
        groupe = QButtonGroup(self)
        for nom in ("Grille", "Liste"):
            bouton = QPushButton(nom)
            bouton.setCheckable(True)
            bouton.setObjectName("segment")
            bouton.setMinimumWidth(bouton.fontMetrics().horizontalAdvance(nom) + 40)
            bouton.clicked.connect(lambda _=False, n=nom: self.vue(n))
            groupe.addButton(bouton)
            actions.addWidget(bouton)
            self.boutons_vue[nom] = bouton

        self.precedent = bouton_role(QPushButton(icone("precedent"), ""), "discret")
        self.suivant = bouton_role(QPushButton(icone("suivant"), ""), "discret")
        self.cette_semaine = QPushButton("Cette semaine")
        self.precedent.clicked.connect(lambda: self.aller(-1))
        self.suivant.clicked.connect(lambda: self.aller(1))
        self.cette_semaine.clicked.connect(self.aujourd_hui)
        self.titre_semaine = QLabel()
        self.titre_semaine.setObjectName("pastille")
        self.message = QLabel()
        self.message.setObjectName("pastille")
        self.message.hide()
        navigation = QHBoxLayout()
        for w in (self.precedent, self.cette_semaine, self.suivant, self.titre_semaine, self.message):
            navigation.addWidget(w)
        navigation.addStretch()
        self.bouton_import = QPushButton(icone("importer"), " Importer une image ou un PDF…")
        self.bouton_import.setToolTip("Gemini lit votre emploi du temps ; vous vérifiez avant tout ajout")
        self.bouton_import.clicked.connect(self.importer)
        navigation.addWidget(self.bouton_import)

        self.grille = GrilleEmploi()
        self.grille.creation_demandee.connect(self.demander_creation)
        self.grille.activite_deplacee.connect(self.changer_horaire)
        self.grille.activite_cliquee.connect(self.ouvrir_menu)
        cadre = carte()
        disposition_cadre = QVBoxLayout(cadre)
        disposition_cadre.setContentsMargins(6, 6, 6, 6)
        defilement = QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setWidget(self.grille)
        disposition_cadre.addWidget(defilement)
        self.cadre_grille = QWidget()
        disposition_grille = QVBoxLayout(self.cadre_grille)
        disposition_grille.setContentsMargins(0, 0, 0, 0)
        disposition_grille.setSpacing(10)
        disposition_grille.addLayout(navigation)
        disposition_grille.addWidget(cadre, 1)

        # Vue liste : l'ancien écran, sans son titre (déjà affiché ici)
        self.liste = PageEmploiDuTemps(base)
        for nom in ("titrePage", "sousTitre"):
            libelle = self.liste.findChild(QLabel, nom)
            if libelle is not None:
                libelle.hide()
        self.liste.layout().setContentsMargins(0, 0, 0, 0)
        self.liste.donnees_modifiees.connect(self._modifie_depuis_liste)

        self.pile = QStackedWidget()
        self.pile.addWidget(self.cadre_grille)
        self.pile.addWidget(self.liste)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 16)
        disposition.setSpacing(12)
        disposition.addWidget(entete)
        disposition.addWidget(self.pile, 1)
        self.vue("Grille")
        self.rafraichir()

    # --- Navigation ------------------------------------------------------------

    def vue(self, nom: str) -> None:
        self.boutons_vue[nom].setChecked(True)
        self.pile.setCurrentWidget(self.cadre_grille if nom == "Grille" else self.liste)

    def aller(self, semaines: int) -> None:
        self.lundi += timedelta(weeks=semaines)
        self.rafraichir()

    def aujourd_hui(self) -> None:
        self.lundi = lundi_de(date.today())
        self.rafraichir()

    def rafraichir(self) -> None:
        dimanche = self.lundi + timedelta(days=6)
        activites = self.base.activites.lister()
        exceptions = self.base.exceptions.lister()
        debut = datetime.combine(self.lundi, time.min)
        epreuves = [e for e in self.base.epreuves.lister() if debut <= e.debut < debut + timedelta(days=7)]
        self.titre_semaine.setText(f"Semaine du {texte_semaine(self.lundi, court=self.width() < self.LARGEUR_LARGE)}")
        self.grille.definir(self.lundi, self.base.preferences(), occurrences(activites, self.lundi, dimanche, exceptions),
                            epreuves, [], self.base.matieres.lister())
        self.liste.rafraichir()

    # --- Import par IA ------------------------------------------------------------

    def _choisir_fichier(self) -> str:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QFileDialog

        dossier = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Choisir l'emploi du temps", dossier, "Emploi du temps (*.pdf *.png *.jpg *.jpeg *.webp)"
        )
        return chemin

    def importer(self) -> None:
        from pathlib import Path

        from ..ia import cle as cle_ia
        from ..ia.gemini import ClientGemini
        from ..ia.import_edt import extraire
        from .fond import en_fond

        if self.client_ia is None and not cle_ia.est_actif(self.base):
            self.avertir(self, "Assistant IA non activé",
                         "Ajoutez votre clé Gemini dans Préférences > Assistant IA, puis réessayez.")
            return
        chemin = self.choisir_fichier()
        if not chemin:
            return
        client = self.client_ia or ClientGemini(cle_ia.lire_cle(self.base), cle_ia.modele(self.base))
        matieres = self.base.matieres.lister(ordre="nom")
        self.bouton_import.setEnabled(False)
        self.message.setText("⏳  Gemini lit votre emploi du temps…")
        self.message.show()
        en_fond(lambda: extraire(client, Path(chemin), matieres, date.today()), self._import_recu, self._import_echoue)

    def _import_echoue(self, message: str) -> None:
        self.bouton_import.setEnabled(True)
        self.message.hide()
        self.avertir(self, "Import impossible", message)

    def _import_recu(self, propositions) -> None:
        from .import_dialogue import DialogueImport

        self.bouton_import.setEnabled(True)
        self.message.hide()
        dialogue = DialogueImport(propositions, self.base.matieres.lister(ordre="nom"), self)
        if self.ouvrir_dialogue(dialogue):
            self.ajouter_import(dialogue.resultat or dialogue.valeurs())

    def ajouter_import(self, activites: list[m.ActiviteFixe]) -> tuple[int, list[str]]:
        ajoutes, refus = 0, []
        for activite in activites:
            conflit = self._chevauchement(activite)
            if conflit:
                refus.append(f"{activite.nom} ({conflit})")
                continue
            self.base.activites.ajouter(activite)
            ajoutes += 1
        if refus:
            self.avertir(self, "Quelques cours non ajoutés",
                         "Ces cours chevauchent une activité déjà présente :\n• " + "\n• ".join(refus))
        if ajoutes:
            self.informer(f"{ajoutes} cours ajouté{'s' if ajoutes > 1 else ''} depuis le document")
            self._modifie()
        return ajoutes, refus

    def informer(self, texte: str) -> None:
        self.message.setText(f"✓  {texte}")
        self.message.show()
        QTimer.singleShot(3500, self.message.hide)

    def _modifie(self) -> None:
        self.rafraichir()
        self.donnees_modifiees.emit()

    def _modifie_depuis_liste(self) -> None:
        self.rafraichir()
        self.donnees_modifiees.emit()

    # --- Règles -------------------------------------------------------------

    def _chevauchement(self, activite: m.ActiviteFixe, ignorer_id: int | None = None) -> str | None:
        """Nom d'une activité existante qui chevaucherait `activite`, sinon None."""
        autres = [a for a in self.base.activites.lister() if a.id != ignorer_id]
        exceptions = self.base.exceptions.lister()
        debut = self.lundi if activite.recurrente else activite.date
        fin = debut + timedelta(days=6 if activite.recurrente else 0)
        miennes = [i for _, i in occurrences([activite], debut, fin, exceptions)]
        for autre, horaire in occurrences(autres, debut, fin, exceptions):
            if any(horaire.chevauche(i) for i in miennes):
                return autre.nom
        return None

    # --- Actions -------------------------------------------------------------

    def demander_creation(self, debut: datetime, fin: datetime) -> None:
        formulaire = FormulaireRapide(self.base.matieres.lister(ordre="nom"), debut, fin, self)
        if not formulaire.exec():
            return
        activite = formulaire.resultat
        if formulaire.plus_d_options:
            complet = FormulaireActivite(self.base.matieres.lister(ordre="nom"), activite, self)
            if not complet.exec():
                return
            activite = complet.resultat
        self.creer(activite)

    def creer(self, activite: m.ActiviteFixe) -> bool:
        conflit = self._chevauchement(activite)
        if conflit:
            self.avertir(self, "Moment déjà occupé", f"Ce moment chevauche « {conflit} ».")
            return False
        self.base.activites.ajouter(activite)
        self.informer(f"« {activite.nom} » ajouté" + (" chaque semaine" if activite.recurrente else ""))
        self._modifie()
        return True

    def changer_horaire(self, activite: m.ActiviteFixe, horaire: Intervalle, debut: datetime, fin: datetime) -> bool:
        if fin.date() != debut.date() or fin <= debut:
            self.avertir(self, "Horaire impossible", "Une activité doit tenir dans une seule journée.")
            self.rafraichir()
            return False
        if activite.recurrente:
            nouvelle = replace(activite, jour_semaine=debut.weekday(), heure_debut=debut.time(), heure_fin=fin.time())
        else:
            nouvelle = replace(activite, date=debut.date(), heure_debut=debut.time(), heure_fin=fin.time())
        conflit = self._chevauchement(nouvelle, ignorer_id=activite.id)
        if conflit:
            self.avertir(self, "Moment déjà occupé", f"Ce moment chevauche « {conflit} ».")
            self.rafraichir()
            return False
        self.base.activites.modifier(nouvelle)
        self.informer("Modifié pour toutes les semaines" if activite.recurrente else "Modifié")
        self._modifie()
        return True

    def ouvrir_menu(self, activite: m.ActiviteFixe, horaire: Intervalle, position) -> None:
        menu = QMenu(self)
        modifier = menu.addAction(icone("modifier"), "Modifier…")
        copier = annuler = None
        if activite.recurrente:
            copier = menu.addAction("Copier sur d'autres jours…")
            annuler = menu.addAction(icone("annuler"), f"Annuler seulement le {horaire.debut:%d/%m}")
        menu.addSeparator()
        texte = "Supprimer (toutes les semaines)" if activite.recurrente else "Supprimer"
        supprimer = menu.addAction(icone("supprimer", theme.DANGER), texte)
        choix = menu.exec(position)
        if choix is modifier:
            formulaire = FormulaireActivite(self.base.matieres.lister(ordre="nom"), activite, self)
            if formulaire.exec():
                self.base.activites.modifier(formulaire.resultat)
                self._modifie()
        elif copier is not None and choix is copier:
            dialogue = DialogueJours(activite, self)
            if dialogue.exec():
                self.copier(activite, dialogue.jours())
        elif annuler is not None and choix is annuler:
            self.annuler_occurrence(activite, horaire.debut.date())
        elif choix is supprimer:
            if self.confirmer("Supprimer ?", f"Supprimer « {activite.nom} »"
                              + (" de toutes les semaines ?" if activite.recurrente else " ?")):
                self.supprimer(activite)

    def copier(self, activite: m.ActiviteFixe, jours: list[int]) -> int:
        copies, refus = 0, []
        for jour in jours:
            copie = replace(activite, jour_semaine=jour, id=None)
            if self._chevauchement(copie):
                refus.append(JOURS[jour].lower())
                continue
            self.base.activites.ajouter(copie)
            copies += 1
        if refus:
            self.avertir(self, "Copie partielle", "Déjà occupé le " + ", ".join(refus) + " : rien n'a été ajouté ces jours-là.")
        if copies:
            self.informer(f"Copié sur {copies} jour{'s' if copies > 1 else ''}")
            self._modifie()
        return copies

    def annuler_occurrence(self, activite: m.ActiviteFixe, jour: date) -> None:
        import sqlite3

        try:
            self.base.exceptions.ajouter(m.ExceptionActivite(activite.id, jour))
        except sqlite3.IntegrityError:
            return
        self.informer(f"« {activite.nom} » n'aura pas lieu le {jour:%d/%m}")
        self._modifie()

    def supprimer(self, activite: m.ActiviteFixe) -> None:
        self.base.activites.supprimer(activite.id)
        self._modifie()
