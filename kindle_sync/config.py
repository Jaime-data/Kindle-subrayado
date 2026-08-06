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
# Es la única fuente para los libros que envías con «Enviar a Kindle»:
# Amazon no publica sus anotaciones en read.amazon.com.
activado = true
# "auto" busca el Kindle por /Volumes. También puedes fijarlo,
# por ejemplo "/Volumes/Kindle".
punto_montaje = "auto"
# Cada cuánto se comprueba si el Kindle está montado, en segundos.
intervalo = 20

[correo]
# Recoge los correos de «Notas → Exportar» del Kindle. Es la vía por Wi-Fi
# para los libros que Amazon no publica en la web.
activado = false
servidor = "imap.gmail.com"
puerto = 993
usuario = "tu-cuenta@ejemplo.com"
carpeta = "INBOX"
# Cuántos días atrás mirar en cada pasada.
dias = 30
# Cada cuánto se revisa el buzón, en segundos.
intervalo = 900

[avisos]
# Notificación de macOS cuando llegan subrayados nuevos.
notificaciones = true
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
    punto_montaje: str = "auto"
    intervalo: int = 20


@dataclass
class CorreoConfig:
    activado: bool = False
    servidor: str = "imap.gmail.com"
    puerto: int = 993
    usuario: str = ""
    carpeta: str = "INBOX"
    dias: int = 30
    intervalo: int = 900


@dataclass
class AvisosConfig:
    notificaciones: bool = True


@dataclass
class Config:
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)
    nube: CloudConfig = field(default_factory=CloudConfig)
    usb: UsbConfig = field(default_factory=UsbConfig)
    correo: CorreoConfig = field(default_factory=CorreoConfig)
    avisos: AvisosConfig = field(default_factory=AvisosConfig)

    @property
    def clippings_path(self) -> Path | None:
        """Ruta a My Clippings.txt, o None si el Kindle no está conectado.

        Con `punto_montaje = "auto"` se recorre /Volumes buscando el fichero:
        los Kindle no siempre se montan como «Kindle» (un segundo dispositivo
        aparece como «Kindle 1», y algunos modelos usan otro nombre).
        """
        if self.usb.punto_montaje != "auto":
            return Path(self.usb.punto_montaje).expanduser() / "documents" / "My Clippings.txt"

        for volumen in sorted(Path("/Volumes").glob("*")):
            candidato = volumen / "documents" / "My Clippings.txt"
            if candidato.exists():
                return candidato
        return None


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
        correo=CorreoConfig(**data.get("correo", {})),
        avisos=AvisosConfig(**data.get("avisos", {})),
    )


def write_default(path: Path | None = None, force: bool = False) -> Path:
    path = path or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
