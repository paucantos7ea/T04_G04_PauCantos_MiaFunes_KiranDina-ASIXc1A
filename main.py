#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escáner y analizador interactivo de incidencias en XML — punto de entrada CLI.

Uso (desde cualquier carpeta y en cualquier sistema operativo):

    python main.py                          # busca respotes.xml / incidencies.xml
    python main.py --file ruta/al/archivo.xml
    python ruta/al/proyecto/main.py -f datos.xml
    python main.py --web                    # interfaz web (Chrome en PC y móvil)
    python main.py --web --port 8502 -f datos.xml

La interfaz web también se puede lanzar directamente con Streamlit:

    streamlit run web.py --server.address 0.0.0.0

Búsqueda automática del XML si no se pasa --file:
    1. Directorio actual desde el que se lanza el comando (Path.cwd()).
    2. Carpeta raíz del proyecto (donde está este main.py).
    3. Si no está en ninguna, se pide la ruta de forma interactiva y no se
       continúa hasta que el archivo exista.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent

# Permite lanzar el programa desde cualquier carpeta: el paquete app/ siempre
# se importa desde la raíz del proyecto, no desde el directorio actual.
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

DEPENDENCIAS = ("rich", "questionary")
DEPENDENCIAS_WEB = ("rich", "streamlit", "plotly")
PUERTO_WEB = 8501


def dependencias_ok(modulos: tuple[str, ...] = DEPENDENCIAS) -> bool:
    """Comprueba las librerías antes de importarlas (mensaje claro, sin traceback)."""
    faltan = [m for m in modulos if importlib.util.find_spec(m) is None]
    if faltan:
        requisitos = RAIZ_PROYECTO / "requirements.txt"
        print(f"Faltan dependencias: {', '.join(faltan)}\n"
              f"Instalalas con:\n    python -m pip install -r \"{requisitos}\"",
              file=sys.stderr)
        return False
    return True


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Escáner y analizador interactivo de incidencias en XML.",
        epilog="Sin --file se busca respotes.xml o incidencies.xml en el directorio "
               "actual y en la carpeta del proyecto.")
    parser.add_argument("-f", "--file", metavar="RUTA",
                        help="ruta al archivo XML (relativa al directorio actual o absoluta)")
    parser.add_argument("--web", action="store_true",
                        help="abre la interfaz web en tiempo real (Streamlit) en lugar del "
                             "menú de terminal")
    parser.add_argument("--port", type=int, default=PUERTO_WEB, metavar="N",
                        help=f"puerto de la interfaz web (por defecto {PUERTO_WEB})")
    parser.add_argument("--clave", metavar="TEXTO",
                        help="con --web: contraseña para entrar en la web "
                             "(también: variable de entorno MONITOR_CLAVE)")
    return parser


# ══════════════════════════════════════════════════════════════════════════
# Interfaz web (--web)
# ══════════════════════════════════════════════════════════════════════════

def ip_local() -> str:
    """IP de esta máquina en la red local (la que usará el móvil).

    Conectar un socket UDP no envía ningún paquete: solo pide al sistema qué
    interfaz usaría para salir, y de ella se lee la IP.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def puerto_libre(desde: int, intentos: int = 20) -> int:
    """Primer puerto libre a partir de `desde` (por si 8501 ya está ocupado)."""
    for puerto in range(desde, desde + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", puerto))
                return puerto
            except OSError:
                continue
    return desde


def lanzar_web(args: argparse.Namespace) -> int:
    """Arranca `streamlit run web.py` escuchando en toda la red local."""
    from rich.panel import Panel
    from rich.text import Text

    from app.ui.console import obtener_consola, panel_error
    from app.utils import limpiar_ruta

    consola = obtener_consola()
    web = RAIZ_PROYECTO / "web.py"
    if not web.is_file():
        consola.print(panel_error("Falta web.py", f"No se encuentra:\n{web}"))
        return 1

    puerto = puerto_libre(args.port)
    ip = ip_local()
    clave = args.clave or os.environ.get("MONITOR_CLAVE", "")
    texto = Text()
    texto.append("Abre en Google Chrome:\n\n", style="bold")
    texto.append("  💻 PC (este equipo)       ", style="dim")
    texto.append(f"http://localhost:{puerto}\n", style="bold cyan underline")
    texto.append("  📱 Móvil (misma Wi-Fi)    ", style="dim")
    texto.append(f"http://{ip}:{puerto}\n\n", style="bold green underline")
    if puerto != args.port:
        texto.append(f"El puerto {args.port} estaba ocupado: se usa el {puerto}.\n", style="yellow")
    if ip == "127.0.0.1":
        texto.append("No se ha detectado una red local: el móvil no podrá conectar.\n",
                     style="yellow")
    texto.append("Desde cualquier red: publícala en Streamlit Community Cloud (ver README).\n",
                 style="dim")
    if clave:
        texto.append("🔒 Protegido con contraseña.\n", style="green")
    texto.append("Ctrl+C detiene el servidor.", style="dim")
    consola.print(Panel(texto, title="[bold]🌐 Monitor web de incidencias[/]",
                        border_style="cyan", expand=False, padding=(1, 2)))

    comando = [sys.executable, "-m", "streamlit", "run", str(web),
               "--server.address", "0.0.0.0", "--server.port", str(puerto),
               "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    if args.file:      # Ruta absoluta: el servidor no depende del directorio actual
        comando += ["--", "--file", str(limpiar_ruta(args.file))]
    entorno = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if clave:
        entorno["MONITOR_CLAVE"] = clave  # Por entorno: no aparece en la lista de procesos
    try:
        return subprocess.call(comando, env=entorno)
    except KeyboardInterrupt:             # Ctrl+C: Streamlit ya se cierra solo
        return 0


def localizar_xml(argumento: str | None) -> tuple[Path | None, str | None]:
    """Devuelve (ruta encontrada, aviso). Si la ruta es None, hay que pedirla."""
    from app.config import NOMBRES_XML_DEFECTO
    from app.utils import limpiar_ruta

    if argumento:
        ruta = limpiar_ruta(argumento)
        if ruta.is_file():
            return ruta, None
        return None, f"No se encuentra el archivo indicado con --file:\n{ruta}"

    carpetas: list[Path] = []
    try:
        carpetas.append(Path.cwd())
    except OSError:                       # El directorio actual ya no existe
        pass
    carpetas.append(RAIZ_PROYECTO)

    for carpeta in dict.fromkeys(carpetas):        # Sin duplicados, en orden
        for nombre in NOMBRES_XML_DEFECTO:
            candidato = carpeta / nombre
            if candidato.is_file():
                return candidato.resolve(), None

    buscados = " ni ".join(NOMBRES_XML_DEFECTO)
    lugares = "\n".join(f"  • {c}" for c in dict.fromkeys(carpetas))
    return None, f"No se ha encontrado {buscados} en:\n{lugares}\nIndica la ruta del archivo."


def main(argv: list[str] | None = None) -> int:
    """Bucle principal protegido: ninguna excepción llega al usuario como traceback."""
    args = crear_parser().parse_args(argv)
    if args.web:
        return lanzar_web(args) if dependencias_ok(DEPENDENCIAS_WEB) else 1
    if not dependencias_ok():
        return 1

    from app.models import ErrorCarga
    from app.ui.console import obtener_consola, panel_aviso, panel_despedida, panel_error

    consola = obtener_consola()           # Fuerza UTF-8 antes de imprimir nada

    try:
        from app.ui.menus import App

        ruta, aviso = localizar_xml(args.file)
        if aviso:
            consola.print(panel_aviso(aviso))
        codigo = App(consola).ejecutar(ruta)
        consola.print(panel_despedida())
        return codigo
    except KeyboardInterrupt:             # Ctrl+C en cualquier punto
        consola.print()
        consola.print(panel_despedida())
        return 0
    except ErrorCarga as error:
        consola.print(panel_error(error.titulo, error.mensaje))
    except ET.ParseError as error:
        consola.print(panel_error("XML malformado", f"El documento no es un XML válido.\n{error}"))
    except FileNotFoundError as error:
        consola.print(panel_error("Archivo no encontrado", str(error)))
    except PermissionError as error:
        consola.print(panel_error("Sin permisos", str(error)))
    except Exception as error:  # noqa: BLE001 — último recurso, a propósito
        consola.print(panel_error("Error inesperado",
                                  f"{type(error).__name__}: {error}\n\n"
                                  "El programa se ha cerrado de forma controlada."))
    return 1


if __name__ == "__main__":
    sys.exit(main())
