from datetime import datetime

import pytest

from kindle_sync import config as cfg
from kindle_sync.models import Highlight, group_by_book
from kindle_sync.sinks.obsidian import END_MARKER, ObsidianSink
from kindle_sync.sync import Syncer


def hl(text, **kw):
    kw.setdefault("book_title", "Sapiens")
    kw.setdefault("book_author", "Yuval Noah Harari")
    return Highlight(text=text, **kw)


@pytest.fixture
def conf(tmp_path):
    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.obsidian.subcarpeta = "Kindle"
    c.nube.activado = False
    c.usb.punto_montaje = str(tmp_path / "Kindle")
    return c


@pytest.fixture
def syncer(conf, tmp_path):
    return Syncer(conf, state_dir=tmp_path / "state")


def test_mismo_subrayado_de_dos_fuentes_cuenta_una_vez():
    a = hl("Los humanos evolucionaron.", source="clippings", location="356-357")
    b = hl("¡Los  humanos   evolucionaron!", source="cloud", location="356")
    assert a.uid == b.uid

    book = group_by_book([a])["sapiens-yuval-noah-harari"]
    assert book.add(b) is False
    assert len(book.highlights) == 1


def test_orden_por_posicion_y_render(conf):
    sink = ObsidianSink(conf.obsidian.vault, conf.obsidian.subcarpeta)
    book = group_by_book([
        hl("Segundo", location="900"),
        hl("Primero", location="100", page="4", added_at=datetime(2025, 8, 4)),
    ])["sapiens-yuval-noah-harari"]

    md = sink.render(book)
    assert md.index("Primero") < md.index("Segundo")
    assert 'titulo: "Sapiens"' in md
    assert "> [!quote] pág. 4 · pos. 100 · 04/08/2025" in md
    assert md.rstrip().endswith(END_MARKER)


def test_sync_incremental_no_duplica(syncer):
    r1 = syncer.ingest([hl("Uno", location="10"), hl("Dos", location="20")])
    assert r1.nuevos == 2

    r2 = syncer.ingest([hl("Uno", location="10"), hl("Tres", location="30")])
    assert r2.nuevos == 1

    path = next((syncer.sink.root).glob("*.md"))
    contenido = path.read_text(encoding="utf-8")
    assert contenido.count("^k-") == 3
    assert "subrayados: 3" in contenido


def test_conserva_lo_escrito_bajo_el_marcador(syncer):
    syncer.ingest([hl("Uno", location="10")])
    path = next(syncer.sink.root.glob("*.md"))
    path.write_text(path.read_text(encoding="utf-8") + "\n## Mis ideas\nAlgo mío.\n",
                    encoding="utf-8")

    syncer.ingest([hl("Dos", location="20")])
    contenido = path.read_text(encoding="utf-8")
    assert "Algo mío." in contenido
    assert "Dos" in contenido


def test_nota_asociada_se_conserva_al_fusionar(syncer):
    syncer.ingest([hl("Texto", location="10")])
    syncer.ingest([hl("Texto", location="10", note="mi comentario")])
    contenido = next(syncer.sink.root.glob("*.md")).read_text(encoding="utf-8")
    assert "**Nota:** mi comentario" in contenido
    assert contenido.count("^k-") == 1


def test_rebuild_regenera_desde_el_estado(syncer):
    syncer.ingest([hl("Uno", location="10")])
    path = next(syncer.sink.root.glob("*.md"))
    path.unlink()
    assert syncer.rebuild() == 1
    assert path.exists()


def test_sync_usb_lee_el_kindle_montado(conf, tmp_path):
    docs = tmp_path / "Kindle" / "documents"
    docs.mkdir(parents=True)
    (docs / "My Clippings.txt").write_text(
        "Sapiens (Yuval Noah Harari)\n"
        "- La subrayado en la posición 1-2 | Añadido el lunes, 4 de agosto de 2025 21:03:11\n"
        "\nTexto.\n==========\n", encoding="utf-8")

    syncer = Syncer(conf, state_dir=tmp_path / "state")
    result = syncer.sync(("clippings",))
    assert result.nuevos == 1
    assert result.errores == []


def test_sync_sin_kindle_conectado_no_falla(syncer):
    result = syncer.sync(("clippings",))
    assert result.nuevos == 0
    assert result.errores == []


def test_detecta_el_kindle_aunque_se_monte_con_otro_nombre(tmp_path, monkeypatch):
    """Un segundo Kindle se monta como «Kindle 1», no como «Kindle»."""
    volumes = tmp_path / "Volumes"
    (volumes / "Macintosh HD").mkdir(parents=True)
    docs = volumes / "Kindle 1" / "documents"
    docs.mkdir(parents=True)
    (docs / "My Clippings.txt").write_text("", encoding="utf-8")
    c = cfg.Config()
    c.usb.punto_montaje = "auto"
    original = cfg.Path
    monkeypatch.setattr(cfg, "Path",
                        lambda p="": original(str(volumes)) if p == "/Volumes" else original(p))

    assert c.clippings_path == docs / "My Clippings.txt"


def test_sin_kindle_montado_la_ruta_es_none(tmp_path, monkeypatch):
    vacio = tmp_path / "Volumes"
    vacio.mkdir()
    original = cfg.Path
    monkeypatch.setattr(cfg, "Path",
                        lambda p="": original(str(vacio)) if p == "/Volumes" else original(p))

    c = cfg.Config()
    c.usb.punto_montaje = "auto"
    assert c.clippings_path is None


def test_editar_la_configuracion_respeta_comentarios(tmp_path):
    path = tmp_path / "config.toml"
    cfg.write_default(path)
    antes = path.read_text(encoding="utf-8")

    cambios = cfg.set_valores(path, "correo",
                              {"activado": True, "usuario": "jaime@ejemplo.com"})

    assert 'usuario = "jaime@ejemplo.com"' in cambios
    texto = path.read_text(encoding="utf-8")
    assert 'usuario = "jaime@ejemplo.com"' in texto
    assert "activado = true" in texto.split("[correo]")[1].split("[avisos]")[0]
    # Los comentarios y el resto de secciones quedan intactos.
    assert "# Notificación de macOS" in texto
    assert texto.count("[obsidian]") == antes.count("[obsidian]")
    assert cfg.load(path).correo.usuario == "jaime@ejemplo.com"


def test_editar_no_toca_la_misma_clave_de_otra_seccion(tmp_path):
    path = tmp_path / "config.toml"
    cfg.write_default(path)
    cfg.set_valores(path, "correo", {"activado": True})

    conf = cfg.load(path)
    assert conf.correo.activado is True
    assert conf.nube.activado is True   # esta ya estaba a true
    assert conf.usb.activado is True


def test_activar_el_correo_en_una_configuracion_antigua(tmp_path):
    """Una config creada antes de que existiera [correo] debe seguir sirviendo."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[obsidian]\n'
        '# mi comentario\n'
        'vault = "~/MisNotas"\n'
        'subcarpeta = "Kindle"\n'
        '\n'
        '[nube]\n'
        'activado = true\n'
        'intervalo = 300\n', encoding="utf-8")

    cambios = cfg.set_valores(path, "correo",
                              {"activado": True, "usuario": "jaime@ejemplo.com"})

    assert len(cambios) == 2
    conf = cfg.load(path)
    assert conf.correo.activado is True
    assert conf.correo.usuario == "jaime@ejemplo.com"
    assert conf.correo.servidor == "imap.gmail.com"   # el resto, por defecto
    # No se estropea nada de lo que ya había.
    assert conf.obsidian.vault == "~/MisNotas"
    assert conf.nube.intervalo == 300
    assert "# mi comentario" in path.read_text(encoding="utf-8")


def test_editar_la_ultima_seccion_del_fichero(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[obsidian]\nvault = "~/N"\n\n[avisos]\nnotificaciones = true\n',
                    encoding="utf-8")

    cfg.set_valores(path, "avisos", {"notificaciones": False})
    assert cfg.load(path).avisos.notificaciones is False
