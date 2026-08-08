"""Colapso de los subrayados que el Kindle duplica al extenderlos.

Los datos son los de una nota real: cuatro versiones del mismo párrafo, cada
una más larga, más el fragmento suelto del final.
"""

import pytest

from kindle_sync.models import Book, Highlight

LARGO = ("La Estrategia de la Corona se basa en una simple sucesión de causa y "
         "efecto: si creemos que estamos destinados a realizar grandes cosas, "
         "nuestra convicción irradiará su brillo de la misma manera en que una "
         "corona crea un aura en torno de un rey. Esta aura deslumbrará a quienes "
         "nos rodean, que se convencerán de que tenemos razones fundadas.")
MEDIO = LARGO[:LARGO.index("rey.") + 4]
CORTO = LARGO[:LARGO.index(" rey.")]
FRAGMENTO = "rey."


def _libro(*highlights) -> Book:
    libro = Book(title="Las 48 leyes del poder", author="Robert Greene")
    for hl in highlights:
        libro.add(hl)
    return libro


def _hl(texto, location, **kw):
    return Highlight(book_title="Las 48 leyes del poder", book_author="Robert Greene",
                     text=texto, location=location, **kw)


def test_colapsa_las_versiones_de_un_subrayado_extendido():
    libro = _libro(
        _hl(LARGO, "7916-7925"),
        _hl(CORTO, "7916-7918"),
        _hl(MEDIO, "7916-7918"),
        _hl(FRAGMENTO, "7918-7918"),
    )
    assert len(libro.highlights) == 4

    descartados = libro.compactar()

    assert len(libro.highlights) == 1
    assert len(descartados) == 3
    (superviviente,) = libro.highlights.values()
    assert superviviente.text == LARGO       # sobrevive la versión completa


def test_conserva_la_nota_y_la_fecha_de_las_versiones_absorbidas():
    from datetime import datetime

    libro = _libro(
        _hl(LARGO, "7916-7925"),
        _hl(CORTO, "7916-7918", note="mi comentario",
            added_at=datetime(2023, 12, 10, 9, 0)),
    )
    libro.compactar()

    (superviviente,) = libro.highlights.values()
    assert superviviente.text == LARGO
    assert superviviente.note == "mi comentario"
    assert superviviente.added_at == datetime(2023, 12, 10, 9, 0)


def test_no_toca_subrayados_distintos():
    libro = _libro(
        _hl("La dignidad siempre es la máscara que usted debe ponerse.", "7942-7944"),
        _hl("Procure siempre encontrar un símbolo para representar su causa.", "8711-8712"),
        _hl("Bene vixit, qui bene latuit.", "8761-8762"),
    )
    assert libro.compactar() == []
    assert len(libro.highlights) == 3


def test_la_misma_frase_en_otra_parte_del_libro_no_es_una_repeticion():
    """Un autor puede repetir una frase; las posiciones lo delatan."""
    libro = _libro(
        _hl("El poder es una ilusión que se sostiene en la percepción ajena.", "100-110"),
        _hl("El poder es una ilusión", "9000-9002"),
    )
    assert libro.compactar() == []
    assert len(libro.highlights) == 2


def test_una_nota_nunca_absorbe_un_subrayado():
    libro = _libro(
        _hl("Texto largo del subrayado sobre la corona y el aura.", "10-20"),
        _hl("la corona", "10-12", kind="note"),
    )
    assert libro.compactar() == []
    assert len(libro.highlights) == 2


def test_sin_posiciones_se_colapsa_igual():
    """El correo exporta sin posición; el solape se decide solo por el texto."""
    libro = _libro(
        _hl("Una idea larga y desarrollada sobre el poder.", None),
        _hl("Una idea larga", None),
    )
    assert len(libro.compactar()) == 1
    assert len(libro.highlights) == 1


def test_compactar_es_idempotente():
    libro = _libro(_hl(LARGO, "7916-7925"), _hl(CORTO, "7916-7918"))
    libro.compactar()
    assert libro.compactar() == []


# --- integración con el motor -------------------------------------------------

def test_el_sync_no_escribe_las_versiones_duplicadas(tmp_path):
    from kindle_sync import config as cfg
    from kindle_sync.sync import Syncer

    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    c.nube.activado = False
    syncer = Syncer(c, state_dir=tmp_path / "state")

    resultado = syncer.ingest([
        _hl(LARGO, "7916-7925"),
        _hl(CORTO, "7916-7918"),
        _hl(MEDIO, "7916-7918"),
        _hl(FRAGMENTO, "7918-7918"),
        _hl("La dignidad siempre es la máscara.", "7942-7944"),
    ])

    assert resultado.nuevos == 2          # el párrafo y la dignidad, no cinco
    nota = next(p for p in syncer.sink.root.glob("*.md") if "48 leyes" in p.name)
    texto = nota.read_text(encoding="utf-8")
    assert texto.count("^k-") == 2
    assert "> rey." not in texto
    assert "subrayados: 2" in texto


def test_compactar_todo_arregla_lo_ya_guardado(tmp_path):
    """Reproduce el caso real: la nota ya estaba escrita con los duplicados."""
    from kindle_sync import config as cfg
    from kindle_sync.models import slugify
    from kindle_sync.state import Store
    from kindle_sync.sync import Syncer

    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    syncer = Syncer(c, state_dir=tmp_path / "state")

    # Estado escrito a mano, como quedó antes de que existiera el colapso.
    libro = _libro(_hl(LARGO, "7916-7925"), _hl(CORTO, "7916-7918"),
                   _hl(MEDIO, "7916-7918"), _hl(FRAGMENTO, "7918-7918"))
    key = slugify(f"{libro.title} {libro.author}")
    syncer.store.save(key, libro)
    syncer.sink.write(libro)
    assert syncer.sink.path_for(libro).read_text(encoding="utf-8").count("^k-") == 4

    assert syncer.compactar_todo(dry_run=True) == [("Las 48 leyes del poder", 3)]
    assert syncer.sink.path_for(libro).read_text(encoding="utf-8").count("^k-") == 4

    syncer.compactar_todo()

    texto = syncer.sink.path_for(libro).read_text(encoding="utf-8")
    assert texto.count("^k-") == 1
    assert LARGO in texto
    assert len(Store(tmp_path / "state").load(key).highlights) == 1
