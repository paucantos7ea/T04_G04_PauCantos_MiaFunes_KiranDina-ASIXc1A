# -*- coding: utf-8 -*-
"""Motor de detección de anomalías, fechas, marcas y severidad.

* AnomalyDetector -> decide VÁLIDA / ANÓMALA y por qué (rellena `anomalias`).
* Clasificador    -> deduce equipo, descripción, categoría, marca y severidad.
* procesar()      -> aplica ambos, en ese orden, a toda la lista.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from app.config import (ANYO_MINIMO, CAMPOS_OBLIGATORIOS, CAT_BASURA, CAT_DESBORDE,
                        CAT_FECHA, CAT_VACIO, CATEGORIA_POR_DEFECTO, MAPA_SEVERIDAD,
                        MARCAS_REALES, MAX_LONGITUD_CORTO, PALABRAS_BASURA, RE_AMARICO,
                        RE_ANYO, RE_BASURA, RE_BINARIO, RE_CAMPO_CORTO,
                        RE_CAMPO_DESCRIPCION, RE_CAMPO_EQUIPO, RE_CAMPO_FECHA,
                        RE_CAMPO_MARCA, RE_CAMPO_MODELO, RE_CAMPO_NO_EQUIPO,
                        RE_CAMPO_NO_MARCA, RE_CAMPO_OPCIONAL, RE_CAMPO_SEVERIDAD,
                        RE_CAMPO_TIPO, RE_FECHA, RE_SEV_ALTA_ARRANQUE, RE_SEV_ALTA_HW,
                        RE_SEV_CRITICA, RE_SEV_LEVE, RE_SEV_MEDIA, SEVERIDAD_POR_DEFECTO,
                        TIPOS_DISPOSITIVO)
from app.models import Anomalia, Incidencia
from app.utils import canonico, decodificar_binario, normalizar, valor_real

Regla = Callable[[Incidencia, str, str], "Anomalia | None"]


# ══════════════════════════════════════════════════════════════════════════
# Detección de anomalías
# ══════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """Aplica todas las reglas y rellena `incidencia.anomalias`.

    Cada regla recibe (incidencia, nombre_campo, valor) y devuelve None si el
    campo está bien, o una Anomalia con la causa precisa.
    """

    def __init__(self, anyo_minimo: int = ANYO_MINIMO, hoy: date | None = None):
        self.anyo_minimo = anyo_minimo
        self.hoy = hoy or date.today()
        self.obligatorios = {normalizar(c): c for c in CAMPOS_OBLIGATORIOS}
        self.reglas: tuple[Regla, ...] = (
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
            if RE_CAMPO_OPCIONAL.search(nombre) and not RE_CAMPO_NO_MARCA.search(nombre):
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
        """Añade 'en campo de código' si la basura está en un campo breve."""
        return f" en campo de código «{nombre}»" if RE_CAMPO_CORTO.search(nombre) else ""

    def _anyo_incorrecto(self, anyo: int) -> str | None:
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
            regla = self._anyo_incorrecto(int(anyo))
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
            regla = self._anyo_incorrecto(int(anyo))
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
# Clasificación: equipo, categoría, marca y severidad
# ══════════════════════════════════════════════════════════════════════════

class Clasificador:
    """Deduce equipo, descripción, categoría, marca y severidad de cada incidencia."""

    def enriquecer(self, inc: Incidencia) -> Incidencia:
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

        inc.tipo = self.categoria(inc, texto_equipo, texto_desc)
        inc.marca = self.marca(inc, texto_equipo, texto_desc)
        texto_severidad = " ".join((texto_desc, texto_equipo, normalizar(inc.tipo)))
        inc.severidad, inc.severidad_inferida = self.severidad(inc, texto_severidad)
        return inc

    @staticmethod
    def categoria(inc: Incidencia, texto_equipo: str, texto_desc: str) -> str:
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
    def marca(inc: Incidencia, texto_equipo: str, texto_desc: str) -> str | None:
        """1) Lectura directa del nodo <camp nom="Marca d'equip"> (se unifica si
              es conocida: "hewlett packard" -> "HP"; si no, se respeta tal cual).
              "Marca de temps" queda excluida: es un timestamp, no una marca.
        2) Si falta, está vacío o es "-": REGEX de marcas conocidas sobre el
           equipo/modelo y después sobre la descripción.
        Las marcas basura (Pull & Bear...) no llegan aquí como válidas: el
        AnomalyDetector ya ha rechazado esas incidencias."""
        campo = inc.buscar_campo(RE_CAMPO_MARCA, excluir=RE_CAMPO_NO_MARCA)
        if campo and (real := valor_real(campo[1])):
            return canonico(normalizar(real), MARCAS_REALES) or real
        for texto in (texto_equipo, texto_desc):
            if nombre := canonico(texto, MARCAS_REALES):
                return nombre
        return None

    @staticmethod
    def severidad(inc: Incidencia, texto: str) -> tuple[str, bool]:
        """Devuelve (nivel, inferida). Si el XML trae un campo de prioridad se
        usa su valor; si no, se aplica el orden explicado en config.py."""
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


def procesar(incidencias: Iterable[Incidencia], hoy: date | None = None) -> list[Incidencia]:
    """Valida y después clasifica cada incidencia (la validación fija la fecha)."""
    detector, clasificador = AnomalyDetector(hoy=hoy), Clasificador()
    resultado = []
    for inc in incidencias:
        detector.validar(inc)
        clasificador.enriquecer(inc)
        resultado.append(inc)
    return resultado
