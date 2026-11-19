#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escáner y analizador interactivo de incidencias en XML — punto de entrada CLI.

Uso (desde cualquier carpeta y en cualquier sistema operativo):

    python main.py                          # busca respotes.xml / incidencies.xml
    python main.py --file ruta/al/archivo.xml
    python ruta/al/proyecto/main.py -f datos.xml
    python main.py --html                   # index.html estático para GitHub Pages
    python main.py --demo                   # inyecta 1 crítica + 1 anomalía de prueba
    python main.py --web                    # web + túnel público con QR (cualquier red)
    python main.py --web --sin-tunel        # web solo en la red local
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


def forzar_utf8() -> None:
    """UTF-8 en stdout/stderr antes de imprimir NADA (incluida la ayuda de --help),
    para que las tildes no rompan en consolas antiguas de Windows o salidas redirigidas."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def dependencias_ok(modulos: tuple[str, ...] = DEPENDENCIAS) -> bool:
    """Comprueba las librerías antes de importarlas (mensaje claro, sin traceback)."""
    faltan = [m for m in modulos if importlib.util.find_spec(m) is None]
    if faltan:
        requisitos = RAIZ_PROYECTO / "requirements.txt"
        print(f"Faltan dependencias: {', '.join(faltan)}\n"
              f"Instálalas con:\n    python -m pip install -r \"{requisitos}\"",
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
    parser.add_argument("--html", action="store_true",
                        help="genera index.html, el dashboard estático para GitHub Pages")
    parser.add_argument("--salida", metavar="RUTA",
                        help="con --html: dónde escribir el HTML (por defecto, index.html en "
                             "la carpeta del proyecto)")
    parser.add_argument("--demo", action="store_true",
                        help="inyecta en el XML 1 incidencia crítica válida y 1 anomalía para "
                             "ver cómo la web abierta detecta el cambio en ~2 s")
    parser.add_argument("--web", action="store_true",
                        help="abre la interfaz web en tiempo real (Streamlit) en lugar del "
                             "menú de terminal")
    parser.add_argument("--port", type=int, default=PUERTO_WEB, metavar="N",
                        help=f"puerto de la interfaz web (por defecto {PUERTO_WEB})")
    parser.add_argument("--tunel", default="auto",
                        choices=["auto", "cloudflared", "ngrok", "localtunnel"],
                        help="con --web: herramienta de túnel público (por defecto, la primera "
                             "disponible)")
    parser.add_argument("--sin-tunel", action="store_true",
                        help="con --web: solo red local, sin URL pública")
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
    """Arranca `streamlit run web.py` en la red local y, salvo --sin-tunel, un
    túnel público HTTPS con su código QR para abrirla desde cualquier red."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    from app.tunel import ErrorTunel, abrir_tunel, qr_ascii
    from app.ui.console import obtener_consola, panel_error
    from app.utils import limpiar_ruta

    consola = obtener_consola()
    web = RAIZ_PROYECTO / "web.py"
    if not web.is_file():
        consola.print(panel_error("Falta web.py", f"No se encuentra:\n{web}"))
        return 1

    puerto = puerto_libre(args.port)
    ip = ip_local()
    from app.auth import ErrorAuth, GestorAuth
    auth = GestorAuth()
    try:
        auth.pins()                       # Crea pins.json si falta y valida la configuración
        pins_de_fabrica = auth.usa_valores_por_defecto()
    except ErrorAuth as error:
        consola.print(panel_error("PINs no válidos", f"{error}\nCorrige pins.json o las "
                                                      "variables PIN_CONSULTA / PIN_TECNICO."))
        return 1
    comando = [sys.executable, "-m", "streamlit", "run", str(web),
               "--server.address", "0.0.0.0", "--server.port", str(puerto),
               "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    if args.file:      # Ruta absoluta: el servidor no depende del directorio actual
        comando += ["--", "--file", str(limpiar_ruta(args.file))]
    entorno = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

    try:
        servidor = subprocess.Popen(comando, env=entorno)
    except OSError as error:
        consola.print(panel_error("No se ha podido arrancar Streamlit", str(error)))
        return 1

    tunel, error_tunel = None, None
    try:
        if not args.sin_tunel:
            with consola.status("[cyan]Abriendo túnel público (acceso desde cualquier red)…[/]",
                                spinner="dots"):
                try:
                    tunel = abrir_tunel(puerto, args.tunel)
                except ErrorTunel as error:
                    error_tunel = str(error)

        texto = Text()
        texto.append("Abre en Google Chrome:\n\n", style="bold")
        texto.append("  PC (este equipo)        ", style="dim")
        texto.append(f"http://localhost:{puerto}\n", style="bold cyan underline")
        texto.append("  Móvil (misma Wi-Fi)     ", style="dim")
        texto.append(f"http://{ip}:{puerto}\n", style="bold green underline")
        if tunel:
            texto.append("  Cualquier red (4G/5G)   ", style="dim")
            texto.append(f"{tunel.url}\n", style="bold magenta underline")
            texto.append(f"                          vía {tunel.proveedor}", style="dim")
            if tunel.proveedor == "localtunnel":
                texto.append(" (la 1.ª vez pide la IP pública de este PC como contraseña)",
                             style="dim")
            texto.append("\n")
        texto.append("\n")
        if puerto != args.port:
            texto.append(f"El puerto {args.port} estaba ocupado: se usa el {puerto}.\n",
                         style="yellow")
        if ip == "127.0.0.1":
            texto.append("No se ha detectado una red local: el móvil no podrá conectar.\n",
                         style="yellow")
        texto.append(f"Acceso por PIN (Consultor / Técnico), leído de {auth.origen()}.\n",
                     style="green")
        if pins_de_fabrica:
            texto.append("⚠ Se usan los PINs de fábrica (1234 / 12345): cualquiera que los "
                         "conozca entra. Cámbialos en pins.json o con PIN_CONSULTA / "
                         "PIN_TECNICO.\n", style="bold red")
        texto.append("Ctrl+C detiene el servidor" + (" y el túnel." if tunel else "."),
                     style="dim")

        bloques: list = [texto]
        if tunel and (qr := qr_ascii(tunel.url)):
            bloques += [Text("\nEscanea con la cámara del móvil:", style="bold"),
                        Text(qr, no_wrap=True, overflow="crop")]
        elif tunel:
            bloques.append(Text("\n(Instala «qrcode» para ver aquí el código QR.)", style="dim"))
        consola.print(Panel(Group(*bloques), title="[bold]Monitor web de incidencias[/]",
                            border_style="cyan", expand=False, padding=(1, 2)))
        if error_tunel:
            consola.print(Panel(Text(error_tunel), title="[bold yellow]Sin acceso externo[/]",
                                border_style="yellow", expand=False, padding=(1, 2)))
        return servidor.wait()
    except KeyboardInterrupt:             # Ctrl+C: se cierra todo limpiamente
        return 0
    finally:
        if tunel:
            tunel.cerrar()
        if servidor.poll() is None:
            servidor.terminate()
            try:
                servidor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                servidor.kill()


def generar_html(args: argparse.Namespace) -> int:
    """`--html`: analiza el XML y escribe index.html. Solo usa la biblioteca
    estándar (no necesita rich ni questionary), así funciona tal cual en GitHub Actions."""
    from app.auth import ErrorAuth
    from app.html_builder import NOMBRE_HTML, generar_desde_xml
    from app.models import ErrorCarga
    from app.utils import limpiar_ruta

    ruta, aviso = localizar_xml(args.file)
    if ruta is None:
        print(f"ERROR: {aviso}", file=sys.stderr)
        return 1
    destino = limpiar_ruta(args.salida) if args.salida else RAIZ_PROYECTO / NOMBRE_HTML
    try:
        salida, datos = generar_desde_xml(ruta, destino)
    except ErrorCarga as error:
        print(f"ERROR ({error.titulo}): {error.mensaje}", file=sys.stderr)
        return 1
    except ErrorAuth as error:
        print(f"ERROR (PINs): {error} No se publica una página sin pantalla de PIN.",
              file=sys.stderr)
        return 1
    except OSError as error:
        print(f"ERROR: no se ha podido escribir {destino}: {error}", file=sys.stderr)
        return 1
    r = datos.resumen
    print(f"✔ {salida} generado ({salida.stat().st_size / 1_048_576:.1f} MB)\n"
          f"  Fuente: {ruta}\n"
          f"  {r.total} incidencias: {r.validas} válidas, {r.anomalas} bloqueadas\n"
          f"  Ábrelo con doble clic o publícalo en GitHub Pages (ver README).")
    return 0


def inyectar_demo(args: argparse.Namespace) -> int:
    """`--demo`: añade 1 crítica válida + 1 anomalía al XML. Solo biblioteca estándar."""
    from app.demo import ErrorDemo, inyectar_demo as inyectar

    ruta, aviso = localizar_xml(args.file)
    if ruta is None:
        print(f"ERROR: {aviso}", file=sys.stderr)
        return 1
    try:
        resultado = inyectar(ruta)
    except ErrorDemo as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"ERROR: no se ha podido escribir {ruta}: {error}", file=sys.stderr)
        return 1
    print(f"✔ Inyectadas 2 incidencias de prueba en {ruta}\n"
          f"  #{resultado.id_valida}  VÁLIDA · Crítica · caída general de la red en la "
          f"Primera planta (fecha de hoy)\n"
          f"  #{resultado.id_anomala}  ANOMALÍA · fecha imposible (1668) + texto aleatorio "
          f"tipo Faker\n"
          f"  Total en el archivo: {resultado.total} incidencias.\n"
          f"  Si la web está abierta, mostrará el aviso y los gráficos actualizados en ~2 s.\n"
          f"  Para deshacerlo (si el XML está en Git): git checkout -- \"{ruta.name}\"")
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
    forzar_utf8()
    args = crear_parser().parse_args(argv)
    if args.html:
        return generar_html(args)
    if args.demo:
        return inyectar_demo(args)
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
