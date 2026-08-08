"""Una nota por temática, además del índice general.

El índice es la vista de pájaro; cada nota de tema es el mapa de esa rama:
sus libros, su propio mapa mental y los subrayados más largos, que suelen ser
las ideas de fondo. Así cada temática existe como nota propia en el grafo de
Obsidian y se puede enlazar desde cualquier sitio.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from ..categorias import SIN_CLASIFICAR
from ..models import Book

CARPETA = "Temas"
END_MARKER = "<!-- kindle-sync:fin -->"
_MAX_RAMA = 32
_DESTACADOS = 5


class TemasSink:
    def __init__(self, vault_dir: str | Path, subfolder: str = "Kindle"):
        self.root = Path(vault_dir).expanduser() / subfolder / CARPETA

    def nombre_nota(self, tema: str) -> str:
        return _sin_barras(tema)

    def path_for(self, tema: str) -> Path:
        return self.root / f"{self.nombre_nota(tema)}.md"

    def write_all(self, por_tema: dict[str, list[Book]], nombre_libro) -> list[Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        escritas = []
        for tema, libros in por_tema.items():
            path = self.path_for(tema)
            tail = _cola_preservada(path)
            path.write_text(self.render(tema, libros, nombre_libro) + tail,
                            encoding="utf-8")
            escritas.append(path)
        self._borrar_temas_vacios({self.path_for(t) for t in por_tema})
        return escritas

    def render(self, tema: str, libros: list[Book], nombre_libro) -> str:
        subrayados = sum(len(l.highlights) for l in libros)
        lineas = [
            "---",
            f"tema: {_yaml(tema)}",
            f"libros: {len(libros)}",
            f"subrayados: {subrayados}",
            f"actualizado: {datetime.now().isoformat(timespec='seconds')}",
            "tags:",
            "  - kindle",
            "  - tema",
            f"  - {etiqueta(tema)}",
            "---",
            "",
            f"# {tema}",
            "",
            f"{len(libros)} libro(s) · {subrayados} subrayado(s) · "
            f"[[Índice|volver al índice]]",
            "",
            "```mermaid",
            "mindmap",
            f"  root(({_rama(tema)}))",
        ]
        for libro in libros:
            lineas.append(f"    {_rama(libro.title)}")
            if libro.author:
                lineas.append(f"      {_rama(libro.author)}")
        lineas += ["```", "", "## Libros", ""]

        for libro in libros:
            autor = f" — {libro.author}" if libro.author else ""
            lineas.append(f"- [[{nombre_libro(libro)}|{libro.title}]]{autor} "
                          f"· {len(libro.highlights)} subrayado(s)")
            if libro.descripcion:
                lineas.append(f"  {libro.descripcion}")

        destacados = _destacados(libros)
        if destacados:
            lineas += ["", "## Ideas de fondo", ""]
            for libro, hl in destacados:
                lineas += [f"> [!quote] {libro.title}",
                           *(f"> {ln}" for ln in hl.text.splitlines()),
                           ""]

        lineas += [END_MARKER, ""]
        return "\n".join(lineas)

    def _borrar_temas_vacios(self, vigentes: set[Path]) -> None:
        """Un tema que se queda sin libros (al reclasificar) deja de existir."""
        if not self.root.exists():
            return
        for path in self.root.glob("*.md"):
            if path not in vigentes and END_MARKER in path.read_text(
                    encoding="utf-8", errors="replace"):
                path.unlink()


def _destacados(libros: list[Book]) -> list[tuple[Book, object]]:
    """Los subrayados más largos del tema: los que desarrollan una idea."""
    candidatos = [(libro, hl) for libro in libros for hl in libro.highlights.values()
                  if hl.kind == "highlight" and 80 <= len(hl.text) <= 400]
    candidatos.sort(key=lambda par: -len(par[1].text))

    vistos: set[str] = set()
    salida = []
    for libro, hl in candidatos:          # como mucho uno por libro
        if libro.title in vistos:
            continue
        vistos.add(libro.title)
        salida.append((libro, hl))
        if len(salida) == _DESTACADOS:
            break
    return salida


def etiqueta(tema: str) -> str:
    texto = unicodedata.normalize("NFKD", tema)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^\w-]+", "-", texto).strip("-").lower()


def _rama(texto: str) -> str:
    limpio = re.sub(r"[()\[\]{}\"'`]", "", texto).strip()
    limpio = re.sub(r"\s+", " ", limpio)
    if len(limpio) > _MAX_RAMA:
        limpio = limpio[:_MAX_RAMA].rstrip() + "…"
    return limpio or "sin título"


def nombre_archivo(tema: str) -> str:
    """Nombre de fichero seguro para un tema, y por tanto su destino de enlace."""
    return re.sub(r'[\\/:*?"<>|]', "-", tema).strip() or SIN_CLASIFICAR


_sin_barras = nombre_archivo


def _yaml(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _cola_preservada(path: Path) -> str:
    if not path.exists():
        return ""
    contenido = path.read_text(encoding="utf-8", errors="replace")
    idx = contenido.find(END_MARKER)
    return "" if idx == -1 else contenido[idx + len(END_MARKER):]
