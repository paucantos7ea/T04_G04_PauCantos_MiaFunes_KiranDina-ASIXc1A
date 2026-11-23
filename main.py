#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escáner y analizador interactivo de incidencias en XML — punto de entrada CLI.

Uso (desde cualquier carpeta y en cualquier sistema operativo):

    python3 main.py                          # menú interactivo de terminal
    python3 main.py --file ruta/al/archivo.xml
    python3 main.py --html                   # genera index.html estático para GitHub Pages
    python3 main.py --html --salida web.html # genera el dashboard en una ruta concreta
    python3 main.py --demo                   # inyecta 1 crítica + 1 anomalía de prueba

Búsqueda automática del XML si no se pasa --file:
    1. Directorio actual desde el que se lanza el comando (Path.cwd()).
    2. Carpeta raíz del proyecto (donde está este main.py).
    3. Si no está en ninguna, se pide la ruta de forma interactiva y no se
       continúa hasta que el archivo exista.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent

# Permite lanzar el programa desde cualquier carpeta: el paquete app/ siempre
# se importa desde la raíz del proyecto, no desde el directorio actual.
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

DEPENDENCIAS = ("rich", "questionary")


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
        description="Escáner y analizador interactivo de incidencias en XML (CLI + GitHub Pages).",
        epilog="Sin --file se busca respotes.xml o incidencies.xml en el directorio "
               "actual y en la carpeta del proyecto.")
    parser.add_argument("-f", "--file", metavar="RUTA",
                        help="ruta al archivo XML (relativa al directorio actual o absoluta)")
    parser.add_argument("--html", action="store_true",
                        help="genera index.html, el dashboard estático oficial para GitHub Pages")
    parser.add_argument("--salida", metavar="RUTA",
                        help="con --html: dónde escribir el HTML (por defecto, index.html en "
                             "la carpeta del proyecto)")
    parser.add_argument("--demo", action="store_true",
                        help="inyecta en el XML 1 incidencia crítica válida y 1 anomalía de prueba")
    return parser


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
          f"  Ejecuta `python3 main.py --html` para regenerar el dashboard con los nuevos datos.\n"
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
