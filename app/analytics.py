# -*- coding: utf-8 -*-
"""Cálculo de métricas, rankings por equipo/tipo/marca y consultas de filtrado."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from app.config import (CATEGORIA_POR_DEFECTO, ESTADO_GESTION_DEFECTO, MARGEN_DUPLICADO_DIAS,
                        MIN_FALLOS_CRONICO, MIN_FALLOS_REINCIDENTE, MIN_FALLOS_VENTANA,
                        MIN_TORMENTA, MINERIA_IGNORAR, NIVELES, RE_CAMPO_CODIGO, RE_CAMPO_ZONA,
                        SLA_HORAS, STOPWORDS, TENDENCIA_CALIENTE, TENDENCIA_VIGILAR,
                        UMBRAL_DUPLICADO, VENTANA_RECIENTE_DIAS, VENTANA_TORMENTA_DIAS)
from app.models import EstadisticasResumen, Incidencia
from app.parser import XMLParser
from app.rules import Reglas
from app.utils import normalizar
from app.validator import procesar


def calcular_resumen(incidencias: list[Incidencia]) -> EstadisticasResumen:
    """Agrega todas las métricas en una sola pasada lógica."""
    validas = [i for i in incidencias if i.valida]
    anomalas = [i for i in incidencias if not i.valida]
    return EstadisticasResumen(
        total=len(incidencias),
        validas=len(validas),
        anomalas=len(anomalas),
        por_tipo=Counter(i.tipo for i in validas),
        por_equipo=Counter(i.equipo for i in validas if i.equipo),
        por_severidad=Counter(i.severidad for i in validas),
        por_marca=Counter(i.marca for i in validas if i.marca),
        por_categoria=Counter(c for i in anomalas for c in i.categorias()),
        por_mes=Counter((i.fecha.year, i.fecha.month) for i in validas if i.fecha),
    )


class Analizador:
    """Resultado de analizar un XML: listas, métricas cacheadas y consultas."""

    def __init__(self, ruta: Path, incidencias: list[Incidencia]):
        self.ruta = ruta
        self.todas = incidencias
        self.validas = [i for i in incidencias if i.valida]
        self.anomalas = [i for i in incidencias if not i.valida]
        self.resumen = calcular_resumen(incidencias)
        self._indice_id: dict[str, list[Incidencia]] = {}
        for inc in incidencias:          # Puede haber IDs repetidos en el XML
            self._indice_id.setdefault(inc.id.strip().lower(), []).append(inc)

    # ── Búsquedas ──────────────────────────────────────────────────────────

    def por_id(self, texto: str, solo_anomalas: bool = False) -> list[Incidencia]:
        encontradas = self._indice_id.get(texto.strip().lower(), [])
        return [i for i in encontradas if not i.valida] if solo_anomalas else encontradas

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

    # ── Filtros ────────────────────────────────────────────────────────────

    def anomalas_de(self, categoria: str | None) -> list[Incidencia]:
        return [i for i in self.anomalas if categoria is None or categoria in i.categorias()]

    def validas_de_severidad(self, nivel: str) -> list[Incidencia]:
        return [i for i in self.validas if i.severidad == nivel]

    def validas_de_marca(self, marca: str) -> list[Incidencia]:
        return [i for i in self.validas if i.marca == marca]

    def validas_sin_marca(self) -> list[Incidencia]:
        return [i for i in self.validas if not i.marca]

    def validas_con_fecha(self) -> list[Incidencia]:
        return [i for i in self.validas if i.fecha]

    @staticmethod
    def de_categoria(incidencias: list[Incidencia], categoria: str) -> list[Incidencia]:
        return [i for i in incidencias if i.tipo == categoria]

    @staticmethod
    def en_rango(incidencias: list[Incidencia], desde: date, hasta: date) -> list[Incidencia]:
        """Incidencias con fecha en [desde, hasta], en orden cronológico."""
        return sorted((i for i in incidencias if i.fecha and desde <= i.fecha <= hasta),
                      key=lambda i: i.fecha)

    @staticmethod
    def en_periodo(incidencias: list[Incidencia], anyo: int,
                   mes: int | None = None) -> list[Incidencia]:
        """Incidencias de un año (y opcionalmente un mes), en orden cronológico."""
        return sorted((i for i in incidencias if i.fecha and i.fecha.year == anyo
                       and (mes is None or i.fecha.month == mes)),
                      key=lambda i: i.fecha)

    # ── Rankings y agregaciones ────────────────────────────────────────────

    @staticmethod
    def contar_por_categoria(incidencias: list[Incidencia]) -> list[tuple[str, int]]:
        return Counter(i.tipo for i in incidencias).most_common()

    @staticmethod
    def anyos_disponibles(incidencias: list[Incidencia]) -> list[tuple[int, int]]:
        """[(año, nº), ...] del más reciente al más antiguo."""
        return sorted(Counter(i.fecha.year for i in incidencias if i.fecha).items(),
                      reverse=True)

    @staticmethod
    def meses_disponibles(incidencias: list[Incidencia], anyo: int) -> list[tuple[int, int]]:
        """[(mes, nº), ...] del año indicado, en orden."""
        return sorted(Counter(i.fecha.month for i in incidencias
                              if i.fecha and i.fecha.year == anyo).items())

    def ranking_equipos(self, top: int) -> list[tuple[str, int]]:
        return self.resumen.por_equipo.most_common(top)

    def ranking_tipos(self) -> list[tuple[str, int]]:
        return self.resumen.por_tipo.most_common()

    def ranking_marcas(self) -> list[tuple[str, int]]:
        return self.resumen.por_marca.most_common()


def analizar_archivo(ruta: Path, hoy: date | None = None,
                     reglas: Reglas | None = None) -> Analizador:
    """Tubería completa: parsear -> reparar/validar/clasificar -> métricas.

    Lanza models.ErrorCarga si el archivo no se puede usar.
    """
    _, incidencias = XMLParser().cargar(ruta)
    return Analizador(ruta, procesar(incidencias, hoy=hoy, reglas=reglas))


# ══════════════════════════════════════════════════════════════════════════
# Radar de zonas y equipos reincidentes
# ══════════════════════════════════════════════════════════════════════════

NIVEL_CRONICO, NIVEL_REINCIDENTE, NIVEL_CALIENTE, NIVEL_VIGILAR, NIVEL_NORMAL = (
    "🔥 Crónico", "⚠️ Reincidente", "🔥 Punto caliente", "⚠️ Vigilar", "Normal")


@dataclass
class PuntoCaliente:
    """Una zona o un equipo con su historial de fallos (solo incidencias válidas)."""
    clave: str
    tipo: str                       # "Zona" | "Equipo"
    total: int
    recientes: int                  # Fallos en la ventana reciente
    primera: date | None
    ultima: date | None
    nivel: str = NIVEL_NORMAL
    zona: str = ""
    categoria: str = ""
    ids: list[str] = field(default_factory=list)
    tendencia: float = 0.0          # Zonas: ritmo reciente / ritmo histórico

    @property
    def alerta(self) -> bool:
        return self.nivel != NIVEL_NORMAL


def _valor(inc: Incidencia, patron: re.Pattern[str]) -> str:
    campo = inc.buscar_campo(patron)
    return " ".join(campo[1].split()) if campo else ""


def fecha_referencia(incidencias: list[Incidencia]) -> date | None:
    """Fecha desde la que se miden las "ventanas recientes".

    Es el percentil 98 de las fechas válidas, no la máxima: así un par de
    incidencias sueltas muy posteriores al resto no dejan la ventana vacía.
    """
    fechas = sorted(i.fecha for i in incidencias if i.valida and i.fecha)
    if not fechas:
        return None
    return fechas[min(len(fechas) - 1, int(len(fechas) * 0.98))]


def _agrupar(incidencias: list[Incidencia], clave, tipo: str,
             referencia: date | None, ventana: int) -> list[PuntoCaliente]:
    grupos: dict[str, list[Incidencia]] = defaultdict(list)
    for inc in incidencias:
        if inc.valida and (k := clave(inc)):
            grupos[k].append(inc)
    desde = referencia - timedelta(days=ventana) if referencia else None
    puntos = []
    for k, lista in grupos.items():
        fechas = sorted(i.fecha for i in lista if i.fecha)
        recientes = sum(1 for f in fechas if desde and f > desde)
        puntos.append(PuntoCaliente(
            k, tipo, len(lista), recientes, fechas[0] if fechas else None,
            fechas[-1] if fechas else None,
            zona=Counter(_valor(i, RE_CAMPO_ZONA) for i in lista).most_common(1)[0][0],
            categoria=Counter(i.tipo for i in lista).most_common(1)[0][0],
            ids=[i.id for i in lista]))
    return puntos


def radar_zonas(incidencias: list[Incidencia], referencia: date | None = None,
                ventana: int = VENTANA_RECIENTE_DIAS) -> list[PuntoCaliente]:
    """Zonas ordenadas por fallos recientes.

    Alerta según la TENDENCIA: fallos en la ventana frente a los que le
    tocarían a esa zona por su ritmo histórico (1.0 = lo normal; 1.3 = un 30 %
    más de lo habitual -> punto caliente)."""
    referencia = referencia or fecha_referencia(incidencias)
    puntos = _agrupar(incidencias, lambda i: _valor(i, RE_CAMPO_ZONA), "Zona",
                      referencia, ventana)
    inicio = min((p.primera for p in puntos if p.primera), default=None)
    if referencia and inicio:
        periodo = max(ventana, (referencia - inicio).days + 1)
        for p in puntos:
            esperado = p.total * ventana / periodo      # Fallos "normales" en la ventana
            p.tendencia = p.recientes / esperado if esperado else 0.0
            if p.recientes >= 3 and p.tendencia >= TENDENCIA_CALIENTE:
                p.nivel = NIVEL_CALIENTE
            elif p.recientes >= 3 and p.tendencia >= TENDENCIA_VIGILAR:
                p.nivel = NIVEL_VIGILAR
    return sorted(puntos, key=lambda p: (p.recientes, p.total), reverse=True)


def equipos_reincidentes(incidencias: list[Incidencia], referencia: date | None = None,
                         ventana: int = VENTANA_RECIENTE_DIAS * 3,
                         minimo: int = MIN_FALLOS_REINCIDENTE) -> list[PuntoCaliente]:
    """Equipos (por código de inventario) con fallos repetidos.

    Crónico: ≥ MIN_FALLOS_CRONICO fallos en total o ≥ MIN_FALLOS_VENTANA en la ventana.
    Reincidente: ≥ MIN_FALLOS_REINCIDENTE fallos en total.
    """
    referencia = referencia or fecha_referencia(incidencias)
    puntos = _agrupar(incidencias, lambda i: _valor(i, RE_CAMPO_CODIGO).upper(), "Equipo",
                      referencia, ventana)
    salida = []
    for p in puntos:
        if p.total >= MIN_FALLOS_CRONICO or p.recientes >= MIN_FALLOS_VENTANA:
            p.nivel = NIVEL_CRONICO
        elif p.total >= minimo:
            p.nivel = NIVEL_REINCIDENTE
        else:
            continue
        salida.append(p)
    return sorted(salida, key=lambda p: (p.nivel == NIVEL_CRONICO, p.recientes, p.total),
                  reverse=True)


def zonas_por_mes(incidencias: list[Incidencia]) -> list[tuple[str, str, int]]:
    """[(zona, 'AAAA-MM', fallos)] de las válidas: base del mapa de calor."""
    conteo = Counter((_valor(i, RE_CAMPO_ZONA), f"{i.fecha:%Y-%m}")
                     for i in incidencias if i.valida and i.fecha and _valor(i, RE_CAMPO_ZONA))
    return [(z, m, n) for (z, m), n in sorted(conteo.items())]


# ══════════════════════════════════════════════════════════════════════════
# Minería de palabras en incidencias sin clasificar
# ══════════════════════════════════════════════════════════════════════════

RE_PALABRA_MINERIA = re.compile(r"[a-z]{3,}")


@dataclass
class Termino:
    texto: str
    tipo: str                       # "Palabra" | "Bigrama"
    incidencias: int                # En cuántas incidencias aparece
    ejemplo: str = ""


def _tokens(texto: str) -> list[str]:
    limpio = normalizar(texto.replace("\u2019", "'")).replace("'", " ")
    return [t for t in RE_PALABRA_MINERIA.findall(limpio)
            if t not in STOPWORDS and t not in MINERIA_IGNORAR]


def palabras_emergentes(incidencias: list[Incidencia], patrones_conocidos: list[re.Pattern[str]],
                        top: int = 15, minimo: int = 2) -> list[Termino]:
    """Palabras y bigramas frecuentes en las válidas SIN clasificar bien
    (categoría por defecto o severidad Media) que todavía no son palabra clave
    de ninguna regla de severidad: candidatos a añadirse a rules.json."""
    conocida = lambda t: any(p.search(t) for p in patrones_conocidos)  # noqa: E731
    docs: Counter[tuple[str, str]] = Counter()
    ejemplos: dict[tuple[str, str], str] = {}
    for inc in incidencias:
        if not inc.valida or (inc.tipo != CATEGORIA_POR_DEFECTO and inc.severidad != "Media"):
            continue
        tokens = _tokens(inc.descripcion)
        terminos = {("Palabra", t) for t in tokens}
        terminos |= {("Bigrama", f"{a} {b}") for a, b in zip(tokens, tokens[1:])}
        for termino in terminos:
            docs[termino] += 1
            ejemplos.setdefault(termino, inc.descripcion)
    salida = [Termino(texto, tipo, n, ejemplos[(tipo, texto)])
              for (tipo, texto), n in docs.most_common()
              if n >= minimo and not conocida(texto)]
    palabras = [t for t in salida if t.tipo == "Palabra"][:top]
    bigramas = [t for t in salida if t.tipo == "Bigrama"][:top]
    return palabras + bigramas


# ══════════════════════════════════════════════════════════════════════════
# Incidencias masivas (tormentas) y tickets duplicados
# ══════════════════════════════════════════════════════════════════════════

def zona_de(inc: Incidencia) -> str:
    """Planta u oficina de la incidencia («Primera planta», «Recepció»…), o ""."""
    return _valor(inc, RE_CAMPO_ZONA)


def sintoma_de(inc: Incidencia) -> str:
    """Síntoma principal: el paso del motor que decidió la severidad, sin el número."""
    criterio = inc.criterio_severidad or ""
    return criterio.split(" · ", 1)[-1] if criterio else inc.tipo


def _peor(severidades) -> str:
    presentes = set(severidades)
    return next((n for n in NIVELES if n in presentes), "")


@dataclass
class Tormenta:
    """Varias incidencias de la misma planta/oficina y categoría en pocos días."""
    zona: str
    categoria: str
    desde: date
    hasta: date
    sintoma: str                    # Síntoma más repetido del grupo
    ids: list[str]
    severidad: str                  # La más grave del grupo

    @property
    def n(self) -> int:
        return len(self.ids)


def detectar_tormentas(incidencias: list[Incidencia], minimo: int = MIN_TORMENTA,
                       ventana_dias: int = VENTANA_TORMENTA_DIAS) -> list[Tormenta]:
    """Agrupa las válidas por (planta/oficina, categoría) y, dentro de cada
    grupo, encadena las que distan como mucho `ventana_dias` días de la anterior
    (0 = el mismo día). Un grupo con ≥ `minimo` incidencias es una tormenta.

    Orden: las más grandes primero; a igual tamaño, las más recientes.
    """
    grupos: dict[tuple[str, str], list[Incidencia]] = defaultdict(list)
    for inc in incidencias:
        if inc.valida and inc.fecha and (zona := zona_de(inc)):
            grupos[(zona, inc.tipo)].append(inc)
    tormentas = []
    for (zona, categoria), lista in grupos.items():
        lista.sort(key=lambda i: (i.fecha, i.id))
        tramo: list[Incidencia] = []
        for inc in [*lista, None]:                      # None = cierra el último tramo
            if inc is not None and tramo and (inc.fecha - tramo[-1].fecha).days <= ventana_dias:
                tramo.append(inc)
                continue
            if len(tramo) >= minimo:
                tormentas.append(Tormenta(
                    zona, categoria, tramo[0].fecha, tramo[-1].fecha,
                    Counter(sintoma_de(i) for i in tramo).most_common(1)[0][0],
                    [i.id for i in tramo], _peor(i.severidad for i in tramo)))
            tramo = [inc] if inc is not None else []
    return sorted(tormentas, key=lambda t: (t.n, t.hasta), reverse=True)


@dataclass
class GrupoDuplicado:
    """Tickets que describen lo mismo en el mismo equipo/ubicación.

    El primero (más antiguo) se considera el original; el resto, duplicados."""
    equipo: str                     # Código de inventario (o equipo + zona si no hay)
    zona: str
    desde: date
    hasta: date
    ids: list[str]
    similitud: float                # Similitud mínima entre parejas enlazadas (0-1)
    descripcion: str                # Texto del original

    @property
    def original(self) -> str:
        return self.ids[0]

    @property
    def duplicados(self) -> list[str]:
        return self.ids[1:]


def similitud(a: str, b: str) -> float:
    """Similitud 0-1 entre dos descripciones (sin tildes, mayúsculas ni espacios extra)."""
    a, b = " ".join(normalizar(a).split()), " ".join(normalizar(b).split())
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def detectar_duplicados(incidencias: list[Incidencia], umbral: float = UMBRAL_DUPLICADO,
                        margen_dias: int = MARGEN_DUPLICADO_DIAS) -> list[GrupoDuplicado]:
    """Parejas de válidas del MISMO equipo (código de inventario; si no hay,
    equipo + zona) con fechas a ≤ `margen_dias` días y descripciones con
    similitud ≥ `umbral`. Las parejas se encadenan: si A≈B y B≈C, es un grupo."""
    grupos: dict[str, list[Incidencia]] = defaultdict(list)
    for inc in incidencias:
        if not (inc.valida and inc.fecha):
            continue
        clave = _valor(inc, RE_CAMPO_CODIGO).upper()
        if not clave and inc.equipo:
            clave = f"{normalizar(inc.equipo)} @ {normalizar(zona_de(inc))}"
        if clave:
            grupos[clave].append(inc)

    salida = []
    for clave, lista in grupos.items():
        if len(lista) < 2:
            continue
        lista.sort(key=lambda i: (i.fecha, i.id))
        padre = list(range(len(lista)))

        def raiz(x: int) -> int:
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        minima: dict[int, float] = {}
        for a in range(len(lista)):
            for b in range(a + 1, len(lista)):
                if (lista[b].fecha - lista[a].fecha).days > margen_dias:
                    break                               # Ordenadas: las siguientes, más lejos
                s = similitud(lista[a].descripcion, lista[b].descripcion)
                if s >= umbral:
                    ra, rb = raiz(a), raiz(b)
                    padre[rb] = ra
                    minima[ra] = min(s, minima.get(ra, 1.0), minima.pop(rb, 1.0))
        componentes: dict[int, list[int]] = defaultdict(list)
        for x in range(len(lista)):
            componentes[raiz(x)].append(x)
        for r, miembros in componentes.items():
            if len(miembros) < 2:
                continue
            incs = [lista[x] for x in sorted(miembros)]
            salida.append(GrupoDuplicado(
                clave, zona_de(incs[0]), incs[0].fecha, incs[-1].fecha, [i.id for i in incs],
                round(min(minima.get(raiz(x), 1.0) for x in miembros), 3), incs[0].descripcion))
    return sorted(salida, key=lambda g: (len(g.ids), g.hasta), reverse=True)


def unicas_estimadas(validas: int, tormentas: list[Tormenta],
                     duplicados: list[GrupoDuplicado]) -> int:
    """Incidencias «reales» si cada tormenta y cada grupo de duplicados contara
    como un solo fallo (sin descontar dos veces las que están en ambos)."""
    redundantes: set[str] = set()
    for grupo in [*tormentas, *duplicados]:
        redundantes.update(grupo.ids[1:])
    return max(0, validas - len(redundantes))


# ══════════════════════════════════════════════════════════════════════════
# Tiempos de resolución: MTTR y SLA
# ══════════════════════════════════════════════════════════════════════════

class _Seguimiento(Protocol):            # gestion.EstadoReparacion (sin importarlo: sin ciclos)
    estado: str
    duracion_minutos: float | None


@dataclass
class ResumenMTTR:
    """Tiempo medio de resolución (minutos) de las resueltas con tiempo medido."""
    minutos: float | None
    resueltas: int
    por_severidad: dict[str, tuple[float, int]]      # nivel -> (media en minutos, n)


def calcular_mttr(incidencias: list[Incidencia],
                  seguimiento: Mapping[str, _Seguimiento]) -> ResumenMTTR:
    """MTTR global y por severidad. Solo cuentan las válidas resueltas que
    tienen `duracion_minutos` (pasaron por «En curso» antes de resolverse)."""
    por_nivel: dict[str, list[float]] = defaultdict(list)
    vistos: set[str] = set()
    for inc in incidencias:
        if not inc.valida or inc.id in vistos:
            continue
        vistos.add(inc.id)
        g = seguimiento.get(inc.id)
        if g and g.estado == "Resuelta" and g.duracion_minutos is not None:
            por_nivel[inc.severidad].append(float(g.duracion_minutos))
    todas = [m for lista in por_nivel.values() for m in lista]
    return ResumenMTTR(
        sum(todas) / len(todas) if todas else None, len(todas),
        {n: (sum(por_nivel[n]) / len(por_nivel[n]), len(por_nivel[n]))
         for n in NIVELES if por_nivel.get(n)})


def formato_duracion(minutos: float | None) -> str:
    """45 min · 3 h 20 min · 2 d 4 h  («—» si no hay dato)."""
    if minutos is None:
        return "—"
    minutos = round(minutos)
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas < 48:
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h" if horas else f"{dias} d"


RE_MARCA_TEMPS = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?")


def apertura(inc: Incidencia) -> datetime | None:
    """Cuándo se abrió el ticket: la «Marca de temps» del formulario y, si no
    se puede leer, la fecha de la incidencia a las 00:00."""
    marca = inc.campos.get("Marca de temps", "")
    if m := RE_MARCA_TEMPS.match(marca):
        d, mes, a, h, mi, s = m.groups()
        try:
            return datetime(int(a), int(mes), int(d), int(h), int(mi), int(s or 0))
        except ValueError:
            pass
    return datetime.combine(inc.fecha, datetime.min.time()) if inc.fecha else None


@dataclass
class AlertaSLA:
    id: str
    severidad: str
    estado: str
    abierta_desde: datetime
    horas_abierta: float
    limite_horas: int
    zona: str
    equipo: str
    descripcion: str

    @property
    def exceso_horas(self) -> float:
        return self.horas_abierta - self.limite_horas


def fuera_de_sla(incidencias: list[Incidencia], seguimiento: Mapping[str, _Seguimiento],
                 ahora: datetime | None = None,
                 limites: Mapping[str, int] | None = None) -> list[AlertaSLA]:
    """Válidas de severidad con SLA (Crítica/Alta) que siguen sin resolver y
    llevan abiertas más horas de las permitidas. Las más graves y viejas primero."""
    ahora = ahora or datetime.now()
    limites = SLA_HORAS if limites is None else limites
    alertas, vistos = [], set()
    for inc in incidencias:
        limite = limites.get(inc.severidad)
        if not inc.valida or limite is None or inc.id in vistos:
            continue
        vistos.add(inc.id)
        g = seguimiento.get(inc.id)
        estado = g.estado if g else ESTADO_GESTION_DEFECTO
        if estado == "Resuelta" or (desde := apertura(inc)) is None:
            continue
        horas = (ahora - desde).total_seconds() / 3600
        if horas > limite:
            alertas.append(AlertaSLA(inc.id, inc.severidad, estado, desde, horas, limite,
                                     zona_de(inc), inc.equipo, inc.descripcion))
    return sorted(alertas, key=lambda a: (NIVELES.index(a.severidad), -a.horas_abierta))
