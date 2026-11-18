# -*- coding: utf-8 -*-
"""Utilidades puras (sin estado ni E/S) compartidas por varios módulos."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

from app.config import MAX_TRUNCAR, RE_BYTE, RE_FECHA_EU, RE_FECHA_ISO, VALORES_NULOS


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, '&' -> 'and' y espacios simples."""
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    sin_tildes = sin_tildes.lower().replace("&", " and ")
    return " ".join(sin_tildes.split())


def truncar(texto: str | None, limite: int = MAX_TRUNCAR) -> str:
    """Una sola línea y como máximo `limite` caracteres + [...]."""
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[:limite] + "[...]"


def limpiar_ruta(entrada: str | None) -> Path:
    """Convierte lo que escribe/arrastra el usuario en un Path absoluto.

    Quita comillas (arrastrar un archivo en Windows/macOS las añade), el
    prefijo '& ' que pone PowerShell, expande '~' y resuelve rutas relativas
    respecto al directorio actual. Funciona igual con '/' que con '\\'.
    """
    entrada = (entrada or "").strip()
    if entrada.startswith("& "):
        entrada = entrada[2:].strip()
    entrada = entrada.strip("'\"")
    if not entrada:
        return Path()
    try:
        return Path(entrada).expanduser().resolve()
    except (OSError, RuntimeError):     # Ruta imposible de resolver: se usa tal cual
        return Path(entrada).expanduser()


def valor_real(valor: str | None) -> str:
    """Valor limpio del campo, o "" si es vacío, "-", "N/A", "Sense marca"..."""
    limpio = " ".join((valor or "").split())
    return "" if normalizar(limpio) in VALORES_NULOS else limpio


def canonico_con_pista(texto_normalizado: str,
                       tabla: list[tuple[str, re.Pattern[str]]]) -> tuple[str, str] | None:
    """(nombre, fragmento que lo ha disparado) del primer patrón de `tabla` que encaja."""
    for nombre, patron in tabla:
        if coincidencia := patron.search(texto_normalizado):
            return nombre, coincidencia.group(0)
    return None


def canonico(texto_normalizado: str, tabla: list[tuple[str, re.Pattern[str]]]) -> str | None:
    """Primer nombre de `tabla` cuyo patrón aparece en el texto."""
    encontrado = canonico_con_pista(texto_normalizado, tabla)
    return encontrado[0] if encontrado else None


def parsear_fecha_usuario(texto: str) -> date | None:
    """Acepta AAAA-MM-DD o DD/MM/AAAA. Devuelve None si no es una fecha real."""
    texto = texto.strip()
    if coincidencia := RE_FECHA_ISO.match(texto):
        anyo, mes, dia = coincidencia.groups()
    elif coincidencia := RE_FECHA_EU.match(texto):
        dia, mes, anyo = coincidencia.groups()
    else:
        return None
    try:
        return date(int(anyo), int(mes), int(dia))
    except ValueError:            # 31/02/2025, mes 13, año 0000...
        return None


def decodificar_binario(valor: str) -> str:
    """Intenta leer los bytes binarios como texto (para la ficha de rechazo)."""
    try:
        datos = bytes(int(b, 2) for b in RE_BYTE.findall(valor))
    except ValueError:
        return ""
    texto = datos.decode("utf-8", errors="replace")
    return "".join(c if c.isprintable() else "·" for c in texto)
