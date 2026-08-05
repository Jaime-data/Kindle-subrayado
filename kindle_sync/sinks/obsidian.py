"""Escribe cada libro como una nota Markdown compatible con Obsidian.

El fichero .md se regenera en cada sincronización a partir del estado
acumulado, así que los subrayados quedan siempre ordenados por posición.
Todo lo que escribas por debajo del marcador `<!-- kindle-sync:fin -->`
se conserva intacto: ahí van tus notas personales.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..models import Book, Highlight

END_MARKER = "<!-- kindle-sync:fin -->"
_HASH_RE = re.compile(r"\^k-([0-9a-f]{12})")


class ObsidianSink:
    def __init__(self, vault_dir: str | Path, subfolder: str = "Kindle",
                 include_bookmarks: bool = False):
        self.root = Path(vault_dir).expanduser() / subfolder
        self.include_bookmarks = include_bookmarks

    def path_for(self, book: Book) -> Path:
        return self.root / f"{_safe_filename(book.title, book.author)}.md"

    def write(self, book: Book) -> Path:
        path = self.path_for(book)
        path.parent.mkdir(parents=True, exist_ok=True)
        tail = _preserved_tail(path)
        path.write_text(self.render(book) + tail, encoding="utf-8")
        return path

    def existing_uids(self, book: Book) -> set[str]:
        path = self.path_for(book)
        if not path.exists():
            return set()
        return set(_HASH_RE.findall(path.read_text(encoding="utf-8", errors="replace")))

    def render(self, book: Book) -> str:
        highlights = [h for h in book.sorted_highlights()
                      if self.include_bookmarks or h.kind != "bookmark"]
        lines = [
            "---",
            f"titulo: {_yaml(book.title)}",
            f"autor: {_yaml(book.author or 'Desconocido')}",
        ]
        if book.asin:
            lines.append(f"asin: {_yaml(book.asin)}")
        lines += [
            "fuente: kindle",
            f"subrayados: {len(highlights)}",
            f"actualizado: {datetime.now().isoformat(timespec='seconds')}",
            "tags:",
            "  - kindle",
            "  - subrayados",
            "---",
            "",
            f"# {book.title}",
            "",
        ]
        if book.author:
            lines += [f"*{book.author}*", ""]

        for hl in highlights:
            lines += _render_highlight(hl)

        lines += ["", END_MARKER, ""]
        return "\n".join(lines)


def _render_highlight(hl: Highlight) -> list[str]:
    ref = " · ".join(filter(None, [
        f"pág. {hl.page}" if hl.page else None,
        f"pos. {hl.location}" if hl.location else None,
        hl.added_at.strftime("%d/%m/%Y") if hl.added_at else None,
    ])) or "sin referencia"

    callout = {"highlight": "quote", "note": "note", "bookmark": "info"}[hl.kind]
    body = hl.text if hl.kind != "bookmark" else "(marcador)"

    out = [f"> [!{callout}] {ref}"]
    out += [f"> {line}" if line else ">" for line in body.splitlines()]
    if hl.note:
        out += [">", f"> **Nota:** {hl.note}"]
    out += [f"^k-{hl.uid}", ""]
    return out


def _preserved_tail(path: Path) -> str:
    """Devuelve lo que el usuario haya escrito tras el marcador final."""
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace")
    idx = content.find(END_MARKER)
    if idx == -1:
        return ""
    return content[idx + len(END_MARKER):]


def _safe_filename(title: str, author: str | None) -> str:
    name = f"{title} - {author}" if author else title
    name = re.sub(r'[\\/:*?"<>|]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "Sin titulo"


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
