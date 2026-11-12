"""Export du planning d'une semaine : PDF A4 paysage (vectoriel) et image PNG."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPoint, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import occurrences
from . import theme
from .calendrier import CalendrierSemaine, _Legende, texte_semaine
from .commun import JOURS, LIBELLES, texte_duree

LARGEUR_LOGIQUE = 1500  # largeur de référence du calendrier avant mise à l'échelle


def _donnees(base: Base, lundi: date):
    debut = datetime.combine(lundi, time.min)
    fin = debut + timedelta(days=7)
    activites = base.activites.lister()
    exceptions = base.exceptions.lister()
    epreuves = [e for e in base.epreuves.lister(ordre="debut") if debut <= e.debut < fin]
    seances = [
        s for s in base.seances.lister(
            "debut >= ? AND debut < ?", (debut.isoformat(timespec="minutes"), fin.isoformat(timespec="minutes")),
            ordre="debut",
        )
        if s.statut not in (m.StatutSeance.MANQUEE, m.StatutSeance.REPORTEE)
    ]
    travaux = [t for t in base.travaux.lister(ordre="echeance")
               if debut <= t.echeance < fin and t.etat is not m.EtatTravail.RENDU]
    return activites, exceptions, epreuves, seances, travaux


def dessiner_planning(p: QPainter, largeur: float, hauteur: float, base: Base, lundi: date,
                      genere_le: datetime | None = None) -> None:
    """Dessine une page complète (en-tête, calendrier, légende, échéances) dans le rectangle donné."""
    activites, exceptions, epreuves, seances, travaux = _donnees(base, lundi)
    matieres = {x.id: x for x in base.matieres.lister()}
    unite = largeur / 1000  # toutes les mesures en millièmes de la largeur
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # En-tête
    titre = QFont("Segoe UI Variable Display")
    titre.setPixelSize(int(26 * unite))
    titre.setBold(True)
    p.setFont(titre)
    p.setPen(QColor(theme.TEXTE))
    hauteur_titre = 34 * unite
    p.drawText(QRectF(0, 0, largeur * 0.7, hauteur_titre), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               f"Planning — {texte_semaine(lundi)}")
    petit = QFont("Segoe UI")
    petit.setPixelSize(int(11 * unite))
    p.setFont(petit)
    p.setPen(QColor(theme.TEXTE_DOUX))
    p.drawText(QRectF(largeur * 0.6, 0, largeur * 0.4, hauteur_titre),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
               f"Généré le {(genere_le or datetime.now()):%d/%m/%Y à %H:%M}")
    total = sum(s.minutes for s in seances)
    resume = f"{len(seances)} séances · {texte_duree(total)} de travail personnel"
    if epreuves:
        resume += f" · {len(epreuves)} épreuve{'s' if len(epreuves) > 1 else ''}"
    p.drawText(QRectF(0, hauteur_titre, largeur, 18 * unite), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, resume)
    y = hauteur_titre + 24 * unite

    # Échéances de la semaine, en bas de page
    lignes_echeances = []
    for e in epreuves:
        nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else ""
        jour = JOURS[e.debut.weekday()].lower()
        lignes_echeances.append(f"⚑ {LIBELLES[e.type]} de {nom} — {jour} {e.debut:%d/%m}, {e.debut:%H:%M}–{e.fin:%H:%M}")
    for t in travaux:
        jour = JOURS[t.echeance.weekday()].lower()
        lignes_echeances.append(f"□ {t.intitule} — à rendre {jour} {t.echeance:%d/%m} à {t.echeance:%H:%M}")
    hauteur_bas = 26 * unite + (14 * unite * min(4, len(lignes_echeances)) if lignes_echeances else 0)

    # Calendrier, mis à l'échelle pour remplir la place restante
    calendrier = CalendrierSemaine()
    calendrier.impression = True
    calendrier.definir(lundi, base.preferences(), occurrences(activites, lundi, lundi + timedelta(days=6), exceptions),
                       epreuves, seances, list(matieres.values()))
    hauteur_logique = calendrier.minimumHeight()
    calendrier.resize(LARGEUR_LOGIQUE, hauteur_logique)
    place = QRectF(0, y, largeur, hauteur - y - hauteur_bas)
    echelle = min(place.width() / LARGEUR_LOGIQUE, place.height() / hauteur_logique)
    p.save()
    p.translate(place.left() + (place.width() - LARGEUR_LOGIQUE * echelle) / 2, place.top())
    p.scale(echelle, echelle)
    calendrier.render(p, QPoint(0, 0))
    p.restore()
    p.setPen(QPen(QColor(theme.BORDURE), max(1.0, unite)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(place.left() + (place.width() - LARGEUR_LOGIQUE * echelle) / 2, place.top(),
                      LARGEUR_LOGIQUE * echelle, hauteur_logique * echelle))

    # Légende (formes et bordures : lisible aussi en noir et blanc)
    y_bas = place.top() + hauteur_logique * echelle + 8 * unite
    legende = _Legende()
    legende.resize(900, 24)
    p.save()
    p.translate(0, y_bas)
    p.scale(unite * 0.9, unite * 0.9)
    legende.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.restore()
    if lignes_echeances:
        p.setFont(petit)
        p.setPen(QColor(theme.TEXTE))
        for n, ligne in enumerate(lignes_echeances[:4]):
            p.drawText(QRectF(0, y_bas + 24 * unite + n * 14 * unite, largeur, 14 * unite),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ligne)


def exporter_pdf(base: Base, lundi: date, chemin: Path | str, genere_le: datetime | None = None) -> Path:
    """PDF A4 paysage, marges de 10 mm, une page par semaine (vectoriel, net à l'impression)."""
    chemin = Path(chemin)
    ecrivain = QPdfWriter(str(chemin))
    ecrivain.setResolution(300)
    ecrivain.setTitle(f"Planning — {texte_semaine(lundi)}")
    ecrivain.setCreator("Planificateur d'études")
    ecrivain.setPageLayout(QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
        QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter,
    ))
    peintre = QPainter(ecrivain)
    try:
        dessiner_planning(peintre, ecrivain.width(), ecrivain.height(), base, lundi, genere_le)
    finally:
        peintre.end()
    return chemin


def exporter_png(base: Base, lundi: date, chemin: Path | str, dpi: int = 200,
                 genere_le: datetime | None = None) -> Path:
    """Image A4 paysage sur fond blanc (pour l'écran ou un partage rapide)."""
    chemin = Path(chemin)
    taille = QSizeF(297, 210) * (dpi / 25.4)
    image = QImage(int(taille.width()), int(taille.height()), QImage.Format.Format_ARGB32)
    points_par_metre = int(dpi / 0.0254)
    image.setDotsPerMeterX(points_par_metre)
    image.setDotsPerMeterY(points_par_metre)
    image.fill(QColor("#FFFFFF"))
    marge = 10 * dpi / 25.4
    peintre = QPainter(image)
    try:
        peintre.translate(marge, marge)
        dessiner_planning(peintre, image.width() - 2 * marge, image.height() - 2 * marge, base, lundi, genere_le)
    finally:
        peintre.end()
    if not image.save(str(chemin), "PNG"):
        raise OSError(f"Impossible d'écrire {chemin}")
    return chemin
