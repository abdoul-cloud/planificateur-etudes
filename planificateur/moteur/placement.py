"""Placement des séances (cahier des charges, sections 6.1 à 6.6).

Déroulement :
1. On garde les séances existantes qu'il ne faut pas toucher (terminées,
   verrouillées, modifiées à la main, passées) ; les autres séances
   automatiques prévues sont retirées et recalculées.
2. On calcule les créneaux libres (étape 2).
3. On sert les échéances — préparations d'épreuves et travaux à rendre — par
   ordre d'échéance, la plus proche d'abord.
   Aucune séance juste avant une épreuve ni après elle le même jour, charge
   réduite le jour même, et
   à préférence égale on choisit le jour le moins chargé.
   Les plages garanties (par défaut 20 h – 23 h du lundi au vendredi) sont
   choisies en premier.
4. Les plages garanties encore libres sont remplies : d'abord avec ce qui
   manque aux échéances, puis avec des révisions, même au-delà du budget.
   Ensuite, du lundi au vendredi, chaque autre moment libre reçoit des
   séances espacées (sans entasser). Une révision de cours se place de préférence
   la veille du cours, sinon l'avant-veille.
5. S'il reste de la place sous la limite de chaque jour, on ajoute les
   révisions régulières, dans la limite du budget hebdomadaire.
6. Ce qui ne tient pas est renvoyé dans `non_places`, avec les minutes
   manquantes : rien n'est entassé au-delà des limites.

Ce sont des règles pratiques, simples et réglables, pas une vérité
scientifique ni un optimum garanti.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..modeles import (
    ActiviteFixe,
    Epreuve,
    EtatEpreuve,
    EtatTravail,
    ExceptionActivite,
    Matiere,
    Origine,
    Preferences,
    Seance,
    StatutSeance,
    Travail,
    TypeSeance,
)
from .creneaux import (
    GRILLE_MIN,
    Intervalle,
    arrondir_grille,
    creneaux_libres,
    niveau_preference,
    occurrences,
    periodes_occupees,
)

PREPARATION_BASE_MIN = 120  # épreuve moyenne, peu préparée → ~3 h 30
PREPARATION_MIN = 60
PREPARATION_MAX = 480


# --------------------------------------------------------------------------
# Règles de calcul
# --------------------------------------------------------------------------


def _minutes_grille(minutes: float, vers_le_haut: bool = True) -> int:
    arrondi = math.ceil if vers_le_haut else math.floor
    return int(arrondi(minutes / GRILLE_MIN) * GRILLE_MIN)


def minutes_preparation(epreuve: Epreuve) -> int:
    """Temps de préparation visé pour une épreuve.

    Valeur saisie par l'utilisateur si elle existe ; sinon 2 h multipliées par
    l'importance, la difficulté et le manque de préparation (3 = neutre),
    bornées entre 1 h et 8 h.
    """
    if epreuve.minutes_preparation is not None:
        return epreuve.minutes_preparation
    facteur = (
        (epreuve.importance / 3)
        * (epreuve.difficulte / 3)
        * ((6 - epreuve.preparation) / 3)
    )
    estime = _minutes_grille(PREPARATION_BASE_MIN * facteur)
    return min(PREPARATION_MAX, max(PREPARATION_MIN, estime))


def poids_matiere(matiere: Matiere) -> float:
    """Priorité d'une matière pour les révisions régulières.

    coefficient × difficulté × (6 − maîtrise) : une matière bien maîtrisée
    reçoit moins de temps, même si son coefficient est élevé.
    """
    return matiere.coefficient * matiere.difficulte * (6 - matiere.maitrise)


def repartir_revisions(nombre: int, matieres: list[Matiere]) -> dict[int, int]:
    """Répartit `nombre` séances entre les matières selon leur poids.

    Méthode des plus forts quotients : chaque séance va à la matière dont
    poids / (séances déjà attribuées + 1) est le plus grand.
    """
    compte = {m.id: 0 for m in matieres}
    for _ in range(nombre):
        choisie = max(matieres, key=lambda m: poids_matiere(m) / (compte[m.id] + 1))
        compte[choisie.id] += 1
    return compte


# --------------------------------------------------------------------------
# Résultat
# --------------------------------------------------------------------------


@dataclass
class Deficit:
    """Travail qui n'a pas pu être placé."""

    type: TypeSeance
    reference_id: int | None  # épreuve, travail, ou matière pour une révision
    intitule: str
    minutes: int
    echeance: datetime | None = None
    en_retard: bool = False  # échéance déjà dépassée


@dataclass
class Resultat:
    seances: list[Seance]  # nouvelles séances générées
    conservees: list[Seance]  # séances existantes gardées telles quelles
    retirees: list[Seance]  # anciennes séances automatiques remplacées
    non_places: list[Deficit]
    # Séances gardées (manuelles, verrouillées) qui chevauchent désormais une
    # activité fixe ou une épreuve : à signaler, jamais déplacées en silence.
    conflits: list[Seance] = field(default_factory=list)

    @property
    def faisable(self) -> bool:
        """Vrai si toutes les échéances sont couvertes (révisions exclues)."""
        return not any(d.type is not TypeSeance.REVISION for d in self.non_places)

    def charge_par_jour(self) -> dict[date, int]:
        charge: dict[date, int] = defaultdict(int)
        for s in [*self.conservees, *self.seances]:
            if s.statut in _STATUTS_COMPTES:
                charge[s.debut.date()] += s.minutes
        return dict(charge)


_STATUTS_COMPTES = (StatutSeance.PREVUE, StatutSeance.TERMINEE, StatutSeance.PARTIELLE)


# --------------------------------------------------------------------------
# Mécanique de placement
# --------------------------------------------------------------------------


@dataclass
class _Besoin:
    type: TypeSeance
    reference_id: int
    matiere_id: int
    intitule: str
    echeance: datetime  # aucune séance ne doit finir après
    minutes: int
    importance: int
    jours_utilises: set[date] = field(default_factory=set)
    anticipe: bool = False  # échéance juste après la période : préparée dès maintenant, sans alerte de manque


ANTICIPATION = timedelta(days=7)  # échéances jusqu'à 7 jours après la période : leur préparation commence avant


class _Agenda:
    """Créneaux encore libres et charge de chaque jour."""

    def __init__(
        self, preferences: Preferences, libres: list[Intervalle], jours_epreuve: set[date]
    ) -> None:
        self.p = preferences
        self.libres = list(libres)
        self.jours_epreuve = jours_epreuve
        self.charge: dict[date, int] = defaultdict(int)
        self.nouvelles: list[Seance] = []

    def occuper(self, seance: Seance) -> None:
        if seance.statut in _STATUTS_COMPTES:
            self.charge[seance.debut.date()] += seance.minutes
        pause = timedelta(minutes=self.p.pause_min)
        self.bloquer(Intervalle(seance.debut - pause, seance.fin + pause))

    def bloquer(self, bloc: Intervalle) -> None:
        """Retire une période des créneaux libres."""
        restants = []
        for libre in self.libres:
            if not libre.chevauche(bloc):
                restants.append(libre)
                continue
            if libre.debut < bloc.debut:
                restants.append(Intervalle(libre.debut, bloc.debut))
            if bloc.fin < libre.fin:
                restants.append(Intervalle(bloc.fin, libre.fin))
        self.libres = restants

    def limite_du_jour(self, jour: date) -> int:
        limite = self.p.jour(jour.weekday()).max_minutes
        if jour in self.jours_epreuve:
            limite = min(limite, self.p.max_minutes_jour_epreuve)
        return limite

    def reste_du_jour(self, jour: date) -> int:
        return self.limite_du_jour(jour) - self.charge[jour]

    def duree(self, a_faire: int, place: int) -> int:
        """Durée de la prochaine séance, ou 0 si elle ne tient pas."""
        p = self.p
        a_faire = _minutes_grille(a_faire)
        place = _minutes_grille(place, vers_le_haut=False)
        if a_faire <= p.duree_min_seance:  # dernier petit morceau
            return a_faire if place >= a_faire else 0
        duree = min(a_faire, p.duree_max_seance, place)
        if duree < p.duree_min_seance:
            return 0
        # Éviter de laisser un reste plus court qu'une séance minimale.
        reste = a_faire - duree
        if 0 < reste < p.duree_min_seance and a_faire - p.duree_min_seance >= p.duree_min_seance:
            duree = min(duree, a_faire - p.duree_min_seance)
        return duree

    def _departs(self, libre: Intervalle) -> list[datetime]:
        """Débuts de séance à essayer dans un créneau libre.

        Le début du créneau, mais aussi le début de chaque plage garantie ou
        préférée qui tombe dedans, et la fin de chaque plage à éviter : sans
        cela, une plage de 20 h dans un créneau libre de 19 h à 23 h ne serait
        jamais choisie.
        """
        jour = libre.debut.date()
        departs = {libre.debut}
        for plage in [*self.p.plages_garanties, *self.p.plages_preferees]:
            if jour.weekday() in plage.jours:
                instant = datetime.combine(jour, plage.debut)
                if libre.debut < instant < libre.fin:
                    departs.add(instant)
        for plage in self.p.plages_evitees:
            if jour.weekday() in plage.jours:
                instant = datetime.combine(jour, plage.fin)
                if libre.debut < instant < libre.fin:
                    departs.add(instant)
        return sorted(departs)

    def candidats(self, a_faire: int, avant: datetime, apres: datetime | None = None):
        """Séances possibles dans les créneaux libres (plusieurs débuts par créneau)."""
        for libre in self.libres:
            for depart in self._departs(libre):
                debut = arrondir_grille(depart, vers_le_haut=True)
                if apres is not None:
                    debut = max(debut, arrondir_grille(apres, vers_le_haut=True))
                fin = min(libre.fin, avant)
                if fin <= debut:
                    continue
                place = min(int((fin - debut).total_seconds() // 60), self.reste_du_jour(debut.date()))
                duree = self.duree(a_faire, place)
                if duree:
                    yield Intervalle(debut, debut + timedelta(minutes=duree))

    def placer(self, creneau: Intervalle, **attributs) -> Seance:
        seance = Seance(debut=creneau.debut, fin=creneau.fin, origine=Origine.AUTO, **attributs)
        self.nouvelles.append(seance)
        self.occuper(seance)
        return seance


def _placer_besoin(agenda: _Agenda, besoin: _Besoin) -> int:
    """Place le besoin ; renvoie les minutes qui n'ont pas pu l'être."""
    cible = {"epreuve_id" if besoin.type is TypeSeance.PREPARATION else "travail_id": besoin.reference_id}
    while besoin.minutes > 0:
        meilleur = None
        for c in agenda.candidats(besoin.minutes, besoin.echeance):
            jour = c.debut.date()
            cle = (
                jour in besoin.jours_utilises,  # 1) un seul passage par jour si possible
                -niveau_preference(c, agenda.p),  # 2) plages préférées, évitées en dernier
                agenda.charge[jour],  # 3) le jour le moins chargé
                -jour.toordinal(),  # 4) à égalité, au plus près de l'échéance
                c.debut,  # 5) le plus tôt dans la journée
            )
            if meilleur is None or cle < meilleur[0]:
                meilleur = (cle, c)
        if meilleur is None:
            return besoin.minutes
        seance = agenda.placer(meilleur[1], type=besoin.type, matiere_id=besoin.matiere_id, **cible)
        besoin.minutes -= seance.minutes
        besoin.jours_utilises.add(seance.debut.date())
    return 0


def _matiere_de(activite: ActiviteFixe, matieres: list[Matiere]) -> int | None:
    """Matière d'une activité : celle choisie, sinon celle dont le nom correspond."""
    if activite.matiere_id is not None:
        return activite.matiere_id
    nom = activite.nom.strip().lower()
    for matiere in matieres:
        autre = matiere.nom.strip().lower()
        if autre and (autre in nom or nom in autre):
            return matiere.id
    return None


def _jours_favorables(
    matieres: list[Matiere], activites: list[ActiviteFixe], exceptions: list[ExceptionActivite], du: date, au: date
) -> dict[int, dict[date, int]]:
    """Pour chaque matière, les bons jours pour la réviser : 2 la veille d'un cours, 1 l'avant-veille.

    On révise avant le cours, pour y arriver préparé : un cours du vendredi se
    révise de préférence le jeudi, sinon le mercredi.
    """
    favorables: dict[int, dict[date, int]] = defaultdict(dict)
    for activite, horaire in occurrences(activites, du, au + timedelta(days=2), exceptions):
        matiere_id = _matiere_de(activite, matieres)
        if matiere_id is None:
            continue
        jour_du_cours = horaire.debut.date()
        for ecart, score in ((1, 2), (2, 1)):
            jour = jour_du_cours - timedelta(days=ecart)
            favorables[matiere_id][jour] = max(favorables[matiere_id].get(jour, 0), score)
    return favorables


def _choisir_matiere(matieres, jour: date, favorables, compte, deja_ce_jour: set[int]) -> Matiere:
    """Matière à réviser : variée dans la journée, puis la veille / l'avant-veille du cours, puis selon le poids."""
    return max(
        matieres,
        key=lambda m: (
            m.id not in deja_ce_jour,
            favorables.get(m.id, {}).get(jour, 0),
            poids_matiere(m) / (compte[m.id] + 1),
        ),
    )


def _placer_contenu(agenda, creneau: Intervalle, besoins, matieres, favorables, compte) -> None:
    """Met dans `creneau` ce qui manque à une échéance, sinon une révision."""
    jour = creneau.debut.date()
    besoin = next((b for b in besoins if b.minutes > 0 and b.echeance >= creneau.fin), None)
    if besoin is not None:
        duree = min(creneau.minutes, _minutes_grille(besoin.minutes))
        creneau = Intervalle(creneau.debut, creneau.debut + timedelta(minutes=duree))
        cible = {"epreuve_id" if besoin.type is TypeSeance.PREPARATION else "travail_id": besoin.reference_id}
        seance = agenda.placer(creneau, type=besoin.type, matiere_id=besoin.matiere_id, **cible)
        besoin.minutes = max(0, besoin.minutes - seance.minutes)
        besoin.jours_utilises.add(jour)
        return
    if not matieres:
        agenda.bloquer(creneau)  # rien à réviser : le moment reste libre
        return
    deja = {s.matiere_id for s in agenda.nouvelles if s.type is TypeSeance.REVISION and s.debut.date() == jour}
    matiere = _choisir_matiere(matieres, jour, favorables, compte, deja)
    agenda.placer(creneau, type=TypeSeance.REVISION, matiere_id=matiere.id)
    compte[matiere.id] += 1


def _placer_revisions(agenda: _Agenda, matieres: list[Matiere], du: date, au: date, favorables) -> list[Deficit]:
    """Révisions du budget hebdomadaire qui restent après les plages garanties et les moments libres."""
    p = agenda.p
    if p.minutes_revision_semaine <= 0 or not matieres:
        return []

    manques: dict[int, int] = defaultdict(int)
    duree = p.duree_min_seance
    debut_semaine = du
    while debut_semaine <= au:
        fin_semaine = min(au, debut_semaine + timedelta(days=6))
        jours = (fin_semaine - debut_semaine).days + 1
        budget = int(p.minutes_revision_semaine * jours / 7)
        deja = sum(
            s.minutes for s in agenda.nouvelles
            if s.type is TypeSeance.REVISION and debut_semaine <= s.debut.date() <= fin_semaine
        )
        nombre = max(0, budget - deja) // duree
        repartition = repartir_revisions(nombre, matieres)
        limite = datetime.combine(fin_semaine + timedelta(days=1), time.min)
        apres = datetime.combine(debut_semaine, time.min)

        for matiere in sorted(matieres, key=poids_matiere, reverse=True):
            jours_matiere: set[date] = set()
            bons_jours = favorables.get(matiere.id, {})
            for _ in range(repartition[matiere.id]):
                meilleur = None
                for c in agenda.candidats(duree, limite, apres):
                    jour = c.debut.date()
                    cle = (
                        jour in jours_matiere,  # 1) une révision par jour et par matière
                        -bons_jours.get(jour, 0),  # 2) la veille du cours, sinon l'avant-veille
                        -niveau_preference(c, p),  # 3) plages préférées
                        agenda.charge[jour],  # 4) le jour le moins chargé
                        jour,  # 5) le plus tôt dans la semaine
                        c.debut,
                    )
                    if meilleur is None or cle < meilleur[0]:
                        meilleur = (cle, c)
                if meilleur is None:
                    manques[matiere.id] += duree
                    continue
                seance = agenda.placer(meilleur[1], type=TypeSeance.REVISION, matiere_id=matiere.id)
                jours_matiere.add(seance.debut.date())
        debut_semaine = fin_semaine + timedelta(days=1)

    noms = {m.id: m.nom for m in matieres}
    return [
        Deficit(TypeSeance.REVISION, mid, f"Révision {noms[mid]}", minutes)
        for mid, minutes in manques.items()
    ]


def _decouper(minutes: int, p: Preferences) -> int:
    """Durée de la prochaine séance pour remplir `minutes` sans laisser un reste inutilisable."""
    if minutes <= p.duree_max_seance:
        return minutes
    # Deux séances au moins : on évite un reste plus court qu'une séance minimale.
    reste = minutes - p.duree_max_seance - p.pause_min
    if 0 < reste < p.duree_min_seance:
        return _minutes_grille((minutes - p.pause_min) / 2, vers_le_haut=False)
    return p.duree_max_seance


def _remplir_plages_garanties(agenda: _Agenda, besoins, matieres, favorables, compte, du: date, au: date,
                              maintenant: datetime) -> None:
    """Remplit entièrement chaque morceau libre des plages garanties.

    Priorité : le reste des échéances dont la date limite est après la séance,
    puis des révisions (la veille ou l'avant-veille du cours d'abord). La limite
    du jour et le budget de révisions ne s'appliquent pas ici : c'est le
    principe même d'une plage garantie.
    """
    p = agenda.p
    jour = du
    while jour <= au:
        for plage in p.plages_garanties:
            if jour.weekday() not in plage.jours:
                continue
            zone = Intervalle(datetime.combine(jour, plage.debut), datetime.combine(jour, plage.fin))
            while True:
                morceaux = [
                    Intervalle(arrondir_grille(max(l.debut, zone.debut), vers_le_haut=True), min(l.fin, zone.fin))
                    for l in agenda.libres
                    if l.chevauche(zone)
                ]
                morceaux = [x for x in morceaux if x.debut >= maintenant and x.minutes >= p.duree_min_seance]
                if not morceaux:
                    break
                morceau = min(morceaux)
                duree = _decouper(_minutes_grille(morceau.minutes, vers_le_haut=False), p)
                _placer_contenu(agenda, Intervalle(morceau.debut, morceau.debut + timedelta(minutes=duree)),
                                besoins, matieres, favorables, compte)
        jour += timedelta(days=1)


def _occuper_moments_libres(agenda: _Agenda, besoins, matieres, favorables, compte, du: date, au: date,
                            maintenant: datetime) -> None:
    """Occupe les moments libres des jours choisis (lundi → vendredi par défaut), sans entasser.

    Séance après séance, on prend le plus grand moment encore libre de la
    journée et on y pose une séance de la durée réglée (45 min par défaut),
    au milieu. Entre deux de ces séances, on garde une respiration d'au moins
    `remplissage_espace` minutes. On s'arrête à la limite de travail du jour :
    le matin et l'après-midi sont ainsi servis à parts égales.
    """
    p = agenda.p
    if not p.remplissage_jours:
        return
    longueur = max(p.remplissage_minutes, p.duree_min_seance)
    espace = timedelta(minutes=p.remplissage_espace)
    jour = du
    while jour <= au:
        if jour.weekday() in p.remplissage_jours:
            debut_jour = datetime.combine(jour, time.min)
            fin_jour = debut_jour + timedelta(days=1)
            ajoutees: list[Seance] = []
            ignores: set[tuple[datetime, datetime]] = set()  # moments où il n'y avait rien à mettre
            while agenda.reste_du_jour(jour) >= p.duree_min_seance:
                candidats = []
                for libre in agenda.libres:
                    if not debut_jour <= libre.debut < fin_jour or (libre.debut, libre.fin) in ignores:
                        continue
                    debut = arrondir_grille(max(libre.debut, maintenant), vers_le_haut=True)
                    fin = libre.fin
                    avant = [s.fin for s in ajoutees if s.fin <= libre.debut]
                    apres = [s.debut for s in ajoutees if s.debut >= libre.fin]
                    if avant:
                        debut = max(debut, arrondir_grille(max(avant) + espace, vers_le_haut=True))
                    if apres:
                        fin = min(fin, min(apres) - espace)
                    place = int((fin - debut).total_seconds() // 60)
                    if place >= p.duree_min_seance:
                        candidats.append((place, debut, libre))
                if not candidats:
                    break
                place, debut, libre = max(candidats, key=lambda c: (c[0], -c[1].timestamp()))
                duree = _minutes_grille(min(place, longueur, agenda.reste_du_jour(jour)), vers_le_haut=False)
                if duree < p.duree_min_seance:
                    break
                decalage = _minutes_grille((place - duree) / 2, vers_le_haut=False)
                creneau = Intervalle(debut + timedelta(minutes=decalage), debut + timedelta(minutes=decalage + duree))
                nombre = len(agenda.nouvelles)
                _placer_contenu(agenda, creneau, besoins, matieres, favorables, compte)
                if len(agenda.nouvelles) == nombre:
                    ignores.add((libre.debut, libre.fin))
                    continue
                ajoutees.append(agenda.nouvelles[-1])
        jour += timedelta(days=1)


def _a_conserver(seance: Seance, maintenant: datetime) -> bool:
    return (
        seance.verrouillee
        or seance.origine is Origine.MANUELLE
        or seance.statut is not StatutSeance.PREVUE
        or seance.debut < maintenant
    )


def _deja_fait(seance: Seance) -> int:
    """Minutes de préparation déjà acquises ou prévues par une séance gardée."""
    if seance.statut is StatutSeance.PREVUE:
        return seance.minutes
    if seance.statut is StatutSeance.TERMINEE:
        return seance.minutes_effectuees if seance.minutes_effectuees is not None else seance.minutes
    if seance.statut is StatutSeance.PARTIELLE:
        return seance.minutes_effectuees or 0
    return 0  # manquée ou reportée


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def planifier(
    du: date,
    au: date,
    preferences: Preferences,
    matieres: Iterable[Matiere] = (),
    activites: Iterable[ActiviteFixe] = (),
    exceptions: Iterable[ExceptionActivite] = (),
    epreuves: Iterable[Epreuve] = (),
    travaux: Iterable[Travail] = (),
    seances_existantes: Iterable[Seance] = (),
    maintenant: datetime | None = None,
) -> Resultat:
    """Génère les séances du `du` au `au` inclus.

    Seules les épreuves et les travaux dont l'échéance tombe dans cette
    période sont préparés : l'horizon (3 semaines par défaut) se règle dans
    les préférences.
    """
    matieres, activites, exceptions = list(matieres), list(activites), list(exceptions)
    # Une matière terminée ne reçoit plus de révisions (ses échéances restent servies).
    matieres = [x for x in matieres if not x.terminee]
    epreuves, travaux = list(epreuves), list(travaux)
    maintenant = maintenant or datetime.combine(du, time.min)
    fin_horizon = datetime.combine(au + timedelta(days=1), time.min)
    noms = {m.id: m.nom for m in matieres}

    existantes = list(seances_existantes)
    conservees = [s for s in existantes if _a_conserver(s, maintenant)]
    retirees = [s for s in existantes if not _a_conserver(s, maintenant)]

    libres = creneaux_libres(
        du, au, preferences, activites, exceptions, epreuves, conservees, a_partir_de=maintenant
    )
    jours_epreuve = {e.debut.date() for e in epreuves}
    agenda = _Agenda(preferences, libres, jours_epreuve)
    for s in conservees:
        agenda.occuper(s)
    repos = timedelta(minutes=preferences.repos_avant_epreuve_min)
    for e in epreuves:
        agenda.bloquer(Intervalle(e.debut - repos, e.debut))
        if preferences.libre_apres_epreuve:
            # Rien après l'épreuve jusqu'au lendemain, plages garanties comprises.
            agenda.bloquer(Intervalle(e.fin, datetime.combine(e.fin.date() + timedelta(days=1), time.min)))

    besoins: list[_Besoin] = []
    non_places: list[Deficit] = []

    fin_anticipation = fin_horizon + ANTICIPATION
    for e in epreuves:
        if e.etat is not EtatEpreuve.A_PREPARER or not maintenant < e.debut <= fin_anticipation:
            continue
        liees = [s for s in conservees if s.epreuve_id == e.id]
        intitule = e.intitule or f"{e.type.value.replace('_', ' ').capitalize()} de {noms.get(e.matiere_id, '?')}"
        besoins.append(
            _Besoin(
                TypeSeance.PREPARATION, e.id, e.matiere_id, intitule, e.debut,
                max(0, minutes_preparation(e) - sum(_deja_fait(s) for s in liees)),
                e.importance, {s.debut.date() for s in liees}, anticipe=e.debut > fin_horizon,
            )
        )

    for t in travaux:
        if t.etat in (EtatTravail.TERMINE, EtatTravail.RENDU) or not t.minutes_restantes:
            continue
        limite = t.date_cible or t.echeance - timedelta(hours=preferences.marge_echeance_heures)
        if limite <= maintenant:  # marge ou date cible dépassée : on vise l'échéance
            limite = t.echeance
        if limite > fin_anticipation:
            continue
        liees = [s for s in conservees if s.travail_id == t.id]
        # Prévues à venir, ou passées mais pas encore pointées (supposées faites
        # tant qu'elles ne sont pas marquées « manquées »).
        prevu = sum(s.minutes for s in liees if s.statut is StatutSeance.PREVUE)
        besoin = _Besoin(
            TypeSeance.TRAVAIL, t.id, t.matiere_id, t.intitule, limite,
            max(0, t.minutes_restantes - prevu), t.importance, {s.debut.date() for s in liees},
            anticipe=limite > fin_horizon,
        )
        if t.echeance <= maintenant:
            non_places.append(
                Deficit(TypeSeance.TRAVAIL, t.id, t.intitule, besoin.minutes, t.echeance, en_retard=True)
            )
            continue
        besoins.append(besoin)

    besoins.sort(key=lambda b: (b.echeance, -b.importance))
    for besoin in besoins:
        besoin.minutes = _placer_besoin(agenda, besoin)
    favorables = _jours_favorables(matieres, activites, exceptions, du, au)
    compte: dict[int, int] = defaultdict(int)  # révisions placées par matière, pour l'équilibre
    _remplir_plages_garanties(agenda, besoins, matieres, favorables, compte, du, au, maintenant)
    _occuper_moments_libres(agenda, besoins, matieres, favorables, compte, du, au, maintenant)
    for besoin in besoins:
        if besoin.minutes and not besoin.anticipe:  # le reste d'une échéance anticipée se fera la période suivante
            non_places.append(
                Deficit(besoin.type, besoin.reference_id, besoin.intitule, besoin.minutes, besoin.echeance)
            )

    non_places += _placer_revisions(agenda, matieres, du, au, favorables)

    occupes = periodes_occupees(du, au, activites, exceptions, epreuves)
    conflits = [
        s for s in conservees
        if s.statut is StatutSeance.PREVUE and s.fin > maintenant
        and any(Intervalle(s.debut, s.fin).chevauche(o) for o in occupes)
    ]

    return Resultat(
        seances=sorted(agenda.nouvelles, key=lambda s: s.debut),
        conservees=conservees,
        retirees=retirees,
        non_places=non_places,
        conflits=conflits,
    )
