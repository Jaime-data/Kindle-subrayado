"""Guarda la contraseña del correo en el Llavero de macOS.

Un fichero de configuración acaba en copias de seguridad, en Drive y en
cualquier `cat` distraído. El Llavero está cifrado y lo gestiona el sistema.
Fuera de macOS se recurre a una variable de entorno.
"""

from __future__ import annotations

import os
import subprocess
import sys

SERVICIO = "kindle-sync"
VARIABLE = "KINDLE_SYNC_PASSWORD"


class SinContrasena(RuntimeError):
    pass


def guardar(cuenta: str, contrasena: str) -> None:
    if sys.platform != "darwin":
        raise SinContrasena(
            f"Fuera de macOS, exporta la contraseña en {VARIABLE}")

    subprocess.run(
        ["security", "add-generic-password", "-U",
         "-s", SERVICIO, "-a", cuenta, "-w", contrasena],
        check=True, capture_output=True)


def leer(cuenta: str) -> str:
    if valor := os.environ.get(VARIABLE):
        return valor

    if sys.platform != "darwin":
        raise SinContrasena(f"No hay contraseña: exporta {VARIABLE}")

    proc = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICIO, "-a", cuenta, "-w"],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SinContrasena(
            "No hay contraseña guardada para esa cuenta. "
            "Ejecuta: kindle-sync correo --configurar")
    return proc.stdout.strip()


def borrar(cuenta: str) -> bool:
    if sys.platform != "darwin":
        return False
    proc = subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICIO, "-a", cuenta],
        capture_output=True, check=False)
    return proc.returncode == 0
