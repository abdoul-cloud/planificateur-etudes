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
from .calendrier import MOIS, CalendrierSemaine, _Legende, texte_semaine
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


def exporter_epreuves_pdf(base: Base, chemin: Path | str, depuis: date | None = None,
                          genere_le: datetime | None = None) -> tuple[Path, int]:
    """Liste des épreuves à venir, en A4 portrait, à afficher ou à imprimer. Renvoie (chemin, nombre)."""
    from html import escape

    from PySide6.QtGui import QTextDocument

    depuis = depuis or date.today()
    genere_le = genere_le or datetime.now()
    matieres = {x.id: x for x in base.matieres.lister()}
    epreuves = sorted((e for e in base.epreuves.lister() if e.debut.date() >= depuis), key=lambda e: e.debut)
    lignes = []
    mois_courant = None
    for e in epreuves:
        mois = f"{MOIS[e.debut.month - 1].capitalize()} {e.debut.year}"
        if mois != mois_courant:
            mois_courant = mois
            lignes.append(f"<tr><td colspan='5' class='mois'>{mois}</td></tr>")
        matiere = matieres.get(e.matiere_id)
        couleur = matiere.couleur if matiere else theme.ACCENT
        jours = (e.debut.date() - depuis).days
        dans = "aujourd'hui" if jours == 0 else "demain" if jours == 1 else f"dans {jours} j"
        details = escape(" · ".join(x for x in (e.intitule, e.chapitres) if x))
        lignes.append(
            f"<tr><td class='date'>{JOURS[e.debut.weekday()][:3].lower()}. {e.debut:%d/%m}<br>"
            f"<span class='doux'>{dans}</span></td>"
            f"<td>{e.debut:%H:%M} – {e.fin:%H:%M}</td>"
            f"<td><span style='color:{couleur}'>&#9632;</span> <b>{escape(matiere.nom if matiere else '?')}</b></td>"
            f"<td>{LIBELLES[e.type]}</td><td class='doux'>{details}</td></tr>")
    if not lignes:
        lignes.append("<tr><td colspan='5' class='doux'>Aucune épreuve à venir.</td></tr>")
    html = f"""
    <style>
      body {{ font-family: 'Segoe UI'; font-size: 10pt; color: #1F2433; }}
      h1 {{ font-size: 18pt; margin: 0; }}
      .doux {{ color: #6B7280; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 14px; }}
      th {{ text-align: left; color: #6B7280; font-weight: 600; border-bottom: 1px solid #D5D9E3; padding: 6px; }}
      td {{ padding: 7px 6px; border-bottom: 1px solid #EEF0F6; vertical-align: top; }}
      td.mois {{ font-weight: 700; color: #4F5BD5; padding-top: 14px; border-bottom: none; }}
      td.date {{ white-space: nowrap; }}
    </style>
    <h1>Mes épreuves</h1>
    <p class='doux'>À partir du {depuis:%d/%m/%Y} · {len(epreuves)} épreuve{'s' if len(epreuves) > 1 else ''} ·
    imprimé le {genere_le:%d/%m/%Y à %H:%M} par le Planificateur d'études</p>
    <table width='100%' cellspacing='0'><tr><th>Date</th><th>Horaire</th><th>Matière</th><th>Type</th><th>Détails</th></tr>
    {''.join(lignes)}</table>
    """
    chemin = Path(chemin)
    ecrivain = QPdfWriter(str(chemin))
    ecrivain.setResolution(300)
    ecrivain.setTitle("Mes épreuves")
    ecrivain.setCreator("Planificateur d'études")
    ecrivain.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                       QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter))
    document = QTextDocument()
    document.setHtml(html)
    document.print_(ecrivain)
    return chemin, len(epreuves)
