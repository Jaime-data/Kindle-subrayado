from datetime import datetime

from kindle_sync.sources import clippings

ES = """﻿Sapiens (Yuval Noah Harari)
- La subrayado en la página 24 | posición 356-357 | Añadido el lunes, 4 de agosto de 2025 21:03:11

Los humanos evolucionaron para pensar en individuos.
==========
Sapiens (Yuval Noah Harari)
- La nota en la página 24 | posición 357 | Añadido el lunes, 4 de agosto de 2025 21:04:00

Revisar este punto.
==========
Sapiens (Yuval Noah Harari)
- Marcador en la página 30 | posición 400 | Añadido el lunes, 4 de agosto de 2025 21:05:00


==========
"""

EN = """Thinking, Fast and Slow (Kahneman, Daniel)
- Your Highlight on page 12 | Location 176-178 | Added on Sunday, August 3, 2025 1:34:56 PM

System 1 operates automatically and quickly.
==========
"""

SIN_AUTOR = """Manual interno
- Tu subrayado en la posición 88-90 | Añadido el martes, 5 de agosto de 2025 09:00:00

Un texto cualquiera.
==========
"""


def test_parsea_entradas_en_espanol():
    hls = clippings.parse_text(ES)
    assert len(hls) == 3

    sub, nota, marcador = hls
    assert sub.kind == "highlight"
    assert sub.book_title == "Sapiens"
    assert sub.book_author == "Yuval Noah Harari"
    assert sub.page == "24"
    assert sub.location == "356-357"
    assert sub.text == "Los humanos evolucionaron para pensar en individuos."
    assert sub.added_at == datetime(2025, 8, 4, 21, 3, 11)

    assert nota.kind == "note"
    assert marcador.kind == "bookmark"


def test_parsea_entradas_en_ingles_y_normaliza_autor():
    hl = clippings.parse_text(EN)[0]
    assert hl.book_title == "Thinking, Fast and Slow"
    assert hl.book_author == "Daniel Kahneman"
    assert hl.location == "176-178"
    assert hl.added_at == datetime(2025, 8, 3, 13, 34, 56)


def test_libro_sin_autor():
    hl = clippings.parse_text(SIN_AUTOR)[0]
    assert hl.book_title == "Manual interno"
    assert hl.book_author is None
    assert hl.location == "88-90"
    assert hl.page is None


def test_ignora_basura_y_entradas_vacias():
    basura = "\n==========\nSolo un título\n==========\n"
    assert clippings.parse_text(basura) == []


def test_lee_fichero(tmp_path):
    path = tmp_path / "My Clippings.txt"
    path.write_text(ES, encoding="utf-8")
    assert len(clippings.parse_file(path)) == 3
