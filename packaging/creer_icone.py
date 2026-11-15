"""Génère l'icône de l'application (PNG pour la fenêtre, ICO multi-tailles pour Windows).

Dessin original (formes géométriques) : aucune police ni image tierce n'est
reprise, l'icône peut donc être diffusée librement avec le projet.

À relancer seulement si l'on change l'icône :
    .venv/Scripts/python.exe packaging/creer_icone.py
"""

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

RACINE = Path(__file__).resolve().parents[1]
PNG = RACINE / "planificateur" / "ui" / "images" / "icone.png"
ICO = RACINE / "packaging" / "icone.ico"


def dessiner(taille: int = 512) -> QImage:
    t = taille
    image = QImage(t, t, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fond : carré arrondi en dégradé
    marge = t * 0.04
    fond = QPainterPath()
    fond.addRoundedRect(QRectF(marge, marge, t - 2 * marge, t - 2 * marge), t * 0.22, t * 0.22)
    degrade = QLinearGradient(0, 0, t, t)
    degrade.setColorAt(0, QColor("#6C78EE"))
    degrade.setColorAt(1, QColor("#4350C4"))
    p.fillPath(fond, QBrush(degrade))

    def point(x, y):
        return QPointF(x * t, y * t)

    blanc = QColor("#FFFFFF")
    # Bandeau (la partie qui entoure la tête), sous le plateau
    bandeau = QPainterPath(point(0.31, 0.47))
    bandeau.lineTo(point(0.31, 0.64))
    bandeau.cubicTo(point(0.40, 0.73), point(0.60, 0.73), point(0.69, 0.64))
    bandeau.lineTo(point(0.69, 0.47))
    bandeau.closeSubpath()
    p.fillPath(bandeau, QColor(255, 255, 255, 215))

    # Plateau du chapeau (losange)
    plateau = QPolygonF([point(0.50, 0.25), point(0.88, 0.42), point(0.50, 0.59), point(0.12, 0.42)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(blanc)
    p.drawPolygon(plateau)

    # Gland : cordon et pompon
    p.setPen(QPen(blanc, t * 0.028, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(point(0.80, 0.455), point(0.80, 0.66))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(point(0.80, 0.69), t * 0.035, t * 0.045)
    p.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    image = dessiner()
    PNG.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(PNG), "PNG")
    Image.open(PNG).save(ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(PNG, ICO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
