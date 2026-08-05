"""Configuración y rutas del programa."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP = "kindle-sync"

CONFIG_DIR = Path(os.environ.get("KINDLE_SYNC_CONFIG_DIR",
                                 Path.home() / ".config" / APP))
STATE_DIR = Path(os.environ.get("KINDLE_SYNC_STATE_DIR",
                                Path.home() / ".local" / "state" / APP))
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSION_FILE = STATE_DIR / "amazon-session.json"
LOG_FILE = STATE_DIR / "kindle-sync.log"

DEFAULT_CONFIG = """\
# Configuración de kindle-sync

[obsidian]
# Carpeta raíz de tu vault de Obsidian (o cualquier carpeta de notas).
vault = "~/Obsidian/MiVault"
# Subcarpeta dentro del vault donde se crean las notas de cada libro.
subcarpeta = "Kindle"
# Incluir marcadores además de subrayados y notas.
incluir_marcadores = false

[nube]
# Sincroniza desde read.amazon.com mientras lees (requiere Wi-Fi en el Kindle
# y que el libro se haya enviado con «Enviar a Kindle», no por USB).
activado = true
# Cada cuánto se consulta la nube, en segundos.
intervalo = 300
# Limitar a documentos personales (los libros que tú has importado).
solo_documentos_personales = false

[usb]
# Sincroniza My Clippings.txt cuando el Kindle está conectado por cable.
activado = true
# Punto de montaje del Kindle en macOS.
punto_montaje = "/Volumes/Kindle"
# Cada cuánto se comprueba si el Kindle está montado, en segundos.
intervalo = 20
"""


@dataclass
class ObsidianConfig:
    vault: str = "~/Obsidian/MiVault"
    subcarpeta: str = "Kindle"
    incluir_marcadores: bool = False


@dataclass
class CloudConfig:
    activado: bool = True
    intervalo: int = 300
    solo_documentos_personales: bool = False


@dataclass
class UsbConfig:
    activado: bool = True
    punto_montaje: str = "/Volumes/Kindle"
    intervalo: int = 20


@dataclass
class Config:
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)
    nube: CloudConfig = field(default_factory=CloudConfig)
    usb: UsbConfig = field(default_factory=UsbConfig)

    @property
    def clippings_path(self) -> Path:
        return Path(self.usb.punto_montaje).expanduser() / "documents" / "My Clippings.txt"


def load(path: Path | None = None) -> Config:
    path = path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Crea la configuración con: kindle-sync init")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(
        obsidian=ObsidianConfig(**data.get("obsidian", {})),
        nube=CloudConfig(**data.get("nube", {})),
        usb=UsbConfig(**data.get("usb", {})),
    )


def write_default(path: Path | None = None, force: bool = False) -> Path:
    path = path or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
