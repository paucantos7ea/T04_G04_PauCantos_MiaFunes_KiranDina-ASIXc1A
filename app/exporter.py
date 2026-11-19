# -*- coding: utf-8 -*-
"""Exportaciones sin interfaz: JSON de válidas, XML limpio, CSV de cuarentena e
informe ejecutivo (informe_estado.html)."""

from __future__ import annotations

import csv
import html
import io
import json
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import (ETIQUETA_CAMPO, ETIQUETA_INCIDENCIA, ETIQUETA_RAIZ, NIVELES,
                        SLA_HORAS)
from app.models import ErrorExportacion, Incidencia

if TYPE_CHECKING:                       # Solo para anotaciones: sin importaciones circulares
    from app.analytics import Analizador


def registros_json(validas: list[Incidencia]) -> list[dict[str, str]]:
    """Cada incidencia como {"id": ..., "<camp nom>": "<valor>", ...}.

    Los campos opcionales que venían vacíos (p. ej. la marca) se guardan como
    "" para que todos los registros tengan las mismas claves.
    """
    registros = []
    for inc in validas:
        registro = {"id": inc.id, **inc.campos}
        registro.update({nombre: "" for nombre in inc.vacios})
        registros.append(registro)
    return registros


def escribir_json(ruta: Path, datos: list[Any]) -> None:
    """Escribe primero en un .tmp y después lo renombra (escritura atómica).

    Si la escritura falla a mitad, el JSON anterior queda intacto. Los OSError
    (permisos, disco lleno...) se propagan para que la interfaz los muestre.
    """
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8", newline="\n") as fichero:
            json.dump(datos, fichero, ensure_ascii=False, indent=4)
        temporal.replace(ruta)              # Atómico en Windows, Linux y macOS
    except OSError:
        temporal.unlink(missing_ok=True)    # No dejar un .tmp huérfano
        raise


def leer_json_existente(ruta: Path) -> list[Any]:
    """Lista guardada en el archivo, o ErrorExportacion si no se puede usar."""
    try:
        with ruta.open(encoding="utf-8") as fichero:
            datos = json.load(fichero)
    except json.JSONDecodeError as error:
        raise ErrorExportacion(f"El fitxer existent no és un JSON vàlid ({error}).") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorExportacion(f"No es pot llegir el fitxer existent ({error}).") from None
    if not isinstance(datos, list):
        raise ErrorExportacion("El fitxer existent no conté una llista d'incidències.")
    return datos


def fusionar(existentes: list[Any], nuevos: list[dict[str, str]]) -> tuple[list[Any], int]:
    """Añade a `existentes` los registros cuyo id aún no está. Devuelve (lista, añadidos)."""
    ids = {str(item.get("id")) for item in existentes if isinstance(item, dict)}
    anadidos = 0
    for registro in nuevos:
        if str(registro["id"]) not in ids:
            existentes.append(registro)
            ids.add(str(registro["id"]))
            anadidos += 1
    return existentes, anadidos


# ══════════════════════════════════════════════════════════════════════════
# XML limpio y cuarentena
# ══════════════════════════════════════════════════════════════════════════

NOMBRE_XML_LIMPIO = "respotes_limpio.xml"
NOMBRE_CUARENTENA = "cuarentena.csv"
COLUMNAS_CUARENTENA = ["id", "tipo_anomalia", "campo_afectado", "regla", "motivo",
                       "valor_detectado", "auto_reparada"]


def xml_limpio(validas: list[Incidencia]) -> bytes:
    """respotes_limpio.xml: misma estructura que el original, solo con las
    incidencias VÁLIDAS y con los valores ya auto-reparados.

        <incidencies>
          <incidencia id="...">
            <camp nom="...">valor</camp>   (o <camp nom="..." /> si venía vacío)
    """
    raiz = ET.Element(ETIQUETA_RAIZ)
    for inc in validas:
        if not inc.valida:                    # Defensa: nunca se cuela una bloqueada
            continue
        nodo = ET.SubElement(raiz, ETIQUETA_INCIDENCIA, id=inc.id)
        for nombre in inc.orden or [*inc.campos, *inc.vacios]:
            camp = ET.SubElement(nodo, ETIQUETA_CAMPO, nom=nombre)
            if valor := inc.campos.get(nombre):
                camp.text = valor
    ET.indent(raiz, space="  ")
    return ET.tostring(raiz, encoding="utf-8", xml_declaration=True) + b"\n"


def cuarentena_csv(anomalas: list[Incidencia]) -> bytes:
    """cuarentena.csv: una fila por regla incumplida (id, campo y motivo exacto).

    Codificado en UTF-8 con BOM para que Excel muestre bien las tildes.
    """
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida)
    escritor.writerow(COLUMNAS_CUARENTENA)
    for inc in anomalas:
        for a in inc.anomalias:
            escritor.writerow([inc.id, a.tipo, a.campo, a.regla, a.motivo_detallado,
                               " ".join(a.valor.split())[:500],
                               "sí" if inc.auto_reparada else "no"])
    return salida.getvalue().encode("utf-8-sig")


# ══════════════════════════════════════════════════════════════════════════
# Informe ejecutivo (informe_estado.html)
# ══════════════════════════════════════════════════════════════════════════

NOMBRE_INFORME = "informe_estado.html"
COLOR_NIVEL_INFORME = {"Crítica": "#d13438", "Alta": "#e8590c", "Media": "#d4a106",
                       "Leve": "#2f74d0"}

_CSS_INFORME = """
:root { --texto:#1b1f27; --suave:#5d6573; --borde:#e1e4ea; --fondo:#f6f7f9; --acento:#3e63dd; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color:var(--texto); background:var(--fondo); }
.hoja { max-width:960px; margin:24px auto; background:#fff; padding:40px 48px;
  border:1px solid var(--borde); border-radius:14px; }
header { display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap;
  border-bottom:3px solid var(--acento); padding-bottom:14px; margin-bottom:20px; }
h1 { font-size:1.6rem; margin:0; }
h2 { font-size:1.08rem; margin:28px 0 10px; padding-bottom:4px; border-bottom:1px solid var(--borde); }
.emision { color:var(--suave); font-size:.88rem; text-align:right; }
.resumen { background:#eef2ff; border-left:4px solid var(--acento); padding:12px 16px;
  border-radius:8px; }
.resumen p { margin:.3rem 0; }
.kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.kpi { border:1px solid var(--borde); border-top:4px solid var(--c); border-radius:10px; padding:10px 12px; }
.kpi .e { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:var(--suave); }
.kpi .v { font-size:1.6rem; font-weight:700; line-height:1.2; }
.kpi .s { font-size:.8rem; color:var(--suave); }
table { width:100%; border-collapse:collapse; font-size:.88rem; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--borde); vertical-align:top; }
th { font-size:.74rem; text-transform:uppercase; letter-spacing:.04em; color:var(--suave); }
td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.barra { height:10px; border-radius:5px; background:var(--c); min-width:2px; }
.pista { background:#eef0f4; border-radius:5px; }
.etiqueta { display:inline-block; padding:0 8px; border-radius:999px; color:#fff; font-size:.76rem;
  font-weight:600; background:var(--c); }
.alerta { color:#b42318; font-weight:600; }
.nota { color:var(--suave); font-size:.8rem; }
footer { margin-top:28px; color:var(--suave); font-size:.78rem; border-top:1px solid var(--borde); padding-top:10px; }
@media (max-width:700px) { .hoja { padding:20px 16px; margin:0; border-radius:0; }
  .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@page { size:A4; margin:14mm; }
@media print {
  body { background:#fff; font-size:11pt; }
  .hoja { margin:0; padding:0; border:0; max-width:none; }
  h2 { break-after:avoid; }
  table, .kpis, .resumen { break-inside:avoid; }
  tr { break-inside:avoid; }
  * { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
}
"""


def _e(texto: object) -> str:
    return html.escape(str(texto), quote=True)


def _n(valor: int | float) -> str:
    return f"{valor:,}".replace(",", ".")


def _pct(parte: int, total: int) -> str:
    return f"{parte / total * 100:.1f} %".replace(".", ",") if total else "—"


def informe_estado(datos: "Analizador", seguimiento: Mapping[str, Any] | None = None,
                   ahora: datetime | None = None, tormentas: list | None = None,
                   duplicados: list | None = None) -> str:
    """informe_estado.html completo: autocontenido (sin JavaScript ni recursos
    externos) y preparado para imprimir o guardar como PDF (@media print).

    `seguimiento` = {id: EstadoReparacion} de gestion.json. Las tormentas y los
    duplicados se calculan aquí si no se pasan ya calculados.
    """
    from app.analytics import (calcular_mttr, detectar_duplicados, detectar_tormentas,
                               formato_duracion, fuera_de_sla, unicas_estimadas, zona_de)

    seguimiento = seguimiento or {}
    ahora = ahora or datetime.now()
    r = datos.resumen
    validas = datos.validas
    tormentas = detectar_tormentas(validas) if tormentas is None else tormentas
    duplicados = detectar_duplicados(validas) if duplicados is None else duplicados
    mttr = calcular_mttr(validas, seguimiento)
    alertas = fuera_de_sla(validas, seguimiento, ahora)
    estados = Counter((g.estado if (g := seguimiento.get(i.id)) else "Pendiente") for i in validas)
    resueltas = estados.get("Resuelta", 0)
    activas = [t for t in tormentas
               if any(getattr(seguimiento.get(i), "estado", "Pendiente") != "Resuelta"
                      for i in t.ids)]
    unicas = unicas_estimadas(len(validas), tormentas, duplicados)

    zonas = Counter(zona_de(i) or "Sin zona" for i in validas)
    graves = Counter(zona_de(i) or "Sin zona" for i in validas if i.severidad in ("Crítica", "Alta"))
    ranking = zonas.most_common(8)
    maximo = ranking[0][1] if ranking else 1

    # ── Resumen ejecutivo en lenguaje claro ─────────────────────────────
    frases = [f"Se han procesado <b>{_n(r.total)}</b> registros del archivo "
              f"<b>{_e(datos.ruta.name)}</b>: <b>{_n(r.validas)}</b> son incidencias válidas "
              f"({_pct(r.validas, r.total)}) y <b>{_n(r.anomalas)}</b> se han bloqueado como "
              f"basura o datos imposibles ({_pct(r.anomalas, r.total)})."]
    if ranking:
        zona, n = ranking[0]
        frases.append(f"La ubicación más afectada es <b>{_e(zona)}</b>, con {_n(n)} incidencias "
                      f"({_pct(n, len(validas))} de las válidas).")
    criticas, altas = r.por_severidad.get("Crítica", 0), r.por_severidad.get("Alta", 0)
    frases.append(f"Hay <b>{_n(criticas)}</b> incidencias críticas y <b>{_n(altas)}</b> altas; "
                  + (f"<span class='alerta'>{_n(len(alertas))} superan su SLA sin resolverse"
                     "</span>." if alertas else "ninguna supera su SLA."))
    if tormentas or duplicados:
        frases.append(f"Se detectan <b>{_n(len(tormentas))}</b> tormentas de incidencias "
                      f"({_n(len(activas))} sin resolver del todo) y <b>{_n(len(duplicados))}"
                      f"</b> grupos de tickets duplicados: descontándolos, las válidas equivalen "
                      f"a unos <b>{_n(unicas)}</b> fallos distintos.")
    frases.append(f"Reparaciones: {_n(resueltas)} resueltas de {_n(len(validas))} "
                  f"({_pct(resueltas, len(validas))}); tiempo medio de resolución (MTTR): "
                  f"<b>{formato_duracion(mttr.minutos)}</b>"
                  + (f" sobre {_n(mttr.resueltas)} resueltas con tiempo medido." if mttr.resueltas
                     else " (aún no hay reparaciones con tiempo medido)."))

    def kpi(etiqueta: str, valor: str, sub: str, color: str) -> str:
        return (f'<div class="kpi" style="--c:{color}"><div class="e">{etiqueta}</div>'
                f'<div class="v">{valor}</div><div class="s">{sub}</div></div>')

    kpis = (kpi("Total procesadas", _n(r.total), _e(datos.ruta.name), "#3e63dd")
            + kpi("% Válidas", _pct(r.validas, r.total), f"{_n(r.validas)} incidencias", "#30a46c")
            + kpi("% Basura bloqueada", _pct(r.anomalas, r.total), f"{_n(r.anomalas)} registros",
                  "#e5484d")
            + kpi("MTTR", formato_duracion(mttr.minutos),
                  f"{_n(mttr.resueltas)} resueltas medidas", "#8e4ec6"))

    filas_zonas = "".join(
        f"<tr><td>{_e(z)}</td><td class='n'>{_n(n)}</td><td class='n'>{_pct(n, len(validas))}</td>"
        f"<td class='n'>{_n(graves.get(z, 0))}</td><td style='width:38%'><div class='pista'>"
        f"<div class='barra' style='--c:#3e63dd;width:{n / maximo * 100:.1f}%'></div></div></td></tr>"
        for z, n in ranking)

    total_sev = sum(r.por_severidad.values()) or 1
    filas_sev = "".join(
        f"<tr><td><span class='etiqueta' style='--c:{COLOR_NIVEL_INFORME[n]}'>{n}</span></td>"
        f"<td class='n'>{_n(r.por_severidad.get(n, 0))}</td>"
        f"<td class='n'>{_pct(r.por_severidad.get(n, 0), total_sev)}</td>"
        f"<td class='n'>{formato_duracion(mttr.por_severidad[n][0]) if n in mttr.por_severidad else '—'}</td>"
        f"<td class='n'>{f'{SLA_HORAS[n]} h' if n in SLA_HORAS else '—'}</td>"
        f"<td class='n'>{_n(sum(1 for a in alertas if a.severidad == n)) if n in SLA_HORAS else '—'}</td></tr>"
        for n in NIVELES)

    filas_tormentas = "".join(
        f"<tr><td>{_e(t.zona)}</td><td>{t.desde:%d/%m/%Y}"
        f"{'' if t.hasta == t.desde else f' – {t.hasta:%d/%m/%Y}'}</td><td>{_e(t.categoria)}</td>"
        f"<td>{_e(t.sintoma)}</td><td class='n'>{t.n}</td></tr>" for t in tormentas[:10])
    filas_dup = "".join(
        f"<tr><td>{_e(g.equipo)}</td><td>{_e(g.zona or '—')}</td><td>#{_e(g.original)}</td>"
        f"<td>{', '.join('#' + _e(i) for i in g.duplicados)}</td>"
        f"<td class='n'>{g.similitud * 100:.0f} %</td></tr>" for g in duplicados[:10])
    filas_sla = "".join(
        f"<tr><td>#{_e(a.id)}</td><td><span class='etiqueta' style='--c:"
        f"{COLOR_NIVEL_INFORME[a.severidad]}'>{a.severidad}</span></td><td>{_e(a.estado)}</td>"
        f"<td>{_e(a.zona or '—')}</td><td>{_e(a.descripcion[:90])}</td>"
        f"<td class='n alerta'>{formato_duracion(a.horas_abierta * 60)}</td></tr>"
        for a in alertas[:10])

    def mas(lista: list, mostrados: int = 10) -> str:
        return (f"<p class='nota'>… y {_n(len(lista) - mostrados)} más (ver la web).</p>"
                if len(lista) > mostrados else "")

    seccion_masivas = (
        f"<table><thead><tr><th>Planta / oficina</th><th>Fecha</th><th>Categoría</th>"
        f"<th>Síntoma principal</th><th>Incid.</th></tr></thead><tbody>{filas_tormentas}"
        f"</tbody></table>{mas(tormentas)}" if tormentas
        else "<p>No se detectan tormentas de incidencias.</p>")
    seccion_dup = (
        f"<table><thead><tr><th>Equipo</th><th>Planta / oficina</th><th>Original</th>"
        f"<th>Duplicados</th><th>Similitud</th></tr></thead><tbody>{filas_dup}</tbody></table>"
        f"{mas(duplicados)}" if duplicados else "<p>No se detectan tickets duplicados.</p>")
    seccion_sla = (
        f"<table><thead><tr><th>ID</th><th>Severidad</th><th>Estado</th><th>Planta / oficina</th>"
        f"<th>Descripción</th><th>Abierta</th></tr></thead><tbody>{filas_sla}</tbody></table>"
        f"{mas(alertas)}" if alertas else "<p>Ningún ticket crítico o alto supera su SLA.</p>")

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe de estado · {ahora:%d/%m/%Y}</title>
<style>{_CSS_INFORME}</style>
</head>
<body>
<main class="hoja">
<header>
  <div><h1>Informe ejecutivo de incidencias</h1>
  <div class="nota">Monitor XML de incidencias · fuente: {_e(datos.ruta.name)}</div></div>
  <div class="emision">Emitido el<br><b>{ahora:%d/%m/%Y}</b> a las <b>{ahora:%H:%M}</b></div>
</header>

<h2>Resumen ejecutivo</h2>
<div class="resumen">{"".join(f"<p>{f}</p>" for f in frases)}</div>

<h2>Indicadores clave</h2>
<div class="kpis">{kpis}</div>

<h2>Plantas y oficinas más afectadas</h2>
<table><thead><tr><th>Planta / oficina</th><th>Incid.</th><th>% válidas</th>
<th>Críticas + altas</th><th></th></tr></thead><tbody>{filas_zonas}</tbody></table>

<h2>Desglose por severidad</h2>
<table><thead><tr><th>Severidad</th><th>Incid.</th><th>%</th><th>MTTR</th><th>SLA</th>
<th>Fuera de SLA</th></tr></thead><tbody>{filas_sev}</tbody></table>

<h2>Tormentas de incidencias (incidencias masivas)</h2>
<p class="nota">≥ 3 incidencias de la misma categoría en la misma planta u oficina el mismo día.</p>
{seccion_masivas}

<h2>Tickets duplicados</h2>
<p class="nota">Mismo equipo, fechas cercanas y descripción con similitud ≥ 75 %.</p>
{seccion_dup}

<h2>Tickets críticos y altos fuera de SLA</h2>
{seccion_sla}

<footer>Informe generado automáticamente a partir del XML y de gestion.json. Para guardarlo
como PDF: Imprimir → «Guardar como PDF».</footer>
</main>
</body>
</html>
"""
