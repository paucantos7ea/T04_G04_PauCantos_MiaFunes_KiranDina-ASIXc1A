# -*- coding: utf-8 -*-
"""Tests del motor: validación, texto aleatorio, severidad, auto-reparación y XML limpio."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET

import pytest
from conftest import CODIGO, DESC, FECHA, HOY, MARCA, escribir_xml, inc

from app.analytics import analizar_archivo
from app.config import CAT_BASURA, CAT_DESBORDE, CAT_FECHA, CAT_SIN_SENTIDO, CAT_VACIO
from app.exporter import cuarentena_csv, xml_limpio
from app.parser import XMLParser

# ══════════════════════════════════════════════════════════════════════════
# Incidencias reales válidas (incluidas las muy cortas)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("descripcion", [
    "No funciona",
    "No funciona.",
    "No me funciona.",
    "No em funciona",
    "No m'arrenca.",
    "No respon",
    "No responde",
    "No encèn.",
    "Teclat trencat",
    "Va molt lent",
    "No arrenca l'ordinador",
    "La impressora no reu els arxius en format pdf.",
    "L'ordinador no s'encén en prémer el botó i no es veu cap senyal d'engegada.",
    "El navegador es tanca inesperadament mentre es consulten pàgines.",
    "El paper queda encallat dins de la impressora i la impressió s'atura.",
    "I connected two monitors and the second one shows No Signal.",
])
def test_incidencias_reales_validas(una, descripcion):
    incidencia = una(desc=descripcion)
    assert incidencia.valida, [a.motivo_detallado for a in incidencia.anomalias]


# ══════════════════════════════════════════════════════════════════════════
# Texto aleatorio tipo Faker / ensalada de palabras
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("descripcion", [
    "Habían vuelve ellas teoría edad orden. México m república.",
    "Cuba ciudad medios ii.",
    "Peso conocer presenta.",
    "Gracias oro e.",
    "Posición él cama precisamente aunque programas presente peso. Llegó decía último nadie.",
    "Meses voy consumo frente muerte perdido debido menos.",
])
def test_faker_bloqueado(una, descripcion):
    incidencia = una(desc=descripcion)
    assert not incidencia.valida
    assert incidencia.categorias() == {CAT_SIN_SENTIDO}
    anomalia = incidencia.anomalias[0]
    assert anomalia.campo == DESC
    assert "Faker" in anomalia.motivo_detallado


def test_faker_cita_senales(una):
    anomalia = una(desc="Cuba ciudad medios ii.").anomalias[0]
    assert "cuba" in anomalia.motivo_detallado
    assert "ii" in anomalia.motivo_detallado


def test_prosa_sin_relacion_tecnica_bloqueada(una):
    texto = ("Los manatíes, conocidos popularmente como vacas marinas, son mamíferos "
             "acuáticos fascinantes que habitan en aguas costeras poco profundas, ríos y "
             "estuarios, y se desplazan con gran lentitud mientras se alimentan de plantas.")
    incidencia = una(desc=texto)
    assert CAT_SIN_SENTIDO in incidencia.categorias()


def test_descripcion_sin_palabras_bloqueada(una):
    assert CAT_SIN_SENTIDO in una(desc="69").categorias()


def test_solo_se_evalua_la_descripcion(una):
    # Otros campos con texto "plano" (p. ej. la frecuencia) no se consideran Faker
    incidencia = una(**{"Amb quina freqüència passa el problema?": "Cada dia."})
    assert incidencia.valida


# ══════════════════════════════════════════════════════════════════════════
# Severidad: Crítica solo con contexto de caída
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("descripcion", [
    "No funciona",
    "Va molt lent",
    "El router de l'aula no emet la llum verda.",
])
def test_router_con_fallo_menor_no_es_critica(una, descripcion):
    incidencia = una(equipo="Router/Switch", desc=descripcion)
    assert incidencia.valida
    assert incidencia.severidad != "Crítica"
    assert any("no se marca Crítica" in p.texto for p in incidencia.traza)


def test_router_fallo_menor_con_muchos_afectados_es_alta(una):
    incidencia = una(equipo="Router/Switch", desc="No funciona",
                     afectados="Tota l’organització")
    assert incidencia.severidad == "Alta"
    assert incidencia.criterio_severidad.startswith("Paso 3")


@pytest.mark.parametrize("equipo,descripcion", [
    ("Router/Switch", "Els dispositius connectats perden la connexió i no hi ha internet."),
    ("Router/Switch", "El switch fa fum i s'ha apagat."),
    ("PC", "El servidor de fitxers no respon."),
    ("PC", "La xarxa està caiguda a tota la planta."),
    ("PC", "Tall general: sense internet a tota l'empresa."),
])
def test_critica_con_contexto_de_caida(una, equipo, descripcion):
    incidencia = una(equipo=equipo, desc=descripcion)
    assert incidencia.valida
    assert incidencia.severidad == "Crítica", incidencia.regla_severidad


def test_pc_sin_internet_individual_no_es_critica(una):
    assert una(desc="El meu ordinador no té connexió, sense internet.").severidad != "Crítica"


def test_pc_cremat_es_alta_no_critica(una):
    incidencia = una(desc="L'ordinador fa olor de cremat.")
    assert incidencia.severidad == "Alta"


@pytest.mark.parametrize("descripcion,nivel", [
    ("Teclat trencat", "Leve"),
    ("No arrenca l'ordinador", "Alta"),
    ("L'aplicació de gestió no s'obre i mostra un missatge d'error.", "Media"),
    ("No arrenca la impressora", "Leve"),        # Periférico antes que "no arranca"
])
def test_resto_de_niveles(una, descripcion, nivel):
    assert una(desc=descripcion).severidad == nivel


# ══════════════════════════════════════════════════════════════════════════
# Auto-reparación
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("entrada", ["2026-05-09", "09.05.2026", "09-05-2026", "9/5/2026"])
def test_reparacion_de_fechas(una, entrada):
    incidencia = una(fecha=entrada)
    assert incidencia.valida
    assert incidencia.campos[FECHA] == "09/05/2026"
    assert incidencia.auto_reparada
    assert any(r.campo == FECHA and r.antes == entrada for r in incidencia.reparaciones)


def test_fecha_con_anyo_incoherente_no_se_repara(una):
    incidencia = una(fecha="1668-05-09")
    assert incidencia.campos[FECHA] == "1668-05-09"
    assert CAT_FECHA in incidencia.categorias()


def test_reparacion_de_espacios(una):
    incidencia = una(desc="No   funciona\t\tel\nteclat")
    assert incidencia.campos[DESC] == "No funciona el teclat"
    assert incidencia.valida and incidencia.auto_reparada


@pytest.mark.parametrize("entrada,esperada", [("hp", "HP"), ("lenovo", "Lenovo"),
                                              ("ASUS", "Asus"), ("Tp-link", "TP-Link")])
def test_reparacion_de_marcas(una, entrada, esperada):
    incidencia = una(marca=entrada)
    assert incidencia.campos[MARCA] == esperada
    assert incidencia.marca == esperada
    assert any(r.motivo.startswith("Mayúsculas") for r in incidencia.reparaciones)


def test_incidencia_correcta_no_se_marca_reparada(una):
    assert not una().auto_reparada


# ══════════════════════════════════════════════════════════════════════════
# Rechazos clásicos
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fecha", ["09/10/1668", "09/10/2040", "31/02/2026"])
def test_fechas_imposibles(una, fecha):
    assert CAT_FECHA in una(fecha=fecha).categorias()


def test_etiqueta_vacia_bloquea(una):
    incidencia = una(equipo=None)
    assert CAT_VACIO in incidencia.categorias()


def test_marca_vacia_no_bloquea(una):
    incidencia = una(marca=None)
    assert incidencia.valida


def test_desbordamiento_en_campo_breve(una):
    assert CAT_DESBORDE in una(codigo="X" * 300).categorias()


def test_binario_bloqueado(una):
    binario = "01001000 01101111 01101100 01100001"
    incidencia = una(desc=binario)
    assert CAT_BASURA in incidencia.categorias()
    assert "Hola" in incidencia.anomalias[0].extra


def test_amarico_bloqueado(una):
    assert CAT_BASURA in una(desc="No funciona ሰላም ኮምፒውተር").categorias()


# ══════════════════════════════════════════════════════════════════════════
# Exportación: respotes_limpio.xml y cuarentena.csv
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mezcla(analizar):
    return analizar(
        inc("1"),
        inc("2", fecha="2026-05-09", marca="hp"),                 # Válida tras reparar
        inc("3", desc="Cuba ciudad medios ii."),                  # Faker
        inc("4", fecha="09/10/1668"),                             # Fecha imposible
        inc("5", equipo=None),                                    # Autocierre
        inc("6", marca=None, desc="Teclat trencat"),              # Válida sin marca
    )


def test_xml_limpio_bien_formado_y_parseable(mezcla, tmp_path, reglas):
    contenido = xml_limpio(mezcla.validas)
    raiz = ET.fromstring(contenido)                      # Bien formado
    assert raiz.tag == "incidencies"
    assert [n.get("id") for n in raiz] == ["1", "2", "6"]

    ruta = tmp_path / "respotes_limpio.xml"
    ruta.write_bytes(contenido)
    _, incidencias = XMLParser().cargar(ruta)            # Pasa la validación de estructura
    assert len(incidencias) == 3
    reanalizado = analizar_archivo(ruta, hoy=HOY, reglas=reglas)
    assert reanalizado.resumen.validas == 3 and reanalizado.resumen.anomalas == 0


def test_xml_limpio_lleva_valores_reparados_y_vacios(mezcla):
    raiz = ET.fromstring(xml_limpio(mezcla.validas))
    dos = raiz.find("incidencia[@id='2']")
    valores = {c.get("nom"): c.text for c in dos}
    assert valores[FECHA] == "09/05/2026" and valores[MARCA] == "HP"
    seis = raiz.find("incidencia[@id='6']")
    marca = [c for c in seis if c.get("nom") == MARCA][0]
    assert marca.text is None                             # Opcional vacío: autocierre
    assert len(list(seis)) == 13                          # Estructura completa


def test_xml_limpio_nunca_incluye_bloqueadas(mezcla):
    raiz = ET.fromstring(xml_limpio(mezcla.todas))       # Aunque se le pasen todas
    assert {n.get("id") for n in raiz} == {"1", "2", "6"}


def test_cuarentena_csv(mezcla):
    texto = cuarentena_csv(mezcla.anomalas).decode("utf-8-sig")
    filas = list(csv.DictReader(io.StringIO(texto)))
    assert {f["id"] for f in filas} == {"3", "4", "5"}
    faker = [f for f in filas if f["id"] == "3"][0]
    assert faker["tipo_anomalia"] == "Texto aleatorio / Sin sentido"
    assert faker["campo_afectado"] == DESC and faker["motivo"]


def test_parser_conserva_orden_de_campos(tmp_path):
    ruta = escribir_xml(tmp_path / "a.xml", [inc("1")])
    _, incidencias = XMLParser().cargar(ruta)
    assert incidencias[0].orden[0] == "Marca de temps"
    assert incidencias[0].orden[6] == CODIGO
