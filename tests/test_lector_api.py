"""Consulta a la API de biblioteca del lector web.

Levanta un servidor que imita `/kindle-library/search`: devuelve libros para
libraryType=BOOKS y documentos personales para DOCS, que es justo la
distinción que hay que descubrir en la cuenta real.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from kindle_sync.sources import web_reader  # noqa: E402

RESPUESTAS = {
    "BOOKS": [{"asin": "B07VMW25TP", "title": "El Plan de Marketing",
               "authors": ["Allan Dib"], "resourceType": "EBOOK"}],
    "DOCS": [{"asin": "CR!A1B2C3D4E5", "title": "Informe interno de LocalMetric",
              "authors": ["Jaime Vicente"], "resourceType": "PDOC"},
             {"asin": "CR!F6G7H8I9J0", "title": "Apuntes de producto",
              "authors": [], "resourceType": "PDOC"}],
}


class _Api(BaseHTTPRequestHandler):
    def do_GET(self):
        partes = urlparse(self.path)
        if partes.path == "/kindle-library/search":
            tipo = parse_qs(partes.query).get("libraryType", [""])[0]
            cuerpo = json.dumps({"itemsList": RESPUESTAS.get(tipo, []),
                                 "libraryType": tipo}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            cuerpo = b"<html><head><meta charset='utf-8'></head><body>Kindle</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def api():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def sesion(tmp_path):
    state = tmp_path / "session.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return state


def test_encuentra_los_documentos_personales_en_su_tipo(monkeypatch, sesion, api):
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{api}/kindle-library")
    resultados = {r["tipo"]: r for r in
                  web_reader.explorar_biblioteca(sesion, tipos=("BOOKS", "DOCS", "PDOC"))}

    assert resultados["BOOKS"]["elementos"] == 1
    assert resultados["DOCS"]["elementos"] == 2
    assert resultados["PDOC"]["elementos"] == 0

    docs = resultados["DOCS"]
    assert docs["asins"] == ["CR!A1B2C3D4E5", "CR!F6G7H8I9J0"]
    assert "Informe interno de LocalMetric" in docs["titulos"]
    assert "resourceType" in docs["claves"]


def test_un_tipo_inexistente_no_rompe(monkeypatch, sesion, api):
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{api}/kindle-library")
    (r,) = web_reader.explorar_biblioteca(sesion, tipos=("INVENTADO",))
    assert r["estado"] == 200
    assert r["elementos"] == 0


JS_BUNDLE = """
    var e = {libraryType: "BOOKS"}, t = ["BOOKS", "KINDLE_EBOOK", "PERSONAL_DOC"];
    function q(libraryType) { return fetch("/kindle-library/search?libraryType=" + libraryType) }
    var paths = ["/kindle-library/mutate", "/service/web/reader/annotations"];
"""


class _ApiConBundle(_Api):
    def do_GET(self):
        if self.path.endswith(".js"):
            cuerpo = JS_BUNDLE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return
        if self.path.startswith("/kindle-library") and ".js" not in self.path \
                and "search" not in self.path:
            cuerpo = (b"<html><head><meta charset='utf-8'>"
                      b"<script src='/app.js'></script></head><body>Kindle</body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return
        super().do_GET()


@pytest.fixture(scope="module")
def api_con_bundle():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ApiConBundle)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_saca_los_tipos_validos_del_javascript(monkeypatch, sesion, api_con_bundle):
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{api_con_bundle}/kindle-library")
    hallazgos = web_reader.analizar_bundle(sesion)

    assert "BOOKS" in hallazgos["library_type"]
    # Los valores del enum aparecen cerca, aunque no estén asignados directamente.
    assert "PERSONAL_DOC" in hallazgos["mayusculas_cerca"]
    assert "/kindle-library/mutate" in hallazgos["rutas"]
    assert "/service/web/reader/annotations" in hallazgos["rutas"]


def test_prueba_variantes_de_la_consulta(monkeypatch, sesion, api_con_bundle):
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{api_con_bundle}/kindle-library")
    variantes = web_reader.probar_variantes(sesion, tipo="BOOKS")

    assert len(variantes) == len(web_reader.VARIANTES)
    assert all(v["estado"] == 200 for v in variantes)
    assert all(v["json"] for v in variantes)
