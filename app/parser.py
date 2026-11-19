# -*- coding: utf-8 -*-
"""Carga y parseo seguro del XML con ElementTree.

Usa ET.iterparse: procesa cada <incidencia> en cuanto se cierra y la libera
con elem.clear(), así la memoria no crece con archivos grandes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from app.config import (CAMPOS_ESPERADOS, ETIQUETA_CAMPO, ETIQUETA_INCIDENCIA,
                        ETIQUETA_RAIZ, MAX_ERRORES_ESTRUCTURA)
from app.models import ErrorCarga, Incidencia
from app.utils import normalizar


def _texto_seguro(elemento: ET.Element | None) -> str:
    """Texto de un elemento, o "" si es None o una etiqueta de autocierre.

    itertext() junta también el texto de posibles subetiquetas y nunca lanza
    AttributeError (a diferencia de `.text.strip()` sobre un nodo vacío).
    """
    if elemento is None:
        return ""
    return "".join(elemento.itertext()).strip()


def _clave_campo(nombre: str) -> str:
    """Nombre comparable: sin tildes/mayúsculas/espacios y apóstrofo recto."""
    return normalizar(nombre.replace("’", "'"))


_ESPERADOS = {_clave_campo(c): c for c in CAMPOS_ESPERADOS}


class XMLParser:
    """Convierte el archivo en una lista de Incidencia o lanza ErrorCarga."""

    def cargar(self, ruta: Path) -> tuple[str, list[Incidencia]]:
        """Devuelve (etiqueta_raíz, incidencias).

        Además de exigir un XML bien formado, valida la ESTRUCTURA:
            <incidencies>                       <- raíz exacta
                <incidencia id="...">           <- solo esto bajo la raíz
                    <camp nom="...">texto</camp>  <- solo esto, sin subetiquetas,
                    ...                              los CAMPOS_ESPERADOS, 1 vez cada uno
        Si algo no encaja se rechaza el archivo completo.
        """
        ruta = Path(ruta)
        if not ruta.exists():
            raise ErrorCarga("Archivo no encontrado", f"No existe el archivo:\n{ruta}")
        if not ruta.is_file():
            raise ErrorCarga("Ruta no válida", f"La ruta no es un archivo:\n{ruta}")
        if ruta.suffix.lower() != ".xml":
            raise ErrorCarga("Extensión no válida", f"El archivo debe ser .xml:\n{ruta}")

        raiz = ""
        profundidad = 0
        incidencias: list[Incidencia] = []
        errores: list[str] = []
        try:
            # Se abre en binario: ElementTree respeta la codificación declarada
            # en el propio XML, igual en Windows que en Linux/macOS.
            with ruta.open("rb") as fichero:
                for evento, elem in ET.iterparse(fichero, events=("start", "end")):
                    if evento == "start":
                        profundidad += 1
                        if profundidad == 1:
                            raiz = elem.tag
                            if raiz != ETIQUETA_RAIZ:
                                raise ErrorCarga(
                                    "Estructura incorrecta",
                                    f"La raíz es <{raiz}>, debe ser <{ETIQUETA_RAIZ}>.")
                        elif profundidad == 2 and elem.tag != ETIQUETA_INCIDENCIA:
                            errores.append(f"<{elem.tag}> dentro de <{raiz}>: "
                                           f"solo se admite <{ETIQUETA_INCIDENCIA}>.")
                        continue

                    # evento == "end"
                    profundidad -= 1
                    if profundidad == 1 and elem.tag == ETIQUETA_INCIDENCIA:
                        posicion = len(incidencias) + 1
                        errores.extend(self._errores_estructura(elem, posicion))
                        incidencias.append(self._convertir(elem, posicion))
                        elem.clear()                     # Libera memoria
                    if len(errores) > MAX_ERRORES_ESTRUCTURA:
                        break                            # Ya es seguro que se rechaza
        except FileNotFoundError:
            raise ErrorCarga("Archivo no encontrado", f"No existe el archivo:\n{ruta}") from None
        except PermissionError:
            raise ErrorCarga("Sin permisos", f"No tienes permiso para leer:\n{ruta}") from None
        except ET.ParseError as error:
            raise ErrorCarga("XML malformado",
                             f"El documento no es un XML bien formado.\n{error}") from None
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise ErrorCarga("Error de lectura", f"No se puede leer el archivo.\n{error}") from None

        if errores:
            lista = "\n".join(f"• {e}" for e in errores[:MAX_ERRORES_ESTRUCTURA])
            if len(errores) > MAX_ERRORES_ESTRUCTURA:
                lista += "\n• ..."
            raise ErrorCarga("Estructura incorrecta",
                             f"El XML no tiene la estructura esperada:\n{lista}")
        if not incidencias:
            raise ErrorCarga("Sin datos", f"El XML no contiene ninguna <{ETIQUETA_INCIDENCIA}>.")
        return raiz, incidencias

    @staticmethod
    def _errores_estructura(nodo: ET.Element, posicion: int) -> list[str]:
        """Lista de fallos de estructura de una <incidencia> (vacía si está bien)."""
        errores: list[str] = []
        id_xml = (nodo.get("id") or "").strip()
        donde = f'<incidencia id="{id_xml}">' if id_xml else f"<incidencia> nº {posicion}"

        if not id_xml:
            errores.append(f"{donde}: falta el atributo id.")
        if (nodo.text or "").strip():
            errores.append(f"{donde}: tiene texto suelto fuera de <{ETIQUETA_CAMPO}>.")

        vistos: Counter[str] = Counter()
        for hijo in nodo:
            if (hijo.tail or "").strip():
                errores.append(f"{donde}: tiene texto suelto fuera de <{ETIQUETA_CAMPO}>.")
            if hijo.tag != ETIQUETA_CAMPO:
                errores.append(f"{donde}: etiqueta <{hijo.tag}> no permitida.")
                continue
            nombre = (hijo.get("nom") or "").strip()
            if not nombre:
                errores.append(f"{donde}: <{ETIQUETA_CAMPO}> sin atributo nom.")
                continue
            if len(hijo):
                errores.append(f'{donde}: <{ETIQUETA_CAMPO} nom="{nombre}"> contiene subetiquetas.')
            clave = _clave_campo(nombre)
            if clave not in _ESPERADOS:
                errores.append(f"{donde}: campo desconocido «{nombre}».")
            vistos[clave] += 1

        for clave, original in _ESPERADOS.items():
            if vistos[clave] == 0:
                errores.append(f"{donde}: falta el campo «{original}».")
            elif vistos[clave] > 1:
                errores.append(f"{donde}: el campo «{original}» está repetido.")
        return errores

    @staticmethod
    def _convertir(nodo: ET.Element, posicion: int) -> Incidencia:
        id_xml = (nodo.get("id") or "").strip()          # .get() con fallback
        inc = Incidencia(id=id_xml or f"SIN-ID-{posicion}", sin_id=not id_xml)

        for camp in nodo.findall(ETIQUETA_CAMPO):        # Solo hijos directos
            nombre = (camp.get("nom") or "").strip() or "(sin nombre)"
            valor = _texto_seguro(camp)

            # Campo repetido en la misma incidencia: se numera, no se pisa
            clave, n = nombre, 2
            while clave in inc.campos or clave in inc.vacios:
                clave, n = f"{nombre} ({n})", n + 1

            inc.orden.append(clave)
            if valor:
                inc.campos[clave] = valor
            else:
                inc.vacios.append(clave)     # <camp nom="X"/> o <camp nom="X"></camp>
        return inc
