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
# Cuaderno de Kindle: sincroniza mientras lees, pero SOLO los libros
# comprados en Amazon. Los documentos personales no se publican ahí,
# da igual cómo los hayas metido en el dispositivo.
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

[ia]
# Clasifica los libros por temática con OpenAI, leyendo una muestra de sus
# subrayados. Necesita OPENAI_API_KEY en el entorno.
# Sin esto se usa un clasificador por palabras clave, que acierta menos.
activado = false
# Comprueba con «kindle-sync modelos» cuáles admite tu cuenta.
modelo = "gpt-5.6-luna"
# Cuánto razona el modelo, si es de razonamiento: low basta para clasificar.
# Déjalo vacío para no mandar el parámetro.
esfuerzo = "low"
# Libros por petición.
lote = 10

[categorias]
# Correcciones a mano de la clasificación automática. La clave es el título
# del libro (o un trozo suyo) y el valor, la categoría que quieras.
# "The Hard Thing About Hard Things" = "Liderazgo y equipos"

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
class IaConfig:
    activado: bool = False
    modelo: str = "gpt-5.6-luna"
    esfuerzo: str = "low"
    lote: int = 10


@dataclass
class AvisosConfig:
    notificaciones: bool = True


@dataclass
class Config:
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)
    nube: CloudConfig = field(default_factory=CloudConfig)
    usb: UsbConfig = field(default_factory=UsbConfig)
    correo: CorreoConfig = field(default_factory=CorreoConfig)
    ia: IaConfig = field(default_factory=IaConfig)
    avisos: AvisosConfig = field(default_factory=AvisosConfig)
    categorias: dict[str, str] = field(default_factory=dict)

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
        ia=IaConfig(**data.get("ia", {})),
        avisos=AvisosConfig(**data.get("avisos", {})),
        categorias={str(k): str(v) for k, v in data.get("categorias", {}).items()},
    )


def set_valores(path: Path, seccion: str, cambios: dict[str, object]) -> list[str]:
    """Cambia claves de una sección del TOML conservando comentarios y formato.

    Editar el fichero a mano es fácil de equivocar; esto toca solo las claves
    indicadas y solo dentro de su sección.
    """
    lineas = path.read_text(encoding="utf-8").splitlines()
    pendientes = dict(cambios)
    aplicados: list[str] = []

    cabecera = _indice_seccion(lineas, seccion)
    if cabecera is None:
        # La configuración es de una versión anterior a esta sección: se añade
        # al final en vez de fallar. Actualizar el programa no debe obligar a
        # rehacer el fichero.
        if lineas and lineas[-1].strip():
            lineas.append("")
        lineas.append(f"[{seccion}]")
        cabecera = len(lineas) - 1

    fin_seccion = _indice_siguiente_seccion(lineas, cabecera)

    for i in range(cabecera + 1, fin_seccion):
        desnuda = lineas[i].strip()
        clave = desnuda.split("=", 1)[0].strip() if "=" in desnuda else ""
        if clave in pendientes:
            valor = pendientes.pop(clave)
            lineas[i] = f"{clave} = {_toml(valor)}"
            aplicados.append(f"{clave} = {_toml(valor)}")

    for clave, valor in pendientes.items():  # claves que faltaban en el fichero
        lineas.insert(fin_seccion, f"{clave} = {_toml(valor)}")
        aplicados.append(f"{clave} = {_toml(valor)}")
        fin_seccion += 1

    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return aplicados


def _indice_seccion(lineas: list[str], seccion: str) -> int | None:
    for i, linea in enumerate(lineas):
        if linea.strip() == f"[{seccion}]":
            return i
    return None


def _indice_siguiente_seccion(lineas: list[str], desde: int) -> int:
    for i in range(desde + 1, len(lineas)):
        desnuda = lineas[i].strip()
        if desnuda.startswith("[") and desnuda.endswith("]"):
            return i
    return len(lineas)


def _toml(valor: object) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    texto = str(valor).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{texto}"'


def write_default(path: Path | None = None, force: bool = False) -> Path:
    path = path or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
