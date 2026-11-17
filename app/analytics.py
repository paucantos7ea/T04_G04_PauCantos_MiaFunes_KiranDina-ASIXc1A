# -*- coding: utf-8 -*-
"""Cálculo de métricas, rankings por equipo/tipo/marca y consultas de filtrado."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from app.models import EstadisticasResumen, Incidencia
from app.parser import XMLParser
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


def analizar_archivo(ruta: Path, hoy: date | None = None) -> Analizador:
    """Tubería completa: parsear -> validar/clasificar -> métricas.

    Lanza models.ErrorCarga si el archivo no se puede usar.
    """
    _, incidencias = XMLParser().cargar(ruta)
    return Analizador(ruta, procesar(incidencias, hoy=hoy))
