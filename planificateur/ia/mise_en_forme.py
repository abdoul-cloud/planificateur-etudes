"""Mise en forme des réponses de l'assistant : le Markdown simple de Gemini devient du texte riche Qt.

Gras (**…**), italique (*…* ou _…_), `code`, titres (#), listes à puces et numérotées, paragraphes.
Le texte est d'abord échappé : aucune balise HTML venant de la réponse n'est interprétée.
"""

from __future__ import annotations

import html
import re

_GRAS = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIQUE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_CODE = re.compile(r"`([^`\n]+)`")
_PUCE = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMERO = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_TITRE = re.compile(r"^\s*#{1,6}\s+(.*)$")


def _en_ligne(texte: str) -> str:
    texte = html.escape(texte, quote=False)
    codes: list[str] = []

    def garder_code(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    texte = _CODE.sub(garder_code, texte)  # pas de gras ni d'italique dans le code
    texte = _GRAS.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", texte)
    texte = _ITALIQUE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", texte)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: f"<code style='background:#EEF0F6'>&nbsp;{codes[int(m.group(1))]}&nbsp;</code>", texte)


def markdown_vers_html(texte: str) -> str:
    morceaux: list[str] = []
    liste: str | None = None  # "ul" ou "ol" en cours
    paragraphe: list[str] = []

    def fermer_paragraphe() -> None:
        if paragraphe:
            morceaux.append("<p style='margin:0 0 6px 0'>" + "<br>".join(paragraphe) + "</p>")
            paragraphe.clear()

    def fermer_liste() -> None:
        nonlocal liste
        if liste:
            morceaux.append(f"</{liste}>")
            liste = None

    def ouvrir_liste(genre: str) -> None:
        nonlocal liste
        if liste != genre:
            fermer_liste()
            morceaux.append(f"<{genre} style='margin:0 0 6px 0; -qt-list-indent:1'>")
            liste = genre

    for ligne in texte.replace("\r\n", "\n").split("\n"):
        if not ligne.strip():
            fermer_paragraphe()
            fermer_liste()
            continue
        if m := _TITRE.match(ligne):
            fermer_paragraphe()
            fermer_liste()
            morceaux.append(f"<p style='margin:4px 0 4px 0'><b>{_en_ligne(m.group(1))}</b></p>")
        elif m := _PUCE.match(ligne):
            fermer_paragraphe()
            ouvrir_liste("ul")
            morceaux.append(f"<li>{_en_ligne(m.group(1))}</li>")
        elif m := _NUMERO.match(ligne):
            fermer_paragraphe()
            ouvrir_liste("ol")
            morceaux.append(f"<li>{_en_ligne(m.group(2))}</li>")
        else:
            fermer_liste()
            paragraphe.append(_en_ligne(ligne.strip()))
    fermer_paragraphe()
    fermer_liste()
    return "".join(morceaux)
