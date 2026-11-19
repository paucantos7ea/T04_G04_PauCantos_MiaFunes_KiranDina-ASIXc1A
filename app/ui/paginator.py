# -*- coding: utf-8 -*-
"""Tablas Zebra paginadas y fichas de diagnóstico por ID.

Controles del paginador:
    [N] Siguiente   [P] Anterior   [G] Ir a página   [I] Ficha por ID   [Q] Volver

El paginador no conoce questionary: recibe cualquier objeto que cumpla el
protocolo `LectorTeclado` (lo implementa ui.menus.Entrada). Así no hay
importaciones circulares entre paginator.py y menus.py.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.config import (COLOR_SEVERIDAD, MAX_FICHA, NEON_AMARILLO, NEON_CIAN, NEON_ROJO,
                        NEON_ROSA, NEON_VERDE, POR_PAGINA, ZEBRA)
from app.models import Incidencia
from app.ui.console import panel_aviso
from app.utils import truncar


class LectorTeclado(Protocol):
    """Lo mínimo que el paginador necesita para leer del usuario."""

    def error(self, mensaje: str) -> None: ...
    def letra(self, mensaje: str, validas: str) -> str: ...
    def numero(self, mensaje: str, minimo: int, maximo: int) -> int | None: ...
    def pausa(self) -> None: ...


# Una acción extra: tecla -> (texto del pie, función a ejecutar)
AccionExtra = dict[str, tuple[str, Callable[[], None]]]
ConstructorTabla = Callable[[Sequence[Any], int, int], Table]


# ══════════════════════════════════════════════════════════════════════════
# Paginador
# ══════════════════════════════════════════════════════════════════════════

class Paginator:
    def __init__(self, consola: Console, entrada: LectorTeclado, por_pagina: int = POR_PAGINA):
        self.consola = consola
        self.entrada = entrada
        self.por_pagina = por_pagina

    def _pie(self, pagina: int, total_pag: int, n: int, extras: AccionExtra) -> Panel:
        def opcion(tecla: str, texto: str, activa: bool) -> Text:
            if activa:
                return Text.assemble((f"[{tecla}]", f"bold {NEON_CIAN}"), (f" {texto}   ", "white"))
            return Text(f"[{tecla}] {texto}   ", style="dim strike")

        estado = Text.assemble(
            ("Página ", "bold"), (str(pagina), f"bold {NEON_AMARILLO}"),
            (" de ", "bold"), (str(total_pag), f"bold {NEON_AMARILLO}"),
            (f"   ·   {n} registros   ·   {self.por_pagina} por página", "dim"))
        teclas = Text.assemble(
            opcion("N", "Siguiente", pagina < total_pag),
            opcion("P", "Anterior", pagina > 1),
            opcion("G", "Ir a página...", total_pag > 1),
            *[opcion(t, texto, True) for t, (texto, _) in extras.items()],
            opcion("Q", "Volver al menú", True))
        return Panel(Group(estado, teclas), border_style=NEON_CIAN, box=box.ROUNDED)

    def mostrar(self, elementos: Sequence[Any], construir: ConstructorTabla, vacio: str,
                extras: AccionExtra | None = None) -> None:
        extras = extras or {}
        if not elementos:
            self.consola.print(panel_aviso(vacio))
            self.entrada.pausa()
            return

        total_pag = math.ceil(len(elementos) / self.por_pagina)
        pagina, aviso = 1, ""
        teclas = "NPG" + "".join(extras) + "Q"

        while True:
            self.consola.clear()
            inicio = (pagina - 1) * self.por_pagina
            self.consola.print(construir(elementos[inicio:inicio + self.por_pagina],
                                         pagina, total_pag))
            self.consola.print(self._pie(pagina, total_pag, len(elementos), extras))
            if aviso:
                self.entrada.error(aviso)
                aviso = ""

            letra = self.entrada.letra(f"Elige [{'/'.join(teclas)}]: ", teclas)
            if letra == "Q":
                return
            if letra == "N":
                if pagina < total_pag:
                    pagina += 1
                else:
                    aviso = "Ya estás en la última página."
            elif letra == "P":
                if pagina > 1:
                    pagina -= 1
                else:
                    aviso = "Ya estás en la primera página."
            elif letra == "G":
                destino = self.entrada.numero(
                    f"Ir a la página (1-{total_pag}, Enter cancela): ", 1, total_pag)
                if destino is not None:
                    pagina = destino
            else:
                extras[letra][1]()   # Acción extra (p. ej. inspeccionar ID)


# ══════════════════════════════════════════════════════════════════════════
# Constructores de tablas Zebra
# ══════════════════════════════════════════════════════════════════════════

def texto_severidad(inc: Incidencia) -> Text:
    texto = Text(inc.severidad, style=f"bold {COLOR_SEVERIDAD.get(inc.severidad, 'white')}")
    if inc.severidad_inferida:
        texto.append(" *", style="dim")
    return texto


def texto_estado(inc: Incidencia) -> Text:
    if inc.valida:
        return Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}")
    return Text("✖ RECHAZADA", style=f"bold {NEON_ROJO}")


def constructor_validas(titulo: str) -> ConstructorTabla:
    def construir(items: Sequence[Incidencia], pagina: int, total_pag: int) -> Table:
        tabla = Table(title=f"[bold {NEON_VERDE}]{escape(titulo)}[/]",
                      caption="[dim]* severidad deducida por palabras clave[/]",
                      box=box.ROUNDED, border_style=NEON_CIAN,
                      header_style=f"bold {NEON_ROSA}", row_styles=["", ZEBRA], expand=True)
        for columna, opciones in [("ID", {"no_wrap": True}), ("Fecha", {"no_wrap": True}),
                                  ("Equipo", {}), ("Categoría", {}), ("Marca", {}),
                                  ("Severidad", {"no_wrap": True}),
                                  ("Descripción", {"overflow": "fold", "ratio": 3}),
                                  ("Estado", {"no_wrap": True})]:
            tabla.add_column(columna, **opciones)
        for inc in items:
            tabla.add_row(
                Text(truncar(inc.id, 15), style=f"bold {NEON_AMARILLO}"),
                inc.fecha.strftime("%d/%m/%Y") if inc.fecha else "—",
                Text(truncar(inc.equipo or "—", 22)),
                Text(inc.tipo), Text(inc.marca or "—"),
                texto_severidad(inc),
                Text(truncar(inc.descripcion or "—")),
                texto_estado(inc))
        return tabla
    return construir


def constructor_anomalias(categoria: str | None) -> ConstructorTabla:
    def construir(items: Sequence[Incidencia], pagina: int, total_pag: int) -> Table:
        tabla = Table(title=f"[bold {NEON_ROJO}]Registro de anomalías · "
                            f"{escape(categoria or 'Todas')}[/]",
                      box=box.ROUNDED, border_style=NEON_ROSA,
                      header_style=f"bold {NEON_CIAN}", expand=True)
        tabla.add_column("ID", no_wrap=True)
        tabla.add_column("Regla violada", overflow="fold", ratio=2)
        tabla.add_column("Campo", overflow="fold")
        tabla.add_column("Contenido detectado", overflow="fold", ratio=2)
        for indice, inc in enumerate(items):
            fondo = ZEBRA if indice % 2 else ""     # Zebra por incidencia
            lista = [a for a in inc.anomalias if categoria in (None, a.categoria)]
            for j, a in enumerate(lista):
                tabla.add_row(
                    Text(truncar(inc.id, 15) if j == 0 else "", style=f"bold {NEON_AMARILLO}"),
                    Text(a.regla, style=f"bold {NEON_ROJO}"),
                    Text(truncar(a.campo, 22), style=NEON_CIAN),
                    Text(truncar(a.valor), style="dim"),
                    style=fondo)
        return tabla
    return construir


def constructor_busqueda(termino: str) -> ConstructorTabla:
    def construir(items: Sequence[tuple[Incidencia, str, str]], pagina: int,
                  total_pag: int) -> Table:
        tabla = Table(title=f"[bold {NEON_CIAN}]Resultados para «{escape(termino)}»[/]",
                      box=box.ROUNDED, border_style=NEON_CIAN,
                      header_style=f"bold {NEON_ROSA}", row_styles=["", ZEBRA], expand=True)
        tabla.add_column("ID", no_wrap=True)
        tabla.add_column("Estado", no_wrap=True)
        tabla.add_column("Campo", overflow="fold")
        tabla.add_column("Coincidencia", overflow="fold", ratio=3)
        for inc, campo, valor in items:
            tabla.add_row(Text(truncar(inc.id, 15), style=f"bold {NEON_AMARILLO}"),
                          texto_estado(inc),
                          Text(truncar(campo, 22), style=NEON_CIAN), Text(truncar(valor)))
        return tabla
    return construir


# ══════════════════════════════════════════════════════════════════════════
# Fichas de diagnóstico ([I] por ID)
# ══════════════════════════════════════════════════════════════════════════

def _tabla_campos(inc: Incidencia) -> Table:
    tabla = Table(box=box.SIMPLE_HEAD, row_styles=["", ZEBRA],
                  header_style=f"bold {NEON_ROSA}", expand=True)
    tabla.add_column("Campo del XML", style=f"bold {NEON_CIAN}")
    tabla.add_column("Valor", overflow="fold", ratio=3)
    for nombre, valor in inc.campos.items():
        tabla.add_row(Text(truncar(nombre, 30)), Text(truncar(valor)))
    for nombre in inc.vacios:
        tabla.add_row(Text(truncar(nombre, 30)), Text("(vacío)", style=f"bold {NEON_ROJO}"))
    return tabla


def ficha_rechazo(inc: Incidencia) -> Panel:
    """Panel de diagnóstico: ID, cada regla violada y el contenido corrupto."""
    cabecera = Table.grid(padding=(0, 2))
    cabecera.add_column(style="dim")
    cabecera.add_column()
    cabecera.add_row("ID", Text(inc.id, style=f"bold {NEON_AMARILLO}"))
    cabecera.add_row("Veredicto", texto_estado(inc))
    cabecera.add_row("Reglas violadas", Text(str(len(inc.anomalias)), style="bold"))
    cabecera.add_row("Categorías", Text(", ".join(sorted(inc.categorias())), style=NEON_ROSA))
    if inc.auto_reparada:
        cabecera.add_row("Auto-reparada", _texto_reparaciones(inc))

    causas = Table(box=box.ROUNDED, border_style=NEON_ROJO, header_style=f"bold {NEON_CIAN}",
                   expand=True, title="[bold]Causa exacta del rechazo[/]")
    causas.add_column("#", justify="right", style="dim")
    causas.add_column("Regla violada", overflow="fold", ratio=2)
    causas.add_column("Campo", overflow="fold")
    causas.add_column("Contenido corrupto extraído", overflow="fold", ratio=3)
    for n, a in enumerate(inc.anomalias, start=1):
        contenido = Text(truncar(a.valor, MAX_FICHA), style=NEON_AMARILLO)
        if len(a.valor) > MAX_FICHA:
            contenido.append(f"\n({len(a.valor)} caracteres en total)", style="dim")
        if a.extra:
            contenido.append(f"\n{a.extra}", style=f"italic {NEON_CIAN}")
        causas.add_row(str(n), Text(a.regla, style=f"bold {NEON_ROJO}"),
                       Text(a.campo, style=NEON_CIAN), contenido)

    return Panel(Group(cabecera, Text(""), causas, Text(""),
                       Text("Registro completo", style="bold"), _tabla_campos(inc)),
                 title=f"[bold {NEON_ROJO}]FICHA DE RECHAZO · ID {escape(inc.id)}[/]",
                 border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2))


def _texto_reparaciones(inc: Incidencia) -> Text:
    return Text("; ".join(f"{r.campo}: «{truncar(r.antes, 25)}» → «{truncar(r.despues, 25)}»"
                          for r in inc.reparaciones), style=NEON_CIAN)


def ficha_valida(inc: Incidencia) -> Panel:
    resumen = Text.assemble(
        texto_estado(inc), ("   Severidad: ", "dim"),
        texto_severidad(inc), ("   Categoría: ", "dim"), (inc.tipo, "bold"),
        ("   Marca: ", "dim"), (inc.marca or "—", "bold"))
    criterio = Text.assemble(("Criterio: ", "dim"),
                             (f"{inc.criterio_severidad} → {inc.regla_severidad}", "italic"))
    partes = [resumen, criterio]
    if inc.auto_reparada:
        partes.append(Text.assemble(("Auto-reparada: ", "dim"), _texto_reparaciones(inc)))
    return Panel(Group(*partes, Text(""), _tabla_campos(inc)),
                 title=f"[bold {NEON_VERDE}]FICHA · ID {escape(inc.id)}[/]",
                 border_style=NEON_VERDE, box=box.HEAVY, padding=(1, 2))


def ficha(inc: Incidencia) -> Panel:
    return ficha_valida(inc) if inc.valida else ficha_rechazo(inc)
