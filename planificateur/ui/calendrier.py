"""Calendrier hebdomadaire : affichage, glisser-déposer et page Planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import Intervalle, occurrences, periodes_occupees
from ..moteur.placement import Resultat, planifier
from ..suivi import marquer
from . import theme
from .commun import JOURS, LIBELLES, texte_duree
from .theme import bouton_role, carte, en_tete, icone, police_icones, vider

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
PAS_MIN = 15


def lundi_de(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


def texte_semaine(lundi: date, court: bool = False) -> str:
    dimanche = lundi + timedelta(days=6)
    if court:  # fenêtre étroite : « 16 – 22 nov. 2026 »
        def abr(n):
            return MOIS_COURTS[n - 1]
        if lundi.month == dimanche.month:
            return f"{lundi.day} – {dimanche.day} {abr(dimanche.month)} {dimanche.year}"
        return f"{lundi.day} {abr(lundi.month)} – {dimanche.day} {abr(dimanche.month)} {dimanche.year}"
    if lundi.month == dimanche.month:
        return f"{lundi.day} – {dimanche.day} {MOIS[dimanche.month - 1]} {dimanche.year}"
    return f"{lundi.day} {MOIS[lundi.month - 1]} – {dimanche.day} {MOIS[dimanche.month - 1]} {dimanche.year}"


def generer(base: Base, maintenant: datetime | None = None) -> Resultat:
    """Calcule le planning à partir de toutes les données enregistrées."""
    maintenant = maintenant or datetime.now().replace(second=0, microsecond=0)
    preferences = base.preferences()
    du = maintenant.date()
    au = m.fin_de_periode(du, preferences.horizon_semaines)  # jusqu'au dimanche, semaines du calendrier
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


def enregistrer_resultat(base: Base, resultat: Resultat) -> None:
    for s in resultat.retirees:
        base.seances.supprimer(s.id)
    for s in resultat.seances:
        base.seances.ajouter(s)


# --------------------------------------------------------------------------
# Widget calendrier
# --------------------------------------------------------------------------


@dataclass
class _Bloc:
    rect: QRectF
    seance: m.Seance


class CalendrierSemaine(QWidget):
    """Grille lundi → dimanche, heures en lignes.

    Les catégories se distinguent aussi sans les couleurs : hachures pour les
    activités fixes, drapeau et cadre pour les épreuves, libellé du type et
    style de bordure pour les séances, cadenas pour les séances verrouillées.
    """

    seance_deplacee = Signal(object, object, object)  # séance, nouveau début, nouvelle fin
    menu_seance = Signal(object, object)  # séance, position écran

    MARGE_HEURES = 56
    HAUT_ENTETE = 52
    PX_HEURE = 52

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lundi = lundi_de(date.today())
        self.preferences = m.Preferences()
        self.activites: list[tuple[m.ActiviteFixe, Intervalle]] = []
        self.epreuves: list[m.Epreuve] = []
        self.seances: list[m.Seance] = []
        self.matieres: dict[int, m.Matiere] = {}
        self.conflits: set[int] = set()
        self.heure_min, self.heure_max = 7, 23
        self._blocs: list[_Bloc] = []
        self._glisse: _Bloc | None = None
        self._decalage = QPointF()
        self._fantome: tuple[datetime, datetime] | None = None
        self.maintenant = None  # pour les tests ; sinon l'heure réelle
        self.impression = False  # rendu pour l'export : ni « aujourd'hui » ni heure actuelle

    # --- Données -------------------------------------------------------------

    def definir(self, lundi, preferences, activites, epreuves, seances, matieres, conflits=()) -> None:
        self.lundi = lundi
        self.preferences = preferences
        self.activites = activites
        self.epreuves = epreuves
        self.seances = seances
        self.matieres = {x.id: x for x in matieres}
        self.conflits = set(conflits)
        reglages = [preferences.jour(j) for j in range(7)]
        debuts = [r.debut.hour for r in reglages if r.travaille] or [7]
        fins = [r.fin.hour + (1 if r.fin.minute else 0) for r in reglages if r.travaille] or [23]
        debuts += [i.debut.hour for _, i in activites] + [e.debut.hour for e in epreuves] + [s.debut.hour for s in seances]
        fins += [i.fin.hour + (1 if i.fin.minute else 0) for _, i in activites if i.fin.date() == i.debut.date()]
        fins += [s.fin.hour + (1 if s.fin.minute else 0) for s in seances]
        self.heure_min = max(0, min(debuts))
        self.heure_max = min(24, max(max(fins), self.heure_min + 8))
        self.setMinimumHeight(self.HAUT_ENTETE + (self.heure_max - self.heure_min) * self.PX_HEURE + 8)
        self.update()

    # --- Géométrie -------------------------------------------------------------

    def _largeur_jour(self) -> float:
        return (self.width() - self.MARGE_HEURES - 8) / 7

    def _x(self, jour: int) -> float:
        return self.MARGE_HEURES + jour * self._largeur_jour()

    def _y(self, instant: time | datetime) -> float:
        t = instant.time() if isinstance(instant, datetime) else instant
        minutes = (t.hour - self.heure_min) * 60 + t.minute
        return self.HAUT_ENTETE + minutes * self.PX_HEURE / 60

    def _rect(self, debut: datetime, fin: datetime, retrait: float = 3) -> QRectF:
        jour = (debut.date() - self.lundi).days
        x = self._x(jour) + retrait
        y_fin = self._y(fin) if fin.date() == debut.date() else self._y(time(23, 59))
        return QRectF(x, self._y(debut) + 1, self._largeur_jour() - 2 * retrait, max(14, y_fin - self._y(debut) - 2))

    def _instant(self, point: QPointF) -> datetime | None:
        jour = int((point.x() - self.MARGE_HEURES) // self._largeur_jour())
        if not 0 <= jour <= 6:
            return None
        minutes = (point.y() - self.HAUT_ENTETE) * 60 / self.PX_HEURE + self.heure_min * 60
        minutes = round(minutes / PAS_MIN) * PAS_MIN
        minutes = max(self.heure_min * 60, min(minutes, self.heure_max * 60))
        return datetime.combine(self.lundi + timedelta(days=jour), time.min) + timedelta(minutes=minutes)

    def bloc_sous(self, point: QPointF) -> _Bloc | None:
        for bloc in reversed(self._blocs):
            if bloc.rect.contains(point):
                return bloc
        return None

    # --- Dessin --------------------------------------------------------------

    def paintEvent(self, _evenement) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        self._dessiner_grille(p)
        for activite, intervalle in self.activites:
            self._dessiner_activite(p, activite, intervalle)
        for epreuve in self.epreuves:
            self._dessiner_epreuve(p, epreuve)
        self._blocs = []
        for seance in self.seances:
            rect = self._rect(seance.debut, seance.fin)
            self._blocs.append(_Bloc(rect, seance))
            self._dessiner_seance(p, seance, rect, fantome=self._glisse is not None and self._glisse.seance is seance)
        if self._glisse and self._fantome:
            self._dessiner_seance(p, self._glisse.seance, self._rect(*self._fantome), deplacement=True)
        self._dessiner_maintenant(p)
        p.end()

    def _dessiner_grille(self, p: QPainter) -> None:
        largeur = self._largeur_jour()
        aujourd_hui = date.today()
        police = QFont(self.font())
        # Zones hors travail et pauses, jour par jour
        for j in range(7):
            jour = self.lundi + timedelta(days=j)
            reglage = self.preferences.jour(jour.weekday())
            x = self._x(j)
            haut, bas = self._y(time(self.heure_min)), self.HAUT_ENTETE + (self.heure_max - self.heure_min) * self.PX_HEURE
            if not reglage.travaille:
                p.fillRect(QRectF(x, haut, largeur, bas - haut), QColor("#F7F8FB"))
                continue
            if reglage.debut.hour > self.heure_min or reglage.debut.minute:
                p.fillRect(QRectF(x, haut, largeur, self._y(reglage.debut) - haut), QColor("#F7F8FB"))
            if self._y(reglage.fin) < bas:
                p.fillRect(QRectF(x, self._y(reglage.fin), largeur, bas - self._y(reglage.fin)), QColor("#F7F8FB"))
            for pause in reglage.pauses:
                rect = QRectF(x, self._y(pause.debut), largeur, self._y(pause.fin) - self._y(pause.debut))
                p.fillRect(rect, QColor("#FBFAF5"))
                if pause.nom and rect.height() >= 16:
                    police.setPointSizeF(7.5)
                    p.setFont(police)
                    p.setPen(QColor("#B8B39A"))
                    p.drawText(rect.adjusted(6, 2, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, pause.nom)

        # Lignes des heures
        police.setPointSizeF(8)
        p.setFont(police)
        for h in range(self.heure_min, self.heure_max + 1):
            y = self._y(time(h)) if h < 24 else self.HAUT_ENTETE + (24 - self.heure_min) * self.PX_HEURE
            p.setPen(QPen(QColor("#ECEEF4"), 1))
            p.drawLine(QPointF(self.MARGE_HEURES, y), QPointF(self.width() - 8, y))
            if h < self.heure_max:
                p.setPen(QPen(QColor("#F5F6FA"), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(self.MARGE_HEURES, y + self.PX_HEURE / 2), QPointF(self.width() - 8, y + self.PX_HEURE / 2))
            p.setPen(QColor(theme.TEXTE_PALE))
            p.drawText(QRectF(0, y - 8, self.MARGE_HEURES - 10, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{h:02d}:00")

        # Colonnes et en-têtes
        for j in range(8):
            x = self._x(j)
            p.setPen(QPen(QColor("#ECEEF4"), 1))
            p.drawLine(QPointF(x, self.HAUT_ENTETE - 6), QPointF(x, self.height()))
        for j in range(7):
            jour = self.lundi + timedelta(days=j)
            x = self._x(j)
            est_aujourd_hui = jour == aujourd_hui and not self.impression
            police.setPointSizeF(8)
            police.setBold(False)
            p.setFont(police)
            p.setPen(QColor(theme.ACCENT if est_aujourd_hui else theme.TEXTE_DOUX))
            p.drawText(QRectF(x, 6, largeur, 16), Qt.AlignmentFlag.AlignCenter, JOURS[j][:3].upper())
            centre = QPointF(x + largeur / 2, 34)
            if est_aujourd_hui:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT))
                p.drawEllipse(centre, 13, 13)
            police.setPointSizeF(11)
            police.setBold(True)
            p.setFont(police)
            p.setPen(QColor("#FFFFFF" if est_aujourd_hui else theme.TEXTE))
            p.drawText(QRectF(centre.x() - 20, centre.y() - 12, 40, 24), Qt.AlignmentFlag.AlignCenter, str(jour.day))
        p.setPen(QPen(QColor(theme.BORDURE), 1))
        p.drawLine(QPointF(self.MARGE_HEURES, self.HAUT_ENTETE), QPointF(self.width() - 8, self.HAUT_ENTETE))

    def _texte_bloc(self, p: QPainter, rect: QRectF, lignes: list[tuple[str, bool, str]]) -> None:
        """Écrit des lignes (texte, gras, couleur) en coupant ce qui dépasse."""
        y = rect.top() + 4
        for texte, gras, couleur in lignes:
            police = QFont(self.font())
            police.setPointSizeF(8.5 if gras else 8)
            police.setBold(gras)
            mesure = QFontMetrics(police)
            if y + mesure.height() > rect.bottom() + 2:
                break
            p.setFont(police)
            p.setPen(QColor(couleur))
            p.drawText(QPointF(rect.left() + 8, y + mesure.ascent()),
                       mesure.elidedText(texte, Qt.TextElideMode.ElideRight, int(rect.width() - 14)))
            y += mesure.height()

    def _dessiner_activite(self, p: QPainter, activite: m.ActiviteFixe, intervalle: Intervalle) -> None:
        rect = self._rect(intervalle.debut, intervalle.fin, retrait=2)
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, 6, 6)
        p.fillPath(chemin, QColor("#EEF0F5"))
        p.fillPath(chemin, QBrush(QColor("#E0E3EB"), Qt.BrushStyle.BDiagPattern))
        p.fillRect(QRectF(rect.left(), rect.top() + 3, 3, rect.height() - 6), QColor("#9AA1B5"))
        horaire = f"{intervalle.debut:%H:%M} – {intervalle.fin:%H:%M}"
        self._texte_bloc(p, rect, [(activite.nom, True, "#3F4557"), (f"{LIBELLES[activite.type]} · {horaire}", False, theme.TEXTE_DOUX)])

    def _dessiner_epreuve(self, p: QPainter, epreuve: m.Epreuve) -> None:
        if not 0 <= (epreuve.debut.date() - self.lundi).days <= 6:
            return
        rect = self._rect(epreuve.debut, epreuve.fin, retrait=2)
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, 6, 6)
        p.fillPath(chemin, QColor("#FFF0F3"))
        p.strokePath(chemin, QPen(QColor(theme.DANGER), 1.6))
        matiere = self.matieres.get(epreuve.matiere_id)
        titre = f"⚑ {LIBELLES[epreuve.type].upper()}"
        self._texte_bloc(p, rect, [
            (titre, True, theme.DANGER),
            (epreuve.intitule or (matiere.nom if matiere else ""), True, "#8A1C33"),
            (f"{epreuve.debut:%H:%M} – {epreuve.fin:%H:%M}", False, "#B4566B"),
        ])

    def _dessiner_seance(self, p: QPainter, s: m.Seance, rect: QRectF, fantome=False, deplacement=False) -> None:
        matiere = self.matieres.get(s.matiere_id)
        base = QColor(matiere.couleur if matiere else theme.ACCENT)
        fond = QColor(base)
        fond.setAlpha(40 if not deplacement else 90)
        terminee = s.statut in (m.StatutSeance.TERMINEE, m.StatutSeance.PARTIELLE)
        manquee = s.statut is m.StatutSeance.MANQUEE
        p.save()
        if fantome:
            p.setOpacity(0.35)
        elif manquee:
            p.setOpacity(0.45)
            base = QColor(theme.TEXTE_PALE)
            fond = QColor(theme.FOND)
        elif terminee:
            p.setOpacity(0.6)
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, 6, 6)
        p.fillPath(chemin, QColor(theme.SURFACE))
        p.fillPath(chemin, fond)
        # Bordure : pleine pour une préparation, pointillée pour un travail, aucune pour une révision
        conflit = s.id is not None and s.id in self.conflits
        if conflit:
            p.strokePath(chemin, QPen(QColor(theme.DANGER), 2))
        elif manquee:
            p.strokePath(chemin, QPen(base, 1.2, Qt.PenStyle.DotLine))
        elif s.type is m.TypeSeance.PREPARATION:
            p.strokePath(chemin, QPen(base, 1.4))
        elif s.type is m.TypeSeance.TRAVAIL:
            p.strokePath(chemin, QPen(base, 1.4, Qt.PenStyle.DashLine))
        p.fillRect(QRectF(rect.left(), rect.top() + 3, 4, rect.height() - 6), base)
        type_texte = LIBELLES[s.type] if s.type is not m.TypeSeance.TRAVAIL else "Travail"
        if s.statut is m.StatutSeance.TERMINEE:
            type_texte = "✓ " + type_texte
        elif s.statut is m.StatutSeance.PARTIELLE:
            type_texte = f"½ {type_texte} ({texte_duree(s.minutes_effectuees or 0)})"
        elif manquee:
            type_texte = "✗ Manquée"
        if conflit:
            type_texte = "⚠ " + type_texte
        couleur_texte = base.darker(170).name()
        self._texte_bloc(p, rect.adjusted(0, 0, -16 if s.verrouillee else 0, 0), [
            (matiere.nom if matiere else "Séance", True, couleur_texte),
            (f"{type_texte} · {s.debut:%H:%M}–{s.fin:%H:%M}", False, couleur_texte),
        ])
        if s.verrouillee:
            police = QFont(police_icones())
            police.setPixelSize(11)
            p.setFont(police)
            p.setPen(QColor(couleur_texte))
            p.drawText(QRectF(rect.right() - 18, rect.top() + 4, 14, 14), Qt.AlignmentFlag.AlignCenter, theme.ICONES["cadenas"])
        p.restore()

    def _dessiner_maintenant(self, p: QPainter) -> None:
        if self.impression:
            return
        maintenant = self.maintenant or datetime.now()
        jour = (maintenant.date() - self.lundi).days
        if not 0 <= jour <= 6 or not self.heure_min <= maintenant.hour < self.heure_max:
            return
        y = self._y(maintenant)
        x = self._x(jour)
        p.setPen(QPen(QColor(theme.DANGER), 1.5))
        p.drawLine(QPointF(x, y), QPointF(x + self._largeur_jour(), y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.DANGER))
        p.drawEllipse(QPointF(x, y), 4, 4)

    # --- Souris --------------------------------------------------------------

    def mousePressEvent(self, evenement) -> None:
        bloc = self.bloc_sous(evenement.position())
        if evenement.button() == Qt.MouseButton.LeftButton and bloc and bloc.seance.statut is m.StatutSeance.PREVUE:
            self._glisse = bloc
            self._decalage = evenement.position() - bloc.rect.topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, evenement) -> None:
        if self._glisse is None:
            bloc = self.bloc_sous(evenement.position())
            self.setCursor(Qt.CursorShape.OpenHandCursor if bloc else Qt.CursorShape.ArrowCursor)
            self.setToolTip(self._infobulle(bloc.seance) if bloc else "")
            return
        debut = self._instant(evenement.position() - self._decalage + QPointF(4, 0))
        if debut is None:
            return
        duree = self._glisse.seance.fin - self._glisse.seance.debut
        self._fantome = (debut, debut + duree)
        self.update()

    def mouseReleaseEvent(self, evenement) -> None:
        if self._glisse is None:
            return
        seance, fantome = self._glisse.seance, self._fantome
        self._glisse, self._fantome = None, None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        if fantome and fantome[0] != seance.debut:
            self.seance_deplacee.emit(seance, fantome[0], fantome[1])

    def contextMenuEvent(self, evenement) -> None:
        bloc = self.bloc_sous(QPointF(evenement.pos()))
        if bloc:
            self.menu_seance.emit(bloc.seance, evenement.globalPos())

    def _infobulle(self, s: m.Seance) -> str:
        matiere = self.matieres.get(s.matiere_id)
        lignes = [f"{LIBELLES[s.type]} — {matiere.nom if matiere else ''}",
                  f"{s.debut:%H:%M} – {s.fin:%H:%M} ({texte_duree(s.minutes)})"]
        statuts = {m.StatutSeance.TERMINEE: "Faite", m.StatutSeance.PARTIELLE: "Faite en partie",
                   m.StatutSeance.MANQUEE: "Manquée (replanifiée ailleurs)"}
        if s.statut in statuts:
            lignes.append(statuts[s.statut])
        if s.verrouillee:
            lignes.append("Verrouillée : le recalcul ne la déplacera pas")
        if s.id in self.conflits:
            lignes.append("⚠ En conflit avec une activité ou une épreuve")
        lignes.append("Glisser pour déplacer · clic droit pour plus d'options")
        return "\n".join(lignes)


# --------------------------------------------------------------------------
# Page Planning
# --------------------------------------------------------------------------


def _pastille(texte: str, danger: bool = False) -> QLabel:
    etiquette = QLabel(texte)
    etiquette.setObjectName("pastilleDanger" if danger else "pastille")
    return etiquette


class _Legende(QWidget):
    ELEMENTS = [
        ("Cours / fixe", "#EEF0F5", "#9AA1B5", "hachures"),
        ("Épreuve", "#FFF0F3", theme.DANGER, "cadre"),
        ("Préparation", "#E8EAFD", theme.ACCENT, "plein"),
        ("Travail à rendre", "#E8EAFD", theme.ACCENT, "pointille"),
        ("Révision", "#E8EAFD", theme.ACCENT, "aucun"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(22)

    def paintEvent(self, _evenement) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        police = QFont(self.font())
        police.setPointSizeF(8.5)
        p.setFont(police)
        mesure = QFontMetrics(police)
        x = 0.0
        for nom, fond, trait, style in self.ELEMENTS + [("Verrouillée", None, None, "cadenas")]:
            rect = QRectF(x, 4, 22, 14)
            if style == "cadenas":
                icone_police = QFont(police_icones())
                icone_police.setPixelSize(12)
                p.setFont(icone_police)
                p.setPen(QColor(theme.TEXTE_DOUX))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, theme.ICONES["cadenas"])
                p.setFont(police)
            else:
                chemin = QPainterPath()
                chemin.addRoundedRect(rect, 3, 3)
                p.fillPath(chemin, QColor(fond))
                if style == "hachures":
                    p.fillPath(chemin, QBrush(QColor("#D5D9E3"), Qt.BrushStyle.BDiagPattern))
                if style in ("cadre", "plein"):
                    p.strokePath(chemin, QPen(QColor(trait), 1.4))
                if style == "pointille":
                    p.strokePath(chemin, QPen(QColor(trait), 1.4, Qt.PenStyle.DashLine))
                p.fillRect(QRectF(rect.left(), rect.top() + 2, 3, rect.height() - 4), QColor(trait))
            p.setPen(QColor(theme.TEXTE_DOUX))
            p.drawText(QPointF(x + 28, 4 + 7 + mesure.ascent() / 2 - 1), nom)
            x += 28 + mesure.horizontalAdvance(nom) + 22
        p.end()


class PagePlanning(QWidget):
    donnees_modifiees = Signal()
    commencer = Signal(object)  # lancer le minuteur sur une séance
    LARGEUR_TITRE_LONG = 1000

    def resizeEvent(self, evenement) -> None:
        super().resizeEvent(evenement)
        if hasattr(self, "titre_semaine"):
            self.titre_semaine.setText(texte_semaine(self.lundi, court=self.width() < self.LARGEUR_TITRE_LONG))

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.lundi = lundi_de(date.today())
        self.dernier_resultat: Resultat | None = None
        self.avertir = QMessageBox.warning  # remplaçable dans les tests

        entete, actions = en_tete("Planning", "")
        self.titre_semaine = entete.findChild(QLabel, "titrePage")
        precedent = bouton_role(QPushButton(icone("precedent"), ""), "discret")
        suivant = bouton_role(QPushButton(icone("suivant"), ""), "discret")
        precedent.setToolTip("Semaine précédente")
        suivant.setToolTip("Semaine suivante")
        aujourd_hui = QPushButton("Aujourd'hui")
        self.bouton_generer = bouton_role(QPushButton(icone("generer", "#FFFFFF"), " Générer le planning"), "primaire")
        self.bouton_generer.setToolTip(
            "Recalcule les séances automatiques à venir.\n"
            "Les séances terminées, déplacées à la main ou verrouillées sont conservées."
        )
        precedent.clicked.connect(lambda: self.aller(-1))
        suivant.clicked.connect(lambda: self.aller(1))
        aujourd_hui.clicked.connect(self.aujourd_hui)
        self.bouton_generer.clicked.connect(self.generer)
        exporter = QPushButton(icone("imprimer"), " Exporter")
        menu_export = QMenu(exporter)
        menu_export.addAction("PDF A4 à imprimer…", self.choisir_export_pdf)
        menu_export.addAction("Image PNG…", self.choisir_export_png)
        menu_export.addSeparator()
        menu_export.addAction("Agenda (.ics) : Google Agenda, Outlook, téléphone…", self.choisir_export_ics)
        exporter.setMenu(menu_export)
        for w in (precedent, aujourd_hui, suivant):
            actions.addWidget(w)
        actions.addSpacing(12)
        actions.addWidget(exporter)
        actions.addWidget(self.bouton_generer)

        self.pastilles = QHBoxLayout()
        self.pastilles.setSpacing(8)
        ligne_infos = QHBoxLayout()
        ligne_infos.addLayout(self.pastilles)
        ligne_infos.addStretch()
        ligne_infos.addWidget(_Legende())

        self.alerte = carte(ombre=False)
        self.alerte.setObjectName("alerte")
        self.texte_alerte = QLabel()
        self.texte_alerte.setWordWrap(True)
        QVBoxLayout(self.alerte).addWidget(self.texte_alerte)
        self.alerte.hide()

        self.bandeau = carte(ombre=False)
        self.bandeau.setObjectName("bandeau")
        ligne_bandeau = QHBoxLayout(self.bandeau)
        ligne_bandeau.setContentsMargins(14, 8, 8, 8)
        texte_bandeau = QLabel("Vos données ont changé depuis le dernier calcul.")
        mettre_a_jour = bouton_role(QPushButton(icone("generer", "#FFFFFF"), " Mettre à jour le planning"), "primaire")
        mettre_a_jour.clicked.connect(self.generer)
        ligne_bandeau.addWidget(texte_bandeau, 1)
        ligne_bandeau.addWidget(mettre_a_jour)
        self.bandeau.hide()
        self.message = QLabel()
        self.message.setObjectName("pastille")
        self.message.hide()

        self.calendrier = CalendrierSemaine()
        self.calendrier.seance_deplacee.connect(self.deplacer)
        self.calendrier.menu_seance.connect(self.ouvrir_menu)
        cadre = carte()
        disposition_cadre = QVBoxLayout(cadre)
        disposition_cadre.setContentsMargins(6, 6, 6, 6)
        defilement = QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setWidget(self.calendrier)
        disposition_cadre.addWidget(defilement)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 16)
        disposition.setSpacing(12)
        disposition.addWidget(entete)
        disposition.addLayout(ligne_infos)
        disposition.addWidget(self.bandeau)
        disposition.addWidget(self.message, 0, Qt.AlignmentFlag.AlignLeft)
        disposition.addWidget(self.alerte)
        disposition.addWidget(cadre, 1)
        self.rafraichir()

    # --- Navigation ------------------------------------------------------------

    def aller(self, semaines: int) -> None:
        self.lundi += timedelta(weeks=semaines)
        self.rafraichir()

    def aujourd_hui(self) -> None:
        self.lundi = lundi_de(date.today())
        self.rafraichir()

    # --- Données ---------------------------------------------------------------

    def _donnees_semaine(self):
        dimanche = self.lundi + timedelta(days=6)
        debut, fin = datetime.combine(self.lundi, time.min), datetime.combine(dimanche + timedelta(days=1), time.min)
        activites = self.base.activites.lister()
        exceptions = self.base.exceptions.lister()
        epreuves = [e for e in self.base.epreuves.lister() if debut <= e.debut < fin]
        seances = self.base.seances.lister("debut >= ? AND debut < ?", (debut.isoformat(timespec="minutes"), fin.isoformat(timespec="minutes")), ordre="debut")
        seances = [s for s in seances if s.statut is not m.StatutSeance.REPORTEE]
        return activites, exceptions, epreuves, seances

    def conflits(self, activites, exceptions, epreuves, seances) -> set[int]:
        """Séances qui chevauchent une activité fixe ou une épreuve (après une modification)."""
        if not seances:
            return set()
        occupes = periodes_occupees(self.lundi, self.lundi + timedelta(days=6), activites, exceptions, epreuves)
        return {
            s.id for s in seances
            if s.statut is m.StatutSeance.PREVUE and any(Intervalle(s.debut, s.fin).chevauche(o) for o in occupes)
        }

    def rafraichir(self) -> None:
        activites, exceptions, epreuves, seances = self._donnees_semaine()
        dimanche = self.lundi + timedelta(days=6)
        conflits = self.conflits(activites, exceptions, epreuves, seances)
        self.titre_semaine.setText(texte_semaine(self.lundi, court=self.width() < self.LARGEUR_TITRE_LONG))
        self.calendrier.definir(
            self.lundi, self.base.preferences(), occurrences(activites, self.lundi, dimanche, exceptions),
            epreuves, seances, self.base.matieres.lister(), conflits,
        )

        vider(self.pastilles)
        actives = [s for s in seances if s.statut is not m.StatutSeance.MANQUEE]
        total = sum(s.minutes for s in actives)
        faites = [s for s in seances if s.statut in (m.StatutSeance.TERMINEE, m.StatutSeance.PARTIELLE)]
        self.pastilles.addWidget(_pastille(f"{len(actives)} séances"))
        self.pastilles.addWidget(_pastille(f"{texte_duree(total)} de travail"))
        if faites:
            self.pastilles.addWidget(_pastille(f"✓ {len(faites)} faite{'s' if len(faites) > 1 else ''}"))
        if epreuves:
            self.pastilles.addWidget(_pastille(f"{len(epreuves)} épreuve{'s' if len(epreuves) > 1 else ''}", danger=True))
        if conflits:
            self.pastilles.addWidget(_pastille(f"⚠ {len(conflits)} conflit{'s' if len(conflits) > 1 else ''}", danger=True))
        self._afficher_alerte()

    def _afficher_alerte(self) -> None:
        resultat = self.dernier_resultat
        manques = [d for d in resultat.non_places if d.type is not m.TypeSeance.REVISION] if resultat else []
        conflits = resultat.conflits if resultat else []
        if not manques and not conflits:
            self.alerte.hide()
            return
        lignes = []
        if manques:
            lignes.append("<b>Tout ne tient pas dans le temps disponible.</b> Il manque :")
            for d in manques:
                retard = " — <b>échéance dépassée</b>" if d.en_retard else ""
                lignes.append(f"• {d.intitule} : {texte_duree(d.minutes)}{retard}")
            lignes.append("Libérez du temps (préférences, jours particuliers) ou réduisez une estimation, puis régénérez.")
        if conflits:
            if lignes:
                lignes.append("")
            pluriel = len(conflits) > 1
            lignes.append(
                f"<b>{len(conflits)} séance{'s' if pluriel else ''} placée{'s' if pluriel else ''} à la main "
                f"chevauche{'nt' if pluriel else ''} maintenant un cours ou une épreuve.</b>"
            )
            for s in conflits[:5]:
                lignes.append(f"• {JOURS[s.debut.weekday()].lower()} {s.debut:%d/%m} {s.debut:%H:%M}–{s.fin:%H:%M} (marquée ⚠ dans le calendrier)")
            lignes.append("Déplacez-les ou supprimez-les : elles ne sont jamais modifiées sans vous.")
        self.texte_alerte.setText("<br>".join(lignes))
        self.alerte.show()

    # --- Actions -------------------------------------------------------------

    def generer(self, maintenant: datetime | None = None) -> Resultat:
        from ..suivi import relier_activites

        relier_activites(self.base)  # cours importés avant leur matière : la révision de la veille devient possible
        resultat = generer(self.base, maintenant if isinstance(maintenant, datetime) else None)
        enregistrer_resultat(self.base, resultat)
        self.dernier_resultat = resultat
        self.bandeau.hide()
        self.rafraichir()
        self.donnees_modifiees.emit()
        return resultat

    def deplacer(self, seance: m.Seance, debut: datetime, fin: datetime) -> bool:
        """Déplace une séance à la main ; refuse un chevauchement."""
        if fin.date() != debut.date():
            self.avertir(self, "Déplacement impossible", "Une séance doit tenir dans une seule journée.")
            self.rafraichir()
            return False
        activites, exceptions, epreuves, seances = self._donnees_semaine()
        occupes = periodes_occupees(debut.date(), debut.date(), activites, exceptions, self.base.epreuves.lister())
        occupes += [Intervalle(s.debut, s.fin) for s in seances
                    if s.id != seance.id and s.statut is not m.StatutSeance.MANQUEE]
        cible = Intervalle(debut, fin)
        if any(cible.chevauche(o) for o in occupes):
            self.avertir(self, "Créneau occupé", "Ce créneau chevauche un cours, une épreuve ou une autre séance.")
            self.rafraichir()
            return False
        nouvelle = replace(seance, debut=debut, fin=fin, origine=m.Origine.MANUELLE, verrouillee=True)
        self.base.seances.modifier(nouvelle)
        self.rafraichir()
        self.donnees_modifiees.emit()
        return True

    def ouvrir_menu(self, seance: m.Seance, position) -> None:
        menu = QMenu(self)
        actions = {}
        if seance.statut is m.StatutSeance.PREVUE and seance.debut.date() == date.today():
            actions[menu.addAction(icone("generer", theme.ACCENT), "Commencer maintenant (minuteur)")] = "commencer"
            menu.addSeparator()
        if seance.statut is not m.StatutSeance.TERMINEE:
            actions[menu.addAction(icone("coche", theme.SUCCES), "Faite")] = "faite"
        if seance.statut is not m.StatutSeance.PARTIELLE:
            actions[menu.addAction("½   Faite en partie…")] = "partielle"
        if seance.statut is not m.StatutSeance.MANQUEE:
            actions[menu.addAction(icone("annuler", theme.DANGER), "Manquée — replanifier")] = "manquee"
        if seance.statut is not m.StatutSeance.PREVUE:
            actions[menu.addAction("↺   Remettre à « prévue »")] = "prevue"
        menu.addSeparator()
        if seance.statut is m.StatutSeance.PREVUE:
            texte = "Déverrouiller" if seance.verrouillee else "Verrouiller (ne plus déplacer)"
            actions[menu.addAction(icone("cadenas"), texte)] = "verrou"
        actions[menu.addAction(icone("supprimer", theme.DANGER), "Supprimer la séance")] = "supprimer"
        choix = actions.get(menu.exec(position))
        if choix == "commencer":
            self.commencer.emit(seance)
        elif choix == "faite":
            self.pointer(seance, m.StatutSeance.TERMINEE)
        elif choix == "partielle":
            minutes, ok = QInputDialog.getInt(
                self, "Faite en partie", "Minutes réellement travaillées :",
                max(5, seance.minutes // 2), 5, max(5, seance.minutes - 5), 5,
            )
            if ok:
                self.pointer(seance, m.StatutSeance.PARTIELLE, minutes)
        elif choix == "manquee":
            self.pointer(seance, m.StatutSeance.MANQUEE)
        elif choix == "prevue":
            self.pointer(seance, m.StatutSeance.PREVUE)
        elif choix == "verrou":
            self.basculer_verrou(seance)
        elif choix == "supprimer":
            self.supprimer(seance)

    def pointer(self, seance: m.Seance, statut: m.StatutSeance, minutes: int | None = None) -> None:
        """Pointe une séance. Une séance manquée déclenche aussitôt la replanification."""
        try:
            marquer(self.base, seance, statut, minutes)
        except ValueError as erreur:
            self.avertir(self, "Saisie incorrecte", str(erreur))
            return
        if statut is m.StatutSeance.MANQUEE:
            resultat = self.generer()
            self.informer("Séance manquée : le planning a été recalculé"
                          + ("" if resultat.faisable else " — tout ne tient plus, voir l'alerte"))
            return
        self.rafraichir()
        self.donnees_modifiees.emit()

    def informer(self, texte: str) -> None:
        self.message.setText(f"✓  {texte}")
        self.message.show()
        QTimer.singleShot(4000, self.message.hide)

    def signaler_changement(self) -> None:
        """Les données ont changé ailleurs : proposer de recalculer."""
        self.bandeau.show()

    # --- Export ------------------------------------------------------------------

    def _chemin_export(self, extension: str, filtre: str) -> Path | None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        propose = str(Path(documents) / f"Planning-{self.lundi.isoformat()}.{extension}")
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter le planning de la semaine", propose, filtre)
        return Path(chemin).with_suffix(f".{extension}") if chemin else None

    def choisir_export_pdf(self) -> None:
        chemin = self._chemin_export("pdf", "Document PDF (*.pdf)")
        if chemin:
            self.exporter(chemin)

    def choisir_export_png(self) -> None:
        chemin = self._chemin_export("png", "Image PNG (*.png)")
        if chemin:
            self.exporter(chemin)

    def choisir_export_ics(self) -> None:
        dialogue = DialogueExportAgenda(self.base.matieres.lister(ordre="nom"), self,
                                        self.periodes_export())
        if dialogue.exec() != QDialog.DialogCode.Accepted:
            return
        self._options_agenda = dialogue.choix()
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        propose = str(Path(documents) / "Planning-revisions.ics")
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter vers un agenda", propose, "Agenda iCalendar (*.ics)")
        if chemin:
            self.exporter_agenda(Path(chemin).with_suffix(".ics"))

    def periodes_export(self) -> list[tuple[str, date, date]]:
        """Périodes proposées à l'export : semaine affichée (par défaut), cette semaine, toute la période planifiée."""
        aujourd_hui = date.today()
        fin_planifiee = m.fin_de_periode(aujourd_hui, self.base.preferences().horizon_semaines)
        periodes = [(f"Semaine affichée ({texte_semaine(self.lundi, court=True)})", self.lundi,
                     self.lundi + timedelta(days=6))]
        if self.lundi != lundi_de(aujourd_hui):
            periodes.append((f"Cette semaine ({texte_semaine(lundi_de(aujourd_hui), court=True)})", aujourd_hui,
                             m.fin_de_periode(aujourd_hui, 1)))
        periodes.append((f"Toute la période planifiée (jusqu'au {fin_planifiee:%d/%m})", aujourd_hui, fin_planifiee))
        return periodes

    def exporter_agenda(self, chemin: Path, **options) -> int | None:
        """Exporte la période choisie (par défaut : la semaine affichée dans le Planning)."""
        options = dict(options or getattr(self, "_options_agenda", {}))
        from ..export_ics import exporter_ics

        _, du, au = self.periodes_export()[0]
        du, au = options.pop("du", du), options.pop("au", au)
        try:
            nombre = exporter_ics(self.base, du, au, chemin, **options)
        except OSError as erreur:
            self.avertir(self, "Export impossible", str(erreur))
            return None
        self.informer(f"{nombre} événement{'s' if nombre > 1 else ''} exporté{'s' if nombre > 1 else ''} "
                      f"dans {chemin.name} : importez ce fichier dans votre agenda.")
        return nombre

    def exporter(self, chemin: Path, ouvrir: bool = True) -> Path | None:
        from .export import exporter_pdf, exporter_png

        try:
            if chemin.suffix.lower() == ".png":
                exporter_png(self.base, self.lundi, chemin)
            else:
                exporter_pdf(self.base, self.lundi, chemin)
        except OSError as erreur:
            self.avertir(self, "Export impossible", str(erreur))
            return None
        self.informer(f"Planning exporté : {chemin.name}")
        if ouvrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(chemin)))
        return chemin

    def basculer_verrou(self, seance: m.Seance) -> None:
        self.base.seances.modifier(replace(seance, verrouillee=not seance.verrouillee))
        self.rafraichir()

    def supprimer(self, seance: m.Seance) -> None:
        self.base.seances.supprimer(seance.id)
        self.rafraichir()
        self.donnees_modifiees.emit()


class DialogueExportAgenda(QDialog):
    """Choisir ce qui part dans l'agenda : matières, épreuves, rappels."""

    def __init__(self, matieres: list[m.Matiere], parent=None, periodes=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exporter vers un agenda")
        self.periode = QComboBox()
        for libelle, du, au in periodes or []:
            self.periode.addItem(libelle, (du, au))
        aide = QLabel("Choisissez ce qui doit apparaître dans votre agenda :")
        aide.setWordWrap(True)
        self.cases: dict[int, QCheckBox] = {}
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(22, 20, 22, 18)
        if periodes:
            ligne = QHBoxLayout()
            ligne.addWidget(QLabel("Période :"))
            ligne.addWidget(self.periode, 1)
            colonne.addLayout(ligne)
            colonne.addSpacing(6)
        colonne.addWidget(aide)
        for x in matieres:
            if x.terminee:
                continue
            case = QCheckBox(x.nom)
            case.setChecked(True)
            pastille = QPixmap(12, 12)
            pastille.fill(QColor(x.couleur))
            case.setIcon(QIcon(pastille))
            self.cases[x.id] = case
            colonne.addWidget(case)
        self.epreuves = QCheckBox("Inclure les épreuves (rappel 1 h avant)")
        self.epreuves.setChecked(True)
        self.alarmes = QCheckBox("Rappel 10 min avant chaque séance")
        self.alarmes.setChecked(True)
        colonne.addSpacing(6)
        colonne.addWidget(self.epreuves)
        colonne.addWidget(self.alarmes)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bouton_role(boutons.button(QDialogButtonBox.StandardButton.Ok), "primaire").setText("Exporter…")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        colonne.addWidget(boutons)

    def choix(self) -> dict:
        options = {"matieres_choisies": {i for i, case in self.cases.items() if case.isChecked()},
                   "avec_epreuves": self.epreuves.isChecked(), "avec_alarmes": self.alarmes.isChecked()}
        if self.periode.count():
            options["du"], options["au"] = self.periode.currentData()
        return options
