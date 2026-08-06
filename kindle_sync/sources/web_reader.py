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


ASIN_TIENDA = re.compile(r"\bB0[0-9A-Z]{8}\b")
ASIN_PERSONAL = re.compile(r"CR!\w+|\b\w{6,}_PDOC\b", re.IGNORECASE)


def sondear(state_file: Path, dump_dir: Path | None = None,
            timeout_s: int = 120) -> dict:
    """Abre la biblioteca del lector web y describe lo que encuentra.

    La biblioteca se pinta en el navegador después de pedir los datos por su
    cuenta, así que además del HTML se graba el tráfico: la respuesta cruda de
    Amazon es mucho más fiable que adivinar clases minificadas.
    """
    from .amazon_cloud import NotLoggedIn

    if not state_file.exists():
        raise NotLoggedIn("No hay sesión guardada. Ejecuta primero: kindle-sync login")

    from playwright.sync_api import sync_playwright

    informe: dict = {"url": BIBLIOTECA_URL}
    trafico: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(state_file))
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)
            page.on("response", lambda r: _anotar(r, trafico))

            page.goto(BIBLIOTECA_URL, wait_until="domcontentloaded")
            _esperar_biblioteca(page)
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass  # la app sigue haciendo peticiones: seguimos igualmente
            _hasta_el_final(page)
            informe["trafico"] = _resumir_trafico(trafico)
            informe["itemViewResponse"] = _elemento(page, "#itemViewResponse")

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
                (dump_dir / "lector-trafico.json").write_text(
                    json.dumps(trafico, indent=2, ensure_ascii=False)[:2_000_000],
                    encoding="utf-8")
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


def _anotar(respuesta, destino: list[dict]) -> None:
    """Guarda cada respuesta que pueda contener la biblioteca."""
    tipo = (respuesta.headers or {}).get("content-type", "")
    if "json" not in tipo and "javascript" not in tipo:
        return
    entrada = {"url": respuesta.url[:200], "estado": respuesta.status, "tipo": tipo[:40]}
    try:
        cuerpo = respuesta.text()
    except Exception:
        entrada["cuerpo"] = "(no se pudo leer)"
        destino.append(entrada)
        return

    entrada["bytes"] = len(cuerpo)
    entrada["asin_tienda"] = len(set(ASIN_TIENDA.findall(cuerpo)))
    entrada["asin_personal"] = sorted(set(ASIN_PERSONAL.findall(cuerpo)))[:5]
    if '"asin"' in cuerpo.lower() or entrada["asin_tienda"] or entrada["asin_personal"]:
        entrada["muestra"] = cuerpo[:1500]
    destino.append(entrada)


def _resumir_trafico(trafico: list[dict]) -> list[dict]:
    """Deja solo las respuestas que parecen traer libros."""
    interesantes = [t for t in trafico
                    if t.get("asin_tienda") or t.get("asin_personal") or "muestra" in t]
    return interesantes[:15]


def _esperar_biblioteca(page, timeout_ms: int = 60_000) -> None:
    """Espera a que la aplicación pinte los libros, no solo el armazón."""
    try:
        page.wait_for_function(
            """() => {
                const html = document.body.innerHTML;
                return /B0[0-9A-Z]{8}/.test(html)
                    || /CR!|_PDOC/i.test(html)
                    || document.querySelectorAll('#web-library-root *').length > 300;
            }""",
            timeout=timeout_ms)
    except Exception:
        pass  # puede que la biblioteca esté vacía: seguimos y lo reflejamos


def _elemento(page, selector: str) -> str:
    try:
        el = page.query_selector(selector)
        if el is None:
            return "(no existe)"
        return (el.inner_text() or el.get_attribute("value") or "")[:1500]
    except Exception:
        return "(no legible)"


# La biblioteca del lector se pide por tipo. El HTML inicial trae
# {"itemsList":[],"libraryType":"BOOKS"}, así que hay más tipos que probar:
# los documentos personales tienen que estar bajo alguno de estos.
TIPOS_BIBLIOTECA = ("BOOKS", "DOCS", "PDOC", "PERSONAL_DOCS", "KINDLE_DOCS",
                    "ALL", "SAMPLES", "AUDIBLE")

CONSULTA = ("/kindle-library/search"
            "?query=&libraryType={tipo}&paginationToken=&sortType=recency&querySize=50")


def explorar_biblioteca(state_file: Path, tipos: tuple[str, ...] = TIPOS_BIBLIOTECA,
                        timeout_s: int = 90) -> list[dict]:
    """Pregunta a la API del lector por cada tipo de biblioteca.

    La petición se lanza desde dentro de la página para que viaje con las
    mismas cookies y cabeceras que usa la aplicación: pedirla por fuera
    suele acabar en un 403.
    """
    from .amazon_cloud import NotLoggedIn

    if not state_file.exists():
        raise NotLoggedIn("No hay sesión guardada. Ejecuta primero: kindle-sync login")

    from playwright.sync_api import sync_playwright

    resultados: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(state_file))
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)
            page.goto(BIBLIOTECA_URL, wait_until="domcontentloaded")

            for tipo in tipos:
                resultados.append(_consultar(page, tipo))
        finally:
            browser.close()
    return resultados


def _consultar(page, tipo: str) -> dict:
    respuesta = page.evaluate(
        """async (ruta) => {
            try {
                const r = await fetch(ruta, {credentials: 'include'});
                return {estado: r.status, cuerpo: (await r.text()).slice(0, 20000)};
            } catch (e) {
                return {estado: -1, cuerpo: String(e)};
            }
        }""",
        CONSULTA.format(tipo=tipo))

    cuerpo = respuesta.get("cuerpo", "")
    salida = {"tipo": tipo, "estado": respuesta.get("estado"), "elementos": 0,
              "titulos": [], "asins": []}
    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError:
        salida["error"] = cuerpo[:200]
        return salida

    items = datos.get("itemsList") or datos.get("items") or []
    salida["elementos"] = len(items)
    salida["titulos"] = [str(i.get("title", ""))[:60] for i in items[:5]]
    salida["asins"] = [str(i.get("asin", "")) for i in items[:5]]
    salida["claves"] = sorted(items[0].keys())[:20] if items else []
    return salida
