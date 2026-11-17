"""Export vers un agenda (Google Agenda, Outlook, Agenda du téléphone…) au format iCalendar (.ics).

Entièrement hors ligne : on écrit un fichier, que l'utilisateur importe lui-même dans son agenda.
Chaque événement garde un identifiant stable : réimporter après une replanification met à jour
les séances au lieu de les dupliquer (dans les agendas qui le permettent, comme Outlook).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import modeles as m
from .base import Base

PRODUIT = "-//Planificateur d'etudes//FR"
DOMAINE = "planificateur-etudes"

TYPES_SEANCE = {
    m.TypeSeance.REVISION: "Révision",
    m.TypeSeance.PREPARATION: "Préparation",
    m.TypeSeance.TRAVAIL: "Travail à rendre",
}
TYPES_EPREUVE = {
    m.TypeEpreuve.INTERROGATION: "Interrogation",
    m.TypeEpreuve.DEVOIR_SURVEILLE: "Devoir surveillé",
    m.TypeEpreuve.COMPOSITION: "Composition",
    m.TypeEpreuve.EXAMEN: "Examen",
}


def echapper(texte: str) -> str:
    return (texte.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def plier(ligne: str) -> str:
    """Lignes de 75 octets au plus (RFC 5545), sans couper un caractère accentué."""
    morceaux, courant, taille = [], "", 0
    for caractere in ligne:
        octets = len(caractere.encode("utf-8"))
        limite = 75 if not morceaux else 74  # les suites commencent par une espace
        if taille + octets > limite:
            morceaux.append(courant)
            courant, taille = "", 0
        courant += caractere
        taille += octets
    morceaux.append(courant)
    return "\r\n ".join(morceaux)


def _heure(instant: datetime) -> str:
    return instant.strftime("%Y%m%dT%H%M%S")  # heure locale « flottante » : celle de l'agenda


def _evenement(uid: str, debut: datetime, fin: datetime, titre: str, description: str,
               horodatage: str, categorie: str, alarme_min: int | None = None) -> list[str]:
    lignes = [
        "BEGIN:VEVENT",
        f"UID:{uid}@{DOMAINE}",
        f"DTSTAMP:{horodatage}",
        f"DTSTART:{_heure(debut)}",
        f"DTEND:{_heure(fin)}",
        f"SUMMARY:{echapper(titre)}",
        f"CATEGORIES:{echapper(categorie)}",
        "TRANSP:OPAQUE",
    ]
    if description:
        lignes.append(f"DESCRIPTION:{echapper(description)}")
    if alarme_min:
        lignes += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{echapper(titre)}",
                   f"TRIGGER:-PT{alarme_min}M", "END:VALARM"]
    lignes.append("END:VEVENT")
    return lignes


def generer_ics(base: Base, du: date, au: date, maintenant: datetime | None = None,
                avec_alarmes: bool = True) -> tuple[str, int]:
    """Texte du calendrier et nombre d'événements, du jour `du` au jour `au` inclus."""
    maintenant = maintenant or datetime.now()
    horodatage = maintenant.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debut_periode = datetime.combine(du, datetime.min.time())
    fin_periode = datetime.combine(au + timedelta(days=1), datetime.min.time())
    matieres = {x.id: x for x in base.matieres.lister()}
    epreuves = {e.id: e for e in base.epreuves.lister()}
    travaux = {t.id: t for t in base.travaux.lister()}

    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODUIT}", "CALSCALE:GREGORIAN",
              "METHOD:PUBLISH", "X-WR-CALNAME:Planning de révision"]
    nombre = 0
    for s in sorted(base.seances.lister(), key=lambda s: s.debut):
        if not (debut_periode <= s.debut < fin_periode):
            continue
        if s.statut in (m.StatutSeance.MANQUEE, m.StatutSeance.REPORTEE):
            continue  # remplacée par une autre séance
        matiere = matieres.get(s.matiere_id)
        nom = matiere.nom if matiere else "Travail"
        details = []
        if s.type is m.TypeSeance.PREPARATION and s.epreuve_id in epreuves:
            e = epreuves[s.epreuve_id]
            details.append(f"Prépare : {TYPES_EPREUVE.get(e.type, 'épreuve')} du {e.debut:%d/%m à %H:%M}")
        if s.type is m.TypeSeance.TRAVAIL and s.travail_id in travaux:
            t = travaux[s.travail_id]
            details.append(f"{t.intitule} — à rendre le {t.echeance:%d/%m à %H:%M}")
        if s.statut is m.StatutSeance.TERMINEE:
            details.append("✓ Faite")
        details.append("Créé par le Planificateur d'études")
        lignes += _evenement(f"seance-{s.id}", s.debut, s.fin, f"{TYPES_SEANCE[s.type]} · {nom}",
                             "\n".join(details), horodatage, "Révision",
                             10 if avec_alarmes and s.statut is m.StatutSeance.PREVUE else None)
        nombre += 1
    for e in sorted(epreuves.values(), key=lambda e: e.debut):
        if not (debut_periode <= e.debut < fin_periode):
            continue
        matiere = matieres.get(e.matiere_id)
        titre = f"{TYPES_EPREUVE.get(e.type, 'Épreuve')} · {matiere.nom if matiere else ''}".rstrip(" ·")
        description = "\n".join(x for x in (e.intitule, f"Chapitres : {e.chapitres}" if e.chapitres else "") if x)
        lignes += _evenement(f"epreuve-{e.id}", e.debut, e.fin, f"⚑ {titre}", description, horodatage,
                             "Épreuve", 60 if avec_alarmes else None)
        nombre += 1
    lignes.append("END:VCALENDAR")
    return "\r\n".join(plier(l) for l in lignes) + "\r\n", nombre


def exporter_ics(base: Base, du: date, au: date, chemin: Path | str, **options) -> int:
    texte, nombre = generer_ics(base, du, au, **options)
    Path(chemin).write_bytes(texte.encode("utf-8"))
    return nombre
