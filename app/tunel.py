# -*- coding: utf-8 -*-
"""Túnel público (HTTPS) para abrir la web desde cualquier red, p. ej. el móvil con 4G/5G.

La IP pública del router no sirve (NAT/firewall), así que se usa un servicio de
túnel que da una URL https://... alcanzable desde Internet. Se prueba, en orden:

    1. cloudflared   Quick Tunnel de Cloudflare: sin cuenta.     -> *.trycloudflare.com
    2. pyngrok       ngrok: necesita NGROK_AUTHTOKEN (gratuito).  -> *.ngrok-free.app
    3. localtunnel   `lt` (npm i -g localtunnel) o `npx`.         -> *.loca.lt

Si no hay ninguno, ErrorTunel explica cómo instalar cloudflared en cada sistema.
"""

from __future__ import annotations

import importlib.util
import io
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

TIEMPO_ESPERA_S = 40
PROVEEDORES = ("cloudflared", "ngrok", "localtunnel")

RE_URL_CLOUDFLARE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RE_URL_LOCALTUNNEL = re.compile(r"https://[a-z0-9-]+\.loca\.lt")

INSTRUCCIONES = """No hay ninguna herramienta de túnel instalada. Instala cloudflared (gratis, sin cuenta):

  • Windows:  winget install --id Cloudflare.cloudflared
  • macOS:    brew install cloudflared
  • Linux:    descarga «cloudflared-linux-amd64» de
              https://github.com/cloudflare/cloudflared/releases
              y guárdalo como ~/.local/bin/cloudflared (chmod +x)

Alternativas: `pip install pyngrok` + variable NGROK_AUTHTOKEN, o `npm i -g localtunnel`.
Para tenerla siempre disponible sin el PC encendido: Streamlit Community Cloud (ver README)."""


class ErrorTunel(Exception):
    """No se ha podido abrir ningún túnel (el mensaje explica qué hacer)."""


@dataclass
class Tunel:
    proveedor: str
    url: str
    _cerrar: Callable[[], None] = field(default=lambda: None, repr=False)

    def cerrar(self) -> None:
        try:
            self._cerrar()
        except Exception:  # noqa: BLE001 — cerrar nunca debe romper la salida
            pass


# ══════════════════════════════════════════════════════════════════════════
# Detección
# ══════════════════════════════════════════════════════════════════════════

def _comando_localtunnel(puerto: int) -> list[str] | None:
    if lt := shutil.which("lt"):
        return [lt, "--port", str(puerto)]
    if npx := shutil.which("npx"):
        return [npx, "--yes", "localtunnel", "--port", str(puerto)]
    return None


def disponibles() -> list[str]:
    """Proveedores utilizables en este equipo, en orden de preferencia."""
    salida = []
    if shutil.which("cloudflared"):
        salida.append("cloudflared")
    if importlib.util.find_spec("pyngrok") is not None:
        salida.append("ngrok")
    if _comando_localtunnel(0):
        salida.append("localtunnel")
    return salida


# ══════════════════════════════════════════════════════════════════════════
# Arranque de un proceso y captura de su URL
# ══════════════════════════════════════════════════════════════════════════

def _proceso_con_url(comando: list[str], patron: re.Pattern[str], proveedor: str,
                     espera: float) -> Tunel:
    """Lanza `comando` y lee su salida hasta encontrar la URL pública."""
    opciones: dict = {}
    if os.name == "nt":                     # Ctrl+C en la consola no lo mata a medias
        opciones["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1, **opciones)
    except OSError as error:
        raise ErrorTunel(f"{proveedor}: no se ha podido ejecutar ({error}).") from None

    lineas: queue.Queue[str] = queue.Queue()

    def leer() -> None:                     # Vacía la tubería siempre (si no, se bloquea)
        assert proceso.stdout is not None
        for linea in proceso.stdout:
            lineas.put(linea)

    threading.Thread(target=leer, daemon=True).start()

    def cerrar() -> None:
        if proceso.poll() is None:
            proceso.terminate()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proceso.kill()

    limite, ultimas = time.monotonic() + espera, []
    while time.monotonic() < limite:
        try:
            linea = lineas.get(timeout=0.25)
        except queue.Empty:
            if proceso.poll() is not None and lineas.empty():
                break                       # El proceso ha muerto sin dar URL
            continue
        ultimas = (ultimas + [linea.strip()])[-4:]
        if m := patron.search(linea):
            return Tunel(proveedor, m.group(0), cerrar)
    cerrar()
    detalle = " | ".join(l for l in ultimas if l) or "sin salida"
    raise ErrorTunel(f"{proveedor}: no ha dado una URL pública en {espera:.0f} s ({detalle}).")


def _ngrok(puerto: int) -> Tunel:
    if not os.environ.get("NGROK_AUTHTOKEN"):
        raise ErrorTunel("ngrok: falta la variable de entorno NGROK_AUTHTOKEN "
                         "(token gratuito en https://dashboard.ngrok.com).")
    try:
        from pyngrok import conf, ngrok      # Importación tardía: dependencia opcional
        conf.get_default().auth_token = os.environ["NGROK_AUTHTOKEN"]
        tunel = ngrok.connect(puerto, "http")
    except Exception as error:  # noqa: BLE001 — pyngrok lanza tipos variados
        raise ErrorTunel(f"ngrok: {error}") from None
    url = tunel.public_url.replace("http://", "https://", 1)

    def cerrar() -> None:
        ngrok.disconnect(tunel.public_url)
        ngrok.kill()

    return Tunel("ngrok", url, cerrar)


def abrir_tunel(puerto: int, preferido: str = "auto", espera: float = TIEMPO_ESPERA_S) -> Tunel:
    """Abre el primer túnel que funcione. Lanza ErrorTunel con todos los motivos si no."""
    orden = list(PROVEEDORES) if preferido == "auto" else [preferido]
    errores = []
    for proveedor in orden:
        try:
            if proveedor == "cloudflared":
                binario = shutil.which("cloudflared")
                if not binario:
                    errores.append("cloudflared: no está instalado.")
                    continue
                return _proceso_con_url(
                    [binario, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{puerto}"],
                    RE_URL_CLOUDFLARE, "cloudflared", espera)
            if proveedor == "ngrok":
                if importlib.util.find_spec("pyngrok") is None:
                    errores.append("ngrok: pyngrok no está instalado.")
                    continue
                return _ngrok(puerto)
            if proveedor == "localtunnel":
                comando = _comando_localtunnel(puerto)
                if not comando:
                    errores.append("localtunnel: ni `lt` ni `npx` están instalados.")
                    continue
                return _proceso_con_url(comando, RE_URL_LOCALTUNNEL, "localtunnel", espera)
            errores.append(f"{proveedor}: proveedor desconocido.")
        except ErrorTunel as error:
            errores.append(str(error))
    if not disponibles():
        raise ErrorTunel(INSTRUCCIONES)
    raise ErrorTunel("No se ha podido abrir el túnel:\n" + "\n".join(f"  • {e}" for e in errores))


# ══════════════════════════════════════════════════════════════════════════
# Código QR en ASCII
# ══════════════════════════════════════════════════════════════════════════

def qr_ascii(url: str) -> str | None:
    """QR de la URL con bloques ▀▄█ para escanearlo desde la terminal.

    Se dibuja "invertido" (módulos oscuros = fondo de la terminal), que es lo
    correcto en terminales de fondo oscuro. None si falta la librería qrcode.
    """
    if importlib.util.find_spec("qrcode") is None:
        return None
    import qrcode                              # Importación tardía: dependencia opcional
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    salida = io.StringIO()
    qr.print_ascii(out=salida, invert=True)
    return salida.getvalue().rstrip("\n")


if __name__ == "__main__":                   # Prueba rápida: python -m app.tunel 8501
    t = abrir_tunel(int(sys.argv[1]) if len(sys.argv) > 1 else 8501)
    print(t.proveedor, t.url)
    print(qr_ascii(t.url) or "")
    t.cerrar()
