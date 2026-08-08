"""Clasifica cada libro por tema, para poder agruparlos en el índice.

Funciona sin conexión ni claves: puntúa palabras clave en el título, el autor
y una muestra de los subrayados. No pretende acertar siempre — pretende no
equivocarse en lo evidente y dejarse corregir a mano desde la configuración.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

SIN_CLASIFICAR = "Sin clasificar"

# Los subrayados desempatan, pero no deciden: su aportación va topada para que
# no puedan superar a la señal del título.
TOPE_TEXTOS = 5

# Palabras que delatan un tema. Se buscan en español e inglés porque las
# bibliotecas suelen estar mezcladas.
TAXONOMIA: dict[str, tuple[str, ...]] = {
    "Negocios": (
        "business", "negocio", "empresa", "company", "startup", "emprend",
        "agencia", "agency", "revenue", "facturac", "modelo de negocio",
        "escalar", "scale", "myth", "traction", "ceo", "founder", "socio",
    ),
    "Marketing y ventas": (
        "marketing", "advertis", "publicidad", "venta", "sales", "vendedor",
        "copywriting", "anuncio", "brand", "marca", "conversion", "embudo",
        "funnel", "cliente potencial", "lead", "persuas", "seo", "cashvertising",
    ),
    "Liderazgo y equipos": (
        "liderazgo", "leader", "manage", "equipo", "team", "candor",
        "cultura", "culture", "contratar", "hiring", "jefe", "boss",
        "feedback", "delega", "remote", "teletrabajo",
    ),
    "Psicología y comportamiento": (
        "psicolog", "psychology", "mente", "mind", "comportamiento", "behavior",
        "hábito", "habit", "emocion", "emotion", "sesgo", "bias", "cerebro",
        "brain", "influence", "persuasion",
    ),
    "Productividad": (
        "productiv", "foco", "focus", "deep work", "céntrate", "centrate",
        "distract", "atención", "attention", "time management",
        "hábitos atómicos", "getting things done", "procrastin",
    ),
    "Inversión y finanzas": (
        "invertir", "invest", "finanz", "financ", "dinero", "money", "bolsa",
        "stock", "portfolio", "cartera", "riqueza", "wealth", "angel",
        "capital", "valoración", "ahorro",
    ),
    "Creatividad e ideas": (
        "creativ", "innovac", "innovation", "whack", "imaginac",
        "storytelling", "narrativ", "relato", "diseño", "design",
    ),
    "Estrategia y poder": (
        "poder", "power", "estrategia", "strategy", "guerra", "war",
        "48 leyes", "maquiavel", "negociac", "negotiat", "competenc",
    ),
    "Filosofía y pensamiento": (
        "filosof", "philosoph", "antifrágil", "antifragil", "taleb", "azar",
        "incertidumbre", "uncertainty", "estoic", "stoic", "sabiduría",
        "pensar", "thinking",
    ),
    "Ficción y literatura": (
        "novela", "novel", "1984", "orwell", "ficción", "fiction", "cuento",
        "poesía", "literatura", "distop",
    ),
    "Tecnología": (
        "software", "programming", "código fuente", "programming language",
        "inteligencia artificial", "machine learning", "algoritmo",
    ),
}


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def clasificar(titulo: str, autor: str | None = None,
               textos: list[str] | None = None) -> tuple[str, int]:
    """Devuelve (categoría, puntuación). Puntuación 0 significa que no se sabe.

    El título pesa mucho más que los subrayados: un libro de negocios cita de
    pasada la palabra «cerebro» sin ser de psicología.
    """
    titulo_n = _sin_tildes(titulo)
    autor_n = _sin_tildes(autor or "")
    textos_n = _sin_tildes(" ".join((textos or [])[:40]))

    puntos: Counter[str] = Counter()
    for categoria, palabras in TAXONOMIA.items():
        del_texto = 0
        for palabra in palabras:
            aguja = _sin_tildes(palabra)
            if aguja in titulo_n:
                puntos[categoria] += 6
            if autor_n and aguja in autor_n:
                puntos[categoria] += 3
            if textos_n:
                # Repetir la misma palabra no multiplica la certeza.
                del_texto += min(len(re.findall(re.escape(aguja), textos_n)), 3)
        # Los subrayados solo desempatan: un libro de negocios menciona
        # «cerebro» de pasada sin ser de psicología.
        puntos[categoria] += min(del_texto, TOPE_TEXTOS)

    puntos = Counter({c: p for c, p in puntos.items() if p})

    if not puntos:
        return SIN_CLASIFICAR, 0

    categoria, puntuacion = puntos.most_common(1)[0]
    return categoria, puntuacion


def categorias_conocidas() -> list[str]:
    return list(TAXONOMIA) + [SIN_CLASIFICAR]
