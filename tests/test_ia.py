"""Clasificación por temática con OpenAI.

No toca la red: se sustituye el cliente de OpenAI por uno que devuelve
respuestas fabricadas, para poder fijar el contrato — qué se le manda al
modelo y qué se hace con lo que responde.
"""

import json
import sys
import types

import pytest

from kindle_sync import config as cfg
from kindle_sync.ia import ErrorModelo, SinClave, clasificar_libros
from kindle_sync.models import Book, Highlight
from kindle_sync.sync import Syncer


class _Mensaje:
    def __init__(self, content):
        self.content = content


class _Eleccion:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Mensaje(content)
        self.finish_reason = finish_reason


class _Respuesta:
    """Imita la respuesta de chat.completions."""

    def __init__(self, payload, finish_reason="stop", texto=None):
        contenido = texto if texto is not None else json.dumps(payload)
        self.choices = [_Eleccion(contenido, finish_reason)]


class _Completions:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


class _Cliente:
    def __init__(self, respuestas):
        self.chat = types.SimpleNamespace(completions=_Completions(respuestas))
        self.models = types.SimpleNamespace(
            list=lambda: [types.SimpleNamespace(id="gpt-5.6-luna")])

    @property
    def llamadas(self):
        return self.chat.completions.llamadas


@pytest.fixture
def openai_falso(monkeypatch):
    """Sustituye el módulo openai y la clave del entorno."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-de-mentira")

    def instalar(*respuestas):
        cliente = _Cliente(respuestas)
        modulo = types.ModuleType("openai")
        modulo.OpenAI = lambda *a, **k: cliente
        monkeypatch.setitem(sys.modules, "openai", modulo)
        return cliente

    return instalar


def _libro(titulo, autor=None, textos=()):
    libro = Book(title=titulo, author=autor)
    for i, texto in enumerate(textos, start=1):
        libro.add(Highlight(book_title=titulo, book_author=autor,
                            text=texto, location=str(i * 10)))
    return libro


def test_clasifica_y_describe(openai_falso):
    cliente = openai_falso(_Respuesta({"libros": [
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

    (llamada,) = cliente.llamadas
    assert llamada["model"] == "gpt-5.6-luna"
    # Esquema estricto: evita tener que interpretar texto libre.
    formato = llamada["response_format"]
    assert formato["type"] == "json_schema"
    assert formato["json_schema"]["strict"] is True
    assert llamada["reasoning_effort"] == "low"


def test_manda_titulo_autor_y_subrayados(openai_falso):
    cliente = openai_falso(_Respuesta({"libros": []}))
    clasificar_libros([_libro("Antifrágil", "Nassim Taleb",
                              ["Lo que no mata al sistema lo hace más fuerte."])])

    mensaje = cliente.llamadas[0]["messages"][1]["content"]
    assert "Antifrágil" in mensaje
    assert "Nassim Taleb" in mensaje
    assert "Lo que no mata al sistema" in mensaje
    assert "Negocios" in mensaje          # las categorías conocidas van de guía


def test_los_libros_van_por_lotes(openai_falso):
    """Veinte libros no son veinte peticiones."""
    cliente = openai_falso(_Respuesta({"libros": []}), _Respuesta({"libros": []}))
    clasificar_libros([_libro(f"Libro {i}") for i in range(20)], lote=10)

    assert len(cliente.llamadas) == 2


def test_una_categoria_nueva_se_reutiliza_en_el_lote_siguiente(openai_falso):
    """Si no, inventaría tres nombres distintos para el mismo tema."""
    cliente = openai_falso(
        _Respuesta({"libros": [{"id": 1, "categoria": "Náutica",
                                "descripcion": "d", "confianza": "alta"}]}),
        _Respuesta({"libros": []}),
    )
    clasificar_libros([_libro("Uno"), _libro("Dos")], lote=1)

    segunda = cliente.llamadas[1]["messages"][1]["content"]
    assert "Náutica" in segunda


def test_normaliza_las_mayusculas_de_la_categoria(openai_falso):
    openai_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "negocios  ", "descripcion": "", "confianza": "media"},
    ]}))
    libros = [_libro("Uno")]
    assert clasificar_libros(libros)[libros[0].key].categoria == "Negocios"


def test_un_bloqueo_del_filtro_no_rompe_nada(openai_falso):
    openai_falso(_Respuesta(None, finish_reason="content_filter", texto=""))
    assert clasificar_libros([_libro("Uno")]) == {}


def test_una_respuesta_ilegible_no_rompe_nada(openai_falso):
    openai_falso(_Respuesta(None, texto="esto no es json"))
    assert clasificar_libros([_libro("Uno")]) == {}


def test_ignora_un_id_inventado(openai_falso):
    openai_falso(_Respuesta({"libros": [
        {"id": 99, "categoria": "Negocios", "descripcion": "", "confianza": "alta"},
    ]}))
    assert clasificar_libros([_libro("Uno")]) == {}


def test_sin_clave_avisa(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SinClave, match="OPENAI_API_KEY"):
        clasificar_libros([_libro("Uno")])


def test_reintenta_sin_el_parametro_de_razonamiento(openai_falso):
    """Un modelo que no razona rechaza reasoning_effort: no es un error fatal."""
    cliente = openai_falso(
        Exception("Unsupported parameter: 'reasoning_effort' is not supported"),
        _Respuesta({"libros": [{"id": 1, "categoria": "Negocios",
                                "descripcion": "d", "confianza": "alta"}]}),
    )
    libros = [_libro("Uno")]
    veredictos = clasificar_libros(libros)

    assert veredictos[libros[0].key].categoria == "Negocios"
    assert "reasoning_effort" in cliente.llamadas[0]
    assert "reasoning_effort" not in cliente.llamadas[1]


def test_un_modelo_inexistente_se_explica(openai_falso):
    openai_falso(Exception("The model `gpt-inventado` does not exist"),
                 Exception("The model `gpt-inventado` does not exist"))
    with pytest.raises(ErrorModelo, match="kindle-sync modelos"):
        clasificar_libros([_libro("Uno")], modelo="gpt-inventado")


def test_lista_los_modelos_de_la_cuenta(openai_falso):
    openai_falso()
    from kindle_sync.ia import modelos_disponibles

    assert modelos_disponibles() == ["gpt-5.6-luna"]


# --- integración con el motor -------------------------------------------------

@pytest.fixture
def syncer(tmp_path):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.nube.activado = False
    return Syncer(c, state_dir=tmp_path / "state")


def test_la_clasificacion_llega_a_las_notas(syncer, openai_falso):
    openai_falso(_Respuesta({"libros": [
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


def test_no_reclasifica_lo_ya_clasificado(syncer, openai_falso):
    cliente = openai_falso(_Respuesta({"libros": []}), _Respuesta({"libros": []}))
    syncer.ingest([Highlight(book_title="Traction- Get a Grip on your Business",
                             book_author="Gino Wickman", text="Una idea.", location="1")])

    syncer.clasificar_con_ia(syncer.libros())          # ya es "Negocios"
    assert cliente.llamadas == []

    syncer.clasificar_con_ia(syncer.libros(), rehacer=True)
    assert len(cliente.llamadas) == 1


def test_la_configuracion_manual_gana_a_la_ia(tmp_path, openai_falso):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.categorias = {"Radical Candor": "Mis imprescindibles"}
    syncer = Syncer(c, state_dir=tmp_path / "state")

    openai_falso(_Respuesta({"libros": [
        {"id": 1, "categoria": "Otra cosa", "descripcion": "d", "confianza": "alta"},
    ]}))
    syncer.ingest([Highlight(book_title="Radical Candor", book_author="Kim Scott",
                             text="Idea.", location="1")])
    syncer.clasificar_con_ia(syncer.libros(), rehacer=True)

    (libro,) = syncer.libros()
    assert libro.categoria == "Mis imprescindibles"
    assert libro.descripcion == "d"      # la descripción sí se aprovecha
