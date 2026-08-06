"""Avisos del sistema, para no tener que mirar el log.

En macOS usa el centro de notificaciones. En el resto no hace nada: es un
adorno, nunca debe tumbar una sincronización.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger("kindle-sync")


def notificar(titulo: str, mensaje: str, activado: bool = True) -> bool:
    """Lanza una notificación. Devuelve si se pudo enviar."""
    if not activado or sys.platform != "darwin":
        return False

    guion = (f'display notification {_escapar(mensaje)} '
             f'with title {_escapar(titulo)} sound name "Glass"')
    try:
        subprocess.run(["osascript", "-e", guion], capture_output=True,
                       timeout=10, check=True)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("No se pudo notificar: %s", exc)
        return False


def _escapar(texto: str) -> str:
    """Cita para AppleScript, que solo entiende comillas dobles."""
    limpio = texto.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")
    return '"' + limpio[:200] + '"'
