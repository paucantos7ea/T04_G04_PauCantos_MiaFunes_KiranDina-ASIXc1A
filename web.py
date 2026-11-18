#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitor web en tiempo real de incidencias XML (Streamlit + Plotly).

Lanzamiento (desde la carpeta del proyecto):

    python main.py --web                              # muestra las URLs de PC y móvil
    streamlit run web.py --server.address 0.0.0.0     # equivalente directo
    streamlit run web.py --server.address 0.0.0.0 -- --file ruta/al/archivo.xml

Toda la lógica de negocio vive en app/ (parser -> validator -> analytics):
este archivo solo la presenta. Vigila el XML cada 2 s por fecha de
modificación y tamaño, y si lo pilla a medio guardar mantiene el último
estado válido y reintenta en el ciclo siguiente.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

import pandas as pd                      # noqa: E402  (dependencia de streamlit)
import plotly.express as px              # noqa: E402
import plotly.graph_objects as go        # noqa: E402
import streamlit as st                   # noqa: E402

from app.analytics import Analizador, analizar_archivo                        # noqa: E402
from app.config import (ANYO_MINIMO, CAT_BASURA, CAT_DESBORDE, CAT_FECHA,     # noqa: E402
                        CAT_VACIO, MAPA_SEVERIDAD, MARCAS_REALES, MAX_FICHA,
                        MAX_LONGITUD_CORTO, NIVELES, PALABRAS_BASURA, RE_CAMPO_CORTO,
                        REGLAS_SEVERIDAD, SEVERIDAD_POR_DEFECTO,
                        TIPO_ANOMALIA, TIPOS_DISPOSITIVO)
from app.models import ErrorCarga, Incidencia                                 # noqa: E402
from app.utils import normalizar, truncar                                     # noqa: E402
from main import ip_local, localizar_xml                                      # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# Ajustes de la interfaz
# ══════════════════════════════════════════════════════════════════════════

INTERVALO_S = 2                 # Cada cuánto se comprueba el XML
MAX_REINTENTOS = 3              # Reintentos con la MISMA firma antes de esperar un cambio

VALIDA, BLOQUEADA = "Válida", "Bloqueada"
COLOR_NIVEL = {"Crítica": "#e5484d", "Alta": "#f76b15", "Media": "#f5b70a", "Leve": "#3e8ef7"}
EMOJI_NIVEL = {"Crítica": "🔴", "Alta": "🟠", "Media": "🟡", "Leve": "🔵"}
COLOR_RESULTADO = {VALIDA: "#30a46c", TIPO_ANOMALIA[CAT_VACIO]: "#8b8d98",
                   TIPO_ANOMALIA[CAT_FECHA]: "#8e4ec6", TIPO_ANOMALIA[CAT_BASURA]: "#e5484d",
                   TIPO_ANOMALIA[CAT_DESBORDE]: "#f76b15"}
ICONO_PASO = {"ok": "✅", "bloqueo": "⛔", "aviso": "⚠️", "info": "➜"}
PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}

CSS = """
<style>
.block-container {padding-top: 3.2rem; padding-bottom: 3rem;}
.cabecera {display:flex; flex-wrap:wrap; align-items:center; gap:.4rem .8rem; margin-bottom:.2rem;}
.cabecera h1 {font-size:1.7rem; margin:0; padding:0;}
.insignia {display:inline-flex; align-items:center; gap:.45rem; padding:.3rem .75rem;
  border-radius:999px; font-size:.86rem; border:1px solid rgba(127,127,127,.3);
  background:rgba(127,127,127,.08); line-height:1.3;}
.insignia small {opacity:.7;}
.insignia.vivo .icono {animation: latido 1.6s ease-in-out infinite;}
@keyframes latido {0%,100% {opacity:1;} 50% {opacity:.35;}}
.kpis {display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:.75rem; margin:.6rem 0 1rem;}
.kpi {border:1px solid rgba(127,127,127,.25); border-left:5px solid var(--acento);
  border-radius:.7rem; padding:.75rem 1rem; background:rgba(127,127,127,.06);}
.kpi .etiqueta {font-size:.8rem; opacity:.75; text-transform:uppercase; letter-spacing:.04em;}
.kpi .valor {font-size:1.9rem; font-weight:700; line-height:1.15;}
.kpi .sub {font-size:.82rem; opacity:.8;}
.kpi .nuevo {color:#30a46c; font-weight:600;}
@media (max-width: 900px) {.kpis {grid-template-columns:repeat(2, minmax(0,1fr));}}
@media (max-width: 480px) {.kpis {grid-template-columns:1fr;} .cabecera h1 {font-size:1.35rem;}}
.tarjetas {display:grid; grid-template-columns:repeat(auto-fill, minmax(260px,1fr)); gap:.75rem; margin:.4rem 0 1rem;}
.regla {border:1px solid rgba(127,127,127,.25); border-top:4px solid var(--acento);
  border-radius:.7rem; padding:.7rem .9rem; background:rgba(127,127,127,.05);}
.regla .paso {font-size:.75rem; opacity:.7; text-transform:uppercase; letter-spacing:.05em;}
.regla .titulo {font-weight:700; margin:.1rem 0 .25rem;}
.regla .nivel {display:inline-block; padding:.05rem .5rem; border-radius:999px; font-size:.78rem;
  font-weight:600; color:#fff; background:var(--acento);}
.regla p {font-size:.86rem; margin:.35rem 0;}
.regla .cuenta {font-size:.8rem; opacity:.75;}
.chip {display:inline-block; margin:.12rem .15rem 0 0; padding:.05rem .45rem; border-radius:.4rem;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:.76rem;
  background:rgba(127,127,127,.14);}
.traza {list-style:none; padding:0; margin:0;}
.traza li {display:flex; gap:.55rem; padding:.45rem .2rem; border-bottom:1px dashed rgba(127,127,127,.25);
  font-size:.9rem;}
.traza li:last-child {border-bottom:none;}
.traza .etapa {font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; opacity:.7; display:block;}
.traza li.bloqueo {background:rgba(229,72,77,.07);}
.traza li.ok {background:rgba(48,164,108,.07);}
.campos {width:100%; border-collapse:collapse; font-size:.86rem;}
.campos td {padding:.35rem .4rem; border-bottom:1px solid rgba(127,127,127,.18); vertical-align:top;
  overflow-wrap:anywhere;}
.campos td:first-child {opacity:.75; width:42%;}
.campos tr.afectado td {background:rgba(229,72,77,.1);}
.campos .vacio {opacity:.6; font-style:italic;}
.resumen {border-radius:.7rem; padding:.8rem 1rem; margin:.4rem 0 .8rem; border:1px solid var(--acento);
  background:color-mix(in srgb, var(--acento) 10%, transparent); font-size:.95rem;}
.anomalia {border-left:4px solid #e5484d; padding:.5rem .8rem; margin:.4rem 0;
  background:rgba(229,72,77,.06); border-radius:.4rem; font-size:.88rem; overflow-wrap:anywhere;}
.anomalia code {white-space:pre-wrap;}
</style>
"""


def e(texto: object) -> str:
    """Escapa contenido del XML antes de meterlo en HTML (nunca se confía en él)."""
    return html.escape(str(texto), quote=True)


# ══════════════════════════════════════════════════════════════════════════
# Carga de datos (cacheada por firma: ruta + mtime + tamaño)
# ══════════════════════════════════════════════════════════════════════════

def _argumento_file() -> str | None:
    """--file pasado tras `--` en `streamlit run web.py -- --file X`."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-f", "--file")
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args.file


def _firma(ruta: Path) -> tuple[int, int]:
    estado = ruta.stat()
    return estado.st_mtime_ns, estado.st_size


@st.cache_resource(max_entries=4, show_spinner="Analizando el XML…")
def _analizar_disco(ruta: str, mtime_ns: int, tamano: int, hoy: date) -> Analizador:
    """Las excepciones (XML a medio guardar) no se cachean: se reintenta solo."""
    return analizar_archivo(Path(ruta), hoy=hoy)


@st.cache_resource(max_entries=2, show_spinner="Analizando el XML subido…")
def _analizar_subida(contenido: bytes, hoy: date) -> Analizador:
    with tempfile.TemporaryDirectory(prefix="monitor_xml_") as carpeta:
        ruta = Path(carpeta) / "subido.xml"          # El parser exige extensión .xml
        ruta.write_bytes(contenido)
        return analizar_archivo(ruta, hoy=hoy)


@st.cache_resource(max_entries=4, show_spinner=False)
def _tabla(clave: tuple, _datos: Analizador) -> pd.DataFrame:
    """Una fila por incidencia, con la explicación ya resumida. No se modifica nunca."""
    filas = []
    for pos, inc in enumerate(_datos.todas):
        principal = inc.anomalia_principal
        if principal:
            donde = f" en «{principal.campo}»" if principal.campo not in ("", "—") else ""
            por_que = f"{principal.tipo}{donde}: {principal.motivo_detallado}"
        else:
            por_que = f"{inc.criterio_severidad} → {inc.regla_severidad}"
        filas.append({
            "pos": pos,
            "ID": inc.id,
            "Estado": VALIDA if inc.valida else BLOQUEADA,
            "Severidad": inc.severidad if inc.valida else None,
            "Resultado": VALIDA if inc.valida else principal.tipo,
            "Tipos": tuple(sorted({a.tipo for a in inc.anomalias})),
            "Criterio": inc.criterio_severidad if inc.valida else None,
            "Por qué": por_que,
            "Categoría": inc.tipo,
            "Marca": truncar(inc.marca, 40) if inc.marca else "Sin marca",
            "Equipo": truncar(inc.equipo, 40) or "—",
            "Fecha": pd.Timestamp(inc.fecha) if inc.fecha else pd.NaT,
            "Descripción": truncar(inc.descripcion, 140),
            "_busca": normalizar(" ".join((inc.id, *inc.campos.values()))),
        })
    return pd.DataFrame(filas)


# ══════════════════════════════════════════════════════════════════════════
# Estado de la sesión y vigilancia del archivo
# ══════════════════════════════════════════════════════════════════════════

def _estado_inicial() -> None:
    ss = st.session_state
    if ss.get("iniciado"):
        return
    arg = _argumento_file()
    ruta, aviso = localizar_xml(arg)
    ss.update(iniciado=True, arg_file=arg, fuente="disco", ruta=ruta, aviso_ruta=aviso,
              datos=None, clave=None, nombre="", firma=None, firma_fallida=None, fallos=0,
              error=None, ultima_lectura=None, ultimo_cambio=None, nuevas=set(),
              subida_id=None, error_subida=None, n_uploader=0, toast=None)


def _aplicar(datos: Analizador, clave: tuple, nombre: str, mismo_origen: bool) -> None:
    """Instala un nuevo estado válido y prepara el aviso de incidencias nuevas."""
    ss = st.session_state
    previo: Analizador | None = ss.datos
    ss.nuevas = set()
    if previo is not None and mismo_origen:
        anadidas = Counter(i.id for i in datos.todas) - Counter(i.id for i in previo.todas)
        eliminadas = len(previo.todas) - len(datos.todas) + sum(anadidas.values())
        if anadidas:
            ss.nuevas = set(anadidas)
            nuevas = [i for i in datos.todas if i.id in anadidas]
            n_val = sum(i.valida for i in nuevas)
            ids = ", ".join(f"#{i}" for i in list(anadidas)[:4]) + ("…" if len(anadidas) > 4 else "")
            ss.toast = (f"{sum(anadidas.values())} incidencia(s) nueva(s): {ids} · "
                        f"{n_val} válida(s), {len(nuevas) - n_val} bloqueada(s)", "🆕")
        elif eliminadas > 0:
            ss.toast = (f"XML actualizado: {eliminadas} incidencia(s) eliminada(s)", "🗑️")
        else:
            ss.toast = ("XML actualizado: se han modificado incidencias existentes", "🔄")
    elif previo is not None:
        ss.toast = (f"Mostrando {nombre}", "📂")
    ss.update(datos=datos, clave=clave, nombre=nombre, error=None,
              ultimo_cambio=datetime.now())


def _sincronizar() -> bool:
    """Comprueba el XML vigilado. Devuelve True si hay datos nuevos que pintar.

    Si el archivo se está guardando (ParseError, estructura a medias o la firma
    cambia mientras se lee) no se toca el último estado válido: se reintenta
    en el siguiente ciclo.
    """
    ss = st.session_state
    if ss.fuente != "disco":
        return False

    # Sin --file se vuelve a buscar en cada ciclo: si aparece respotes.xml, se adopta
    if not ss.arg_file or ss.ruta is None or not ss.ruta.is_file():
        encontrada, aviso = localizar_xml(ss.arg_file)
        if encontrada is not None and encontrada != ss.ruta:
            ss.ruta, ss.firma = encontrada, None
        ss.aviso_ruta = aviso if encontrada is None else None
    ruta: Path | None = ss.ruta
    if ruta is None:
        return False

    try:
        firma = _firma(ruta)
    except OSError:                      # Borrado o renombrado durante un guardado
        ss.error = ErrorCarga("Archivo no disponible", f"No se puede leer:\n{ruta}")
        return False
    ss.ultima_lectura = datetime.now()
    if firma == ss.firma:
        return False
    if firma == ss.firma_fallida and ss.fallos >= MAX_REINTENTOS:
        return False                     # Error persistente: esperar a que cambie

    try:
        datos = _analizar_disco(str(ruta), *firma, date.today())
        if _firma(ruta) != firma:        # Lo han reescrito mientras se leía
            raise ErrorCarga("Guardado en curso", "El archivo ha cambiado durante la lectura.")
    except (ErrorCarga, OSError) as error:
        ss.fallos = ss.fallos + 1 if firma == ss.firma_fallida else 1
        ss.firma_fallida = firma
        ss.error = error if isinstance(error, ErrorCarga) else ErrorCarga("Error de lectura",
                                                                          str(error))
        return False

    mismo = ss.clave is not None and ss.clave[:2] == ("disco", str(ruta))
    ss.firma, ss.firma_fallida, ss.fallos = firma, None, 0
    _aplicar(datos, ("disco", str(ruta), *firma), ruta.name, mismo)
    return True


def _volver_a_disco() -> None:
    ss = st.session_state
    ss.update(fuente="disco", firma=None, subida_id=None, error_subida=None,
              n_uploader=ss.n_uploader + 1)    # Nueva key = uploader vacío


# ══════════════════════════════════════════════════════════════════════════
# Cabecera, insignia en vivo y barra lateral
# ══════════════════════════════════════════════════════════════════════════

def _insignia() -> None:
    ss = st.session_state
    hora = ss.ultima_lectura.strftime("%H:%M:%S") if ss.ultima_lectura else "--:--:--"
    datos_hora = ss.ultimo_cambio.strftime("%H:%M:%S") if ss.ultimo_cambio else "—"
    vivo = ""
    if ss.fuente == "subido":
        icono, texto = "📄", f"Archivo subido · {e(ss.nombre)} · cargado {datos_hora}"
    elif ss.ruta is None:
        icono, texto = "⚪", "Esperando un XML… (súbelo desde el menú lateral)"
    elif ss.error and ss.datos is not None:
        persistente = ss.fallos >= MAX_REINTENTOS
        icono = "🟠" if persistente else "🟡"
        estado = "XML no válido" if persistente else "Reintentando lectura"
        texto = (f"{estado} · mostrando último estado válido ({datos_hora}) "
                 f"<small>· Última lectura: {hora}</small>")
    elif ss.error:
        icono, texto = "🟠", f"Esperando un XML válido · Última lectura: {hora}"
    elif not ss.get("en_vivo", True):
        icono, texto = "⏸️", f"En pausa · Última lectura: {hora}"
    else:
        icono, vivo = "🟢", " vivo"
        texto = (f"En vivo · Última lectura: {hora} "
                 f"<small>· {e(ss.nombre)} · datos de {datos_hora}</small>")
    st.markdown(f'<div class="insignia{vivo}"><span class="icono">{icono}</span><span>{texto}</span></div>',
                unsafe_allow_html=True)


def _vigilante() -> None:
    """Fragmento que se repite cada INTERVALO_S: solo relanza la app si hay cambios.

    En una ejecución completa la app ya acaba de sincronizar: no se repite la lectura.
    """
    if not st.session_state.pop("recien_sincronizado", False) and _sincronizar():
        st.rerun(scope="app")
    _insignia()


def _barra_lateral() -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown("### 📂 Fuente de datos")
        if ss.fuente == "disco" and ss.ruta is not None:
            st.markdown(f"Vigilando **{e(ss.ruta.name)}**")
            st.caption(str(ss.ruta))
        elif ss.fuente == "disco":
            st.warning(ss.aviso_ruta or "No se ha encontrado ningún XML.")

        st.toggle(f"🔄 Actualización en vivo (cada {INTERVALO_S} s)", value=True, key="en_vivo",
                  disabled=ss.fuente != "disco")

        subida = st.file_uploader("Cargar otro XML manualmente", type=["xml"],
                                  key=f"uploader_{ss.n_uploader}",
                                  help="Útil desde el móvil: analiza un XML sin tocar el vigilado.")
        if subida is not None and subida.file_id != ss.subida_id:
            ss.subida_id = subida.file_id
            try:
                datos = _analizar_subida(subida.getvalue(), date.today())
            except ErrorCarga as error:
                ss.error_subida = error
            else:
                ss.update(fuente="subido", error_subida=None)
                _aplicar(datos, ("subido", subida.file_id), subida.name, False)
        elif subida is None and ss.fuente == "subido":
            _volver_a_disco()              # Han quitado el archivo con la ✕

        if ss.error_subida:
            st.error(f"**{ss.error_subida.titulo}**\n\n{ss.error_subida.mensaje}")
        if ss.fuente == "subido":
            st.info(f"Mostrando **{ss.nombre}** (subido). La vigilancia en vivo está en pausa.")
            st.button("↩️ Volver al archivo vigilado", on_click=_volver_a_disco,
                      width="stretch")

        st.divider()
        puerto = st.get_option("server.port")
        st.markdown("### 📱 Abrir en el móvil")
        st.markdown(f"Con el móvil en la **misma Wi-Fi**, abre en Chrome:\n\n"
                    f"`http://{ip_local()}:{puerto}`")
        st.caption("Si no carga, permite el puerto en el cortafuegos del PC o usa un túnel "
                   f"(p. ej. `cloudflared tunnel --url http://localhost:{puerto}`).")


# ══════════════════════════════════════════════════════════════════════════
# Filtros
# ══════════════════════════════════════════════════════════════════════════

CLAVES_FILTRO = ("f_texto", "f_estado", "f_sev", "f_anom", "f_cat", "f_marca", "f_fechas")


def _limpiar_filtros() -> None:
    for clave in CLAVES_FILTRO:
        st.session_state.pop(clave, None)


def _opciones(actuales: list[str], clave: str) -> list[str]:
    """Opciones + lo ya seleccionado (si el XML cambia, el filtro no se pierde)."""
    seleccion = st.session_state.get(clave) or []
    return list(dict.fromkeys([*actuales, *seleccion]))


def _filtros(df: pd.DataFrame) -> pd.DataFrame:
    validas = df[df["Estado"] == VALIDA]
    texto = st.text_input("🔎 Buscar por ID o texto", key="f_texto",
                          placeholder="Ej.: impressora, Dell, no arrenca…  ·  #42 = ID exacto")
    c1, c2 = st.columns(2)
    with c1:
        estado = st.pills("Estado", [VALIDA, BLOQUEADA], selection_mode="multi", key="f_estado",
                          format_func=lambda x: f"✅ {x}s" if x == VALIDA else f"⛔ {x}s")
    with c2:
        sev = st.pills("Severidad", NIVELES, selection_mode="multi", key="f_sev",
                       format_func=lambda n: f"{EMOJI_NIVEL[n]} {n}")
    with st.expander("🎛️ Más filtros: anomalía, categoría, marca y fechas"):
        anom = st.pills("Tipo de anomalía", list(TIPO_ANOMALIA.values()),
                        selection_mode="multi", key="f_anom")
        c3, c4 = st.columns(2)
        with c3:
            cats = st.multiselect(
                "Categoría de equipo", key="f_cat", placeholder="Todas",
                options=_opciones(sorted(validas["Categoría"].unique()), "f_cat"))
        with c4:
            marcas = st.multiselect(
                "Marca", key="f_marca", placeholder="Todas",
                options=_opciones(validas["Marca"].value_counts().index.tolist(), "f_marca"))
        fechas = st.date_input("Rango de fechas de la incidencia", value=(), key="f_fechas",
                               format="DD/MM/YYYY",
                               help="Las incidencias sin fecha válida quedan fuera al filtrar.")
        st.caption("Severidad solo afecta a las válidas y Tipo de anomalía solo a las "
                   "bloqueadas; si eliges ambos se muestran las dos.")
        st.button("🧹 Limpiar filtros", on_click=_limpiar_filtros)

    m = pd.Series(True, index=df.index)
    if consulta := normalizar(texto):
        if consulta.startswith("#"):
            m &= df["ID"].str.strip().str.lower() == consulta[1:].strip()
        else:
            m &= df["_busca"].str.contains(consulta, regex=False)
    if estado:
        m &= df["Estado"].isin(estado)
    if sev or anom:
        ok_val = (df["Estado"] == VALIDA) & df["Severidad"].isin(sev) if sev else False
        ok_blo = ((df["Estado"] == BLOQUEADA)
                  & df["Tipos"].map(lambda ts: not set(anom).isdisjoint(ts))) if anom else False
        m &= ok_val | ok_blo
    if cats:
        m &= df["Categoría"].isin(cats)
    if marcas:
        m &= df["Marca"].isin(marcas)
    if fechas:
        desde = pd.Timestamp(fechas[0])
        hasta = pd.Timestamp(fechas[1] if len(fechas) > 1 else fechas[0])
        m &= df["Fecha"].between(desde, hasta)
    return df[m]


# ══════════════════════════════════════════════════════════════════════════
# KPIs y gráficos
# ══════════════════════════════════════════════════════════════════════════

def _kpis(f: pd.DataFrame, total_xml: int) -> None:
    n = len(f)
    val = int((f["Estado"] == VALIDA).sum())
    blo = n - val
    crit = int((f["Severidad"] == "Crítica").sum())
    alta = int((f["Severidad"] == "Alta").sum())
    pct = (lambda x: f"{x / n * 100:.1f}%") if n else (lambda x: "—")
    nuevas = len(st.session_state.nuevas)
    sub_total = f"de {total_xml:,} en el XML".replace(",", ".") if n != total_xml else "todas"
    if nuevas:
        sub_total += f' · <span class="nuevo">▲ {nuevas} nueva(s)</span>'

    def tarjeta(etiqueta: str, valor: str, sub: str, acento: str) -> str:
        return (f'<div class="kpi" style="--acento:{acento}"><div class="etiqueta">{etiqueta}'
                f'</div><div class="valor">{valor}</div><div class="sub">{sub}</div></div>')

    st.markdown('<div class="kpis">'
                + tarjeta("Total procesadas", f"{n:,}".replace(",", "."), sub_total, "#3e63dd")
                + tarjeta("Válidas", f"{val:,}".replace(",", "."), pct(val), "#30a46c")
                + tarjeta("Bloqueadas", f"{blo:,}".replace(",", "."), pct(blo), "#e5484d")
                + tarjeta("Críticas / Altas", f"{crit + alta:,}".replace(",", "."),
                          f"🔴 {crit} críticas · 🟠 {alta} altas", "#f76b15")
                + "</div>", unsafe_allow_html=True)


def _estilo(fig: go.Figure, alto: int = 330, leyenda: bool = True) -> go.Figure:
    """Diseño táctil: sin zoom/arrastre accidental al hacer scroll en el móvil."""
    fig.update_layout(height=alto, margin=dict(l=8, r=8, t=10, b=8), dragmode=False,
                      showlegend=leyenda, hovermode="closest",
                      legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, title=None))
    fig.update_xaxes(fixedrange=True, title=None)
    fig.update_yaxes(fixedrange=True, title=None)
    return fig


def _pintar(fig: go.Figure, clave: str) -> None:
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, theme="streamlit", key=clave)


def _vacio(mensaje: str = "Sin incidencias válidas con estos filtros.") -> None:
    st.info(mensaje, icon="🫥")


def _grafico_donut(f: pd.DataFrame) -> None:
    st.markdown("##### Validez vs anomalías")
    st.caption("Las bloqueadas se agrupan por la primera regla que las rechazó.")
    if f.empty:
        return _vacio("Ninguna incidencia con estos filtros.")
    conteo = f["Resultado"].value_counts()
    etiquetas = [r for r in COLOR_RESULTADO if conteo.get(r, 0)]
    fig = go.Figure(go.Pie(
        labels=etiquetas, values=[int(conteo[r]) for r in etiquetas], hole=.62, sort=False,
        marker=dict(colors=[COLOR_RESULTADO[r] for r in etiquetas]),
        textinfo="percent", textposition="inside", insidetextorientation="horizontal",
        hovertemplate="<b>%{label}</b><br>%{value} incidencias · %{percent}<extra></extra>"))
    pct = conteo.get(VALIDA, 0) / len(f) * 100
    fig.add_annotation(text=f"<b>{pct:.0f}%</b><br>válidas", showarrow=False,
                       font=dict(size=20))
    _pintar(_estilo(fig), "g_donut")


def _grafico_severidad(f: pd.DataFrame) -> None:
    st.markdown("##### Distribución por severidad")
    st.caption("Solo incidencias válidas.")
    conteo = f["Severidad"].value_counts()
    if not conteo.sum():
        return _vacio()
    valores = [int(conteo.get(n, 0)) for n in NIVELES]
    fig = go.Figure(go.Bar(
        x=NIVELES, y=valores, marker_color=[COLOR_NIVEL[n] for n in NIVELES],
        text=valores, textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y} incidencias<extra></extra>"))
    fig.update_yaxes(rangemode="tozero")
    _pintar(_estilo(fig, leyenda=False), "g_sev")


def _grafico_tiempo(f: pd.DataFrame) -> None:
    cab, ctrl = st.columns([3, 2], vertical_alignment="bottom")
    with cab:
        st.markdown("##### Evolución temporal")
        st.caption("Incidencias válidas por fecha de la incidencia, apiladas por severidad.")
    with ctrl:
        grano = st.segmented_control("Agrupar por", ["Día", "Semana", "Mes"], default="Mes",
                                     key="g_grano", label_visibility="collapsed") or "Mes"
    v = f[(f["Estado"] == VALIDA) & f["Fecha"].notna()]
    if v.empty:
        return _vacio()
    periodo = {"Día": v["Fecha"].dt.normalize(),
               "Semana": v["Fecha"].dt.to_period("W-SUN").dt.start_time,
               "Mes": v["Fecha"].dt.to_period("M").dt.start_time}[grano]
    serie = (v.assign(Periodo=periodo).groupby(["Periodo", "Severidad"]).size()
             .reset_index(name="Incidencias"))
    fig = px.bar(serie, x="Periodo", y="Incidencias", color="Severidad",
                 color_discrete_map=COLOR_NIVEL, category_orders={"Severidad": NIVELES})
    total = serie.groupby("Periodo")["Incidencias"].sum().reset_index()
    fig.add_trace(go.Scatter(x=total["Periodo"], y=total["Incidencias"], name="Total",
                             mode="lines+markers", line=dict(color="#8b8d98", width=2),
                             hovertemplate="Total: %{y}<extra></extra>"))
    formato = {"Día": "%d/%m/%Y", "Semana": "Semana del %d/%m/%Y", "Mes": "%B %Y"}[grano]
    fig.update_traces(selector=dict(type="bar"),
                      hovertemplate="%{fullData.name}: %{y}<extra></extra>")
    fig.update_layout(barmode="stack", hovermode="x unified")
    fig.update_xaxes(hoverformat=formato)
    _pintar(_estilo(fig, alto=360), "g_tiempo")


def _grafico_ranking(f: pd.DataFrame, columna: str, titulo: str, color: str, clave: str,
                     top: int = 10) -> None:
    st.markdown(f"##### {titulo}")
    v = f[(f["Estado"] == VALIDA) & (f[columna] != "—")]
    if v.empty:
        return _vacio()
    conteo = v[columna].value_counts().head(top).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=conteo.values, y=conteo.index, orientation="h", marker_color=color,
        text=conteo.values, textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x} incidencias<extra></extra>"))
    _pintar(_estilo(fig, alto=max(240, 34 * len(conteo) + 40), leyenda=False), clave)


def _panel(f: pd.DataFrame) -> None:
    c1, c2 = st.columns(2, gap="large")
    with c1:
        _grafico_donut(f)
    with c2:
        _grafico_severidad(f)
    _grafico_tiempo(f)
    c3, c4 = st.columns(2, gap="large")
    with c3:
        _grafico_ranking(f, "Equipo", "Top equipos con más fallos", "#3e63dd", "g_equipos")
    with c4:
        _grafico_ranking(f, "Categoría", "Categorías con más fallos", "#8e4ec6", "g_categorias")


# ══════════════════════════════════════════════════════════════════════════
# Listado y ficha explicativa
# ══════════════════════════════════════════════════════════════════════════

def _vista_tabla(f: pd.DataFrame) -> pd.DataFrame:
    nuevas = st.session_state.nuevas
    return pd.DataFrame({
        "🆕": f["ID"].map(lambda i: "🆕" if i in nuevas else ""),
        "ID": f["ID"],
        "Estado": f["Estado"].map(lambda s: f"✅ {s}" if s == VALIDA else f"⛔ {s}"),
        "Resultado": [f"{EMOJI_NIVEL[s]} {s}" if isinstance(s, str) else f"⛔ {r}"
                      for s, r in zip(f["Severidad"], f["Resultado"])],
        "Por qué": f["Por qué"],
        "Categoría": f["Categoría"],
        "Marca": f["Marca"],
        "Equipo": f["Equipo"],
        "Fecha": f["Fecha"],
        "Descripción": f["Descripción"],
    })


def _listado(f: pd.DataFrame, datos: Analizador) -> None:
    cab, boton = st.columns([3, 1], vertical_alignment="bottom")
    cab.caption(f"**{len(f):,}** incidencias con los filtros actuales · "
                "toca una fila para ver su ficha explicada.".replace(",", "."))
    boton.download_button("⬇️ CSV", f.drop(columns=["_busca", "pos", "Tipos"])
                          .to_csv(index=False).encode("utf-8-sig"),
                          file_name="incidencias_filtradas.csv", mime="text/csv",
                          width="stretch")
    evento = st.dataframe(
        _vista_tabla(f), hide_index=True, height=440, key="tabla",
        on_select="rerun", selection_mode="single-row",
        column_config={
            "🆕": st.column_config.TextColumn(width=40),
            "ID": st.column_config.TextColumn(width="small"),
            "Por qué": st.column_config.TextColumn(width="large"),
            "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Descripción": st.column_config.TextColumn(width="large"),
        })
    filas = evento.selection.rows if evento else []
    if filas and filas[0] < len(f):
        st.divider()
        _ficha(datos.todas[int(f.iloc[filas[0]]["pos"])])


def _ficha(inc: Incidencia) -> None:
    """Ficha visual: campos originales + explicación paso a paso del motor."""
    principal = inc.anomalia_principal
    if inc.valida:
        acento = COLOR_NIVEL.get(inc.severidad, "#30a46c")
        etiqueta = f"✅ VÁLIDA · {EMOJI_NIVEL.get(inc.severidad, '')} Severidad {inc.severidad}"
        resumen = (f"Severidad <b>{e(inc.severidad)}</b> porque se aplicó "
                   f"<b>{e(inc.criterio_severidad)}</b> → {e(inc.regla_severidad)}.<br>"
                   f"Categoría <b>{e(inc.tipo)}</b> ({e(inc.origen_tipo)}) · Marca "
                   f"<b>{e(truncar(inc.marca, 40) or 'Sin marca')}</b> ({e(inc.origen_marca)}).")
    else:
        acento = "#e5484d"
        etiqueta = f"⛔ BLOQUEADA · {principal.tipo}"
        donde = f" en «{e(principal.campo)}»" if principal.campo not in ("", "—") else ""
        extra = len(inc.anomalias) - 1
        resumen = (f"Rechazada por <b>{e(principal.tipo)}</b>{donde}: "
                   f"{e(principal.motivo_detallado)}"
                   + (f"<br>…y {extra} regla(s) más (detalle abajo)." if extra else ""))

    st.markdown(f"#### Incidencia #{e(inc.id)} &nbsp;·&nbsp; {e(etiqueta)}",
                unsafe_allow_html=True)
    st.markdown(f'<div class="resumen" style="--acento:{acento}">{resumen}</div>',
                unsafe_allow_html=True)

    afectados = {a.campo for a in inc.anomalias}
    izq, der = st.columns([1.1, 1], gap="large")
    with izq:
        st.markdown("**📄 Campos originales del XML**")
        filas = []
        for nombre in (*inc.campos, *inc.vacios):
            clase = ' class="afectado"' if nombre in afectados else ""
            if nombre in inc.campos:
                valor = e(truncar(inc.campos[nombre], MAX_FICHA))
            else:
                valor = '<span class="vacio">∅ vacío</span>'
            filas.append(f"<tr{clase}><td>{e(nombre)}</td><td>{valor}</td></tr>")
        st.markdown(f'<table class="campos">{"".join(filas)}</table>', unsafe_allow_html=True)
        if afectados:
            st.caption("En rojo: campos que han provocado el bloqueo.")
    with der:
        st.markdown("**🧠 Por qué el motor decidió esto (paso a paso)**")
        pasos = "".join(
            f'<li class="{p.estado}"><span>{ICONO_PASO.get(p.estado, "➜")}</span>'
            f'<span><span class="etapa">{e(p.etapa)}</span>{e(p.texto)}</span></li>'
            for p in inc.traza)
        st.markdown(f'<ul class="traza">{pasos}</ul>', unsafe_allow_html=True)

    if inc.anomalias:
        st.markdown("**⛔ Reglas incumplidas**")
        for n, a in enumerate(inc.anomalias, 1):
            extra = f"<br><i>{e(a.extra)}</i>" if a.extra else ""
            st.markdown(
                f'<div class="anomalia"><b>{n}. {e(a.tipo)}</b> · campo «{e(a.campo)}»<br>'
                f"{e(a.motivo_detallado)}<br>Valor: <code>{e(truncar(a.valor, MAX_FICHA))}"
                f"</code>{extra}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# Auditoría: mapa de reglas + inspector
# ══════════════════════════════════════════════════════════════════════════

def _alternativas(patron: str) -> list[str]:
    """Convierte una regex de config.py en palabras clave legibles (chips)."""
    partes, nivel, actual = [], 0, ""
    for c in patron:                       # Divide por '|' solo fuera de paréntesis
        nivel += (c == "(") - (c == ")")
        if c == "|" and nivel == 0:
            partes.append(actual)
            actual = ""
        else:
            actual += c
    partes.append(actual)
    legibles = []
    for p in partes:
        p = re.sub(r"\\b|\^|\$|\\s\?", "", p)
        p = p.replace(r"\.?", "").replace(r"\.", "·").replace(".*", "…").replace(r"\W", " ")
        p = p.replace(" ?", " ")                         # Espacio opcional
        p = re.sub(r"\[(\w+)\]\?", lambda m: f"({'/'.join(m.group(1))})", p)  # [ae]? -> (a/e)
        p = re.sub(r"\(([^()]*)\)\?", r"[\1]", p)       # Grupo opcional -> [..]
        p = re.sub(r"(\w)\?", r"(\1)", p)                # Letra opcional -> (s)
        p = p.replace(".", "'").replace("·", ".").replace("|", "/").replace("?:", "")
        legibles.append(p.strip())
    return [p for p in legibles if p]


def _chips(palabras: list[str]) -> str:
    return "".join(f'<span class="chip">{e(p)}</span>' for p in palabras)


def _tarjeta_regla(paso: str, titulo: str, nivel: str | None, texto: str, chips: str,
                   cuenta: str, acento: str) -> str:
    etiqueta = f'<span class="nivel">{e(nivel)}</span>' if nivel else ""
    return (f'<div class="regla" style="--acento:{acento}"><div class="paso">{e(paso)}</div>'
            f'<div class="titulo">{e(titulo)} {etiqueta}</div><p>{texto}</p>'
            f'<div>{chips}</div><p class="cuenta">{cuenta}</p></div>')


def _mapa_reglas(df: pd.DataFrame, datos: Analizador) -> None:
    validas = df[df["Estado"] == VALIDA]
    criterios = validas["Criterio"].fillna("")
    def cuantas(prefijo: str) -> str:
        n = int(criterios.str.startswith(prefijo).sum())
        return f"📌 {n:,} incidencias válidas resueltas así".replace(",", ".")

    st.markdown("#### 🗺️ Cómo se decide la severidad")
    st.caption("Se evalúa en orden y **gana la primera regla que encaja**. Las palabras clave se "
               "buscan en la descripción, el equipo y su categoría (sin tildes ni mayúsculas).")
    tarjetas = [_tarjeta_regla(
        "Paso 0 · Prioridad explícita", "Campo de prioridad del XML", None,
        "Si el XML trae un campo <i>Prioritat / Severitat / Urgència</i>, manda su valor y no "
        "se deduce nada.",
        "".join(f"<div><b>{e(n)}</b>: {_chips(_alternativas(p.pattern))}</div>"
                for n, p in MAPA_SEVERIDAD),
        cuantas("Campo de prioridad"), "#8b8d98")]
    for regla in REGLAS_SEVERIDAD:
        tarjetas.append(_tarjeta_regla(
            f"Paso {regla.paso}", regla.titulo, regla.nivel, e(regla.descripcion),
            _chips(_alternativas(regla.patron.pattern)), cuantas(f"Paso {regla.paso} "),
            COLOR_NIVEL[regla.nivel]))
    ultimo = len(REGLAS_SEVERIDAD) + 1
    tarjetas.append(_tarjeta_regla(
        f"Paso {ultimo}", "Sin pistas", SEVERIDAD_POR_DEFECTO,
        "Ninguna palabra clave encaja: se asume <b>fallo genérico</b> (mejor no infravalorar).",
        "", cuantas(f"Paso {ultimo} "), COLOR_NIVEL[SEVERIDAD_POR_DEFECTO]))
    st.markdown(f'<div class="tarjetas">{"".join(tarjetas)}</div>', unsafe_allow_html=True)

    st.markdown("#### 🚫 Qué bloquea el sistema")
    st.caption("Una sola regla incumplida basta para bloquear la incidencia: no cuenta en las "
               "métricas de válidas.")
    por_tipo = Counter(a.tipo for i in datos.anomalas for a in i.anomalias)
    def veces(cat: str) -> str:
        return f"📌 Detectado {por_tipo.get(TIPO_ANOMALIA[cat], 0):,} veces".replace(",", ".")
    hoy = date.today()
    bloqueos = [
        (CAT_FECHA, "Campos de fecha (<i>Data, Fecha, Date…</i>) con:",
         [f"año < {ANYO_MINIMO}", f"año > {hoy.year}", f"posterior a {hoy:%d/%m/%Y}",
          "día/mes inexistente (31/02)", "sin formato reconocible"]),
        (CAT_VACIO, "Etiquetas vacías o de autocierre en campos obligatorios. Marca y modelo "
                    "son opcionales y <b>no</b> bloquean:",
         ['<camp nom="X"/>', '<camp nom="X"></camp>', "sin atributo id",
          "opcional: marca", "opcional: modelo"]),
        (CAT_BASURA, "Texto que no es una incidencia real, en cualquier campo:",
         ["binario ≥ 3 bytes (01001000…)", "escritura amárica (ሀ…)",
          *(f"{p} → {t}" for p, t in PALABRAS_BASURA.items())]),
        (CAT_DESBORDE, f"Más de <b>{MAX_LONGITUD_CORTO}</b> caracteres en un campo breve "
                       "(código, equipo, marca, modelo, IP…):",
         re.search(r"\((.*)\)", RE_CAMPO_CORTO.pattern).group(1).split("|")),
    ]
    st.markdown('<div class="tarjetas">' + "".join(
        _tarjeta_regla("Bloqueo", TIPO_ANOMALIA[cat], None, texto, _chips(chips), veces(cat),
                       COLOR_RESULTADO[TIPO_ANOMALIA[cat]])
        for cat, texto, chips in bloqueos) + "</div>", unsafe_allow_html=True)

    with st.expander("🏷️ Categorías de equipo y marcas reconocidas"):
        st.caption("Si el XML no trae categoría, se deduce del equipo (y si no, de la "
                   "descripción): gana la primera fila que encaja. La marca se lee del campo "
                   "«Marca d'equip» y, si viene vacía, se busca con estos patrones.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Categorías**")
            st.markdown("".join(f"<div><b>{e(n)}</b>: {_chips(_alternativas(p.pattern))}</div>"
                                for n, p in TIPOS_DISPOSITIVO), unsafe_allow_html=True)
        with c2:
            st.markdown("**Marcas**")
            st.markdown("".join(f"<div><b>{e(n)}</b>: {_chips(_alternativas(p.pattern))}</div>"
                                for n, p in MARCAS_REALES), unsafe_allow_html=True)


def _inspector(f: pd.DataFrame, datos: Analizador) -> None:
    st.markdown("#### 🔎 Inspector de incidencias")
    c1, c2 = st.columns([1, 2])
    with c1:
        buscado = st.text_input("Buscar por ID exacto", key="insp_id", placeholder="Ej.: 42")
    with c2:
        posiciones = f["pos"].tolist()
        etiquetas = dict(zip(posiciones, (
            f"#{i} · {'✅ ' + EMOJI_NIVEL[s] + ' ' + s if isinstance(s, str) else '⛔ ' + r}"
            f" · {eq}" for i, s, r, eq in zip(f["ID"], f["Severidad"], f["Resultado"],
                                               f["Equipo"]))))
        elegido = st.selectbox(
            f"…o elige del listado filtrado ({len(posiciones):,})".replace(",", "."),
            posiciones, index=None, key="insp_sel", format_func=etiquetas.get,
            placeholder="Escribe para buscar (ID, severidad, equipo)…")

    if buscado.strip():
        encontradas = datos.por_id(buscado.strip().lstrip("#"))
        if not encontradas:
            st.warning(f"No hay ninguna incidencia con ID «{buscado.strip()}».")
        for inc in encontradas:
            if len(encontradas) > 1:
                st.caption(f"⚠️ El ID aparece {len(encontradas)} veces en el XML.")
            with st.container(border=True):
                _ficha(inc)
    elif elegido is not None and elegido < len(datos.todas):
        with st.container(border=True):
            _ficha(datos.todas[elegido])
    else:
        st.info("Busca un ID o elige una incidencia para ver su ficha con la explicación paso "
                "a paso de por qué se validó o rechazó y por qué recibió esa severidad.",
                icon="👆")


# ══════════════════════════════════════════════════════════════════════════
# Página
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    st.set_page_config(page_title="Monitor XML Incidencias", page_icon="📊", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    _estado_inicial()
    ss = st.session_state

    _barra_lateral()
    _sincronizar()
    ss.recien_sincronizado = True
    if ss.toast:
        mensaje, icono = ss.toast
        st.toast(mensaje, icon=icono)
        ss.toast = None

    st.markdown('<div class="cabecera"><h1>📊 Monitor XML de Incidencias</h1></div>',
                unsafe_allow_html=True)
    vivo = ss.fuente == "disco" and ss.get("en_vivo", True)
    st.fragment(_vigilante, run_every=INTERVALO_S if vivo else None)()

    datos: Analizador | None = ss.datos
    if datos is None:
        if ss.error:
            st.warning(f"**{ss.error.titulo}** — {ss.error.mensaje}\n\n"
                       "Se reintentará automáticamente en cuanto el archivo cambie.", icon="⏳")
        else:
            st.info(ss.aviso_ruta or "Esperando datos…", icon="📂")
        st.caption("También puedes subir un XML desde el menú lateral (☰ / >).")
        return

    df = _tabla(ss.clave, datos)
    hueco_kpis = st.container()
    filtrado = _filtros(df)
    with hueco_kpis:
        _kpis(filtrado, len(df))

    panel, listado, auditoria = st.tabs(
        ["📊 Panel", "📋 Incidencias", "🔍 Cómo se categoriza (Auditoría y Reglas)"],
        key="pestana")
    with panel:
        _panel(filtrado)
    with listado:
        _listado(filtrado, datos)
    with auditoria:
        _inspector(filtrado, datos)
        st.divider()
        _mapa_reglas(df, datos)


main()
