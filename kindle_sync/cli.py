"""Interfaz de línea de comandos de kindle-sync."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import config as cfg
from .sync import Syncer
from .watcher import Watcher

AGENT_LABEL = "com.kindle-sync.agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kindle-sync",
        description="Sube los subrayados del Kindle a tus notas de Obsidian.")
    parser.add_argument("-v", "--verbose", action="store_true", help="más detalle en el log")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea el fichero de configuración")

    p_login = sub.add_parser("login", help="inicia sesión en Amazon (una sola vez)")
    p_login.add_argument("--headless", action="store_true",
                         help="sin ventana (solo si ya tienes cookies válidas)")

    p_sync = sub.add_parser("sync", help="sincroniza una vez y termina")
    p_sync.add_argument("--source", choices=["clippings", "cloud", "all"], default="all",
                        help="de dónde leer (por defecto: ambas)")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="enseña qué haría sin escribir nada")

    p_libros = sub.add_parser(
        "libros", help="diagnóstico: lista lo que el programa ve en tu cuenta de Amazon")
    p_libros.add_argument("--dump", metavar="CARPETA", type=Path,
                          help="guarda el HTML y capturas para depurar")

    p_lector = sub.add_parser(
        "lector", help="sondea el Lector Web de Kindle en busca de tus documentos personales")
    p_lector.add_argument("--dump", metavar="CARPETA", type=Path,
                          help="guarda el HTML y capturas del lector")
    p_lector.add_argument("--api", action="store_true",
                          help="pregunta a la API del lector por cada tipo de biblioteca")
    p_lector.add_argument("--codigo", action="store_true",
                          help="busca en el JavaScript del lector los tipos válidos")

    sub.add_parser("watch", help="vigila en segundo plano y sincroniza solo")
    sub.add_parser("rebuild", help="regenera los .md desde el estado guardado")
    sub.add_parser("status", help="muestra configuración y estado actual")
    sub.add_parser("install-agent", help="instala el arranque automático (launchd)")
    sub.add_parser("uninstall-agent", help="desinstala el arranque automático")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        return _dispatch(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ImportError:
        print("error: falta Playwright, necesario para leer de la nube.\n"
              '  pip install "kindle-sync[nube]" && python -m playwright install chromium',
              file=sys.stderr)
        return 2
    except RuntimeError as exc:  # incluye NotLoggedIn
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _dispatch(args) -> int:
    if args.cmd == "init":
        path = cfg.write_default()
        print(f"Configuración en {path}")
        print("Edita la ruta de tu vault de Obsidian y luego: kindle-sync login")
        return 0

    if args.cmd == "login":
        from .sources.amazon_cloud import login
        login(cfg.SESSION_FILE, headless=args.headless)
        return 0

    if args.cmd == "libros":
        return _libros(args.dump)

    if args.cmd == "lector":
        if args.codigo:
            return _lector_codigo()
        return _lector_api() if args.api else _lector(args.dump)

    if args.cmd == "install-agent":
        return _install_agent()

    if args.cmd == "uninstall-agent":
        return _uninstall_agent()

    conf = cfg.load()

    if args.cmd == "status":
        return _status(conf)

    if args.cmd == "sync":
        sources = ("clippings", "cloud") if args.source == "all" else (args.source,)
        syncer = Syncer(conf, dry_run=args.dry_run)
        result = syncer.sync(sources)
        print(result)
        return 1 if result.errores and not result.nuevos else 0

    if args.cmd == "rebuild":
        n = Syncer(conf).rebuild()
        print(f"{n} nota(s) regenerada(s)")
        return 0

    if args.cmd == "watch":
        Watcher(conf).run()
        return 0

    return 1


def _libros(dump: Path | None) -> int:
    from .sources.amazon_cloud import list_books

    libros = list_books(cfg.SESSION_FILE, dump_dir=dump)
    if not libros:
        print("Amazon no ha devuelto ningún libro.")
        print("Si tu biblioteca no está vacía, la página ha cambiado:")
        print("  kindle-sync libros --dump ~/Desktop/kindle-dump")
        return 1

    ancho = min(60, max(len(b["titulo"]) for b in libros))
    personales = 0
    for b in sorted(libros, key=lambda b: -b["subrayados"]):
        tipo = "personal" if b["documento_personal"] else "tienda  "
        personales += b["documento_personal"]
        print(f"{b['titulo'][:ancho]:<{ancho}}  {tipo}  {b['subrayados']:>4} subrayado(s)")

    total = sum(b["subrayados"] for b in libros)
    print(f"\n{len(libros)} libro(s), {personales} importado(s) por ti, "
          f"{total} subrayado(s) en total.")
    if dump:
        print(f"Volcado guardado en {dump}")
    return 0


def _lector_codigo() -> int:
    from .sources.web_reader import analizar_bundle, probar_variantes

    print("Buscando en el código del lector los valores válidos…\n")
    hallazgos = analizar_bundle(cfg.SESSION_FILE)
    print(f"Bundles revisados: {hallazgos['bundles']}")

    print("\nValores de libraryType encontrados en el código:")
    for valor in hallazgos["library_type"] or ["  (ninguno)"]:
        print(f"  {valor}")

    print("\nConstantes en mayúsculas cerca de «libraryType»:")
    for valor in hallazgos["mayusculas_cerca"][:40] or ["  (ninguna)"]:
        print(f"  {valor}")

    print("\nRutas de API que menciona el código:")
    for ruta in hallazgos["rutas"][:25] or ["  (ninguna)"]:
        print(f"  {ruta}")

    print("\nVariantes de la consulta con libraryType=BOOKS:")
    for v in probar_variantes(cfg.SESSION_FILE):
        marca = "JSON" if v["json"] else "html"
        print(f"  {v['estado']}  {marca}  {v['ruta'][:95]}")
        if v["json"]:
            print(f"        {v['muestra'][:150]}")
    return 0


def _lector_api() -> int:
    from .sources.web_reader import explorar_biblioteca

    print("Preguntando a la API del lector por cada tipo de biblioteca…\n")
    hallazgo = False
    for r in explorar_biblioteca(cfg.SESSION_FILE):
        estado = r["estado"]
        if "error" in r:
            print(f"  {r['tipo']:<14} {estado}  (respuesta no JSON) {r['error'][:60]}")
            continue
        print(f"  {r['tipo']:<14} {estado}  {r['elementos']:>3} elemento(s)")
        for asin, titulo in zip(r["asins"], r["titulos"]):
            print(f"       · {asin:<16} {titulo}")
        if r["elementos"] and r["tipo"] != "BOOKS":
            hallazgo = True
        if r.get("claves"):
            print(f"       campos: {', '.join(r['claves'][:12])}")

    if hallazgo:
        print("\nHay documentos fuera de BOOKS: esta vía sirve.")
    else:
        print("\nSolo aparecen libros comprados.")
    return 0


def _lector(dump: Path | None) -> int:
    from .sources.web_reader import sondear

    informe = sondear(cfg.SESSION_FILE, dump_dir=dump)

    print(f"URL final       : {informe['url_final']}")
    print(f"Título página   : {informe['titulo_pagina']}")
    print(f"Sesión válida   : {'sí' if informe['sesion_valida'] else 'NO (pide login)'}")
    print(f"Habla de «docs» : {'sí' if informe['menciona_documentos'] else 'no'}")

    print("\nElementos encontrados por selector:")
    for selector, n in informe["candidatos"].items():
        print(f"  {n:>4}  {selector}")

    print("\nPosibles controles de filtrado:")
    for selector, n in informe["filtros"].items():
        print(f"  {n:>4}  {selector}")

    print("\nMuestras de las primeras entradas:")
    for muestra in informe["muestras"] or ["  (ninguna)"]:
        print(f"  · {muestra}")

    print("\nRespuestas de Amazon que traen libros:")
    for r in informe.get("trafico") or []:
        personales = ", ".join(r.get("asin_personal") or []) or "ninguno"
        print(f"  {r['estado']}  {r.get('bytes', 0):>7} B  "
              f"comprados={r.get('asin_tienda', 0)}  personales={personales}")
        print(f"        {r['url'][:120]}")
    if not informe.get("trafico"):
        print("  (ninguna: la biblioteca no llegó a cargar)")

    vista = (informe.get("itemViewResponse") or "").strip()
    print(f"\n#itemViewResponse: {vista[:300] if vista else '(vacío)'}")

    if dump:
        print(f"\nVolcado guardado en {dump}")
    return 0


def _status(conf: cfg.Config) -> int:
    vault = Path(conf.obsidian.vault).expanduser() / conf.obsidian.subcarpeta
    clippings = conf.clippings_path
    notas = len(list(vault.glob("*.md"))) if vault.exists() else 0

    print(f"Configuración   : {cfg.CONFIG_FILE}")
    print(f"Carpeta destino : {vault} ({'existe' if vault.exists() else 'aún no creada'})")
    print(f"Notas escritas  : {notas}")
    if clippings and clippings.exists():
        print(f"Kindle por USB  : conectado ({clippings.parent.parent})")
    else:
        print("Kindle por USB  : no conectado")
    print(f"Sesión Amazon   : {'guardada' if cfg.SESSION_FILE.exists() else 'no iniciada'}")
    print(f"Nube            : {'activada' if conf.nube.activado else 'desactivada'}"
          f" · cada {conf.nube.intervalo}s")
    print(f"Agente launchd  : {'instalado' if PLIST_PATH.exists() else 'no instalado'}")
    print(f"Log             : {cfg.LOG_FILE}")
    return 0


def _install_agent() -> int:
    if sys.platform != "darwin":
        print("El arranque automático con launchd solo aplica a macOS.", file=sys.stderr)
        return 2

    template = Path(__file__).resolve().parent / "agent.plist.template"
    plist = template.read_text(encoding="utf-8").format(
        label=AGENT_LABEL,
        python=sys.executable,
        log=cfg.LOG_FILE,
        home=str(Path.home()),
        path=os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    )
    cfg.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist, encoding="utf-8")

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                   capture_output=True, check=False)
    proc = subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode
    print(f"Agente instalado: {PLIST_PATH}")
    print("Arrancará solo al iniciar sesión. Log en", cfg.LOG_FILE)
    return 0


def _uninstall_agent() -> int:
    if not PLIST_PATH.exists():
        print("No hay agente instalado.")
        return 0
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                   capture_output=True, check=False)
    PLIST_PATH.unlink()
    print("Agente desinstalado.")
    return 0


def _setup_logging(verbose: bool) -> None:
    cfg.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(logging.FileHandler(cfg.LOG_FILE, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
