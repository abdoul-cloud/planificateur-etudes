"""Copie automatique des données vers un autre endroit : clé USB, disque externe, dossier OneDrive…

Si l'ordinateur tombe en panne, la dernière copie permet de tout retrouver (Sauvegarde > Restaurer).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .base import Base

PARAMETRE = "sauvegarde_externe"
PREFIXE = "PlanificateurEtudes_"
GARDER = 5  # copies conservées dans le dossier choisi
FREQUENCES = {1: "Chaque jour", 7: "Chaque semaine", 14: "Toutes les deux semaines"}


class DossierIndisponible(Exception):
    """Clé USB débranchée, disque absent… : la copie sera retentée plus tard."""


@dataclass
class Reglages:
    dossier: str = ""
    frequence_jours: int = 7
    derniere: datetime | None = None

    @property
    def actif(self) -> bool:
        return bool(self.dossier)


def charger(base: Base) -> Reglages:
    try:
        brut = json.loads(base.parametre(PARAMETRE) or "{}")
    except ValueError:
        brut = {}
    derniere = brut.get("derniere")
    frequence = int(brut.get("frequence_jours", 7))
    return Reglages(str(brut.get("dossier") or ""), frequence if frequence in FREQUENCES else 7,
                    datetime.fromisoformat(derniere) if derniere else None)


def enregistrer(base: Base, reglages: Reglages) -> None:
    base.definir_parametre(PARAMETRE, json.dumps({
        "dossier": reglages.dossier,
        "frequence_jours": reglages.frequence_jours,
        "derniere": reglages.derniere.isoformat(timespec="minutes") if reglages.derniere else None,
    }))


def dossier_onedrive() -> Path | None:
    """Dossier OneDrive de l'utilisateur, s'il est installé (synchronisé automatiquement en ligne)."""
    for variable in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        chemin = os.environ.get(variable)
        if chemin and Path(chemin).is_dir():
            return Path(chemin) / "Planificateur d'études"
    return None


def copie_due(base: Base, maintenant: datetime) -> bool:
    r = charger(base)
    return r.actif and (r.derniere is None or maintenant - r.derniere >= timedelta(days=r.frequence_jours))


def en_retard(base: Base, maintenant: datetime) -> bool:
    """Plus d'une semaine de retard sur la fréquence choisie : à signaler."""
    r = charger(base)
    return r.actif and r.derniere is not None and maintenant - r.derniere >= timedelta(days=r.frequence_jours + 7)


def copies(dossier: Path) -> list[Path]:
    return sorted(dossier.glob(f"{PREFIXE}*.db")) if dossier.is_dir() else []


def faire_copie(base: Base, maintenant: datetime) -> Path:
    reglages = charger(base)
    if not reglages.actif:
        raise DossierIndisponible("Aucun dossier choisi pour la copie automatique.")
    dossier = Path(reglages.dossier)
    racine = Path(dossier.anchor) if dossier.anchor else dossier
    if not racine.exists():
        raise DossierIndisponible(f"{dossier} est introuvable : branchez la clé USB ou le disque, "
                                  "la copie se fera automatiquement.")
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / f"{PREFIXE}{maintenant:%Y-%m-%d_%H%M}.db"
        base.sauvegarder(cible)
    except OSError as erreur:
        raise DossierIndisponible(f"Copie impossible dans {dossier} : {erreur.strerror or erreur}") from erreur
    for ancienne in copies(dossier)[:-GARDER]:
        try:
            ancienne.unlink()
        except OSError:
            pass
    reglages.derniere = maintenant
    enregistrer(base, reglages)
    return cible


def etat_texte(base: Base, maintenant: datetime) -> str:
    r = charger(base)
    if not r.actif:
        return "Désactivée : vos données ne sont copiées que sur cet ordinateur."
    frequence = FREQUENCES[r.frequence_jours].lower()
    if r.derniere is None:
        return f"Vers {r.dossier}, {frequence}. Aucune copie faite pour l'instant."
    jours = (maintenant.date() - r.derniere.date()).days
    quand = "aujourd'hui" if jours == 0 else "hier" if jours == 1 else f"il y a {jours} jours"
    alerte = "⚠ " if en_retard(base, maintenant) else "✓ "
    return f"{alerte}Dernière copie {quand} ({r.derniere:%d/%m à %H:%M}) vers {r.dossier}, {frequence}."
