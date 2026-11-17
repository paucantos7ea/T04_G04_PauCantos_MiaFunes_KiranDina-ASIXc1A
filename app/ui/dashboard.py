# -*- coding: utf-8 -*-
"""Dashboard inicial, tarjetas KPI y gráficas de barras / sparklines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from rich import box
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.analytics import Analizador
from app.config import (BLOQUES_PARCIALES, CATEGORIAS, COLOR_SEVERIDAD, NEON_CIAN,
                        NEON_NARANJA, NEON_ROJO, NEON_ROSA, NEON_VERDE, NIVELES, SPARK,
                        TOP_EQUIPOS)
from app.utils import truncar

# ── Primitivas gráficas ───────────────────────────────────────────────────


def barra(valor: float, maximo: float, ancho: int = 40) -> str:
    """Barra horizontal con precisión de 1/8 de carácter (█ + ▏▎▍▌▋▊▉)."""
    if maximo <= 0 or valor <= 0:
        return ""
    octavos = round(valor / maximo * ancho * 8)
    llenos, resto = divmod(octavos, 8)
    return ("█" * llenos + (BLOQUES_PARCIALES[resto] if resto else "")) or "▏"


def sparkline(valores: Sequence[int]) -> str:
    """Mini gráfico de una línea: ▁▂▃▄▅▆▇█."""
    maximo = max(valores, default=0)
    if maximo == 0:
        return ""
    return "".join(SPARK[min(7, round(v / maximo * 7))] for v in valores)


def tabla_barras(pares: Sequence[tuple[str, int]], color: str | Mapping[str, str],
                 ancho: int = 36) -> Table:
    """Gráfico de barras horizontales: etiqueta | barra | número."""
    tabla = Table(box=None, show_header=False, padding=(0, 1))
    tabla.add_column(style="bold white", no_wrap=True)
    tabla.add_column(no_wrap=True)
    tabla.add_column(justify="right", style=f"bold {NEON_ROSA}")
    maximo = max((n for _, n in pares), default=0)
    for etiqueta, n in pares:
        tono = color.get(etiqueta, NEON_CIAN) if isinstance(color, Mapping) else color
        tabla.add_row(truncar(etiqueta, 24), Text(barra(n, maximo, ancho), style=tono), str(n))
    return tabla


def tarjeta(titulo: str, valor: str, sub: str, color: str) -> Panel:
    """Tarjeta KPI: número grande + subtítulo."""
    contenido = Text(justify="center")
    contenido.append(f"{valor}\n", style=f"bold {color}")
    contenido.append(sub, style="dim")
    return Panel(contenido, title=f"[bold]{titulo}[/]", border_style=color,
                 box=box.HEAVY, width=22, padding=(1, 1))


def panel_severidad(datos: Analizador, titulo: str = "Incidencias válidas por severidad") -> Panel:
    pares = [(n, datos.resumen.por_severidad.get(n, 0)) for n in NIVELES]
    return Panel(tabla_barras(pares, COLOR_SEVERIDAD), title=f"[bold]{titulo}[/]",
                 border_style=NEON_NARANJA, box=box.ROUNDED, padding=(1, 2))


# ── Vistas completas ──────────────────────────────────────────────────────


def render_dashboard(datos: Analizador) -> Panel:
    """Panel de inicio: KPIs, barra de validez y sparklines."""
    r = datos.resumen
    pct = r.pct_validas

    tarjetas = Columns([
        tarjeta("Procesadas", str(r.total), "incidencias", NEON_CIAN),
        tarjeta("Válidas", str(r.validas), f"{pct:.1f} %", NEON_VERDE),
        tarjeta("Bloqueadas", str(r.anomalas), f"{r.pct_anomalas:.1f} %", NEON_ROJO),
        tarjeta("Críticas", str(r.por_severidad.get("Crítica", 0)),
                "entre las válidas", NEON_NARANJA),
    ])

    ancho = 50
    verdes = round(ancho * pct / 100)
    validez = Text.assemble(("Validez   ", "bold"), ("█" * verdes, NEON_VERDE),
                            ("█" * (ancho - verdes), NEON_ROJO), (f"  {pct:.1f} %", "dim"))

    spark = Table(box=None, show_header=False, padding=(0, 1))
    spark.add_column(style="bold")
    spark.add_column(style=f"bold {NEON_CIAN}", no_wrap=True)
    spark.add_column(style="dim")
    meses = r.actividad_mensual()
    if meses:
        spark.add_row("Actividad mensual", sparkline([n for _, n in meses]),
                      f"{meses[0][0]} → {meses[-1][0]}")
    spark.add_row("Severidad", Text(sparkline([r.por_severidad.get(n, 0) for n in NIVELES]),
                                    style=NEON_NARANJA), "Crítica → Leve")
    top = datos.ranking_equipos(TOP_EQUIPOS)
    if top:
        spark.add_row("Top equipos", sparkline([n for _, n in top]),
                      f"líder: {truncar(top[0][0], 22)} ({top[0][1]})")
    spark.add_row("Anomalías por tipo",
                  Text(sparkline([r.por_categoria.get(c, 0) for c in CATEGORIAS]), style=NEON_ROJO),
                  " · ".join(f"{c.split()[0]} {r.por_categoria.get(c, 0)}" for c in CATEGORIAS))

    return Panel(
        Group(Text.assemble(("Archivo: ", "dim"), (str(datos.ruta), "bold")), Text(""),
              tarjetas, Text(""), validez, Text(""), spark),
        title=f"[bold {NEON_ROSA}]◆ ESCÁNER DE INCIDENCIAS XML ◆[/]",
        subtitle=f"[{NEON_CIAN}]↑↓ moverte · Enter elegir · Ctrl+C salir[/]",
        border_style=NEON_ROSA, box=box.DOUBLE, padding=(1, 2))


def render_graficas(datos: Analizador) -> Panel:
    """Averías por categoría, top equipos y distribución de severidad."""
    tipos = Panel(tabla_barras(datos.ranking_tipos(), NEON_CIAN),
                  title="[bold]Averías por categoría de equipo[/]",
                  border_style=NEON_CIAN, box=box.ROUNDED, padding=(1, 2))
    top = datos.ranking_equipos(TOP_EQUIPOS)
    contenido_equipos: RenderableType = (
        tabla_barras(top, NEON_ROSA) if top
        else Text("No se ha detectado un campo de equipo.", style="dim"))
    equipos = Panel(contenido_equipos,
                    title=f"[bold]Top {TOP_EQUIPOS} equipos con más averías[/]",
                    border_style=NEON_ROSA, box=box.ROUNDED, padding=(1, 2))
    return Panel(Group(tipos, equipos, panel_severidad(datos, "Distribución por severidad")),
                 title=f"[bold {NEON_ROSA}]◆ GRÁFICAS DE AVERÍAS (solo incidencias válidas) ◆[/]",
                 border_style=NEON_ROSA, box=box.DOUBLE)
