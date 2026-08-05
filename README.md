# kindle-sync

Sube automáticamente los subrayados de tu Kindle a tus notas de Obsidian.
Una nota Markdown por libro, sin duplicados, incremental.

Pensado para **macOS** y para **libros importados** (los que tú metes en el
Kindle, no comprados en Amazon).

---

## Antes de nada: qué es posible y qué no

Esto es importante porque determina si conseguirás sincronizar *mientras lees*
o solo al enchufar el cable. Depende de **cómo metiste el libro en el Kindle**:

| Cómo importaste el libro | Dónde acaban los subrayados | ¿Sincroniza mientras lees? |
|---|---|---|
| **Enviar a Kindle** (email o app de escritorio) | En la nube de Amazon (`read.amazon.com/notebook`) y en el Kindle | **Sí.** Con el Kindle en Wi-Fi, el subrayado sube en segundos |
| **Cable USB** (arrastrar a `documents/`) | Solo en `My Clippings.txt`, dentro del Kindle | **No.** Solo al conectar el cable |

Con USB no hay truco posible: mientras el Kindle está montado en el Mac no
puedes leer, y mientras lees el Mac no ve su memoria. Nadie puede sortear eso.

**Si quieres sincronización en vivo, manda tus libros con «Enviar a Kindle»**
en vez de por cable. Se convierten en documentos personales y sus anotaciones
viajan a la nube igual que las de un libro comprado.

`kindle-sync` lee de las **dos** fuentes y las fusiona: si un subrayado llega
por los dos caminos, se guarda una sola vez.

---

## Instalación

Requiere Python 3.11 o superior.

```bash
git clone <este-repo> kindle-sync && cd kindle-sync
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[nube]"
python -m playwright install chromium    # solo si vas a usar la nube
```

## Puesta en marcha

```bash
kindle-sync init          # crea ~/.config/kindle-sync/config.toml
```

Edita ese fichero y pon la ruta de tu vault:

```toml
[obsidian]
vault = "~/Documentos/MiVault"
subcarpeta = "Kindle"
```

Inicia sesión en Amazon una sola vez (se abre un navegador; haz login con tu
contraseña y tu 2FA, la sesión queda guardada):

```bash
kindle-sync login
```

Primera sincronización a mano, para comprobar que todo va:

```bash
kindle-sync sync
kindle-sync status
```

Y ya en automático, para que arranque solo al encender el Mac:

```bash
kindle-sync install-agent
```

A partir de aquí no tienes que hacer nada: subrayas leyendo, y en unos minutos
aparece en Obsidian.

## Comandos

| Comando | Qué hace |
|---|---|
| `kindle-sync init` | Crea la configuración inicial |
| `kindle-sync login` | Guarda la sesión de Amazon (una vez cada varios meses) |
| `kindle-sync sync` | Sincroniza una vez y termina |
| `kindle-sync sync --dry-run` | Enseña qué haría, sin escribir |
| `kindle-sync sync --source clippings` | Solo desde el cable USB |
| `kindle-sync sync --source cloud` | Solo desde la nube |
| `kindle-sync watch` | Vigila en primer plano (útil para depurar) |
| `kindle-sync status` | Estado: destino, Kindle conectado, sesión, agente |
| `kindle-sync rebuild` | Regenera todos los `.md` desde el estado guardado |
| `kindle-sync install-agent` / `uninstall-agent` | Arranque automático con launchd |

## Cómo queda la nota en Obsidian

```markdown
---
titulo: "Sapiens"
autor: "Yuval Noah Harari"
fuente: kindle
subrayados: 34
actualizado: 2026-08-05T21:02:30
tags:
  - kindle
  - subrayados
---

# Sapiens

*Yuval Noah Harari*

> [!quote] pág. 24 · pos. 356-357 · 04/08/2025
> Los humanos evolucionaron para pensar en individuos.
^k-68cec1e1f846

<!-- kindle-sync:fin -->
```

Detalles que importan:

- El `^k-…` es un **ID de bloque de Obsidian**: puedes enlazar un subrayado
  concreto desde otra nota con `[[Sapiens - Yuval Noah Harari#^k-68cec1e1f846]]`.
- El fichero **se regenera** en cada sincronización, para mantener los
  subrayados ordenados por posición. **Todo lo que escribas por debajo de
  `<!-- kindle-sync:fin -->` se conserva intacto** — escribe ahí tus notas.
- Nada se borra nunca: el historial vive en `~/.local/state/kindle-sync/books/`.
  Si pierdes el vault, `kindle-sync rebuild` lo reconstruye entero.

## Configuración

```toml
[obsidian]
vault = "~/Obsidian/MiVault"
subcarpeta = "Kindle"
incluir_marcadores = false          # los marcadores sin texto suelen ser ruido

[nube]
activado = true
intervalo = 300                     # segundos entre consultas a Amazon
solo_documentos_personales = false  # true = ignora los libros comprados

[usb]
activado = true
punto_montaje = "/Volumes/Kindle"
intervalo = 20                      # cada cuánto mira si has enchufado el cable
```

## Si algo no va

```bash
tail -f ~/.local/state/kindle-sync/kindle-sync.log
```

- **«La sesión de Amazon ha caducado»** → `kindle-sync login` otra vez.
- **La nube no devuelve tu libro importado** → lo metiste por USB. Vuelve a
  enviarlo con «Enviar a Kindle» o sincroniza por cable.
- **El Kindle no aparece en `/Volumes/Kindle`** → míralo con `ls /Volumes` y
  ajusta `punto_montaje` (algunos modelos se montan como `Kindle 1`).
- **El agente no arranca** → `launchctl list | grep kindle-sync`, y revisa el log.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest
```
