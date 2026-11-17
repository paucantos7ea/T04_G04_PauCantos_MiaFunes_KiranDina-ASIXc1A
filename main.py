#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escáner y analizador interactivo de incidencias en XML — punto de entrada CLI.

Uso (desde cualquier carpeta y en cualquier sistema operativo):

    python main.py                          # busca respotes.xml / incidencies.xml
    python main.py --file ruta/al/archivo.xml
    python ruta/al/proyecto/main.py -f datos.xml

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


def dependencias_ok() -> bool:
    """Comprueba las librerías antes de importarlas (mensaje claro, sin traceback)."""
    faltan = [m for m in DEPENDENCIAS if importlib.util.find_spec(m) is None]
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
    return parser


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
    if not dependencias_ok():
        return 1

    from app.models import ErrorCarga
    from app.ui.console import obtener_consola, panel_aviso, panel_despedida, panel_error

    consola = obtener_consola()           # Fuerza UTF-8 antes de imprimir nada
    args = crear_parser().parse_args(argv)

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
