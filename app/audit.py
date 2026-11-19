# -*- coding: utf-8 -*-
"""Registro persistente de auditoría en audit.log (UTF-8, solo se añade al final).

Una línea por evento:

    [YYYY-MM-DD HH:MM:SS] [ROL] [ACCIÓN] Detalle del cambio

Los saltos de línea del detalle se sustituyen por « ⏎ »: así nadie puede
inyectar líneas falsas escribiendo, por ejemplo, una nota con un salto de línea.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import RAIZ_PROYECTO

RUTA_AUDITORIA = RAIZ_PROYECTO / "audit.log"

ACCESO = "ACCESO"
ACCESO_FALLIDO = "ACCESO_FALLIDO"
CIERRE_SESION = "CIERRE_SESION"
REPARACION = "REPARACION"
REGLAS = "REGLAS"
EXPORTACION = "EXPORTACION"
ACCIONES = (ACCESO, ACCESO_FALLIDO, CIERRE_SESION, REPARACION, REGLAS, EXPORTACION)
ROL_ANONIMO = "Anónimo"

RE_LINEA = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]*)\] \[([^\]]*)\] (.*)$")
_bloqueo = threading.Lock()


@dataclass(frozen=True)
class Evento:
    fecha: str
    rol: str
    accion: str
    detalle: str


def _limpio(texto: object) -> str:
    """Una sola línea, sin corchetes que confundan el formato en rol/acción."""
    return " ⏎ ".join(str(texto).splitlines()).strip()


def formatear(rol: str, accion: str, detalle: str, ahora: datetime | None = None) -> str:
    fecha = (ahora or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    rol = _limpio(rol).replace("[", "(").replace("]", ")") or ROL_ANONIMO
    accion = _limpio(accion).replace("[", "(").replace("]", ")")
    return f"[{fecha}] [{rol}] [{accion}] {_limpio(detalle)}"


def registrar(rol: str, accion: str, detalle: str, ruta: Path | None = None,
              ahora: datetime | None = None) -> str:
    """Añade el evento a audit.log y devuelve la línea escrita.

    Si el disco falla, el error se propaga: perder auditoría en silencio no es
    aceptable, la interfaz decide cómo avisar.
    """
    linea = formatear(rol, accion, detalle, ahora)
    with _bloqueo, Path(ruta or RUTA_AUDITORIA).open("a", encoding="utf-8", newline="\n") as f:
        f.write(linea + "\n")
    return linea


def leer(ruta: Path | None = None, accion: str | None = None,
         limite: int | None = None) -> list[Evento]:
    """Eventos del más reciente al más antiguo (opcionalmente de una acción)."""
    ruta = Path(ruta or RUTA_AUDITORIA)
    if not ruta.exists():
        return []
    eventos = []
    with ruta.open(encoding="utf-8", errors="replace") as fichero:
        for linea in fichero:
            if m := RE_LINEA.match(linea.rstrip("\n")):
                evento = Evento(*m.groups())
                if accion is None or evento.accion == accion:
                    eventos.append(evento)
    eventos.reverse()
    return eventos[:limite] if limite else eventos


# ══════════════════════════════════════════════════════════════════════════
# Descripción legible de un cambio en rules.json
# ══════════════════════════════════════════════════════════════════════════

def _lista(antes: list[str], despues: list[str], nombre: str) -> list[str]:
    cambios = []
    if anadidas := [p for p in despues if p not in antes]:
        cambios.append(f"{nombre}: +{', +'.join(anadidas)}")
    if quitadas := [p for p in antes if p not in despues]:
        cambios.append(f"{nombre}: -{', -'.join(quitadas)}")
    return cambios


def cambios_reglas(antes: dict, despues: dict) -> list[str]:
    """Lista de cambios entre dos versiones de rules.json (vacía si son iguales)."""
    cambios: list[str] = []
    for campo, nombre in (("minimo", "año mínimo"), ("maximo", "año máximo")):
        a, d = antes["anyos"][campo], despues["anyos"][campo]
        if a != d:
            cambios.append(f"{nombre}: {a or 'año actual'} → {d or 'año actual'}")
    for grupo in ("severidad", "lexico_tecnico"):
        for clave in sorted(set(antes[grupo]) | set(despues[grupo])):
            cambios += _lista(antes[grupo].get(clave, []), despues[grupo].get(clave, []), clave)
    marcas_a, marcas_d = antes["marcas"], despues["marcas"]
    for marca in sorted(set(marcas_d) - set(marcas_a)):
        cambios.append(f"marca añadida: {marca}")
    for marca in sorted(set(marcas_a) - set(marcas_d)):
        cambios.append(f"marca eliminada: {marca}")
    for marca in sorted(set(marcas_a) & set(marcas_d)):
        cambios += _lista(marcas_a[marca], marcas_d[marca], f"alias de {marca}")
    return cambios
