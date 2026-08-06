#!/usr/bin/env python3
"""Resume un volcado de `kindle-sync libros --dump` en texto pegable.

    python herramientas/inspeccionar_volcado.py ~/Desktop/kindle-dump/biblioteca.html

Enseña los controles de filtrado, las entradas de la biblioteca y las pistas
sobre documentos personales que haya en la página, sin volcar el HTML entero
(son megas) y sin sacar nada que identifique tu cuenta.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

INTERESANTES = ("library", "notebook", "filter", "personal", "doc")
PALABRAS = ("personal", "documento", "document", "libro", "book", "todos", "all", "filtr")


class Resumen(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.controles: list[str] = []
        self.libros: list[tuple[str, str]] = []
        self.contenedores: list[str] = []
        self._ruta: list[str] = []
        self._captura: str | None = None
        self._cierra_con: str | None = None
        self._texto: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        ident = attrs.get("id", "")
        clases = attrs.get("class", "")
        etiqueta = f"{ident} {clases}".lower()

        if tag in ("select", "option", "button", "a") and any(p in etiqueta for p in ("filter", "sort", "dropdown")):
            self.controles.append(_describe(tag, ident, clases))
            self._captura = "control"
            self._cierra_con = tag  # un <select> se cierra en </select>, no en </option>
            self._texto = []
        elif "kp-notebook-library-each-book" in clases:
            self._captura = "libro"
            self._texto = []
            self._ruta.append(ident)
        elif tag == "div" and ident and any(p in ident.lower() for p in INTERESANTES):
            self.contenedores.append(ident)

    def handle_data(self, data: str) -> None:
        if self._captura and (limpio := data.strip()):
            self._texto.append(limpio)

    def handle_endtag(self, tag: str) -> None:
        if self._captura == "control" and tag == self._cierra_con:
            if self._texto and self.controles:
                self.controles[-1] += "  → opciones: " + " | ".join(self._texto)[:120]
            self._captura = None
        elif self._captura == "libro" and tag == "div" and self._ruta:
            self.libros.append((self._ruta.pop(), " · ".join(self._texto[:2])[:70]))
            self._captura = None


def _describe(tag: str, ident: str, clases: str) -> str:
    partes = [f"<{tag}>"]
    if ident:
        partes.append(f"id={ident}")
    if clases:
        partes.append(f"class={clases[:50]}")
    return " ".join(partes)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    path = Path(argv[1]).expanduser()
    if not path.exists():
        print(f"No existe: {path}")
        return 2

    html = path.read_text(encoding="utf-8", errors="replace")
    resumen = Resumen()
    resumen.feed(html)

    print("=" * 62)
    print(f"VOLCADO: {path.name}  ({len(html) // 1024} KB)")
    print("=" * 62)

    print(f"\n-- LIBROS EN LA BIBLIOTECA ({len(resumen.libros)}) --")
    for ident, texto in resumen.libros:
        tipo = "tienda  " if re.fullmatch(r"B[0-9A-Z]{9}", ident) else "PERSONAL"
        print(f"  [{tipo}] {ident:<16} {texto}")

    print(f"\n-- CONTROLES DE FILTRADO ({len(resumen.controles)}) --")
    for control in resumen.controles or ["  (ninguno)"]:
        print(f"  {control}")

    print(f"\n-- CONTENEDORES RELEVANTES ({len(resumen.contenedores)}) --")
    for ident in sorted(set(resumen.contenedores)):
        print(f"  #{ident}")

    print("\n-- MENCIONES A DOCUMENTOS PERSONALES --")
    encontradas = set()
    for m in re.finditer(r"[^<>]{0,60}(documentos?\s+personal\w*|personal\s+documents?)[^<>]{0,60}",
                         html, re.IGNORECASE):
        encontradas.add(" ".join(m.group().split())[:110])
    for frase in sorted(encontradas)[:15] or ["  (ninguna)"]:
        print(f"  …{frase}…")

    print("\n-- CONTADORES QUE DECLARA LA PÁGINA --")
    for m in re.finditer(r'(?:id|class)="([^"]*(?:count|total|library-pagination|next-page)[^"]*)"',
                         html, re.IGNORECASE):
        print(f"  {m.group(1)[:70]}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
