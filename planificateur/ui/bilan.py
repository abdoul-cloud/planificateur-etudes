"""Écran Bilan : prévu, réalisé et manqué, par matière (cahier des charges, section 9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import modeles as m
from ..base import Base
from ..suivi import Bilan, bilan
from . import theme
from .accueil import _Liste, _Statistique, _texte_jour
from .calendrier import generer, lundi_de
from .commun import LIBELLES, texte_duree
from .theme import carte, en_tete

PERIODES = ["Cette semaine", "Semaine dernière", "4 dernières semaines"]


def bornes(periode: str, aujourd_hui: date) -> tuple[date, date]:
    lundi = lundi_de(aujourd_hui)
    if periode == "Semaine dernière":
        return lundi - timedelta(weeks=1), lundi - timedelta(days=1)
    if periode == "4 dernières semaines":
        return lundi - timedelta(weeks=3), lundi + timedelta(days=6)
    return lundi, lundi + timedelta(days=6)


class BarresMatieres(QWidget):
    """Une ligne par matière : barre du temps prévu, remplie du temps réalisé.

    La couleur de la matière ne sert qu'à la marque ; noms et valeurs restent
    dans la couleur du texte. Survoler une ligne affiche le détail.
    """

    HAUTEUR_LIGNE = 46
    LARGEUR_NOM = 150
    LARGEUR_VALEUR = 150

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.lignes: list[tuple[str, str, int, int, int]] = []  # nom, couleur, prévu, fait, manqué
        self._survol = -1

    def definir(self, lignes) -> None:
        self.lignes = lignes
        self.setMinimumHeight(max(1, len(lignes)) * self.HAUTEUR_LIGNE + 8)
        self.update()

    def _zone_barre(self, n: int) -> QRectF:
        y = n * self.HAUTEUR_LIGNE + self.HAUTEUR_LIGNE / 2 - 5
        largeur = max(40.0, self.width() - self.LARGEUR_NOM - self.LARGEUR_VALEUR - 16)
        return QRectF(self.LARGEUR_NOM, y, largeur, 10)

    def paintEvent(self, _evenement) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        police = QFont(self.font())
        mesure = QFontMetrics(police)
        if not self.lignes:
            p.setPen(QColor(theme.TEXTE_PALE))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Aucune séance sur cette période.")
            p.end()
            return
        maximum = max(prevu for _, _, prevu, _, _ in self.lignes) or 1
        for n, (nom, couleur, prevu, fait, manque) in enumerate(self.lignes):
            zone = self._zone_barre(n)
            centre = n * self.HAUTEUR_LIGNE + self.HAUTEUR_LIGNE / 2
            if n == self._survol:
                p.fillRect(QRectF(0, n * self.HAUTEUR_LIGNE + 2, self.width(), self.HAUTEUR_LIGNE - 4), QColor("#F6F7FB"))
            p.setPen(QColor(theme.TEXTE))
            p.setFont(police)
            p.drawText(QRectF(8, centre - 10, self.LARGEUR_NOM - 16, 20), Qt.AlignmentFlag.AlignVCenter,
                       mesure.elidedText(nom, Qt.TextElideMode.ElideRight, self.LARGEUR_NOM - 16))
            # Piste du prévu, puis le réalisé par-dessus (extrémités arrondies 4 px)
            largeur_prevu = zone.width() * prevu / maximum
            piste = QPainterPath()
            piste.addRoundedRect(QRectF(zone.left(), zone.top(), max(8.0, largeur_prevu), zone.height()), 4, 4)
            p.fillPath(piste, QColor("#E6E8F0"))
            if fait:
                largeur_fait = largeur_prevu * min(1.0, fait / prevu) if prevu else 0
                rempli = QPainterPath()
                rempli.addRoundedRect(QRectF(zone.left(), zone.top(), max(8.0, largeur_fait), zone.height()), 4, 4)
                p.fillPath(rempli, QColor(couleur))
            valeur = f"{texte_duree(fait)} / {texte_duree(prevu)}"
            p.setPen(QColor(theme.TEXTE_DOUX))
            p.drawText(QRectF(self.width() - self.LARGEUR_VALEUR, centre - 10, self.LARGEUR_VALEUR - 8, 20),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, valeur)
        p.end()

    def mouseMoveEvent(self, evenement) -> None:
        n = int(evenement.position().y() // self.HAUTEUR_LIGNE)
        n = n if 0 <= n < len(self.lignes) else -1
        if n != self._survol:
            self._survol = n
            self.update()
        if n >= 0:
            nom, _, prevu, fait, manque = self.lignes[n]
            taux = f" ({round(100 * fait / prevu)} %)" if prevu else ""
            self.setToolTip(f"{nom}\nRéalisé : {texte_duree(fait)} sur {texte_duree(prevu)} prévus{taux}"
                            + (f"\nManqué : {texte_duree(manque)}" if manque else ""))
        else:
            self.setToolTip("")

    def leaveEvent(self, _evenement) -> None:
        self._survol = -1
        self.update()


class PageBilan(QWidget):
    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.periode = PERIODES[0]
        self.maintenant: datetime | None = None  # pour les tests

        entete, actions = en_tete("Bilan", "Ce que vous avez réellement fait, comparé à ce qui était prévu.")
        groupe = QButtonGroup(self)
        self.boutons_periode = {}
        for nom in PERIODES:
            bouton = QPushButton(nom)
            bouton.setCheckable(True)
            bouton.setObjectName("segment")
            bouton.clicked.connect(lambda _=False, n=nom: self.choisir(n))
            groupe.addButton(bouton)
            bouton.setMinimumWidth(bouton.fontMetrics().horizontalAdvance(nom) + 44)
            actions.addWidget(bouton)
            self.boutons_periode[nom] = bouton
        self.boutons_periode[self.periode].setChecked(True)

        self.stat_prevu = _Statistique("planning", "Prévu")
        self.stat_fait = _Statistique("coche", "Réalisé")
        self.stat_taux = _Statistique("epreuves", "Taux de réalisation")
        self.stat_manque = _Statistique("annuler", "Manqué")
        ligne_stats = QHBoxLayout()
        ligne_stats.setSpacing(16)
        for s in (self.stat_prevu, self.stat_fait, self.stat_taux, self.stat_manque):
            ligne_stats.addWidget(s, 1)

        self.cadre_barres = carte()
        colonne = QVBoxLayout(self.cadre_barres)
        colonne.setContentsMargins(20, 16, 20, 16)
        titre = QLabel("Par matière")
        titre.setObjectName("titreCarte")
        legende = QLabel("Barre claire : temps prévu · partie colorée : temps réellement fait")
        legende.setObjectName("pale")
        self.barres = BarresMatieres()
        colonne.addWidget(titre)
        colonne.addWidget(legende)
        colonne.addWidget(self.barres)

        self.liste_reste = _Liste("Reste à placer", "Tout ce qui est prévu tient dans le temps disponible.")
        self.liste_manquees = _Liste("Séances manquées", "Aucune séance manquée sur cette période.")
        grille = QGridLayout()
        grille.setSpacing(16)
        grille.addWidget(self.liste_reste, 0, 0)
        grille.addWidget(self.liste_manquees, 0, 1)
        grille.setColumnStretch(0, 1)
        grille.setColumnStretch(1, 1)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(18)
        disposition.addWidget(entete)
        disposition.addLayout(ligne_stats)
        disposition.addWidget(self.cadre_barres)
        disposition.addLayout(grille)
        disposition.addStretch(1)
        self.rafraichir()

    def choisir(self, periode: str) -> None:
        self.periode = periode
        self.boutons_periode[periode].setChecked(True)
        self.rafraichir()

    def calculer(self) -> Bilan:
        maintenant = self.maintenant or datetime.now()
        du, au = bornes(self.periode, maintenant.date())
        return bilan(self.base, du, au, maintenant)

    def rafraichir(self) -> None:
        maintenant = self.maintenant or datetime.now()
        resultat = self.calculer()
        self.stat_prevu.definir(texte_duree(resultat.prevu), f"du {resultat.du:%d/%m} au {resultat.au:%d/%m}")
        self.stat_fait.definir(texte_duree(resultat.fait),
                               f"{texte_duree(resultat.non_pointe)} non pointées" if resultat.non_pointe else "tout est pointé")
        self.stat_taux.definir("—" if resultat.taux is None else f"{round(100 * resultat.taux)} %",
                               "des séances passées" if resultat.taux is not None else "rien à mesurer encore")
        self.stat_manque.definir(texte_duree(resultat.manque),
                                 f"{len(resultat.manquees)} séance{'s' if len(resultat.manquees) > 1 else ''}")

        matieres = {x.id: x for x in self.base.matieres.lister()}
        lignes = []
        for matiere_id, ligne in sorted(resultat.par_matiere.items(), key=lambda kv: -kv[1].prevu):
            matiere = matieres.get(matiere_id)
            lignes.append((matiere.nom if matiere else "Sans matière", matiere.couleur if matiere else theme.ACCENT,
                           ligne.prevu, ligne.fait, ligne.manque))
        self.barres.definir(lignes)

        # Ce qui ne tient pas, calculé à partir des données actuelles (sans rien enregistrer)
        reste = []
        for d in generer(self.base, maintenant).non_places:
            quand = f"échéance {_texte_jour(d.echeance.date())}" if d.echeance else "révisions régulières"
            reste.append((theme.DANGER if d.type is not m.TypeSeance.REVISION else theme.TEXTE_PALE,
                          d.intitule, quand + (" — dépassée" if d.en_retard else ""), texte_duree(d.minutes)))
        self.liste_reste.definir(reste[:6])

        manquees = []
        for s in resultat.manquees[-6:]:
            matiere = matieres.get(s.matiere_id)
            manquees.append((matiere.couleur if matiere else theme.ACCENT, f"{matiere.nom if matiere else 'Séance'} · {LIBELLES[s.type]}",
                             f"{_texte_jour(s.debut.date())}, {s.debut:%H:%M} – {s.fin:%H:%M}", texte_duree(s.minutes)))
        self.liste_manquees.definir(manquees)
