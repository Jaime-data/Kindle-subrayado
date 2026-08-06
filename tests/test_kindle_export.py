"""Parser del fichero de «Exportar notas» del Kindle."""

from pathlib import Path

from kindle_sync.sources import kindle_export

FIXTURE = Path(__file__).parent / "fixtures" / "exportacion_kindle.html"


def test_reconoce_una_exportacion():
    assert kindle_export.es_exportacion(FIXTURE.read_text(encoding="utf-8"))
    assert not kindle_export.es_exportacion("<html><body>un correo cualquiera</body></html>")


def test_extrae_subrayados_notas_y_metadatos():
    hls = kindle_export.parse_file(FIXTURE)

    assert [h.kind for h in hls] == ["highlight", "highlight", "highlight", "note"]
    assert all(h.book_title == "Informe interno de LocalMetric 2025" for h in hls)
    assert all(h.book_author == "Jaime Vicente" for h in hls)  # «Vicente, Jaime» dado la vuelta
    assert all(h.source == "export" for h in hls)

    primero, segundo, tercero, suelta = hls
    assert primero.page == "12" and primero.location == "176"
    assert primero.note is None
    # La nota que sigue a un subrayado en la misma posición se une a él.
    assert segundo.note == "Contrastar con los datos del trimestre pasado."
    assert tercero.location == "402"
    # Una nota sin subrayado delante se queda como nota independiente.
    assert suelta.text == "Una nota suelta, sin subrayado delante."
    # El marcador sin texto se descarta.
    assert all("marcador" not in h.text.lower() for h in hls)


def test_los_uid_coinciden_con_los_del_fichero_de_clippings():
    """Un mismo subrayado leído por las dos vías no puede duplicarse."""
    from kindle_sync.models import Highlight

    export = kindle_export.parse_file(FIXTURE)[0]
    clipping = Highlight(
        book_title="Informe interno de LocalMetric 2025",
        text="La retención importa más que la captación en el primer año.",
        source="clippings",
    )
    assert export.uid == clipping.uid
