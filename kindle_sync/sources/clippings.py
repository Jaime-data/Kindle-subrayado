"""Lector de `My Clippings.txt` (el fichero que el Kindle escribe en su memoria).

Es la única fuente disponible para libros copiados por USB, y funciona con
Kindle en español e inglés.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..models import Highlight

SEPARATOR = "=========="

# Meses en los idiomas más habituales de la interfaz del Kindle.
_MONTHS = {
    **{m: i for i, m in enumerate(
        "enero febrero marzo abril mayo junio julio agosto "
        "septiembre octubre noviembre diciembre".split(), 1)},
    **{m: i for i, m in enumerate(
        "january february march april may june july august "
        "september october november december".split(), 1)},
    **{m: i for i, m in enumerate(
        "gener febrer març abril maig juny juliol agost "
        "setembre octubre novembre desembre".split(), 1)},
}

_TITLE_AUTHOR = re.compile(r"^(?P<title>.+?)\s*\((?P<author>[^()]+)\)\s*$")
_PAGE = re.compile(r"(?:p[áa]gina|page)\s+([\w.-]+)", re.IGNORECASE)
_LOCATION = re.compile(r"(?:posici[óo]n|location|loc\.?)\s+([\d.,-]+)", re.IGNORECASE)
_DATE_ES = re.compile(
    r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})[,\s]+(\d{1,2}):(\d{2}):(\d{2})", re.IGNORECASE)
_DATE_EN = re.compile(
    r"(\w+)\s+(\d{1,2}),\s+(\d{4})[,\s]+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE)

_KIND_MARKERS = (
    ("bookmark", ("marcador", "bookmark", "marcapágin", "marcapagin")),
    ("note", ("nota", "note")),
    ("highlight", ("subrayad", "highlight", "destacad")),
)


def parse_file(path: str | Path) -> list[Highlight]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return parse_text(raw)


def parse_text(raw: str) -> list[Highlight]:
    out: list[Highlight] = []
    for chunk in raw.split(SEPARATOR):
        hl = _parse_entry(chunk)
        if hl is not None:
            out.append(hl)
    return out


def _parse_entry(chunk: str) -> Highlight | None:
    lines = [ln.strip("﻿ \t\r") for ln in chunk.splitlines()]
    while lines and not lines[0]:  # el separador deja líneas en blanco delante
        lines.pop(0)
    if len(lines) < 2:
        return None

    title_line, meta_line = lines[0], lines[1]
    if not title_line or not meta_line.startswith("-"):
        return None

    body = "\n".join(lines[2:]).strip()
    kind = _detect_kind(meta_line)
    if kind != "bookmark" and not body:
        return None  # subrayado vacío: el Kindle a veces deja restos

    title, author = _split_title_author(title_line)
    page = _PAGE.search(meta_line)
    location = _LOCATION.search(meta_line)

    return Highlight(
        book_title=title,
        book_author=author,
        text=body,
        kind=kind,
        page=page.group(1) if page else None,
        location=location.group(1) if location else None,
        added_at=_parse_date(meta_line),
        source="clippings",
    )


def _detect_kind(meta_line: str) -> str:
    low = meta_line.casefold()
    for kind, markers in _KIND_MARKERS:
        if any(m in low for m in markers):
            return kind
    return "highlight"


def _split_title_author(line: str) -> tuple[str, str | None]:
    m = _TITLE_AUTHOR.match(line)
    if not m:
        return line, None
    author = m.group("author").strip()
    # El Kindle escribe "Apellido, Nombre" en muchos libros importados.
    if author.count(",") == 1:
        last, first = (p.strip() for p in author.split(","))
        if last and first:
            author = f"{first} {last}"
    return m.group("title").strip(), author


def _parse_date(meta_line: str) -> datetime | None:
    m = _DATE_ES.search(meta_line)
    if m:
        day, month_name, year, hh, mm, ss = m.groups()
        month = _MONTHS.get(month_name.casefold())
        if month:
            return datetime(int(year), month, int(day), int(hh), int(mm), int(ss))

    m = _DATE_EN.search(meta_line)
    if m:
        month_name, day, year, hh, mm, ss, ampm = m.groups()
        month = _MONTHS.get(month_name.casefold())
        if month:
            hour = int(hh)
            if ampm and ampm.upper() == "PM" and hour < 12:
                hour += 12
            elif ampm and ampm.upper() == "AM" and hour == 12:
                hour = 0
            return datetime(int(year), month, int(day), hour, int(mm), int(ss))
    return None
