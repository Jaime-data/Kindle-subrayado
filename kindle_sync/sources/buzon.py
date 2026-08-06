"""Recoge del correo las exportaciones de notas que manda el Kindle.

En el Kindle, dentro de un libro: *Notas → Exportar*. El dispositivo envía por
Wi-Fi un correo con un adjunto HTML que contiene todos los subrayados de ese
libro, también de los documentos personales — que es justo lo que Amazon no
publica por web.

Aquí solo se lee el buzón: el adjunto lo interpreta `kindle_export`.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message

from ..models import Highlight
from . import kindle_export

log = logging.getLogger("kindle-sync")


class ErrorBuzon(RuntimeError):
    pass


@dataclass
class Mensaje:
    uid: str
    asunto: str
    fecha: datetime | None
    highlights: list[Highlight]


def descargar(servidor: str, puerto: int, usuario: str, contrasena: str,
              carpeta: str = "INBOX", dias: int = 30,
              vistos: set[str] | None = None) -> list[Mensaje]:
    """Devuelve las exportaciones de notas encontradas en el buzón."""
    vistos = vistos or set()
    try:
        with imaplib.IMAP4_SSL(servidor, puerto) as imap:
            imap.login(usuario, contrasena)
            imap.select(carpeta, readonly=True)  # nunca se toca el correo
            uids = _buscar(imap, dias)
            log.info("Correo: %d mensaje(s) candidatos en los últimos %d días",
                     len(uids), dias)
            return [m for uid in uids if uid not in vistos
                    if (m := _leer(imap, uid)) is not None]
    except imaplib.IMAP4.error as exc:
        raise ErrorBuzon(_explicar(exc)) from exc
    except OSError as exc:
        raise ErrorBuzon(f"no se pudo conectar con {servidor}:{puerto} ({exc})") from exc


def _buscar(imap: imaplib.IMAP4_SSL, dias: int) -> list[str]:
    desde = (datetime.now() - timedelta(days=dias)).strftime("%d-%b-%Y")
    estado, datos = imap.search(None, "SINCE", desde)
    if estado != "OK":
        return []
    return [uid.decode() for uid in datos[0].split()]


def _leer(imap: imaplib.IMAP4_SSL, uid: str) -> Mensaje | None:
    estado, datos = imap.fetch(uid, "(RFC822)")
    if estado != "OK" or not datos or not isinstance(datos[0], tuple):
        return None
    return extraer_de_mensaje(datos[0][1], uid=uid)


def extraer_de_mensaje(bruto: bytes, uid: str = "") -> Mensaje | None:
    """Saca los subrayados de un correo, si es una exportación del Kindle."""
    mensaje = email.message_from_bytes(bruto)
    highlights: list[Highlight] = []

    for parte in mensaje.walk():
        contenido = _texto_de_parte(parte)
        if contenido and kindle_export.es_exportacion(contenido):
            highlights.extend(kindle_export.parse_html(contenido))

    if not highlights:
        return None

    return Mensaje(
        uid=uid,
        asunto=_cabecera(mensaje, "Subject"),
        fecha=_fecha(mensaje),
        highlights=highlights,
    )


def _texto_de_parte(parte: Message) -> str | None:
    """Devuelve el HTML de una parte, sea adjunto o cuerpo."""
    if parte.get_content_maintype() == "multipart":
        return None
    nombre = parte.get_filename() or ""
    tipo = parte.get_content_type()
    if tipo not in ("text/html", "application/octet-stream") and \
            not nombre.lower().endswith(".html"):
        return None

    carga = parte.get_payload(decode=True)
    if not carga:
        return None
    juego = parte.get_content_charset() or "utf-8"
    try:
        return carga.decode(juego, errors="replace")
    except LookupError:
        return carga.decode("utf-8", errors="replace")


def _cabecera(mensaje: Message, nombre: str) -> str:
    bruto = mensaje.get(nombre, "")
    try:
        return str(make_header(decode_header(bruto)))
    except Exception:
        return bruto


def _fecha(mensaje: Message) -> datetime | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(mensaje.get("Date", ""))
    except (TypeError, ValueError):
        return None


def _explicar(exc: Exception) -> str:
    texto = str(exc)
    if re.search(r"AUTHENTICATIONFAILED|Invalid credentials", texto, re.IGNORECASE):
        return ("el servidor rechaza usuario o contraseña. Con Gmail o Google "
                "Workspace hace falta una «contraseña de aplicación», no la "
                "tuya de siempre: https://myaccount.google.com/apppasswords")
    return texto
