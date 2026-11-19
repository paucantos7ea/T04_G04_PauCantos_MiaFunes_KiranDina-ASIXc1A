# -*- coding: utf-8 -*-
"""Reglas editables del motor: carga, validación, compilación y guardado de rules.json.

rules.json vive en la raíz del proyecto. Si no existe se genera con los
valores de fábrica de config.REGLAS_POR_DEFECTO. Si existe pero está dañado
NO se sobrescribe: se usan los valores de fábrica en memoria y se avisa.

Las palabras clave son texto normal (sin regex). Al compilarlas:
  * se normalizan (minúsculas, sin tildes),
  * los espacios, guiones y apóstrofos se vuelven flexibles
    ("s'encen" encaja con "s’encén", "s encen" y "sencen"),
  * se buscan al INICIO de palabra ("lent" -> lento, lenta...),
  * las MARCAS se buscan como palabra completa ("acer" no encaja en "acerca").
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.config import NOMBRE_REGLAS, RAIZ_PROYECTO, REGLAS_POR_DEFECTO
from app.utils import normalizar

RUTA_REGLAS = RAIZ_PROYECTO / NOMBRE_REGLAS
NUNCA = re.compile(r"(?!x)x")              # Patrón que no encaja con nada

_bloqueo = threading.Lock()
_cache: dict[tuple, "Reglas"] = {}


class ErrorReglas(Exception):
    """rules.json no tiene un formato utilizable."""


# ══════════════════════════════════════════════════════════════════════════
# Compilación
# ══════════════════════════════════════════════════════════════════════════

def normalizar_clave(palabra: str) -> str:
    """Forma canónica de una palabra clave (la que se guarda y se compara)."""
    return normalizar(str(palabra).replace("’", "'")).strip()


def _fragmento(palabra: str) -> str:
    """Regex de una palabra clave con espacios, guiones y apóstrofos flexibles."""
    partes = []
    for c in palabra:
        if c == " ":
            partes.append(r"\s+")
        elif c in "'-":
            partes.append(r"['’\s-]?")
        else:
            partes.append(re.escape(c))
    return "".join(partes)


def compilar(palabras: list[str], completa: bool = False) -> re.Pattern[str]:
    """Una sola regex con todas las palabras (las más largas primero)."""
    limpias = sorted({p for p in map(normalizar_clave, palabras) if p}, key=len, reverse=True)
    if not limpias:
        return NUNCA
    final = r"(?![a-z0-9])" if completa else ""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(_fragmento, limpias)) + ")" + final)


# ══════════════════════════════════════════════════════════════════════════
# Validación del contenido de rules.json
# ══════════════════════════════════════════════════════════════════════════

def _lista(valor: Any, donde: str) -> list[str]:
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise ErrorReglas(f"«{donde}» debe ser una lista de textos.")
    vistas, salida = set(), []
    for v in valor:                         # Sin duplicados, respetando el orden
        clave = normalizar_clave(v)
        if clave and clave not in vistas:
            vistas.add(clave)
            salida.append(clave)
    return salida


def validar_datos(datos: Any) -> dict:
    """Devuelve una copia limpia y completa (rellena lo que falte con los valores de fábrica)."""
    if not isinstance(datos, dict):
        raise ErrorReglas("El archivo debe contener un objeto JSON.")
    base = copy.deepcopy(REGLAS_POR_DEFECTO)

    anyos = datos.get("anyos", base["anyos"])
    if not isinstance(anyos, dict):
        raise ErrorReglas("«anyos» debe ser un objeto {minimo, maximo}.")
    minimo, maximo = anyos.get("minimo", 2000), anyos.get("maximo")
    if isinstance(minimo, bool) or not isinstance(minimo, int) or not 1 <= minimo <= 9999:
        raise ErrorReglas("«anyos.minimo» debe ser un año entre 1 y 9999.")
    if maximo in (0, None):
        maximo = None
    elif isinstance(maximo, bool) or not isinstance(maximo, int) or not 1 <= maximo <= 9999:
        raise ErrorReglas("«anyos.maximo» debe ser un año, 0 o null (= año actual).")
    elif maximo < minimo:
        raise ErrorReglas("«anyos.maximo» no puede ser menor que «anyos.minimo».")
    base["anyos"] = {"minimo": minimo, "maximo": maximo}

    severidad = datos.get("severidad", {})
    if not isinstance(severidad, dict):
        raise ErrorReglas("«severidad» debe ser un objeto de listas.")
    for clave in base["severidad"]:
        if clave in severidad:
            base["severidad"][clave] = _lista(severidad[clave], f"severidad.{clave}")

    lexico = datos.get("lexico_tecnico", {})
    if not isinstance(lexico, dict):
        raise ErrorReglas("«lexico_tecnico» debe ser un objeto de listas.")
    for clave in base["lexico_tecnico"]:
        if clave in lexico:
            base["lexico_tecnico"][clave] = _lista(lexico[clave], f"lexico_tecnico.{clave}")

    if "marcas" in datos:
        marcas = datos["marcas"]
        if not isinstance(marcas, dict):
            raise ErrorReglas("«marcas» debe ser un objeto {Marca: [alias, ...]}.")
        limpias: dict[str, list[str]] = {}
        for nombre, alias in marcas.items():
            nombre = " ".join(str(nombre).split())
            if not nombre:
                continue
            lista = _lista(alias, f"marcas.{nombre}")
            if normalizar_clave(nombre) not in lista:   # El propio nombre siempre cuenta
                lista.insert(0, normalizar_clave(nombre))
            limpias[nombre] = lista
        base["marcas"] = limpias
    return base


# ══════════════════════════════════════════════════════════════════════════
# Reglas compiladas
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Reglas:
    """rules.json ya validado y compilado. Inmutable en la práctica: no se toca."""
    datos: dict
    origen: str = "fábrica"                 # "rules.json" | "fábrica"
    aviso: str = ""                         # Problema al leer rules.json (si lo hubo)
    huella: str = ""                        # Hash del contenido (claves de caché)
    patrones: dict[str, re.Pattern[str]] = field(default_factory=dict)
    marcas: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)

    @classmethod
    def desde_datos(cls, datos: dict, origen: str = "fábrica", aviso: str = "") -> "Reglas":
        limpio = validar_datos(datos)
        texto = json.dumps(limpio, ensure_ascii=False, sort_keys=True)
        patrones = {clave: compilar(lista) for clave, lista in limpio["severidad"].items()}
        patrones.update({clave: compilar(lista)
                         for clave, lista in limpio["lexico_tecnico"].items()})
        marcas = [(nombre, compilar(alias, completa=True))
                  for nombre, alias in limpio["marcas"].items()]
        return cls(limpio, origen, aviso, hashlib.sha1(texto.encode()).hexdigest()[:12],
                   patrones, marcas)

    @classmethod
    def por_defecto(cls) -> "Reglas":
        return cls.desde_datos(copy.deepcopy(REGLAS_POR_DEFECTO))

    # ── Accesos cómodos ────────────────────────────────────────────────────

    @property
    def anyo_minimo(self) -> int:
        return self.datos["anyos"]["minimo"]

    def anyo_maximo(self, hoy: date | None = None) -> int:
        """Año máximo permitido (el actual si rules.json dice null/0)."""
        return self.datos["anyos"]["maximo"] or (hoy or date.today()).year

    def patron(self, clave: str) -> re.Pattern[str]:
        return self.patrones.get(clave, NUNCA)

    def nombres_marcas(self) -> list[str]:
        return [nombre for nombre, _ in self.marcas]

    def todas_las_claves(self) -> set[str]:
        """Todas las palabras clave conocidas (para la minería de palabras nuevas)."""
        claves = {p for lista in self.datos["severidad"].values() for p in lista}
        claves |= {p for lista in self.datos["lexico_tecnico"].values() for p in lista}
        return claves


# ══════════════════════════════════════════════════════════════════════════
# Lectura / escritura
# ══════════════════════════════════════════════════════════════════════════

def _escribir(ruta: Path, datos: dict) -> None:
    """Escritura atómica: .tmp + replace (el archivo nunca queda a medias)."""
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8", newline="\n") as fichero:
            json.dump(datos, fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")
        temporal.replace(ruta)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise


def cargar_reglas(ruta: Path | None = None) -> Reglas:
    """Reglas vigentes. Crea rules.json con los valores de fábrica si no existe.

    Se cachea por (ruta, fecha de modificación, tamaño): llamarla en cada
    ciclo de la web no recompila nada si el archivo no ha cambiado.
    """
    ruta = Path(ruta or RUTA_REGLAS)
    with _bloqueo:
        if not ruta.exists():
            try:
                _escribir(ruta, validar_datos(REGLAS_POR_DEFECTO))
            except OSError as error:          # Carpeta de solo lectura: se sigue en memoria
                return Reglas.desde_datos(copy.deepcopy(REGLAS_POR_DEFECTO), "fábrica",
                                          f"No se ha podido crear {ruta.name}: {error}")
        try:
            estado = ruta.stat()
            clave = (str(ruta), estado.st_mtime_ns, estado.st_size)
            if clave in _cache:
                return _cache[clave]
            with ruta.open(encoding="utf-8") as fichero:
                reglas = Reglas.desde_datos(json.load(fichero), NOMBRE_REGLAS)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ErrorReglas) as error:
            return Reglas.desde_datos(copy.deepcopy(REGLAS_POR_DEFECTO), "fábrica",
                                      f"{ruta.name} no es válido ({error}); se usan los "
                                      "valores de fábrica. Corrígelo o restáuralo desde la web.")
        _cache.clear()                        # Solo interesa la última versión
        _cache[clave] = reglas
        return reglas


def guardar_reglas(datos: dict, ruta: Path | None = None) -> Reglas:
    """Valida, guarda y devuelve las nuevas reglas. Lanza ErrorReglas u OSError."""
    ruta = Path(ruta or RUTA_REGLAS)
    limpio = validar_datos(datos)
    Reglas.desde_datos(limpio)                # Comprueba que compila antes de escribir
    with _bloqueo:
        _escribir(ruta, limpio)
        _cache.clear()
    return cargar_reglas(ruta)


def restaurar_reglas(ruta: Path | None = None) -> Reglas:
    """Vuelve a los valores de fábrica."""
    return guardar_reglas(copy.deepcopy(REGLAS_POR_DEFECTO), ruta)


def anadir_palabra(lista: str, palabra: str, ruta: Path | None = None) -> Reglas:
    """Añade una palabra a una lista de severidad o de léxico técnico y guarda."""
    actuales = cargar_reglas(ruta)
    datos = copy.deepcopy(actuales.datos)
    for grupo in ("severidad", "lexico_tecnico"):
        if lista in datos[grupo]:
            datos[grupo][lista].append(palabra)
            return guardar_reglas(datos, ruta)
    raise ErrorReglas(f"La lista «{lista}» no existe.")
