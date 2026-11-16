"""Intégration à Windows : démarrage automatique et instance unique.

- Démarrage avec Windows : une entrée dans la clé « Run » de l'utilisateur
  (aucun droit administrateur), seulement pour l'application installée.
- Instance unique : si l'application tourne déjà (par exemple près de
  l'horloge), relancer son raccourci fait réapparaître la fenêtre existante
  au lieu d'en ouvrir une seconde.
"""

from __future__ import annotations

import sys

NOM = "PlanificateurEtudes"
CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
OPTION_ARRIERE_PLAN = "--arriere-plan"

try:  # Windows seulement
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


def commande_demarrage() -> str | None:
    """Commande lancée au démarrage de Windows, ou None hors application installée."""
    if not getattr(sys, "frozen", False):
        return None  # depuis le code source : pas de démarrage automatique
    return f'"{sys.executable}" {OPTION_ARRIERE_PLAN}'


def demarrage_actif() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLE_RUN) as cle:
            winreg.QueryValueEx(cle, NOM)
            return True
    except OSError:
        return False


def definir_demarrage(actif: bool, commande: str | None = None) -> bool:
    """Active ou retire le démarrage avec Windows. Renvoie l'état obtenu."""
    if winreg is None:
        return False
    commande = commande or commande_demarrage()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLE_RUN) as cle:
        if actif:
            if not commande:
                raise RuntimeError("Le démarrage avec Windows n'est disponible que pour l'application installée.")
            winreg.SetValueEx(cle, NOM, 0, winreg.REG_SZ, commande)
        else:
            try:
                winreg.DeleteValue(cle, NOM)
            except OSError:
                pass
    return demarrage_actif()


class InstanceUnique:
    """Verrou nommé de Windows (mutex) + signal de réveil (événement)."""

    ERREUR_DEJA_EXISTANT = 183

    def __init__(self, nom: str = NOM) -> None:
        self.premiere = True
        self._evenement = None
        if sys.platform != "win32":
            return
        import ctypes

        noyau = ctypes.windll.kernel32
        self._noyau = noyau
        self._verrou = noyau.CreateMutexW(None, False, f"Local\\{nom}")
        self.premiere = noyau.GetLastError() != self.ERREUR_DEJA_EXISTANT
        self._evenement = noyau.CreateEventW(None, False, False, f"Local\\{nom}Reveil")

    def reveiller_l_autre(self) -> None:
        """Demande à l'instance déjà ouverte de montrer sa fenêtre."""
        if self._evenement:
            self._noyau.SetEvent(self._evenement)

    def a_ete_reveillee(self) -> bool:
        """Vrai si une autre instance a demandé de montrer la fenêtre (non bloquant)."""
        return bool(self._evenement) and self._noyau.WaitForSingleObject(self._evenement, 0) == 0
