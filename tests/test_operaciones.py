# -*- coding: utf-8 -*-
"""Tests de las funciones operativas: tormentas por planta/oficina, tickets
duplicados, marcas de tiempo de gestion.json, MTTR, SLA, informe ejecutivo e
inyector de pruebas (main.py --demo)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytest
from conftest import HOY, RAIZ, escribir_xml, inc

from app.analytics import (analizar_archivo, calcular_mttr, detectar_duplicados,
                           detectar_tormentas, formato_duracion, fuera_de_sla, similitud,
                           unicas_estimadas)
from app.demo import ErrorDemo, inyectar_demo
from app.exporter import informe_estado
from app.gestion import ErrorGestion, GestorReparaciones

ZONA = "En quina zona de l'empresa es troba l'equip?"
T0 = datetime(2026, 11, 19, 9, 0, 0)


# ══════════════════════════════════════════════════════════════════════════
# Tormentas de incidencias por planta / oficina
# ══════════════════════════════════════════════════════════════════════════

def test_tormenta_misma_planta_mismo_dia(analizar):
    datos = analizar(
        inc("1", fecha="10/11/2026", desc="No arrenca l'ordinador", codigo="PC-1"),
        inc("2", fecha="10/11/2026", desc="L'ordinador no s'encén", codigo="PC-2"),
        inc("3", fecha="10/11/2026", desc="No arrenca", codigo="PC-3"),
        inc("4", fecha="10/11/2026", desc="No arrenca", codigo="PC-4", **{ZONA: "Recepció"}),
        inc("5", fecha="12/11/2026", desc="No arrenca", codigo="PC-5"),
    )
    tormentas = detectar_tormentas(datos.validas)
    assert len(tormentas) == 1
    t = tormentas[0]
    assert t.zona == "Primera planta" and t.n == 3 and t.ids == ["1", "2", "3"]
    assert t.desde == t.hasta == HOY.replace(day=10)
    assert t.sintoma == "El equipo no arranca" and t.severidad == "Alta"


def test_tormenta_con_ventana_de_dias_y_minimo(analizar):
    datos = analizar(*(inc(str(i), fecha=f"{d:02d}/11/2026", desc="No arrenca", codigo=f"PC-{i}")
                       for i, d in enumerate([1, 2, 3, 10], 1)))
    assert detectar_tormentas(datos.validas) == []                       # Días distintos
    [t] = detectar_tormentas(datos.validas, ventana_dias=1)              # Encadena 1-2-3
    assert t.ids == ["1", "2", "3"] and t.hasta == HOY.replace(day=3)
    assert len(detectar_tormentas(datos.validas, minimo=4, ventana_dias=1)) == 0


def test_las_bloqueadas_no_forman_tormenta(analizar):
    datos = analizar(inc("1", fecha="10/11/2026"), inc("2", fecha="10/11/2026"),
                     inc("3", fecha="10/11/2026", desc="Cuba ciudad medios ii."))
    assert detectar_tormentas(datos.todas) == []


# ══════════════════════════════════════════════════════════════════════════
# Tickets duplicados
# ══════════════════════════════════════════════════════════════════════════

def test_duplicados_mismo_equipo_texto_parecido(analizar):
    datos = analizar(
        inc("1", fecha="10/11/2026", codigo="PC-9", desc="La impressora no imprimeix res"),
        inc("2", fecha="11/11/2026", codigo="PC-9", desc="La impressora no imprimeix res!!"),
        inc("3", fecha="11/11/2026", codigo="PC-8", desc="La impressora no imprimeix res"),
        inc("4", fecha="25/11/2025", codigo="PC-9", desc="La impressora no imprimeix res"),
        inc("5", fecha="12/11/2026", codigo="PC-9", desc="El monitor parpelleja molt"),
    )
    [grupo] = detectar_duplicados(datos.validas)
    assert grupo.ids == ["1", "2"] and grupo.original == "1" and grupo.duplicados == ["2"]
    assert grupo.equipo == "PC-9" and grupo.zona == "Primera planta"
    assert grupo.similitud >= 0.75


def test_duplicados_encadenados_y_umbral():
    assert similitud("No funciona el ratolí", "no FUNCIONA   el ratolí") == 1.0
    assert similitud("", "algo") == 0.0
    assert similitud("La impressora no imprimeix", "El servidor no respon") < 0.75


def test_duplicados_cadena_a_b_c(analizar):
    datos = analizar(*(inc(str(i), fecha=f"{10 + i}/11/2026", codigo="PC-1",
                           desc="El teclat no escriu bé" + "!" * i) for i in range(1, 4)))
    [grupo] = detectar_duplicados(datos.validas)
    assert grupo.ids == ["1", "2", "3"]
    assert unicas_estimadas(3, [], [grupo]) == 1


# ══════════════════════════════════════════════════════════════════════════
# gestion.json: marcas de tiempo, MTTR y SLA
# ══════════════════════════════════════════════════════════════════════════

def test_timestamps_de_gestion(tmp_path):
    g = GestorReparaciones(tmp_path / "gestion.json")
    g.actualizar("7", "En curso", ahora=T0)
    g.actualizar("7", "Pendiente", ahora=T0 + timedelta(minutes=10))      # No borra el inicio
    g.actualizar("7", "En curso", ahora=T0 + timedelta(minutes=20))       # Ni lo mueve
    fin = g.actualizar("7", "Resuelta", "Cable cambiado", ahora=T0 + timedelta(minutes=95))
    assert fin.fecha_inicio == "2026-11-19T09:00:00"
    assert fin.fecha_resolucion == "2026-11-19T10:35:00"
    assert fin.duracion_minutos == 95.0
    disco = json.loads((tmp_path / "gestion.json").read_text(encoding="utf-8"))["7"]
    assert disco["duracion_minutos"] == 95.0 and len(disco["historial"]) == 4

    # Cambiar solo la nota de una resuelta no toca sus tiempos
    nota = g.actualizar("7", "Resuelta", "Y limpiado", ahora=T0 + timedelta(hours=5))
    assert (nota.fecha_resolucion, nota.duracion_minutos) == (fin.fecha_resolucion, 95.0)
    # Reabrir borra la resolución
    reabierta = g.actualizar("7", "En curso", ahora=T0 + timedelta(hours=6))
    assert reabierta.fecha_resolucion is None and reabierta.duracion_minutos is None
    assert reabierta.fecha_inicio == "2026-11-19T09:00:00"


def test_resuelta_sin_pasar_por_en_curso_no_tiene_duracion(tmp_path):
    g = GestorReparaciones(tmp_path / "gestion.json")
    r = g.actualizar("1", "Resuelta", ahora=T0)
    assert r.fecha_resolucion and r.fecha_inicio is None and r.duracion_minutos is None


def test_gestion_antigua_o_editada_a_mano_no_rompe(tmp_path):
    ruta = tmp_path / "gestion.json"
    ruta.write_text(json.dumps({"1": {"estado": "Resuelta", "nota": "", "actualizado": "x",
                                      "fecha_inicio": "no es fecha", "duracion_minutos": -5},
                                "2": {"estado": "En curso"}}), encoding="utf-8")
    todos = GestorReparaciones(ruta).todos()
    assert todos["1"].fecha_inicio is None and todos["1"].duracion_minutos is None
    assert todos["2"].estado == "En curso"
    with pytest.raises(ErrorGestion):
        GestorReparaciones(ruta).actualizar("1", "Cerrada")


def test_mttr_global_y_por_severidad(analizar, tmp_path):
    datos = analizar(inc("1", desc="No arrenca l'ordinador"),             # Alta
                     inc("2", desc="No arrenca l'ordinador"),             # Alta
                     inc("3", desc="El ratolí no funciona"),              # Leve
                     inc("4", desc="El ratolí no funciona"))              # Leve, sin medir
    g = GestorReparaciones(tmp_path / "gestion.json")
    for id_, minutos in (("1", 60), ("2", 120), ("3", 30)):
        g.actualizar(id_, "En curso", ahora=T0)
        g.actualizar(id_, "Resuelta", ahora=T0 + timedelta(minutes=minutos))
    g.actualizar("4", "Resuelta", ahora=T0)
    mttr = calcular_mttr(datos.validas, g.todos())
    assert mttr.resueltas == 3 and mttr.minutos == pytest.approx(70.0)
    assert mttr.por_severidad == {"Alta": (90.0, 2), "Leve": (30.0, 1)}
    assert calcular_mttr(datos.validas, {}).minutos is None


@pytest.mark.parametrize("minutos, texto", [(None, "—"), (45, "45 min"), (60, "1 h"),
                                            (200, "3 h 20 min"), (3000, "2 d 2 h")])
def test_formato_duracion(minutos, texto):
    assert formato_duracion(minutos) == texto


def test_sla_alerta_criticas_y_altas_abiertas(analizar, tmp_path):
    marca = "Marca de temps"
    datos = analizar(
        inc("1", desc="No arrenca l'ordinador", **{marca: "19/11/2026 08:00:00"}),   # Alta, 26 h
        inc("2", desc="No arrenca l'ordinador", **{marca: "20/11/2026 09:00:00"}),   # Alta, 1 h
        inc("3", desc="El ratolí no funciona", **{marca: "01/11/2026 08:00:00"}),    # Leve: sin SLA
        inc("4", desc="No arrenca l'ordinador", **{marca: "18/11/2026 08:00:00"}),   # Alta resuelta
    )
    g = GestorReparaciones(tmp_path / "gestion.json")
    g.actualizar("4", "Resuelta", ahora=T0)
    ahora = datetime(2026, 11, 20, 10, 0)
    [alerta] = fuera_de_sla(datos.validas, g.todos(), ahora)
    assert alerta.id == "1" and alerta.severidad == "Alta" and alerta.limite_horas == 24
    assert alerta.horas_abierta == pytest.approx(26.0) and alerta.exceso_horas == pytest.approx(2.0)
    assert fuera_de_sla(datos.validas, g.todos(), ahora, limites={"Alta": 48}) == []
    assert [a.id for a in fuera_de_sla(datos.validas, {}, ahora)] == ["4", "1"]   # Sin resolver


# ══════════════════════════════════════════════════════════════════════════
# Informe ejecutivo
# ══════════════════════════════════════════════════════════════════════════

def test_informe_estado_html(analizar, tmp_path):
    datos = analizar(
        inc("1", fecha="10/11/2026", desc="No arrenca l'ordinador", codigo="PC-1"),
        inc("2", fecha="10/11/2026", desc="No arrenca l'ordinador", codigo="PC-1"),
        inc("3", fecha="10/11/2026", desc="No arrenca <b>res</b>", codigo="PC-3"),
        inc("4", fecha="09/10/1668"),
    )
    g = GestorReparaciones(tmp_path / "gestion.json")
    g.actualizar("1", "En curso", ahora=T0)
    g.actualizar("1", "Resuelta", ahora=T0 + timedelta(minutes=50))
    html = informe_estado(datos, g.todos(), ahora=datetime(2026, 11, 19, 12, 30))
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "19/11/2026" in html and "12:30" in html                     # Fecha de emisión
    assert "@media print" in html and "<script" not in html            # Imprimible y sin JS
    for texto in ("Resumen ejecutivo", "Total procesadas", "% Válidas", "% Basura bloqueada",
                  "MTTR", "50 min", "Plantas y oficinas más afectadas", "Primera planta",
                  "Desglose por severidad", "Tormentas de incidencias", "Tickets duplicados",
                  "fuera de SLA"):
        assert texto in html, texto
    assert "<b>res</b>" not in html                                     # Texto del XML escapado
    assert "75,0 %" in html                                             # 3 de 4 válidas


# ══════════════════════════════════════════════════════════════════════════
# Inyector de pruebas (main.py --demo)
# ══════════════════════════════════════════════════════════════════════════

def test_inyectar_demo(tmp_path, reglas):
    ruta = escribir_xml(tmp_path / "respotes.xml", [inc("7"), inc("12"), inc("abc")])
    antes = ruta.read_text(encoding="utf-8")
    r = inyectar_demo(ruta, ahora=datetime(2026, 11, 19, 9, 5, 0))
    assert (r.id_valida, r.id_anomala, r.total) == ("13", "14", 5)
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith(antes[:antes.rfind("</incidencies>")].rstrip())   # Nada se pierde
    assert not (tmp_path / "respotes.xml.tmp").exists()
    ET.fromstring(texto.encode("utf-8"))                               # XML bien formado
    datos = analizar_archivo(ruta, hoy=HOY, reglas=reglas)
    [valida], [anomala] = datos.por_id("13"), datos.por_id("14")
    assert valida.valida and valida.severidad == "Crítica" and valida.fecha == HOY
    assert "Primera planta" in valida.campos.values()
    assert not anomala.valida
    assert {a.tipo for a in anomala.anomalias} >= {"Fecha imposible"}


def test_inyectar_demo_rechaza_xml_roto(tmp_path):
    ruta = tmp_path / "respotes.xml"
    ruta.write_text("<incidencies><incidencia id='1'>", encoding="utf-8")
    with pytest.raises(ErrorDemo):
        inyectar_demo(ruta)
    assert ruta.read_text(encoding="utf-8") == "<incidencies><incidencia id='1'>"


def test_main_demo(tmp_path):
    xml = tmp_path / "incidencies.xml"
    shutil.copy(escribir_xml(tmp_path / "base.xml", [inc("1"), inc("2")]), xml)
    proceso = subprocess.run([sys.executable, str(RAIZ / "main.py"), "--demo", "--file", str(xml)],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             encoding="utf-8", timeout=120)
    assert proceso.returncode == 0, proceso.stderr
    assert "#3" in proceso.stdout and "#4" in proceso.stdout
    assert len(ET.parse(xml).getroot()) == 4
