"""Genera la nota índice: un mapa mental de la biblioteca por temas.

Obsidian dibuja los bloques ```mermaid```, así que el mapa se ve como un
diagrama de verdad y no como una lista. Debajo van las secciones por tema con
enlaces a cada libro, para poder navegar y para que el grafo de Obsidian los
conecte.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..categorias import SIN_CLASIFICAR
from ..models import Book
from .temas import CARPETA as CARPETA_TEMAS

NOMBRE = "Índice"
END_MARKER = "<!-- kindle-sync:fin -->"
_MAX_RAMA = 32  # títulos largos rompen la legibilidad del diagrama


class IndiceSink:
    def __init__(self, vault_dir: str | Path, subfolder: str = "Kindle"):
        self.root = Path(vault_dir).expanduser() / subfolder

    @property
    def path(self) -> Path:
        return self.root / f"{NOMBRE}.md"

    def write(self, libros: list[Book], nombre_nota) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        tail = _cola_preservada(self.path)
        self.path.write_text(self.render(libros, nombre_nota) + tail, encoding="utf-8")
        return self.path

    def render(self, libros: list[Book], nombre_nota) -> str:
        por_tema = _agrupar(libros)
        total_subrayados = sum(len(l.highlights) for l in libros)

        lineas = [
            "---",
            "titulo: Índice de subrayados del Kindle",
            f"libros: {len(libros)}",
            f"subrayados: {total_subrayados}",
            f"temas: {len(por_tema)}",
            f"actualizado: {datetime.now().isoformat(timespec='seconds')}",
            "tags:",
            "  - kindle",
            "  - indice",
            "---",
            "",
            "# Índice de subrayados",
            "",
            f"{len(libros)} libro(s) · {total_subrayados} subrayado(s) · "
            f"{len(por_tema)} tema(s)",
            "",
            "```mermaid",
            "mindmap",
            "  root((Biblioteca))",
        ]

        for tema, del_tema in por_tema.items():
            lineas.append(f"    {_rama(tema)}")
            for libro in del_tema:
                lineas.append(f"      {_rama(libro.title)}")
        lineas += ["```", ""]

        for tema, del_tema in por_tema.items():
            subrayados = sum(len(l.highlights) for l in del_tema)
            lineas += [f"## [[{CARPETA_TEMAS}/{_sin_barras(tema)}|{tema}]]",
                       "",
                       f"*{len(del_tema)} libro(s) · {subrayados} subrayado(s)*",
                       ""]
            for libro in del_tema:
                autor = f" — {libro.author}" if libro.author else ""
                lineas.append(
                    f"- [[{nombre_nota(libro)}|{libro.title}]]{autor} "
                    f"· {len(libro.highlights)} subrayado(s)")
            lineas.append("")

        lineas += [END_MARKER, ""]
        return "\n".join(lineas)


def _agrupar(libros: list[Book]) -> dict[str, list[Book]]:
    """Agrupa por tema, con los temas más nutridos primero y el cajón al final."""
    por_tema: dict[str, list[Book]] = {}
    for libro in libros:
        por_tema.setdefault(libro.categoria or SIN_CLASIFICAR, []).append(libro)

    for del_tema in por_tema.values():
        del_tema.sort(key=lambda l: (-len(l.highlights), l.title))

    return dict(sorted(
        por_tema.items(),
        key=lambda par: (par[0] == SIN_CLASIFICAR, -len(par[1]), par[0])))


def _sin_barras(tema: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", tema).strip() or SIN_CLASIFICAR


def _rama(texto: str) -> str:
    """Prepara un texto para mermaid, que se atraganta con ( ) [ ] { } y comillas."""
    limpio = re.sub(r"[()\[\]{}\"'`]", "", texto).strip()
    limpio = re.sub(r"\s+", " ", limpio)
    if len(limpio) > _MAX_RAMA:
        limpio = limpio[:_MAX_RAMA].rstrip() + "…"
    return limpio or "sin título"


def _cola_preservada(path: Path) -> str:
    if not path.exists():
        return ""
    contenido = path.read_text(encoding="utf-8", errors="replace")
    idx = contenido.find(END_MARKER)
    return "" if idx == -1 else contenido[idx + len(END_MARKER):]
