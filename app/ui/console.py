# -*- coding: utf-8 -*-
"""Configuración centralizada de la consola Rich (multiplataforma y UTF-8).

Todo el programa pinta a través de `obtener_consola()`, que se crea una sola
vez DESPUÉS de forzar UTF-8 en stdout/stderr. Así las terminales antiguas de
Windows (CMD/PowerShell con cp850/cp1252) no lanzan UnicodeEncodeError al
dibujar bordes, bloques █ o tildes.
"""

from __future__ import annotations

import io
import sys

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from app.config import NEON_AMARILLO, NEON_CIAN, NEON_ROJO, NEON_ROSA, NEON_VERDE

_consola: Console | None = None


def forzar_utf8() -> None:
    """Reconfigura stdout/stderr a UTF-8 si el entorno lo permite.

    `errors="replace"` garantiza que un carácter imposible de representar se
    sustituya en vez de romper el programa. Si el flujo no admite
    reconfigure() (p. ej. redirigido a un objeto sin ese método) se ignora.
    """
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is None:
            continue
        try:
            reconfigurar(encoding="utf-8", errors="replace")
        except (ValueError, OSError, io.UnsupportedOperation):
            pass


def obtener_consola() -> Console:
    """Consola Rich única para toda la aplicación."""
    global _consola
    if _consola is None:
        forzar_utf8()
        _consola = Console(emoji=False, highlight=False)
    return _consola


def es_interactiva() -> bool:
    """questionary necesita una terminal real; si no la hay, menús numerados."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):     # Flujos cerrados o sustituidos
        return False


# ── Paneles de mensaje reutilizables ──────────────────────────────────────

def panel_error(titulo: str, mensaje: str) -> Panel:
    return Panel(Text(mensaje), title=f"[bold {NEON_ROJO}]✖ {escape(titulo)}[/]",
                 border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2))


def panel_aviso(mensaje: str) -> Panel:
    return Panel(Text(mensaje), border_style=NEON_AMARILLO)


def texto_exito(mensaje: str) -> Text:
    return Text(f"\n✔ {mensaje}", style=f"bold {NEON_VERDE}")


def panel_despedida() -> Panel:
    return Panel(Text("Sesión cerrada. ¡Hasta la próxima!", justify="center",
                      style=f"bold {NEON_CIAN}"),
                 border_style=NEON_ROSA, box=box.DOUBLE, padding=(0, 4))
