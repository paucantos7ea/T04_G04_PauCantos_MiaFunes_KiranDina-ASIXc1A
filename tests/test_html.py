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
import sys
from datetime import datetime
from pathlib import Path

import pytest
from conftest import HOY, RAIZ, escribir_xml, inc

from app.analytics import analizar_archivo
from app.html_builder import datos_embebidos, generar_html

_RUTAS_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
NAVEGADOR = next(
    (r for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
     if (r := shutil.which(n))),
    next((p for p in _RUTAS_CHROME if Path(p).is_file()), None),
)
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
    # Estructura en 6 acordeones + navegación rápida + controles de expansión
    for id_acc in ("acc-validez", "acc-evolucion", "acc-masivas", "acc-explorador", "acc-anomalias", "acc-reglas"):
        assert f'id="{id_acc}"' in html
    assert 'id="salto-seccion"' in html
    assert 'id="menu-descargas"' in html and 'id="descargar-json"' in html
    assert 'id="descargar-cuarentena"' in html
    assert 'id="btn-expandir-todo"' in html and 'id="btn-contraer-todo"' in html
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
    proceso = subprocess.run([sys.executable, str(RAIZ / "main.py"), "--html", "--file", str(xml),
                              "--salida", str(salida)], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, encoding="utf-8", timeout=120,
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
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
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
         "--dump-dom", pagina.as_uri()], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180).stdout
    m = re.search(r'<pre id="resultado-pin">(.*?)</pre>', dom, re.S)
    assert m, "el arnés del PIN no ha escrito resultados"
    import html as html_mod
    r = json.loads(html_mod.unescape(m.group(1)))
    assert r["sha"] == hashlib.sha256(("sal:PIN ñ€ " + "x" * 80).encode()).hexdigest()
    assert r["alAbrir"] and r["trasFallo"] and r["error"] == "PIN incorrecto."
    assert not r["trasAcierto"] and r["rol"] == "Consultor"
    assert r["trasCerrar"]


# ══════════════════════════════════════════════════════════════════════════
# Masivas, duplicados, SLA e informe en el dashboard estático
# ══════════════════════════════════════════════════════════════════════════

def test_index_lleva_informe_y_configuracion(casos, reglas):
    carga = _carga(generar_html(casos, reglas, AHORA, HOY, PINES))
    assert "@media print" in carga["informeCss"]                  # El informe se genera en el navegador
    assert carga["config"]["reglasFabrica"]["anyos"]["minimo"] == 2000
    assert carga["emergentes"] == [] or len(carga["emergentes"][0]) == 4
    assert carga["config"]["sla"] == {"Crítica": 4, "Alta": 24}
    assert carga["config"]["masivas"]["umbral"] == 0.75


PARES_SIMILITUD = [["No arrenca l'ordinador", "L'ordinador no arrenca"], ["abc", "abd"],
                   ["La impressora no imprimeix res", "La impressora no imprimeix res!!"],
                   ["Àéî ÕÜ ñ 😀 x", "aei ou n 😀 y"], ["", "algo"], ["aaaa bbbb aaaa", "bbbb aaaa bbbb"]]

ARNES_OPERACIONES = r"""
<script>
(() => {
  const r = {};
  try {
    const regs = window.Dashboard.ST.publicados;
    const N = ["Crítica", "Alta", "Media", "Leve"];
    r.torm = Operaciones.tormentas(regs, 3, 0, N).map((t) => [t.zona, t.categoria, t.desde, t.hasta, t.sintoma, t.ids, t.severidad]);
    r.torm1 = Operaciones.tormentas(regs, 3, 1, N).map((t) => t.ids);
    r.dups = Operaciones.duplicados(regs, 0.75, 3).map((g) => [g.equipo, g.zona, g.ids, g.similitud]);
    r.sim = JSON.parse(document.getElementById("pares").textContent).map(([a, b]) => Operaciones.similitud(a, b));
    r.sla = Operaciones.fueraDeSla(regs, {"Crítica": 4, "Alta": 24}, N, new Date(2026, 10, 19, 10, 30)).map((a) => [a.r.id, Math.round(a.horas * 1000) / 1000]);
  } catch (e) { r.error = String(e && e.stack || e); }
  const pre = document.createElement("pre"); pre.id = "resultado-op";
  pre.textContent = JSON.stringify(r); document.body.append(pre);
})();
</script>
"""


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
@pytest.mark.skipif(not (RAIZ / "incidencies.xml").exists(), reason="sin el XML real")
def test_paridad_masivas_duplicados_sla(reglas, tmp_path):
    from app.analytics import detectar_duplicados, detectar_tormentas, fuera_de_sla, similitud
    datos = analizar_archivo(RAIZ / "incidencies.xml", hoy=HOY, reglas=reglas)
    html = generar_html(datos, reglas, AHORA, HOY, PINES)
    extra = ('<script type="application/json" id="pares">'
             + json.dumps(PARES_SIMILITUD).replace("<", "\\u003c") + "</script>" + ARNES_OPERACIONES)
    pagina = tmp_path / "op.html"
    pagina.write_text(html.replace("</body>", extra + "</body>"), encoding="utf-8")
    dom = subprocess.run(
        [NAVEGADOR, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={tmp_path / 'perfil'}", "--virtual-time-budget=60000",
         "--dump-dom", pagina.as_uri()], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300).stdout
    m = re.search(r'<pre id="resultado-op">(.*?)</pre>', dom, re.S)
    assert m, "el arnés de operaciones no ha escrito resultados"
    import html as html_mod
    r = json.loads(html_mod.unescape(m.group(1)))
    assert "error" not in r, r.get("error")

    torm = [[t.zona, t.categoria, t.desde.isoformat(), t.hasta.isoformat(), t.sintoma, t.ids,
             t.severidad] for t in detectar_tormentas(datos.todas)]
    assert torm and r["torm"] == torm
    assert r["torm1"] == [t.ids for t in detectar_tormentas(datos.todas, ventana_dias=1)]
    dups = detectar_duplicados(datos.todas)
    assert dups and [d[:3] for d in r["dups"]] == [[g.equipo, g.zona, g.ids] for g in dups]
    assert [round(d[3], 3) for d in r["dups"]] == [g.similitud for g in dups]
    assert r["sim"] == pytest.approx([similitud(a, b) for a, b in PARES_SIMILITUD], abs=1e-12)
    sla = fuera_de_sla(datos.todas, {}, AHORA)
    assert sla and [x[0] for x in r["sla"]] == [a.id for a in sla]
    assert [x[1] for x in r["sla"]] == pytest.approx([a.horas_abierta for a in sla], abs=1e-3)



# ══════════════════════════════════════════════════════════════════════════
# Modo Técnico del dashboard estático
# ══════════════════════════════════════════════════════════════════════════

ARNES_TECNICO = r"""
<script>
(async () => {
  const r = {};
  const enviar = (pin) => { document.getElementById("acceso-pin").value = pin;
                            document.getElementById("acceso-form").requestSubmit(); };
  try {
    enviar("1234");
    r.consultor = { auditoria: !document.getElementById("pestana-auditoria").hidden,
                    editor: !!document.getElementById("form-reglas") };
    document.getElementById("cerrar-sesion").click();
    enviar("12345");
    r.tecnico = { auditoria: !document.getElementById("pestana-auditoria").hidden,
                  editor: !!document.getElementById("form-reglas") };
    const D = JSON.parse(document.getElementById("datos").textContent);
    const mod = JSON.parse(document.getElementById("reglas-mod").textContent);
    r.validadas = Tecnico.validarReglas(mod, D.config.reglasFabrica);
    try { Tecnico.validarReglas({ anyos: { minimo: 2020, maximo: 2010 } }, D.config.reglasFabrica); r.errorAnyos = null; }
    catch (e) { r.errorAnyos = e.message; }
    await window.Dashboard.aplicarReglas(mod);
    r.analisis = window.Dashboard.ST.todos.map((x) => [x.id, x.valida, x.sev, x.criterio, x.regla, x.cat, x.marca]);
    r.locales = window.Dashboard.ST.reglasLocales;
    const t0 = new Date(2026, 10, 19, 9, 0, 0);
    Tecnico.actualizarSeguimiento("1", "En curso", "", D.config.estadosGestion, t0);
    const fin = Tecnico.actualizarSeguimiento("1", "Resuelta", "Cable cambiado", D.config.estadosGestion, new Date(t0.getTime() + 95 * 60000));
    r.seg = fin.registro;
    r.mttr = Tecnico.mttr(window.Dashboard.ST.todos, Tecnico.seguimiento(), D.config.niveles);
    r.audit = Tecnico.textoAuditLog().trim().split("\n");
    window.Dashboard.ST.seg = Tecnico.seguimiento();   // (la interfaz lo refresca al guardar)
    r.informe = window.Dashboard.informeHtml();
  } catch (e) { r.error = String(e && e.stack || e); }
  const pre = document.createElement("pre"); pre.id = "resultado-tec";
  pre.textContent = JSON.stringify(r); document.body.append(pre);
})();
</script>
"""


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
def test_modo_tecnico_en_el_navegador(casos, reglas, tmp_path):
    import copy as copia
    from app.config import REGLAS_POR_DEFECTO
    from app.rules import Reglas, validar_datos
    mod = copia.deepcopy(REGLAS_POR_DEFECTO)
    mod["anyos"]["minimo"] = 2010
    mod["severidad"]["critica_caida"].append("Pantalla   NEGRA")          # Se normaliza
    mod["severidad"]["alta_arranque"] = [p for p in mod["severidad"]["alta_arranque"] if "arrenca" not in p]
    mod["severidad"]["leve_perifericos"].append("teclat")
    mod["severidad"]["critica_caida_general"].append("no funciona")      # «No funciona» -> Crítica
    mod["marcas"]["Nova Marca"] = ["novabrand", "Dell"]
    html = generar_html(casos, reglas, AHORA, HOY, PINES)
    extra = ('<script type="application/json" id="reglas-mod">'
             + json.dumps(mod).replace("<", "\\u003c") + "</script>" + ARNES_TECNICO)
    pagina = tmp_path / "tecnico.html"
    pagina.write_text(html.replace("</body>", extra + "</body>"), encoding="utf-8")
    dom = subprocess.run(
        [NAVEGADOR, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={tmp_path / 'perfil'}", "--virtual-time-budget=30000",
         "--dump-dom", pagina.as_uri()], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180).stdout
    m = re.search(r'<pre id="resultado-tec">(.*?)</pre>', dom, re.S)
    assert m, "el arnés del modo Técnico no ha escrito resultados"
    import html as html_mod
    r = json.loads(html_mod.unescape(m.group(1)))
    assert "error" not in r, r.get("error")

    assert r["consultor"] == {"auditoria": False, "editor": False}
    assert r["tecnico"] == {"auditoria": True, "editor": True}
    assert r["validadas"] == validar_datos(mod)                          # Misma validación
    assert "menor" in r["errorAnyos"]
    # Re-análisis en el navegador con las reglas nuevas = análisis de Python con esas reglas
    py = analizar_archivo(casos.ruta, hoy=HOY, reglas=Reglas.desde_datos(mod))
    esperado = [[i.id, i.valida, i.severidad, i.criterio_severidad, i.regla_severidad, i.tipo, i.marca]
                for i in py.todas]
    assert r["analisis"] == esperado
    assert r["analisis"] != [[i.id, i.valida, i.severidad, i.criterio_severidad, i.regla_severidad,
                              i.tipo, i.marca] for i in casos.todas]       # Las reglas sí cambian algo
    assert r["locales"] is True
    # Seguimiento con marcas de tiempo y MTTR
    assert r["seg"]["fecha_inicio"] == "2026-11-19T09:00:00"
    assert r["seg"]["fecha_resolucion"] == "2026-11-19T10:35:00" and r["seg"]["duracion_minutos"] == 95
    assert r["mttr"]["resueltas"] == 1 and r["mttr"]["minutos"] == 95
    # Auditoría con el formato de audit.log
    linea = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[[^\]]+\] \[[A-Z_]+\] .+$")
    assert all(linea.match(x) for x in r["audit"]), r["audit"]
    acciones = [re.match(r"^\[.*?\] \[(.*?)\] \[(.*?)\]", x).groups() for x in r["audit"]]
    assert acciones[:4] == [("Consultor", "ACCESO"), ("Consultor", "CIERRE_SESION"),
                            ("Técnico", "ACCESO"), ("Técnico", "REGLAS")]
    assert any("año mínimo: 2000 → 2010" in x for x in r["audit"])
    assert any("marca añadida: Nova Marca" in x for x in r["audit"])
    # Informe ejecutivo generado en el navegador
    inf = r["informe"]
    for texto in ("<!doctype html>", "Informe ejecutivo de incidencias", "Resumen ejecutivo", "MTTR",
                  "1 h 35 min", "Plantas y oficinas más afectadas", "Desglose por severidad",
                  "Tormentas de incidencias", "Tickets duplicados", "@media print", "</html>"):
        assert texto in inf, texto
    assert "<script" not in inf


ARNES_ACORDEONES = r"""
<script>
(() => {
  const r = {};
  try {
    document.getElementById("acceso-pin").value = "12345";
    document.getElementById("acceso-form").requestSubmit();
    const accs = [...document.querySelectorAll("details.acordeon")];
    r.total = accs.length;
    r.inicialAbiertos = accs.filter((a) => a.open).length;
    document.getElementById("btn-expandir-todo").click();
    r.trasExpandir = accs.filter((a) => a.open).length;
    document.getElementById("btn-contraer-todo").click();
    r.trasContraer = accs.filter((a) => a.open).length;
    const salto = document.getElementById("salto-seccion");
    salto.value = "acc-anomalias";
    salto.dispatchEvent(new Event("change", { bubbles: true }));
    r.saltoAbrioAnomalias = document.getElementById("acc-anomalias").open;
    r.kpis = document.querySelectorAll("#kpis .kpi").length;
    r.badgeMasivas = document.getElementById("badge-masivas").textContent;
    r.badgeAnomalias = document.getElementById("badge-anomalias").textContent;
    r.anomContador = document.getElementById("anom-contador").textContent;
    r.anomFilas = document.querySelectorAll("#anom-lista tbody tr, #anom-lista .registro").length;
    r.anomCsvCabecera = window.Dashboard.cuarentenaCsvTexto(window.Dashboard.ST.anomFiltradas).split("\r\n")[0];
    r.jsonValidas = JSON.parse(window.Dashboard.incidenciesJsonTexto(window.Dashboard.ST.todos)).length;
    document.querySelector("#anom-lista button[data-ver]").click();
    r.modalAbierto = document.getElementById("modal").open;
  } catch (e) { r.error = String(e && e.stack || e); }
  const pre = document.createElement("pre"); pre.id = "resultado-acc";
  pre.textContent = JSON.stringify(r); document.body.append(pre);
})();
</script>
"""


@pytest.mark.skipif(NAVEGADOR is None, reason="no hay Chromium/Chrome instalado")
def test_acordeones_y_navegacion_en_el_navegador(casos, reglas, tmp_path):
    html = generar_html(casos, reglas, AHORA, HOY, PINES)
    pagina = tmp_path / "acordeones.html"
    pagina.write_text(html.replace("</body>", ARNES_ACORDEONES + "</body>"), encoding="utf-8")
    dom = subprocess.run(
        [NAVEGADOR, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={tmp_path / 'perfil'}", "--virtual-time-budget=20000",
         "--dump-dom", pagina.as_uri()], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180).stdout
    m = re.search(r'<pre id="resultado-acc">(.*?)</pre>', dom, re.S)
    assert m, "el arnés de acordeones no ha escrito resultados"
    import html as html_mod
    r = json.loads(html_mod.unescape(m.group(1)))
    assert "error" not in r, r.get("error")
    assert r["total"] == 6
    assert r["inicialAbiertos"] == 0
    assert r["trasExpandir"] == 6
    assert r["trasContraer"] == 0
    assert r["saltoAbrioAnomalias"] is True
    assert r["kpis"] == 6
    assert r["badgeMasivas"]
    assert "anomalías" in r["badgeAnomalias"]
    assert "Mostrando 1–10 de" in r["anomContador"]
    assert r["anomFilas"] == 10
    assert r["anomCsvCabecera"] == "\ufeffid,tipo_anomalia,campo_afectado,regla,motivo,valor_detectado,auto_reparada"
    assert r["jsonValidas"] == casos.resumen.validas
    assert r["modalAbierto"] is True
