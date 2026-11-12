"""Lancement : python -m planificateur"""

import sys

from PySide6.QtWidgets import QApplication

from .base import Base
from .ui.fenetre import FenetrePrincipale
from .ui.theme import appliquer_theme


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Planificateur d'études")
    appliquer_theme(application)
    base = Base()
    fenetre = FenetrePrincipale(base)
    fenetre.show()
    code = application.exec()
    base.fermer()
    return code


if __name__ == "__main__":
    sys.exit(main())
