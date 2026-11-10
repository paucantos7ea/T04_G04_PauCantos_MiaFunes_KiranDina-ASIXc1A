# -*- coding: utf-8 -*-
"""
filtro_respotes.py — Analizador interactivo de incidencias en XML (v3)
=====================================================================

Lee un XML de incidencias con esta estructura:

    <incidencies>
        <incidencia id="1">
            <camp nom="Nombre del campo">Valor</camp>
            ...
        </incidencia>
    </incidencies>

Arquitectura (una responsabilidad por clase):

    XMLParser        -> lectura y parseo seguro del archivo (iterparse)
    AnomalyDetector  -> motor de validación: decide VÁLIDA / ANÓMALA y por qué
    AnalyticsEngine  -> enriquece cada incidencia (tipo, marca, severidad...)
                        y calcula las métricas una sola vez
    Paginator        -> listados de 10 en 10 con [N] [P] [G] [Q]
    EntradaUsuario   -> todas las lecturas de teclado, ya saneadas
    CLIInterface     -> dashboard, menús, gráficas y fichas

Uso:
    python filtro_respotes.py ruta\\al\\respotes.xml   -> lee ese XML
    python filtro_respotes.py                        -> te pide la ruta

Dependencias:
    pip install rich questionary
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Si falta una librería, mensaje claro en vez de traceback
try:
    import questionary
    from rich import box
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError as error:
    print(f"Falta la librería '{error.name}'. Ejecuta:  pip install rich questionary")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURACIÓN
#    Todo lo que puedes querer ajustar está aquí. Las expresiones regulares
#    se compilan UNA sola vez al arrancar (rendimiento).
# ══════════════════════════════════════════════════════════════════════════

NOMBRE_XML_DEFECTO = "respotes.xml"   # Se propone como ruta si existe
ANYO_MINIMO = 2000                    # Años anteriores = imposibles
MAX_TRUNCAR = 50                      # Caracteres visibles en las tablas
MAX_FICHA = 160                       # Caracteres visibles en la ficha de rechazo
MAX_LONGITUD_CORTO = 200              # Desbordamiento en campos breves
POR_PAGINA = 10                       # Registros por página
TOP_EQUIPOS = 10                      # Equipos en la gráfica

# Campos que deben existir siempre. Vacío = solo se marcan etiquetas vacías.
# Ejemplo: CAMPOS_OBLIGATORIOS = ["Data", "Equip", "Descripció"]
CAMPOS_OBLIGATORIOS: list[str] = []

# Campos OPCIONALES: si vienen vacíos (<camp nom="Marca d'equip"/>) NO se
# rechaza la incidencia; la marca se deduce por REGEX o queda "sin marca".
RE_CAMPO_OPCIONAL = re.compile(r"marca|fabricant|brand|model", re.I)

# Palabra basura (sin tildes, minúsculas) -> qué tipo de basura es
PALABRAS_BASURA: dict[str, str] = {
    "fox news": "recorte de noticias",
    "cerditos": "cuento infantil",
    "miercoles addams": "relato de ficción",
    "pull and bear": "marca incongruente",
}

# ── Reconocer el PAPEL de cada campo por su atributo nom="..." ────────────
RE_CAMPO_FECHA = re.compile(r"data|fecha|date|\bdia\b", re.I)
RE_CAMPO_EQUIPO = re.compile(
    r"equip|ordinador|ordenador|dispositiu|dispositivo|m[aà]quina|\bpc\b|host", re.I)
RE_CAMPO_NO_EQUIPO = re.compile(r"tipus|tipo|categor|marca|model", re.I)
# Categoría del EQUIPO: "Categoria", "Tipus d'equip", "Tipo de dispositivo"...
# pero NO "Tipus d'incidència" (eso es el tipo de avería, no del equipo)
RE_CAMPO_TIPO = re.compile(
    r"categor|(tipus|tipo)\W.*(equip|dispositi|m[aà]quina|aparell)|^\s*(tipus|tipo)\s*$", re.I)
# Marca: "Marca", "Marca d'equip", "Fabricant"...
RE_CAMPO_MARCA = re.compile(r"marca|fabricant|brand", re.I)
RE_CAMPO_MODELO = re.compile(r"model", re.I)
RE_CAMPO_SEVERIDAD = re.compile(
    r"prioritat|prioridad|severitat|severidad|gravetat|gravedad|urg[eè]nci|impact|criticitat",
    re.I)
RE_CAMPO_DESCRIPCION = re.compile(r"descripci|detall|detalle|observaci|problema|comentari", re.I)
RE_CAMPO_CORTO = re.compile(
    r"\b(id|codi|codigo|código|code|equip|equipo|aula|ip|mac|prioritat|prioridad|"
    r"estat|estado|tipus|tipo|marca|model|modelo|host|hostname)\b", re.I)

# ── Detectar contenido basura en los valores ──────────────────────────────
RE_FECHA = re.compile(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})")
RE_ANYO = re.compile(r"(?<!\d)\d{4}(?!\d)")
RE_BINARIO = re.compile(r"(?:[01]{8}[\s,;]*){3,}")          # 3 bytes o más
RE_BYTE = re.compile(r"[01]{8}")
RE_AMARICO = re.compile("[ሀ-᎟ⶀ-⷟꬀-꬯]")
RE_BASURA = re.compile("|".join(re.escape(p) for p in PALABRAS_BASURA))

# ── Categorías de equipo (el orden importa: la primera que encaje gana) ──
# Se usan para traducir el valor del campo de categoría del XML a un nombre
# único (p. ej. "Impressora" y "Impressores" -> "Impressores") y, si ese campo
# no existe, para deducir la categoría a partir del equipo o la descripción.
TIPOS_DISPOSITIVO: list[tuple[str, re.Pattern]] = [(n, re.compile(p)) for n, p in [
    ("Portàtil", r"portatil|laptop|notebook|macbook|thinkpad|elitebook|probook|"
                 r"latitude|chromebook|zenbook|vivobook"),
    ("Impressores", r"impres?sor|printer|laserjet|officejet|deskjet|plotter|escaner|"
                    r"scanner|multifunci"),
    ("Servidors", r"servidor|server|\bsrv|\bnas\b|\brack\b|poweredge|proliant"),
    ("Xarxa", r"router|switch|commutador|encaminador|\bap\b|punt d.acces|punto de acceso|"
              r"access point|firewall|\bmodem\b|^xarxa$|^red$"),
    ("Monitors", r"monitor|pantalla|display|projector|proyector"),
    ("Mòbils/Tauletes", r"\bmobil|\bmovil|telefon|tablet|tauleta|ipad|iphone|smartphone"),
    ("Sobretaula", r"\bpc\b|\bpc-|sobretaula|sobremesa|ordinador|ordenador|desktop|"
                   r"optiplex|\bimac\b|\btorre\b|workstation"),
    ("Perifèrics", r"perifer|teclat|teclado|ratoli|raton|mouse|webcam|auricular|"
                   r"altaveu|altavoz"),
]]
CATEGORIA_POR_DEFECTO = "Altres"

# Valores que en realidad significan "no hay dato" (se comparan normalizados)
VALORES_NULOS = {"", "-", "--", "—", "n/a", "na", "null", "none", "cap", "ninguna",
                 "ninguno", "desconeguda", "desconegut", "desconocida", "desconocido",
                 "sense marca", "sin marca"}

# ── Marcas conocidas ──────────────────────────────────────────────────────
# 1) Unifican el valor del campo de marca ("hewlett packard" -> "HP").
# 2) Si el campo no existe o viene vacío / "-", se buscan en el equipo y la
#    descripción (también por modelo: ThinkPad -> Lenovo, OptiPlex -> Dell).
MARCAS_REALES: list[tuple[str, re.Pattern]] = [(n, re.compile(p)) for n, p in [
    ("HP", r"\bh\.?\s?p\b|hewlett|elitebook|probook|laserjet|officejet|deskjet|"
           r"proliant|pavilion"),
    ("Dell", r"\bdell\b|latitude|optiplex|inspiron|poweredge|alienware|vostro"),
    ("Lenovo", r"lenovo|thinkpad|thinkcentre|ideapad"),
    ("Apple", r"\bapple\b|macbook|\bimac\b|mac mini|\bipad\b|iphone"),
    ("Asus", r"\basus\b|zenbook|vivobook"),
    ("Acer", r"\bacer\b|aspire|travelmate"),
    ("MSI", r"\bmsi\b"),
    ("Samsung", r"samsung|galaxy"),
    ("Microsoft", r"microsoft|\bsurface\b"),
    ("Toshiba", r"toshiba|dynabook"),
    ("Fujitsu", r"fujitsu"),
    ("Cisco", r"\bcisco\b|catalyst|meraki"),
    ("TP-Link", r"tp-?link"),
    ("Ubiquiti", r"ubiquiti|unifi"),
    ("Netgear", r"netgear"),
    ("Epson", r"epson"),
    ("Brother", r"\bbrother\b"),
    ("Canon", r"\bcanon\b"),
    ("Xerox", r"xerox"),
    ("Ricoh", r"ricoh"),
    ("Kyocera", r"kyocera"),
    ("Logitech", r"logitech"),
    ("LG", r"\blg\b"),
    ("BenQ", r"benq"),
    ("Huawei", r"huawei"),
    ("Xiaomi", r"xiaomi"),
]]

# ── Severidad ─────────────────────────────────────────────────────────────
NIVELES = ["Crítica", "Alta", "Media", "Leve"]

# 1) Si el XML tiene un campo de prioridad/severidad, se traduce su valor
MAPA_SEVERIDAD: list[tuple[str, re.Pattern]] = [(n, re.compile(p)) for n, p in [
    ("Crítica", r"critic|urgent|bloquejant|bloqueante|maxim"),
    ("Alta", r"\balt[ae]?\b|high|elevad|important"),
    ("Media", r"mitj|medi|normal|moderad"),
    ("Leve", r"baix|baj|leve|lleu|low|menor|minim"),
]]
# 2) Si no lo tiene, se deduce por palabras clave sobre la descripción, el
#    equipo y su categoría (texto normalizado: sin tildes ni mayúsculas).
#    Orden de decisión (ver AnalyticsEngine._severidad):
#      1. CRÍTICA  -> caída de infraestructura (servidor, BD, xarxa caiguda...)
#      2. ALTA     -> hardware grave del equipo (disco, BSOD, placa base...)
#      3. LEVE     -> periféricos (teclat, ratolí, cables, altaveus, impressora)
#      4. ALTA     -> "no arrenca" / "no s'encén", si NO es un periférico
#      5. MEDIA    -> errores genéricos o de software ("no funciona", "no respon"...)
#      6. Sin pistas -> SEVERIDAD_POR_DEFECTO
#    Así "No funciona el teclat" es LEVE (paso 3 antes que el 5) y
#    "No arrenca l'ordinador" es ALTA.
RE_SEV_CRITICA = re.compile(
    r"servidor|server|\bsrv\b|\bsrv-|base de dades|base de datos|database|\bbbdd\b|"
    r"xarxa caiguda|caiguda de (la )?xarxa|red caida|caida de (la )?red|"
    r"(switch|router|commutador|encaminador)s? (principal|central|core|troncal)|"
    r"\bcpd\b|tota la xarxa|toda la red|tot l.institut|todo el centro|ransomware")
RE_SEV_ALTA_HW = re.compile(
    r"disc dur|disco duro|\bssd\b|\bhdd\b|pantalla (blava|azul)|\bbsod\b|blue ?screen|"
    r"pantallazo|placa (base|mare)|motherboard|font d.alimentacio|fuente de alimentacion|"
    r"memoria ram|sobreescalf|sobrecalent|cremat|quemad|virus|malware")
RE_SEV_ALTA_ARRANQUE = re.compile(
    r"no (arrenca|arranca|engega|encen|enciende|inicia)|no s.encen|no se enciende|"
    r"pantalla negra")
RE_SEV_LEVE = re.compile(
    r"perifer|teclat|teclado|ratoli|raton|mouse|cable|altaveu|altavoz|auricular|webcam|"
    r"impres?sor|printer|toner|tinta|\bpaper\b|\bpapel\b|alfombreta|\busb\b")
RE_SEV_MEDIA = re.compile(
    r"no funciona|no (respon|responde)|error|falla|bloquejad|bloquejat|bloquead|penjat|"
    r"se cuelga|es penja|\blent|lento|pantalla secundaria|segona pantalla|"
    r"segunda pantalla|programa|aplicacio|software|actualitz|actualiz|contrasenya|"
    r"password|reinici|intermitent|sense connexio|sin conexion|wifi")
SEVERIDAD_POR_DEFECTO = "Media"   # Sin pistas: mejor no infravalorar

# ── Categorías de anomalía (opciones del filtro) ──────────────────────────
CAT_FECHA = "Fechas imposibles"
CAT_BASURA = "Contenido basura"
CAT_DESBORDE = "Desbordamiento de texto"
CAT_VACIO = "Campos vacíos / incompletos"
CATEGORIAS = [CAT_FECHA, CAT_BASURA, CAT_DESBORDE, CAT_VACIO]

# ── Estética ──────────────────────────────────────────────────────────────
NEON_ROSA = "#ff2bd6"
NEON_CIAN = "#00f0ff"
NEON_VERDE = "#39ff14"
NEON_ROJO = "#ff3860"
NEON_NARANJA = "#ff9f1c"
NEON_AMARILLO = "#ffe600"
ZEBRA = "on grey15"
COLOR_SEVERIDAD = {"Crítica": NEON_ROJO, "Alta": NEON_NARANJA,
                   "Media": NEON_AMARILLO, "Leve": NEON_VERDE}
SPARK = "▁▂▃▄▅▆▇█"
BLOQUES_PARCIALES = " ▏▎▍▌▋▊▉"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Fechas que escribe el usuario en el filtro por rango
RE_FECHA_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")    # AAAA-MM-DD
RE_FECHA_EU = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")     # DD/MM/AAAA

ESTILO_MENU = questionary.Style([
    ("qmark", f"fg:{NEON_ROSA} bold"),
    ("question", "bold"),
    ("pointer", f"fg:{NEON_CIAN} bold"),
    ("highlighted", f"fg:{NEON_CIAN} bold"),
    ("answer", f"fg:{NEON_ROSA} bold"),
])

# questionary necesita una terminal real; si no la hay, menús numerados
INTERACTIVO = sys.stdin.isatty() and sys.stdout.isatty()


# ══════════════════════════════════════════════════════════════════════════
# 2. UTILIDADES PURAS (sin estado)
# ══════════════════════════════════════════════════════════════════════════

def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, '&' -> 'and' y espacios simples."""
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    sin_tildes = sin_tildes.lower().replace("&", " and ")
    return " ".join(sin_tildes.split())


def truncar(texto: str | None, limite: int = MAX_TRUNCAR) -> str:
    """Una sola línea y como máximo `limite` caracteres + [...]."""
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[:limite] + "[...]"


def limpiar_ruta(entrada: str | None) -> Path:
    """Limpia una ruta escrita o arrastrada (comillas y '& ' de PowerShell)."""
    entrada = (entrada or "").strip()
    if entrada.startswith("& "):
        entrada = entrada[2:].strip()
    return Path(entrada.strip("'\"")).expanduser()


def texto_seguro(elemento: ET.Element | None) -> str:
    """Texto de un elemento, o "" si es None o una etiqueta de autocierre.

    Equivale a un `.text` condicional, pero itertext() también junta el texto
    de posibles subetiquetas. Nunca lanza AttributeError.
    """
    if elemento is None:
        return ""
    return "".join(elemento.itertext()).strip()


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


def decodificar_binario(valor: str) -> str:
    """Intenta leer los bytes binarios como texto (para la ficha de rechazo)."""
    try:
        datos = bytes(int(b, 2) for b in RE_BYTE.findall(valor))
        texto = datos.decode("utf-8", errors="replace")
        return "".join(c if c.isprintable() else "·" for c in texto)
    except ValueError:
        return ""


def valor_real(valor: str | None) -> str:
    """Valor limpio del campo, o "" si es vacío, "-", "N/A", "Sense marca"..."""
    limpio = " ".join((valor or "").split())
    return "" if normalizar(limpio) in VALORES_NULOS else limpio


def canonico(texto_normalizado: str, tabla: list[tuple[str, re.Pattern]]) -> str | None:
    """Primer nombre de `tabla` cuyo patrón aparece en el texto."""
    for nombre, patron in tabla:
        if patron.search(texto_normalizado):
            return nombre
    return None


def parsear_fecha_usuario(texto: str) -> date | None:
    """Acepta AAAA-MM-DD o DD/MM/AAAA. Devuelve None si no es una fecha real."""
    texto = texto.strip()
    if coincidencia := RE_FECHA_ISO.match(texto):
        anyo, mes, dia = coincidencia.groups()
    elif coincidencia := RE_FECHA_EU.match(texto):
        dia, mes, anyo = coincidencia.groups()
    else:
        return None
    try:
        return date(int(anyo), int(mes), int(dia))
    except ValueError:            # 31/02/2025, mes 13, año 0000...
        return None


# ══════════════════════════════════════════════════════════════════════════
# 3. MODELO DE DATOS
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Anomalia:
    """Una regla violada."""
    categoria: str          # Una de CATEGORIAS
    regla: str              # Causa precisa, legible
    campo: str = "—"        # Dónde se ha detectado
    valor: str = ""         # Contenido corrupto extraído
    extra: str = ""         # Pista adicional (p. ej. binario decodificado)


@dataclass
class Incidencia:
    """Una <incidencia> del XML, ya enriquecida."""
    id: str
    campos: dict[str, str] = field(default_factory=dict)   # Campos con valor
    vacios: list[str] = field(default_factory=list)        # Etiquetas vacías
    sin_id: bool = False
    anomalias: list[Anomalia] = field(default_factory=list)
    # Rellenados por AnomalyDetector / AnalyticsEngine
    fecha: date | None = None
    equipo: str = ""
    descripcion: str = ""
    tipo: str = CATEGORIA_POR_DEFECTO   # Categoría del equipo
    marca: str | None = None
    severidad: str = "Leve"
    severidad_inferida: bool = True

    @property
    def valida(self) -> bool:
        return not self.anomalias

    def categorias(self) -> set[str]:
        return {a.categoria for a in self.anomalias}

    def buscar_campo(self, patron: re.Pattern,
                     excluir: re.Pattern | None = None) -> tuple[str, str] | None:
        """Primer (nombre, valor) cuyo nombre encaja con `patron`."""
        for nombre, valor in self.campos.items():
            if patron.search(nombre) and not (excluir and excluir.search(nombre)):
                return nombre, valor
        return None


class ErrorCarga(Exception):
    """Error controlado al cargar el XML (título + mensaje para el panel)."""

    def __init__(self, titulo: str, mensaje: str):
        super().__init__(mensaje)
        self.titulo = titulo
        self.mensaje = mensaje


# ══════════════════════════════════════════════════════════════════════════
# 4. XMLParser — lectura y parseo seguro
# ══════════════════════════════════════════════════════════════════════════

class XMLParser:
    """Convierte el archivo en una lista de Incidencia.

    Usa ET.iterparse: procesa cada <incidencia> en cuanto se cierra y la
    libera con elem.clear(), así la memoria no crece con archivos grandes.
    """

    ETIQUETA_INCIDENCIA = "incidencia"
    ETIQUETA_CAMPO = "camp"

    def cargar(self, ruta: Path) -> tuple[str, list[Incidencia]]:
        """Devuelve (etiqueta_raíz, incidencias) o lanza ErrorCarga."""
        if not ruta.exists():
            raise ErrorCarga("Archivo no encontrado", f"No existe el archivo:\n{ruta}")
        if not ruta.is_file():
            raise ErrorCarga("Ruta no válida", f"La ruta no es un archivo:\n{ruta}")

        raiz = ""
        incidencias: list[Incidencia] = []
        try:
            for evento, elem in ET.iterparse(str(ruta), events=("start", "end")):
                if evento == "start":
                    raiz = raiz or elem.tag          # La primera etiqueta es la raíz
                elif elem.tag == self.ETIQUETA_INCIDENCIA:
                    incidencias.append(self._convertir(elem, len(incidencias) + 1))
                    elem.clear()                     # Libera memoria
        except FileNotFoundError:
            raise ErrorCarga("Archivo no encontrado", f"No existe el archivo:\n{ruta}") from None
        except PermissionError:
            raise ErrorCarga("Sin permisos", f"No tienes permiso para leer:\n{ruta}") from None
        except ET.ParseError as error:
            raise ErrorCarga("XML malformado",
                             f"El documento no es un XML bien formado.\n{error}") from None
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise ErrorCarga("Error de lectura", f"No se puede leer el archivo.\n{error}") from None

        return raiz, incidencias

    def _convertir(self, nodo: ET.Element, posicion: int) -> Incidencia:
        id_xml = (nodo.get("id") or "").strip()          # .get() con fallback
        inc = Incidencia(id=id_xml or f"SIN-ID-{posicion}", sin_id=not id_xml)

        for camp in nodo.iter(self.ETIQUETA_CAMPO):
            nombre = (camp.get("nom") or "").strip() or "(sin nombre)"
            valor = texto_seguro(camp)

            # Campo repetido en la misma incidencia: se numera, no se pisa
            clave, n = nombre, 2
            while clave in inc.campos or clave in inc.vacios:
                clave, n = f"{nombre} ({n})", n + 1

            if valor:
                inc.campos[clave] = valor
            else:
                inc.vacios.append(clave)     # <camp nom="X"/> o <camp nom="X"></camp>
        return inc


# ══════════════════════════════════════════════════════════════════════════
# 5. AnomalyDetector — motor de validación
# ══════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """Aplica todas las reglas y rellena `incidencia.anomalias`.

    Cada regla recibe (nombre_campo, valor) y devuelve None si el campo está
    bien, o una Anomalia con la causa precisa.
    """

    def __init__(self, anyo_minimo: int = ANYO_MINIMO, hoy: date | None = None):
        self.anyo_minimo = anyo_minimo
        self.hoy = hoy or date.today()
        self.obligatorios = {normalizar(c): c for c in CAMPOS_OBLIGATORIOS}
        self.reglas: tuple[Callable[[Incidencia, str, str], Anomalia | None], ...] = (
            self._regla_fecha,
            self._regla_binario,
            self._regla_amarico,
            self._regla_palabras,
            self._regla_desbordamiento,
        )

    def validar(self, inc: Incidencia) -> Incidencia:
        inc.anomalias.clear()

        # ── Incompletitud ──────────────────────────────────────────────────
        if inc.sin_id:
            inc.anomalias.append(Anomalia(CAT_VACIO, "Incidencia sin atributo id"))
        if not inc.campos and not inc.vacios:
            inc.anomalias.append(Anomalia(CAT_VACIO, "Incidencia sin ningún campo"))
        for nombre in inc.vacios:
            if RE_CAMPO_OPCIONAL.search(nombre):
                continue                     # Marca/modelo vacíos: no es motivo de rechazo
            inc.anomalias.append(Anomalia(
                CAT_VACIO, "Campo obligatorio vacío / etiqueta de autocierre",
                nombre, f'<camp nom="{nombre}"/>'))

        presentes = {normalizar(n) for n in (*inc.campos, *inc.vacios)}
        for clave, original in self.obligatorios.items():
            if clave not in presentes:
                inc.anomalias.append(Anomalia(
                    CAT_VACIO, "Campo obligatorio ausente", original, "(no existe)"))

        # ── Contenido, campo a campo ───────────────────────────────────────
        for nombre, valor in inc.campos.items():
            for regla in self.reglas:
                anomalia = regla(inc, nombre, valor)
                if anomalia:
                    inc.anomalias.append(anomalia)
        return inc

    # ── Reglas ─────────────────────────────────────────────────────────────

    @staticmethod
    def _donde(nombre: str) -> str:
        """Añade 'en código de equipo' si la basura está en un campo breve."""
        return f" en campo de código «{nombre}»" if RE_CAMPO_CORTO.search(nombre) else ""

    def _anyo_incorrecto(self, anyo: int, valor: str) -> str | None:
        if anyo < self.anyo_minimo:
            return f"Fecha imposible: {anyo:04d}"
        if anyo > self.hoy.year:
            return f"Fecha futura: {anyo}"
        return None

    def _regla_fecha(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        """Solo se aplica a campos cuyo nombre indica una fecha."""
        if not RE_CAMPO_FECHA.search(nombre):
            return None

        def mal(regla: str) -> Anomalia:
            return Anomalia(CAT_FECHA, regla, nombre, valor)

        partes = RE_FECHA.search(valor)
        if partes:
            a, b, c = partes.groups()
            anyo, mes, dia = (a, b, c) if len(a) == 4 else (c, b, a)   # AAAA-MM-DD o DD/MM/AAAA
            if len(anyo) != 4:
                return mal("Fecha con formato no reconocido")
            regla = self._anyo_incorrecto(int(anyo), valor)
            if regla:
                return mal(regla)
            try:
                fecha = date(int(anyo), int(mes), int(dia))
            except ValueError:
                return mal(f"Fecha imposible: {valor.strip()} (día o mes inexistente)")
            if fecha > self.hoy:
                return mal(f"Fecha futura: {fecha:%d/%m/%Y}")
            inc.fecha = fecha
            return None

        anyos = RE_ANYO.findall(valor)
        if not anyos:
            return mal("Fecha sin formato reconocible")
        for anyo in anyos:
            regla = self._anyo_incorrecto(int(anyo), valor)
            if regla:
                return mal(regla)
        return None

    def _regla_binario(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if not RE_BINARIO.search(valor):
            return None
        decodificado = decodificar_binario(valor)
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: secuencia de código binario",
                        nombre, valor,
                        f"Decodificado: «{decodificado}»" if decodificado else "")

    def _regla_amarico(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if not RE_AMARICO.search(valor):
            return None
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: texto en amárico",
                        nombre, valor)

    def _regla_palabras(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        encontradas = sorted(set(RE_BASURA.findall(normalizar(valor))))
        if not encontradas:
            return None
        tipos = sorted({PALABRAS_BASURA[p] for p in encontradas})
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: {', '.join(tipos)}",
                        nombre, valor, "Palabras: " + ", ".join(encontradas))

    def _regla_desbordamiento(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if RE_CAMPO_CORTO.search(nombre) and len(valor) > MAX_LONGITUD_CORTO:
            return Anomalia(CAT_DESBORDE,
                            f"Desbordamiento de texto: >{MAX_LONGITUD_CORTO} caracteres "
                            f"({len(valor)}) en un campo breve",
                            nombre, valor)
        return None


# ══════════════════════════════════════════════════════════════════════════
# 6. AnalyticsEngine — enriquecimiento y métricas (calculadas una vez)
# ══════════════════════════════════════════════════════════════════════════

class AnalyticsEngine:
    """Deduce tipo, marca, equipo y severidad, y guarda todas las métricas."""

    def __init__(self, incidencias: list[Incidencia]):
        self.todas = incidencias
        for inc in incidencias:
            self._enriquecer(inc)

        self.validas = [i for i in incidencias if i.valida]
        self.anomalas = [i for i in incidencias if not i.valida]

        # Métricas cacheadas: los menús solo las leen
        self.por_tipo = Counter(i.tipo for i in self.validas)
        self.por_equipo = Counter(i.equipo for i in self.validas if i.equipo)
        self.por_severidad = Counter(i.severidad for i in self.validas)
        self.por_marca = Counter(i.marca for i in self.validas if i.marca)
        self.por_categoria = Counter(c for i in self.anomalas for c in i.categorias())
        self.por_mes = Counter((i.fecha.year, i.fecha.month) for i in self.validas if i.fecha)
        self.indice_id: dict[str, list[Incidencia]] = {}
        for inc in incidencias:
            self.indice_id.setdefault(inc.id.strip().lower(), []).append(inc)

    # ── Enriquecimiento ────────────────────────────────────────────────────

    def _enriquecer(self, inc: Incidencia) -> None:
        equipo = inc.buscar_campo(RE_CAMPO_EQUIPO, excluir=RE_CAMPO_NO_EQUIPO)
        inc.equipo = equipo[1].strip() if equipo else ""

        descripcion = inc.buscar_campo(RE_CAMPO_DESCRIPCION)
        if descripcion:
            inc.descripcion = descripcion[1]
        elif inc.campos:   # Sin campo claro: el texto más largo
            inc.descripcion = max(inc.campos.values(), key=len)

        modelo = inc.buscar_campo(RE_CAMPO_MODELO, excluir=RE_CAMPO_MARCA)
        texto_equipo = normalizar(" ".join(filter(None, [
            inc.equipo, modelo[1] if modelo else ""])))
        texto_desc = normalizar(inc.descripcion)

        inc.tipo = self._categoria(inc, texto_equipo, texto_desc)
        inc.marca = self._marca(inc, texto_equipo, texto_desc)
        texto_severidad = " ".join((texto_desc, texto_equipo, normalizar(inc.tipo)))
        inc.severidad, inc.severidad_inferida = self._severidad(inc, texto_severidad)

    @staticmethod
    def _categoria(inc: Incidencia, texto_equipo: str, texto_desc: str) -> str:
        """1) Valor real del campo de categoría (unificado si se reconoce).
        2) Si no hay campo o viene vacío / "-": se deduce del equipo y,
           si el equipo no aclara nada, de la descripción."""
        campo = inc.buscar_campo(RE_CAMPO_TIPO)
        if campo and (real := valor_real(campo[1])):
            return canonico(normalizar(real), TIPOS_DISPOSITIVO) or real
        for texto in (texto_equipo, texto_desc):
            if nombre := canonico(texto, TIPOS_DISPOSITIVO):
                return nombre
        return CATEGORIA_POR_DEFECTO

    @staticmethod
    def _marca(inc: Incidencia, texto_equipo: str, texto_desc: str) -> str | None:
        """1) Valor real del nodo <camp nom="Marca..."> (se unifica si es una
              marca conocida: "hewlett packard" -> "HP"; si no, se respeta tal cual).
        2) Si falta, está vacío o es "-": REGEX de marcas conocidas sobre el
           equipo/modelo y después sobre la descripción.
        Las marcas basura (Pull & Bear...) no llegan aquí como válidas: el
        AnomalyDetector ya ha rechazado esas incidencias."""
        campo = inc.buscar_campo(RE_CAMPO_MARCA)
        if campo and (real := valor_real(campo[1])):
            return canonico(normalizar(real), MARCAS_REALES) or real
        for texto in (texto_equipo, texto_desc):
            if nombre := canonico(texto, MARCAS_REALES):
                return nombre
        return None

    @staticmethod
    def _severidad(inc: Incidencia, texto: str) -> tuple[str, bool]:
        """Devuelve (nivel, inferida). Si el XML trae un campo de prioridad se
        usa ese valor; si no, se aplica el orden explicado en la configuración."""
        campo = inc.buscar_campo(RE_CAMPO_SEVERIDAD)
        if campo:
            valor = normalizar(campo[1])
            for nivel, patron in MAPA_SEVERIDAD:
                if patron.search(valor):
                    return nivel, False

        if RE_SEV_CRITICA.search(texto):
            return "Crítica", True
        if RE_SEV_ALTA_HW.search(texto):
            return "Alta", True
        es_periferico = bool(RE_SEV_LEVE.search(texto))
        if RE_SEV_ALTA_ARRANQUE.search(texto) and not es_periferico:
            return "Alta", True
        if es_periferico:
            return "Leve", True
        if RE_SEV_MEDIA.search(texto):
            return "Media", True
        return SEVERIDAD_POR_DEFECTO, True

    # ── Consultas ──────────────────────────────────────────────────────────

    @property
    def pct_validas(self) -> float:
        return len(self.validas) / len(self.todas) * 100 if self.todas else 0.0

    def actividad_mensual(self, meses: int = 12) -> list[tuple[str, int]]:
        """Últimos `meses` meses con datos: [('2025-03', 4), ...]."""
        ordenados = sorted(self.por_mes.items())[-meses:]
        return [(f"{a}-{m:02d}", n) for (a, m), n in ordenados]

    def por_id(self, texto: str) -> list[Incidencia]:
        return self.indice_id.get(texto.strip().lower(), [])

    def buscar_texto(self, termino: str) -> list[tuple[Incidencia, str, str]]:
        """Una fila por incidencia: (incidencia, campo, valor) de la 1ª coincidencia."""
        buscado = normalizar(termino)
        resultados = []
        for inc in self.todas:
            for campo, valor in inc.campos.items():
                if buscado in normalizar(valor):
                    resultados.append((inc, campo, valor))
                    break
        return resultados


# ══════════════════════════════════════════════════════════════════════════
# 7. EntradaUsuario — todas las lecturas de teclado, saneadas
# ══════════════════════════════════════════════════════════════════════════

class EntradaUsuario:
    """Nunca devuelve un dato inválido ni deja escapar un ValueError.

    Ctrl+C (o el cierre de la entrada) se convierte en KeyboardInterrupt,
    que sube hasta main() para cerrar con la despedida.
    """

    def __init__(self, consola: Console):
        self.consola = consola

    def error(self, mensaje: str) -> None:
        self.consola.print(f"[bold {NEON_ROJO}]✖ {mensaje}[/]")

    def linea(self, mensaje: str) -> str:
        try:
            return self.consola.input(mensaje)
        except EOFError:
            raise KeyboardInterrupt from None

    def seleccionar(self, mensaje: str, opciones: list[str]) -> str:
        """Menú con flechas (o numerado si no hay terminal interactiva)."""
        if INTERACTIVO:
            return questionary.select(mensaje, choices=opciones, style=ESTILO_MENU,
                                      qmark="➤", pointer="❯").unsafe_ask()
        self.consola.print(f"[bold]{escape(mensaje)}[/]")
        for i, opcion in enumerate(opciones, start=1):
            self.consola.print(f"  {i}. {escape(opcion)}")
        while True:
            entrada = self.linea("Opción: ").strip()
            try:
                numero = int(entrada)
            except ValueError:
                self.error(f"«{escape(entrada)}» no es un número de la lista.")
                continue
            if 1 <= numero <= len(opciones):
                return opciones[numero - 1]
            self.error(f"Elige un número entre 1 y {len(opciones)}.")

    def texto(self, mensaje: str) -> str:
        if INTERACTIVO:
            return (questionary.text(mensaje, style=ESTILO_MENU, qmark="➤").unsafe_ask() or "").strip()
        return self.linea(f"{mensaje} ").strip()

    def letra(self, mensaje: str, validas: str) -> str:
        while True:
            letra = self.linea(mensaje).strip().upper()
            if len(letra) == 1 and letra in validas:
                return letra
            self.error(f"Opción no válida. Usa: {', '.join(validas)}.")

    def numero(self, mensaje: str, minimo: int, maximo: int) -> int | None:
        """Entero en [minimo..maximo]; Enter vacío = cancelar (None)."""
        while True:
            entrada = self.linea(mensaje).strip()
            if not entrada:
                return None
            try:
                numero = int(entrada)
            except ValueError:
                self.error(f"«{escape(entrada)}» no es un número. Enter para cancelar.")
                continue
            if minimo <= numero <= maximo:
                return numero
            self.error(f"La página {numero} no existe. Elige entre {minimo} y {maximo}.")

    def fecha(self, mensaje: str) -> date | None:
        """Pide una fecha hasta que sea válida. Enter vacío = cancelar (None)."""
        while True:
            entrada = self.linea(mensaje).strip()
            if not entrada:
                return None
            if (fecha := parsear_fecha_usuario(entrada)) is not None:
                return fecha
            self.error(f"«{escape(entrada)}» no es una fecha válida. "
                       "Usa AAAA-MM-DD (p. ej. 2025-03-15) o DD/MM/AAAA. Enter para cancelar.")

    def ruta(self) -> Path:
        """Pide una ruta no vacía; propone respotes.xml si lo encuentra."""
        propuesta = ""
        for carpeta in (Path.cwd(), Path(__file__).resolve().parent):
            if (carpeta / NOMBRE_XML_DEFECTO).is_file():
                propuesta = str(carpeta / NOMBRE_XML_DEFECTO)
                break
        while True:
            if INTERACTIVO:
                entrada = questionary.path(
                    "Ruta del archivo XML (escríbela, usa Tab o arrastra el archivo):",
                    default=propuesta, style=ESTILO_MENU, qmark="➤").unsafe_ask()
            else:
                entrada = self.linea("Ruta del archivo XML: ")
            if (entrada or "").strip():
                return limpiar_ruta(entrada)
            self.error("Escribe una ruta.")

    def pausa(self) -> None:
        if INTERACTIVO:
            questionary.press_any_key_to_continue("Pulsa una tecla para volver...").unsafe_ask()
        else:
            self.linea("Pulsa Enter para volver...")


# ══════════════════════════════════════════════════════════════════════════
# 8. Paginator — listados con [N] [P] [G] [Q] (+ acciones extra)
# ══════════════════════════════════════════════════════════════════════════

# Una acción extra: tecla -> (texto del pie, función a ejecutar)
AccionExtra = dict[str, tuple[str, Callable[[], None]]]
ConstructorTabla = Callable[[Sequence, int, int], Table]


class Paginator:
    def __init__(self, consola: Console, entrada: EntradaUsuario, por_pagina: int = POR_PAGINA):
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

    def mostrar(self, elementos: Sequence, construir: ConstructorTabla, vacio: str,
                extras: AccionExtra | None = None) -> None:
        extras = extras or {}
        if not elementos:
            self.consola.print(Panel(vacio, border_style=NEON_AMARILLO))
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
# 9. CLIInterface — todo lo que se ve
# ══════════════════════════════════════════════════════════════════════════

class CLIInterface:
    OP_VALIDAS = "✔  Incidencias válidas"
    OP_ANOMALIAS = "✖  Registro de anomalías y fichas de rechazo"
    OP_SEVERIDAD = "▲  Explorar por severidad"
    OP_GRAFICAS = "▇  Gráficas de averías (categorías y equipos)"
    OP_MARCAS = "◉  Filtrar por marca o categoría de equipo"
    OP_FECHAS = "▣  Filtrar por fechas"
    OP_BUSCAR = "⌕  Buscar por texto o ID"
    OP_SALIR = "⏻  Salir"

    def __init__(self, consola: Console, ruta_inicial: Path | None = None):
        self.consola = consola
        self.entrada = EntradaUsuario(consola)
        self.paginador = Paginator(consola, self.entrada)
        self.ruta_inicial = ruta_inicial
        self.ruta: Path | None = None
        self.datos: AnalyticsEngine | None = None

    # ── Arranque: carga con reintento ──────────────────────────────────────

    def cargar(self) -> bool:
        """Pide/usa la ruta y carga el XML. Si falla, ofrece reintentar o salir."""
        ruta = self.ruta_inicial
        parser, detector = XMLParser(), AnomalyDetector()

        while True:
            if ruta is None:
                ruta = self.entrada.ruta()
            try:
                with self.consola.status(f"[{NEON_CIAN}]Escaneando el XML...[/]", spinner="dots"):
                    raiz, incidencias = parser.cargar(ruta)
                    if not incidencias:
                        raise ErrorCarga("Sin datos", "El XML no contiene ninguna <incidencia>.")
                    for inc in incidencias:
                        detector.validar(inc)
                    datos = AnalyticsEngine(incidencias)
            except ErrorCarga as error:
                self.panel_error(error.titulo, error.mensaje)
                otra, misma, salir = ("↻  Probar con otra ruta",
                                      "⟳  Reintentar el mismo archivo", "⏻  Salir")
                eleccion = self.entrada.seleccionar("¿Qué quieres hacer?", [otra, misma, salir])
                if eleccion == salir:
                    return False
                if eleccion == otra:
                    ruta = None
                continue

            if raiz != "incidencies":
                self.consola.print(f"[{NEON_AMARILLO}]⚠ La raíz es <{escape(raiz)}>, "
                                   f"se esperaba <incidencies>.[/]")
            self.ruta, self.datos = ruta, datos
            return True

    def ejecutar(self) -> int:
        if not self.cargar():
            return 1
        acciones = {
            self.OP_VALIDAS: self.ver_validas,
            self.OP_ANOMALIAS: self.ver_anomalias,
            self.OP_SEVERIDAD: self.ver_severidad,
            self.OP_GRAFICAS: self.ver_graficas,
            self.OP_MARCAS: self.ver_marcas,
            self.OP_FECHAS: self.ver_fechas,
            self.OP_BUSCAR: self.buscar,
        }
        while True:
            self.consola.clear()
            self.dashboard()
            eleccion = self.entrada.seleccionar("¿Qué quieres hacer?", [*acciones, self.OP_SALIR])
            if eleccion == self.OP_SALIR:
                return 0
            acciones[eleccion]()

    # ── Paneles genéricos ──────────────────────────────────────────────────

    def panel_error(self, titulo: str, mensaje: str) -> None:
        self.consola.print(Panel(Text(mensaje), title=f"[bold {NEON_ROJO}]✖ {escape(titulo)}[/]",
                                 border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2)))

    @staticmethod
    def tabla_barras(pares: Sequence[tuple[str, int]], color: str | dict[str, str],
                     ancho: int = 36) -> Table:
        """Gráfico de barras horizontales: etiqueta | barra | número."""
        tabla = Table(box=None, show_header=False, padding=(0, 1))
        tabla.add_column(style="bold white", no_wrap=True)
        tabla.add_column(no_wrap=True)
        tabla.add_column(justify="right", style=f"bold {NEON_ROSA}")
        maximo = max((n for _, n in pares), default=0)
        for etiqueta, n in pares:
            tono = color.get(etiqueta, NEON_CIAN) if isinstance(color, dict) else color
            tabla.add_row(truncar(etiqueta, 24), Text(barra(n, maximo, ancho), style=tono), str(n))
        return tabla

    def _tarjeta(self, titulo: str, valor: str, sub: str, color: str) -> Panel:
        contenido = Text(justify="center")
        contenido.append(f"{valor}\n", style=f"bold {color}")
        contenido.append(sub, style="dim")
        return Panel(contenido, title=f"[bold]{titulo}[/]", border_style=color,
                     box=box.HEAVY, width=22, padding=(1, 1))

    # ── Dashboard ──────────────────────────────────────────────────────────

    def dashboard(self) -> None:
        d = self.datos
        total, pct = len(d.todas), d.pct_validas

        tarjetas = Columns([
            self._tarjeta("Procesadas", str(total), "incidencias", NEON_CIAN),
            self._tarjeta("Válidas", str(len(d.validas)), f"{pct:.1f} %", NEON_VERDE),
            self._tarjeta("Bloqueadas", str(len(d.anomalas)), f"{100 - pct:.1f} %", NEON_ROJO),
            self._tarjeta("Críticas", str(d.por_severidad.get("Crítica", 0)),
                          "entre las válidas", NEON_NARANJA),
        ])

        ancho = 50
        verdes = round(ancho * pct / 100)
        validez = Text.assemble(("Validez   ", "bold"), ("█" * verdes, NEON_VERDE),
                                ("█" * (ancho - verdes), NEON_ROJO), (f"  {pct:.1f} %", "dim"))

        # Mini-gráficos sparkline
        meses = d.actividad_mensual()
        spark = Table(box=None, show_header=False, padding=(0, 1))
        spark.add_column(style="bold")
        spark.add_column(style=f"bold {NEON_CIAN}", no_wrap=True)
        spark.add_column(style="dim")
        if meses:
            spark.add_row("Actividad mensual", sparkline([n for _, n in meses]),
                          f"{meses[0][0]} → {meses[-1][0]}")
        spark.add_row("Severidad", Text(sparkline([d.por_severidad.get(n, 0) for n in NIVELES]),
                                        style=NEON_NARANJA), "Crítica → Leve")
        top = d.por_equipo.most_common(TOP_EQUIPOS)
        if top:
            spark.add_row("Top equipos", sparkline([n for _, n in top]),
                          f"líder: {truncar(top[0][0], 22)} ({top[0][1]})")
        spark.add_row("Anomalías por tipo",
                      Text(sparkline([d.por_categoria.get(c, 0) for c in CATEGORIAS]), style=NEON_ROJO),
                      " · ".join(f"{c.split()[0]} {d.por_categoria.get(c, 0)}" for c in CATEGORIAS))

        self.consola.print(Panel(
            Group(Text.assemble(("Archivo: ", "dim"), (str(self.ruta), "bold")), Text(""),
                  tarjetas, Text(""), validez, Text(""), spark),
            title=f"[bold {NEON_ROSA}]◆ ESCÁNER DE INCIDENCIAS XML ◆[/]",
            subtitle=f"[{NEON_CIAN}]↑↓ moverte · Enter elegir · Ctrl+C salir[/]",
            border_style=NEON_ROSA, box=box.DOUBLE, padding=(1, 2)))

    # ── Tablas ─────────────────────────────────────────────────────────────

    def _texto_severidad(self, inc: Incidencia) -> Text:
        texto = Text(inc.severidad, style=f"bold {COLOR_SEVERIDAD[inc.severidad]}")
        if inc.severidad_inferida:
            texto.append(" *", style="dim")
        return texto

    def _constructor_validas(self, titulo: str) -> ConstructorTabla:
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
                    inc.tipo, inc.marca or "—",
                    self._texto_severidad(inc),
                    Text(truncar(inc.descripcion or "—")),
                    Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}"))
            return tabla
        return construir

    def _constructor_anomalias(self, categoria: str | None) -> ConstructorTabla:
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

    def _constructor_busqueda(self, termino: str) -> ConstructorTabla:
        def construir(items, pagina: int, total_pag: int) -> Table:
            tabla = Table(title=f"[bold {NEON_CIAN}]Resultados para «{escape(termino)}»[/]",
                          box=box.ROUNDED, border_style=NEON_CIAN,
                          header_style=f"bold {NEON_ROSA}", row_styles=["", ZEBRA], expand=True)
            tabla.add_column("ID", no_wrap=True)
            tabla.add_column("Estado", no_wrap=True)
            tabla.add_column("Campo", overflow="fold")
            tabla.add_column("Coincidencia", overflow="fold", ratio=3)
            for inc, campo, valor in items:
                estado = (Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}") if inc.valida
                          else Text("✖ RECHAZADA", style=f"bold {NEON_ROJO}"))
                tabla.add_row(Text(truncar(inc.id, 15), style=f"bold {NEON_AMARILLO}"), estado,
                              Text(truncar(campo, 22), style=NEON_CIAN), Text(truncar(valor)))
            return tabla
        return construir

    # ── Fichas ─────────────────────────────────────────────────────────────

    def _tabla_campos(self, inc: Incidencia) -> Table:
        tabla = Table(box=box.SIMPLE_HEAD, row_styles=["", ZEBRA],
                      header_style=f"bold {NEON_ROSA}", expand=True)
        tabla.add_column("Campo del XML", style=f"bold {NEON_CIAN}")
        tabla.add_column("Valor", overflow="fold", ratio=3)
        for nombre, valor in inc.campos.items():
            tabla.add_row(truncar(nombre, 30), Text(truncar(valor)))
        for nombre in inc.vacios:
            tabla.add_row(truncar(nombre, 30), Text("(vacío)", style=f"bold {NEON_ROJO}"))
        return tabla

    def ficha_rechazo(self, inc: Incidencia) -> Panel:
        """Panel de diagnóstico: ID, cada regla violada y el contenido corrupto."""
        cabecera = Table.grid(padding=(0, 2))
        cabecera.add_column(style="dim")
        cabecera.add_column()
        cabecera.add_row("ID", Text(inc.id, style=f"bold {NEON_AMARILLO}"))
        cabecera.add_row("Veredicto", Text("✖ RECHAZADA", style=f"bold {NEON_ROJO}"))
        cabecera.add_row("Reglas violadas", Text(str(len(inc.anomalias)), style="bold"))
        cabecera.add_row("Categorías", Text(", ".join(sorted(inc.categorias())), style=NEON_ROSA))

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
                           Text("Registro completo", style="bold"), self._tabla_campos(inc)),
                     title=f"[bold {NEON_ROJO}]FICHA DE RECHAZO · ID {escape(inc.id)}[/]",
                     border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2))

    def ficha_valida(self, inc: Incidencia) -> Panel:
        resumen = Text.assemble(
            ("✔ VÁLIDA", f"bold {NEON_VERDE}"), ("   Severidad: ", "dim"),
            self._texto_severidad(inc), ("   Categoría: ", "dim"), (inc.tipo, "bold"),
            ("   Marca: ", "dim"), (inc.marca or "—", "bold"))
        return Panel(Group(resumen, Text(""), self._tabla_campos(inc)),
                     title=f"[bold {NEON_VERDE}]FICHA · ID {escape(inc.id)}[/]",
                     border_style=NEON_VERDE, box=box.HEAVY, padding=(1, 2))

    def mostrar_fichas(self, incidencias: list[Incidencia]) -> None:
        self.consola.clear()
        for inc in incidencias:          # Puede haber IDs repetidos en el XML
            self.consola.print(self.ficha_valida(inc) if inc.valida else self.ficha_rechazo(inc))
        self.entrada.pausa()

    def inspeccionar_id(self, solo_anomalas: bool = False) -> None:
        """Pide un ID hasta que exista (Enter cancela) y muestra su ficha."""
        while True:
            texto = self.entrada.texto("ID a inspeccionar (Enter para cancelar):")
            if not texto:
                return
            encontradas = self.datos.por_id(texto)
            if solo_anomalas:
                encontradas = [i for i in encontradas if not i.valida]
            if encontradas:
                self.mostrar_fichas(encontradas)
                return
            tipo = "anómala " if solo_anomalas else ""
            self.entrada.error(f"No hay ninguna incidencia {tipo}con ID «{escape(texto)}».")

    # ── Vistas del menú ────────────────────────────────────────────────────

    def ver_validas(self) -> None:
        self.paginador.mostrar(self.datos.validas,
                               self._constructor_validas("Incidencias válidas"),
                               "No hay incidencias válidas.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})

    def ver_anomalias(self) -> None:
        d = self.datos
        opciones = {f"Todas ({len(d.anomalas)})": None}
        opciones.update({f"{c} ({d.por_categoria.get(c, 0)})": c for c in CATEGORIAS})
        volver = "↩  Volver al menú"
        eleccion = self.entrada.seleccionar("¿Qué tipo de anomalía quieres revisar?",
                                            [*opciones, volver])
        if eleccion == volver:
            return
        categoria = opciones[eleccion]
        filtradas = [i for i in d.anomalas if categoria is None or categoria in i.categorias()]
        self.paginador.mostrar(
            filtradas, self._constructor_anomalias(categoria),
            f"No hay anomalías del tipo «{categoria}».",
            {"I": ("Ficha de rechazo por ID", lambda: self.inspeccionar_id(solo_anomalas=True))})

    def ver_severidad(self) -> None:
        d = self.datos
        opciones = {f"{n} ({d.por_severidad.get(n, 0)})": n for n in NIVELES}
        volver = "↩  Volver al menú"
        self.consola.print(Panel(self.tabla_barras([(n, d.por_severidad.get(n, 0)) for n in NIVELES],
                                                   COLOR_SEVERIDAD),
                                 title="[bold]Incidencias válidas por severidad[/]",
                                 border_style=NEON_NARANJA))
        eleccion = self.entrada.seleccionar("¿Qué nivel quieres revisar?", [*opciones, volver])
        if eleccion == volver:
            return
        nivel = opciones[eleccion]
        filtradas = [i for i in d.validas if i.severidad == nivel]
        self.paginador.mostrar(filtradas, self._constructor_validas(f"Severidad {nivel}"),
                               f"No hay incidencias válidas de severidad {nivel}.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})

    def ver_graficas(self) -> None:
        d = self.datos
        self.consola.clear()
        tipos = Panel(self.tabla_barras(d.por_tipo.most_common(), NEON_CIAN),
                      title="[bold]Averías por categoría de equipo[/]",
                      border_style=NEON_CIAN, box=box.ROUNDED, padding=(1, 2))
        equipos = Panel(self.tabla_barras(d.por_equipo.most_common(TOP_EQUIPOS), NEON_ROSA)
                        if d.por_equipo else Text("No se ha detectado un campo de equipo.", style="dim"),
                        title=f"[bold]Top {TOP_EQUIPOS} equipos con más averías[/]",
                        border_style=NEON_ROSA, box=box.ROUNDED, padding=(1, 2))
        severidad = Panel(self.tabla_barras([(n, d.por_severidad.get(n, 0)) for n in NIVELES],
                                            COLOR_SEVERIDAD),
                          title="[bold]Distribución por severidad[/]",
                          border_style=NEON_NARANJA, box=box.ROUNDED, padding=(1, 2))
        self.consola.print(Panel(Group(tipos, equipos, severidad),
                                 title=f"[bold {NEON_ROSA}]◆ GRÁFICAS DE AVERÍAS (solo incidencias válidas) ◆[/]",
                                 border_style=NEON_ROSA, box=box.DOUBLE))
        self.entrada.pausa()

    def ver_marcas(self) -> None:
        """Filtra las válidas por marca. Las que no tienen marca se pueden
        filtrar por su categoría de equipo (Portàtil, Sobretaula, Monitors...)."""
        d = self.datos
        if not d.validas:
            self.consola.print(Panel("No hay incidencias válidas.", border_style=NEON_AMARILLO))
            self.entrada.pausa()
            return

        sin_marca = [i for i in d.validas if not i.marca]
        # Cada opción -> ("marca", nombre) o ("categoria", None)
        opciones: dict[str, tuple[str, str | None]] = {
            f"{marca} ({n})": ("marca", marca) for marca, n in d.por_marca.most_common()}
        if sin_marca:
            opciones[f"▤  Sin marca → filtrar por categoría de equipo ({len(sin_marca)})"] = (
                "categoria", None)
        volver = "↩  Volver al menú"

        titulo = (f"Marcas detectadas: {len(d.por_marca)}"
                  if d.por_marca else "No se ha encontrado ninguna marca en las válidas")
        eleccion = self.entrada.seleccionar(f"{titulo}. ¿Qué quieres ver?", [*opciones, volver])
        if eleccion == volver:
            return
        clase, marca = opciones[eleccion]
        if clase == "categoria":
            self._filtrar_categoria(sin_marca, "sin marca")
            return
        self.paginador.mostrar([i for i in d.validas if i.marca == marca],
                               self._constructor_validas(f"Incidencias válidas · {marca}"),
                               f"No hay incidencias de {marca}.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})

    def _filtrar_categoria(self, incidencias: list[Incidencia], etiqueta: str) -> None:
        """Submenú de categorías de equipo sobre la lista recibida."""
        conteo = Counter(i.tipo for i in incidencias)
        opciones = {f"{cat} ({n})": cat for cat, n in conteo.most_common()}
        volver = "↩  Volver al menú"
        eleccion = self.entrada.seleccionar(f"Categoría de equipo ({etiqueta}):",
                                            [*opciones, volver])
        if eleccion == volver:
            return
        categoria = opciones[eleccion]
        self.paginador.mostrar([i for i in incidencias if i.tipo == categoria],
                               self._constructor_validas(
                                   f"Incidencias válidas {etiqueta} · {categoria}"),
                               f"No hay incidencias de la categoría {categoria}.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})

    # ── Filtro por fechas ──────────────────────────────────────────────────

    def ver_fechas(self) -> None:
        """Filtra las válidas por año/mes existente o por un rango escrito."""
        con_fecha = [i for i in self.datos.validas if i.fecha]
        if not con_fecha:
            self.consola.print(Panel("Ninguna incidencia válida tiene una fecha completa "
                                     "(día, mes y año).", border_style=NEON_AMARILLO))
            self.entrada.pausa()
            return

        primera = min(i.fecha for i in con_fecha)
        ultima = max(i.fecha for i in con_fecha)
        sin_fecha = len(self.datos.validas) - len(con_fecha)
        op_mes = "▦  Elegir año / mes de los datos"
        op_rango = "↔  Escribir un rango de fechas (AAAA-MM-DD a AAAA-MM-DD)"
        volver = "↩  Volver al menú"
        eleccion = self.entrada.seleccionar(
            f"Datos del {primera:%d/%m/%Y} al {ultima:%d/%m/%Y}"
            + (f" ({sin_fecha} válidas sin fecha completa)" if sin_fecha else "")
            + ". ¿Cómo quieres filtrar?",
            [op_mes, op_rango, volver])
        if eleccion == volver:
            return

        resultado = (self._elegir_anyo_mes(con_fecha) if eleccion == op_mes
                     else self._pedir_rango(con_fecha, primera, ultima))
        if resultado is None:
            return
        titulo, seleccion = resultado
        seleccion.sort(key=lambda i: i.fecha)        # Orden cronológico
        self.paginador.mostrar(seleccion, self._constructor_validas(titulo),
                               "No hay incidencias válidas en ese periodo.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})

    def _elegir_anyo_mes(self, con_fecha: list[Incidencia]) -> tuple[str, list[Incidencia]] | None:
        """Año y mes se sacan de los datos: solo se ofrece lo que existe."""
        volver = "↩  Volver"
        anyos = Counter(i.fecha.year for i in con_fecha)
        op_anyo = {f"{a} ({n})": a for a, n in sorted(anyos.items(), reverse=True)}
        eleccion = self.entrada.seleccionar("Elige el año:", [*op_anyo, volver])
        if eleccion == volver:
            return None
        anyo = op_anyo[eleccion]
        del_anyo = [i for i in con_fecha if i.fecha.year == anyo]

        meses = Counter(i.fecha.month for i in del_anyo)
        op_mes: dict[str, int | None] = {f"Todo {anyo} ({len(del_anyo)})": None}
        op_mes.update({f"{MESES[m - 1].capitalize()} {anyo} ({n})": m
                       for m, n in sorted(meses.items())})
        eleccion = self.entrada.seleccionar("Elige el mes:", [*op_mes, volver])
        if eleccion == volver:
            return None
        mes = op_mes[eleccion]
        if mes is None:
            return f"Incidencias válidas · año {anyo}", del_anyo
        return (f"Incidencias válidas · {MESES[mes - 1]} de {anyo}",
                [i for i in del_anyo if i.fecha.month == mes])

    def _pedir_rango(self, con_fecha: list[Incidencia], primera: date,
                     ultima: date) -> tuple[str, list[Incidencia]] | None:
        """Pide 'desde' y 'hasta' validando formato, fecha real y orden."""
        self.consola.print(Panel(
            f"Escribe las fechas como AAAA-MM-DD (o DD/MM/AAAA).\n"
            f"Los datos van del {primera:%Y-%m-%d} al {ultima:%Y-%m-%d}. Enter vacío cancela.",
            title="[bold]Rango de fechas[/]", border_style=NEON_CIAN))
        desde = self.entrada.fecha("Desde: ")
        if desde is None:
            return None
        while True:
            hasta = self.entrada.fecha("Hasta: ")
            if hasta is None:
                return None
            if hasta >= desde:
                break
            self.entrada.error(f"La fecha final no puede ser anterior a {desde:%Y-%m-%d}.")
        return (f"Incidencias válidas · {desde:%d/%m/%Y} → {hasta:%d/%m/%Y}",
                [i for i in con_fecha if desde <= i.fecha <= hasta])

    def buscar(self) -> None:
        """ID exacto -> ficha directa. Si no, búsqueda de texto en todos los campos."""
        termino = self.entrada.texto("Texto o ID a buscar:")
        if not termino:
            return
        por_id = self.datos.por_id(termino)
        if por_id:
            self.mostrar_fichas(por_id)
            return
        self.paginador.mostrar(self.datos.buscar_texto(termino),
                               self._constructor_busqueda(termino),
                               f"No se ha encontrado «{termino}» en ningún ID ni campo.",
                               {"I": ("Ver ficha por ID", self.inspeccionar_id)})


# ══════════════════════════════════════════════════════════════════════════
# 10. PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════

def despedida(consola: Console) -> None:
    consola.print()
    consola.print(Panel(Text("Sesión cerrada. ¡Hasta la próxima!", justify="center",
                             style=f"bold {NEON_CIAN}"),
                        border_style=NEON_ROSA, box=box.DOUBLE, padding=(0, 4)))


def main() -> int:
    """Red de seguridad: ninguna excepción llega a la consola como traceback."""
    consola = Console()
    ruta = limpiar_ruta(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else None
    try:
        codigo = CLIInterface(consola, ruta).ejecutar()
        despedida(consola)
        return codigo
    except KeyboardInterrupt:
        despedida(consola)
        return 0
    except Exception as error:  # noqa: BLE001 — último recurso, a propósito
        consola.print(Panel(Text(f"{type(error).__name__}: {error}\n\n"
                                 "El programa se ha cerrado de forma controlada."),
                            title=f"[bold {NEON_ROJO}]✖ Error inesperado[/]",
                            border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2)))
        return 1


if __name__ == "__main__":
    sys.exit(main())