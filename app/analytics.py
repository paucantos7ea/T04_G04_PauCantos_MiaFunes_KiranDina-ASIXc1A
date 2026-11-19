# -*- coding: utf-8 -*-
"""Cálculo de métricas, rankings por equipo/tipo/marca y consultas de filtrado."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from app.config import (CATEGORIA_POR_DEFECTO, MIN_FALLOS_CRONICO, MIN_FALLOS_REINCIDENTE,
                        MIN_FALLOS_VENTANA, TENDENCIA_CALIENTE, TENDENCIA_VIGILAR,
                        MINERIA_IGNORAR, RE_CAMPO_CODIGO, RE_CAMPO_ZONA, STOPWORDS,
                        VENTANA_RECIENTE_DIAS)
from app.models import EstadisticasResumen, Incidencia
from app.parser import XMLParser
from app.rules import Reglas
from app.utils import normalizar
from app.validator import procesar


def calcular_resumen(incidencias: list[Incidencia]) -> EstadisticasResumen:
    """Agrega todas las métricas en una sola pasada lógica."""
    validas = [i for i in incidencias if i.valida]
    anomalas = [i for i in incidencias if not i.valida]
    return EstadisticasResumen(
        total=len(incidencias),
        validas=len(validas),
        anomalas=len(anomalas),
        por_tipo=Counter(i.tipo for i in validas),
        por_equipo=Counter(i.equipo for i in validas if i.equipo),
        por_severidad=Counter(i.severidad for i in validas),
        por_marca=Counter(i.marca for i in validas if i.marca),
        por_categoria=Counter(c for i in anomalas for c in i.categorias()),
        por_mes=Counter((i.fecha.year, i.fecha.month) for i in validas if i.fecha),
    )


class Analizador:
    """Resultado de analizar un XML: listas, métricas cacheadas y consultas."""

    def __init__(self, ruta: Path, incidencias: list[Incidencia]):
        self.ruta = ruta
        self.todas = incidencias
        self.validas = [i for i in incidencias if i.valida]
        self.anomalas = [i for i in incidencias if not i.valida]
        self.resumen = calcular_resumen(incidencias)
        self._indice_id: dict[str, list[Incidencia]] = {}
        for inc in incidencias:          # Puede haber IDs repetidos en el XML
            self._indice_id.setdefault(inc.id.strip().lower(), []).append(inc)

    # ── Búsquedas ──────────────────────────────────────────────────────────

    def por_id(self, texto: str, solo_anomalas: bool = False) -> list[Incidencia]:
        encontradas = self._indice_id.get(texto.strip().lower(), [])
        return [i for i in encontradas if not i.valida] if solo_anomalas else encontradas

    def buscar_texto(self, termino: str) -> list[tuple[Incidencia, str, str]]:
        """Una fila por incidencia: (incidencia, campo, valor) de la 1ª coincidencia."""
        buscado = normalizar(termino)
        resultados = []
        for inc in self.todas:
            for campo, valor in inc.campos.items():
                if buscado in normalizar(valor):
                    resultados.append((inc, campo, valor))
                    break
        return resultados

    # ── Filtros ────────────────────────────────────────────────────────────

    def anomalas_de(self, categoria: str | None) -> list[Incidencia]:
        return [i for i in self.anomalas if categoria is None or categoria in i.categorias()]

    def validas_de_severidad(self, nivel: str) -> list[Incidencia]:
        return [i for i in self.validas if i.severidad == nivel]

    def validas_de_marca(self, marca: str) -> list[Incidencia]:
        return [i for i in self.validas if i.marca == marca]

    def validas_sin_marca(self) -> list[Incidencia]:
        return [i for i in self.validas if not i.marca]

    def validas_con_fecha(self) -> list[Incidencia]:
        return [i for i in self.validas if i.fecha]

    @staticmethod
    def de_categoria(incidencias: list[Incidencia], categoria: str) -> list[Incidencia]:
        return [i for i in incidencias if i.tipo == categoria]

    @staticmethod
    def en_rango(incidencias: list[Incidencia], desde: date, hasta: date) -> list[Incidencia]:
        """Incidencias con fecha en [desde, hasta], en orden cronológico."""
        return sorted((i for i in incidencias if i.fecha and desde <= i.fecha <= hasta),
                      key=lambda i: i.fecha)

    @staticmethod
    def en_periodo(incidencias: list[Incidencia], anyo: int,
                   mes: int | None = None) -> list[Incidencia]:
        """Incidencias de un año (y opcionalmente un mes), en orden cronológico."""
        return sorted((i for i in incidencias if i.fecha and i.fecha.year == anyo
                       and (mes is None or i.fecha.month == mes)),
                      key=lambda i: i.fecha)

    # ── Rankings y agregaciones ────────────────────────────────────────────

    @staticmethod
    def contar_por_categoria(incidencias: list[Incidencia]) -> list[tuple[str, int]]:
        return Counter(i.tipo for i in incidencias).most_common()

    @staticmethod
    def anyos_disponibles(incidencias: list[Incidencia]) -> list[tuple[int, int]]:
        """[(año, nº), ...] del más reciente al más antiguo."""
        return sorted(Counter(i.fecha.year for i in incidencias if i.fecha).items(),
                      reverse=True)

    @staticmethod
    def meses_disponibles(incidencias: list[Incidencia], anyo: int) -> list[tuple[int, int]]:
        """[(mes, nº), ...] del año indicado, en orden."""
        return sorted(Counter(i.fecha.month for i in incidencias
                              if i.fecha and i.fecha.year == anyo).items())

    def ranking_equipos(self, top: int) -> list[tuple[str, int]]:
        return self.resumen.por_equipo.most_common(top)

    def ranking_tipos(self) -> list[tuple[str, int]]:
        return self.resumen.por_tipo.most_common()

    def ranking_marcas(self) -> list[tuple[str, int]]:
        return self.resumen.por_marca.most_common()


def analizar_archivo(ruta: Path, hoy: date | None = None,
                     reglas: Reglas | None = None) -> Analizador:
    """Tubería completa: parsear -> reparar/validar/clasificar -> métricas.

    Lanza models.ErrorCarga si el archivo no se puede usar.
    """
    _, incidencias = XMLParser().cargar(ruta)
    return Analizador(ruta, procesar(incidencias, hoy=hoy, reglas=reglas))


# ══════════════════════════════════════════════════════════════════════════
# Radar de zonas y equipos reincidentes
# ══════════════════════════════════════════════════════════════════════════

NIVEL_CRONICO, NIVEL_REINCIDENTE, NIVEL_CALIENTE, NIVEL_VIGILAR, NIVEL_NORMAL = (
    "🔥 Crónico", "⚠️ Reincidente", "🔥 Punto caliente", "⚠️ Vigilar", "Normal")


@dataclass
class PuntoCaliente:
    """Una zona o un equipo con su historial de fallos (solo incidencias válidas)."""
    clave: str
    tipo: str                       # "Zona" | "Equipo"
    total: int
    recientes: int                  # Fallos en la ventana reciente
    primera: date | None
    ultima: date | None
    nivel: str = NIVEL_NORMAL
    zona: str = ""
    categoria: str = ""
    ids: list[str] = field(default_factory=list)
    tendencia: float = 0.0          # Zonas: ritmo reciente / ritmo histórico

    @property
    def alerta(self) -> bool:
        return self.nivel != NIVEL_NORMAL


def _valor(inc: Incidencia, patron: re.Pattern[str]) -> str:
    campo = inc.buscar_campo(patron)
    return " ".join(campo[1].split()) if campo else ""


def fecha_referencia(incidencias: list[Incidencia]) -> date | None:
    """Fecha desde la que se miden las "ventanas recientes".

    Es el percentil 98 de las fechas válidas, no la máxima: así un par de
    incidencias sueltas muy posteriores al resto no dejan la ventana vacía.
    """
    fechas = sorted(i.fecha for i in incidencias if i.valida and i.fecha)
    if not fechas:
        return None
    return fechas[min(len(fechas) - 1, int(len(fechas) * 0.98))]


def _agrupar(incidencias: list[Incidencia], clave, tipo: str,
             referencia: date | None, ventana: int) -> list[PuntoCaliente]:
    grupos: dict[str, list[Incidencia]] = defaultdict(list)
    for inc in incidencias:
        if inc.valida and (k := clave(inc)):
            grupos[k].append(inc)
    desde = referencia - timedelta(days=ventana) if referencia else None
    puntos = []
    for k, lista in grupos.items():
        fechas = sorted(i.fecha for i in lista if i.fecha)
        recientes = sum(1 for f in fechas if desde and f > desde)
        puntos.append(PuntoCaliente(
            k, tipo, len(lista), recientes, fechas[0] if fechas else None,
            fechas[-1] if fechas else None,
            zona=Counter(_valor(i, RE_CAMPO_ZONA) for i in lista).most_common(1)[0][0],
            categoria=Counter(i.tipo for i in lista).most_common(1)[0][0],
            ids=[i.id for i in lista]))
    return puntos


def radar_zonas(incidencias: list[Incidencia], referencia: date | None = None,
                ventana: int = VENTANA_RECIENTE_DIAS) -> list[PuntoCaliente]:
    """Zonas ordenadas por fallos recientes.

    Alerta según la TENDENCIA: fallos en la ventana frente a los que le
    tocarían a esa zona por su ritmo histórico (1.0 = lo normal; 1.3 = un 30 %
    más de lo habitual -> punto caliente)."""
    referencia = referencia or fecha_referencia(incidencias)
    puntos = _agrupar(incidencias, lambda i: _valor(i, RE_CAMPO_ZONA), "Zona",
                      referencia, ventana)
    inicio = min((p.primera for p in puntos if p.primera), default=None)
    if referencia and inicio:
        periodo = max(ventana, (referencia - inicio).days + 1)
        for p in puntos:
            esperado = p.total * ventana / periodo      # Fallos "normales" en la ventana
            p.tendencia = p.recientes / esperado if esperado else 0.0
            if p.recientes >= 3 and p.tendencia >= TENDENCIA_CALIENTE:
                p.nivel = NIVEL_CALIENTE
            elif p.recientes >= 3 and p.tendencia >= TENDENCIA_VIGILAR:
                p.nivel = NIVEL_VIGILAR
    return sorted(puntos, key=lambda p: (p.recientes, p.total), reverse=True)


def equipos_reincidentes(incidencias: list[Incidencia], referencia: date | None = None,
                         ventana: int = VENTANA_RECIENTE_DIAS * 3,
                         minimo: int = MIN_FALLOS_REINCIDENTE) -> list[PuntoCaliente]:
    """Equipos (por código de inventario) con fallos repetidos.

    Crónico: ≥ MIN_FALLOS_CRONICO fallos en total o ≥ MIN_FALLOS_VENTANA en la ventana.
    Reincidente: ≥ MIN_FALLOS_REINCIDENTE fallos en total.
    """
    referencia = referencia or fecha_referencia(incidencias)
    puntos = _agrupar(incidencias, lambda i: _valor(i, RE_CAMPO_CODIGO).upper(), "Equipo",
                      referencia, ventana)
    salida = []
    for p in puntos:
        if p.total >= MIN_FALLOS_CRONICO or p.recientes >= MIN_FALLOS_VENTANA:
            p.nivel = NIVEL_CRONICO
        elif p.total >= minimo:
            p.nivel = NIVEL_REINCIDENTE
        else:
            continue
        salida.append(p)
    return sorted(salida, key=lambda p: (p.nivel == NIVEL_CRONICO, p.recientes, p.total),
                  reverse=True)


def zonas_por_mes(incidencias: list[Incidencia]) -> list[tuple[str, str, int]]:
    """[(zona, 'AAAA-MM', fallos)] de las válidas: base del mapa de calor."""
    conteo = Counter((_valor(i, RE_CAMPO_ZONA), f"{i.fecha:%Y-%m}")
                     for i in incidencias if i.valida and i.fecha and _valor(i, RE_CAMPO_ZONA))
    return [(z, m, n) for (z, m), n in sorted(conteo.items())]


# ══════════════════════════════════════════════════════════════════════════
# Minería de palabras en incidencias sin clasificar
# ══════════════════════════════════════════════════════════════════════════

RE_PALABRA_MINERIA = re.compile(r"[a-z]{3,}")


@dataclass
class Termino:
    texto: str
    tipo: str                       # "Palabra" | "Bigrama"
    incidencias: int                # En cuántas incidencias aparece
    ejemplo: str = ""


def _tokens(texto: str) -> list[str]:
    limpio = normalizar(texto.replace("\u2019", "'")).replace("'", " ")
    return [t for t in RE_PALABRA_MINERIA.findall(limpio)
            if t not in STOPWORDS and t not in MINERIA_IGNORAR]


def palabras_emergentes(incidencias: list[Incidencia], patrones_conocidos: list[re.Pattern[str]],
                        top: int = 15, minimo: int = 2) -> list[Termino]:
    """Palabras y bigramas frecuentes en las válidas SIN clasificar bien
    (categoría por defecto o severidad Media) que todavía no son palabra clave
    de ninguna regla de severidad: candidatos a añadirse a rules.json."""
    conocida = lambda t: any(p.search(t) for p in patrones_conocidos)  # noqa: E731
    docs: Counter[tuple[str, str]] = Counter()
    ejemplos: dict[tuple[str, str], str] = {}
    for inc in incidencias:
        if not inc.valida or (inc.tipo != CATEGORIA_POR_DEFECTO and inc.severidad != "Media"):
            continue
        tokens = _tokens(inc.descripcion)
        terminos = {("Palabra", t) for t in tokens}
        terminos |= {("Bigrama", f"{a} {b}") for a, b in zip(tokens, tokens[1:])}
        for termino in terminos:
            docs[termino] += 1
            ejemplos.setdefault(termino, inc.descripcion)
    salida = [Termino(texto, tipo, n, ejemplos[(tipo, texto)])
              for (tipo, texto), n in docs.most_common()
              if n >= minimo and not conocida(texto)]
    palabras = [t for t in salida if t.tipo == "Palabra"][:top]
    bigramas = [t for t in salida if t.tipo == "Bigrama"][:top]
    return palabras + bigramas
