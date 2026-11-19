# -*- coding: utf-8 -*-
"""Inyector de pruebas en tiempo real (`python3 main.py --demo`).

Añade al final del XML vigilado dos incidencias nuevas para ver cómo la web
abierta detecta el cambio en ~2 segundos:

    1. Una incidencia VÁLIDA de severidad Crítica, con la fecha de hoy
       (caída general de la red en la Primera planta).
    2. Una ANOMALÍA evidente: fecha imposible (1668) y texto aleatorio tipo Faker.

Seguridad de la escritura:
    * Los nombres de los <camp> se copian de la última incidencia del archivo,
      así la estructura coincide EXACTAMENTE con la que espera el validador.
    * Los valores se escapan (&, <, >, comillas) antes de entrar en el XML.
    * El texto resultante se vuelve a parsear antes de guardarlo y se escribe
      de forma atómica (.tmp + replace): la web nunca lee un archivo a medias.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from app.config import CAMPOS_ESPERADOS, ETIQUETA_CAMPO, ETIQUETA_INCIDENCIA, ETIQUETA_RAIZ
from app.utils import normalizar


class ErrorDemo(Exception):
    """El XML no se puede usar para inyectar las pruebas."""


@dataclass
class ResultadoDemo:
    ruta: Path
    id_valida: str
    id_anomala: str
    total: int                       # Incidencias en el archivo tras la inyección


# Valores por «papel» del campo (se busca por fragmento del nombre, sin tildes)
def _valores(ahora: datetime, valida: bool) -> list[tuple[str, str]]:
    marca_temps = f"{ahora:%d/%m/%Y} {ahora.hour}:{ahora:%M:%S}"
    if valida:
        return [
            ("marca de temps", marca_temps),
            ("proteccio", "He llegit la informació relativa sobre la protecció de dades"),
            ("data", f"{ahora:%d/%m/%Y}"),
            ("zona", "Primera planta"),
            ("departament", "Informàtica"),
            ("quin equip", "Router/Switch"),
            ("codi", "SW-P1-DEMO"),
            ("descripcio", "Caiguda general de la xarxa a tota la planta: cap ordinador "
                           "té connexió i no hi ha internet."),
            ("marca d", "Cisco"),
            ("frequencia", "Cada dia"),
            ("persones", "Més de 10 persones"),
            ("reiniciar", "Sí"),
            ("horari", "En qualsevol moment"),
        ]
    return [
        ("marca de temps", marca_temps),
        ("proteccio", "He llegit la informació relativa sobre la protecció de dades"),
        ("data", "09/10/1668"),                                   # Fecha imposible
        ("zona", "Segona planta"),
        ("departament", "Informàtica"),
        ("quin equip", "PC"),
        ("codi", "PC-DEMO-666"),
        ("descripcio", "Empresas tipos tendrá muerto lugar sola."),  # Texto Faker
        ("marca d", "Dell"),
        ("frequencia", "De tant en tant"),
        ("persones", "Només jo"),
        ("reiniciar", "No"),
        ("horari", "A la tarda"),
    ]


def _valor_para(nombre: str, valores: list[tuple[str, str]]) -> str:
    clave = normalizar(nombre).replace("’", "'")
    return next((v for fragmento, v in valores if fragmento in clave), "")


def _bloque(id_: str, nombres: list[str], valores: list[tuple[str, str]]) -> str:
    lineas = [f"  <{ETIQUETA_INCIDENCIA} id={quoteattr(id_)}>"]
    for nombre in nombres:
        valor = _valor_para(nombre, valores)
        if valor:
            lineas.append(f"    <{ETIQUETA_CAMPO} nom={quoteattr(nombre)}>{escape(valor)}"
                          f"</{ETIQUETA_CAMPO}>")
        else:
            lineas.append(f"    <{ETIQUETA_CAMPO} nom={quoteattr(nombre)} />")
    lineas.append(f"  </{ETIQUETA_INCIDENCIA}>")
    return "\n".join(lineas) + "\n"


def inyectar_demo(ruta: Path, ahora: datetime | None = None) -> ResultadoDemo:
    """Añade las dos incidencias de prueba a `ruta`. Lanza ErrorDemo u OSError."""
    ahora = ahora or datetime.now()
    try:
        texto = ruta.read_text(encoding="utf-8")
        raiz = ET.fromstring(texto.encode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise ErrorDemo(f"{ruta.name} no es un XML UTF-8 válido: {error}") from None
    if raiz.tag != ETIQUETA_RAIZ:
        raise ErrorDemo(f"La raíz de {ruta.name} es <{raiz.tag}>, no <{ETIQUETA_RAIZ}>.")

    incidencias = raiz.findall(ETIQUETA_INCIDENCIA)
    nombres = ([c.get("nom", "") for c in incidencias[-1].findall(ETIQUETA_CAMPO)]
               if incidencias else list(CAMPOS_ESPERADOS))
    numeros = [int(i.get("id")) for i in incidencias if (i.get("id") or "").strip().isdigit()]
    siguiente = max(numeros, default=0) + 1
    id_valida, id_anomala = str(siguiente), str(siguiente + 1)

    cierre = texto.rfind(f"</{ETIQUETA_RAIZ}>")
    if cierre < 0:
        raise ErrorDemo(f"No se encuentra la etiqueta de cierre </{ETIQUETA_RAIZ}>.")
    antes = texto[:cierre]
    if not antes.endswith("\n"):
        antes += "\n"
    nuevo = (antes + _bloque(id_valida, nombres, _valores(ahora, True))
             + _bloque(id_anomala, nombres, _valores(ahora, False)) + texto[cierre:])

    try:                                     # Comprobación antes de tocar el disco
        total = len(ET.fromstring(nuevo.encode("utf-8")).findall(ETIQUETA_INCIDENCIA))
    except ET.ParseError as error:          # pragma: no cover — defensa
        raise ErrorDemo(f"El XML resultante no sería válido: {error}") from None
    if total != len(incidencias) + 2:       # pragma: no cover — defensa
        raise ErrorDemo("La inyección no ha añadido exactamente 2 incidencias.")

    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        temporal.write_text(nuevo, encoding="utf-8", newline="")
        temporal.replace(ruta)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise
    return ResultadoDemo(ruta, id_valida, id_anomala, total)
