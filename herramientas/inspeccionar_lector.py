#!/usr/bin/env python3
"""Descubre la estructura de un volcado del Lector Web de Kindle.

    python herramientas/inspeccionar_lector.py ~/Desktop/kindle-lector/lector-biblioteca.html

No da por supuesto ningún selector: mide qué hay. Busca identificadores de
libro, resume las clases y atributos que más se repiten (que es como se
reconoce una lista de elementos) y saca el JSON que la aplicación incrusta,
que suele traer la biblioteca entera.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

# Los libros comprados tienen ASIN «B» + 9. Los documentos personales usan
# otros formatos, y encontrarlos es justo el objetivo de esta herramienta.
ASIN_TIENDA = re.compile(r"\bB0[0-9A-Z]{8}\b")
ASIN_PERSONAL = re.compile(r"CR!\w+|\bA?[0-9A-Z]{8,}_(?:EBOK|PDOC)\b|\b\w+_PDOC\b")


class Estructura(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.clases: Counter[str] = Counter()
        self.testids: Counter[str] = Counter()
        self.otros_data: Counter[str] = Counter()
        self.ids: list[str] = []
        self.scripts: list[str] = []
        self._en_script = False

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        for clase in attrs.get("class", "").split():
            if not re.fullmatch(r"[a-z0-9_-]{1,4}", clase):  # ignora clases minificadas
                self.clases[clase] += 1
        if valor := attrs.get("data-testid"):
            self.testids[valor] += 1
        for nombre in attrs:
            if nombre.startswith("data-") and nombre != "data-testid":
                self.otros_data[nombre] += 1
        if ident := attrs.get("id"):
            self.ids.append(ident)
        if tag == "script":
            self._en_script = True

    def handle_data(self, data: str) -> None:
        if self._en_script and len(data) > 200:
            self.scripts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._en_script = False


def buscar_json_con_libros(scripts: list[str]) -> list[dict]:
    """Saca objetos con pinta de entrada de biblioteca del JSON incrustado."""
    hallados: list[dict] = []
    for script in scripts:
        for bruto in re.findall(r'\{[^{}]*"asin"\s*:\s*"[^"]+"[^{}]*\}', script, re.IGNORECASE):
            try:
                hallados.append(json.loads(bruto))
            except json.JSONDecodeError:
                claves = dict(re.findall(r'"(\w+)"\s*:\s*"([^"]{0,60})"', bruto))
                if claves:
                    hallados.append(claves)
    return hallados


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    path = Path(argv[1]).expanduser()
    if not path.exists():
        print(f"No existe: {path}")
        return 2

    html = path.read_text(encoding="utf-8", errors="replace")
    est = Estructura()
    est.feed(html)

    print("=" * 64)
    print(f"VOLCADO DEL LECTOR: {path.name}  ({len(html) // 1024} KB)")
    print("=" * 64)

    tienda = sorted(set(ASIN_TIENDA.findall(html)))
    personal = sorted(set(ASIN_PERSONAL.findall(html)))
    print(f"\n-- IDENTIFICADORES DE LIBRO --")
    print(f"  Comprados (ASIN B…) : {len(tienda)}  {tienda[:6]}")
    print(f"  Personales          : {len(personal)}  {personal[:6]}")

    print(f"\n-- CLASES MÁS REPETIDAS (candidatas a «una fila por libro») --")
    for clase, n in est.clases.most_common(15):
        if n > 1:
            print(f"  {n:>4}  .{clase[:60]}")

    print(f"\n-- data-testid --")
    for valor, n in est.testids.most_common(12) or [("(ninguno)", 0)]:
        print(f"  {n:>4}  {valor[:60]}")

    print(f"\n-- OTROS ATRIBUTOS data-* --")
    for nombre, n in est.otros_data.most_common(12) or [("(ninguno)", 0)]:
        print(f"  {n:>4}  {nombre[:60]}")

    print(f"\n-- IDs DE LA PÁGINA ({len(est.ids)}) --")
    for ident in est.ids[:20]:
        print(f"  #{ident[:60]}")

    objetos = buscar_json_con_libros(est.scripts)
    print(f"\n-- OBJETOS JSON CON «asin» ({len(objetos)}) --")
    for obj in objetos[:8]:
        resumen = {k: v for k, v in obj.items()
                   if k.lower() in ("asin", "title", "originType", "producttype",
                                    "origintype", "type", "authors")}
        print(f"  {resumen or obj}")

    print(f"\n-- SEÑALES DE ESTADO --")
    for patron, etiqueta in (
        (r"spinner|loading|cargando", "cargando"),
        (r"no results|sin resultados|empty|vac[íi]o", "vacío"),
        (r"sign ?in|iniciar sesi[óo]n|ap/signin", "pide login"),
        (r"librarylist|getLibrary|/service/web", "llamadas a la API de biblioteca"),
    ):
        encontrados = len(re.findall(patron, html, re.IGNORECASE))
        print(f"  {encontrados:>4}  {etiqueta}")

    endpoints = sorted({m.group(0) for m in re.finditer(
        r"/(?:service|api)/web/[\w/-]+", html)})[:10]
    if endpoints:
        print(f"\n-- ENDPOINTS QUE MENCIONA LA PÁGINA --")
        for endpoint in endpoints:
            print(f"  {endpoint}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
