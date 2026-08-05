"""Comprueba el scraper del Cuaderno de Kindle contra páginas de ejemplo.

No toca la red: carga con Chromium unas réplicas locales del HTML de
read.amazon.com. Si Amazon cambia su web, estos ficheros de `fixtures/` son
lo que hay que actualizar (`kindle-sync libros --dump` genera el HTML real).
"""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from kindle_sync.sources import amazon_cloud  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def servidor():
    """Sirve los fixtures por HTTP: Amazon usa query strings (?asin=…),
    que un file:// no sabe resolver."""
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # sin ruido en la salida de los tests
        pass


@pytest.fixture
def biblioteca_url(servidor):
    return f"{servidor}/notebook_biblioteca.html"


@pytest.fixture
def libro_url(servidor):
    return f"{servidor}/notebook_libro.html"


@pytest.fixture
def page():
    """Navegador de un solo test: Playwright síncrono no se puede anidar."""
    try:
        with playwright_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            yield browser.new_page()
            browser.close()
    except Exception as exc:  # navegador no instalado en esta máquina
        pytest.skip(f"Chromium no disponible: {exc}")


@pytest.fixture
def sesion_falsa(tmp_path):
    state = tmp_path / "session.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return state


def test_lee_la_biblioteca_y_distingue_documentos_personales(page, biblioteca_url):
    page.goto(biblioteca_url)
    libros = amazon_cloud._library(page)

    assert [b[1] for b in libros] == ["Sapiens", "Informe interno 2025", "Apuntes sueltos"]

    sapiens, informe, apuntes = libros
    assert sapiens[2] == "Yuval Noah Harari"  # quita el prefijo "De:"
    assert sapiens[3] is False                # ASIN de tienda
    assert informe[3] is True                 # documento personal importado
    assert apuntes[2] is None                 # sin autor, no revienta


def test_lee_subrayados_notas_y_posiciones(page, libro_url, monkeypatch):
    monkeypatch.setattr(amazon_cloud, "NOTEBOOK_URL", libro_url)
    hls = amazon_cloud._book_highlights(page, "B00ABCDEFG", "Sapiens", "Yuval Noah Harari")

    assert len(hls) == 3  # la cuarta anotación está vacía y se descarta

    primero, segundo, nota = hls
    assert primero.kind == "highlight"
    assert primero.text == "Los humanos evolucionaron para pensar en individuos."
    assert primero.location == "356"
    assert primero.page == "24"
    assert primero.note is None
    assert primero.source == "cloud"
    assert primero.asin == "B00ABCDEFG"

    assert segundo.note == "Enlazar con el capítulo de imperios."

    assert nota.kind == "note"
    assert nota.text == "Una nota suelta sin subrayado."


def test_fetch_completo_contra_una_pagina_local(monkeypatch, sesion_falsa, libro_url):
    monkeypatch.setattr(amazon_cloud, "NOTEBOOK_URL", libro_url)
    hls = amazon_cloud.fetch(sesion_falsa)

    assert len(hls) == 3
    assert {h.book_title for h in hls} == {"Sapiens"}


def test_list_books_vuelca_html_para_depurar(monkeypatch, sesion_falsa, tmp_path, libro_url):
    monkeypatch.setattr(amazon_cloud, "NOTEBOOK_URL", libro_url)
    dump = tmp_path / "dump"
    libros = amazon_cloud.list_books(sesion_falsa, dump_dir=dump)

    assert libros == [{
        "asin": "B00ABCDEFG",
        "titulo": "Sapiens",
        "autor": "Yuval Noah Harari",
        "documento_personal": False,
        "subrayados": 3,
    }]
    assert (dump / "biblioteca.html").exists()
    assert (dump / "primer-libro.png").exists()


def test_sin_sesion_guardada_avisa(tmp_path):
    with pytest.raises(amazon_cloud.NotLoggedIn, match="kindle-sync login"):
        amazon_cloud.fetch(tmp_path / "no-existe.json")
