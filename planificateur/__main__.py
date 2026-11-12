"""Lancement : python -m planificateur"""

import sys

from PySide6.QtWidgets import QApplication

from .base import Base
from .ui.fenetre import FenetrePrincipale


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Planificateur d'études")
    base = Base()
    fenetre = FenetrePrincipale(base)
    fenetre.show()
    code = application.exec()
    base.fermer()
    return code


if __name__ == "__main__":
    sys.exit(main())
