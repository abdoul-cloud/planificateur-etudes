"""Point d'entrée de l'exécutable construit par PyInstaller."""

import sys

from planificateur.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
