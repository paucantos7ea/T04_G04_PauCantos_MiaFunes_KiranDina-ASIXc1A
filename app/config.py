# -*- coding: utf-8 -*-
"""Configuración central: constantes, colores, palabras clave y expresiones regulares.

Todo lo que se puede querer ajustar está aquí. Las expresiones regulares se
compilan UNA sola vez al importar el módulo (rendimiento).
"""

from __future__ import annotations

import re
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════
# Archivos y rutas
# ══════════════════════════════════════════════════════════════════════════

# Nombres que se buscan automáticamente si no se pasa --file (por orden)
NOMBRES_XML_DEFECTO: tuple[str, ...] = ("respotes.xml", "incidencies.xml")
NOMBRE_JSON = "incidencies.json"          # Se guarda junto al XML analizado

# Carpeta raíz del proyecto (la que contiene main.py y la carpeta app/)
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

# ══════════════════════════════════════════════════════════════════════════
# Límites
# ══════════════════════════════════════════════════════════════════════════

ANYO_MINIMO = 2000                    # Años anteriores = imposibles
MAX_TRUNCAR = 50                      # Caracteres visibles en las tablas
MAX_FICHA = 160                       # Caracteres visibles en la ficha de rechazo
MAX_LONGITUD_CORTO = 200              # Desbordamiento en campos breves
POR_PAGINA = 10                       # Registros por página
TOP_EQUIPOS = 10                      # Equipos en la gráfica
MAX_ERRORES_ESTRUCTURA = 10           # Errores que se enseñan al rechazar un XML

# ══════════════════════════════════════════════════════════════════════════
# Estructura esperada del XML
# ══════════════════════════════════════════════════════════════════════════

ETIQUETA_RAIZ = "incidencies"
ETIQUETA_INCIDENCIA = "incidencia"
ETIQUETA_CAMPO = "camp"

# Estructura EXACTA que debe tener cada <incidencia>. Si el archivo no la
# cumple se rechaza entero, antes de analizar nada.
CAMPOS_ESPERADOS: list[str] = [
    "Marca de temps",
    "Informació relativa sobre la protecció de dades",
    "Data d'incidència",
    "En quina zona de l'empresa es troba l'equip?",
    "Quin departament ha detectat la incidència",
    "Quin equip presenta l'incidència?",
    "Quin codi d'identificació té l'equip?",
    "Descripció del problema",
    "Marca d'equip",
    "Amb quina freqüència passa el problema?",
    "Quantes persones estan afectades pel problema?",
    "S'ha provat de reiniciar l'equip? (Si el problema es amb l'ordinador)",
    "En quin horari es pot revisar o reparar l'equip?",
]

# Campos que deben existir siempre. Vacío = solo se marcan etiquetas vacías.
# Ejemplo: CAMPOS_OBLIGATORIOS = ["Data", "Equip", "Descripció"]
CAMPOS_OBLIGATORIOS: list[str] = []

# ══════════════════════════════════════════════════════════════════════════
# Reconocer el PAPEL de cada campo por su atributo nom="..."
# ══════════════════════════════════════════════════════════════════════════

# "Marca de temps" (timestamp del formulario) NO es la marca del equipo
RE_CAMPO_NO_MARCA = re.compile(r"temps|tiempo|time|hora", re.I)

# Campos OPCIONALES: si vienen vacíos (<camp nom="Marca d'equip"/>) NO se
# rechaza la incidencia; la marca se deduce por REGEX o queda "sin marca".
RE_CAMPO_OPCIONAL = re.compile(r"marca|fabricant|brand|model", re.I)

RE_CAMPO_FECHA = re.compile(r"data|fecha|date|\bdia\b", re.I)
RE_CAMPO_EQUIPO = re.compile(
    r"equip|ordinador|ordenador|dispositiu|dispositivo|m[aà]quina|\bpc\b|host", re.I)
# Preguntas que mencionan "l'equip" pero no dicen QUÉ equipo es
RE_CAMPO_NO_EQUIPO = re.compile(
    r"tipus|tipo|categor|marca|model|zona|codi|c[oó]digo|identificaci|reinici|horari|"
    r"revis|repar", re.I)
# Categoría del EQUIPO: "Categoria", "Tipus d'equip", "Tipo de dispositivo"...
# pero NO "Tipus d'incidència" (eso es el tipo de avería, no del equipo)
RE_CAMPO_TIPO = re.compile(
    r"categor|(tipus|tipo)\W.*(equip|dispositi|m[aà]quina|aparell)|^\s*(tipus|tipo)\s*$", re.I)
RE_CAMPO_MARCA = re.compile(r"marca|fabricant|brand", re.I)
RE_CAMPO_MODELO = re.compile(r"model", re.I)
RE_CAMPO_SEVERIDAD = re.compile(
    r"prioritat|prioridad|severitat|severidad|gravetat|gravedad|urg[eè]nci|impact|criticitat",
    re.I)
RE_CAMPO_DESCRIPCION = re.compile(r"descripci|detall|detalle|observaci|problema|comentari", re.I)
RE_CAMPO_CORTO = re.compile(
    r"\b(id|codi|codigo|código|code|equip|equipo|aula|ip|mac|prioritat|prioridad|"
    r"estat|estado|tipus|tipo|marca|model|modelo|host|hostname)\b", re.I)

# ══════════════════════════════════════════════════════════════════════════
# Contenido basura
# ══════════════════════════════════════════════════════════════════════════

# Palabra basura (sin tildes, minúsculas) -> qué tipo de basura es
PALABRAS_BASURA: dict[str, str] = {
    "fox news": "recorte de noticias",
    "cerditos": "cuento infantil",
    "miercoles addams": "relato de ficción",
    "pull and bear": "marca incongruente",
}

RE_FECHA = re.compile(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})")
RE_ANYO = re.compile(r"(?<!\d)\d{4}(?!\d)")
RE_BINARIO = re.compile(r"(?:[01]{8}[\s,;]*){3,}")          # 3 bytes o más
RE_BYTE = re.compile(r"[01]{8}")
RE_AMARICO = re.compile("[ሀ-᎟ⶀ-⷟꬀-꬯]")   # Bloques etíopes
RE_BASURA = re.compile("|".join(re.escape(p) for p in PALABRAS_BASURA))

# Valores que en realidad significan "no hay dato" (se comparan normalizados)
VALORES_NULOS = {"", "-", "--", "—", "n/a", "na", "null", "none", "cap", "ninguna",
                 "ninguno", "desconeguda", "desconegut", "desconocida", "desconocido",
                 "sense marca", "sin marca"}

# ══════════════════════════════════════════════════════════════════════════
# Categorías de equipo (el orden importa: la primera que encaje gana)
# ══════════════════════════════════════════════════════════════════════════
# Traducen el valor del campo de categoría a un nombre único y, si ese campo
# no existe, permiten deducir la categoría a partir del equipo o la descripción.

TablaPatrones = list[tuple[str, "re.Pattern[str]"]]


def _compilar(pares: list[tuple[str, str]]) -> TablaPatrones:
    return [(nombre, re.compile(patron)) for nombre, patron in pares]


TIPOS_DISPOSITIVO: TablaPatrones = _compilar([
    ("Portàtil", r"portatil|laptop|notebook|macbook|thinkpad|elitebook|probook|"
                 r"latitude|chromebook|zenbook|vivobook"),
    ("Impressores", r"impres?sor|printer|laserjet|officejet|deskjet|plotter|escaner|"
                    r"scanner|multifunci"),
    ("Servidors", r"servidor|server|\bsrv|\bnas\b|\brack\b|poweredge|proliant"),
    ("Xarxa", r"router|switch|commutador|encaminador|\bap\b|punt d.acces|punto de acceso|"
              r"access point|firewall|\bmodem\b|^xarxa$|^red$"),
    ("Monitors", r"monitor|pantalla|display|projector|proyector"),
    ("Mòbils/Tauletes", r"\bmobil|\bmovil|telefon|tablet|tauleta|ipad|iphone|smartphone"),
    ("Programari", r"programari|software|aplicaci"),
    ("Sobretaula", r"\bpc\b|\bpc-|sobretaula|sobremesa|ordinador|ordenador|desktop|"
                   r"optiplex|\bimac\b|\btorre\b|workstation"),
    ("Perifèrics", r"perifer|teclat|teclado|ratoli|raton|mouse|webcam|auricular|"
                   r"altaveu|altavoz"),
])
CATEGORIA_POR_DEFECTO = "Altres"

# ══════════════════════════════════════════════════════════════════════════
# Marcas conocidas
# ══════════════════════════════════════════════════════════════════════════
# 1) Unifican el valor del nodo de marca ("hewlett packard" -> "HP").
# 2) Si el nodo falta o viene vacío / "-", se buscan en el equipo y la
#    descripción (también por modelo: ThinkPad -> Lenovo, OptiPlex -> Dell).

MARCAS_REALES: TablaPatrones = _compilar([
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
    ("Ugreen", r"ugreen"),
    ("Digitus", r"digitus"),
    ("LG", r"\blg\b"),
    ("BenQ", r"benq"),
    ("Huawei", r"huawei"),
    ("Xiaomi", r"xiaomi"),
])

# ══════════════════════════════════════════════════════════════════════════
# Severidad
# ══════════════════════════════════════════════════════════════════════════

NIVELES = ["Crítica", "Alta", "Media", "Leve"]
SEVERIDAD_POR_DEFECTO = "Media"   # Sin pistas: mejor no infravalorar

# 1) Si el XML tiene un campo de prioridad/severidad, se traduce su valor
MAPA_SEVERIDAD: TablaPatrones = _compilar([
    ("Crítica", r"critic|urgent|bloquejant|bloqueante|maxim"),
    ("Alta", r"\balt[ae]?\b|high|elevad|important"),
    ("Media", r"mitj|medi|normal|moderad"),
    ("Leve", r"baix|baj|leve|lleu|low|menor|minim"),
])

# 2) Si no lo tiene, se deduce por palabras clave sobre la descripción, el
#    equipo y su categoría (texto normalizado: sin tildes ni mayúsculas).
#    Orden de decisión (ver validator.Clasificador.severidad):
#      1. CRÍTICA  -> servidores y red general (servidor, BD, router/switch, xarxa caiguda...)
#      2. ALTA     -> hardware crítico del equipo (disco, BSOD, placa base...)
#      3. LEVE     -> periféricos (teclat, ratolí, cables, altaveus, impressora)
#      4. ALTA     -> "no arrenca" / "no s'encén", si NO es un periférico
#      5. MEDIA    -> software o errores genéricos ("no funciona", "programari"...)
#      6. Sin pistas -> SEVERIDAD_POR_DEFECTO
#    Así "No funciona el teclat" es LEVE (paso 3 antes que el 5) y
#    "No arrenca l'ordinador" es ALTA.
RE_SEV_CRITICA = re.compile(
    r"servidor|server|\bsrv\b|\bsrv-|base de dades|base de datos|database|\bbbdd\b|"
    r"xarxa caiguda|caiguda de (la )?xarxa|red caida|caida de (la )?red|"
    r"\brouter\b|\bswitch\b|commutador|encaminador|firewall|"
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

# ══════════════════════════════════════════════════════════════════════════
# Categorías de anomalía (opciones del filtro)
# ══════════════════════════════════════════════════════════════════════════

CAT_FECHA = "Fechas imposibles"
CAT_BASURA = "Contenido basura"
CAT_DESBORDE = "Desbordamiento de texto"
CAT_VACIO = "Campos vacíos / incompletos"
CATEGORIAS = [CAT_FECHA, CAT_BASURA, CAT_DESBORDE, CAT_VACIO]

# ══════════════════════════════════════════════════════════════════════════
# Fechas escritas por el usuario y nombres de meses
# ══════════════════════════════════════════════════════════════════════════

RE_FECHA_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")    # AAAA-MM-DD
RE_FECHA_EU = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")     # DD/MM/AAAA
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# ══════════════════════════════════════════════════════════════════════════
# Estética
# ══════════════════════════════════════════════════════════════════════════

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
