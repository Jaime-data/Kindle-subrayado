"""Motor de sincronización: fuentes -> estado -> notas de Obsidian."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg
from .models import Book, Highlight, group_by_book
from .sinks.obsidian import ObsidianSink
from .sources import clippings
from .state import Store

log = logging.getLogger("kindle-sync")


@dataclass
class SyncResult:
    nuevos: int = 0
    libros_tocados: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.errores and not self.nuevos:
            return "sin novedades (" + "; ".join(self.errores) + ")"
        if not self.nuevos:
            return "sin subrayados nuevos"
        libros = ", ".join(self.libros_tocados)
        return f"{self.nuevos} subrayado(s) nuevo(s) en: {libros}"


class Syncer:
    def __init__(self, conf: cfg.Config, state_dir: Path | None = None,
                 dry_run: bool = False):
        self.conf = conf
        self.dry_run = dry_run
        self.store = Store(state_dir or cfg.STATE_DIR)
        self.sink = ObsidianSink(
            conf.obsidian.vault,
            conf.obsidian.subcarpeta,
            include_bookmarks=conf.obsidian.incluir_marcadores,
        )

    # --- fuentes -----------------------------------------------------------

    def from_clippings(self) -> list[Highlight]:
        path = self.conf.clippings_path
        if path is None or not path.exists():
            log.debug("Kindle no conectado (%s)", path or "ningún volumen con My Clippings.txt")
            return []
        found = clippings.parse_file(path)
        log.info("USB: %d entradas leídas de %s", len(found), path)
        return found

    def from_correo(self) -> list[Highlight]:
        from .llavero import leer
        from .sources.buzon import descargar

        c = self.conf.correo
        if not c.usuario:
            raise RuntimeError("falta el usuario en la sección [correo]")

        mensajes = descargar(c.servidor, c.puerto, c.usuario, leer(c.usuario),
                             carpeta=c.carpeta, dias=c.dias)
        found = [hl for m in mensajes for hl in m.highlights]
        log.info("Correo: %d subrayado(s) en %d exportación(es)", len(found), len(mensajes))
        return found

    def from_cloud(self) -> list[Highlight]:
        from .sources import amazon_cloud

        found = amazon_cloud.fetch(
            cfg.SESSION_FILE,
            only_personal_docs=self.conf.nube.solo_documentos_personales,
        )
        log.info("Nube: %d anotaciones leídas del Cuaderno de Kindle", len(found))
        return found

    # --- orquestación ------------------------------------------------------

    def sync(self, sources: tuple[str, ...] = ("clippings", "correo", "cloud")) -> SyncResult:
        result = SyncResult()
        incoming: list[Highlight] = []

        if "clippings" in sources and self.conf.usb.activado:
            try:
                incoming += self.from_clippings()
            except OSError as exc:
                result.errores.append(f"USB: {exc}")
                log.warning("Fallo leyendo My Clippings.txt: %s", exc)

        if "correo" in sources and self.conf.correo.activado:
            try:
                incoming += self.from_correo()
            except Exception as exc:  # buzón inaccesible, contraseña ausente
                result.errores.append(f"correo: {exc}")
                log.warning("Fallo leyendo el correo: %s", exc)

        if "cloud" in sources and self.conf.nube.activado:
            try:
                incoming += self.from_cloud()
            except Exception as exc:  # red, sesión caducada, Playwright ausente
                result.errores.append(f"nube: {exc}")
                log.warning("Fallo consultando la nube de Amazon: %s", exc)

        if not incoming:
            return result

        return self.ingest(incoming, result)

    def ingest(self, highlights: list[Highlight], result: SyncResult | None = None) -> SyncResult:
        result = result or SyncResult()
        for key, incoming_book in group_by_book(highlights).items():
            book = self.store.load(key)
            if book is None:
                book = incoming_book
                nuevos = len(book.highlights)
                cambiado = True
            else:
                antes = _snapshot(book)
                book.author = book.author or incoming_book.author
                book.asin = book.asin or incoming_book.asin
                nuevos = sum(book.add(hl) for hl in incoming_book.highlights.values())
                # Un subrayado ya conocido puede enriquecerse (p. ej. le llega
                # la nota desde la nube): también hay que reescribir la nota.
                cambiado = nuevos > 0 or _snapshot(book) != antes

            if not cambiado and self.sink.path_for(book).exists():
                continue

            result.nuevos += nuevos
            result.libros_tocados.append(book.title)
            if self.dry_run:
                log.info("[simulación] %s: %d nuevo(s)", book.title, nuevos)
                continue

            self.store.save(key, book)
            path = self.sink.write(book)
            log.info("%s: %d nuevo(s) -> %s", book.title, nuevos, path)
        return result

    def rebuild(self) -> int:
        """Reescribe todas las notas .md desde el estado guardado."""
        count = 0
        for key in self.store.keys():
            book = self.store.load(key)
            if book is None:
                continue
            self.sink.write(book)
            count += 1
        return count


def _snapshot(book: Book) -> tuple:
    """Huella del contenido de un libro, para detectar cambios reales."""
    return tuple(
        (h.uid, h.text, h.note, h.page, h.location)
        for h in book.sorted_highlights()
    )
