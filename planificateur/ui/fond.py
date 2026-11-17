"""Exécute un appel lent (réseau) sans figer la fenêtre."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..ia.gemini import ErreurGemini
from ..mises_a_jour import ErreurMiseAJour

ERREURS_EXPLIQUEES = (ErreurGemini, ErreurMiseAJour)

SYNCHRONE = False  # les tests passent à True pour tout exécuter immédiatement
_en_cours: set = set()


class _Signaux(QObject):
    fini = Signal(object)
    echec = Signal(str)


class _Tache(QRunnable):
    def __init__(self, fonction: Callable[[], object], signaux: _Signaux) -> None:
        super().__init__()
        self.fonction = fonction
        self.signaux = signaux

    def run(self) -> None:
        try:
            resultat = self.fonction()
        except ERREURS_EXPLIQUEES as erreur:
            self.signaux.echec.emit(str(erreur))
        except Exception as erreur:  # noqa: BLE001 — toute erreur doit revenir à l'écran
            self.signaux.echec.emit(f"Erreur inattendue : {erreur}")
        else:
            self.signaux.fini.emit(resultat)


def en_fond(fonction: Callable[[], object], si_ok: Callable[[object], None], si_erreur: Callable[[str], None]) -> None:
    """Lance `fonction` en arrière-plan ; `si_ok` / `si_erreur` sont appelés dans le fil principal."""
    if SYNCHRONE:
        try:
            resultat = fonction()
        except ERREURS_EXPLIQUEES as erreur:
            si_erreur(str(erreur))
        except Exception as erreur:  # noqa: BLE001
            si_erreur(f"Erreur inattendue : {erreur}")
        else:
            si_ok(resultat)
        return
    signaux = _Signaux()
    _en_cours.add(signaux)

    def terminer(_=None):
        _en_cours.discard(signaux)

    signaux.fini.connect(si_ok)
    signaux.echec.connect(si_erreur)
    signaux.fini.connect(terminer)
    signaux.echec.connect(terminer)
    QThreadPool.globalInstance().start(_Tache(fonction, signaux))
