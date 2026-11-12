"""Persistance locale SQLite : ouverture, migrations et opérations de base."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, fields
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar, get_args, get_type_hints

from . import modeles as m

T = TypeVar("T")

VERSION_SCHEMA = 1
_SCHEMA = Path(__file__).with_name("schema.sql")


def chemin_par_defaut() -> Path:
    """Emplacement stable des données : %APPDATA%\\PlanificateurEtudes."""
    racine = Path(os.environ.get("APPDATA", Path.home()))
    return racine / "PlanificateurEtudes" / "donnees.db"


def _vers_sql(valeur):
    if isinstance(valeur, Enum):
        return valeur.value
    if isinstance(valeur, bool):
        return int(valeur)
    if isinstance(valeur, datetime):
        return valeur.isoformat(timespec="minutes")
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, time):
        return valeur.strftime("%H:%M")
    return valeur


def _depuis_sql(type_champ, valeur):
    if valeur is None:
        return None
    arguments = get_args(type_champ)  # « int | None » -> (int, NoneType)
    if arguments:
        type_champ = next(a for a in arguments if a is not type(None))
    if type_champ is bool:
        return bool(valeur)
    if type_champ is datetime:
        return datetime.fromisoformat(valeur)
    if type_champ is date:
        return date.fromisoformat(valeur)
    if type_champ is time:
        return time.fromisoformat(valeur)
    if isinstance(type_champ, type) and issubclass(type_champ, Enum):
        return type_champ(valeur)
    return valeur


class Depot(Generic[T]):
    """Création, lecture, modification et suppression pour une table."""

    def __init__(self, cx: sqlite3.Connection, classe: type[T], table: str) -> None:
        self._cx = cx
        self._classe = classe
        self._table = table
        self._types = get_type_hints(classe)
        self._colonnes = [f.name for f in fields(classe) if f.name != "id"]

    def _valeurs(self, objet: T) -> list:
        return [_vers_sql(getattr(objet, c)) for c in self._colonnes]

    def _objet(self, ligne: sqlite3.Row) -> T:
        return self._classe(
            **{c: _depuis_sql(self._types[c], ligne[c]) for c in ligne.keys()}
        )

    def ajouter(self, objet: T) -> T:
        colonnes = ", ".join(self._colonnes)
        marques = ", ".join("?" * len(self._colonnes))
        with self._cx:
            curseur = self._cx.execute(
                f"INSERT INTO {self._table} ({colonnes}) VALUES ({marques})",
                self._valeurs(objet),
            )
        objet.id = curseur.lastrowid
        return objet

    def modifier(self, objet: T) -> None:
        if objet.id is None:
            raise ValueError("Objet non enregistré : utiliser ajouter()")
        affectations = ", ".join(f"{c} = ?" for c in self._colonnes)
        with self._cx:
            self._cx.execute(
                f"UPDATE {self._table} SET {affectations} WHERE id = ?",
                [*self._valeurs(objet), objet.id],
            )

    def supprimer(self, identifiant: int) -> None:
        with self._cx:
            self._cx.execute(f"DELETE FROM {self._table} WHERE id = ?", [identifiant])

    def obtenir(self, identifiant: int) -> T | None:
        ligne = self._cx.execute(
            f"SELECT * FROM {self._table} WHERE id = ?", [identifiant]
        ).fetchone()
        return self._objet(ligne) if ligne else None

    def lister(self, condition: str = "", parametres=(), ordre: str = "id") -> list[T]:
        requete = f"SELECT * FROM {self._table}"
        if condition:
            requete += f" WHERE {condition}"
        requete += f" ORDER BY {ordre}"
        return [self._objet(l) for l in self._cx.execute(requete, parametres)]


class Base:
    """Point d'accès unique aux données locales."""

    def __init__(self, chemin: Path | str | None = None) -> None:
        chemin = Path(chemin) if chemin is not None else chemin_par_defaut()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin = chemin
        self._cx = sqlite3.connect(chemin)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        self._migrer()

        self.matieres = Depot(self._cx, m.Matiere, "matieres")
        self.activites = Depot(self._cx, m.ActiviteFixe, "activites_fixes")
        self.exceptions = Depot(self._cx, m.ExceptionActivite, "exceptions_activite")
        self.epreuves = Depot(self._cx, m.Epreuve, "epreuves")
        self.travaux = Depot(self._cx, m.Travail, "travaux")
        self.sous_taches = Depot(self._cx, m.SousTache, "sous_taches")
        self.seances = Depot(self._cx, m.Seance, "seances")

    @property
    def version(self) -> int:
        return self._cx.execute("PRAGMA user_version").fetchone()[0]

    def _migrer(self) -> None:
        version = self.version
        if version > VERSION_SCHEMA:
            raise RuntimeError(
                "Ce fichier a été créé par une version plus récente de l'application"
            )
        if version < 1:
            self._cx.executescript(
                "BEGIN;"
                + _SCHEMA.read_text(encoding="utf-8")
                + f"PRAGMA user_version = {VERSION_SCHEMA}; COMMIT;"
            )
        # Les migrations futures (version 2, 3…) s'ajouteront ici.

    def preferences(self) -> m.Preferences:
        ligne = self._cx.execute(
            "SELECT valeur FROM parametres WHERE cle = 'preferences'"
        ).fetchone()
        if ligne is None:
            return m.Preferences()
        types = get_type_hints(m.Preferences)
        donnees = {
            c: v if isinstance(v, list) else _depuis_sql(types[c], v)
            for c, v in json.loads(ligne[0]).items()
            if c in types
        }
        return m.Preferences(**donnees)

    def enregistrer_preferences(self, preferences: m.Preferences) -> None:
        donnees = {c: _vers_sql(v) for c, v in asdict(preferences).items()}
        with self._cx:
            self._cx.execute(
                "INSERT INTO parametres (cle, valeur) VALUES ('preferences', ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                [json.dumps(donnees)],
            )

    def fermer(self) -> None:
        self._cx.close()
