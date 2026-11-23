# -*- coding: utf-8 -*-
"""Generador del dashboard estático index.html (para GitHub Pages).

GitHub Pages solo sirve archivos: no ejecuta Python. Por eso el análisis se
hace aquí (parser -> validator -> analytics, el mismo motor que el resto de la
aplicación) y el resultado queda EMBEBIDO en un único index.html autocontenido:

    * CSS y JavaScript en línea (app/estatico/*), sin rutas relativas que romper.
    * Los datos en <script type="application/json" id="datos">, sin fetch ni CORS.
    * Solo Chart.js se carga desde un CDN; si falla, la página funciona sin gráficos.

Formato de los datos (compacto: las cadenas repetidas se guardan una sola vez
en la tabla S y los registros las referencian por índice, -1 = sin valor):

    I[k] = [id, valida, sev, inferida, cat, marca, equipo, fecha, desc, criterio,
            regla, origen_tipo, origen_marca, nota_infra, zona, codigo,
            anomalias[[cat, regla, campo, valor, extra, motivo]],
            reparaciones[[campo, antes, despues, motivo]],
            campos[nombre, valor, nombre, valor, ...]]

La configuración del motor (expresiones regulares, reglas de rules.json,
límites...) también se exporta para que app/estatico/motor.js pueda analizar en
el navegador otro XML con EXACTAMENTE las mismas reglas.

Pantalla de PIN: la página se abre bloqueada y pide el PIN de Consultor o de
Técnico (pins.json o PIN_CONSULTA / PIN_TECNICO). En el HTML NO van los PINs,
solo su SHA-256 con una sal aleatoria. Aun así es una barrera de cortesía, no
seguridad real: un sitio estático no puede ocultar sus propios datos (van
embebidos en la página) y un PIN de 4-5 cifras se prueba entero en segundos.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from app import config as cfg
from app.analytics import Analizador, _valor, analizar_archivo, palabras_emergentes
from app.auth import ROL_CONSULTA, ROL_TECNICO, GestorAuth
from app.exporter import _CSS_INFORME
from app.models import Incidencia
from app.rules import Reglas, cargar_reglas, validar_datos

CARPETA_ESTATICA = Path(__file__).resolve().parent / "estatico"
NOMBRE_HTML = "index.html"
NOMBRE_XML_PUBLICADO = "datos.xml"   # Copia del XML junto a index.html (re-análisis con reglas nuevas)
MAX_VALOR = 600                 # Caracteres por valor embebido (la basura gigante se recorta)
ZONA_HORARIA = "Europe/Madrid"  # Hora del sello "Actualizado" (GitHub Actions corre en UTC)

# Expresiones de config.py que necesita el motor del navegador
_REGEX_MOTOR = (
    "RE_CAMPO_NO_MARCA", "RE_CAMPO_OPCIONAL", "RE_CAMPO_FECHA", "RE_CAMPO_EQUIPO",
    "RE_CAMPO_NO_EQUIPO", "RE_CAMPO_TIPO", "RE_CAMPO_MARCA", "RE_CAMPO_MODELO",
    "RE_CAMPO_SEVERIDAD", "RE_CAMPO_DESCRIPCION", "RE_CAMPO_AFECTADOS", "RE_CAMPO_ZONA",
    "RE_CAMPO_CODIGO", "RE_CAMPO_CORTO", "RE_FECHA", "RE_BINARIO", "RE_AMARICO",
    "RE_FRASES_FAKER", "RE_FECHA_REPARABLE_ISO", "RE_FECHA_REPARABLE_EU",
)


# ══════════════════════════════════════════════════════════════════════════
# Configuración exportada al navegador
# ══════════════════════════════════════════════════════════════════════════

def _js(patron: re.Pattern[str]) -> dict[str, str]:
    """Expresión de Python como {fuente, flags} para new RegExp() (sin flag u:
    así los escapes de re.escape como «\\ » siguen siendo válidos en JS)."""
    return {"s": patron.pattern, "f": "i" if patron.flags & re.IGNORECASE else ""}


def configuracion_motor(reglas: Reglas) -> dict:
    return {
        "etiquetas": {"raiz": cfg.ETIQUETA_RAIZ, "incidencia": cfg.ETIQUETA_INCIDENCIA,
                      "campo": cfg.ETIQUETA_CAMPO},
        "camposEsperados": cfg.CAMPOS_ESPERADOS,
        "camposObligatorios": cfg.CAMPOS_OBLIGATORIOS,
        "re": {nombre: _js(getattr(cfg, nombre)) for nombre in _REGEX_MOTOR},
        "tipos": [[nombre, p.pattern] for nombre, p in cfg.TIPOS_DISPOSITIVO],
        "mapaSeveridad": [[nombre, p.pattern] for nombre, p in cfg.MAPA_SEVERIDAD],
        "palabrasBasura": cfg.PALABRAS_BASURA,
        "valoresNulos": sorted(cfg.VALORES_NULOS),
        "numerosRomanos": sorted(cfg.NUMEROS_ROMANOS),
        "nombresFaker": sorted(cfg.NOMBRES_PROPIOS_FAKER),
        "limites": {"maxLongitudCorto": cfg.MAX_LONGITUD_CORTO,
                    "minPalabrasFaker": cfg.MIN_PALABRAS_FAKER,
                    "minPalabrasProsa": cfg.MIN_PALABRAS_PROSA,
                    "minPalabrasParrafo": cfg.MIN_PALABRAS_PARRAFO,
                    "maxErrores": cfg.MAX_ERRORES_ESTRUCTURA},
        "cat": {"fecha": cfg.CAT_FECHA, "basura": cfg.CAT_BASURA, "desborde": cfg.CAT_DESBORDE,
                "vacio": cfg.CAT_VACIO, "sinSentido": cfg.CAT_SIN_SENTIDO},
        "tipoAnomalia": cfg.TIPO_ANOMALIA,
        "defectos": {"categoria": cfg.CATEGORIA_POR_DEFECTO,
                     "severidad": cfg.SEVERIDAD_POR_DEFECTO},
        "niveles": cfg.NIVELES,
        "pasos": cfg.PASOS_SEVERIDAD,
        "etiquetasListas": cfg.ETIQUETAS_LISTAS,
        "sla": cfg.SLA_HORAS,
        "estadosGestion": cfg.ESTADOS_GESTION,
        "reglasFabrica": validar_datos(copy.deepcopy(cfg.REGLAS_POR_DEFECTO)),
        "masivas": {"minTormenta": cfg.MIN_TORMENTA, "ventana": cfg.VENTANA_TORMENTA_DIAS,
                    "umbral": cfg.UMBRAL_DUPLICADO, "margen": cfg.MARGEN_DUPLICADO_DIAS},
        "reglas": {"datos": reglas.datos,
                   "patrones": {clave: p.pattern for clave, p in reglas.patrones.items()},
                   "marcas": [[nombre, p.pattern] for nombre, p in reglas.marcas]},
    }


# ══════════════════════════════════════════════════════════════════════════
# Datos compactos
# ══════════════════════════════════════════════════════════════════════════

class _Tabla:
    """Tabla de cadenas: cada texto distinto se guarda una vez."""

    def __init__(self):
        self.cadenas: list[str] = []
        self._indice: dict[str, int] = {}

    def __call__(self, texto: str | None) -> int:
        if texto is None:
            return -1
        texto = str(texto)
        if len(texto) > MAX_VALOR:
            texto = texto[:MAX_VALOR] + f"… [recortado: {len(texto):,} caracteres en total]"
        if texto not in self._indice:
            self._indice[texto] = len(self.cadenas)
            self.cadenas.append(texto)
        return self._indice[texto]


def _nota_infra(inc: Incidencia) -> str | None:
    return next((p.texto for p in inc.traza
                 if p.etapa == "Severidad" and p.texto.startswith("Equipo de infraestructura")),
                None)


def _registro(inc: Incidencia, s: _Tabla) -> list:
    campos: list[int] = []
    for nombre in inc.orden or [*inc.campos, *inc.vacios]:
        campos += [s(nombre), s(inc.campos.get(nombre))]
    return [
        s(inc.id), int(inc.valida), s(inc.severidad), int(inc.severidad_inferida), s(inc.tipo),
        s(inc.marca), s(inc.equipo), s(inc.fecha.isoformat() if inc.fecha else None),
        s(inc.descripcion), s(inc.criterio_severidad), s(inc.regla_severidad), s(inc.origen_tipo),
        s(inc.origen_marca), s(_nota_infra(inc)), s(_valor(inc, cfg.RE_CAMPO_ZONA)),
        s(_valor(inc, cfg.RE_CAMPO_CODIGO).upper()),
        [[s(a.categoria), s(a.regla), s(a.campo), s(a.valor), s(a.extra), s(a.motivo_detallado)]
         for a in inc.anomalias],
        [[s(r.campo), s(r.antes), s(r.despues), s(r.motivo)] for r in inc.reparaciones],
        campos,
    ]


def _ahora() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(ZONA_HORARIA))
    except Exception:  # noqa: BLE001 — sin base de datos de zonas (Windows sin tzdata)
        return datetime.now()


def huella_pin(sal: str, pin: str) -> str:
    """SHA-256 hexadecimal de «sal:pin» (lo mismo calcula plantilla.html en el navegador)."""
    return hashlib.sha256(f"{sal}:{pin}".encode("utf-8")).hexdigest()


def acceso_embebido(pins: Mapping[str, str] | None = None, sal: str | None = None) -> dict:
    """{"sal": ..., "huellas": [[sha256, rol], ...]} para la pantalla de PIN.

    Sin `pins` se leen de pins.json / variables de entorno (lanza ErrorAuth si
    la configuración no es válida: mejor no publicar que publicar sin PIN)."""
    pins = pins if pins is not None else GestorAuth().pins()
    sal = sal or secrets.token_hex(16)
    return {"sal": sal, "huellas": [[huella_pin(sal, pins["consulta"]), ROL_CONSULTA],
                                    [huella_pin(sal, pins["tecnico"]), ROL_TECNICO]]}


def datos_embebidos(datos: Analizador, reglas: Reglas, ahora: datetime | None = None,
                    hoy: date | None = None, pins: Mapping[str, str] | None = None) -> dict:
    ahora = ahora or _ahora()
    s = _Tabla()
    registros = [_registro(inc, s) for inc in datos.todas]
    return {
        "meta": {"generado": f"{ahora:%d/%m/%Y %H:%M}", "generadoISO": ahora.isoformat(),
                 "fuente": datos.ruta.name, "hoy": (hoy or date.today()).isoformat(),
                 "total": datos.resumen.total, "validas": datos.resumen.validas,
                 "anomalas": datos.resumen.anomalas, "reglas": reglas.huella,
                 "xml": NOMBRE_XML_PUBLICADO},
        "config": configuracion_motor(reglas),
        "acceso": acceso_embebido(pins),
        # Informe ejecutivo ya generado (botón «Descargar Informe Ejecutivo»). En Pages no
        # hay gestion.json: sin seguimiento, todas las incidencias cuentan como abiertas.
        # Estilos del informe ejecutivo: el navegador lo genera al pulsar el botón, con las
        # reglas y el seguimiento vigentes (misma estructura que exporter.informe_estado)
        "informeCss": _CSS_INFORME,
        # Palabras frecuentes que aún no son palabra clave (botones ➕ del modo Técnico)
        "emergentes": [[t.texto, t.tipo, t.incidencias, t.ejemplo[:200]] for t in palabras_emergentes(
            datos.todas, [reglas.patron(c) for c in reglas.datos["severidad"]], top=15)],
        "S": s.cadenas,
        "I": registros,
    }


def _json_seguro(objeto) -> str:
    """JSON listo para ir dentro de <script>: «<» escapado (nunca cierra la etiqueta)."""
    texto = json.dumps(objeto, ensure_ascii=False, separators=(",", ":"))
    return texto.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


# ══════════════════════════════════════════════════════════════════════════
# Montaje del HTML
# ══════════════════════════════════════════════════════════════════════════

def _estatico(nombre: str) -> str:
    return (CARPETA_ESTATICA / nombre).read_text(encoding="utf-8")


def generar_html(datos: Analizador, reglas: Reglas, ahora: datetime | None = None,
                 hoy: date | None = None, pins: Mapping[str, str] | None = None) -> str:
    """index.html completo como texto."""
    carga = datos_embebidos(datos, reglas, ahora, hoy, pins)
    meta = carga["meta"]
    sello = (f"Actualizado: {meta['generado']} · {meta['total']:,} registros procesados · "
             f"{meta['validas']:,} válidas · fuente: {meta['fuente']}").replace(",", ".")
    html = _estatico("plantilla.html")
    for marca, contenido in (("{{CSS}}", _estatico("dashboard.css")),
                             ("{{MOTOR}}", _estatico("motor.js")),
                             ("{{OPERACIONES}}", _estatico("operaciones.js")),
                             ("{{TECNICO}}", _estatico("tecnico.js")),
                             ("{{APP}}", _estatico("dashboard.js")),
                             ("{{ACCESO}}", _estatico("acceso.js")),
                             ("{{SELLO}}", sello.replace("&", "&amp;").replace("<", "&lt;"))):
        html = html.replace(marca, contenido)
    return html.replace("{{DATOS}}", _json_seguro(carga))   # Los datos, los últimos


def escribir_index(datos: Analizador, reglas: Reglas | None = None,
                   destino: Path | None = None) -> Path:
    """Escribe index.html (de forma atómica) y devuelve su ruta."""
    destino = Path(destino or cfg.RAIZ_PROYECTO / NOMBRE_HTML)
    html = generar_html(datos, reglas or cargar_reglas())
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        temporal.write_text(html, encoding="utf-8", newline="\n")
        temporal.replace(destino)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise
    return destino


def generar_desde_xml(ruta_xml: Path, destino: Path | None = None) -> tuple[Path, Analizador]:
    """Tubería completa para `python3 main.py --html`. Lanza ErrorCarga u OSError."""
    reglas = cargar_reglas()
    datos = analizar_archivo(ruta_xml, reglas=reglas)
    return escribir_index(datos, reglas, destino), datos
