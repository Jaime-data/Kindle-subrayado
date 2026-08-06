"""Sondeo del Lector Web de Kindle (read.amazon.com).

El Cuaderno (`/notebook`) solo publica libros comprados. El lector web es otra
aplicación distinta y sí lista los documentos personales archivados, así que
puede ser la única vía para sacar sus subrayados sin cable y sin correo.

Este módulo no da nada por supuesto sobre el HTML: sondea varios selectores
candidatos, cuenta qué encuentra cada uno y guarda un volcado. Con esos datos
se escribe después el lector de verdad.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BIBLIOTECA_URL = "https://read.amazon.com/kindle-library"

# Selectores candidatos: los que Amazon ha usado en distintas versiones.
CANDIDATOS_LIBRO = (
    "#cover-art-grid li",
    "[id^='title-']",
    ".library-item",
    "[data-testid='library-item']",
    "li[role='listitem']",
    ".kp-notebook-library-each-book",
)
CANDIDATOS_FILTRO = (
    "#library-filter",
    "[data-testid='library-filter']",
    "select",
    "button[aria-haspopup]",
)


def sondear(state_file: Path, dump_dir: Path | None = None,
            timeout_s: int = 90) -> dict:
    """Abre la biblioteca del lector web y describe lo que encuentra."""
    from .amazon_cloud import NotLoggedIn

    if not state_file.exists():
        raise NotLoggedIn("No hay sesión guardada. Ejecuta primero: kindle-sync login")

    from playwright.sync_api import sync_playwright

    informe: dict = {"url": BIBLIOTECA_URL}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(state_file))
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)
            page.goto(BIBLIOTECA_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass  # la app sigue haciendo peticiones: seguimos igualmente
            _hasta_el_final(page)

            informe["url_final"] = page.url
            informe["titulo_pagina"] = page.title()
            informe["sesion_valida"] = "signin" not in page.url and "ap/" not in page.url
            informe["candidatos"] = {sel: _contar(page, sel) for sel in CANDIDATOS_LIBRO}
            informe["filtros"] = {sel: _contar(page, sel) for sel in CANDIDATOS_FILTRO}
            informe["muestras"] = _muestras(page)
            informe["menciona_documentos"] = bool(
                re.search(r"documento|personal doc|\bdocs\b", page.content(), re.IGNORECASE))

            if dump_dir:
                dump_dir.mkdir(parents=True, exist_ok=True)
                (dump_dir / "lector-biblioteca.html").write_text(
                    page.content(), encoding="utf-8")
                page.screenshot(path=str(dump_dir / "lector-biblioteca.png"), full_page=True)
                (dump_dir / "lector-informe.json").write_text(
                    json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
        finally:
            browser.close()
    return informe


def _hasta_el_final(page, vueltas: int = 10) -> None:
    """La biblioteca carga por scroll: bajamos hasta que deje de crecer."""
    anterior = -1
    for _ in range(vueltas):
        actual = len(page.query_selector_all("li, [id^='title-']"))
        if actual == anterior:
            return
        anterior = actual
        page.mouse.wheel(0, 20_000)
        page.wait_for_timeout(700)


def _contar(page, selector: str) -> int:
    try:
        return len(page.query_selector_all(selector))
    except Exception:
        return -1  # selector no válido en este DOM


def _muestras(page, cuantas: int = 6) -> list[str]:
    """Textos de los primeros elementos que parezcan entradas de biblioteca."""
    for selector in CANDIDATOS_LIBRO:
        elementos = []
        try:
            elementos = page.query_selector_all(selector)
        except Exception:
            continue
        if len(elementos) >= 2:
            return [" ".join(e.inner_text().split())[:80] for e in elementos[:cuantas]]
    return []
