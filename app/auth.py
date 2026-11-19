# -*- coding: utf-8 -*-
"""Autenticación por PIN con dos niveles de acceso.

    PIN de consulta -> rol «Consultor» (solo lectura)
    PIN de técnico  -> rol «Técnico»  (lectura y edición: reglas y reparaciones)

Origen de los PINs, por prioridad:
    1. Variables de entorno PIN_CONSULTA y PIN_TECNICO (servidores, Streamlit Cloud).
    2. pins.json en la raíz del proyecto (se crea con los valores por defecto si falta).

Seguridad:
    * Comparación en tiempo constante (hmac.compare_digest).
    * Freno de fuerza bruta: tras MAX_FALLOS intentos fallidos en VENTANA_FALLOS
      segundos se rechaza cualquier PIN durante BLOQUEO_S segundos (global para
      el proceso: abrir otra pestaña no lo salta). Un PIN de 4 cifras sin este
      freno se adivina en minutos si la web está expuesta con el túnel público.
    * pins.json está en .gitignore: el repositorio es público.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path

from app.config import RAIZ_PROYECTO

RUTA_PINS = RAIZ_PROYECTO / "pins.json"
ROL_CONSULTA = "Consultor"
ROL_TECNICO = "Técnico"
ROLES = (ROL_CONSULTA, ROL_TECNICO)
PINS_POR_DEFECTO = {"consulta": "1234", "tecnico": "12345"}
VARIABLES_ENTORNO = {"consulta": "PIN_CONSULTA", "tecnico": "PIN_TECNICO"}

MAX_FALLOS = 5            # Intentos fallidos permitidos...
VENTANA_FALLOS = 60       # ...en esta ventana (segundos)
BLOQUEO_S = 60            # Duración del bloqueo al superarlos

_bloqueo = threading.Lock()


class ErrorAuth(Exception):
    """Configuración de PINs inutilizable: se deniega todo el acceso."""


class AccesoBloqueado(Exception):
    """Demasiados intentos fallidos: hay que esperar `segundos`."""

    def __init__(self, segundos: int):
        super().__init__(f"Demasiados intentos fallidos. Espera {segundos} s.")
        self.segundos = segundos


class _FrenoIntentos:
    """Cuenta los fallos recientes y bloquea temporalmente (memoria del proceso)."""

    def __init__(self, maximo: int = MAX_FALLOS, ventana: float = VENTANA_FALLOS,
                 bloqueo: float = BLOQUEO_S, reloj=time.monotonic):
        self.maximo, self.ventana, self.duracion, self.reloj = maximo, ventana, bloqueo, reloj
        self.fallos: deque[float] = deque()
        self.hasta = 0.0

    def restante(self) -> int:
        """Segundos de bloqueo que quedan (0 = se puede intentar)."""
        return max(0, int(self.hasta - self.reloj() + 0.999))

    def fallo(self) -> None:
        ahora = self.reloj()
        self.fallos.append(ahora)
        while self.fallos and ahora - self.fallos[0] > self.ventana:
            self.fallos.popleft()
        if len(self.fallos) >= self.maximo:
            self.hasta = ahora + self.duracion
            self.fallos.clear()

    def exito(self) -> None:
        self.fallos.clear()


_FRENO = _FrenoIntentos()


def _pin_valido(pin: object) -> bool:
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 12


class GestorAuth:
    """Carga los PINs y traduce un PIN introducido a un rol."""

    def __init__(self, ruta: Path | None = None, entorno: Mapping[str, str] | None = None,
                 freno: _FrenoIntentos | None = None):
        self.ruta = Path(ruta or RUTA_PINS)
        self.entorno = os.environ if entorno is None else entorno
        self.freno = freno or _FRENO

    # ── Configuración ──────────────────────────────────────────────────────

    def _crear_por_defecto(self) -> None:
        try:
            with self.ruta.open("x", encoding="utf-8") as fichero:   # "x": nunca pisa uno existente
                json.dump(PINS_POR_DEFECTO, fichero, indent=2)
                fichero.write("\n")
        except FileExistsError:
            pass

    def pins(self) -> dict[str, str]:
        """{"consulta": ..., "tecnico": ...} ya validado. Lanza ErrorAuth si no sirve."""
        desde_entorno = {rol: self.entorno.get(var, "").strip()
                         for rol, var in VARIABLES_ENTORNO.items()}
        datos: dict = {}
        if not all(desde_entorno.values()):        # Falta alguno: se completa con pins.json
            with _bloqueo:
                if not self.ruta.exists():
                    try:
                        self._crear_por_defecto()
                    except OSError as error:
                        raise ErrorAuth(f"No se ha podido crear {self.ruta.name}: {error}") from None
                try:
                    with self.ruta.open(encoding="utf-8") as fichero:
                        datos = json.load(fichero)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ErrorAuth(f"{self.ruta.name} no se puede leer ({error}).") from None
            if not isinstance(datos, dict):
                raise ErrorAuth(f"{self.ruta.name} debe ser un objeto "
                                '{"consulta": "...", "tecnico": "..."}.')
        pins = {rol: desde_entorno[rol] or str(datos.get(rol, "")).strip()
                for rol in VARIABLES_ENTORNO}
        for rol, pin in pins.items():
            if not _pin_valido(pin):
                raise ErrorAuth(f"El PIN de «{rol}» debe tener entre 4 y 12 cifras.")
        if pins["consulta"] == pins["tecnico"]:
            raise ErrorAuth("Los PINs de consulta y de técnico no pueden ser iguales.")
        return pins

    def usa_valores_por_defecto(self) -> bool:
        """True si algún PIN sigue siendo el de fábrica (conviene cambiarlo)."""
        try:
            pins = self.pins()
        except ErrorAuth:
            return False
        return any(pins[r] == PINS_POR_DEFECTO[r] for r in PINS_POR_DEFECTO)

    def origen(self) -> str:
        if all(self.entorno.get(v, "").strip() for v in VARIABLES_ENTORNO.values()):
            return "variables de entorno"
        return self.ruta.name

    # ── Verificación ───────────────────────────────────────────────────────

    def verificar_pin(self, pin: str) -> str | None:
        """Rol del PIN («Consultor» o «Técnico») o None si es incorrecto.

        Lanza AccesoBloqueado si hay demasiados intentos fallidos recientes y
        ErrorAuth si la configuración de PINs es inválida (se deniega todo).
        """
        if restante := self.freno.restante():
            raise AccesoBloqueado(restante)
        pins = self.pins()
        intento = str(pin or "").strip().encode()
        # Se comparan ambos siempre: el tiempo no revela cuál ha coincidido
        es_tecnico = hmac.compare_digest(intento, pins["tecnico"].encode())
        es_consulta = hmac.compare_digest(intento, pins["consulta"].encode())
        if es_tecnico or es_consulta:
            self.freno.exito()
            return ROL_TECNICO if es_tecnico else ROL_CONSULTA
        self.freno.fallo()
        return None

    @staticmethod
    def puede_editar(rol: str | None) -> bool:
        """Solo el Técnico edita reglas y reparaciones y ve el registro de auditoría."""
        return rol == ROL_TECNICO
