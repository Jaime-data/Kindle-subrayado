"""El sondeo del lector web contra una biblioteca simulada."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from kindle_sync.sources import web_reader  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def servidor():
    handler = functools.partial(_Silencioso, directory=str(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class _Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def sesion(tmp_path):
    state = tmp_path / "session.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return state


def test_sondea_la_biblioteca_y_cuenta_entradas(monkeypatch, sesion, servidor, tmp_path):
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{servidor}/lector_biblioteca.html")
    dump = tmp_path / "dump"
    informe = web_reader.sondear(sesion, dump_dir=dump)

    assert informe["sesion_valida"] is True
    # La biblioteca se pinta por JavaScript: el sondeo debe esperarla.
    assert informe["candidatos"]["#cover-art-grid li"] == 2
    assert any("Informe interno" in m for m in informe["muestras"])
    assert (dump / "lector-biblioteca.html").exists()
    assert (dump / "lector-informe.json").exists()
    assert (dump / "lector-trafico.json").exists()


def test_graba_el_trafico_y_ve_los_documentos_personales(monkeypatch, sesion, servidor):
    """Lo que decide todo: si la respuesta de la API trae documentos personales."""
    monkeypatch.setattr(web_reader, "BIBLIOTECA_URL", f"{servidor}/lector_biblioteca.html")
    informe = web_reader.sondear(sesion)

    respuestas = informe["trafico"]
    assert respuestas, "no se grabó ninguna respuesta con libros"
    personales = [a for r in respuestas for a in r.get("asin_personal", [])]
    assert "CR!A1B2C3D4E5" in personales
    assert any(r["asin_tienda"] for r in respuestas)


def test_sin_sesion_avisa(tmp_path):
    from kindle_sync.sources.amazon_cloud import NotLoggedIn

    with pytest.raises(NotLoggedIn, match="kindle-sync login"):
        web_reader.sondear(tmp_path / "no-existe.json")
