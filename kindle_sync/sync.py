"""Motor de sincronización: fuentes -> estado -> notas de Obsidian."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg
from .models import Book, Highlight, group_by_book, limpiar_titulo, slugify
from .categorias import SIN_CLASIFICAR, clasificar
from .sinks.indice import IndiceSink
from .sinks.temas import TemasSink
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
        self.indice = IndiceSink(conf.obsidian.vault, conf.obsidian.subcarpeta)
        self.temas = TemasSink(conf.obsidian.vault, conf.obsidian.subcarpeta)

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
                book.compactar()
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

            # El Kindle duplica un subrayado cada vez que lo extiendes.
            if descartados := book.compactar():
                nuevos = max(0, nuevos - len(descartados))
                cambiado = True
                log.debug("%s: %d versión(es) duplicada(s) colapsada(s)",
                          book.title, len(descartados))

            if not cambiado and self.sink.path_for(book).exists():
                continue

            result.nuevos += nuevos
            result.libros_tocados.append(book.title)
            if self.dry_run:
                log.info("[simulación] %s: %d nuevo(s)", book.title, nuevos)
                continue

            self.clasificar_libro(book)
            self.store.save(key, book)
            path = self.sink.write(book)
            log.info("%s: %d nuevo(s) -> %s", book.title, nuevos, path)

        if result.libros_tocados and not self.dry_run:
            self.escribir_indice()
        return result

    def clasificar_con_ia(self, libros: list[Book], rehacer: bool = False) -> int:
        """Clasifica con IA los libros que no tengan tema (o todos).

        Si la IA falla o no está configurada, cada libro se queda con lo que
        diga el clasificador por palabras clave: nunca se pierde la
        clasificación por un problema de red o de clave.
        """
        from .ia import clasificar_libros

        pendientes = [l for l in libros
                      if rehacer or not l.categoria or l.categoria == SIN_CLASIFICAR]
        if not pendientes:
            return 0

        veredictos = clasificar_libros(
            pendientes,
            categorias=self._categorias_en_uso(libros),
            modelo=self.conf.ia.modelo,
            esfuerzo=self.conf.ia.esfuerzo,
            lote=self.conf.ia.lote,
        )

        cambiados = 0
        for libro in pendientes:
            veredicto = veredictos.get(libro.key)
            if veredicto is None:
                continue
            manual = self._categoria_manual(libro)
            libro.categoria = manual or veredicto.categoria
            libro.descripcion = veredicto.descripcion or libro.descripcion
            self.store.save(libro.key, libro)
            self.sink.write(libro)   # la nota lleva la categoría en el frontmatter
            cambiados += 1
            log.info("IA: %s -> %s (%s)", libro.title, libro.categoria, veredicto.confianza)

        if cambiados:
            self.escribir_indice()
        return cambiados

    def _categorias_en_uso(self, libros: list[Book]) -> list[str]:
        from .categorias import TAXONOMIA

        vistas = [l.categoria for l in libros if l.categoria and l.categoria != SIN_CLASIFICAR]
        return list(dict.fromkeys(list(TAXONOMIA) + vistas + list(self.conf.categorias.values())))

    def _categoria_manual(self, book: Book) -> str | None:
        for patron, categoria in self.conf.categorias.items():
            if patron.casefold() in book.title.casefold():
                return categoria
        return None

    def clasificar_libro(self, book: Book) -> str:
        """Asigna tema al libro. Lo escrito a mano en la configuración manda."""
        if manual := self._categoria_manual(book):
            book.categoria = manual
            return manual

        textos = [h.text for h in book.highlights.values()]
        categoria, _ = clasificar(book.title, book.author, textos)
        book.categoria = categoria
        return categoria

    def libros(self) -> list[Book]:
        return [b for key in self.store.keys() if (b := self.store.load(key))]

    def escribir_indice(self) -> Path:
        """Regenera el índice y una nota por cada temática."""
        from .sinks.indice import _agrupar

        libros = self.libros()
        for libro in libros:  # por si alguno viene de antes de las categorías
            if not libro.categoria:
                self.clasificar_libro(libro)

        por_tema = _agrupar(libros)
        self.temas.write_all(por_tema, self.sink.nombre_nota)
        return self.indice.write(libros, self.sink.nombre_nota)

    def limpiar_titulos(self, dry_run: bool = False) -> list[tuple[str, str]]:
        """Renombra los libros ya guardados con el título limpio.

        Cambiar el título cambia la clave del libro, así que hay que mover el
        estado, fusionar los que acaben coincidiendo y borrar la nota vieja;
        si no, quedarían duplicados al siguiente sync.
        """
        cambios: list[tuple[str, str]] = []
        for key in self.store.keys():
            book = self.store.load(key)
            if book is None:
                continue
            limpio = limpiar_titulo(book.title, book.author)
            if limpio == book.title:
                continue

            cambios.append((book.title, limpio))
            if dry_run:
                continue

            antigua = self.sink.path_for(book)
            nueva_key = slugify(f"{limpio} {book.author or ''}")
            book.title = limpio

            existente = self.store.load(nueva_key) if nueva_key != key else None
            if existente is not None:  # dos títulos sucios que limpian igual
                for hl in book.highlights.values():
                    existente.add(hl)
                book = existente

            self.store.save(nueva_key, book)
            if nueva_key != key:
                (self.store.dir / f"{key}.json").unlink(missing_ok=True)
            nueva = self.sink.write(book)
            if antigua != nueva:
                antigua.unlink(missing_ok=True)
        if cambios and not dry_run:
            self.escribir_indice()
        return cambios

    def compactar_todo(self, dry_run: bool = False) -> list[tuple[str, int]]:
        """Colapsa en los libros ya guardados las versiones duplicadas."""
        resultado: list[tuple[str, int]] = []
        for key in self.store.keys():
            book = self.store.load(key)
            if book is None:
                continue
            descartados = book.compactar()
            if not descartados:
                continue
            resultado.append((book.title, len(descartados)))
            if dry_run:
                continue
            self.store.save(key, book)
            self.sink.write(book)

        if resultado and not dry_run:
            self.escribir_indice()
        return resultado

    def rebuild(self) -> int:
        """Reescribe todas las notas .md desde el estado guardado."""
        count = 0
        for key in self.store.keys():
            book = self.store.load(key)
            if book is None:
                continue
            self.sink.write(book)
            count += 1
        if count:
            self.escribir_indice()
        return count


def _snapshot(book: Book) -> tuple:
    """Huella del contenido de un libro, para detectar cambios reales."""
    return tuple(
        (h.uid, h.text, h.note, h.page, h.location)
        for h in book.sorted_highlights()
    )
