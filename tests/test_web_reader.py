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
    assert informe["candidatos"]["#cover-art-grid li"] == 3
    assert informe["menciona_documentos"] is True
    assert any("Informe interno" in m for m in informe["muestras"])
    assert (dump / "lector-biblioteca.html").exists()
    assert (dump / "lector-informe.json").exists()


def test_sin_sesion_avisa(tmp_path):
    from kindle_sync.sources.amazon_cloud import NotLoggedIn

    with pytest.raises(NotLoggedIn, match="kindle-sync login"):
        web_reader.sondear(tmp_path / "no-existe.json")
