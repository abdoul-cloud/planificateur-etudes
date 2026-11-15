"""Client minimal de l'API Gemini (Interactions API, REST), sans dépendance externe.

Seul module de l'application autorisé à accéder au réseau. Il n'envoie que
ce qu'on lui donne explicitement, et garde une copie lisible du dernier envoi
pour l'écran « Voir ce qui est envoyé ».
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
REVISION = "2026-05-20"
DELAI_S = 90
TAILLE_MAX_FICHIER = 20 * 1024 * 1024

TYPES_FICHIERS = {
    ".pdf": ("document", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
}


class ErreurGemini(Exception):
    """Erreur expliquée en français, prête à afficher (avec le code HTTP s'il y en a un)."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


# Surcharge passagère côté Google : on réessaie, puis on passe à un autre modèle.
CODES_PASSAGERS = {500, 502, 503, 504}
ATTENTES_S = (2, 5)  # délais avant les nouveaux essais sur le même modèle
MODELES_SECOURS = ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
MODELES_PROPOSES = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.8-flash",
                    "gemini-3.6-flash", "gemini-3.5-flash-lite"]


@dataclass
class Appel:
    """Action demandée par le modèle (appel de fonction)."""

    nom: str
    arguments: dict


@dataclass
class Reponse:
    texte: str = ""
    appels: list[Appel] = field(default_factory=list)
    brut: dict = field(default_factory=dict)


def bloc_texte(texte: str) -> dict:
    return {"type": "text", "text": texte}


def bloc_fichier(chemin: Path) -> dict:
    """Image ou PDF joint, encodé en base64."""
    chemin = Path(chemin)
    nature = TYPES_FICHIERS.get(chemin.suffix.lower())
    if nature is None:
        raise ErreurGemini("Format non pris en charge : choisissez un PDF ou une image (PNG, JPG, WEBP).")
    taille = chemin.stat().st_size
    if taille > TAILLE_MAX_FICHIER:
        raise ErreurGemini("Fichier trop lourd (20 Mo au maximum). Recadrez ou réduisez l'image.")
    type_bloc, mime = nature
    return {"type": type_bloc, "data": base64.b64encode(chemin.read_bytes()).decode("ascii"), "mime_type": mime}


def verifier_https() -> None:
    """Vérifie que la connexion sécurisée est disponible (sert à l'auto-test de l'exécutable)."""
    import ssl

    ssl.create_default_context()


def _transport_http(url: str, corps: bytes, entetes: dict[str, str]) -> dict:
    requete = urllib.request.Request(url, data=corps, headers=entetes, method="POST")
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        detail, raison = "", ""
        try:
            donnees = json.loads(erreur.read().decode("utf-8"))
            if isinstance(donnees, list) and donnees:  # Google enveloppe parfois l'erreur dans une liste
                donnees = donnees[0]
            infos = donnees.get("error", {})
            detail = infos.get("message", "")
            raison = next((d.get("reason", "") for d in infos.get("details", []) if d.get("reason")), "")
        except Exception:  # noqa: BLE001 — le détail est facultatif
            pass
        if raison == "API_KEY_INVALID" or "API key not valid" in detail:
            raise ErreurGemini("Clé API invalide : vérifiez-la dans les Préférences (Assistant IA).", erreur.code) from erreur
        raise ErreurGemini(_message_http(erreur.code, detail), erreur.code) from erreur
    except urllib.error.URLError as erreur:
        raise ErreurGemini("Impossible de joindre Gemini : vérifiez votre connexion Internet.") from erreur
    except TimeoutError as erreur:
        raise ErreurGemini("Gemini met trop de temps à répondre. Réessayez dans un instant.") from erreur


def _message_http(code: int, detail: str) -> str:
    messages = {
        400: "Requête refusée par Gemini.",
        401: "Clé API refusée : vérifiez-la dans les Préférences.",
        403: "Clé API refusée ou sans accès à ce modèle : vérifiez-la dans les Préférences.",
        404: "Modèle introuvable : vérifiez son nom dans les Préférences.",
        429: "Limite de la formule gratuite atteinte. Réessayez dans quelques minutes.",
        503: "Gemini est très sollicité en ce moment (surcharge passagère chez Google). Réessayez dans un instant.",
    }
    texte = messages.get(code, f"Gemini a renvoyé une erreur ({code}). Réessayez plus tard.")
    return f"{texte}\n\nDétail : {detail}" if detail else texte


def _apercu(valeur):
    """Copie lisible de l'envoi : les fichiers sont remplacés par leur taille."""
    if isinstance(valeur, dict):
        if "data" in valeur and valeur.get("type") in ("image", "document"):
            taille = len(valeur["data"]) * 3 // 4 // 1024
            return {**valeur, "data": f"<fichier joint, environ {taille} Ko>"}
        return {k: _apercu(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [_apercu(v) for v in valeur]
    return valeur


class ClientGemini:
    def __init__(self, cle: str, modele: str,
                 transport: Callable[[str, bytes, dict[str, str]], dict] | None = None,
                 secours: list[str] | None = None, attentes: tuple[float, ...] = ATTENTES_S,
                 attendre: Callable[[float], None] | None = None) -> None:
        self.cle = cle
        self.modele = modele
        self.transport = transport or _transport_http
        self.secours = [x for x in (MODELES_SECOURS if secours is None else secours) if x != modele]
        self.attentes = attentes
        self.attendre = attendre or __import__("time").sleep
        self.dernier_envoi: dict | None = None  # pour « Voir ce qui est envoyé »
        self.modele_utilise: str = modele  # modèle qui a réellement répondu

    def interagir(self, entree, instruction: str | None = None, outils: list[dict] | None = None,
                  schema: dict | None = None) -> Reponse:
        """Envoie la requête ; en cas de surcharge, réessaie puis passe aux modèles de secours."""
        derniere: ErreurGemini | None = None
        for modele in [self.modele, *self.secours]:
            essais = (0, *self.attentes) if modele == self.modele else (0,)
            for attente in essais:
                if attente:
                    self.attendre(attente)
                try:
                    reponse = self._envoyer(modele, entree, instruction, outils, schema)
                except ErreurGemini as erreur:
                    if erreur.code in CODES_PASSAGERS:
                        derniere = erreur
                        continue  # surcharge : nouvel essai, puis modèle suivant
                    if erreur.code == 404 and modele != self.modele:
                        break  # ce modèle de secours n'existe pas (ou plus) : on passe au suivant
                    raise
                self.modele_utilise = modele
                return reponse
        raise derniere or ErreurGemini("Gemini ne répond pas pour le moment. Réessayez plus tard.")

    def _envoyer(self, modele: str, entree, instruction, outils, schema) -> Reponse:
        corps: dict = {"model": modele, "input": entree, "store": False}
        if instruction:
            corps["system_instruction"] = instruction
        if outils:
            corps["tools"] = outils
        if schema:
            corps["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
        self.dernier_envoi = _apercu(corps)
        entetes = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.cle,
            "Api-Revision": REVISION,
        }
        brut = self.transport(URL, json.dumps(corps).encode("utf-8"), entetes)
        return lire_reponse(brut)

    def tester(self) -> str:
        """Petite requête pour vérifier la clé et le modèle."""
        reponse = self.interagir("Réponds seulement par le mot : OK")
        if not reponse.texte.strip():
            raise ErreurGemini("Gemini a répondu, mais sans texte.")
        return reponse.texte.strip()


def lire_reponse(brut: dict) -> Reponse:
    """Extrait le texte et les appels de fonction, en tolérant de petites variantes de format."""
    if brut.get("error"):
        raise ErreurGemini(str(brut["error"].get("message", brut["error"])))
    textes: list[str] = []
    appels: list[Appel] = []
    for etape in brut.get("steps", []) or brut.get("outputs", []) or []:
        type_etape = etape.get("type")
        if type_etape in ("function_call", "tool_call"):
            appels.append(_appel(etape))
            continue
        if type_etape in ("thought", "user_input"):
            continue
        for bloc in etape.get("content", []) or []:
            if bloc.get("type") == "text" and bloc.get("text"):
                textes.append(bloc["text"])
            elif bloc.get("type") in ("function_call", "tool_call"):
                appels.append(_appel(bloc))
    return Reponse("\n".join(textes).strip(), appels, brut)


def _appel(donnees: dict) -> Appel:
    arguments = donnees.get("arguments", donnees.get("args", {})) or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    return Appel(str(donnees.get("name", "")), arguments)


def json_de(texte: str):
    """JSON contenu dans une réponse texte (avec ou sans bloc ```json)."""
    texte = texte.strip()
    if texte.startswith("```"):
        texte = texte.split("\n", 1)[1] if "\n" in texte else texte
        texte = texte.rsplit("```", 1)[0]
    debut = min([i for i in (texte.find("{"), texte.find("[")) if i >= 0], default=-1)
    if debut > 0:
        texte = texte[debut:]
    try:
        return json.loads(texte)
    except json.JSONDecodeError as erreur:
        raise ErreurGemini("La réponse de Gemini n'a pas pu être lue. Réessayez.") from erreur

