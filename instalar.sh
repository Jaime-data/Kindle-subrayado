#!/usr/bin/env bash
#
# Instalador de kindle-sync para macOS.
#
#   bash instalar.sh
#
# Se puede volver a ejecutar cuantas veces quieras: no repite lo ya hecho.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VERDE=$'\033[32m'; AMAR=$'\033[33m'; ROJO=$'\033[31m'; NEG=$'\033[1m'; FIN=$'\033[0m'
paso()  { printf "\n%s==> %s%s\n" "$NEG" "$1" "$FIN"; }
ok()    { printf "%s  ✓ %s%s\n" "$VERDE" "$1" "$FIN"; }
aviso() { printf "%s  ! %s%s\n" "$AMAR" "$1" "$FIN"; }
error() { printf "%s  ✗ %s%s\n" "$ROJO" "$1" "$FIN" >&2; exit 1; }

preguntar_si() {  # preguntar_si "¿Texto?" -> 0 si sí
    local respuesta
    read -r -p "  $1 [S/n] " respuesta </dev/tty || return 1
    [[ -z "$respuesta" || "$respuesta" =~ ^[SsYy] ]]
}

buscar_vaults() {
    # Un vault de Obsidian es una carpeta con un subdirectorio .obsidian.
    # Se busca en el HOME, saltándose ~/Library salvo CloudStorage y Mobile
    # Documents, que es justo donde viven los vaults en Google Drive e iCloud
    # (y que quedan más hondos, de ahí la profundidad extra).
    {
        find "$HOME" -maxdepth 5 -type d -name .obsidian \
             -not -path "$HOME/Library/*" -not -path '*/.Trash/*' 2>/dev/null
        for nube in "$HOME/Library/CloudStorage" "$HOME/Library/Mobile Documents"; do
            [[ -d "$nube" ]] && find "$nube" -maxdepth 6 -type d -name .obsidian 2>/dev/null
        done
    } | sort -u
}

escribir_vault() {  # escribir_vault RUTA CONFIG
    VAULT="$1" python - "$2" <<'PY'
import os, pathlib, sys

vault = os.environ["VAULT"]
if '"' in vault or "\\" in vault:
    sys.exit(f"La ruta tiene caracteres que rompen el TOML: {vault}")

p = pathlib.Path(sys.argv[1])
texto = p.read_text(encoding="utf-8")
nuevo = texto.replace('vault = "~/Obsidian/MiVault"', f'vault = "{vault}"')
if nuevo == texto:
    sys.exit("No he podido escribir la ruta en la configuración; edítala a mano.")
p.write_text(nuevo, encoding="utf-8")
PY
}

VAULT_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --vault) VAULT_ARG="${2:-}"; shift 2 ;;
        -h|--help)
            echo "Uso: bash instalar.sh [--vault RUTA]"
            echo "  --vault RUTA   carpeta de notas destino (si no, la busca sola)"
            exit 0 ;;
        *) error "Opción desconocida: $1" ;;
    esac
done

[[ -t 0 || -e /dev/tty ]] || error "Ejecútalo en una terminal: hace falta responder preguntas."

# --- 1. Python -------------------------------------------------------------

paso "Comprobando Python"
PY=""
for candidato in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidato" >/dev/null 2>&1 &&
       "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PY="$candidato"; break
    fi
done
[[ -n "$PY" ]] || error "Hace falta Python 3.11 o superior. Instálalo con: brew install python@3.12"
ok "$($PY --version)"

# --- 2. Entorno virtual y dependencias -------------------------------------

paso "Preparando el entorno"
[[ -d .venv ]] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
python -m pip install --quiet -e ".[nube]"
ok "kindle-sync instalado"

if python -c 'import playwright' 2>/dev/null; then
    if python -m playwright install chromium >/dev/null 2>&1; then
        ok "Navegador listo"
    else
        aviso "No se pudo descargar Chromium (¿sin conexión?)."
        aviso "Reintenta luego con: python -m playwright install chromium"
    fi
fi

# --- 3. Configuración ------------------------------------------------------

paso "Configuración"
CONFIG="${KINDLE_SYNC_CONFIG_DIR:-$HOME/.config/kindle-sync}/config.toml"
kindle-sync init >/dev/null

if [[ -n "$VAULT_ARG" ]]; then
    VAULT="${VAULT_ARG/#\~/$HOME}"
    [[ -d "$VAULT" ]] || error "No existe la carpeta: $VAULT"
    escribir_vault "$VAULT" "$CONFIG"
    ok "Vault: $VAULT"
elif grep -q '~/Obsidian/MiVault' "$CONFIG"; then
    echo "  Buscando tus vaults de Obsidian…"
    VAULTS=()
    while IFS= read -r hallado; do
        VAULTS+=("$(dirname "$hallado")")
    done < <(buscar_vaults)

    VAULT=""
    if [[ ${#VAULTS[@]} -eq 1 ]]; then
        VAULT="${VAULTS[0]}"
        ok "Encontrado: $VAULT"
        preguntar_si "¿Uso este?" || VAULT=""
    elif [[ ${#VAULTS[@]} -gt 1 ]]; then
        echo "  He encontrado varios:"
        for i in "${!VAULTS[@]}"; do echo "    $((i + 1))) ${VAULTS[$i]}"; done
        read -r -p "  ¿Cuál uso? [1-${#VAULTS[@]}, o Intro para escribir otra ruta] " n </dev/tty
        [[ -n "$n" ]] && VAULT="${VAULTS[$((n - 1))]}"
    fi

    while [[ -z "$VAULT" || ! -d "$VAULT" ]]; do
        read -r -p "  Ruta de tu vault de Obsidian: " VAULT </dev/tty
        VAULT="${VAULT/#\~/$HOME}"
        [[ -d "$VAULT" ]] || aviso "No existe esa carpeta."
    done

    escribir_vault "$VAULT" "$CONFIG"
    ok "Vault: $VAULT"
else
    ok "Ya estaba configurado ($CONFIG)"
fi

# --- 4. Sesión de Amazon ---------------------------------------------------

paso "Sesión de Amazon"
SESION="${KINDLE_SYNC_STATE_DIR:-$HOME/.local/state/kindle-sync}/amazon-session.json"
if [[ -f "$SESION" ]]; then
    ok "Ya hay una sesión guardada"
else
    echo "  Se abrirá un navegador. Inicia sesión con tu cuenta de Amazon"
    echo "  (contraseña y verificación en dos pasos). Solo hay que hacerlo una vez."
    preguntar_si "¿Seguimos?" || error "Sin sesión no se puede leer de la nube."
    kindle-sync login
fi

# --- 5. Diagnóstico --------------------------------------------------------

paso "Esto es lo que veo en tu cuenta"
if ! kindle-sync libros; then
    aviso "No he podido leer tu biblioteca."
    echo "  Genera un volcado para poder depurarlo:"
    echo "    source .venv/bin/activate && kindle-sync libros --dump ~/Desktop/kindle-dump"
    exit 1
fi

# --- 6. Primera sincronización --------------------------------------------

paso "Primera sincronización"
if preguntar_si "¿Escribo ya las notas en tu vault?"; then
    kindle-sync sync
    kindle-sync status
fi

# --- 7. Automatizar --------------------------------------------------------

paso "Automatizar"
echo "  Deja un proceso en segundo plano que sincroniza solo cada 5 minutos,"
echo "  y que arranca al encender el Mac."
if preguntar_si "¿Lo instalo?"; then
    kindle-sync install-agent
fi

paso "Listo"
cat <<EOF
  Para usar los comandos a mano, activa antes el entorno:

    cd "$PWD" && source .venv/bin/activate

  Comprobar el estado : kindle-sync status
  Ver el registro     : tail -f ~/.local/state/kindle-sync/kindle-sync.log
  Quitar el automático: kindle-sync uninstall-agent
EOF
