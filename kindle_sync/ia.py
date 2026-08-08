"""Clasificación de libros por temática usando la API de OpenAI.

Las palabras clave aciertan lo evidente y fallan con los títulos opacos: «The
Hard Thing About Hard Things» no dice de qué va. Un modelo que lee además una
muestra de los subrayados sí lo sabe.

Se pide la respuesta con un esquema JSON estricto, así que no hay que
interpretar texto libre, y los libros van por lotes para no hacer una petición
por libro.
"""

from __future__ import annotations

import json
import logging
import os
import re

from .categorias import SIN_CLASIFICAR, TAXONOMIA
from .models import Book

log = logging.getLogger("kindle-sync")

MODELO = "gpt-5.6-luna"
LOTE = 10                # libros por petición
SUBRAYADOS_POR_LIBRO = 8
LARGO_SUBRAYADO = 300
VARIABLE_CLAVE = "OPENAI_API_KEY"

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


class ErrorModelo(RuntimeError):
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
    return bool(os.environ.get(VARIABLE_CLAVE))


def cliente_openai():
    if not hay_clave():
        raise SinClave(
            f"Falta {VARIABLE_CLAVE}. Consíguela en https://platform.openai.com/api-keys "
            "y expórtala, o desactiva [ia] en la configuración.")
    import openai

    return openai.OpenAI()


def modelos_disponibles() -> list[str]:
    """Pregunta a la API qué modelos tiene disponibles esta cuenta."""
    return sorted(m.id for m in cliente_openai().models.list())


def clasificar_libros(libros: list[Book], categorias: list[str] | None = None,
                      modelo: str = MODELO, esfuerzo: str = "low",
                      lote: int = LOTE) -> dict[str, Veredicto]:
    """Clasifica libros con OpenAI. Devuelve {clave del libro: Veredicto}."""
    if not libros:
        return {}

    cliente = cliente_openai()
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
    mensajes = [
        {"role": "system", "content": SISTEMA},
        {"role": "user", "content": _peticion(libros, categorias)},
    ]
    texto = _pedir(cliente, mensajes, modelo, esfuerzo)

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


def _pedir(cliente, mensajes: list[dict], modelo: str, esfuerzo: str) -> str:
    """Lanza la petición, adaptándose a lo que el modelo y el SDK admitan.

    Los modelos de razonamiento aceptan `reasoning`; los demás lo rechazan. En
    vez de mantener una lista de qué modelo es de cada tipo —que caduca con
    cada lanzamiento— se intenta con el parámetro y se reintenta sin él.
    """
    formato = {
        "type": "json_schema",
        "json_schema": {"name": "clasificacion", "schema": ESQUEMA, "strict": True},
    }

    intentos = [{"reasoning_effort": esfuerzo}, {}] if esfuerzo else [{}]
    ultimo: Exception | None = None

    for extra in intentos:
        try:
            respuesta = cliente.chat.completions.create(
                model=modelo,
                messages=mensajes,
                response_format=formato,
                **extra,
            )
        except TypeError as exc:            # el SDK no conoce el parámetro
            ultimo = exc
            continue
        except Exception as exc:
            if extra and _es_parametro_no_admitido(exc):
                ultimo = exc
                continue
            raise ErrorModelo(_explicar(exc, modelo)) from exc

        return _texto(respuesta)

    raise ErrorModelo(_explicar(ultimo, modelo)) if ultimo else ErrorModelo("sin respuesta")


def _texto(respuesta) -> str:
    eleccion = respuesta.choices[0]
    if getattr(eleccion, "finish_reason", None) == "content_filter":
        log.warning("IA: respuesta bloqueada por el filtro de contenido")
        return ""
    return eleccion.message.content or ""


def _es_parametro_no_admitido(exc: Exception) -> bool:
    texto = str(exc).lower()
    return ("unsupported" in texto or "unrecognized" in texto
            or "unknown parameter" in texto) and "reasoning" in texto


def _explicar(exc: Exception | None, modelo: str) -> str:
    texto = str(exc or "")
    if re.search(r"model.*(not found|does not exist)|invalid.*model", texto, re.IGNORECASE):
        return (f"tu cuenta no reconoce el modelo «{modelo}». "
                "Mira cuáles tienes con: kindle-sync modelos")
    if re.search(r"invalid.*api key|incorrect api key", texto, re.IGNORECASE):
        return f"la clave de {VARIABLE_CLAVE} no es válida."
    if re.search(r"insufficient_quota|exceeded your current quota", texto, re.IGNORECASE):
        return "la cuenta de OpenAI no tiene saldo."
    return texto


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
