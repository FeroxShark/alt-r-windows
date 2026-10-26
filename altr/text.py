"""Limpieza del texto y troceado en frases (independiente de la plataforma)."""
from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_MD_IMG = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_FENCE = re.compile(r"^\s*(```|~~~).*$", re.M)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_MD_QUOTE = re.compile(r"^\s*>+\s?", re.M)
_MD_EMPH = re.compile(r"(\*\*|__|\*|`|~~)")
_SENT_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n+")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def clean_text(text: str, *, strip_markdown: bool = True, read_urls: bool = False,
               max_chars: int = 20000, lexicon: dict[str, str] | None = None) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    if not read_urls:
        t = _URL.sub("enlace", t)
    if strip_markdown:
        t = _MD_IMG.sub(r"\1", t)
        t = _MD_LINK.sub(r"\1", t)
        t = _MD_FENCE.sub("", t)
        t = _MD_HEADING.sub("", t)
        t = _MD_BULLET.sub("", t)
        t = _MD_QUOTE.sub("", t)
        t = _MD_EMPH.sub("", t)
    if lexicon:
        t = _WORD.sub(lambda m: lexicon.get(m.group(0).lower(), m.group(0)), t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n\s*", "\n", t).strip()
    return t[:max_chars].strip()


def _hard_split(piece: str, limit: int) -> list[str]:
    """Parte un trozo demasiado largo por comas/espacios sin cortar palabras."""
    out: list[str] = []
    while len(piece) > limit:
        cut = max(piece.rfind(sep, 0, limit) for sep in (", ", "; ", ": ", " - "))
        if cut < limit // 3:
            cut = piece.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        else:
            cut += 1
        out.append(piece[:cut].strip())
        piece = piece[cut:].strip()
    if piece:
        out.append(piece)
    return out


def split_chunks(text: str, first_max: int = 160, max_chars: int = 400) -> list[str]:
    """Trozos por oración. El primero es corto para empezar a hablar rápido."""
    sentences = [s.strip() for s in _SENT_END.split(text) if s and s.strip()]
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        limit = first_max if not chunks else max_chars
        for piece in _hard_split(s, limit):
            limit = first_max if not chunks else max_chars
            if not cur:
                cur = piece
            elif len(cur) + 1 + len(piece) <= limit:
                cur = f"{cur} {piece}"
            else:
                chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks
