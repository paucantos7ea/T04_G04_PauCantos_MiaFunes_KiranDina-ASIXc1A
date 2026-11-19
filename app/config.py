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
RE_CAMPO_AFECTADOS = re.compile(r"afectad|persones|personas", re.I)
RE_CAMPO_ZONA = re.compile(r"zona|ubicaci|planta|aula|sala|lloc|lugar", re.I)
RE_CAMPO_CODIGO = re.compile(r"codi|c[oó]digo|identificaci|inventari|serial", re.I)
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

# ── Texto aleatorio tipo Faker ("Cuba ciudad medios ii.") ─────────────────
# Una o varias micro-frases: Mayúscula inicial, solo palabras en minúscula
# sin comas, apóstrofos ni cifras, y punto final. Es la huella del
# generador de texto de Faker; las frases reales casi nunca son así de "planas".
RE_FRASES_FAKER = re.compile(
    r"^(?:[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]*(?: [a-záéíóúñü]+)*\.\s*)+$")
RE_PALABRA = re.compile(r"[^\W\d_]{2,}")              # Palabra de 2+ letras
# Señales extra que se citan en el motivo del rechazo
NUMEROS_ROMANOS = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"}
NOMBRES_PROPIOS_FAKER = {
    "mexico", "cuba", "espana", "argentina", "colombia", "peru", "chile", "venezuela",
    "europa", "america", "paris", "madrid", "londres", "roma", "francisco", "juan",
    "maria", "jose", "manuel", "pedro", "jorge", "felipe", "rafael", "martin", "carlos",
    "antonio", "luis", "garcia", "lopez", "gonzalez", "rodriguez", "fernandez", "martinez",
    "sanchez", "perez", "fernando", "psoe", "dios", "iglesia",
}
MIN_PALABRAS_FAKER = 3        # Por debajo, solo se bloquea si hay señales extra
MIN_PALABRAS_PROSA = 12       # Prosa sin ninguna palabra técnica = sin sentido
MIN_PALABRAS_PARRAFO = 25     # Párrafo largo: exige más evidencia técnica (fuerza ≥ 3)

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
# Reglas editables (rules.json)
# ══════════════════════════════════════════════════════════════════════════
# Las palabras clave de severidad, las marcas, el léxico técnico y el rango
# de años NO se programan aquí: viven en rules.json (raíz del proyecto) y se
# pueden editar desde la web. Estos son solo los VALORES DE FÁBRICA con los
# que app/rules.py genera rules.json si no existe.
#
# Formato de las palabras clave: texto normal, sin tildes ni mayúsculas
# (se normalizan solas). Se buscan al INICIO de palabra, así "impressor"
# encaja con impressora/impressores y "lent" con lento/lenta. Las MARCAS se
# buscan como palabra completa ("acer" no encaja con "acerca").

NOMBRE_REGLAS = "rules.json"
NOMBRE_GESTION = "gestion.json"

NIVELES = ["Crítica", "Alta", "Media", "Leve"]
SEVERIDAD_POR_DEFECTO = "Media"   # Sin pistas: mejor no infravalorar

# Si el XML trae un campo de prioridad/severidad, se traduce su valor (Paso 0)
MAPA_SEVERIDAD: TablaPatrones = _compilar([
    ("Crítica", r"critic|urgent|bloquejant|bloqueante|maxim"),
    ("Alta", r"\balt[ae]?\b|high|elevad|important"),
    ("Media", r"mitj|medi|normal|moderad"),
    ("Leve", r"baix|baj|leve|lleu|low|menor|minim"),
])

REGLAS_POR_DEFECTO: dict = {
    "version": 1,
    "anyos": {
        "minimo": 2000,         # Años anteriores = fecha imposible
        "maximo": None,         # None / 0 = el año actual
    },
    "severidad": {
        # ── CRÍTICA: exige CONTEXTO de caída en la descripción ────────────
        # Caídas generales: bastan por sí solas
        "critica_caida_general": [
            "xarxa caiguda", "caiguda de la xarxa", "caiguda de xarxa", "red caida",
            "caida de la red", "tall general", "corte general", "apagada general",
            "caiguda general", "caida general", "ransomware",
        ],
        # Síntomas de caída/daño grave: Crítica solo si afectan a infraestructura
        # o a varios usuarios/plantas (si no, deciden los pasos siguientes)
        "critica_caida": [
            "caigut", "caiguda", "caido", "caida", "sense connexio", "sin conexion",
            "sense xarxa", "sin red", "sense internet", "sin internet", "no hi ha internet",
            "no hay internet", "no hi ha xarxa", "no respon", "no responde", "inaccessible",
            "inaccesible", "cremat", "quemad", "fum", "humo", "perden la connexio",
            "pierden la conexion", "perd la connexio", "interromp la connexio",
            "no obtenen una adreca ip", "no obtienen ip", "sense ip", "sin ip",
            "deixat de funcionar", "dejado de funcionar",
        ],
        # Equipos de infraestructura compartida
        "critica_infraestructura": [
            "servidor", "server", "srv", "router", "switch", "commutador", "encaminador",
            "firewall", "tallafoc", "cpd", "base de dades", "base de datos", "database",
            "bbdd", "punt d'acces", "punto de acceso", "access point",
        ],
        # Expresiones de impacto multiusuario en la descripción
        "critica_multiusuario": [
            "tota la xarxa", "toda la red", "tot l'institut", "todo el centro",
            "tot l'edifici", "todo el edificio", "tota la planta", "toda la planta",
            "totes les plantes", "todas las plantas", "tota l'empresa", "toda la empresa",
            "tota l'oficina", "tothom", "todo el mundo", "tots els usuaris",
            "todos los usuarios", "tot el departament", "todo el departamento",
            "diversos usuaris", "varios usuarios",
        ],
        # Valores del campo «Quantes persones estan afectades» que indican impacto amplio
        "afectados_multiples": [
            "mes de 10", "mas de 10", "tot el departament", "todo el departamento",
            "tota l'organitzacio", "toda la organizacion",
        ],
        # ── ALTA ──────────────────────────────────────────────────────────
        "alta_hardware": [
            "disc dur", "disco duro", "ssd", "hdd", "pantalla blava", "pantalla azul",
            "bsod", "blue screen", "bluescreen", "pantallazo", "placa base", "placa mare",
            "motherboard", "font d'alimentacio", "fuente de alimentacion", "memoria ram",
            "sobreescalf", "sobrecalent", "cremat", "quemad", "fum", "humo", "virus",
            "malware",
        ],
        "alta_arranque": [
            "no arrenca", "no arranca", "no engega", "no encen", "no enciende", "no inicia",
            "no s'encen", "no se enciende", "no arriba a iniciar", "no llega a iniciar",
            "pantalla negra",
        ],
        # ── LEVE ──────────────────────────────────────────────────────────
        "leve_perifericos": [
            "perifer", "teclat", "teclado", "ratoli", "raton", "mouse", "cable", "altaveu",
            "altavoz", "auricular", "webcam", "impressor", "impresor", "printer", "toner",
            "tinta", "paper", "papel", "alfombreta", "usb",
        ],
        # ── MEDIA ─────────────────────────────────────────────────────────
        "media_generico": [
            "no funciona", "no respon", "no responde", "error", "falla", "bloquejad",
            "bloquejat", "bloquead", "penjat", "se cuelga", "es penja", "lent", "lento",
            "pantalla secundaria", "segona pantalla", "segunda pantalla", "programa",
            "aplicacio", "software", "actualitz", "actualiz", "contrasenya", "password",
            "reinici", "intermitent", "sense connexio", "sin conexion", "wifi",
        ],
    },
    # Marca canónica -> alias (palabra completa). El primer alias que encaja gana.
    "marcas": {
        "HP": ["hp", "h.p", "h p", "hewlett", "hewlett packard", "elitebook", "probook",
               "laserjet", "officejet", "deskjet", "proliant", "pavilion"],
        "Dell": ["dell", "latitude", "optiplex", "inspiron", "poweredge", "alienware", "vostro"],
        "Lenovo": ["lenovo", "thinkpad", "thinkcentre", "ideapad"],
        "Apple": ["apple", "macbook", "imac", "mac mini", "ipad", "iphone"],
        "Asus": ["asus", "zenbook", "vivobook"],
        "Acer": ["acer", "aspire", "travelmate"],
        "MSI": ["msi"],
        "Samsung": ["samsung", "galaxy"],
        "Microsoft": ["microsoft", "surface"],
        "Toshiba": ["toshiba", "dynabook"],
        "Fujitsu": ["fujitsu"],
        "Cisco": ["cisco", "catalyst", "meraki"],
        "TP-Link": ["tp-link", "tplink", "tp link"],
        "Ubiquiti": ["ubiquiti", "unifi"],
        "Netgear": ["netgear"],
        "Epson": ["epson"],
        "Brother": ["brother"],
        "Canon": ["canon"],
        "Xerox": ["xerox"],
        "Ricoh": ["ricoh"],
        "Kyocera": ["kyocera"],
        "Logitech": ["logitech"],
        "Ugreen": ["ugreen"],
        "Digitus": ["digitus"],
        "LG": ["lg"],
        "BenQ": ["benq"],
        "Huawei": ["huawei"],
        "Xiaomi": ["xiaomi"],
    },
    # Léxico que demuestra intención técnica en la descripción (filtro anti-Faker)
    "lexico_tecnico": {
        # Verbos y síntomas de avería: cuentan doble
        "sintomas": [
            "no funciona", "no funcionen", "no funcionan", "no me funciona", "no em funciona",
            "no le funciona", "no li funciona", "no nos funciona", "no ens funciona",
            "no me va", "no em va", "no me deja", "no em deixa", "no me arranca",
            "no m'arrenca", "no me enciende", "no m'encen", "no me carga", "no em carrega",
            "no me imprime", "no m'imprimeix", "no me abre", "no m'obre",
            "no va", "no respon", "no responde", "no encen", "no s'encen",
            "no enciende", "no se enciende", "no arrenca", "no arranca", "no inicia",
            "no s'obre", "no obre", "no se abre", "no abre", "no carrega", "no carga",
            "no imprimeix", "no imprime", "no connecta", "no conecta", "no detecta",
            "no reconeix", "no reconoce", "no mostra", "no muestra", "no permet",
            "no deixa", "no rep", "no reu", "no llegan", "no arriba", "no hi ha",
            "error", "errada", "falla", "fallo", "avaria", "averia", "trencat", "trencada",
            "roto", "rota", "espatllat", "lent", "lento", "lenta", "bloquejat",
            "bloquejada", "bloquead", "penjat", "penja", "se cuelga", "es tanca",
            "se cierra", "es reinicia", "se reinicia", "reinici", "tarda", "triga",
            "parpelleja", "parpadea", "soroll", "ruido", "sobreescalf", "calent",
            "cremat", "quemad", "fum", "humo", "virus", "malware", "caigut", "caiguda",
            "caido", "caida", "sense connexio", "sin conexion", "sense internet",
            "sin internet", "desconnect", "desconect", "intermitent", "not working",
            "doesn't work", "broken", "crash", "slow", "freez", "won't", "no signal",
            "encallat", "encallad", "atasca", "atascad", "apagad", "s'apaga", "se apaga",
            "no s'imprimeix", "no emet", "no escriu", "no registra", "no es mou",
            "no desplaca", "desenfocad", "parpelleja", "es perd", "perden", "se pierde",
            "pierden", "interromp",
            "no obtenen", "no obtiene", "no s'estableix", "deixat de funcionar",
            "deixa de funcionar", "dejado de funcionar", "sense senyal", "sin senal",
            "tall visible", "exposat",
        ],
        # Dispositivos y conceptos informáticos
        "dispositivos": [
            "ordinador", "ordenador", "portatil", "pc", "pantalla", "monitor", "teclat",
            "teclado", "ratoli", "raton", "mouse", "impressor", "impresor", "imprimir",
            "printer", "escaner", "wifi", "xarxa", "internet", "router", "switch", "cable",
            "usb", "servidor", "programa", "programari", "aplicacio", "aplicacion",
            "software", "navegador", "correu", "correo", "email", "e-mail", "compte d'usuari",
            "contrasenya", "contrasena", "password", "sistema operatiu", "sistema operativo",
            "windows", "office", "excel", "pdf", "fitxer", "arxiu", "archivo", "disc dur",
            "disco duro", "ssd", "memoria", "bateria", "carregador", "cargador", "altaveu",
            "auricular", "webcam", "projector", "proyector", "imatge", "telefon", "mobil",
            "tauleta", "tablet", "toner", "tinta", "llicencia", "licencia", "actualitzaci",
            "actualizaci", "driver", "controlador", "bios", "display", "screen",
            "computer", "laptop", "keyboard", "network", "graphics", "displayport",
            "hdmi", "vga", "bluetooth", "ip", "adreca ip", "tecla", "cursor", "impressio",
            "alimentacio", "audio", "enllac", "connexio", "conexion", "senyal", "senal",
            "dispositiu", "dispositivo", "equip de xarxa", "ram",
        ],
    },
}

# Metadatos legibles de cada paso del motor de severidad (para la web).
# Las listas que usa cada paso se leen de rules.json.
PASOS_SEVERIDAD: list[dict] = [
    {"paso": 1, "nivel": "Crítica", "titulo": "Caída de infraestructura o corte general",
     "descripcion": "Solo si la DESCRIPCIÓN habla de caída o daño grave: una caída general "
                    "basta; un síntoma de caída exige además equipo de infraestructura "
                    "(servidor, router…) o impacto multiusuario. Un router con un fallo "
                    "menor NO es Crítica.",
     "listas": ["critica_caida_general", "critica_caida", "critica_infraestructura",
                "critica_multiusuario"]},
    {"paso": 2, "nivel": "Alta", "titulo": "Hardware crítico del equipo",
     "descripcion": "Avería física o de seguridad que deja el equipo inutilizable o en riesgo.",
     "listas": ["alta_hardware"]},
    {"paso": 3, "nivel": "Alta", "titulo": "Infraestructura con impacto multiusuario",
     "descripcion": "Equipo de infraestructura que afecta a varias personas (campo de "
                    "afectados o descripción) pero sin caída descrita.",
     "listas": ["critica_infraestructura", "afectados_multiples", "critica_multiusuario"]},
    {"paso": 4, "nivel": "Leve", "titulo": "Periféricos y consumibles",
     "descripcion": "Teclado, ratón, cables, impresora…: molesto pero con alternativa fácil. "
                    "Va ANTES que «no arranca»: «no arrenca la impressora» es Leve.",
     "listas": ["leve_perifericos"]},
    {"paso": 5, "nivel": "Alta", "titulo": "El equipo no arranca",
     "descripcion": "El ordenador no enciende, no carga el sistema o se queda en negro.",
     "listas": ["alta_arranque"]},
    {"paso": 6, "nivel": "Media", "titulo": "Software o error genérico",
     "descripcion": "Programas, contraseñas, lentitud, cortes intermitentes, «no funciona»…",
     "listas": ["media_generico"]},
]

# Nombre legible de cada lista editable (editor de reglas de la web)
ETIQUETAS_LISTAS: dict[str, str] = {
    "critica_caida_general": "Crítica · Caídas generales (bastan solas)",
    "critica_caida": "Crítica · Síntomas de caída / daño grave",
    "critica_infraestructura": "Crítica · Equipos de infraestructura",
    "critica_multiusuario": "Crítica · Impacto multiusuario (descripción)",
    "afectados_multiples": "Crítica · Valores de «personas afectadas» que cuentan como muchas",
    "alta_hardware": "Alta · Hardware crítico",
    "alta_arranque": "Alta · No arranca",
    "leve_perifericos": "Leve · Periféricos y consumibles",
    "media_generico": "Media · Software y errores genéricos",
    "sintomas": "Léxico técnico · Síntomas de avería (cuentan doble)",
    "dispositivos": "Léxico técnico · Dispositivos y conceptos",
}

# ══════════════════════════════════════════════════════════════════════════
# Categorías de anomalía (opciones del filtro)
# ══════════════════════════════════════════════════════════════════════════

CAT_FECHA = "Fechas imposibles"
CAT_BASURA = "Contenido basura"
CAT_DESBORDE = "Desbordamiento de texto"
CAT_VACIO = "Campos vacíos / incompletos"
CAT_SIN_SENTIDO = "Texto aleatorio / sin sentido"
CATEGORIAS = [CAT_FECHA, CAT_BASURA, CAT_SIN_SENTIDO, CAT_DESBORDE, CAT_VACIO]

# Nombre corto de cada tipo de anomalía (gráficos y fichas de auditoría)
TIPO_ANOMALIA: dict[str, str] = {
    CAT_FECHA: "Fecha imposible",
    CAT_VACIO: "Campo vacío",
    CAT_BASURA: "Spam / Contenido basura",
    CAT_DESBORDE: "Desbordamiento",
    CAT_SIN_SENTIDO: "Texto aleatorio / Sin sentido",
}

# ══════════════════════════════════════════════════════════════════════════
# Fechas escritas por el usuario y nombres de meses
# ══════════════════════════════════════════════════════════════════════════

# Auto-reparación: fechas alternativas que se reescriben como DD/MM/AAAA
RE_FECHA_REPARABLE_ISO = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")   # AAAA-MM-DD
RE_FECHA_REPARABLE_EU = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*$")   # DD.MM.AAAA

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

# ══════════════════════════════════════════════════════════════════════════
# Analítica avanzada
# ══════════════════════════════════════════════════════════════════════════

VENTANA_RECIENTE_DIAS = 30        # "Recientes" = últimos N días del dataset
MIN_FALLOS_REINCIDENTE = 3        # Mismo equipo con N fallos en total -> reincidente
MIN_FALLOS_CRONICO = 10           # N fallos en total -> crónico...
MIN_FALLOS_VENTANA = 3            # ... o N fallos en los últimos 90 días -> crónico
TENDENCIA_CALIENTE = 1.3          # Zona con un 30 % más de fallos de lo habitual
TENDENCIA_VIGILAR = 1.1

# Palabras vacías (español + catalán + restos de apóstrofos) para la minería
STOPWORDS: frozenset[str] = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquellos aqui
asi aun aunque bajo bien cada casi como con contra cual cuales cuando de del desde donde dos
el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta estaba estado estan
estar estas este esto estos fue fueron ha haber habia han hasta hay la las le les lo los mas
me mi mientras mis muy nada ni no nos o os otra otras otro otros para pero poco por porque que
quien se ser si sido sin sobre son su sus tambien tan tanto te tiene tienen todo todos tu un
una uno unos ya yo
als amb aquest aquesta aquests aquestes aqui cap ell ella elles ells els em en encara era es
esta estan esta fa ha han hi ho i jo la les li lo mes meu molt nosaltres o pel per pero perque
pels quan que qui se sense ser seu seva ses si sobre son tambe te tot tota tots totes un una
uns unes va van vaig dels al d l s n m t
""".split())

# Palabras de relleno de los formularios que no aportan nada como "problema nuevo"
MINERIA_IGNORAR: frozenset[str] = frozenset("""
problema persisteix reiniciat reiniciar provat encara mentre durant despres dins quan
ordinador ordenador equip usuari usuaria intenta intentat sempre algun alguns moment
""".split())

# ══════════════════════════════════════════════════════════════════════════
# Seguimiento de reparaciones (gestion.json)
# ══════════════════════════════════════════════════════════════════════════

ESTADOS_GESTION = ["Pendiente", "En curso", "Resuelta"]
ESTADO_GESTION_DEFECTO = "Pendiente"
