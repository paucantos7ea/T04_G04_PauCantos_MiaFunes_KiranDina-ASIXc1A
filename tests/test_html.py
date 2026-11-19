# -*- coding: utf-8 -*-
"""Tests del dashboard estático (index.html para GitHub Pages).

* Sin navegador: el HTML es autocontenido, los datos embebidos son correctos y
  el contenido del XML no puede romper la etiqueta <script>.
* Con Chromium (si está instalado): la página arranca sin errores y el motor
  JavaScript (motor.js, usado con «Cargar otro XML local») da EXACTAMENTE los
  mismos resultados que el motor de Python, incidencia por incidencia.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from conftest import HOY, RAIZ, escribir_xml, inc

from app.analytics import analizar_archivo
from app.html_builder import datos_embebidos, generar_html

NAVEGADOR = next((r for n in ("chromium", "chromium-browser", "google-chrome",
                              "google-chrome-stable") if (r := shutil.which(n))), None)
AHORA = datetime(2026, 11, 19, 10, 30)
PINES = {"consulta": "1234", "tecnico": "12345"}


def _carga(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="datos">(.*?)</script>', html, re.S)
    assert m, "no hay bloque de datos"
    return json.loads(m.group(1))


@pytest.fixture
def casos(tmp_path, reglas):
    """XML con los casos difíciles: reparaciones, Faker, routers, basura, vacíos..."""
    ruta = escribir_xml(tmp_path / "respotes.xml", [
        inc("1"),
        inc("2", fecha="2026-05-09", marca="hp", desc="No   funciona\tel teclat"),
        inc("3", desc="Cuba ciudad medios ii."),
        inc("4", fecha="09/10/1668"),
        inc("5", equipo=None),
        inc("6", marca=None, desc="Teclat trencat"),
        inc("7", equipo="Router/Switch", desc="Va molt lent"),
        inc("8", equipo="Router/Switch", desc="No funciona", afectados="Tota l’organització"),
        inc("9", equipo="Router/Switch", desc="Els dispositius perden la connexió i no hi ha internet."),
        inc("10", desc="01001000 01101111 01101100 01100001"),
        inc("11", desc="No funciona ሰላም"),
        inc("12", codigo="X" * 300),
        inc("13", desc="69"),
        inc("14", desc="No me funciona."),
        inc("15", fecha="31/02/2026"),
        inc("16", fecha="09/10/2040"),
        inc("17", desc="Noticia de Fox News sobre el ordenador que no arranca"),
        inc("18", marca="Tp-link", equipo="Router/Switch", desc="El switch fa fum."),
        inc("19", desc="L'ordinador s'encén, però el sistema operatiu no arriba a iniciar-se."),
        inc("20", marca=None, desc="La pantalla del portàtil Lenovo parpelleja."),
        inc("21", desc="Los manatíes, conocidos como vacas marinas, son mamíferos acuáticos que "
                       "habitan en aguas costeras poco profundas y se desplazan con gran "
                       "lentitud mientras se alimentan de plantas acuáticas y algas."),
    ])
    return analizar_archivo(ruta, hoy=HOY, reglas=reglas)


# ══════════════════════════════════════════════════════════════════════════
# Sin navegador
# ══════════════════════════════════════════════════════════════════════════

def test_html_autocontenido(casos, reglas):
    html = generar_html(casos, reglas, AHORA, HOY, PINES)
    assert html.startswith("<!doctype html>")
    assert "{{" not in html                                   # Ninguna marca sin sustituir
    assert "Actualizado: 19/11/2026 10:30" in html
    assert "21 registros procesados" in html
    assert 'name="viewport"' in html
    # Sin recursos locales: solo Chart.js por CDN (GitHub Pages sin rutas rotas)
    externos = re.findall(r'(?:src|href)="([^"#]+)"', html)
    assert all(u.startswith(("https://", "data:")) for u in externos), externos


def test_datos_embebidos_coinciden(casos, reglas):
    carga = _carga(generar_html(casos, reglas, AHORA, HOY, PINES))
    assert carga["meta"]["total"] == 21
    assert carga["meta"]["validas"] == casos.resumen.validas
    S = carga["S"]
    validas = [S[r[0]] for r in carga["I"] if r[1]]
    assert validas == [i.id for i in casos.validas]
    dos = next(r for r in carga["I"] if S[r[0]] == "2")
    assert S[dos[7]] == "2026-05-09"                          # Fecha ya reparada
    assert len(dos[17]) == 3                                  # 3 reparaciones


def test_el_xml_no_puede_cerrar_el_script(tmp_path, reglas):
    ruta = escribir_xml(tmp_path / "x.xml", [inc("1", desc="No funciona </script><script>alert(1)</script>")])
    html = generar_html(analizar_archivo(ruta, hoy=HOY, reglas=reglas), reglas, AHORA, HOY, PINES)
    bloque = re.search(r'id="datos">(.*?)</script>', html, re.S).group(1)
    assert "<" not in bloque                                  # Todo «<» va como <
    assert "</script><script>alert(1)" in json.dumps(_carga(html), ensure_ascii=False)


def test_valores_gigantes_se_recortan(tmp_path, reglas):
    ruta = escribir_xml(tmp_path / "x.xml", [inc("1", desc="No funciona " + "a" * 5000)])
    carga = datos_embebidos(analizar_archivo(ruta, hoy=HOY, reglas=reglas), reglas, AHORA, HOY, PINES)
    assert max(len(t) for t in carga["S"]) < 700


def test_main_html_genera_index(tmp_path):
    xml = escribir_xml(tmp_path / "respotes.xml", [inc("1"), inc("2", desc="Peso conocer presenta.")])
    salida = tmp_path / "web" / "index.html"
    salida.parent.mkdir()
    proceso = subprocess.run(["python3", str(RAIZ / "main.py"), "--html", "--file", str(xml),
                              "--salida", str(salida)], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "PIN_CONSULTA": "2468", "PIN_TECNICO": "13579"})
    assert proceso.returncode == 0, proceso.stderr
    assert _carga(salida.read_text(encoding="utf-8"))["meta"]["validas"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Con navegador: arranque y paridad JS ↔ Python
# ══════════════════════════════════════════════════════════════════════════

ARNES = r"""
<script>
(() => {
  const res = {};
  try {
    const xml = JSON.parse(document.getElementById("xml-prueba").textContent);
    const D = JSON.parse(document.getElementById("datos").textContent);
    const py = window.Dashboard.ST.publicados;
    const js = Motor.analizarXML(xml, D.meta.hoy);
    const igual = (a, b) => {
      if (typeof a === "string" && a.includes("… [recortado:")) return String(b).startsWith(a.split("… [recortado:")[0]);
      return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    };
    const difs = [];
    const claves = ["id", "valida", "sev", "inferida", "cat", "marca", "equipo", "fecha", "desc", "criterio",
                    "regla", "oTipo", "oMarca", "notaInfra", "zona", "codigo"];
    py.forEach((p, i) => {
      const j = js[i] || {};
      for (const k of claves) if (!igual(p[k], j[k])) difs.push([p.id, k, p[k], j[k]]);
      const an = (l) => (l || []).map((a) => [a.cat, a.regla, a.campo, a.motivo, a.extra, a.valor]);
      an(p.anom).forEach((a, x) => a.forEach((v, y) => { if (!igual(v, (an(j.anom)[x] || [])[y])) difs.push([p.id, "anom" + x + "." + y, v, (an(j.anom)[x] || [])[y]]); }));
      if (an(p.anom).length !== an(j.anom).length) difs.push([p.id, "n_anom", p.anom.length, (j.anom || []).length]);
      const rp = (l) => (l || []).map((r) => [r.campo, r.antes, r.despues, r.motivo]);
      if (rp(p.rep).length !== rp(j.rep).length) difs.push([p.id, "n_rep", p.rep.length, (j.rep || []).length]);
      rp(p.rep).forEach((r, x) => r.forEach((v, y) => { const w = (rp(j.rep)[x] || [])[y]; if (!igual(v, w)) difs.push([p.id, "rep" + x + "." + y, v, w]); }));
      p.campos.forEach(([n, v], x) => { const c = (j.campos || [])[x] || []; if (n !== c[0] || !igual(v, c[1])) difs.push([p.id, "campo " + n, v, c[1]]); });
    });
    Object.assign(res, { py: py.length, js: js.length, total: difs.length, difs: difs.slice(0, 15) });
  } catch (e) { res.error = String(e && e.stack || e); }
  const pre = document.createElement("pre");
  pre.id = "resultado";
  pre.textContent = JSON.stringify(res);
  document.body.append(pre);
})();
</script>
"""


def _ejecutar(html: str, tmp_path: Path, xml: str) -> str:
    extra = ('<script type="application/json" id="xml-prueba">'
             + json.dumps(xml).replace("<", "\\u003c") + "</script>" + ARNES)
    pagina = tmp_path / "prueba.html"
    pagina.write_text(html.replace("</body>", extra + "</body>"), encoding="utf-8")
    proceso = subprocess.run(
        [NAVEGADOR, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={tmp_path / 'perfil'}", "--virtual-time-budget=30000",
         "--dump-dom", pagina.as_uri()],
        capture_output=True, text=True, timeout=180)
    return proceso.stdout


def _paridad(html: str, tmp_path: Path, xml: str) -> dict:
    dom = _ejecutar(html, tmp_path, xml)
    assert 'data-listo="1"' in dom, "el dashboard no ha arrancado (error de JavaScript)"
    m = re.search(r'<pre id="resultado">(.*?)</pre>', dom, re.S)
    assert m, "el arnés no ha escrito resultados"
    import html as html_mod
    return json.loads(html_mod.unescape(m.group(1)))


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
def test_paridad_motor_js_casos_dificiles(casos, reglas, tmp_path):
    xml = casos.ruta.read_text(encoding="utf-8")
    res = _paridad(generar_html(casos, reglas, AHORA, HOY, PINES), tmp_path, xml)
    assert "error" not in res, res.get("error")
    assert res["py"] == res["js"] == 21
    assert res["total"] == 0, res["difs"]


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
@pytest.mark.skipif(not (RAIZ / "incidencies.xml").exists(), reason="sin el XML real")
def test_paridad_motor_js_xml_real(reglas, tmp_path):
    ruta = RAIZ / "incidencies.xml"
    datos = analizar_archivo(ruta, hoy=HOY, reglas=reglas)
    res = _paridad(generar_html(datos, reglas, AHORA, HOY, PINES), tmp_path, ruta.read_text(encoding="utf-8"))
    assert "error" not in res, res.get("error")
    assert res["py"] == res["js"] == datos.resumen.total
    assert res["total"] == 0, res["difs"]


# ══════════════════════════════════════════════════════════════════════════
# Pantalla de PIN del index.html
# ══════════════════════════════════════════════════════════════════════════

def test_index_sin_pins_en_claro(casos, reglas):
    html = generar_html(casos, reglas, AHORA, HOY, {"consulta": "4826", "tecnico": "97531"})
    acceso = _carga(html)["acceso"]
    sin_huellas = re.sub(r"[0-9a-f]{32,}", "", html)            # (una huella podría contenerlo)
    assert "4826" not in sin_huellas and "97531" not in sin_huellas   # Nunca el PIN en claro
    huellas = {rol: h for h, rol in acceso["huellas"]}
    assert huellas["Consultor"] == hashlib.sha256(f"{acceso['sal']}:4826".encode()).hexdigest()
    assert huellas["Técnico"] == hashlib.sha256(f"{acceso['sal']}:97531".encode()).hexdigest()
    assert '<body class="bloqueado">' in html and "<main inert>" in html


ARNES_PIN = r"""
<script>
(() => {
  const r = {};
  const enviar = (pin) => { document.getElementById("acceso-pin").value = pin;
                            document.getElementById("acceso-form").requestSubmit(); };
  r.sha = window.Acceso.sha256("sal:PIN ñ€ " + "x".repeat(80));
  r.alAbrir = document.body.classList.contains("bloqueado");
  enviar("0000");
  r.trasFallo = document.body.classList.contains("bloqueado");
  r.error = document.getElementById("acceso-error").textContent;
  enviar("1234");
  r.trasAcierto = document.body.classList.contains("bloqueado");
  r.rol = document.documentElement.dataset.rol;
  document.getElementById("cerrar-sesion").click();
  r.trasCerrar = document.body.classList.contains("bloqueado");
  const pre = document.createElement("pre"); pre.id = "resultado-pin";
  pre.textContent = JSON.stringify(r); document.body.append(pre);
})();
</script>
"""


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
def test_pantalla_pin_en_el_navegador(casos, reglas, tmp_path):
    html = generar_html(casos, reglas, AHORA, HOY, PINES)
    pagina = tmp_path / "pin.html"
    pagina.write_text(html.replace("</body>", ARNES_PIN + "</body>"), encoding="utf-8")
    dom = subprocess.run(
        [NAVEGADOR, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={tmp_path / 'perfil'}", "--virtual-time-budget=20000",
         "--dump-dom", pagina.as_uri()], capture_output=True, text=True, timeout=180).stdout
    m = re.search(r'<pre id="resultado-pin">(.*?)</pre>', dom, re.S)
    assert m, "el arnés del PIN no ha escrito resultados"
    import html as html_mod
    r = json.loads(html_mod.unescape(m.group(1)))
    assert r["sha"] == hashlib.sha256(("sal:PIN ñ€ " + "x" * 80).encode()).hexdigest()
    assert r["alAbrir"] and r["trasFallo"] and r["error"] == "PIN incorrecto."
    assert not r["trasAcierto"] and r["rol"] == "Consultor"
    assert r["trasCerrar"]
