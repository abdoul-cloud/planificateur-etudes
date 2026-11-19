"""Import d'un calendrier d'épreuves (examens, devoirs surveillés…) depuis une image ou un PDF, lu par Gemini.

Comme pour l'emploi du temps : rien n'est enregistré ici, l'étudiant vérifie chaque épreuve avant l'ajout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from .. import modeles as m
from .gemini import ClientGemini, ErreurGemini, bloc_fichier, bloc_texte, json_de
from .import_edt import associer_matiere, lire_heure

TYPES = {
    "interrogation": m.TypeEpreuve.INTERROGATION,
    "devoir_surveille": m.TypeEpreuve.DEVOIR_SURVEILLE,
    "composition": m.TypeEpreuve.COMPOSITION,
    "examen": m.TypeEpreuve.EXAMEN,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "epreuves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intitule": {"type": "string", "description": "Intitulé tel qu'écrit (matière, épreuve)"},
                    "matiere": {"type": "string", "description": "Matière correspondante parmi la liste fournie, ou vide"},
                    "type": {"type": "string", "enum": list(TYPES)},
                    "date": {"type": "string", "description": "AAAA-MM-JJ"},
                    "debut": {"type": "string", "description": "Heure de début HH:MM, vide si inconnue"},
                    "fin": {"type": "string", "description": "Heure de fin HH:MM, vide si inconnue"},
                    "duree_minutes": {"type": "integer", "description": "Durée si seule la durée est indiquée"},
                    "salle": {"type": "string"},
                    "chapitres": {"type": "string", "description": "Chapitres ou programme indiqués, sinon vide"},
                },
                "required": ["intitule", "type", "date"],
            },
        }
    },
    "required": ["epreuves"],
}

HEURE_PAR_DEFAUT = time(8, 0)
DUREE_PAR_DEFAUT = 120


@dataclass
class PropositionEpreuve:
    intitule: str
    matiere_id: int | None
    type: m.TypeEpreuve
    jour: date
    debut: time
    fin: time
    heure_devinee: bool = False  # heure absente du document : à vérifier
    chapitres: str = ""

    def epreuve(self) -> m.Epreuve:
        return m.Epreuve(self.matiere_id, datetime.combine(self.jour, self.debut), datetime.combine(self.jour, self.fin),
                         type=self.type, intitule=self.intitule, chapitres=self.chapitres)


def consigne(matieres: list[m.Matiere], reference: date, remarque: str = "") -> str:
    noms = ", ".join(f"« {x.nom} »" for x in matieres if not x.terminee) or "(aucune encore)"
    return (
        "Voici un calendrier d'épreuves d'un étudiant (examens, compositions, devoirs surveillés, "
        "interrogations), en image ou PDF. Liste chaque épreuve qui y figure.\n"
        f"- Matières de l'étudiant : {noms}. Indique dans « matiere » le nom exact de la matière "
        "correspondante dans cette liste (même si l'intitulé est abrégé), ou laisse vide.\n"
        "- « type » : examen (session d'examens, partiel), composition, devoir_surveille (DS) ou "
        "interrogation (interro, test court).\n"
        f"- « date » au format AAAA-MM-JJ (nous sommes le {reference.isoformat()} : déduis l'année si besoin). "
        "Heures HH:MM sur 24 h ; si seule la durée est donnée, remplis « duree_minutes ».\n"
        "- N'invente rien : laisse vide ce qui n'est pas écrit, ignore ce qui est illisible."
        + (f"\n- Remarque de l'étudiant à respecter : {remarque.strip()}" if remarque.strip() else "")
    )


def extraire_epreuves(client: ClientGemini, fichier: Path, matieres: list[m.Matiere],
                      reference: date | None = None, remarque: str = "") -> list[PropositionEpreuve]:
    reference = reference or date.today()
    reponse = client.interagir([bloc_fichier(fichier), bloc_texte(consigne(matieres, reference, remarque))],
                               schema=SCHEMA)
    donnees = json_de(reponse.texte) if reponse.texte else {}
    propositions = interpreter(donnees, matieres)
    if not propositions:
        raise ErreurGemini("Aucune épreuve datée n'a été reconnue dans ce document. "
                           "Essayez une image plus nette ou un PDF.")
    return propositions


def interpreter(donnees, matieres: list[m.Matiere]) -> list[PropositionEpreuve]:
    liste = donnees.get("epreuves", []) if isinstance(donnees, dict) else donnees if isinstance(donnees, list) else []
    propositions = []
    for e in liste:
        if not isinstance(e, dict):
            continue
        try:
            jour = date.fromisoformat(str(e.get("date", ""))[:10])
        except ValueError:
            continue  # une épreuve sans date ne peut pas être planifiée
        intitule = str(e.get("intitule", "")).strip()
        debut, fin = lire_heure(e.get("debut")), lire_heure(e.get("fin"))
        devinee = debut is None
        debut = debut or HEURE_PAR_DEFAUT
        if fin is None or fin <= debut:
            try:
                duree = int(e.get("duree_minutes") or DUREE_PAR_DEFAUT)
            except (TypeError, ValueError):
                duree = DUREE_PAR_DEFAUT
            minutes = min(debut.hour * 60 + debut.minute + max(15, duree), 23 * 60 + 59)
            fin = time(minutes // 60, minutes % 60)
            devinee = devinee or e.get("fin") in (None, "") and not e.get("duree_minutes")
        matiere_id = associer_matiere(str(e.get("matiere", "")), matieres) or associer_matiere(intitule, matieres)
        chapitres = str(e.get("chapitres") or "").strip()
        salle = str(e.get("salle") or "").strip()
        if salle:
            chapitres = (chapitres + " · " if chapitres else "") + f"Salle {salle}"
        propositions.append(PropositionEpreuve(
            intitule, matiere_id, TYPES.get(str(e.get("type", "")).lower(), m.TypeEpreuve.EXAMEN),
            jour, debut, fin, bool(devinee), chapitres))
    return sorted(propositions, key=lambda p: (p.jour, p.debut))
