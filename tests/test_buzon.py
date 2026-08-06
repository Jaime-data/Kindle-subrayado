"""Lectura de las exportaciones de notas que llegan por correo."""

from email.message import EmailMessage
from pathlib import Path

from kindle_sync.sources import buzon

FIXTURE = Path(__file__).parent / "fixtures" / "exportacion_kindle.html"


def _correo(asunto: str, adjuntos: list[tuple[str, str, str]],
            cuerpo: str = "Adjunto va tu cuaderno.") -> bytes:
    """Construye un correo MIME: (nombre, contenido, subtipo) por adjunto."""
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = "do-not-reply@amazon.com"
    msg["To"] = "jaime@ejemplo.com"
    msg["Date"] = "Wed, 06 Aug 2026 10:15:00 +0200"
    msg.set_content(cuerpo)
    for nombre, contenido, subtipo in adjuntos:
        msg.add_attachment(contenido.encode("utf-8"), maintype="text",
                           subtype=subtipo, filename=nombre)
    return msg.as_bytes()


def test_extrae_los_subrayados_de_un_adjunto():
    html = FIXTURE.read_text(encoding="utf-8")
    bruto = _correo("Notas y subrayados: Informe interno",
                    [("Notas.html", html, "html")])

    mensaje = buzon.extraer_de_mensaje(bruto, uid="42")

    assert mensaje is not None
    assert mensaje.uid == "42"
    assert mensaje.asunto == "Notas y subrayados: Informe interno"
    assert mensaje.fecha is not None and mensaje.fecha.year == 2026
    assert len(mensaje.highlights) == 4
    assert mensaje.highlights[0].book_title == "Informe interno de LocalMetric 2025"


def test_ignora_correos_que_no_son_exportaciones():
    bruto = _correo("Tu pedido de Amazon", [("factura.html", "<html>Factura</html>", "html")])
    assert buzon.extraer_de_mensaje(bruto) is None

    sin_adjunto = _correo("Hola", [], cuerpo="Un correo normal y corriente.")
    assert buzon.extraer_de_mensaje(sin_adjunto) is None


def test_soporta_acentos_en_el_asunto():
    html = FIXTURE.read_text(encoding="utf-8")
    bruto = _correo("Tus notas de «Informe interno»", [("Notas.html", html, "html")])
    mensaje = buzon.extraer_de_mensaje(bruto)

    assert mensaje is not None
    assert mensaje.asunto == "Tus notas de «Informe interno»"


def test_varios_adjuntos_y_solo_uno_vale():
    html = FIXTURE.read_text(encoding="utf-8")
    bruto = _correo("Notas", [
        ("aviso.html", "<html>Publicidad</html>", "html"),
        ("Notas.html", html, "html"),
    ])
    mensaje = buzon.extraer_de_mensaje(bruto)

    assert mensaje is not None
    assert len(mensaje.highlights) == 4


def test_el_error_de_contrasena_explica_lo_de_gmail():
    import imaplib

    texto = buzon._explicar(imaplib.IMAP4.error("AUTHENTICATIONFAILED bad credentials"))
    assert "contraseña de aplicación" in texto
    assert "apppasswords" in texto


def test_los_subrayados_del_correo_no_duplican_los_del_cable(tmp_path):
    """Un mismo subrayado por correo y por USB tiene que contar una sola vez."""
    from kindle_sync import config as cfg
    from kindle_sync.sync import Syncer

    html = FIXTURE.read_text(encoding="utf-8")
    mensaje = buzon.extraer_de_mensaje(_correo("Notas", [("n.html", html, "html")]))

    c = cfg.Config()
    c.obsidian.vault = str(tmp_path / "vault")
    syncer = Syncer(c, state_dir=tmp_path / "state")

    assert syncer.ingest(mensaje.highlights).nuevos == 4
    assert syncer.ingest(mensaje.highlights).nuevos == 0
