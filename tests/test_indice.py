"""Clasificación por temas y nota índice."""

import pytest

from kindle_sync import config as cfg
from kindle_sync.categorias import SIN_CLASIFICAR, clasificar
from kindle_sync.models import Highlight
from kindle_sync.sync import Syncer

BIBLIOTECA = [
    ("Traction- Get a Grip on your Business", "Gino Wickman", "Negocios"),
    ("El Plan de Marketing de 1-Página", "Allan Dib", "Marketing y ventas"),
    ("Radical Candor", "Kim Scott", "Liderazgo y equipos"),
    ("Céntrate (Deep Work)", "Cal Newport", "Productividad"),
    ("Las 48 leyes del poder", "Robert Greene", "Estrategia y poder"),
    ("1984", "George Orwell", "Ficción y literatura"),
    ("Antifrágil", "Nassim Nicholas Taleb", "Filosofía y pensamiento"),
    ("Angel How to Invest in Technology Startups", "Jason Calacanis",
     "Inversión y finanzas"),
]


@pytest.mark.parametrize("titulo,autor,esperada", BIBLIOTECA)
def test_clasifica_por_el_titulo(titulo, autor, esperada):
    categoria, puntos = clasificar(titulo, autor)
    assert categoria == esperada
    assert puntos > 0


def test_un_titulo_opaco_se_resuelve_con_los_subrayados():
    """«The Hard Thing About Hard Things» no dice de qué va; sus subrayados sí."""
    solo_titulo, _ = clasificar("The Hard Thing About Hard Things", "Ben Horowitz")
    assert solo_titulo == SIN_CLASIFICAR

    con_textos, puntos = clasificar(
        "The Hard Thing About Hard Things", "Ben Horowitz",
        ["Contratar a un ejecutivo para tu startup es distinto.",
         "El CEO tiene que decidir con información incompleta.",
         "La cultura de la empresa se construye a diario."])
    assert con_textos != SIN_CLASIFICAR
    assert puntos > 0


def test_sin_pistas_no_se_inventa_una_categoria():
    assert clasificar("Zzz", None) == (SIN_CLASIFICAR, 0)


@pytest.fixture
def syncer(tmp_path):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.nube.activado = False
    return Syncer(c, state_dir=tmp_path / "state")


def _highlights():
    for titulo, autor, _ in BIBLIOTECA:
        yield Highlight(book_title=titulo, book_author=autor,
                        text=f"Una idea de {titulo}.", location="10")


def test_el_indice_agrupa_por_tema(syncer):
    syncer.ingest(list(_highlights()))
    indice = syncer.indice.path.read_text(encoding="utf-8")

    assert "# Índice de subrayados" in indice
    assert "libros: 8" in indice
    assert "```mermaid" in indice and "mindmap" in indice
    for _, _, tema in BIBLIOTECA:
        assert f"## {tema}" in indice
    # Enlaces que Obsidian resuelve a la nota del libro.
    assert "[[Radical Candor - Kim Scott|Radical Candor]]" in indice


def test_la_categoria_llega_al_frontmatter_y_a_las_etiquetas(syncer):
    syncer.ingest(list(_highlights()))
    nota = (syncer.sink.root / "Radical Candor - Kim Scott.md").read_text(encoding="utf-8")

    assert 'categoria: "Liderazgo y equipos"' in nota
    assert "  - liderazgo-y-equipos" in nota   # sin espacios ni tildes


def test_la_configuracion_manda_sobre_la_clasificacion(tmp_path):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.categorias = {"Radical Candor": "Mis imprescindibles"}
    syncer = Syncer(c, state_dir=tmp_path / "state")

    syncer.ingest(list(_highlights()))
    indice = syncer.indice.path.read_text(encoding="utf-8")

    assert "## Mis imprescindibles" in indice
    assert "[[Radical Candor - Kim Scott|Radical Candor]]" in indice


def test_el_mapa_mental_no_rompe_mermaid(syncer):
    """Paréntesis y comillas en un título tumban el diagrama entero."""
    syncer.ingest([Highlight(
        book_title="Céntrate (Deep Work) [edición \"especial\"]",
        book_author="Cal Newport", text="Una idea.", location="1")])

    mapa = syncer.indice.path.read_text(encoding="utf-8").split("```mermaid")[1]
    ramas = [ln for ln in mapa.split("```")[0].splitlines()
             if ln.strip() and not ln.strip().startswith(("mindmap", "root"))]

    assert ramas
    for rama in ramas:  # el root sí lleva paréntesis: es sintaxis de mermaid
        assert not set("()[]{}\"'") & set(rama), rama
    assert any("Centrate" in r or "Céntrate" in r for r in ramas)


def test_lo_escrito_bajo_el_marcador_del_indice_se_conserva(syncer):
    syncer.ingest(list(_highlights()))
    ruta = syncer.indice.path
    ruta.write_text(ruta.read_text(encoding="utf-8") + "\n## Mis conclusiones\nAlgo.\n",
                    encoding="utf-8")

    syncer.ingest([Highlight(book_title="Otro libro", text="Idea.", location="1")])
    assert "Algo." in ruta.read_text(encoding="utf-8")
