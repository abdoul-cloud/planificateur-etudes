"""Modèles de données du planificateur (cahier des charges, section 5).

Ces classes ne dépendent ni de SQLite ni de l'interface : le moteur de
planification les reçoit en entrée et renvoie des `Seance`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum


class TypeActivite(StrEnum):
    COURS = "cours"
    TD = "td"
    TP = "tp"
    DEPLACEMENT = "deplacement"
    PERSONNEL = "personnel"  # sommeil, repas, repos, engagements
    AUTRE = "autre"


class TypeEpreuve(StrEnum):
    INTERROGATION = "interrogation"
    DEVOIR_SURVEILLE = "devoir_surveille"
    COMPOSITION = "composition"
    EXAMEN = "examen"


class EtatEpreuve(StrEnum):
    A_PREPARER = "a_preparer"
    PREPAREE = "preparee"
    PASSEE = "passee"


class EtatTravail(StrEnum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    RENDU = "rendu"


class TypeSeance(StrEnum):
    REVISION = "revision"
    PREPARATION = "preparation"  # préparation d'une épreuve
    TRAVAIL = "travail"  # travail à rendre


class StatutSeance(StrEnum):
    PREVUE = "prevue"
    TERMINEE = "terminee"
    PARTIELLE = "partielle"
    MANQUEE = "manquee"
    REPORTEE = "reportee"


class Origine(StrEnum):
    AUTO = "auto"
    MANUELLE = "manuelle"


def _echelle(nom: str, valeur: int) -> None:
    if not 1 <= valeur <= 5:
        raise ValueError(f"{nom} doit être compris entre 1 et 5 (reçu : {valeur})")


def _ordre(debut, fin) -> None:
    if fin <= debut:
        raise ValueError("La fin doit être postérieure au début")


@dataclass
class Matiere:
    nom: str
    code: str = ""
    coefficient: float = 1.0
    difficulte: int = 3  # 1 = facile, 5 = très difficile
    maitrise: int = 3  # 1 = pas maîtrisée, 5 = très bien maîtrisée
    couleur: str = "#4C72B0"
    notes: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.nom.strip():
            raise ValueError("Le nom de la matière est obligatoire")
        if self.coefficient <= 0:
            raise ValueError("Le coefficient doit être positif")
        _echelle("La difficulté", self.difficulte)
        _echelle("La maîtrise", self.maitrise)


@dataclass
class ActiviteFixe:
    """Créneau non déplaçable : hebdomadaire (jour_semaine) ou ponctuel (date)."""

    nom: str
    heure_debut: time
    heure_fin: time
    type: TypeActivite = TypeActivite.COURS
    jour_semaine: int | None = None  # 0 = lundi … 6 = dimanche
    date: date | None = None
    valide_du: date | None = None  # bornes de la récurrence (semestre)
    valide_au: date | None = None
    marge_avant_min: int = 0  # déplacement avant
    marge_apres_min: int = 0
    matiere_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _ordre(self.heure_debut, self.heure_fin)
        if (self.jour_semaine is None) == (self.date is None):
            raise ValueError("Indiquer soit un jour de la semaine, soit une date")
        if self.jour_semaine is not None and not 0 <= self.jour_semaine <= 6:
            raise ValueError("Le jour de la semaine va de 0 (lundi) à 6 (dimanche)")
        if self.marge_avant_min < 0 or self.marge_apres_min < 0:
            raise ValueError("Les marges ne peuvent pas être négatives")

    @property
    def recurrente(self) -> bool:
        return self.jour_semaine is not None


@dataclass
class ExceptionActivite:
    """Occurrence annulée d'une activité récurrente (férié, cours annulé)."""

    activite_id: int
    date: date
    id: int | None = None


@dataclass
class Epreuve:
    matiere_id: int
    debut: datetime
    fin: datetime
    type: TypeEpreuve = TypeEpreuve.COMPOSITION
    intitule: str = ""
    chapitres: str = ""
    importance: int = 3
    difficulte: int = 3
    preparation: int = 1  # niveau de préparation estimé, 1 à 5
    etat: EtatEpreuve = EtatEpreuve.A_PREPARER
    minutes_preparation: int | None = None  # None = estimation automatique
    id: int | None = None

    def __post_init__(self) -> None:
        _ordre(self.debut, self.fin)
        if self.minutes_preparation is not None and self.minutes_preparation <= 0:
            raise ValueError("Le temps de préparation doit être positif")
        _echelle("L'importance", self.importance)
        _echelle("La difficulté", self.difficulte)
        _echelle("Le niveau de préparation", self.preparation)


@dataclass
class Travail:
    intitule: str
    matiere_id: int
    echeance: datetime
    minutes_estimees: int
    minutes_restantes: int | None = None  # None = rien de fait
    type: str = "devoir"
    date_cible: datetime | None = None  # échéance personnelle anticipée
    importance: int = 3
    etat: EtatTravail = EtatTravail.A_FAIRE
    notes: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.intitule.strip():
            raise ValueError("L'intitulé du travail est obligatoire")
        if self.minutes_estimees <= 0:
            raise ValueError("Le temps estimé doit être positif")
        if self.minutes_restantes is None:
            self.minutes_restantes = self.minutes_estimees
        if self.minutes_restantes < 0:
            raise ValueError("Le temps restant ne peut pas être négatif")
        if self.date_cible is not None and self.date_cible > self.echeance:
            raise ValueError("La date cible doit précéder l'échéance officielle")
        _echelle("L'importance", self.importance)


@dataclass
class SousTache:
    travail_id: int
    intitule: str
    terminee: bool = False
    ordre: int = 0
    id: int | None = None


@dataclass
class Seance:
    type: TypeSeance
    debut: datetime
    fin: datetime
    matiere_id: int | None = None
    epreuve_id: int | None = None
    travail_id: int | None = None
    statut: StatutSeance = StatutSeance.PREVUE
    minutes_effectuees: int | None = None
    origine: Origine = Origine.AUTO
    verrouillee: bool = False  # jamais déplacée par un recalcul
    id: int | None = None

    def __post_init__(self) -> None:
        _ordre(self.debut, self.fin)
        if self.type is TypeSeance.PREPARATION and self.epreuve_id is None:
            raise ValueError("Une séance de préparation doit viser une épreuve")
        if self.type is TypeSeance.TRAVAIL and self.travail_id is None:
            raise ValueError("Une séance de travail doit viser un travail à rendre")

    @property
    def minutes(self) -> int:
        return int((self.fin - self.debut).total_seconds() // 60)


@dataclass
class Plage:
    """Plage horaire dans une journée (pause, repas, repos…)."""

    debut: time
    fin: time
    nom: str = ""

    def __post_init__(self) -> None:
        _ordre(self.debut, self.fin)


def _plages_garanties_par_defaut() -> list["PlageHebdo"]:
    # Du lundi au vendredi, de 20 h à 23 h : toujours du travail personnel.
    return [PlageHebdo([0, 1, 2, 3, 4], time(20), time(23))]


def _pauses_par_defaut() -> list[Plage]:
    # Le déjeuner inclut la petite pause qui suit le repas.
    return [Plage(time(12), time(13), "Déjeuner"), Plage(time(18), time(19), "Dîner")]


@dataclass
class ReglageJour:
    """Réglage d'un jour de la semaine, qui remplace le réglage général."""

    travaille: bool = True  # False = jour de repos complet
    debut: time = time(7)
    fin: time = time(23)
    max_minutes: int = 360
    pauses: list[Plage] = field(default_factory=_pauses_par_defaut)

    def __post_init__(self) -> None:
        _ordre(self.debut, self.fin)
        if self.max_minutes < 0:
            raise ValueError("La limite de travail du jour ne peut pas être négative")


@dataclass
class PlageHebdo:
    """Plage répétée certains jours de la semaine (0 = lundi)."""

    jours: list[int]
    debut: time
    fin: time

    def __post_init__(self) -> None:
        _ordre(self.debut, self.fin)
        if not self.jours or any(not 0 <= j <= 6 for j in self.jours):
            raise ValueError("Les jours vont de 0 (lundi) à 6 (dimanche)")


@dataclass
class Preferences:
    duree_min_seance: int = 45  # minutes
    duree_max_seance: int = 90
    pause_min: int = 10  # entre deux séances
    # Réglage général, valable pour tout jour sans réglage particulier.
    debut_journee: time = time(7, 0)
    fin_journee: time = time(23, 0)
    max_minutes_jour: int = 360  # 6 h de travail personnel par jour
    pauses_quotidiennes: list[Plage] = field(default_factory=_pauses_par_defaut)
    # Réglages particuliers par jour de la semaine (0 = lundi).
    reglages_jour: dict[int, ReglageJour] = field(default_factory=dict)
    # Le moteur choisit d'abord les plages préférées et n'utilise les plages
    # évitées qu'en dernier recours.
    plages_preferees: list[PlageHebdo] = field(default_factory=list)
    plages_evitees: list[PlageHebdo] = field(default_factory=list)
    # Plages garanties : remplies de séances dès qu'elles sont libres (seuls les
    # activités fixes, épreuves, pauses et le sommeil passent avant), même au-delà
    # du budget de révisions et de la limite du jour.
    plages_garanties: list[PlageHebdo] = field(default_factory=_plages_garanties_par_defaut)
    marge_echeance_heures: int = 12
    horizon_semaines: int = 3
    # Révisions régulières : temps visé par semaine, placé seulement s'il
    # reste de la place une fois les échéances servies.
    minutes_revision_semaine: int = 300
    # Avant une épreuve : aucune séance dans les heures qui précèdent, et une
    # charge réduite le jour même.
    repos_avant_epreuve_min: int = 180
    max_minutes_jour_epreuve: int = 120
    # Après une épreuve, plus aucune séance jusqu'au lendemain (soirée libre).
    libre_apres_epreuve: bool = True

    def __post_init__(self) -> None:
        if self.minutes_revision_semaine < 0:
            raise ValueError("Le temps de révision ne peut pas être négatif")
        if self.repos_avant_epreuve_min < 0 or self.max_minutes_jour_epreuve < 0:
            raise ValueError("Repos ou limite du jour d'épreuve invalide")
        if not 0 < self.duree_min_seance <= self.duree_max_seance:
            raise ValueError("Durées de séance incohérentes")
        _ordre(self.debut_journee, self.fin_journee)
        if self.pause_min < 0 or self.max_minutes_jour <= 0:
            raise ValueError("Pause ou limite quotidienne invalide")
        if any(not 0 <= j <= 6 for j in self.reglages_jour):
            raise ValueError("Les jours vont de 0 (lundi) à 6 (dimanche)")

    def jour(self, jour_semaine: int) -> ReglageJour:
        """Réglage effectif d'un jour : particulier s'il existe, sinon général."""
        if jour_semaine in self.reglages_jour:
            return self.reglages_jour[jour_semaine]
        return ReglageJour(
            debut=self.debut_journee,
            fin=self.fin_journee,
            max_minutes=self.max_minutes_jour,
            pauses=list(self.pauses_quotidiennes),
        )
