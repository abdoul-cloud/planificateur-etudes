"""Historique des conversations avec l'assistant, enregistré sur cet ordinateur (comme dans les applis de chat).

Chaque conversation garde :
- les messages affichés (bulles de l'étudiant et de l'assistant, propositions et leur résultat) ;
- la mémoire envoyée à Gemini pour la suite de l'échange (avec les résultats des propositions).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .base import Base

LONGUEUR_TITRE = 48


@dataclass
class Message:
    qui: str  # « utilisateur », « assistant » ou « proposition »
    texte: str
    heure: str = ""  # HH:MM
    etat: str = ""  # pour une proposition : « proposee », « appliquee », « ignoree », « echec »


@dataclass
class Conversation:
    titre: str = "Nouvelle conversation"
    messages: list[Message] = field(default_factory=list)
    memoire: list[tuple[str, str]] = field(default_factory=list)  # échanges transmis à Gemini
    creee: datetime | None = None
    modifiee: datetime | None = None
    id: int | None = None

    @property
    def vide(self) -> bool:
        return not self.messages


@dataclass
class Resume:
    id: int
    titre: str
    modifiee: datetime
    nombre: int


def titre_automatique(texte: str) -> str:
    texte = " ".join(texte.split())
    if len(texte) <= LONGUEUR_TITRE:
        return texte or "Nouvelle conversation"
    coupe = texte[:LONGUEUR_TITRE].rsplit(" ", 1)[0]
    return (coupe or texte[:LONGUEUR_TITRE]) + "…"


def enregistrer(base: Base, conversation: Conversation, maintenant: datetime | None = None) -> Conversation:
    """Crée ou met à jour la conversation (une conversation vide n'est jamais enregistrée)."""
    if conversation.vide:
        return conversation
    maintenant = (maintenant or datetime.now()).replace(microsecond=0)
    conversation.creee = conversation.creee or maintenant
    conversation.modifiee = maintenant
    contenu = json.dumps({"messages": [asdict(x) for x in conversation.messages],
                          "memoire": [list(x) for x in conversation.memoire]}, ensure_ascii=False)
    cx = base._cx
    with cx:
        if conversation.id is None:
            curseur = cx.execute("INSERT INTO conversations (titre, creee, modifiee, contenu) VALUES (?, ?, ?, ?)",
                                 [conversation.titre, conversation.creee.isoformat(), conversation.modifiee.isoformat(),
                                  contenu])
            conversation.id = curseur.lastrowid
        else:
            cx.execute("UPDATE conversations SET titre = ?, modifiee = ?, contenu = ? WHERE id = ?",
                       [conversation.titre, conversation.modifiee.isoformat(), contenu, conversation.id])
    return conversation


def lister(base: Base) -> list[Resume]:
    lignes = base._cx.execute("SELECT id, titre, modifiee, contenu FROM conversations ORDER BY modifiee DESC, id DESC")
    resultat = []
    for identifiant, titre, modifiee, contenu in lignes:
        try:
            nombre = len(json.loads(contenu).get("messages", []))
        except ValueError:
            nombre = 0
        resultat.append(Resume(identifiant, titre, datetime.fromisoformat(modifiee), nombre))
    return resultat


def charger(base: Base, identifiant: int) -> Conversation | None:
    ligne = base._cx.execute("SELECT id, titre, creee, modifiee, contenu FROM conversations WHERE id = ?",
                             [identifiant]).fetchone()
    if ligne is None:
        return None
    try:
        contenu = json.loads(ligne[4])
    except ValueError:
        contenu = {}
    messages = [Message(**{k: v for k, v in x.items() if k in Message.__dataclass_fields__})
                for x in contenu.get("messages", []) if isinstance(x, dict)]
    memoire = [(str(x[0]), str(x[1])) for x in contenu.get("memoire", []) if isinstance(x, list) and len(x) == 2]
    return Conversation(ligne[1], messages, memoire, datetime.fromisoformat(ligne[2]), datetime.fromisoformat(ligne[3]),
                        ligne[0])


def renommer(base: Base, identifiant: int, titre: str) -> None:
    titre = " ".join(titre.split())[:80] or "Conversation"
    with base._cx:
        base._cx.execute("UPDATE conversations SET titre = ? WHERE id = ?", [titre, identifiant])


def supprimer(base: Base, identifiant: int) -> None:
    with base._cx:
        base._cx.execute("DELETE FROM conversations WHERE id = ?", [identifiant])


def tout_supprimer(base: Base) -> int:
    with base._cx:
        return base._cx.execute("DELETE FROM conversations").rowcount


def texte_quand(instant: datetime, maintenant: datetime) -> str:
    jours = (maintenant.date() - instant.date()).days
    if jours == 0:
        return f"aujourd'hui {instant:%H:%M}"
    if jours == 1:
        return "hier"
    if jours < 7:
        return ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][instant.weekday()]
    return f"{instant:%d/%m/%Y}"
