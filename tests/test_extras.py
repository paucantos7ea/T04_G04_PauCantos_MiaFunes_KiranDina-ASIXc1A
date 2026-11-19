# -*- coding: utf-8 -*-
"""Tests de las piezas nuevas: rules.json, gestion.json, radar, minería y túnel."""

from __future__ import annotations

import json
import os
import stat
from datetime import date, timedelta

import pytest
from conftest import HOY, escribir_xml, inc

from app.analytics import (NIVEL_CRONICO, NIVEL_REINCIDENTE, analizar_archivo,
                           equipos_reincidentes, palabras_emergentes, radar_zonas)
from app.gestion import ErrorGestion, GestorReparaciones
from app.rules import ErrorReglas, anadir_palabra, cargar_reglas, guardar_reglas
from app.tunel import ErrorTunel, abrir_tunel, qr_ascii

# ══════════════════════════════════════════════════════════════════════════
# rules.json
# ══════════════════════════════════════════════════════════════════════════

def test_rules_se_genera_si_no_existe(tmp_path):
    ruta = tmp_path / "rules.json"
    reglas = cargar_reglas(ruta)
    assert ruta.exists() and reglas.origen == "rules.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert {"anyos", "severidad", "marcas", "lexico_tecnico"} <= set(datos)


def test_rules_corrupto_no_se_sobrescribe(tmp_path):
    ruta = tmp_path / "rules.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    reglas = cargar_reglas(ruta)
    assert reglas.origen == "fábrica" and reglas.aviso
    assert ruta.read_text(encoding="utf-8") == "{ esto no es json"


def test_rules_valida_anyos(tmp_path):
    with pytest.raises(ErrorReglas):
        guardar_reglas({"anyos": {"minimo": 2030, "maximo": 2020}}, tmp_path / "r.json")


def test_anadir_palabra_cambia_la_severidad(tmp_path):
    ruta_reglas = tmp_path / "rules.json"
    xml = escribir_xml(tmp_path / "x.xml", [inc("1", desc="El navegador es tanca sol.")])
    antes = analizar_archivo(xml, hoy=HOY, reglas=cargar_reglas(ruta_reglas)).todas[0]
    assert antes.severidad != "Alta"
    reglas = anadir_palabra("alta_hardware", "Navegador", ruta_reglas)   # Se normaliza
    assert "navegador" in reglas.datos["severidad"]["alta_hardware"]
    despues = analizar_archivo(xml, hoy=HOY, reglas=reglas).todas[0]
    assert despues.severidad == "Alta"


def test_rango_de_anyos_editable(tmp_path):
    ruta_reglas = tmp_path / "rules.json"
    reglas = guardar_reglas({"anyos": {"minimo": 2026, "maximo": None}}, ruta_reglas)
    xml = escribir_xml(tmp_path / "x.xml", [inc("1", fecha="01/09/2025")])
    assert not analizar_archivo(xml, hoy=HOY, reglas=reglas).todas[0].valida


def test_marca_completa_no_encaja_dentro_de_otra_palabra(una):
    incidencia = una(marca=None, desc="No funciona acerca del monitor")
    assert incidencia.marca is None                       # "acer" no está en "acerca"


# ══════════════════════════════════════════════════════════════════════════
# gestion.json
# ══════════════════════════════════════════════════════════════════════════

def test_gestion_por_defecto_y_actualizacion(tmp_path):
    gestor = GestorReparaciones(tmp_path / "gestion.json")
    assert gestor.estado("42").estado == "Pendiente"
    gestor.actualizar("42", "En curso", "  Cable   cambiat ")
    gestor.actualizar("42", "Resuelta", "Fet")
    estado = gestor.estado("42")
    assert estado.estado == "Resuelta" and estado.nota == "Fet"
    datos = json.loads((tmp_path / "gestion.json").read_text(encoding="utf-8"))
    assert [h["estado"] for h in datos["42"]["historial"]] == ["En curso", "Resuelta"]


def test_gestion_rechaza_estado_invalido(tmp_path):
    with pytest.raises(ErrorGestion):
        GestorReparaciones(tmp_path / "g.json").actualizar("1", "Inventado")


def test_gestion_corrupta_no_se_pierde(tmp_path):
    ruta = tmp_path / "gestion.json"
    ruta.write_text("[roto", encoding="utf-8")
    with pytest.raises(ErrorGestion):
        GestorReparaciones(ruta).actualizar("1", "Resuelta")
    assert ruta.read_text(encoding="utf-8") == "[roto"


# ══════════════════════════════════════════════════════════════════════════
# Analítica avanzada
# ══════════════════════════════════════════════════════════════════════════

def _fecha(dias_atras: int) -> str:
    return f"{date(2026, 7, 31) - timedelta(days=dias_atras):%d/%m/%Y}"


def test_equipos_reincidentes_y_cronicos(analizar):
    datos = analizar(
        *[inc(str(i), codigo="PC-A", fecha=_fecha(i * 5)) for i in range(3)],    # 3 recientes
        *[inc(f"b{i}", codigo="PC-B", fecha=_fecha(200 + i)) for i in range(3)],  # 3 antiguos
        inc("c", codigo="PC-C"),
    )
    niveles = {p.clave: p.nivel for p in equipos_reincidentes(datos.todas)}
    assert niveles == {"PC-A": NIVEL_CRONICO, "PC-B": NIVEL_REINCIDENTE}


def test_radar_de_zonas(analizar):
    zona = "En quina zona de l'empresa es troba l'equip?"
    datos = analizar(*[inc(str(i), fecha=_fecha(i * 20), **{zona: "Recepció"})
                       for i in range(10)])
    zonas = radar_zonas(datos.todas)
    assert zonas[0].clave == "Recepció" and zonas[0].total == 10


def test_palabras_emergentes(analizar, reglas):
    datos = analizar(*[inc(str(i), desc="El navegador es tanca inesperadament.")
                       for i in range(3)])
    conocidos = [reglas.patron(c) for c in reglas.datos["severidad"]]
    textos = {t.texto for t in palabras_emergentes(datos.todas, conocidos)}
    assert "navegador" in textos and "tanca inesperadament" in textos
    assert "error" not in textos                          # Ya es palabra clave


# ══════════════════════════════════════════════════════════════════════════
# Túnel público (con un cloudflared simulado) y QR
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(os.name == "nt", reason="el binario simulado es un script de shell")
def test_tunel_captura_la_url(tmp_path, monkeypatch):
    falso = tmp_path / "cloudflared"
    falso.write_text("#!/bin/sh\n"
                     "echo 'INF Requesting new quick Tunnel on trycloudflare.com...'\n"
                     "echo 'INF |  https://prueba-uno-dos.trycloudflare.com  |'\n"
                     "sleep 30\n", encoding="utf-8")
    falso.chmod(falso.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    tunel = abrir_tunel(8501, "cloudflared", espera=10)
    try:
        assert tunel.proveedor == "cloudflared"
        assert tunel.url == "https://prueba-uno-dos.trycloudflare.com"
    finally:
        tunel.cerrar()


def test_tunel_sin_herramientas_explica_que_instalar(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))             # Nada instalado
    monkeypatch.setattr("app.tunel.importlib.util.find_spec", lambda nombre: None)
    with pytest.raises(ErrorTunel, match="cloudflared"):
        abrir_tunel(8501)


def test_qr_ascii():
    qr = qr_ascii("https://prueba.trycloudflare.com")
    pytest.importorskip("qrcode")
    assert qr and "█" in qr and len(qr.splitlines()) > 10
