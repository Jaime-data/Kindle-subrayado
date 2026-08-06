"""Lector del fichero que genera «Exportar notas» en el Kindle.

Es la única forma de sacar por Wi-Fi los subrayados de un libro que no has
comprado en Amazon: en el Kindle, dentro del libro, *Notas → Exportar*, y el
dispositivo te manda por correo un HTML con todo.

Formato del fichero (estable desde hace años):

    <div class="bookTitle">Título</div>
    <div class="authors">Autor</div>
    <div class="sectionHeading">Capítulo 3</div>
    <div class="noteHeading">Subrayado (amarillo) - Página 24 · Posición 356</div>
    <div class="noteText">Texto del subrayado</div>
    <div class="noteHeading">Nota - Página 24 · Posición 356</div>
    <div class="noteText">Mi comentario</div>
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from ..models import Highlight

_PAGE = re.compile(r"(?:p[áa]gina|page)\s+([\w.]+)", re.IGNORECASE)
_LOC = re.compile(r"(?:posici[óo]n|location|loc\.?)\s+([\d.,-]+)", re.IGNORECASE)
_KINDS = (
    ("bookmark", ("marcador", "bookmark")),
    ("note", ("nota", "note")),
    ("highlight", ("subrayado", "highlight", "destacado")),
)


class _Parser(HTMLParser):
    """Recorre el HTML acumulando el texto de cada div con clase conocida."""

    CLASES = ("bookTitle", "authors", "sectionHeading", "noteHeading", "noteText")

    def __init__(self) -> None:
        super().__init__()
        self.bloques: list[tuple[str, str]] = []
        self._clase: str | None = None
        self._profundidad = 0
        self._texto: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        clases = dict(attrs).get("class") or ""
        if self._clase:
            self._profundidad += 1
        elif clases in self.CLASES:
            self._clase = clases
            self._profundidad = 1
            self._texto = []

    def handle_data(self, data: str) -> None:
        if self._clase and (limpio := data.strip()):
            self._texto.append(limpio)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._clase:
            return
        self._profundidad -= 1
        if self._profundidad == 0:
            self.bloques.append((self._clase, " ".join(self._texto)))
            self._clase = None


def parse_file(path: str | Path) -> list[Highlight]:
    return parse_html(Path(path).read_text(encoding="utf-8", errors="replace"))


def es_exportacion(html: str) -> bool:
    """¿Este HTML es una exportación de notas del Kindle?"""
    return 'class="bookTitle"' in html and 'class="noteHeading"' in html


def parse_html(html: str) -> list[Highlight]:
    parser = _Parser()
    parser.feed(html)

    titulo = autor = None
    seccion = None
    cabecera: str | None = None
    salida: list[Highlight] = []

    for clase, texto in parser.bloques:
        if clase == "bookTitle":
            titulo = texto
        elif clase == "authors":
            autor = _normaliza_autor(texto)
        elif clase == "sectionHeading":
            seccion = texto
        elif clase == "noteHeading":
            cabecera = texto
        elif clase == "noteText" and titulo:
            hl = _construir(titulo, autor, seccion, cabecera or "", texto)
            if hl is not None:
                salida.append(hl)
            cabecera = None

    return _fusionar_notas(salida)


def _construir(titulo: str, autor: str | None, seccion: str | None,
               cabecera: str, texto: str) -> Highlight | None:
    if not texto.strip():
        return None
    kind = _detectar_kind(cabecera)
    page = _PAGE.search(cabecera)
    loc = _LOC.search(cabecera)
    return Highlight(
        book_title=titulo,
        book_author=autor,
        text=texto.strip(),
        kind=kind,
        page=page.group(1) if page else None,
        location=loc.group(1) if loc else None,
        note=None,
        source="export",
        asin=None,
    )


def _fusionar_notas(items: list[Highlight]) -> list[Highlight]:
    """Une una nota con el subrayado inmediatamente anterior en la misma posición.

    El Kindle exporta la nota como una entrada aparte justo detrás del
    subrayado al que acompaña.
    """
    salida: list[Highlight] = []
    for hl in items:
        anterior = salida[-1] if salida else None
        if (hl.kind == "note" and anterior is not None
                and anterior.kind == "highlight"
                and hl.location and anterior.location
                and _cerca(hl.location, anterior.location)):
            salida[-1] = Highlight(
                book_title=anterior.book_title,
                book_author=anterior.book_author,
                text=anterior.text,
                note=hl.text,
                kind="highlight",
                page=anterior.page,
                location=anterior.location,
                added_at=anterior.added_at,
                source=anterior.source,
                asin=anterior.asin,
            )
            continue
        salida.append(hl)
    return salida


def _cerca(a: str, b: str, margen: int = 3) -> bool:
    na, nb = _num(a), _num(b)
    return na is not None and nb is not None and abs(na - nb) <= margen


def _num(valor: str) -> int | None:
    m = re.search(r"\d+", valor.replace(".", "").replace(",", ""))
    return int(m.group()) if m else None


def _detectar_kind(cabecera: str) -> str:
    low = cabecera.casefold()
    for kind, marcas in _KINDS:
        if any(m in low for m in marcas):
            return kind
    return "highlight"


def _normaliza_autor(texto: str) -> str | None:
    autor = texto.strip()
    if not autor:
        return None
    if autor.count(",") == 1:  # «Apellido, Nombre»
        apellido, nombre = (p.strip() for p in autor.split(","))
        if apellido and nombre:
            return f"{nombre} {apellido}"
    return autor
