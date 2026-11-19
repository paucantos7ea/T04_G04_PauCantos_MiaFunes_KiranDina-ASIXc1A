# -*- coding: utf-8 -*-
"""Seguimiento de reparaciones en gestion.json (el XML original NUNCA se toca).

Formato, indexado por id de incidencia:

    {
      "42": {"estado": "En curso", "nota": "Cambiado el cable", "actualizado": "...",
             "historial": [{"fecha": "...", "estado": "Pendiente", "nota": ""}, ...]}
    }

Las incidencias que no aparecen están "Pendiente". Varias sesiones web pueden
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
                salida[str(id_)] = EstadoReparacion(valor["estado"], str(valor.get("nota", "")),
                                                    str(valor.get("actualizado", "")))
        return salida

    def estado(self, id_: str) -> EstadoReparacion:
        return self.todos().get(str(id_), EstadoReparacion())

    # ── Escritura ──────────────────────────────────────────────────────────

    def actualizar(self, id_: str, estado: str, nota: str = "") -> EstadoReparacion:
        if estado not in ESTADOS_GESTION:
            raise ErrorGestion(f"Estado no válido: «{estado}». Usa: {', '.join(ESTADOS_GESTION)}.")
        nota = " ".join(str(nota).split())[:MAX_NOTA]
        ahora = datetime.now().isoformat(timespec="seconds")
        with _bloqueo:
            datos = self._leer()
            registro = datos.get(str(id_)) if isinstance(datos.get(str(id_)), dict) else {}
            historial = list(registro.get("historial", []))[-(MAX_HISTORIAL - 1):]
            historial.append({"fecha": ahora, "estado": estado, "nota": nota})
            datos[str(id_)] = {"estado": estado, "nota": nota, "actualizado": ahora,
                               "historial": historial}
            self._escribir(datos)
        return EstadoReparacion(estado, nota, ahora)

    def _escribir(self, datos: dict) -> None:
        temporal = self.ruta.with_name(self.ruta.name + ".tmp")
        try:
            with temporal.open("w", encoding="utf-8", newline="\n") as fichero:
                json.dump(datos, fichero, ensure_ascii=False, indent=2, sort_keys=True)
            temporal.replace(self.ruta)
        except OSError as error:
            temporal.unlink(missing_ok=True)
            raise ErrorGestion(f"No se ha podido guardar {self.ruta.name}: {error}") from None
