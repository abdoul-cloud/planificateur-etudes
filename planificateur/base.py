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

VERSION_SCHEMA = 4
_SCHEMA = Path(__file__).with_name("schema.sql")  # version 1

# Chaque migration fait passer la base de la version précédente à la clé.
MIGRATIONS = {
    4: "CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, titre TEXT NOT NULL, "
    "creee TEXT NOT NULL, modifiee TEXT NOT NULL, contenu TEXT NOT NULL DEFAULT '{}');",
    3: "ALTER TABLE matieres ADD COLUMN terminee INTEGER NOT NULL DEFAULT 0;",
    2: "ALTER TABLE epreuves ADD COLUMN minutes_preparation INTEGER "
    "CHECK (minutes_preparation IS NULL OR minutes_preparation > 0);",
}


TABLES_ATTENDUES = {"matieres", "activites_fixes", "epreuves", "travaux", "seances", "parametres"}


class InfoSauvegarde:
    """Résumé d'un fichier de sauvegarde vérifié."""

    def __init__(self, chemin: Path, version: int, comptes: dict[str, int]) -> None:
        self.chemin = chemin
        self.version = version
        self.comptes = comptes

    def resume(self) -> str:
        c = self.comptes
        return (f"{c['matieres']} matière(s), {c['activites_fixes']} activité(s), {c['epreuves']} épreuve(s), "
                f"{c['travaux']} travail(aux), {c['seances']} séance(s)")


def _ouvrir_lecture_seule(chemin: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(chemin).resolve().as_uri() + "?mode=ro", uri=True)


def verifier_sauvegarde(chemin: Path | str) -> InfoSauvegarde:
    """Vérifie qu'un fichier est une sauvegarde lisible et intacte du planificateur.

    Lève ValueError avec un message compréhensible sinon. Le fichier n'est
    jamais modifié.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ValueError("Ce fichier n'existe pas.")
    try:
        cx = _ouvrir_lecture_seule(chemin)
        try:
            if cx.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Ce fichier est endommagé : la vérification d'intégrité a échoué.")
            version = cx.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not TABLES_ATTENDUES <= tables or version < 1:
                raise ValueError("Ce fichier n'est pas une sauvegarde du planificateur.")
            if version > VERSION_SCHEMA:
                raise ValueError("Cette sauvegarde vient d'une version plus récente de l'application.")
            comptes = {nom: cx.execute(f"SELECT COUNT(*) FROM {nom}").fetchone()[0] for nom in sorted(TABLES_ATTENDUES)}
        finally:
            cx.close()
    except sqlite3.DatabaseError as erreur:
        raise ValueError("Ce fichier n'est pas une sauvegarde lisible du planificateur.") from erreur
    return InfoSauvegarde(chemin, version, comptes)


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


def _en_json(valeur):
    """Convertit récursivement les heures en texte pour json.dumps."""
    if isinstance(valeur, dict):
        return {str(k): _en_json(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [_en_json(v) for v in valeur]
    return _vers_sql(valeur)


def _preferences_depuis(donnees: dict) -> m.Preferences:
    h = time.fromisoformat

    def plage(d: dict) -> m.Plage:
        return m.Plage(h(d["debut"]), h(d["fin"]), d.get("nom", ""))

    def hebdo(d: dict) -> m.PlageHebdo:
        return m.PlageHebdo(d["jours"], h(d["debut"]), h(d["fin"]))

    def reglage(d: dict) -> m.ReglageJour:
        return m.ReglageJour(
            bool(d["travaille"]), h(d["debut"]), h(d["fin"]), d["max_minutes"],
            [plage(p) for p in d["pauses"]],
        )

    connus = {f.name for f in fields(m.Preferences)}
    d = {c: v for c, v in donnees.items() if c in connus}  # ignore les anciens champs
    for cle in ("debut_journee", "fin_journee"):
        if cle in d:
            d[cle] = h(d[cle])
    types = get_type_hints(m.Preferences)
    for cle, valeur in list(d.items()):
        if types.get(cle) is bool:
            d[cle] = bool(valeur)  # les booléens sont enregistrés en 0 / 1
    if "pauses_quotidiennes" in d:
        d["pauses_quotidiennes"] = [plage(p) for p in d["pauses_quotidiennes"]]
    if "reglages_jour" in d:
        d["reglages_jour"] = {int(j): reglage(r) for j, r in d["reglages_jour"].items()}
    for cle in ("plages_preferees", "plages_evitees", "plages_garanties"):
        if cle in d:
            d[cle] = [hebdo(p) for p in d[cle]]
    return m.Preferences(**d)


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
                "BEGIN;" + _SCHEMA.read_text(encoding="utf-8") + "PRAGMA user_version = 1; COMMIT;"
            )
            version = 1
        for cible in range(version + 1, VERSION_SCHEMA + 1):
            self._cx.executescript(
                f"BEGIN; {MIGRATIONS[cible]} PRAGMA user_version = {cible}; COMMIT;"
            )

    # --- Paramètres divers (texte libre, ex. réglages de l'assistant) ----------

    def parametre(self, cle: str, defaut: str | None = None) -> str | None:
        ligne = self._cx.execute("SELECT valeur FROM parametres WHERE cle = ?", [cle]).fetchone()
        return ligne[0] if ligne else defaut

    def definir_parametre(self, cle: str, valeur: str) -> None:
        with self._cx:
            self._cx.execute(
                "INSERT INTO parametres (cle, valeur) VALUES (?, ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                [cle, valeur],
            )

    def supprimer_parametre(self, cle: str) -> None:
        with self._cx:
            self._cx.execute("DELETE FROM parametres WHERE cle = ?", [cle])

    def preferences(self) -> m.Preferences:
        ligne = self._cx.execute(
            "SELECT valeur FROM parametres WHERE cle = 'preferences'"
        ).fetchone()
        if ligne is None:
            return m.Preferences()
        return _preferences_depuis(json.loads(ligne[0]))

    def enregistrer_preferences(self, preferences: m.Preferences) -> None:
        donnees = _en_json(asdict(preferences))
        with self._cx:
            self._cx.execute(
                "INSERT INTO parametres (cle, valeur) VALUES ('preferences', ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                [json.dumps(donnees)],
            )

    # --- Sauvegarde et restauration -----------------------------------------

    @property
    def dossier_sauvegardes(self) -> Path:
        dossier = self.chemin.parent / "sauvegardes"
        dossier.mkdir(parents=True, exist_ok=True)
        return dossier

    def sauvegarder(self, destination: Path | str) -> InfoSauvegarde:
        """Copie cohérente des données vers `destination`, puis vérification."""
        destination = Path(destination)
        if destination.resolve() == self.chemin.resolve():
            raise ValueError("Choisissez un autre fichier que celui des données en cours.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        cible = sqlite3.connect(destination)
        try:
            self._cx.backup(cible)
        finally:
            cible.close()
        return verifier_sauvegarde(destination)

    def restaurer(self, source: Path | str, maintenant: datetime | None = None) -> Path:
        """Remplace les données par celles d'une sauvegarde vérifiée.

        Les données actuelles sont d'abord copiées dans le dossier des
        sauvegardes : renvoie le chemin de cette copie de sécurité.
        """
        source = Path(source)
        if source.resolve() == self.chemin.resolve():
            raise ValueError("Ce fichier est celui des données en cours.")
        verifier_sauvegarde(source)
        horodatage = (maintenant or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
        securite = self.dossier_sauvegardes / f"avant-restauration_{horodatage}.db"
        self.sauvegarder(securite)
        origine = _ouvrir_lecture_seule(source)
        try:
            origine.backup(self._cx)
        finally:
            origine.close()
        self._migrer()  # une sauvegarde plus ancienne est mise à niveau
        return securite

    def sauvegarde_automatique(self, garder: int = 10, aujourd_hui: date | None = None) -> Path | None:
        """Une copie par jour dans le dossier des sauvegardes, les `garder` plus récentes."""
        jour = aujourd_hui or date.today()
        cible = self.dossier_sauvegardes / f"auto_{jour.isoformat()}.db"
        cree = None
        if not cible.exists():
            self.sauvegarder(cible)
            cree = cible
        automatiques = sorted(self.dossier_sauvegardes.glob("auto_*.db"))
        for ancienne in automatiques[:-garder]:
            ancienne.unlink()
        return cree

    def fermer(self) -> None:
        self._cx.close()
