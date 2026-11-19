# -*- coding: utf-8 -*-
"""Tests de extremo a extremo de la web Streamlit (web.py) con AppTest.

Comprueban el bloqueo obligatorio por PIN al abrir, los permisos de cada rol,
la escritura en audit.log y que todas las pestañas se pintan sin excepciones.
Todo se redirige a carpetas temporales: pins.json, audit.log, gestion.json y el XML.
"""

from __future__ import annotations

import sys

import pytest
from conftest import RAIZ, escribir_xml, inc

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app import audit, auth, gestion  # noqa: E402
from app.auth import ROL_CONSULTA, ROL_TECNICO  # noqa: E402

TIEMPO = 90


@pytest.fixture
def web(tmp_path, monkeypatch):
    """Fábrica de AppTest aislada (sin tocar ningún archivo real del proyecto)."""
    xml = escribir_xml(tmp_path / "respotes.xml", [
        inc("1", fecha="10/11/2026", desc="No arrenca l'ordinador"),
        inc("2", fecha="10/11/2026", desc="No arrenca l'ordinador"),
        inc("3", fecha="10/11/2026", desc="L'ordinador no arrenca"),
        inc("4", fecha="09/10/1668"),
    ])
    monkeypatch.setattr(auth, "RUTA_PINS", tmp_path / "pins.json")
    monkeypatch.setattr(auth, "_FRENO", auth._FrenoIntentos())
    monkeypatch.setattr(audit, "RUTA_AUDITORIA", tmp_path / "audit.log")
    monkeypatch.setattr(gestion, "RUTA_GESTION", tmp_path / "gestion.json")
    monkeypatch.delenv("PIN_CONSULTA", raising=False)
    monkeypatch.delenv("PIN_TECNICO", raising=False)
    monkeypatch.setattr(sys, "argv", ["web.py", "--file", str(xml)])

    def crear() -> AppTest:
        at = AppTest.from_file(str(RAIZ / "web.py"), default_timeout=TIEMPO)
        return at.run()
    return crear


def _entrar(at: AppTest, pin: str) -> AppTest:
    at.text_input[0].input(pin)
    return at.button[0].click().run()


def _sin_excepciones(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def test_al_abrir_solo_se_ve_el_pin(web):
    at = web()
    _sin_excepciones(at)
    assert len(at.text_input) == 1                         # Solo el campo del PIN
    assert len(at.tabs) == 0                               # Ni pestañas, ni datos, ni gráficos
    assert "rol" not in at.session_state
    assert "iniciado" not in at.session_state              # El XML ni siquiera se ha leído


def test_pin_incorrecto_se_audita(web, tmp_path):
    at = _entrar(web(), "0000")
    _sin_excepciones(at)
    assert any("PIN incorrecto" in e.value for e in at.error)
    assert len(at.tabs) == 0
    eventos = audit.leer(tmp_path / "audit.log")
    assert eventos[0].accion == audit.ACCESO_FALLIDO and eventos[0].rol == audit.ROL_ANONIMO


def test_consultor_solo_lectura(web, tmp_path):
    at = _entrar(web(), "1234")
    _sin_excepciones(at)
    assert at.session_state["rol"] == ROL_CONSULTA
    etiquetas = [t.label for t in at.tabs]
    assert "⚡ Incidencias Masivas y Duplicadas" in etiquetas
    assert "📜 Auditoría de Cambios" not in etiquetas
    assert any("Modo Consultor" in m.value for m in at.markdown)
    eventos = audit.leer(tmp_path / "audit.log")
    assert (eventos[0].rol, eventos[0].accion) == (ROL_CONSULTA, audit.ACCESO)


def test_tecnico_ve_auditoria_y_todo_se_pinta(web, tmp_path):
    at = _entrar(web(), "12345")
    _sin_excepciones(at)
    assert at.session_state["rol"] == ROL_TECNICO
    assert "📜 Auditoría de Cambios" in [t.label for t in at.tabs]
    # La tormenta (3 incidencias el mismo día en la Primera planta) aparece en su pestaña
    assert any("Primera planta" in x.label for x in at.expander)


def test_tema_oscuro_y_cierre_de_sesion(web, tmp_path):
    at = _entrar(web(), "12345")
    tema = next(w for w in at.get("button_group") if w.key == "tema")
    assert tema.value == "☀️ Claro"                        # Claro por defecto
    tema.set_value("🌙 Oscuro")
    at = at.run()
    _sin_excepciones(at)
    assert any("--o-fondo" in m.value for m in at.markdown)
    salir = next(b for b in at.button if "Cerrar sesión" in b.label)
    at = salir.click().run()
    assert "rol" not in at.session_state and len(at.tabs) == 0
    acciones = [e.accion for e in audit.leer(tmp_path / "audit.log")]
    assert acciones[:2] == [audit.CIERRE_SESION, audit.ACCESO]
