# -*- coding: utf-8 -*-
"""
filtro_respotes.py — Analizador interactivo de incidencias en XML (v2)
=====================================================================

Lee un XML de incidencias con esta estructura:

    <incidencies>
        <incidencia id="1">
            <camp nom="Nombre del campo">Valor</camp>
            ...
        </incidencia>
    </incidencies>

Funciones principales:
  * Valida cada <incidencia> y la clasifica como VÁLIDA o ANÓMALA.
  * Agrupa las anomalías en tres tipos: Fechas imposibles, Spam / Texto largo
    y Campos vacíos.
  * Muestra un dashboard, listados paginados (N/P/G/Q) y búsqueda libre o por ID.
  * Permite exportar las incidencias válidas a incidencies.json (crear, sobreescribir o fusionar).
  * Diseño "anti-crash": ningún error termina en un traceback por consola.

Uso:
    python filtro_respotes.py ruta\\al\\respotes.xml   -> lee ese XML
    python filtro_respotes.py                        -> te pide la ruta

Dependencias:
    pip install rich questionary
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Si falta alguna librería, avisamos con un mensaje claro en vez de un traceback
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
# 1. CONFIGURACIÓN (cambia aquí las reglas sin tocar el resto del código)
# ══════════════════════════════════════════════════════════════════════════

NOMBRE_XML_DEFECTO = "respotes.xml"   # Se propone como ruta si existe
ANYO_MINIMO = 2000                    # Años anteriores = imposibles
MAX_TRUNCAR = 50                      # Caracteres visibles en las tablas
MAX_LONGITUD_CORTO = 100              # Límite en campos que deben ser breves
POR_PAGINA = 10                       # Registros por página
TOP_EQUIPOS = 3                       # Equipos mostrados en el dashboard

CAMPOS_OBLIGATORIOS: list[str] = []

PALABRAS_BASURA = [
    "fox news", "cerditos", "miercoles addams", "pull and bear",
]

PATRON_CAMPO_FECHA = re.compile(r"data|fecha|date|\bdia\b", re.IGNORECASE)
PATRON_CAMPO_CORTO = re.compile(
    r"\b(id|codi|codigo|código|code|equip|equipo|aula|ip|mac|"
    r"prioritat|prioridad|estat|estado|tipus|tipo|marca|model|modelo)\b",
    re.IGNORECASE,
)
PATRON_CAMPO_EQUIPO = re.compile(
    r"equip|ordinador|ordenador|dispositiu|dispositivo|m[aà]quina|marca|\bpc\b",
    re.IGNORECASE,
)

PATRON_FECHA = re.compile(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})")
PATRON_ANYO = re.compile(r"(?<!\d)\d{4}(?!\d)")
PATRON_BINARIO = re.compile(r"(?:[01]{8}[\s,;]*){3,}")
PATRON_AMARICO = re.compile("[ሀ-᎟ⶀ-⷟꬀-꬯]")

CAT_FECHA = "Fechas imposibles"
CAT_SPAM = "Spam / Texto largo"
CAT_VACIO = "Campos vacíos"
CATEGORIAS = [CAT_FECHA, CAT_SPAM, CAT_VACIO]

NEON_ROSA = "#ff2bd6"
NEON_CIAN = "#00f0ff"
NEON_VERDE = "#39ff14"
NEON_ROJO = "#ff3860"
NEON_AMARILLO = "#ffe600"
ZEBRA = "on grey15"

ESTILO_MENU = questionary.Style([
    ("qmark", f"fg:{NEON_ROSA} bold"),
    ("question", "bold"),
    ("pointer", f"fg:{NEON_CIAN} bold"),
    ("highlighted", f"fg:{NEON_CIAN} bold"),
    ("answer", f"fg:{NEON_ROSA} bold"),
])

INTERACTIVO = sys.stdin.isatty() and sys.stdout.isatty()


# ══════════════════════════════════════════════════════════════════════════
# 2. UTILIDADES
# ══════════════════════════════════════════════════════════════════════════

def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    sin_tildes = sin_tildes.lower().replace("&", " and ")
    return re.sub(r"\s+", " ", sin_tildes).strip()


def truncar(texto: str, limite: int = MAX_TRUNCAR) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[:limite] + "[...]"


def limpiar_ruta(entrada: str) -> Path:
    entrada = (entrada or "").strip()
    if entrada.startswith("& "):
        entrada = entrada[2:].strip()
    return Path(entrada.strip("'\"")).expanduser()


def texto_seguro(elemento: ET.Element | None) -> str:
    if elemento is None:
        return ""
    return "".join(elemento.itertext()).strip()


def panel_error(consola: Console, titulo: str, mensaje: str) -> None:
    consola.print(Panel(
        Text(mensaje), title=f"[bold {NEON_ROJO}]✖ {escape(titulo)}[/]",
        border_style=NEON_ROJO, box=box.HEAVY, padding=(1, 2),
    ))


def despedida(consola: Console) -> None:
    consola.print()
    consola.print(Panel(
        Text("Sesión cerrada. ¡Hasta la próxima!", justify="center",
             style=f"bold {NEON_CIAN}"),
        border_style=NEON_ROSA, box=box.DOUBLE, padding=(0, 4),
    ))


# ══════════════════════════════════════════════════════════════════════════
# 3. MODELO DE DATOS
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Anomalia:
    categoria: str
    motivo: str
    campo: str = "—"
    valor: str = ""


@dataclass
class Incidencia:
    id: str
    campos: dict[str, str] = field(default_factory=dict)
    vacios: list[str] = field(default_factory=list)
    anomalias: list[Anomalia] = field(default_factory=list)
    sin_id: bool = False

    @property
    def valida(self) -> bool:
        return not self.anomalias

    def categorias(self) -> set[str]:
        return {a.categoria for a in self.anomalias}


# ══════════════════════════════════════════════════════════════════════════
# 4. LECTURA SEGURA DEL XML
# ══════════════════════════════════════════════════════════════════════════

class ErrorCarga(Exception):
    def __init__(self, titulo: str, mensaje: str):
        super().__init__(mensaje)
        self.titulo = titulo
        self.mensaje = mensaje


def cargar_incidencias(ruta: Path) -> tuple[str, list[Incidencia]]:
    if not ruta.exists():
        raise ErrorCarga("Archivo no encontrado", f"No existe el archivo:\n{ruta}")
    if not ruta.is_file():
        raise ErrorCarga("Ruta no válida", f"La ruta no es un archivo:\n{ruta}")

    try:
        raiz = ET.parse(ruta).getroot()
    except ET.ParseError as error:
        raise ErrorCarga("XML malformado",
                         f"El documento no es un XML bien formado.\n{error}") from None
    except PermissionError:
        raise ErrorCarga("Sin permisos", f"No tienes permiso para leer:\n{ruta}") from None
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ErrorCarga("Error de lectura", f"No se puede leer el archivo.\n{error}") from None

    incidencias: list[Incidencia] = []
    for posicion, nodo in enumerate(raiz.iter("incidencia"), start=1):
        id_xml = (nodo.get("id") or "").strip()
        inc = Incidencia(id=id_xml or f"SIN-ID-{posicion}", sin_id=not id_xml)

        for camp in nodo.iter("camp"):
            nombre = (camp.get("nom") or "").strip() or "(sin nombre)"
            valor = texto_seguro(camp)

            clave, n = nombre, 2
            while clave in inc.campos or clave in inc.vacios:
                clave, n = f"{nombre} ({n})", n + 1

            if valor:
                inc.campos[clave] = valor
            else:
                inc.vacios.append(clave)

        incidencias.append(inc)

    return raiz.tag, incidencias


# ══════════════════════════════════════════════════════════════════════════
# 5. MOTOR DE VALIDACIÓN
# ══════════════════════════════════════════════════════════════════════════

class ValidadorIncidencias:
    def __init__(self, anyo_minimo: int = ANYO_MINIMO, hoy: date | None = None):
        self.anyo_minimo = anyo_minimo
        self.hoy = hoy or date.today()
        self.palabras = [normalizar(p) for p in PALABRAS_BASURA]
        self.obligatorios = [normalizar(c) for c in CAMPOS_OBLIGATORIOS]
        self.reglas = (
            self._regla_fecha,
            self._regla_binario,
            self._regla_amarico,
            self._regla_palabras,
            self._regla_longitud,
        )

    def validar(self, inc: Incidencia) -> Incidencia:
        inc.anomalias.clear()

        if inc.sin_id:
            inc.anomalias.append(Anomalia(CAT_VACIO, "Incidencia sin atributo id"))
        if not inc.campos and not inc.vacios:
            inc.anomalias.append(Anomalia(CAT_VACIO, "Incidencia sin ningún campo"))
        for nombre in inc.vacios:
            inc.anomalias.append(
                Anomalia(CAT_VACIO, "Campo vacío", nombre, "(etiqueta sin valor)"))

        presentes = {normalizar(n) for n in [*inc.campos, *inc.vacios]}
        for obligatorio, original in zip(self.obligatorios, CAMPOS_OBLIGATORIOS):
            if obligatorio not in presentes:
                inc.anomalias.append(
                    Anomalia(CAT_VACIO, "Falta un campo obligatorio", original, "(no existe)"))

        for nombre, valor in inc.campos.items():
            for regla in self.reglas:
                resultado = regla(nombre, valor)
                if resultado:
                    categoria, motivo = resultado
                    inc.anomalias.append(Anomalia(categoria, motivo, nombre, valor))
        return inc

    def _comprobar_anyo(self, anyo: int) -> str | None:
        if anyo < self.anyo_minimo:
            return f"Año imposible ({anyo:04d})"
        if anyo > self.hoy.year:
            return f"Año futuro ({anyo})"
        return None

    def _regla_fecha(self, nombre: str, valor: str):
        if not PATRON_CAMPO_FECHA.search(nombre):
            return None

        coincidencia = PATRON_FECHA.search(valor)
        if coincidencia:
            a, b, c = coincidencia.groups()
            anyo, mes, dia = (a, b, c) if len(a) == 4 else (c, b, a)
            if len(anyo) != 4:
                return CAT_FECHA, "Formato de fecha no reconocido"
            motivo = self._comprobar_anyo(int(anyo))
            if motivo:
                return CAT_FECHA, motivo
            try:
                fecha = date(int(anyo), int(mes), int(dia))
            except ValueError:
                return CAT_FECHA, "Fecha imposible (día o mes inexistente)"
            if fecha > self.hoy:
                return CAT_FECHA, "Fecha futura"
            return None

        anyos = PATRON_ANYO.findall(valor)
        if not anyos:
            return CAT_FECHA, "Fecha sin formato reconocible"
        for anyo in anyos:
            motivo = self._comprobar_anyo(int(anyo))
            if motivo:
                return CAT_FECHA, motivo
        return None

    def _regla_binario(self, nombre: str, valor: str):
        if PATRON_BINARIO.search(valor):
            return CAT_SPAM, "Secuencia de código binario"
        return None

    def _regla_amarico(self, nombre: str, valor: str):
        if PATRON_AMARICO.search(valor):
            return CAT_SPAM, "Caracteres en amárico"
        return None

    def _regla_palabras(self, nombre: str, valor: str):
        texto = normalizar(valor)
        encontradas = [p for p in self.palabras if p in texto]
        if encontradas:
            return CAT_SPAM, "Contenido no relacionado: " + ", ".join(encontradas)
        return None

    def _regla_longitud(self, nombre: str, valor: str):
        if PATRON_CAMPO_CORTO.search(nombre) and len(valor) > MAX_LONGITUD_CORTO:
            return CAT_SPAM, f"Desbordamiento de campo breve ({len(valor)} caracteres)"
        return None


# ══════════════════════════════════════════════════════════════════════════
# 6. ENTRADAS DEL USUARIO
# ══════════════════════════════════════════════════════════════════════════

def seleccionar(consola: Console, mensaje: str, opciones: list[str]) -> str:
    if INTERACTIVO:
        return questionary.select(
            mensaje, choices=opciones, style=ESTILO_MENU, qmark="➤", pointer="❯",
        ).unsafe_ask()

    consola.print(f"[bold]{escape(mensaje)}[/]")
    for i, opcion in enumerate(opciones, start=1):
        consola.print(f"  {i}. {escape(opcion)}")
    while True:
        try:
            numero = int(leer_linea(consola, "Opción: "))
        except ValueError:
            consola.print(f"[{NEON_AMARILLO}]⚠ Escribe un número de la lista.[/]")
            continue
        if 1 <= numero <= len(opciones):
            return opciones[numero - 1]
        consola.print(f"[{NEON_AMARILLO}]⚠ Elige entre 1 y {len(opciones)}.[/]")


def leer_linea(consola: Console, mensaje: str) -> str:
    try:
        return consola.input(mensaje)
    except EOFError:
        raise KeyboardInterrupt from None


def pedir_texto(consola: Console, mensaje: str) -> str:
    if INTERACTIVO:
        return questionary.text(mensaje, style=ESTILO_MENU, qmark="➤").unsafe_ask() or ""
    return leer_linea(consola, f"{mensaje} ")


def pedir_letra(consola: Console, mensaje: str, validas: str) -> str:
    while True:
        letra = leer_linea(consola, mensaje).strip().upper()
        if len(letra) == 1 and letra in validas:
            return letra
        consola.print(f"[{NEON_AMARILLO}]⚠ Opción no válida. Usa: "
                      f"{', '.join(validas)}.[/]")


def pedir_numero(consola: Console, mensaje: str, minimo: int, maximo: int) -> int | None:
    while True:
        entrada = leer_linea(consola, mensaje).strip()
        if not entrada:
            return None
        try:
            numero = int(entrada)
        except ValueError:
            consola.print(f"[{NEON_AMARILLO}]⚠ «{escape(entrada)}» no es un número. "
                          f"Prueba otra vez (Enter para cancelar).[/]")
            continue
        if minimo <= numero <= maximo:
            return numero
        consola.print(f"[{NEON_AMARILLO}]⚠ La página {numero} no existe. "
                      f"Elige entre {minimo} y {maximo}.[/]")


def pedir_ruta(consola: Console) -> Path:
    propuesta = ""
    for carpeta in (Path.cwd(), Path(__file__).resolve().parent):
        if (carpeta / NOMBRE_XML_DEFECTO).is_file():
            propuesta = str(carpeta / NOMBRE_XML_DEFECTO)
            break

    while True:
        if INTERACTIVO:
            entrada = questionary.path(
                "Ruta del archivo XML (escríbela, usa Tab o arrastra el archivo):",
                default=propuesta, style=ESTILO_MENU, qmark="➤",
            ).unsafe_ask()
        else:
            entrada = leer_linea(consola, "Ruta del archivo XML: ")

        if not (entrada or "").strip():
            consola.print(f"[{NEON_AMARILLO}]⚠ Escribe una ruta.[/]")
            continue
        ruta = limpiar_ruta(entrada)
        if ruta.is_file():
            return ruta
        consola.print(f"[{NEON_AMARILLO}]⚠ No existe el archivo:[/] {escape(str(ruta))}")


def pausa(consola: Console) -> None:
    if INTERACTIVO:
        questionary.press_any_key_to_continue(
            "Pulsa una tecla para volver...").unsafe_ask()
    else:
        leer_linea(consola, "Pulsa Enter para volver...")


# ══════════════════════════════════════════════════════════════════════════
# 7. INTERFAZ DE TERMINAL
# ══════════════════════════════════════════════════════════════════════════

class AppIncidencias:
    OPCION_VALIDAS = "✔  Ver incidencias válidas"
    OPCION_ANOMALIAS = "✖  Ver registro de anomalías"
    OPCION_BUSCAR = "⌕  Buscar por texto libre o ID"
    OPCION_JSON = "💾  Guardar incidencias válidas en JSON"
    OPCION_SALIR = "⏻  Salir"

    def __init__(self, consola: Console, incidencias: list[Incidencia], ruta: Path):
        self.consola = consola
        self.ruta = ruta
        self.todas = incidencias
        self.validas = [i for i in incidencias if i.valida]
        self.anomalas = [i for i in incidencias if not i.valida]
        self.campo_equipo = self._detectar_campo_equipo()
        self.columnas = self._columnas_principales()

    def _detectar_campo_equipo(self) -> str | None:
        for inc in self.todas:
            for nombre in inc.campos:
                if PATRON_CAMPO_EQUIPO.search(nombre):
                    return nombre
        return None

    def _columnas_principales(self, maximo: int = 4) -> list[str]:
        frecuencia = Counter(n for i in self.validas for n in i.campos)
        mas_comunes = {n for n, _ in frecuencia.most_common(maximo)}
        orden: list[str] = []
        for inc in self.validas:
            for nombre in inc.campos:
                if nombre in mas_comunes and nombre not in orden:
                    orden.append(nombre)
        return orden

    def _ranking_equipos(self) -> list[tuple[str, int]]:
        if not self.campo_equipo:
            return []
        conteo = Counter(
            i.campos[self.campo_equipo].strip()
            for i in self.validas if self.campo_equipo in i.campos
        )
        return conteo.most_common(TOP_EQUIPOS)

    def _tarjeta(self, titulo: str, valor: str, subtitulo: str, color: str) -> Panel:
        contenido = Text(justify="center")
        contenido.append(f"{valor}\n", style=f"bold {color}")
        contenido.append(subtitulo, style="dim")
        return Panel(contenido, title=f"[bold]{titulo}[/]", border_style=color,
                     box=box.HEAVY, width=26, padding=(1, 1))

    def mostrar_dashboard(self) -> None:
        total = len(self.todas)
        n_val, n_anom = len(self.validas), len(self.anomalas)
        pct_val = n_val / total * 100 if total else 0.0
        pct_anom = 100 - pct_val if total else 0.0

        tarjetas = Columns([
            self._tarjeta("Total procesados", str(total), "incidencias", NEON_CIAN),
            self._tarjeta("Válidas", str(n_val), f"{pct_val:.1f} %", NEON_VERDE),
            self._tarjeta("Anomalías bloqueadas", str(n_anom), f"{pct_anom:.1f} %", NEON_ROJO),
        ])

        ancho = 52
        verdes = round(ancho * pct_val / 100)
        barra = Text.assemble(
            ("Validez  ", "bold"),
            ("█" * verdes, NEON_VERDE), ("█" * (ancho - verdes), NEON_ROJO),
            (f"  {pct_val:.1f} % válidas", "dim"),
        )

        ranking = self._ranking_equipos()
        if ranking:
            maximo = ranking[0][1]
            top = Table(box=None, show_header=False, padding=(0, 1))
            top.add_column(style=f"bold {NEON_AMARILLO}")
            top.add_column(style="bold white", no_wrap=True)
            top.add_column()
            top.add_column(justify="right", style=f"bold {NEON_ROSA}")
            for puesto, (equipo, n) in enumerate(ranking, start=1):
                barra_eq = Text("█" * max(1, round(n / maximo * 24)), style=NEON_CIAN)
                top.add_row(f"{puesto}º", truncar(equipo, 25), barra_eq, str(n))
            bloque_top = Group(
                Text.assemble((f"Top {TOP_EQUIPOS} equipos con incidencias reales ", "bold"),
                              (f"(campo «{self.campo_equipo}»)", "dim")),
                top,
            )
        else:
            bloque_top = Text("No se ha detectado un campo de equipo/marca con datos válidos.",
                              style="dim")

        conteo_cat = Counter(c for i in self.anomalas for c in i.categorias())
        desglose = Text("Anomalías por tipo:  ", style="bold")
        for cat in CATEGORIAS:
            desglose.append(f"{cat} ", style=NEON_ROJO)
            desglose.append(f"{conteo_cat.get(cat, 0)}   ", style="bold white")

        cabecera = Text.assemble(("Archivo: ", "dim"), (str(self.ruta), "bold"))

        self.consola.print(Panel(
            Group(cabecera, Text(""), tarjetas, Text(""), barra, Text(""),
                  bloque_top, Text(""), desglose),
            title=f"[bold {NEON_ROSA}]◆ ESCÁNER DE INCIDENCIAS XML ◆[/]",
            subtitle=f"[{NEON_CIAN}]↑↓ para moverte · Enter para elegir · Ctrl+C para salir[/]",
            border_style=NEON_ROSA, box=box.DOUBLE, padding=(1, 2),
        ))

    def _pie_paginacion(self, pagina: int, total_pag: int, n_registros: int) -> Panel:
        def opcion(tecla: str, texto: str, activa: bool) -> Text:
            if activa:
                return Text.assemble((f"[{tecla}]", f"bold {NEON_CIAN}"), (f" {texto}   ", "white"))
            return Text(f"[{tecla}] {texto}   ", style="dim strike")

        estado = Text.assemble(
            ("Página ", "bold"), (str(pagina), f"bold {NEON_AMARILLO}"),
            (" de ", "bold"), (str(total_pag), f"bold {NEON_AMARILLO}"),
            (f"   ·   {n_registros} registros", "dim"),
        )
        teclas = Text.assemble(
            opcion("N", "Siguiente", pagina < total_pag),
            opcion("P", "Anterior", pagina > 1),
            opcion("G", "Ir a página...", total_pag > 1),
            opcion("Q", "Volver al menú", True),
        )
        return Panel(Group(estado, teclas), border_style=NEON_CIAN, box=box.ROUNDED)

    def paginar(self, elementos: list, construir_tabla, vacio: str) -> None:
        if not elementos:
            self.consola.print(Panel(vacio, border_style=NEON_AMARILLO))
            pausa(self.consola)
            return

        total_pag = math.ceil(len(elementos) / POR_PAGINA)
        pagina, aviso = 1, ""

        while True:
            self.consola.clear()
            inicio = (pagina - 1) * POR_PAGINA
            trozo = elementos[inicio:inicio + POR_PAGINA]
            self.consola.print(construir_tabla(trozo, pagina, total_pag))
            self.consola.print(self._pie_paginacion(pagina, total_pag, len(elementos)))
            if aviso:
                self.consola.print(f"[{NEON_AMARILLO}]⚠ {aviso}[/]")
                aviso = ""

            letra = pedir_letra(self.consola, "Elige [N/P/G/Q]: ", "NPGQ")
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
                destino = pedir_numero(self.consola,
                                       f"Ir a la página (1-{total_pag}, Enter cancela): ",
                                       1, total_pag)
                if destino is not None:
                    pagina = destino

    def _tabla_validas(self, items, pagina, total_pag) -> Table:
        tabla = Table(
            title=f"[bold {NEON_VERDE}]Incidencias válidas[/]",
            box=box.ROUNDED, border_style=NEON_CIAN, header_style=f"bold {NEON_ROSA}",
            row_styles=["", ZEBRA], expand=True,
        )
        tabla.add_column("ID", no_wrap=True)
        for nombre in self.columnas:
            tabla.add_column(truncar(nombre, 25), overflow="fold")
        tabla.add_column("Estado", justify="center", no_wrap=True)

        for inc in items:
            tabla.add_row(
                Text(truncar(inc.id, 20), style=f"bold {NEON_AMARILLO}"),
                *[Text(truncar(inc.campos.get(n, "—"))) for n in self.columnas],
                Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}"),
            )
        return tabla

    def _tabla_anomalias(self, categoria: str | None):
        def construir(items, pagina, total_pag) -> Table:
            titulo = categoria or "Todas las anomalías"
            tabla = Table(
                title=f"[bold {NEON_ROJO}]Registro de anomalías · {escape(titulo)}[/]",
                box=box.ROUNDED, border_style=NEON_ROSA, header_style=f"bold {NEON_CIAN}",
                expand=True,
            )
            tabla.add_column("ID", no_wrap=True)
            tabla.add_column("Tipo", overflow="fold")
            tabla.add_column("Motivo del rechazo", overflow="fold")
            tabla.add_column("Campo", overflow="fold")
            tabla.add_column("Valor detectado", overflow="fold")

            for indice, inc in enumerate(items):
                fondo = ZEBRA if indice % 2 else ""
                lista = [a for a in inc.anomalias if categoria in (None, a.categoria)]
                for j, a in enumerate(lista):
                    tabla.add_row(
                        Text(truncar(inc.id, 20) if j == 0 else "", style=f"bold {NEON_AMARILLO}"),
                        Text(a.categoria, style=NEON_ROSA),
                        Text(a.motivo, style=f"bold {NEON_ROJO}"),
                        Text(truncar(a.campo, 25), style=NEON_CIAN),
                        Text(truncar(a.valor), style="dim"),
                        style=fondo,
                    )
            return tabla
        return construir

    def _tabla_busqueda(self, termino: str):
        def construir(items, pagina, total_pag) -> Table:
            tabla = Table(
                title=f"[bold {NEON_CIAN}]Resultados para «{escape(termino)}»[/]",
                box=box.ROUNDED, border_style=NEON_CIAN, header_style=f"bold {NEON_ROSA}",
                row_styles=["", ZEBRA], expand=True,
            )
            tabla.add_column("ID", no_wrap=True)
            tabla.add_column("Estado", no_wrap=True)
            tabla.add_column("Campo", overflow="fold")
            tabla.add_column("Coincidencia", overflow="fold")
            for inc, campo, valor in items:
                estado = (Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}") if inc.valida
                          else Text("✖ ANÓMALA", style=f"bold {NEON_ROJO}"))
                tabla.add_row(Text(truncar(inc.id, 20), style=f"bold {NEON_AMARILLO}"),
                              estado, Text(truncar(campo, 25), style=NEON_CIAN),
                              Text(truncar(valor)))
            return tabla
        return construir

    def ver_validas(self) -> None:
        self.paginar(self.validas, self._tabla_validas, "No hay incidencias válidas.")

    def ver_anomalias(self) -> None:
        conteo = Counter(c for i in self.anomalas for c in i.categorias())
        opciones = {f"Todas ({len(self.anomalas)})": None}
        for cat in CATEGORIAS:
            opciones[f"{cat} ({conteo.get(cat, 0)})"] = cat
        volver = "↩  Volver al menú"

        eleccion = seleccionar(self.consola, "¿Qué anomalías quieres ver?",
                               [*opciones, volver])
        if eleccion == volver:
            return
        categoria = opciones[eleccion]
        filtradas = [i for i in self.anomalas if categoria in (None, *i.categorias())]
        self.paginar(filtradas, self._tabla_anomalias(categoria),
                     f"No hay anomalías del tipo «{categoria}».")

    def _detalle(self, inc: Incidencia) -> Panel:
        tabla = Table(box=box.SIMPLE_HEAD, row_styles=["", ZEBRA],
                      header_style=f"bold {NEON_ROSA}", expand=True)
        tabla.add_column("Campo", style=f"bold {NEON_CIAN}")
        tabla.add_column("Valor", overflow="fold")
        for nombre, valor in inc.campos.items():
            tabla.add_row(truncar(nombre, 30), Text(truncar(valor)))
        for nombre in inc.vacios:
            tabla.add_row(truncar(nombre, 30), Text("(vacío)", style=f"bold {NEON_ROJO}"))

        if inc.valida:
            estado = Text("✔ VÁLIDA", style=f"bold {NEON_VERDE}")
        else:
            estado = Text("✖ ANÓMALA\n", style=f"bold {NEON_ROJO}")
            for a in inc.anomalias:
                estado.append(f"  • {a.motivo} ", style=NEON_ROJO)
                estado.append(f"[{a.categoria} · {a.campo}]\n", style="dim")

        return Panel(Group(tabla, estado),
                     title=f"[bold]Incidencia [{NEON_AMARILLO}]{escape(inc.id)}[/][/]",
                     border_style=NEON_VERDE if inc.valida else NEON_ROJO, box=box.HEAVY)

    def buscar(self) -> None:
        termino = pedir_texto(self.consola, "Texto o ID a buscar:").strip()
        if not termino:
            return

        por_id = [i for i in self.todas if i.id.strip().lower() == termino.lower()]
        if por_id:
            self.consola.clear()
            for inc in por_id:
                self.consola.print(self._detalle(inc))
            pausa(self.consola)
            return

        buscado = normalizar(termino)
        resultados = []
        for inc in self.todas:
            for campo, valor in inc.campos.items():
                if buscado in normalizar(valor):
                    resultados.append((inc, campo, valor))
                    break
        self.paginar(resultados, self._tabla_busqueda(termino),
                     f"No se ha encontrado «{termino}» en ningún ID ni campo.")

    def guardar_json(self) -> None:
        """Exporta las incidencias válidas a incidencies.json (Punto 4 del ejercicio)."""
        ruta_json = self.ruta.parent / "incidencies.json"
        
        registros_nuevos = [
            {"id": inc.id, **inc.campos}
            for inc in self.validas
        ]

        self.consola.clear()
        self.consola.print(Panel(
            Text(f"Ruta destino: {ruta_json}", style="dim"),
            title=f"[bold {NEON_VERDE}]💾 Exportación a JSON[/]",
            border_style=NEON_VERDE, box=box.ROUNDED
        ))

        # 1. Si no existe, se crea directamente
        if not ruta_json.exists():
            with open(ruta_json, "w", encoding="utf-8") as f:
                json.dump(registros_nuevos, f, ensure_ascii=False, indent=4)
            self.consola.print(f"\n[{NEON_VERDE}]✔ Fitxer [bold]incidencies.json[/bold] creat amb {len(registros_nuevos)} incidències.[/{NEON_VERDE}]")
            pausa(self.consola)
            return

        # 2. Si ya existe, preguntar qué hacer
        self.consola.print(f"[{NEON_AMARILLO}]⚠ El fitxer 'incidencies.json' ja existeix.[/{NEON_AMARILLO}]\n")
        
        opcion = seleccionar(
            self.consola,
            "Què vols fer amb el fitxer existent?",
            [
                "Sobreescriure'l (esborra el contingut anterior)",
                "Afegir les noves incidències (evita duplicats per ID)",
                "↩ Cancel·lar"
            ]
        )

        if "Sobreescriure" in opcion:
            with open(ruta_json, "w", encoding="utf-8") as f:
                json.dump(registros_nuevos, f, ensure_ascii=False, indent=4)
            self.consola.print(f"\n[{NEON_VERDE}]✔ Fitxer sobreescrit correctament amb {len(registros_nuevos)} incidències.[/{NEON_VERDE}]")

        elif "Afegir" in opcion:
            try:
                with open(ruta_json, "r", encoding="utf-8") as f:
                    existentes = json.load(f)
            except (json.JSONDecodeError, OSError):
                existentes = []

            ids_existentes = {str(item.get("id")) for item in existentes if isinstance(item, dict)}
            
            nuevas_añadidas = 0
            for reg in registros_nuevos:
                if str(reg["id"]) not in ids_existentes:
                    existentes.append(reg)
                    ids_existentes.add(str(reg["id"]))
                    nuevas_añadidas += 1

            with open(ruta_json, "w", encoding="utf-8") as f:
                json.dump(existentes, f, ensure_ascii=False, indent=4)

            self.consola.print(
                f"\n[{NEON_VERDE}]✔ Procés completat: S'han afegit [bold]{nuevas_añadidas}[/bold] noves incidències. "
                f"Total al fitxer: {len(existentes)}.[/{NEON_VERDE}]"
            )

        pausa(self.consola)

    def ejecutar(self) -> None:
        acciones = {
            self.OPCION_VALIDAS: self.ver_validas,
            self.OPCION_ANOMALIAS: self.ver_anomalias,
            self.OPCION_BUSCAR: self.buscar,
            self.OPCION_JSON: self.guardar_json,
        }
        while True:
            self.consola.clear()
            self.mostrar_dashboard()
            eleccion = seleccionar(self.consola, "¿Qué quieres hacer?",
                                   [*acciones, self.OPCION_SALIR])
            if eleccion == self.OPCION_SALIR:
                return
            acciones[eleccion]()


# ══════════════════════════════════════════════════════════════════════════
# 8. PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════

def iniciar(consola: Console) -> int:
    if len(sys.argv) > 1:
        ruta = limpiar_ruta(" ".join(sys.argv[1:]))
    else:
        ruta = pedir_ruta(consola)

    try:
        with consola.status(f"[{NEON_CIAN}]Escaneando el XML...[/]", spinner="dots"):
            raiz, incidencias = cargar_incidencias(ruta)
            validador = ValidadorIncidencias()
            for inc in incidencias:
                validador.validar(inc)
    except ErrorCarga as error:
        panel_error(consola, error.titulo, error.mensaje)
        return 1

    if raiz != "incidencies":
        consola.print(f"[{NEON_AMARILLO}]⚠ La raíz es <{escape(raiz)}>, "
                      f"se esperaba <incidencies>.[/]")
    if not incidencias:
        panel_error(consola, "Sin datos", "El XML no contiene ninguna <incidencia>.")
        return 1

    AppIncidencias(consola, incidencias, ruta).ejecutar()
    despedida(consola)
    return 0


def main() -> int:
    consola = Console()
    try:
        return iniciar(consola)
    except KeyboardInterrupt:
        despedida(consola)
        return 0
    except Exception as error:
        panel_error(consola, "Error inesperado",
                    f"{type(error).__name__}: {error}\n\n"
                    "El programa se ha cerrado de forma controlada.")
        return 1


if __name__ == "__main__":
    sys.exit(main())