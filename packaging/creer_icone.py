"""Génère l'icône de l'application (PNG pour la fenêtre, ICO multi-tailles pour Windows).

À relancer seulement si l'on change l'icône :
    .venv/Scripts/python.exe packaging/creer_icone.py
"""

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

RACINE = Path(__file__).resolve().parents[1]
PNG = RACINE / "planificateur" / "ui" / "images" / "icone.png"
ICO = RACINE / "packaging" / "icone.ico"
CHAPEAU = ""  # glyphe « Education » de Segoe Fluent Icons


def dessiner(taille: int = 512) -> QImage:
    image = QImage(taille, taille, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fond = QPainterPath()
    marge = taille * 0.04
    fond.addRoundedRect(QRectF(marge, marge, taille - 2 * marge, taille - 2 * marge), taille * 0.22, taille * 0.22)
    p.fillPath(fond, QColor("#4F5BD5"))
    police = QFont("Segoe Fluent Icons")
    police.setPixelSize(int(taille * 0.58))
    p.setFont(police)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(0, taille * 0.02, taille, taille), Qt.AlignmentFlag.AlignCenter, CHAPEAU)
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
