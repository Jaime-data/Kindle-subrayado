"""Lector de subrayados desde el Cuaderno de Kindle (read.amazon.com/notebook).

Esta es la fuente que permite sincronizar *mientras lees*: cuando subrayas con
el Kindle conectado al Wi-Fi, Amazon sube la anotación a la nube en segundos.

Requisito: los libros importados tienen que haber llegado al Kindle vía
«Enviar a Kindle» (email o app), no arrastrados por USB. Solo así son
documentos personales sincronizados y sus notas viajan a la nube.

Usa Playwright con una sesión guardada; el login se hace una sola vez a mano
(`kindle-sync login`) porque Amazon exige contraseña + 2FA.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from ..models import Highlight

NOTEBOOK_URL = "https://read.amazon.com/notebook"

_LOC = re.compile(r"(?:posici[óo]n|location)\s*[:\s]\s*([\d.,]+)", re.IGNORECASE)
_PAGE = re.compile(r"(?:p[áa]gina|page)\s*[:\s]\s*([\w.]+)", re.IGNORECASE)


class NotLoggedIn(RuntimeError):
    pass


def login(state_file: Path, headless: bool = False, timeout_s: int = 300) -> None:
    """Abre un navegador para iniciar sesión a mano y guarda las cookies."""
    from playwright.sync_api import sync_playwright

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(NOTEBOOK_URL, wait_until="domcontentloaded")
        print("Inicia sesión en Amazon en la ventana que se ha abierto.")
        print("Cuando veas tu lista de libros, la sesión se guardará sola.")
        page.wait_for_selector("#kp-notebook-library", timeout=timeout_s * 1000)
        context.storage_state(path=str(state_file))
        browser.close()
    print(f"Sesión guardada en {state_file}")


@contextmanager
def _notebook(state_file: Path, timeout_s: int = 60):
    """Abre el Cuaderno de Kindle con la sesión guardada."""
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    if not state_file.exists():
        raise NotLoggedIn("No hay sesión guardada. Ejecuta primero: kindle-sync login")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(state_file))
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)
            page.goto(NOTEBOOK_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_selector("#kp-notebook-library", timeout=20_000)
            except PWTimeout as exc:
                raise NotLoggedIn(
                    "La sesión de Amazon ha caducado o la página ha cambiado. "
                    "Prueba: kindle-sync login (y si persiste, kindle-sync libros --dump)"
                ) from exc
            yield page
            context.storage_state(path=str(state_file))  # refresca cookies
        finally:
            browser.close()


def fetch(state_file: Path, only_personal_docs: bool = False,
          timeout_s: int = 60) -> list[Highlight]:
    """Descarga todos los subrayados del Cuaderno de Kindle."""
    out: list[Highlight] = []
    with _notebook(state_file, timeout_s) as page:
        for asin, title, author, is_personal in _library(page):
            if only_personal_docs and not is_personal:
                continue
            out.extend(_book_highlights(page, asin, title, author))
    return out


def list_books(state_file: Path, dump_dir: Path | None = None,
               timeout_s: int = 60) -> list[dict]:
    """Diagnóstico de solo lectura: qué ve el programa en tu cuenta.

    Con `dump_dir` guarda el HTML de las páginas, que es lo que necesitamos
    para arreglar los selectores si Amazon cambia su web.
    """
    out: list[dict] = []
    with _notebook(state_file, timeout_s) as page:
        if dump_dir:
            _dump(page, dump_dir, "biblioteca")
        for i, (asin, title, author, is_personal) in enumerate(_library(page)):
            highlights = _book_highlights(page, asin, title, author)
            if dump_dir and i == 0:
                _dump(page, dump_dir, "primer-libro")
            out.append({
                "asin": asin,
                "titulo": title,
                "autor": author,
                "documento_personal": is_personal,
                "subrayados": len(highlights),
            })
    return out


def _dump(page, dump_dir: Path, nombre: str) -> None:
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / f"{nombre}.html").write_text(page.content(), encoding="utf-8")
    page.screenshot(path=str(dump_dir / f"{nombre}.png"), full_page=True)


def _library(page) -> list[tuple[str, str, str | None, bool]]:
    rows = page.query_selector_all(".kp-notebook-library-each-book")
    books = []
    for row in rows:
        asin = row.get_attribute("id") or ""
        title_el = row.query_selector("h2")
        author_el = row.query_selector("p")
        if not asin or not title_el:
            continue
        author = (author_el.inner_text().strip() if author_el else "") or None
        if author:
            # Amazon lo formatea como "De: Nombre Apellido" / "By: ..."
            author = re.sub(r"^(de|by|por)\s*:?\s*", "", author, flags=re.IGNORECASE).strip(" .")
        # Los documentos personales no tienen ASIN de tienda (empiezan por CR!/ o similar).
        is_personal = not re.fullmatch(r"B[0-9A-Z]{9}", asin)
        books.append((asin, title_el.inner_text().strip(), author or None, is_personal))
    return books


def _book_highlights(page, asin: str, title: str, author: str | None) -> list[Highlight]:
    page.goto(f"{NOTEBOOK_URL}?asin={asin}&contentLimitState=&", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    out: list[Highlight] = []
    for el in page.query_selector_all("#kp-notebook-annotations .a-row.a-spacing-base"):
        text_el = el.query_selector("#highlight")
        note_el = el.query_selector("#note")
        header_el = el.query_selector("#annotationHighlightHeader, #annotationNoteHeader")
        loc_el = el.query_selector("#kp-annotation-location")

        text = text_el.inner_text().strip() if text_el else ""
        note = note_el.inner_text().strip() if note_el else ""
        if not text and not note:
            continue

        header = header_el.inner_text().strip() if header_el else ""
        location = loc_el.get_attribute("value") if loc_el else None
        if not location:
            m = _LOC.search(header)
            location = m.group(1) if m else None
        page_m = _PAGE.search(header)

        out.append(Highlight(
            book_title=title,
            book_author=author,
            text=text or note,
            note=(note or None) if text else None,
            kind="highlight" if text else "note",
            page=page_m.group(1) if page_m else None,
            location=location,
            source="cloud",
            asin=asin,
        ))
    return out
