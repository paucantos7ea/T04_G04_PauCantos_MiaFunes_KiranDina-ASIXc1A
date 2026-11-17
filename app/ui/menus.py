# -*- coding: utf-8 -*-
"""Menús interactivos con questionary y controlador de la aplicación.

* Entrada -> todas las lecturas de teclado, ya saneadas (nunca deja escapar un
             ValueError; Ctrl+C / fin de entrada suben como KeyboardInterrupt).
* App     -> carga con reintento, menú principal y todas las vistas/filtros.

Si no hay una terminal interactiva (salida redirigida, CI...), los menús con
flechas se sustituyen por menús numerados, que funcionan en cualquier SO.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from app.analytics import Analizador, analizar_archivo
from app.config import (CATEGORIAS, MESES, NEON_AMARILLO, NEON_CIAN, NEON_ROJO, NEON_ROSA,
                        NEON_VERDE, NIVELES, NOMBRE_JSON)
from app.exporter import (escribir_json, fusionar, leer_json_existente,
                          registros_json)
from app.models import ErrorCarga, ErrorExportacion, Incidencia
from app.ui.console import (es_interactiva, panel_aviso, panel_error, texto_exito)
from app.ui.dashboard import panel_severidad, render_dashboard, render_graficas
from app.ui.paginator import (AccionExtra, Paginator, constructor_anomalias,
                              constructor_busqueda, constructor_validas, ficha)
from app.utils import limpiar_ruta, parsear_fecha_usuario

ESTILO_MENU = questionary.Style([
    ("qmark", f"fg:{NEON_ROSA} bold"),
    ("question", "bold"),
    ("pointer", f"fg:{NEON_CIAN} bold"),
    ("highlighted", f"fg:{NEON_CIAN} bold"),
    ("answer", f"fg:{NEON_ROSA} bold"),
])

VOLVER = "↩  Volver al menú"


# ══════════════════════════════════════════════════════════════════════════
# Entrada de usuario
# ══════════════════════════════════════════════════════════════════════════

class Entrada:
    """Nunca devuelve un dato inválido ni deja escapar un ValueError."""

    def __init__(self, consola: Console, interactiva: bool | None = None):
        self.consola = consola
        self.interactiva = es_interactiva() if interactiva is None else interactiva

    def error(self, mensaje: str) -> None:
        self.consola.print(Text(f"✖ {mensaje}", style=f"bold {NEON_ROJO}"))

    def linea(self, mensaje: str) -> str:
        try:
            return self.consola.input(mensaje)
        except EOFError:                 # Ctrl+D / Ctrl+Z+Enter / fin de tubería
            raise KeyboardInterrupt from None

    def seleccionar(self, mensaje: str, opciones: list[str]) -> str:
        """Menú con flechas (o numerado si no hay terminal interactiva)."""
        if self.interactiva:
            return questionary.select(mensaje, choices=opciones, style=ESTILO_MENU,
                                      qmark="➤", pointer="❯").unsafe_ask()
        self.consola.print(Text(mensaje, style="bold"))
        for i, opcion in enumerate(opciones, start=1):
            self.consola.print(Text(f"  {i}. {opcion}"))
        while True:
            entrada = self.linea("Opción: ").strip()
            try:
                numero = int(entrada)
            except ValueError:
                self.error(f"«{entrada}» no es un número de la lista.")
                continue
            if 1 <= numero <= len(opciones):
                return opciones[numero - 1]
            self.error(f"Elige un número entre 1 y {len(opciones)}.")

    def texto(self, mensaje: str) -> str:
        if self.interactiva:
            respuesta = questionary.text(mensaje, style=ESTILO_MENU, qmark="➤").unsafe_ask()
            return (respuesta or "").strip()
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
                self.error(f"«{entrada}» no es un número. Enter para cancelar.")
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
            self.error(f"«{entrada}» no es una fecha válida. "
                       "Usa AAAA-MM-DD (p. ej. 2025-03-15) o DD/MM/AAAA. Enter para cancelar.")

    @staticmethod
    def _validar_ruta(texto: str) -> bool | str:
        if not (texto or "").strip():
            return "Escribe una ruta."
        ruta = limpiar_ruta(texto)
        if not ruta.exists():
            return f"No existe: {ruta}"
        if not ruta.is_file():
            return "Esa ruta es una carpeta, no un archivo."
        return True

    def ruta(self, propuesta: Path | None = None) -> Path:
        """Pide la ruta del XML y no la acepta hasta que el archivo exista."""
        while True:
            if self.interactiva:
                entrada = questionary.path(
                    "Ruta del archivo XML (escríbela, usa Tab o arrastra el archivo):",
                    default=str(propuesta or ""), validate=self._validar_ruta,
                    style=ESTILO_MENU, qmark="➤").unsafe_ask()
            else:
                entrada = self.linea("Ruta del archivo XML: ")
            resultado = self._validar_ruta(entrada)
            if resultado is True:
                return limpiar_ruta(entrada)
            self.error(str(resultado))

    def pausa(self) -> None:
        if self.interactiva:
            questionary.press_any_key_to_continue("Pulsa una tecla para volver...").unsafe_ask()
        else:
            self.linea("Pulsa Enter para volver...")


# ══════════════════════════════════════════════════════════════════════════
# Aplicación
# ══════════════════════════════════════════════════════════════════════════

class App:
    OP_VALIDAS = "✔  Incidencias válidas"
    OP_ANOMALIAS = "✖  Registro de anomalías y fichas de rechazo"
    OP_SEVERIDAD = "▲  Explorar por severidad"
    OP_GRAFICAS = "▇  Gráficas de averías (categorías y equipos)"
    OP_MARCAS = "◉  Filtrar por marca o categoría de equipo"
    OP_FECHAS = "▣  Filtrar por fechas"
    OP_BUSCAR = "⌕  Buscar por texto o ID"
    OP_JSON = "⇩  Guardar incidencias válidas en JSON"
    OP_SALIR = "×  Salir"

    def __init__(self, consola: Console, entrada: Entrada | None = None):
        self.consola = consola
        self.entrada = entrada or Entrada(consola)
        self.paginador = Paginator(consola, self.entrada)
        self._datos: Analizador | None = None

    @property
    def datos(self) -> Analizador:
        if self._datos is None:          # Solo puede pasar si se usa sin cargar()
            raise RuntimeError("No hay ningún XML cargado.")
        return self._datos

    # ── Arranque: carga con reintento ──────────────────────────────────────

    def cargar(self, ruta: Path | None) -> bool:
        """Carga el XML. Si falla, ofrece otra ruta, reintentar o salir."""
        while True:
            if ruta is None:
                ruta = self.entrada.ruta()
            try:
                with self.consola.status(f"[{NEON_CIAN}]Escaneando el XML...[/]", spinner="dots"):
                    self._datos = analizar_archivo(ruta)
                return True
            except ErrorCarga as error:
                self.consola.print(panel_error(error.titulo, error.mensaje))
                otra, misma, salir = ("↻  Probar con otra ruta",
                                      "⟳  Reintentar el mismo archivo", "×  Salir")
                eleccion = self.entrada.seleccionar("¿Qué quieres hacer?", [otra, misma, salir])
                if eleccion == salir:
                    return False
                if eleccion == otra:
                    ruta = None

    def ejecutar(self, ruta: Path | None) -> int:
        """Bucle principal. Devuelve el código de salida."""
        if not self.cargar(ruta):
            return 1
        acciones: dict[str, Callable[[], None]] = {
            self.OP_VALIDAS: self.ver_validas,
            self.OP_ANOMALIAS: self.ver_anomalias,
            self.OP_SEVERIDAD: self.ver_severidad,
            self.OP_GRAFICAS: self.ver_graficas,
            self.OP_MARCAS: self.ver_marcas,
            self.OP_FECHAS: self.ver_fechas,
            self.OP_BUSCAR: self.buscar,
            self.OP_JSON: self.guardar_json,
        }
        while True:
            self.consola.clear()
            self.consola.print(render_dashboard(self.datos))
            eleccion = self.entrada.seleccionar("¿Qué quieres hacer?", [*acciones, self.OP_SALIR])
            if eleccion == self.OP_SALIR:
                return 0
            acciones[eleccion]()

    # ── Utilidades de vista ────────────────────────────────────────────────

    def _aviso_y_pausa(self, mensaje: str) -> None:
        self.consola.print(panel_aviso(mensaje))
        self.entrada.pausa()

    def _extra_ficha(self, solo_anomalas: bool = False) -> AccionExtra:
        texto = "Ficha de rechazo por ID" if solo_anomalas else "Ver ficha por ID"
        return {"I": (texto, lambda: self.inspeccionar_id(solo_anomalas))}

    def _listar_validas(self, incidencias: list[Incidencia], titulo: str, vacio: str) -> None:
        self.paginador.mostrar(incidencias, constructor_validas(titulo), vacio,
                               self._extra_ficha())

    # ── Fichas ─────────────────────────────────────────────────────────────

    def mostrar_fichas(self, incidencias: list[Incidencia]) -> None:
        self.consola.clear()
        for inc in incidencias:          # Puede haber IDs repetidos en el XML
            self.consola.print(ficha(inc))
        self.entrada.pausa()

    def inspeccionar_id(self, solo_anomalas: bool = False) -> None:
        """Pide un ID hasta que exista (Enter cancela) y muestra su ficha."""
        while True:
            texto = self.entrada.texto("ID a inspeccionar (Enter para cancelar):")
            if not texto:
                return
            encontradas = self.datos.por_id(texto, solo_anomalas=solo_anomalas)
            if encontradas:
                self.mostrar_fichas(encontradas)
                return
            tipo = "anómala " if solo_anomalas else ""
            self.entrada.error(f"No hay ninguna incidencia {tipo}con ID «{texto}».")

    # ── Vistas del menú ────────────────────────────────────────────────────

    def ver_validas(self) -> None:
        self._listar_validas(self.datos.validas, "Incidencias válidas",
                             "No hay incidencias válidas.")

    def ver_anomalias(self) -> None:
        r = self.datos.resumen
        opciones: dict[str, str | None] = {f"Todas ({r.anomalas})": None}
        opciones.update({f"{c} ({r.por_categoria.get(c, 0)})": c for c in CATEGORIAS})
        eleccion = self.entrada.seleccionar("¿Qué tipo de anomalía quieres revisar?",
                                            [*opciones, VOLVER])
        if eleccion == VOLVER:
            return
        categoria = opciones[eleccion]
        self.paginador.mostrar(self.datos.anomalas_de(categoria),
                               constructor_anomalias(categoria),
                               f"No hay anomalías del tipo «{categoria}».",
                               self._extra_ficha(solo_anomalas=True))

    def ver_severidad(self) -> None:
        r = self.datos.resumen
        opciones = {f"{n} ({r.por_severidad.get(n, 0)})": n for n in NIVELES}
        self.consola.print(panel_severidad(self.datos))
        eleccion = self.entrada.seleccionar("¿Qué nivel quieres revisar?", [*opciones, VOLVER])
        if eleccion == VOLVER:
            return
        nivel = opciones[eleccion]
        self._listar_validas(self.datos.validas_de_severidad(nivel), f"Severidad {nivel}",
                             f"No hay incidencias válidas de severidad {nivel}.")

    def ver_graficas(self) -> None:
        self.consola.clear()
        self.consola.print(render_graficas(self.datos))
        self.entrada.pausa()

    def ver_marcas(self) -> None:
        """Filtra las válidas por marca. Las que no tienen marca se pueden
        filtrar por su categoría de equipo (Portàtil, Sobretaula, Monitors...)."""
        d = self.datos
        if not d.validas:
            self._aviso_y_pausa("No hay incidencias válidas.")
            return

        sin_marca = d.validas_sin_marca()
        marcas = d.ranking_marcas()
        # Cada opción -> nombre de marca, o None = "sin marca → por categoría"
        opciones: dict[str, str | None] = {f"{marca} ({n})": marca for marca, n in marcas}
        if sin_marca:
            opciones[f"▤  Sin marca → filtrar por categoría de equipo ({len(sin_marca)})"] = None

        titulo = (f"Marcas detectadas: {len(marcas)}"
                  if marcas else "No se ha encontrado ninguna marca en las válidas")
        eleccion = self.entrada.seleccionar(f"{titulo}. ¿Qué quieres ver?", [*opciones, VOLVER])
        if eleccion == VOLVER:
            return
        marca = opciones[eleccion]
        if marca is None:
            self._filtrar_categoria(sin_marca, "sin marca")
            return
        self._listar_validas(d.validas_de_marca(marca), f"Incidencias válidas · {marca}",
                             f"No hay incidencias de {marca}.")

    def _filtrar_categoria(self, incidencias: list[Incidencia], etiqueta: str) -> None:
        """Submenú de categorías de equipo sobre la lista recibida."""
        opciones = {f"{cat} ({n})": cat for cat, n in Analizador.contar_por_categoria(incidencias)}
        eleccion = self.entrada.seleccionar(f"Categoría de equipo ({etiqueta}):",
                                            [*opciones, VOLVER])
        if eleccion == VOLVER:
            return
        categoria = opciones[eleccion]
        self._listar_validas(Analizador.de_categoria(incidencias, categoria),
                             f"Incidencias válidas {etiqueta} · {categoria}",
                             f"No hay incidencias de la categoría {categoria}.")

    # ── Filtro por fechas ──────────────────────────────────────────────────

    def ver_fechas(self) -> None:
        """Filtra las válidas por año/mes existente o por un rango escrito."""
        con_fecha = self.datos.validas_con_fecha()
        if not con_fecha:
            self._aviso_y_pausa("Ninguna incidencia válida tiene una fecha completa "
                                "(día, mes y año).")
            return

        primera = min(i.fecha for i in con_fecha if i.fecha)
        ultima = max(i.fecha for i in con_fecha if i.fecha)
        sin_fecha = len(self.datos.validas) - len(con_fecha)
        op_mes = "▦  Elegir año / mes de los datos"
        op_rango = "↔  Escribir un rango de fechas (AAAA-MM-DD a AAAA-MM-DD)"
        eleccion = self.entrada.seleccionar(
            f"Datos del {primera:%d/%m/%Y} al {ultima:%d/%m/%Y}"
            + (f" ({sin_fecha} válidas sin fecha completa)" if sin_fecha else "")
            + ". ¿Cómo quieres filtrar?",
            [op_mes, op_rango, VOLVER])
        if eleccion == VOLVER:
            return

        resultado = (self._elegir_anyo_mes(con_fecha) if eleccion == op_mes
                     else self._pedir_rango(con_fecha, primera, ultima))
        if resultado is None:
            return
        titulo, seleccion = resultado
        self._listar_validas(seleccion, titulo, "No hay incidencias válidas en ese periodo.")

    def _elegir_anyo_mes(self, con_fecha: list[Incidencia]) -> tuple[str, list[Incidencia]] | None:
        """Año y mes se sacan de los datos: solo se ofrece lo que existe."""
        volver = "↩  Volver"
        op_anyo = {f"{a} ({n})": a for a, n in Analizador.anyos_disponibles(con_fecha)}
        eleccion = self.entrada.seleccionar("Elige el año:", [*op_anyo, volver])
        if eleccion == volver:
            return None
        anyo = op_anyo[eleccion]
        del_anyo = Analizador.en_periodo(con_fecha, anyo)

        op_mes: dict[str, int | None] = {f"Todo {anyo} ({len(del_anyo)})": None}
        op_mes.update({f"{MESES[m - 1].capitalize()} {anyo} ({n})": m
                       for m, n in Analizador.meses_disponibles(con_fecha, anyo)})
        eleccion = self.entrada.seleccionar("Elige el mes:", [*op_mes, volver])
        if eleccion == volver:
            return None
        mes = op_mes[eleccion]
        if mes is None:
            return f"Incidencias válidas · año {anyo}", del_anyo
        return (f"Incidencias válidas · {MESES[mes - 1]} de {anyo}",
                Analizador.en_periodo(con_fecha, anyo, mes))

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
                Analizador.en_rango(con_fecha, desde, hasta))

    # ── Búsqueda ───────────────────────────────────────────────────────────

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
                               constructor_busqueda(termino),
                               f"No se ha encontrado «{termino}» en ningún ID ni campo.",
                               self._extra_ficha())

    # ── Exportación a JSON ─────────────────────────────────────────────────

    def guardar_json(self) -> None:
        """Exporta las válidas a incidencies.json, en la misma carpeta que el XML.

        * Si no existe, lo crea.
        * Si existe: sobreescribir, añadir sin duplicar IDs o cancelar.
        """
        ruta_json = self.datos.ruta.parent / NOMBRE_JSON
        nuevos = registros_json(self.datos.validas)

        self.consola.clear()
        self.consola.print(Panel(
            Text.assemble(("Ruta destí: ", "dim"), (str(ruta_json), "bold"),
                          ("\nIncidències vàlides a exportar: ", "dim"),
                          (str(len(nuevos)), f"bold {NEON_VERDE}")),
            title=f"[bold {NEON_VERDE}]⇩ Exportació a JSON[/]",
            border_style=NEON_VERDE, box=box.ROUNDED))

        if not nuevos:
            self.entrada.error("No hi ha incidències vàlides per exportar.")
            self.entrada.pausa()
            return

        try:
            if not ruta_json.exists():
                escribir_json(ruta_json, nuevos)
                self.consola.print(texto_exito(
                    f"Fitxer {NOMBRE_JSON} creat amb {len(nuevos)} incidències."))
            else:
                self._actualizar_json_existente(ruta_json, nuevos)
        except OSError as error:   # Sin permisos, disco lleno, ruta bloqueada...
            self.consola.print(panel_error("No s'ha pogut desar el JSON",
                                           f"{type(error).__name__}: {error}"))
        self.entrada.pausa()

    def _actualizar_json_existente(self, ruta_json: Path, nuevos: list[dict[str, str]]) -> None:
        self.consola.print(Text(f"⚠ El fitxer '{NOMBRE_JSON}' ja existeix.\n",
                                style=NEON_AMARILLO))
        sobreescribir = "Sobreescriure'l (esborra el contingut anterior)"
        anadir = "Afegir les noves incidències (evita duplicats per ID)"
        cancelar = "↩  Cancel·lar"
        opcion = self.entrada.seleccionar("Què vols fer amb el fitxer existent?",
                                          [sobreescribir, anadir, cancelar])

        if opcion == cancelar:
            self.consola.print("[dim]Operació cancel·lada. No s'ha modificat res.[/]")
            return
        if opcion == sobreescribir:
            escribir_json(ruta_json, nuevos)
            self.consola.print(texto_exito(
                f"Fitxer sobreescrit correctament amb {len(nuevos)} incidències."))
            return

        # ── Añadir: se fusiona con lo que ya hay ───────────────────────────
        try:
            existentes = leer_json_existente(ruta_json)
        except ErrorExportacion as error:
            # No se puede fusionar sin perder datos: se pregunta, no se borra en silencio
            self.entrada.error(str(error))
            forzar = "Sobreescriure'l igualment"
            no_tocar = "↩  Cancel·lar (no tocar el fitxer)"
            if self.entrada.seleccionar("No es pot afegir sobre aquest fitxer. Què vols fer?",
                                        [forzar, no_tocar]) == forzar:
                escribir_json(ruta_json, nuevos)
                self.consola.print(texto_exito(
                    f"Fitxer sobreescrit amb {len(nuevos)} incidències."))
            else:
                self.consola.print("[dim]Operació cancel·lada. No s'ha modificat res.[/]")
            return

        total, anadidas = fusionar(existentes, nuevos)
        escribir_json(ruta_json, total)
        self.consola.print(texto_exito(
            f"Procés completat: s'han afegit {anadidas} noves incidències "
            f"({len(nuevos) - anadidas} ja hi eren). Total al fitxer: {len(total)}."))
