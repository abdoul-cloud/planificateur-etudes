"""Import d'un emploi du temps depuis une image ou un PDF, lu par Gemini.

Gemini renvoie une liste de cours au format JSON imposé ; rien n'est
enregistré ici : l'utilisateur vérifie et corrige chaque proposition avant
de l'ajouter.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

from .. import modeles as m
from .gemini import ClientGemini, ErreurGemini, bloc_fichier, bloc_texte, json_de

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TYPES = {"cours": m.TypeActivite.COURS, "td": m.TypeActivite.TD, "tp": m.TypeActivite.TP,
         "autre": m.TypeActivite.AUTRE}

SCHEMA = {
    "type": "object",
    "properties": {
        "cours": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Intitulé tel qu'écrit sur le document"},
                    "matiere": {"type": "string", "description": "Matière correspondante parmi la liste fournie, ou vide"},
                    "type": {"type": "string", "enum": ["cours", "td", "tp", "autre"]},
                    "chaque_semaine": {"type": "boolean", "description": "Vrai si le cours revient chaque semaine"},
                    "jour": {"type": "string", "enum": JOURS},
                    "date": {"type": "string", "description": "AAAA-MM-JJ si le cours a lieu à une date précise"},
                    "debut": {"type": "string", "description": "Heure de début HH:MM"},
                    "fin": {"type": "string", "description": "Heure de fin HH:MM"},
                },
                "required": ["nom", "type", "chaque_semaine", "debut", "fin"],
            },
        }
    },
    "required": ["cours"],
}


@dataclass
class Proposition:
    nom: str
    type: m.TypeActivite
    debut: time
    fin: time
    jour_semaine: int | None
    date: date | None
    matiere_id: int | None

    def activite(self) -> m.ActiviteFixe:
        return m.ActiviteFixe(
            nom=self.nom, heure_debut=self.debut, heure_fin=self.fin, type=self.type,
            jour_semaine=self.jour_semaine if self.date is None else None,
            date=self.date, matiere_id=self.matiere_id,
        )


def consigne(matieres: list[m.Matiere], reference: date, remarque: str = "") -> str:
    noms = ", ".join(f"« {x.nom} »" for x in matieres if not x.terminee) or "(aucune encore)"
    return (
        "Voici l'emploi du temps d'un étudiant (image ou PDF). Liste chaque cours, TD, TP ou activité "
        "à horaire fixe qui y figure.\n"
        f"- Matières de l'étudiant : {noms}. Pour chaque cours, indique dans « matiere » le nom exact de "
        "la matière correspondante dans cette liste (même si l'intitulé est abrégé), ou laisse vide si "
        "aucune ne correspond.\n"
        "- Si le document est un emploi du temps type qui se répète, mets « chaque_semaine » à vrai et "
        "donne le « jour ». S'il porte des dates précises, mets « chaque_semaine » à faux et donne la "
        f"« date » (AAAA-MM-JJ ; nous sommes le {reference.isoformat()}, déduis l'année si besoin).\n"
        "- Heures au format HH:MM sur 24 h. N'invente rien : ignore ce qui est illisible.\n"
        "- Les pauses, repas et cases vides ne sont pas des cours."
        + (f"\n- Remarque de l'étudiant à respecter : {remarque.strip()}" if remarque.strip() else "")
    )


def extraire(client: ClientGemini, fichier: Path, matieres: list[m.Matiere],
             reference: date | None = None, remarque: str = "") -> list[Proposition]:
    reference = reference or date.today()
    reponse = client.interagir([bloc_fichier(fichier), bloc_texte(consigne(matieres, reference, remarque))],
                               schema=SCHEMA)
    donnees = json_de(reponse.texte) if reponse.texte else {}
    propositions = interpreter(donnees, matieres)
    if not propositions:
        raise ErreurGemini("Aucun cours n'a été reconnu dans ce document. Essayez une image plus nette ou un PDF.")
    return propositions


# --- Interprétation ------------------------------------------------------------


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9/ ]+", " ", texte).strip()


def associer_matiere(texte: str, matieres: list[m.Matiere]) -> int | None:
    """Matière la plus probable pour un intitulé, abréviations comprises (« Trait. signal »)."""
    cible = _normaliser(texte or "")
    if not cible:
        return None
    candidates = [x for x in matieres if not x.terminee] or matieres
    for x in candidates:
        if _normaliser(x.nom) == cible:
            return x.id
    for x in candidates:
        nom = _normaliser(x.nom)
        if nom and (nom in cible or cible in nom):
            return x.id
    generiques = {"de", "du", "des", "la", "le", "les", "et", "en", "tp", "td", "cm", "cours", "seance", "ds"}
    mots = [w for w in cible.split() if len(w) > 1 and w not in generiques]
    for x in candidates:
        mots_nom = _normaliser(x.nom).split()
        if mots and all(any(n.startswith(w) or w.startswith(n) for n in mots_nom) for w in mots):
            return x.id
    return None


def lire_heure(texte: str) -> time | None:
    resultat = re.match(r"^\s*(\d{1,2})\s*[:hH.]\s*(\d{2})?\s*$", str(texte or ""))
    if not resultat:
        return None
    heures, minutes = int(resultat.group(1)), int(resultat.group(2) or 0)
    if not (0 <= heures <= 23 and 0 <= minutes <= 59):
        return None
    return time(heures, minutes)


def interpreter(donnees, matieres: list[m.Matiere]) -> list[Proposition]:
    cours = donnees.get("cours", []) if isinstance(donnees, dict) else donnees if isinstance(donnees, list) else []
    propositions = []
    for c in cours:
        if not isinstance(c, dict):
            continue
        nom = str(c.get("nom", "")).strip()
        debut, fin = lire_heure(c.get("debut")), lire_heure(c.get("fin"))
        if not nom or debut is None or fin is None or fin <= debut:
            continue
        jour = _normaliser(str(c.get("jour", "")))
        jour_semaine = JOURS.index(jour) if jour in JOURS else None
        le_jour = None
        if not c.get("chaque_semaine") and c.get("date"):
            try:
                le_jour = date.fromisoformat(str(c["date"])[:10])
            except ValueError:
                le_jour = None
        if le_jour is None and jour_semaine is None:
            continue
        if le_jour is not None:
            jour_semaine = le_jour.weekday()
        matiere_id = associer_matiere(str(c.get("matiere", "")), matieres) or associer_matiere(nom, matieres)
        propositions.append(Proposition(nom, TYPES.get(str(c.get("type", "cours")).lower(), m.TypeActivite.COURS),
                                        debut, fin, jour_semaine, le_jour, matiere_id))
    return sorted(propositions, key=lambda p: (p.date or date.min, p.jour_semaine or 0, p.debut))
