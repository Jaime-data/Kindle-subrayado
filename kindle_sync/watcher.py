"""Demonio que sincroniza solo, sin que tengas que ejecutar nada.

Dos relojes independientes:

* USB   — comprueba cada pocos segundos si el Kindle está montado y si
          `My Clippings.txt` ha cambiado de tamaño o fecha.
* Nube  — consulta el Cuaderno de Kindle cada N minutos, que es lo que
          permite que un subrayado hecho mientras lees acabe en Obsidian
          sin tocar el cable.
"""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from . import config as cfg
from .notify import notificar
from .sync import Syncer

log = logging.getLogger("kindle-sync")

TICK = 5  # segundos entre latidos del bucle principal


class Watcher:
    def __init__(self, conf: cfg.Config):
        self.conf = conf
        self.syncer = Syncer(conf)
        self._stop = False
        self._last_cloud = 0.0
        self._last_correo = 0.0
        self._last_usb_check = 0.0
        self._clippings_stamp: tuple[int, float] | None = None

    def stop(self, *_args) -> None:
        log.info("Parando…")
        self._stop = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        log.info("Vigilando. USB cada %ss · correo cada %ss · nube cada %ss",
                 self.conf.usb.intervalo,
                 self.conf.correo.intervalo if self.conf.correo.activado else "—",
                 self.conf.nube.intervalo)

        while not self._stop:
            now = time.monotonic()

            if self.conf.usb.activado and now - self._last_usb_check >= self.conf.usb.intervalo:
                self._last_usb_check = now
                self._tick_usb()

            if (self.conf.correo.activado
                    and now - self._last_correo >= self.conf.correo.intervalo):
                self._last_correo = now
                self._run("correo", ("correo",))

            if self.conf.nube.activado and now - self._last_cloud >= self.conf.nube.intervalo:
                self._last_cloud = now
                self._tick_cloud()

            time.sleep(TICK)

    # --- ciclos ------------------------------------------------------------

    def _tick_usb(self) -> None:
        path = self.conf.clippings_path
        stamp = _stamp(path)
        if stamp is None:
            self._clippings_stamp = None  # Kindle desconectado
            return
        if stamp == self._clippings_stamp:
            return  # montado pero sin cambios desde la última lectura
        self._clippings_stamp = stamp
        self._run("USB", ("clippings",))

    def _tick_cloud(self) -> None:
        self._run("nube", ("cloud",))

    def _run(self, etiqueta: str, sources: tuple[str, ...]) -> None:
        try:
            result = self.syncer.sync(sources)
        except Exception:  # el demonio nunca debe morir por un fallo puntual
            log.exception("Error sincronizando desde %s", etiqueta)
            return
        if result.nuevos:
            log.info("[%s] %s", etiqueta, result)
            notificar(
                f"{result.nuevos} subrayado(s) nuevo(s)",
                ", ".join(result.libros_tocados),
                activado=self.conf.avisos.notificaciones,
            )
        else:
            log.debug("[%s] %s", etiqueta, result)


def _stamp(path: Path | None) -> tuple[int, float] | None:
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime)
