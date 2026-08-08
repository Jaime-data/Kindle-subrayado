"""Modelo de datos común a todas las fuentes de subrayados."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal

Kind = Literal["highlight", "note", "bookmark"]

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    """Normaliza texto para comparar subrayados que vienen de fuentes distintas.

    El mismo subrayado leído de `My Clippings.txt` y de read.amazon.com puede
    diferir en comillas tipográficas, espacios o mayúsculas.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip().casefold()


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text).lower()
    return text[:max_len].strip("-") or "sin-titulo"


# Restos que dejan las webs de descarga en el nombre del fichero y que el
# Kindle acaba mostrando como si fueran parte del título.
_RUIDO = re.compile(
    r"""\(?\s*(?:z[\s._-]*librar(?:y|ies)|1lib|z[\s._-]*lib)"""
    r"""[\w\s.,_-]*\)?""", re.IGNORECASE)
# No incluye paréntesis: «Céntrate (Deep Work)» lleva uno con sentido.
_SUFIJO_SOBRANTE = re.compile(r"[\s_,;.\-–—]+$")
_PARENTESIS_VACIOS = re.compile(r"\(\s*\)")


def limpiar_titulo(titulo: str, autor: str | None = None) -> str:
    """Quita del título el ruido de las webs de descarga y el autor repetido.

    «Radical Candor (Kim Scott) (z-library.sk, 1lib.sk, z-lib.sk)» es, para
    quien lee sus notas, «Radical Candor».
    """
    limpio = _RUIDO.sub(" ", titulo)
    limpio = limpio.replace("_", " ")

    if autor:
        # El autor suele venir repetido entre paréntesis dentro del título.
        apellido = autor.split()[-1] if autor.split() else ""
        for repetido in (autor, f"{apellido}, {autor.split()[0]}" if autor.split() else ""):
            if repetido:
                limpio = re.sub(rf"\(\s*{re.escape(repetido)}\s*\)", " ", limpio,
                                flags=re.IGNORECASE)

    limpio = _PARENTESIS_VACIOS.sub(" ", limpio)
    limpio = _WS.sub(" ", limpio).strip()
    limpio = _SUFIJO_SOBRANTE.sub("", limpio)

    # Al quitar el ruido puede quedar un paréntesis sin pareja.
    while limpio.count(")") > limpio.count("("):
        limpio = _SUFIJO_SOBRANTE.sub("", limpio.rstrip(")").rstrip())
    while limpio.count("(") > limpio.count(")"):
        limpio = _SUFIJO_SOBRANTE.sub("", limpio[:limpio.rfind("(")].rstrip())

    return limpio or titulo.strip()


@dataclass(frozen=True)
class Highlight:
    book_title: str
    text: str
    book_author: str | None = None
    note: str | None = None
    kind: Kind = "highlight"
    page: str | None = None
    location: str | None = None
    added_at: datetime | None = None
    source: str = "clippings"
    asin: str | None = None

    @property
    def uid(self) -> str:
        """Identidad estable e independiente de la fuente.

        Se basa en el libro (con el título ya limpio) y el texto normalizado:
        así un subrayado cuenta una sola vez aunque llegue por vías distintas
        y con el título más o menos ensuciado por la web de descarga.
        """
        titulo = limpiar_titulo(self.book_title, self.book_author)
        base = f"{normalize(titulo)}|{self.kind}|{normalize(self.text)}"
        if self.kind == "bookmark":  # un marcador no tiene texto que lo distinga
            base += f"|{self.location or self.page or ''}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

    @property
    def sort_key(self) -> tuple[int, int, float]:
        loc = _first_int(self.location)
        page = _first_int(self.page)
        ts = self.added_at.timestamp() if self.added_at else 0.0
        # Sin posición conocida, van al final pero ordenados por fecha.
        return (loc if loc is not None else 10**9, page if page is not None else 10**9, ts)

    def merged_with(self, other: "Highlight") -> "Highlight":
        """Combina dos versiones del mismo subrayado quedándose con más datos."""
        return Highlight(
            book_title=self.book_title,
            text=self.text if len(self.text) >= len(other.text) else other.text,
            book_author=self.book_author or other.book_author,
            note=self.note or other.note,
            kind=self.kind,
            page=self.page or other.page,
            location=self.location or other.location,
            added_at=self.added_at or other.added_at,
            source=self.source if self.source == other.source else "clippings+cloud",
            asin=self.asin or other.asin,
        )


@dataclass
class Book:
    title: str
    author: str | None = None
    asin: str | None = None
    highlights: dict[str, Highlight] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return slugify(f"{self.title} {self.author or ''}")

    def add(self, hl: Highlight) -> bool:
        """Añade un subrayado. Devuelve True si es nuevo."""
        existing = self.highlights.get(hl.uid)
        if existing is None:
            self.highlights[hl.uid] = hl
            return True
        self.highlights[hl.uid] = existing.merged_with(hl)
        return False

    def sorted_highlights(self) -> list[Highlight]:
        return sorted(self.highlights.values(), key=lambda h: h.sort_key)


def group_by_book(highlights: Iterable[Highlight]) -> dict[str, Book]:
    books: dict[str, Book] = {}
    for hl in highlights:
        # El título se limpia aquí, el único punto por el que pasan todas
        # las fuentes, para que la clave del libro sea la misma vengan de
        # donde vengan los subrayados.
        titulo = limpiar_titulo(hl.book_title, hl.book_author)
        key = slugify(f"{titulo} {hl.book_author or ''}")
        book = books.get(key)
        if book is None:
            book = Book(title=titulo, author=hl.book_author, asin=hl.asin)
            books[key] = book
        book.author = book.author or hl.book_author
        book.asin = book.asin or hl.asin
        book.add(hl)
    return books


def _first_int(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"\d+", value.replace(".", "").replace(",", ""))
    return int(m.group()) if m else None
