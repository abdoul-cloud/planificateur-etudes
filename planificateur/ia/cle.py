"""Clé API Gemini, chiffrée avec la protection de données de Windows (DPAPI).

La clé n'est jamais enregistrée en clair : elle est chiffrée pour le compte
Windows courant (seul cet utilisateur, sur cet ordinateur, peut la relire),
puis rangée dans la base sous forme illisible. Une sauvegarde copiée sur un
autre ordinateur ne permet donc pas de la récupérer.
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

from ..base import Base

CLE_PARAMETRE = "gemini_cle_chiffree"
MODELE_PARAMETRE = "gemini_modele"
ACTIF_PARAMETRE = "gemini_actif"
MODELE_PAR_DEFAUT = "gemini-flash-latest"  # alias tenu à jour par Google vers le dernier modèle Flash


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _vers_blob(donnees: bytes) -> _Blob:
    tampon = ctypes.create_string_buffer(donnees, len(donnees))
    return _Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))


def _depuis_blob(blob: _Blob) -> bytes:
    donnees = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return donnees


def proteger(texte: str) -> str:
    """Chiffre pour l'utilisateur Windows courant ; renvoie du base64."""
    if sys.platform != "win32":
        raise RuntimeError("Le chiffrement de la clé n'est disponible que sous Windows.")
    entree, sortie = _vers_blob(texte.encode("utf-8")), _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entree), "Planificateur", None, None, None, 0,
                                                  ctypes.byref(sortie)):
        raise ctypes.WinError()
    return base64.b64encode(_depuis_blob(sortie)).decode("ascii")


def deproteger(chiffre: str) -> str:
    if sys.platform != "win32":
        raise RuntimeError("Le chiffrement de la clé n'est disponible que sous Windows.")
    entree, sortie = _vers_blob(base64.b64decode(chiffre)), _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entree), None, None, None, None, 0,
                                                    ctypes.byref(sortie)):
        raise ctypes.WinError()
    return _depuis_blob(sortie).decode("utf-8")


def enregistrer_cle(base: Base, cle: str) -> None:
    cle = cle.strip()
    if len(cle) < 20 or " " in cle:
        raise ValueError("Cette clé ne ressemble pas à une clé API Gemini.")
    base.definir_parametre(CLE_PARAMETRE, proteger(cle))


def lire_cle(base: Base) -> str | None:
    chiffre = base.parametre(CLE_PARAMETRE)
    if not chiffre:
        return None
    try:
        return deproteger(chiffre)
    except OSError:
        return None  # chiffrée par un autre compte ou un autre ordinateur (ex. sauvegarde restaurée)


def effacer_cle(base: Base) -> None:
    base.supprimer_parametre(CLE_PARAMETRE)


def modele(base: Base) -> str:
    return base.parametre(MODELE_PARAMETRE) or MODELE_PAR_DEFAUT


def definir_modele(base: Base, nom: str) -> None:
    base.definir_parametre(MODELE_PARAMETRE, nom.strip() or MODELE_PAR_DEFAUT)


def est_actif(base: Base) -> bool:
    return base.parametre(ACTIF_PARAMETRE, "1") == "1" and lire_cle(base) is not None


def definir_actif(base: Base, actif: bool) -> None:
    base.definir_parametre(ACTIF_PARAMETRE, "1" if actif else "0")
