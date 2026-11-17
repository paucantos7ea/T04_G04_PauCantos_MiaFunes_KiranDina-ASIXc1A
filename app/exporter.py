# -*- coding: utf-8 -*-
"""Exportación de las incidencias válidas a JSON (sin interfaz: solo E/S)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import ErrorExportacion, Incidencia


def registros_json(validas: list[Incidencia]) -> list[dict[str, str]]:
    """Cada incidencia como {"id": ..., "<camp nom>": "<valor>", ...}.

    Los campos opcionales que venían vacíos (p. ej. la marca) se guardan como
    "" para que todos los registros tengan las mismas claves.
    """
    registros = []
    for inc in validas:
        registro = {"id": inc.id, **inc.campos}
        registro.update({nombre: "" for nombre in inc.vacios})
        registros.append(registro)
    return registros


def escribir_json(ruta: Path, datos: list[Any]) -> None:
    """Escribe primero en un .tmp y después lo renombra (escritura atómica).

    Si la escritura falla a mitad, el JSON anterior queda intacto. Los OSError
    (permisos, disco lleno...) se propagan para que la interfaz los muestre.
    """
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8", newline="\n") as fichero:
            json.dump(datos, fichero, ensure_ascii=False, indent=4)
        temporal.replace(ruta)              # Atómico en Windows, Linux y macOS
    except OSError:
        temporal.unlink(missing_ok=True)    # No dejar un .tmp huérfano
        raise


def leer_json_existente(ruta: Path) -> list[Any]:
    """Lista guardada en el archivo, o ErrorExportacion si no se puede usar."""
    try:
        with ruta.open(encoding="utf-8") as fichero:
            datos = json.load(fichero)
    except json.JSONDecodeError as error:
        raise ErrorExportacion(f"El fitxer existent no és un JSON vàlid ({error}).") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorExportacion(f"No es pot llegir el fitxer existent ({error}).") from None
    if not isinstance(datos, list):
        raise ErrorExportacion("El fitxer existent no conté una llista d'incidències.")
    return datos


def fusionar(existentes: list[Any], nuevos: list[dict[str, str]]) -> tuple[list[Any], int]:
    """Añade a `existentes` los registros cuyo id aún no está. Devuelve (lista, añadidos)."""
    ids = {str(item.get("id")) for item in existentes if isinstance(item, dict)}
    anadidos = 0
    for registro in nuevos:
        if str(registro["id"]) not in ids:
            existentes.append(registro)
            ids.add(str(registro["id"]))
            anadidos += 1
    return existentes, anadidos
