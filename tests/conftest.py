# -*- coding: utf-8 -*-
"""Utilidades compartidas por los tests.

Ningún test toca los archivos reales del proyecto: las reglas son las de
fábrica en memoria y los XML/JSON se crean en carpetas temporales (tmp_path).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.analytics import Analizador, analizar_archivo  # noqa: E402
from app.rules import Reglas  # noqa: E402

HOY = date(2026, 11, 19)

# Incidencia correcta de referencia (mismos 13 campos que el formulario real)
BASE: dict[str, str | None] = {
    "Marca de temps": "03/11/2026 11:56:39",
    "Informació relativa sobre la protecció de dades": "He llegit la informació relativa "
                                                       "sobre la protecció de dades",
    "Data d'incidència": "01/09/2026",
    "En quina zona de l'empresa es troba l'equip?": "Primera planta",
    "Quin departament ha detectat la incidència": "Informàtica",
    "Quin equip presenta l'incidència?": "PC",
    "Quin codi d'identificació té l'equip?": "PC-ADM-001",
    "Descripció del problema": "No funciona",
    "Marca d'equip": "Dell",
    "Amb quina freqüència passa el problema?": "Cada dia",
    "Quantes persones estan afectades pel problema?": "Només jo",
    "S'ha provat de reiniciar l'equip? (Si el problema es amb l'ordinador)": "Sí",
    "En quin horari es pot revisar o reparar l'equip?": "En qualsevol moment",
}
DESC = "Descripció del problema"
EQUIPO = "Quin equip presenta l'incidència?"
FECHA = "Data d'incidència"
MARCA = "Marca d'equip"
CODIGO = "Quin codi d'identificació té l'equip?"
AFECTADOS = "Quantes persones estan afectades pel problema?"


def inc(id_: str = "1", **cambios: str | None) -> dict[str, str | None]:
    """Campos de una incidencia: BASE + cambios (claves con _ en vez de nombre largo)."""
    alias = {"desc": DESC, "equipo": EQUIPO, "fecha": FECHA, "marca": MARCA,
             "codigo": CODIGO, "afectados": AFECTADOS}
    campos = dict(BASE)
    for clave, valor in cambios.items():
        campos[alias.get(clave, clave)] = valor
    campos["__id__"] = id_
    return campos


def escribir_xml(ruta: Path, incidencias: list[dict[str, str | None]]) -> Path:
    raiz = ET.Element("incidencies")
    for campos in incidencias:
        nodo = ET.SubElement(raiz, "incidencia", id=str(campos["__id__"]))
        for nombre, valor in campos.items():
            if nombre == "__id__":
                continue
            camp = ET.SubElement(nodo, "camp", nom=nombre)
            if valor is not None:                 # None -> <camp nom="..."/> (autocierre)
                camp.text = valor
    ET.ElementTree(raiz).write(ruta, encoding="utf-8", xml_declaration=True)
    return ruta


@pytest.fixture
def reglas() -> Reglas:
    return Reglas.por_defecto()


@pytest.fixture
def analizar(tmp_path, reglas):
    """analizar(inc(...), inc(...)) -> Analizador sobre un XML temporal."""
    def _analizar(*incidencias: dict[str, str | None]) -> Analizador:
        ruta = escribir_xml(tmp_path / "respotes.xml", list(incidencias))
        return analizar_archivo(ruta, hoy=HOY, reglas=reglas)
    return _analizar


@pytest.fixture
def una(analizar):
    """una(desc=..., ...) -> la Incidencia ya procesada."""
    def _una(**cambios: str | None):
        return analizar(inc("1", **cambios)).todas[0]
    return _una
