# -*- coding: utf-8 -*-
"""Modelo de datos: Incidencia, Anomalia, EstadisticasResumen y errores controlados."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from app.config import CATEGORIA_POR_DEFECTO, SEVERIDAD_POR_DEFECTO


@dataclass
class Anomalia:
    """Una regla de validación violada."""
    categoria: str          # Una de config.CATEGORIAS
    regla: str              # Causa precisa, legible
    campo: str = "—"        # Dónde se ha detectado
    valor: str = ""         # Contenido corrupto extraído
    extra: str = ""         # Pista adicional (p. ej. binario decodificado)


@dataclass
class Incidencia:
    """Una <incidencia> del XML, ya validada y enriquecida."""
    id: str
    campos: dict[str, str] = field(default_factory=dict)   # Campos con valor
    vacios: list[str] = field(default_factory=list)        # Etiquetas vacías
    sin_id: bool = False
    anomalias: list[Anomalia] = field(default_factory=list)
    # Rellenados por validator.AnomalyDetector / validator.Clasificador
    fecha: date | None = None
    equipo: str = ""
    descripcion: str = ""
    tipo: str = CATEGORIA_POR_DEFECTO   # Categoría del equipo
    marca: str | None = None
    severidad: str = SEVERIDAD_POR_DEFECTO
    severidad_inferida: bool = True

    @property
    def valida(self) -> bool:
        return not self.anomalias

    def categorias(self) -> set[str]:
        """Categorías de anomalía en las que cae esta incidencia."""
        return {a.categoria for a in self.anomalias}

    def buscar_campo(self, patron: re.Pattern[str],
                     excluir: re.Pattern[str] | None = None) -> tuple[str, str] | None:
        """Primer (nombre, valor) cuyo nombre encaja con `patron` y no con `excluir`."""
        for nombre, valor in self.campos.items():
            if patron.search(nombre) and not (excluir and excluir.search(nombre)):
                return nombre, valor
        return None


@dataclass
class EstadisticasResumen:
    """Métricas agregadas, calculadas una sola vez tras la carga."""
    total: int = 0
    validas: int = 0
    anomalas: int = 0
    por_tipo: Counter[str] = field(default_factory=Counter)
    por_equipo: Counter[str] = field(default_factory=Counter)
    por_severidad: Counter[str] = field(default_factory=Counter)
    por_marca: Counter[str] = field(default_factory=Counter)
    por_categoria: Counter[str] = field(default_factory=Counter)
    por_mes: Counter[tuple[int, int]] = field(default_factory=Counter)

    @property
    def pct_validas(self) -> float:
        return self.validas / self.total * 100 if self.total else 0.0

    @property
    def pct_anomalas(self) -> float:
        return 100 - self.pct_validas if self.total else 0.0

    def actividad_mensual(self, meses: int = 12) -> list[tuple[str, int]]:
        """Últimos `meses` meses con datos: [('2025-03', 4), ...]."""
        ordenados = sorted(self.por_mes.items())[-meses:]
        return [(f"{anyo}-{mes:02d}", n) for (anyo, mes), n in ordenados]


class ErrorCarga(Exception):
    """Error controlado al cargar el XML (título + mensaje para el panel)."""

    def __init__(self, titulo: str, mensaje: str):
        super().__init__(mensaje)
        self.titulo = titulo
        self.mensaje = mensaje


class ErrorExportacion(Exception):
    """El JSON existente no se puede leer o fusionar."""
