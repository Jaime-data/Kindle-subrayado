"""Clasificación por temática con Claude.

No toca la red: se sustituye el cliente de Anthropic por uno que devuelve
respuestas fabricadas, para poder fijar el contrato — qué se le manda al
modelo y qué se hace con lo que responde.
"""

import json
import sys
import types

import pytest

from kindle_sync import config as cfg
from kindle_sync.ia import SinClave, clasificar_libros
from kindle_sync.models import Book, Highlight
from kindle_sync.sync import Syncer


class _Bloque:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Respuesta:
    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [_Bloque(json.dumps(payload))] if payload is not None else []
        self.stop_reason = stop_reason


class _Mensajes:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return self.respuestas.pop(0)


class _Cliente:
    def __init__(self, respuestas):
        self.messages = _Mensajes(respuestas)


@pytest.fixture
def anthropic_falso(monkeypatch):
    """Sustituye el módulo anthropic y la clave del entorno."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-mentira")
    creados = []

    def instalar(*respuestas):
        cliente = _Cliente(respuestas)
        creados.append(cliente)
        modulo = types.ModuleType("anthropic")
        modulo.Anthropic = lambda *a, **k: cliente
        monkeypatch.setitem(sys.modules, "anthropic", modulo)
        return cliente

    return instalar


def _libro(titulo, autor=None, textos=()):
    libro = Book(title=titulo, author=autor)
    for i, texto in enumerate(textos, start=1):
        libro.add(Highlight(book_title=titulo, book_author=autor,
                            text=texto, location=str(i * 10)))
    return libro


def test_clasifica_y_describe(anthropic_falso):
    cliente = anthropic_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "Liderazgo y equipos",
         "descripcion": "Cómo dirigir equipos siendo honesto sin ser cruel.",
         "confianza": "alta"},
    ]}))

    libros = [_libro("The Hard Thing About Hard Things", "Ben Horowitz",
                     ["Contratar a un ejecutivo para tu startup es distinto."])]
    veredictos = clasificar_libros(libros)

    veredicto = veredictos[libros[0].key]
    assert veredicto.categoria == "Liderazgo y equipos"
    assert veredicto.descripcion.startswith("Cómo dirigir")
    assert veredicto.confianza == "alta"

    (llamada,) = cliente.messages.llamadas
    assert llamada["model"] == "claude-opus-5"
    # Structured outputs: el esquema evita tener que interpretar texto libre.
    assert llamada["output_config"]["format"]["type"] == "json_schema"
    assert llamada["output_config"]["effort"] == "low"


def test_manda_titulo_autor_y_subrayados(anthropic_falso):
    cliente = anthropic_falso(_Respuesta({"libros": []}))
    clasificar_libros([_libro("Antifrágil", "Nassim Taleb",
                              ["Lo que no mata al sistema lo hace más fuerte."])])

    mensaje = cliente.messages.llamadas[0]["messages"][0]["content"]
    assert "Antifrágil" in mensaje
    assert "Nassim Taleb" in mensaje
    assert "Lo que no mata al sistema" in mensaje
    assert "Negocios" in mensaje          # las categorías conocidas van de guía


def test_los_libros_van_por_lotes(anthropic_falso):
    """Veinte libros no son veinte peticiones."""
    cliente = anthropic_falso(_Respuesta({"libros": []}), _Respuesta({"libros": []}))
    clasificar_libros([_libro(f"Libro {i}") for i in range(20)], lote=10)

    assert len(cliente.messages.llamadas) == 2


def test_una_categoria_nueva_se_reutiliza_en_el_lote_siguiente(anthropic_falso):
    """Si no, inventaría tres nombres distintos para el mismo tema."""
    cliente = anthropic_falso(
        _Respuesta({"libros": [{"id": 1, "categoria": "Náutica",
                                "descripcion": "d", "confianza": "alta"}]}),
        _Respuesta({"libros": []}),
    )
    clasificar_libros([_libro("Uno"), _libro("Dos")], lote=1)

    segunda = cliente.messages.llamadas[1]["messages"][0]["content"]
    assert "Náutica" in segunda


def test_normaliza_las_mayusculas_de_la_categoria(anthropic_falso):
    anthropic_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "negocios  ", "descripcion": "", "confianza": "media"},
    ]}))
    libros = [_libro("Uno")]
    assert clasificar_libros(libros)[libros[0].key].categoria == "Negocios"


def test_un_rechazo_no_rompe_nada(anthropic_falso):
    anthropic_falso(_Respuesta(None, stop_reason="refusal"))
    assert clasificar_libros([_libro("Uno")]) == {}


def test_una_respuesta_ilegible_no_rompe_nada(anthropic_falso, monkeypatch):
    cliente = _Cliente([_Respuesta(None)])
    cliente.messages.respuestas = [type("R", (), {
        "content": [_Bloque("esto no es json")], "stop_reason": "end_turn"})()]
    modulo = types.ModuleType("anthropic")
    modulo.Anthropic = lambda *a, **k: cliente
    monkeypatch.setitem(sys.modules, "anthropic", modulo)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-mentira")

    assert clasificar_libros([_libro("Uno")]) == {}


def test_ignora_un_id_inventado(anthropic_falso):
    anthropic_falso(_Respuesta({"libros": [
        {"id": 99, "categoria": "Negocios", "descripcion": "", "confianza": "alta"},
    ]}))
    assert clasificar_libros([_libro("Uno")]) == {}


def test_sin_clave_avisa(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SinClave, match="ANTHROPIC_API_KEY"):
        clasificar_libros([_libro("Uno")])


# --- integración con el motor -------------------------------------------------

@pytest.fixture
def syncer(tmp_path):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.nube.activado = False
    return Syncer(c, state_dir=tmp_path / "state")


def test_la_clasificacion_llega_a_las_notas(syncer, anthropic_falso):
    anthropic_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "Liderazgo y equipos",
         "descripcion": "Sobre dirigir equipos.", "confianza": "alta"},
    ]}))
    syncer.ingest([Highlight(book_title="The Hard Thing About Hard Things",
                             book_author="Ben Horowitz",
                             text="Un texto sin pistas.", location="10")])
    # Las palabras clave no sacan nada de ese título: aquí entra la IA.
    assert syncer.libros()[0].categoria == "Sin clasificar"

    assert syncer.clasificar_con_ia(syncer.libros()) == 1

    nota = next(p for p in syncer.sink.root.glob("*.md") if "Hard Thing" in p.name)
    texto = nota.read_text(encoding="utf-8")
    assert 'categoria: "Liderazgo y equipos"' in texto
    assert "> Sobre dirigir equipos." in texto

    tema = syncer.temas.path_for("Liderazgo y equipos").read_text(encoding="utf-8")
    assert "Sobre dirigir equipos." in tema


def test_no_reclasifica_lo_ya_clasificado(syncer, anthropic_falso):
    cliente = anthropic_falso(_Respuesta({"libros": []}), _Respuesta({"libros": []}))
    syncer.ingest([Highlight(book_title="Traction- Get a Grip on your Business",
                             book_author="Gino Wickman", text="Una idea.", location="1")])

    syncer.clasificar_con_ia(syncer.libros())          # ya es "Negocios"
    assert cliente.messages.llamadas == []

    syncer.clasificar_con_ia(syncer.libros(), rehacer=True)
    assert len(cliente.messages.llamadas) == 1


def test_la_configuracion_manual_gana_a_la_ia(tmp_path, anthropic_falso):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.categorias = {"Radical Candor": "Mis imprescindibles"}
    syncer = Syncer(c, state_dir=tmp_path / "state")

    anthropic_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "Otra cosa", "descripcion": "d", "confianza": "alta"},
    ]}))
    syncer.ingest([Highlight(book_title="Radical Candor", book_author="Kim Scott",
                             text="Idea.", location="1")])
    syncer.clasificar_con_ia(syncer.libros(), rehacer=True)

    (libro,) = syncer.libros()
    assert libro.categoria == "Mis imprescindibles"
    assert libro.descripcion == "d"      # la descripción sí se aprovecha
