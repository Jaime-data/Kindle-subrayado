"""Limpieza de los títulos que llegan del Kindle."""

import pytest

from kindle_sync.models import limpiar_titulo

CASOS = [
    # (título tal cual llega, autor, resultado esperado)
    ("Las 48 leyes del poder (Robert Greene) (Z-Library)", "Robert Greene",
     "Las 48 leyes del poder"),
    ("Radical Candor (Kim Scott) (z-library.sk, 1lib.sk, z-lib.sk)", "Kim Scott",
     "Radical Candor"),
    ("Remote_Office_Not_Required_Jason_Fri_z_library_sk,_1lib_sk,", "Jason Fried",
     "Remote Office Not Required Jason Fri"),
    ("Agencynomics_Fully_Revised_Edition_20_z_library_sk__1lib_sk_", "Spencer Gallagher",
     "Agencynomics Fully Revised Edition 20"),
    ("The Psychology of Money (Morgan Housel) (Z-Library)", "Morgan Housel",
     "The Psychology of Money"),
    ("Antifrágil (Nassim Nicholas Taleb) (Z-Library)", "Nassim Nicholas Taleb",
     "Antifrágil"),
    ("Céntrate (Deep Work) (Cal Newport) (Z-Library)", "Cal Newport",
     "Céntrate (Deep Work)"),          # los paréntesis con sentido se conservan
]


@pytest.mark.parametrize("bruto,autor,esperado", CASOS)
def test_limpia_el_ruido_de_las_descargas(bruto, autor, esperado):
    assert limpiar_titulo(bruto, autor) == esperado


def test_no_toca_un_titulo_limpio():
    assert limpiar_titulo("Sapiens", "Yuval Noah Harari") == "Sapiens"
    assert limpiar_titulo("1984", "George Orwell") == "1984"
    assert limpiar_titulo("El Plan de Marketing de 1-Página: Consigue Nuevos Clientes",
                          "Allan Dib") == "El Plan de Marketing de 1-Página: Consigue Nuevos Clientes"


def test_nunca_devuelve_vacio():
    assert limpiar_titulo("(Z-Library)", None) == "(Z-Library)"
    assert limpiar_titulo("   ", None) == ""


def test_el_mismo_subrayado_no_se_duplica_aunque_el_titulo_venga_sucio():
    """El USB trae el nombre del fichero; el correo, el título limpio."""
    from kindle_sync.models import Highlight, group_by_book

    por_usb = Highlight(
        book_title="Radical Candor (Kim Scott) (z-library.sk, 1lib.sk, z-lib.sk)",
        book_author="Kim Scott", text="Di lo que piensas y hazlo con cariño.",
        source="clippings")
    por_correo = Highlight(
        book_title="Radical Candor", book_author="Kim Scott",
        text="Di lo que piensas y hazlo con cariño.", source="export")

    assert por_usb.uid == por_correo.uid

    libros = group_by_book([por_usb, por_correo])
    assert len(libros) == 1
    (libro,) = libros.values()
    assert libro.title == "Radical Candor"
    assert len(libro.highlights) == 1


def test_migrar_notas_ya_escritas_con_titulos_sucios(tmp_path):
    """Reproduce el caso real: 20 libros ya sincronizados con ruido."""
    from kindle_sync import config as cfg
    from kindle_sync.models import Highlight
    from kindle_sync.sync import Syncer

    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    syncer = Syncer(c, state_dir=tmp_path / "state")

    # Se escribe el estado a mano con el título sucio, como quedó antes
    # de que existiera la limpieza.
    sucio = Highlight(book_title="1984 (George Orwell) (Z-Library)",
                      book_author="George Orwell", text="La guerra es la paz.",
                      location="10")
    from kindle_sync.models import Book, slugify
    libro = Book(title=sucio.book_title, author=sucio.book_author)
    libro.add(sucio)
    key = slugify(f"{libro.title} {libro.author}")
    syncer.store.save(key, libro)
    vieja = syncer.sink.write(libro)
    assert vieja.exists()

    cambios = syncer.limpiar_titulos(dry_run=True)
    assert cambios == [("1984 (George Orwell) (Z-Library)", "1984")]
    assert vieja.exists(), "el ensayo en seco no debe tocar nada"

    syncer.limpiar_titulos()

    assert not vieja.exists(), "la nota con el nombre sucio debe desaparecer"
    nueva = syncer.sink.root / "1984 - George Orwell.md"
    assert nueva.exists()
    assert "La guerra es la paz." in nueva.read_text(encoding="utf-8")
    assert len(list(syncer.sink.root.glob("*.md"))) == 1

    # Y un sync posterior no vuelve a crear el libro sucio.
    assert syncer.ingest([sucio]).nuevos == 0
    assert len(list(syncer.sink.root.glob("*.md"))) == 1
