"""Clasificación de libros por temática usando Claude.

Las palabras clave aciertan lo evidente y fallan con los títulos opacos: «The
Hard Thing About Hard Things» no dice de qué va. Un modelo que lee además una
muestra de los subrayados sí lo sabe.

Se pide la respuesta con un esquema JSON (structured outputs), así que no hay
que interpretar texto libre, y los libros van por lotes para no hacer una
petición por libro.
"""

from __future__ import annotations

import json
import logging
import os
import re

from .categorias import SIN_CLASIFICAR, TAXONOMIA
from .models import Book

log = logging.getLogger("kindle-sync")

MODELO = "claude-opus-5"
LOTE = 10                # libros por petición
SUBRAYADOS_POR_LIBRO = 8
LARGO_SUBRAYADO = 300

SISTEMA = """\
Eres un bibliotecario que ordena la biblioteca personal de alguien para que \
pueda navegarla por temas.

Para cada libro recibes el título, el autor y una muestra de los subrayados que \
esa persona hizo al leerlo. Los subrayados son la mejor pista: revelan de qué \
trata el libro de verdad y qué le interesó de él.

Reglas:
- Reutiliza una de las categorías existentes siempre que encaje razonablemente. \
Solo propón una nueva si ninguna sirve, y entonces que sea igual de general \
(un tema, no el asunto de un libro concreto).
- Una categoría por libro: la principal, no todas las que roza.
- La descripción es una sola frase, en español, sobre de qué trata el libro. \
Sin adjetivos publicitarios.
- Si los subrayados no bastan para decidir, di confianza "baja" en vez de \
inventar.
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "libros": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer",
                           "description": "El número que acompaña al libro en la lista"},
                    "categoria": {"type": "string"},
                    "descripcion": {"type": "string",
                                    "description": "Una frase sobre de qué trata"},
                    "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
                },
                "required": ["id", "categoria", "descripcion", "confianza"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["libros"],
    "additionalProperties": False,
}


class SinClave(RuntimeError):
    pass


class Veredicto:
    __slots__ = ("categoria", "descripcion", "confianza")

    def __init__(self, categoria: str, descripcion: str = "", confianza: str = "media"):
        self.categoria = categoria
        self.descripcion = descripcion
        self.confianza = confianza

    def __repr__(self) -> str:
        return f"Veredicto({self.categoria!r}, {self.confianza!r})"


def hay_clave() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def clasificar_libros(libros: list[Book], categorias: list[str] | None = None,
                      modelo: str = MODELO, esfuerzo: str = "low",
                      lote: int = LOTE) -> dict[str, Veredicto]:
    """Clasifica libros con Claude. Devuelve {clave del libro: Veredicto}."""
    if not libros:
        return {}
    if not hay_clave():
        raise SinClave(
            "Falta ANTHROPIC_API_KEY. Consíguela en https://console.anthropic.com "
            "y expórtala, o desactiva [ia] en la configuración.")

    import anthropic

    cliente = anthropic.Anthropic()
    conocidas = list(categorias or TAXONOMIA)
    salida: dict[str, Veredicto] = {}

    for i in range(0, len(libros), lote):
        trozo = libros[i:i + lote]
        log.info("IA: clasificando %d libro(s) (%d/%d)",
                 len(trozo), i + len(trozo), len(libros))
        salida.update(_clasificar_lote(cliente, trozo, conocidas, modelo, esfuerzo))
        # Las categorías nuevas quedan disponibles para los lotes siguientes,
        # para que no invente tres nombres distintos para el mismo tema.
        for veredicto in salida.values():
            if veredicto.categoria not in conocidas:
                conocidas.append(veredicto.categoria)

    return salida


def _clasificar_lote(cliente, libros: list[Book], categorias: list[str],
                     modelo: str, esfuerzo: str) -> dict[str, Veredicto]:
    respuesta = cliente.messages.create(
        model=modelo,
        max_tokens=16000,
        system=SISTEMA,
        output_config={
            "effort": esfuerzo,
            "format": {"type": "json_schema", "schema": ESQUEMA},
        },
        messages=[{"role": "user", "content": _peticion(libros, categorias)}],
    )

    if respuesta.stop_reason == "refusal":
        log.warning("IA: la petición fue rechazada; se deja sin clasificar")
        return {}

    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        log.warning("IA: respuesta ilegible, se deja sin clasificar")
        return {}

    salida: dict[str, Veredicto] = {}
    for item in datos.get("libros", []):
        indice = item.get("id")
        if not isinstance(indice, int) or not 1 <= indice <= len(libros):
            continue
        categoria = _normalizar(item.get("categoria", ""), categorias)
        salida[libros[indice - 1].key] = Veredicto(
            categoria,
            str(item.get("descripcion", "")).strip(),
            str(item.get("confianza", "media")).strip().lower(),
        )
    return salida


def _peticion(libros: list[Book], categorias: list[str]) -> str:
    partes = ["Categorías existentes:",
              *(f"- {c}" for c in categorias),
              "", "Libros:"]

    for i, libro in enumerate(libros, start=1):
        partes.append(f"\n[{i}] «{libro.title}»"
                      + (f", de {libro.author}" if libro.author else ""))
        muestras = _muestra(libro)
        if muestras:
            partes.append("Subrayados:")
            partes += [f"  · {s}" for s in muestras]
        else:
            partes.append("(sin subrayados legibles)")

    return "\n".join(partes)


def _muestra(libro: Book) -> list[str]:
    """Subrayados representativos: los más largos desarrollan la idea."""
    textos = [h.text.strip() for h in libro.sorted_highlights()
              if h.kind == "highlight" and h.text.strip()]
    textos.sort(key=len, reverse=True)
    return [re.sub(r"\s+", " ", t)[:LARGO_SUBRAYADO]
            for t in textos[:SUBRAYADOS_POR_LIBRO]]


def _normalizar(categoria: str, conocidas: list[str]) -> str:
    """Evita que «negocios» y «Negocios» acaben como dos temas distintos."""
    limpia = re.sub(r"\s+", " ", categoria).strip(" .")
    if not limpia:
        return SIN_CLASIFICAR
    for conocida in conocidas:
        if conocida.casefold() == limpia.casefold():
            return conocida
    return limpia[:60]
