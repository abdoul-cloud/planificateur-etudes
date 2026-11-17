"""Nouvelle version disponible ? (facultatif, désactivable dans les Préférences)

Une seule question est posée, à GitHub : « quelle est la dernière version publiée ? ».
Rien n'est envoyé : ni données, ni identifiant, seulement le nom de l'application et son numéro de version.
Ce module et le client Gemini sont les deux seuls à accéder à Internet.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from . import __version__

DEPOT = "abdoul-cloud/planificateur-etudes"
URL_DERNIERE = f"https://api.github.com/repos/{DEPOT}/releases/latest"
URL_PAGE = f"https://github.com/{DEPOT}/releases/latest"
DELAI_S = 10
INTERVALLE = timedelta(hours=20)  # au plus une vérification par jour (environ)

PARAMETRE = "mises_a_jour"


@dataclass(frozen=True)
class Version:
    numero: str
    page: str  # page de la version (notes)
    telechargement: str  # lien direct vers l'installateur, sinon la page
    notes: str = ""


@dataclass
class Reglages:
    actif: bool = True
    derniere_verification: datetime | None = None
    version_ignoree: str = ""


class ErreurMiseAJour(Exception):
    pass


def numero(texte: str) -> tuple[int, ...]:
    """« v0.10.2 » -> (0, 10, 2) ; ce qui n'est pas un numéro donne ()."""
    morceaux = re.findall(r"\d+", texte.split("-")[0])
    return tuple(int(x) for x in morceaux[:4])


def plus_recente(candidate: str, actuelle: str = __version__) -> bool:
    a, b = numero(candidate), numero(actuelle)
    return bool(a) and a > b


def _telecharger(url: str) -> bytes:
    requete = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"PlanificateurEtudes/{__version__}",
    })
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
            return reponse.read()
    except urllib.error.HTTPError as erreur:
        raise ErreurMiseAJour(f"GitHub a répondu {erreur.code}") from erreur
    except (urllib.error.URLError, TimeoutError, OSError) as erreur:
        raise ErreurMiseAJour("Pas de connexion à Internet (ou GitHub injoignable)") from erreur


def derniere_version(transport: Callable[[str], bytes] = _telecharger) -> Version:
    try:
        donnees = json.loads(transport(URL_DERNIERE))
        tag = str(donnees["tag_name"])
    except (ValueError, KeyError, TypeError) as erreur:
        raise ErreurMiseAJour("Réponse de GitHub illisible") from erreur
    page = str(donnees.get("html_url") or URL_PAGE)
    installateur = next((a.get("browser_download_url") for a in donnees.get("assets") or []
                         if str(a.get("name", "")).lower().endswith(".exe")), None)
    return Version(tag.lstrip("vV"), page, str(installateur or page), str(donnees.get("body") or ""))


# --- Réglages, enregistrés dans la base -------------------------------------------------------


def charger(base) -> Reglages:
    try:
        brut = json.loads(base.parametre(PARAMETRE) or "{}")
    except ValueError:
        brut = {}
    date = brut.get("derniere_verification")
    return Reglages(
        actif=bool(brut.get("actif", True)),
        derniere_verification=datetime.fromisoformat(date) if date else None,
        version_ignoree=str(brut.get("version_ignoree", "")),
    )


def enregistrer(base, reglages: Reglages) -> None:
    base.definir_parametre(PARAMETRE, json.dumps({
        "actif": reglages.actif,
        "derniere_verification": reglages.derniere_verification.isoformat(timespec="minutes")
        if reglages.derniere_verification else None,
        "version_ignoree": reglages.version_ignoree,
    }))


def a_verifier(base, maintenant: datetime) -> bool:
    r = charger(base)
    return r.actif and (r.derniere_verification is None or maintenant - r.derniere_verification >= INTERVALLE)


def verifier(base, maintenant: datetime, transport: Callable[[str], bytes] = _telecharger,
             forcer: bool = False) -> Version | None:
    """Renvoie la nouvelle version à proposer, ou None. Lève ErreurMiseAJour si GitHub est injoignable.

    Sans `forcer`, une version que l'utilisateur a choisi d'ignorer n'est plus proposée.
    """
    version = derniere_version(transport)
    reglages = charger(base)
    reglages.derniere_verification = maintenant
    enregistrer(base, reglages)
    if not plus_recente(version.numero):
        return None
    if not forcer and version.numero == reglages.version_ignoree:
        return None
    return version


def ignorer(base, version: str) -> None:
    reglages = charger(base)
    reglages.version_ignoree = version
    enregistrer(base, reglages)
