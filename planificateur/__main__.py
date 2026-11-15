"""Lancement : python -m planificateur

Option --autotest : ouvre toute l'interface sur des données temporaires,
vérifie les ressources (schéma, images, icône), exporte un PDF, puis quitte
avec le code 0 si tout va bien. Sert à contrôler l'exécutable construit.
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

from .base import Base
from .ui.fenetre import FenetrePrincipale
from .ui.theme import IMAGES, appliquer_theme

VERSION = "0.4.0"


def _autotest() -> int:
    import tempfile
    import traceback
    from datetime import date, datetime, time

    from . import modeles as m
    from .ui.calendrier import enregistrer_resultat, generer
    from .ui.export import exporter_pdf

    dossier = Path(tempfile.mkdtemp(prefix="planificateur-autotest-"))
    journal = dossier / "autotest.txt"
    try:
        for nom in ("chevron_bas.svg", "chevron_haut.svg", "coche.svg", "icone.png"):
            if QImage(f"{IMAGES}/{nom}").isNull():
                raise RuntimeError(f"Image illisible dans l'application construite : {nom}")
        base = Base(dossier / "donnees.db")
        maths = base.matieres.ajouter(m.Matiere("Maths"))
        base.activites.ajouter(m.ActiviteFixe("Cours", time(7), time(12), jour_semaine=0, matiere_id=maths.id))
        lundi = date.today()
        base.epreuves.ajouter(m.Epreuve(maths.id, datetime.combine(lundi, time(14)), datetime.combine(lundi, time(16))))
        enregistrer_resultat(base, generer(base))
        fenetre = FenetrePrincipale(base)
        for nom in FenetrePrincipale.ECRANS:
            fenetre.afficher(nom)
            fenetre.grab()
        exporter_pdf(base, lundi, dossier / "planning.pdf")
        base.sauvegarder(dossier / "copie.db")
        # L'assistant IA a besoin du HTTPS : vérifie qu'il est bien embarqué (aucune requête envoyée).
        from .ia.gemini import verifier_https

        verifier_https()
        base.fermer()
        journal.write_text("OK", encoding="utf-8")
        print(f"autotest OK — {dossier}")
        return 0
    except Exception:  # noqa: BLE001 — on veut le détail complet dans le journal
        journal.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"autotest ÉCHEC — voir {journal}")
        return 1


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Planificateur d'études")
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(QIcon(f"{IMAGES}/icone.png"))
    appliquer_theme(application)
    if "--autotest" in sys.argv:
        return _autotest()
    base = Base()
    try:
        base.sauvegarde_automatique()
    except (OSError, ValueError):
        pass  # une copie manquée ne doit jamais empêcher l'ouverture
    fenetre = FenetrePrincipale(base)
    fenetre.show()
    code = application.exec()
    base.fermer()
    return code


if __name__ == "__main__":
    sys.exit(main())
