"""Estado acumulado: qué subrayados conocemos ya de cada libro.

Guardar el estado aparte del .md permite regenerar las notas de Obsidian sin
perder nada y evita duplicar un subrayado que llega dos veces (nube y USB).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

from .models import Book, Highlight

SCHEMA = 1


class Store:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir) / "books"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def load(self, key: str) -> Book | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        book = Book(title=data["title"], author=data.get("author"),
                    asin=data.get("asin"), categoria=data.get("categoria"))
        for raw in data.get("highlights", []):
            book.add(_from_json(raw))
        return book

    def save(self, key: str, book: Book) -> None:
        payload = {
            "schema": SCHEMA,
            "title": book.title,
            "author": book.author,
            "asin": book.asin,
            "categoria": book.categoria,
            "highlights": [_to_json(h) for h in book.sorted_highlights()],
        }
        _atomic_write(self._path(key), json.dumps(payload, ensure_ascii=False, indent=1))

    def keys(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))


def _to_json(h: Highlight) -> dict:
    return {
        "uid": h.uid,
        "book_title": h.book_title,
        "book_author": h.book_author,
        "text": h.text,
        "note": h.note,
        "kind": h.kind,
        "page": h.page,
        "location": h.location,
        "added_at": h.added_at.isoformat() if h.added_at else None,
        "source": h.source,
        "asin": h.asin,
    }


def _from_json(raw: dict) -> Highlight:
    added = raw.get("added_at")
    return Highlight(
        book_title=raw["book_title"],
        book_author=raw.get("book_author"),
        text=raw["text"],
        note=raw.get("note"),
        kind=raw.get("kind", "highlight"),
        page=raw.get("page"),
        location=raw.get("location"),
        added_at=datetime.fromisoformat(added) if added else None,
        source=raw.get("source", "clippings"),
        asin=raw.get("asin"),
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
