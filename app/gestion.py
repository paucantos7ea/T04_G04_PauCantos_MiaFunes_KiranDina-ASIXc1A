# -*- coding: utf-8 -*-
"""Seguimiento de reparaciones en gestion.json (el XML original NUNCA se toca).

Formato, indexado por id de incidencia:

    {
      "42": {"estado": "Resuelta", "nota": "Cambiado el cable",
             "actualizado": "2026-11-19T10:40:00",
             "fecha_inicio": "2026-11-19T09:00:00",       # 1.ª vez que pasa a «En curso»
             "fecha_resolucion": "2026-11-19T10:40:00",   # Al pasar a «Resuelta»
             "duracion_minutos": 100.0,                   # resolución - inicio
             "historial": [{"fecha": "...", "estado": "En curso", "nota": ""}, ...]}
    }

Las incidencias que no aparecen están "Pendiente". Reglas de las marcas de tiempo:

    * fecha_inicio se fija la PRIMERA vez que la incidencia pasa a «En curso»
      y ya no cambia (aunque vuelva a «Pendiente» o se reabra).
    * Al pasar a «Resuelta» se fija fecha_resolucion y, si hay fecha_inicio,
      duracion_minutos. Si se resuelve sin haber pasado por «En curso», no hay
      duración medible y no cuenta para el MTTR.
    * Editar solo la nota de una incidencia ya resuelta no toca sus tiempos.
    * Reabrirla («Resuelta» -> otro estado) borra la resolución y la duración. Varias sesiones web pueden
escribir a la vez: cada cambio es leer-modificar-escribir bajo un cerrojo y la
escritura es atómica (.tmp + replace), así el archivo nunca queda a medias.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import (ESTADO_GESTION_DEFECTO, ESTADOS_GESTION, NOMBRE_GESTION,
                        RAIZ_PROYECTO)

RUTA_GESTION = RAIZ_PROYECTO / NOMBRE_GESTION
MAX_HISTORIAL = 20
MAX_NOTA = 500

_bloqueo = threading.Lock()


class ErrorGestion(Exception):
    """gestion.json no se puede leer o escribir."""


@dataclass
class EstadoReparacion:
    estado: str = ESTADO_GESTION_DEFECTO
    nota: str = ""
    actualizado: str = ""
    fecha_inicio: str | None = None
    fecha_resolucion: str | None = None
    duracion_minutos: float | None = None


def _iso(valor: object) -> str | None:
    """Timestamp ISO válido o None (un gestion.json editado a mano no rompe nada)."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        datetime.fromisoformat(valor)
    except ValueError:
        return None
    return valor


def _minutos(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor < 0:
        return None
    return float(valor)


class GestorReparaciones:
    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta or RUTA_GESTION)

    # ── Lectura ────────────────────────────────────────────────────────────

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {}
        try:
            with self.ruta.open(encoding="utf-8") as fichero:
                datos = json.load(fichero)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorGestion(f"{self.ruta.name} no se puede leer ({error}). No se ha "
                               "modificado: revísalo o renómbralo para empezar de cero.") from None
        if not isinstance(datos, dict):
            raise ErrorGestion(f"{self.ruta.name} no contiene un objeto {{id: estado}}.")
        return datos

    def todos(self) -> dict[str, EstadoReparacion]:
        """{id: EstadoReparacion} de las incidencias con algún seguimiento."""
        with _bloqueo:
            datos = self._leer()
        salida = {}
        for id_, valor in datos.items():
            if isinstance(valor, dict) and valor.get("estado") in ESTADOS_GESTION:
                salida[str(id_)] = EstadoReparacion(
                    valor["estado"], str(valor.get("nota", "")), str(valor.get("actualizado", "")),
                    _iso(valor.get("fecha_inicio")), _iso(valor.get("fecha_resolucion")),
                    _minutos(valor.get("duracion_minutos")))
        return salida

    def estado(self, id_: str) -> EstadoReparacion:
        return self.todos().get(str(id_), EstadoReparacion())

    # ── Escritura ──────────────────────────────────────────────────────────

    def actualizar(self, id_: str, estado: str, nota: str = "",
                   ahora: datetime | None = None) -> EstadoReparacion:
        if estado not in ESTADOS_GESTION:
            raise ErrorGestion(f"Estado no válido: «{estado}». Usa: {', '.join(ESTADOS_GESTION)}.")
        nota = " ".join(str(nota).split())[:MAX_NOTA]
        momento = (ahora or datetime.now()).replace(microsecond=0)
        marca = momento.isoformat(timespec="seconds")
        with _bloqueo:
            datos = self._leer()
            registro = datos.get(str(id_)) if isinstance(datos.get(str(id_)), dict) else {}
            anterior = registro.get("estado", ESTADO_GESTION_DEFECTO)
            inicio = _iso(registro.get("fecha_inicio"))
            resolucion = _iso(registro.get("fecha_resolucion"))
            duracion = _minutos(registro.get("duracion_minutos"))
            if estado == "En curso" and inicio is None:
                inicio = marca                              # Primera vez «En curso»
            if estado == "Resuelta":
                if anterior != "Resuelta" or resolucion is None:
                    resolucion = marca
                    duracion = None
                    if inicio is not None:
                        segundos = (momento - datetime.fromisoformat(inicio)).total_seconds()
                        duracion = round(max(0.0, segundos) / 60, 1)
            else:                                           # Abierta o reabierta
                resolucion = duracion = None
            historial = list(registro.get("historial", []))[-(MAX_HISTORIAL - 1):]
            historial.append({"fecha": marca, "estado": estado, "nota": nota})
            datos[str(id_)] = {"estado": estado, "nota": nota, "actualizado": marca,
                               "fecha_inicio": inicio, "fecha_resolucion": resolucion,
                               "duracion_minutos": duracion, "historial": historial}
            self._escribir(datos)
        return EstadoReparacion(estado, nota, marca, inicio, resolucion, duracion)

    def _escribir(self, datos: dict) -> None:
        temporal = self.ruta.with_name(self.ruta.name + ".tmp")
        try:
            with temporal.open("w", encoding="utf-8", newline="\n") as fichero:
                json.dump(datos, fichero, ensure_ascii=False, indent=2, sort_keys=True)
            temporal.replace(self.ruta)
        except OSError as error:
            temporal.unlink(missing_ok=True)
            raise ErrorGestion(f"No se ha podido guardar {self.ruta.name}: {error}") from None
