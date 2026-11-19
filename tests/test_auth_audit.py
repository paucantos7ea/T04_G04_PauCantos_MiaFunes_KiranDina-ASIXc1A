# -*- coding: utf-8 -*-
"""Tests de autenticación por PIN (app/auth.py) y del registro de auditoría (app/audit.py)."""

from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from app import audit
from app.auth import (PINS_POR_DEFECTO, ROL_CONSULTA, ROL_TECNICO, AccesoBloqueado, ErrorAuth,
                      GestorAuth, _FrenoIntentos)
from app.config import REGLAS_POR_DEFECTO


class Reloj:
    """Reloj manual para probar el bloqueo sin esperar de verdad."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def gestor(tmp_path):
    """GestorAuth aislado: pins.json temporal, sin variables de entorno y freno propio."""
    return GestorAuth(tmp_path / "pins.json", entorno={}, freno=_FrenoIntentos())


# ══════════════════════════════════════════════════════════════════════════
# pins.json
# ══════════════════════════════════════════════════════════════════════════

def test_crea_pins_json_si_falta(gestor):
    assert not gestor.ruta.exists()
    assert gestor.pins() == PINS_POR_DEFECTO
    assert json.loads(gestor.ruta.read_text(encoding="utf-8")) == {"consulta": "1234",
                                                                   "tecnico": "12345"}


def test_carga_pins_json_existente(tmp_path):
    ruta = tmp_path / "pins.json"
    ruta.write_text('{"consulta": "4321", "tecnico": "987654"}', encoding="utf-8")
    gestor = GestorAuth(ruta, entorno={}, freno=_FrenoIntentos())
    assert gestor.verificar_pin("4321") == ROL_CONSULTA
    assert gestor.verificar_pin("987654") == ROL_TECNICO
    assert gestor.verificar_pin("1234") is None            # Los de fábrica ya no sirven
    assert not gestor.usa_valores_por_defecto()


def test_variables_de_entorno_tienen_prioridad(tmp_path):
    ruta = tmp_path / "pins.json"
    ruta.write_text(json.dumps(PINS_POR_DEFECTO), encoding="utf-8")
    gestor = GestorAuth(ruta, entorno={"PIN_CONSULTA": "5555", "PIN_TECNICO": "777777"},
                        freno=_FrenoIntentos())
    assert gestor.verificar_pin("5555") == ROL_CONSULTA
    assert gestor.verificar_pin("777777") == ROL_TECNICO
    assert gestor.verificar_pin("1234") is None
    assert gestor.origen() == "variables de entorno"


def test_variable_de_entorno_parcial_se_completa_con_el_archivo(tmp_path):
    gestor = GestorAuth(tmp_path / "pins.json", entorno={"PIN_TECNICO": "999999"},
                        freno=_FrenoIntentos())
    assert gestor.verificar_pin("1234") == ROL_CONSULTA     # Del archivo
    assert gestor.verificar_pin("999999") == ROL_TECNICO    # Del entorno


@pytest.mark.parametrize("contenido", ['{"consulta": "12", "tecnico": "12345"}',
                                       '{"consulta": "abcd", "tecnico": "12345"}',
                                       '{"consulta": "1234", "tecnico": "1234"}',
                                       "[1, 2]", "{roto"])
def test_configuracion_invalida_deniega_todo(tmp_path, contenido):
    ruta = tmp_path / "pins.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ErrorAuth):
        GestorAuth(ruta, entorno={}, freno=_FrenoIntentos()).verificar_pin("1234")
    assert ruta.read_text(encoding="utf-8") == contenido    # No se sobrescribe


# ══════════════════════════════════════════════════════════════════════════
# Verificación de PIN y permisos
# ══════════════════════════════════════════════════════════════════════════

def test_pin_consulta_sin_edicion(gestor):
    rol = gestor.verificar_pin("1234")
    assert rol == ROL_CONSULTA
    assert not gestor.puede_editar(rol)


def test_pin_tecnico_con_edicion(gestor):
    rol = gestor.verificar_pin("12345")
    assert rol == ROL_TECNICO
    assert gestor.puede_editar(rol)


@pytest.mark.parametrize("pin", ["", "0000", "123", "123456", "12345 6", "abcd", "1234a"])
def test_pin_incorrecto_rechazado(gestor, pin):
    assert gestor.verificar_pin(pin) is None


def test_espacios_alrededor_del_pin_se_ignoran(gestor):
    assert gestor.verificar_pin("  12345 ") == ROL_TECNICO


def test_sin_rol_no_puede_editar():
    assert not GestorAuth.puede_editar(None)
    assert not GestorAuth.puede_editar("Administrador")


def test_bloqueo_por_fuerza_bruta(tmp_path):
    reloj = Reloj()
    freno = _FrenoIntentos(maximo=5, ventana=60, bloqueo=60, reloj=reloj)
    gestor = GestorAuth(tmp_path / "pins.json", entorno={}, freno=freno)
    for _ in range(5):
        assert gestor.verificar_pin("0000") is None
    with pytest.raises(AccesoBloqueado) as error:
        gestor.verificar_pin("12345")                       # Ni el PIN bueno durante el bloqueo
    assert error.value.segundos == 60
    reloj.t += 61
    assert gestor.verificar_pin("12345") == ROL_TECNICO     # Pasado el bloqueo, vuelve a ir


def test_fallos_antiguos_no_cuentan(tmp_path):
    reloj = Reloj()
    gestor = GestorAuth(tmp_path / "pins.json", entorno={},
                        freno=_FrenoIntentos(maximo=5, ventana=60, bloqueo=60, reloj=reloj))
    for _ in range(4):
        gestor.verificar_pin("0000")
    reloj.t += 120                                          # Fuera de la ventana
    gestor.verificar_pin("0000")
    assert gestor.verificar_pin("1234") == ROL_CONSULTA


# ══════════════════════════════════════════════════════════════════════════
# audit.log
# ══════════════════════════════════════════════════════════════════════════

def test_formato_de_linea():
    linea = audit.formatear("Técnico", audit.REPARACION, "ID 42: Pendiente → Resuelta",
                            datetime(2026, 11, 19, 10, 5, 7))
    assert linea == "[2026-11-19 10:05:07] [Técnico] [REPARACION] ID 42: Pendiente → Resuelta"


def test_escritura_y_lectura(tmp_path):
    ruta = tmp_path / "audit.log"
    audit.registrar("Consultor", audit.ACCESO, "Inicio de sesión en Modo Consultor", ruta,
                    datetime(2026, 11, 19, 9, 0, 0))
    audit.registrar("Anónimo", audit.ACCESO_FALLIDO, "PIN incorrecto (4 cifras)", ruta,
                    datetime(2026, 11, 19, 9, 1, 0))
    audit.registrar("Técnico", audit.EXPORTACION, "Descarga de cuarentena.csv (3 registros)",
                    ruta, datetime(2026, 11, 19, 9, 2, 0))
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 3 and lineas[0].startswith("[2026-11-19 09:00:00] [Consultor] [ACCESO]")
    eventos = audit.leer(ruta)
    assert [e.accion for e in eventos] == [audit.EXPORTACION, audit.ACCESO_FALLIDO, audit.ACCESO]
    assert eventos[0].rol == "Técnico" and "cuarentena.csv" in eventos[0].detalle
    assert [e.accion for e in audit.leer(ruta, accion=audit.ACCESO)] == [audit.ACCESO]


def test_append_no_borra_lo_anterior(tmp_path):
    ruta = tmp_path / "audit.log"
    for i in range(3):
        audit.registrar("Técnico", audit.REGLAS, f"cambio {i}", ruta)
    assert len(audit.leer(ruta)) == 3


def test_no_se_pueden_inyectar_lineas_falsas(tmp_path):
    ruta = tmp_path / "audit.log"
    audit.registrar("Técnico", audit.REPARACION,
                    "nota «ok»\n[2020-01-01 00:00:00] [Técnico] [ACCESO] falso", ruta)
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 1
    assert len(audit.leer(ruta)) == 1


def test_leer_sin_archivo(tmp_path):
    assert audit.leer(tmp_path / "no_existe.log") == []


def test_cambios_de_reglas():
    antes = copy.deepcopy(REGLAS_POR_DEFECTO)
    despues = copy.deepcopy(REGLAS_POR_DEFECTO)
    despues["anyos"]["minimo"] = 2010
    despues["severidad"]["media_generico"].append("navegador")
    despues["severidad"]["leve_perifericos"].remove("webcam")
    despues["marcas"]["Nueva"] = ["nueva"]
    del despues["marcas"]["Xiaomi"]
    cambios = audit.cambios_reglas(antes, despues)
    assert "año mínimo: 2000 → 2010" in cambios
    assert "media_generico: +navegador" in cambios
    assert "leve_perifericos: -webcam" in cambios
    assert "marca añadida: Nueva" in cambios and "marca eliminada: Xiaomi" in cambios
    assert audit.cambios_reglas(antes, copy.deepcopy(antes)) == []
