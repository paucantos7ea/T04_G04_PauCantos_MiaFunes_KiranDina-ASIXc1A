# -*- coding: utf-8 -*-
"""Motor de detección de anomalías, fechas, marcas y severidad.

* AnomalyDetector -> decide VÁLIDA / ANÓMALA y por qué (rellena `anomalias`).
* Clasificador    -> deduce equipo, descripción, categoría, marca y severidad.
* procesar()      -> aplica ambos, en ese orden, a toda la lista.

Además de decidir, ambos dejan TRAZABILIDAD en cada incidencia: el motivo
detallado de cada rechazo (`Anomalia.motivo`), la regla/palabra clave exacta
que fijó la severidad, cómo se dedujeron categoría y marca, y una traza
paso a paso (`Incidencia.traza`) que la interfaz web muestra en la auditoría.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from app.config import (ANYO_MINIMO, CAMPOS_OBLIGATORIOS, CAT_BASURA, CAT_DESBORDE,
                        CAT_FECHA, CAT_VACIO, CATEGORIA_POR_DEFECTO, MAPA_SEVERIDAD,
                        MARCAS_REALES, MAX_LONGITUD_CORTO, PALABRAS_BASURA, RE_AMARICO,
                        RE_ANYO, RE_BASURA, RE_BINARIO, RE_BYTE, RE_CAMPO_CORTO,
                        RE_CAMPO_DESCRIPCION, RE_CAMPO_EQUIPO, RE_CAMPO_FECHA,
                        RE_CAMPO_MARCA, RE_CAMPO_MODELO, RE_CAMPO_NO_EQUIPO,
                        RE_CAMPO_NO_MARCA, RE_CAMPO_OPCIONAL, RE_CAMPO_SEVERIDAD,
                        RE_CAMPO_TIPO, RE_FECHA, RE_SEV_ALTA_ARRANQUE, RE_SEV_LEVE,
                        REGLAS_SEVERIDAD, SEVERIDAD_POR_DEFECTO, TIPOS_DISPOSITIVO)
from app.models import Anomalia, Incidencia, Paso
from app.utils import canonico_con_pista, decodificar_binario, normalizar, truncar, valor_real

Regla = Callable[[Incidencia, str, str], "Anomalia | None"]


# ══════════════════════════════════════════════════════════════════════════
# Detección de anomalías
# ══════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """Aplica todas las reglas y rellena `incidencia.anomalias`.

    Cada regla recibe (incidencia, nombre_campo, valor) y devuelve None si el
    campo está bien, o una Anomalia con la causa precisa y el motivo detallado.
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
        inc.traza = []
        avisos: list[Paso] = []

        # ── Incompletitud ──────────────────────────────────────────────────
        if inc.sin_id:
            inc.anomalias.append(Anomalia(
                CAT_VACIO, "Incidencia sin atributo id", "id",
                motivo="La etiqueta <incidencia> no tiene atributo id: no se puede identificar "
                       "ni deduplicar el registro."))
        if not inc.campos and not inc.vacios:
            inc.anomalias.append(Anomalia(
                CAT_VACIO, "Incidencia sin ningún campo",
                motivo="La <incidencia> no contiene ningún <camp>."))
        for nombre in inc.vacios:
            if RE_CAMPO_OPCIONAL.search(nombre) and not RE_CAMPO_NO_MARCA.search(nombre):
                avisos.append(Paso("Validación",
                                   f"El campo «{nombre}» está vacío, pero es opcional "
                                   "(marca/modelo): no bloquea.", "aviso"))
                continue                     # Marca/modelo vacíos: no es motivo de rechazo
            inc.anomalias.append(Anomalia(
                CAT_VACIO, "Campo obligatorio vacío / etiqueta de autocierre",
                nombre, f'<camp nom="{nombre}"/>',
                motivo=f"El campo «{nombre}» llega vacío y es obligatorio "
                       "(solo marca y modelo pueden faltar)."))

        presentes = {normalizar(n) for n in (*inc.campos, *inc.vacios)}
        for clave, original in self.obligatorios.items():
            if clave not in presentes:
                inc.anomalias.append(Anomalia(
                    CAT_VACIO, "Campo obligatorio ausente", original, "(no existe)",
                    motivo=f"Falta el campo obligatorio «{original}»."))

        # ── Contenido, campo a campo ───────────────────────────────────────
        for nombre, valor in inc.campos.items():
            for regla in self.reglas:
                anomalia = regla(inc, nombre, valor)
                if anomalia:
                    inc.anomalias.append(anomalia)

        self._trazar(inc, avisos)
        return inc

    def _trazar(self, inc: Incidencia, avisos: list[Paso]) -> None:
        """Resume la validación en pasos legibles (auditoría)."""
        if inc.anomalias:
            n = len(inc.anomalias)
            inc.traza.append(Paso(
                "Validación", f"BLOQUEADA: incumple {n} regla{'s' if n > 1 else ''} de calidad.",
                "bloqueo"))
            for a in inc.anomalias:
                donde = f" en «{a.campo}»" if a.campo not in ("", "—") else ""
                inc.traza.append(Paso("Validación", f"{a.tipo}{donde}: {a.motivo_detallado}",
                                      "bloqueo"))
        else:
            inc.traza.append(Paso(
                "Validación",
                f"VÁLIDA: campos obligatorios completos, fecha real entre {self.anyo_minimo} y "
                f"hoy, sin spam (binario, amárico, palabras prohibidas) y ningún campo breve "
                f"de más de {MAX_LONGITUD_CORTO} caracteres.", "ok"))
            if inc.fecha:
                inc.traza.append(Paso("Validación",
                                      f"Fecha de la incidencia reconocida: {inc.fecha:%d/%m/%Y}.",
                                      "ok"))
        inc.traza.extend(avisos)

    # ── Reglas ─────────────────────────────────────────────────────────────

    @staticmethod
    def _donde(nombre: str) -> str:
        """Añade 'en campo de código' si la basura está en un campo breve."""
        return f" en campo de código «{nombre}»" if RE_CAMPO_CORTO.search(nombre) else ""

    def _anyo_incorrecto(self, anyo: int) -> tuple[str, str] | None:
        """(regla, motivo detallado) si el año no es posible."""
        if anyo < self.anyo_minimo:
            return (f"Fecha imposible: {anyo:04d}",
                    f"Año {anyo:04d} fuera de rango válido ({self.anyo_minimo}–{self.hoy.year}).")
        if anyo > self.hoy.year:
            return (f"Fecha futura: {anyo}",
                    f"Año {anyo} posterior al actual ({self.hoy.year}).")
        return None

    def _regla_fecha(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        """Solo se aplica a campos cuyo nombre indica una fecha."""
        if not RE_CAMPO_FECHA.search(nombre):
            return None

        def mal(regla: str, motivo: str) -> Anomalia:
            return Anomalia(CAT_FECHA, regla, nombre, valor, motivo=motivo)

        partes = RE_FECHA.search(valor)
        if partes:
            a, b, c = partes.groups()
            anyo, mes, dia = (a, b, c) if len(a) == 4 else (c, b, a)   # AAAA-MM-DD o DD/MM/AAAA
            if len(anyo) != 4:
                return mal("Fecha con formato no reconocido",
                           f"«{valor.strip()}» no tiene un año de 4 cifras "
                           "(se espera DD/MM/AAAA o AAAA-MM-DD).")
            if incorrecto := self._anyo_incorrecto(int(anyo)):
                return mal(*incorrecto)
            try:
                fecha = date(int(anyo), int(mes), int(dia))
            except ValueError:
                return mal(f"Fecha imposible: {valor.strip()} (día o mes inexistente)",
                           f"El día {int(dia)} del mes {int(mes)} no existe en el calendario.")
            if fecha > self.hoy:
                return mal(f"Fecha futura: {fecha:%d/%m/%Y}",
                           f"{fecha:%d/%m/%Y} es posterior a hoy ({self.hoy:%d/%m/%Y}).")
            inc.fecha = fecha
            return None

        anyos = RE_ANYO.findall(valor)
        if not anyos:
            return mal("Fecha sin formato reconocible",
                       f"«{truncar(valor, 40)}» no contiene ninguna fecha ni año reconocible.")
        for anyo in anyos:
            if incorrecto := self._anyo_incorrecto(int(anyo)):
                return mal(*incorrecto)
        return None

    def _regla_binario(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if not RE_BINARIO.search(valor):
            return None
        decodificado = decodificar_binario(valor)
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: secuencia de código binario",
                        nombre, valor,
                        f"Decodificado: «{decodificado}»" if decodificado else "",
                        motivo=f"Contiene {len(RE_BYTE.findall(valor))} bytes en binario "
                               "(grupos de 8 ceros/unos) en lugar de texto humano.")

    def _regla_amarico(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if not (letra := RE_AMARICO.search(valor)):
            return None
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: texto en amárico",
                        nombre, valor,
                        motivo=f"Contiene escritura etíope (amárico, p. ej. «{letra.group(0)}»), "
                               "ajena al idioma del formulario.")

    def _regla_palabras(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        encontradas = sorted(set(RE_BASURA.findall(normalizar(valor))))
        if not encontradas:
            return None
        tipos = sorted({PALABRAS_BASURA[p] for p in encontradas})
        detalle = ", ".join(f'"{p}" ({PALABRAS_BASURA[p]})' for p in encontradas)
        return Anomalia(CAT_BASURA,
                        f"Contenido basura{self._donde(nombre)}: {', '.join(tipos)}",
                        nombre, valor, "Palabras: " + ", ".join(encontradas),
                        motivo=f"Contiene la expresión prohibida {detalle}.")

    def _regla_desbordamiento(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        if RE_CAMPO_CORTO.search(nombre) and len(valor) > MAX_LONGITUD_CORTO:
            return Anomalia(CAT_DESBORDE,
                            f"Desbordamiento de texto: >{MAX_LONGITUD_CORTO} caracteres "
                            f"({len(valor)}) en un campo breve",
                            nombre, valor,
                            motivo=f"Campo breve (código/identificador) con {len(valor)} "
                                   f"caracteres; el máximo admitido es {MAX_LONGITUD_CORTO}.")
        return None


# ══════════════════════════════════════════════════════════════════════════
# Clasificación: equipo, categoría, marca y severidad
# ══════════════════════════════════════════════════════════════════════════

class Clasificador:
    """Deduce equipo, descripción, categoría, marca y severidad de cada incidencia."""

    def enriquecer(self, inc: Incidencia) -> Incidencia:
        equipo = inc.buscar_campo(RE_CAMPO_EQUIPO, excluir=RE_CAMPO_NO_EQUIPO)
        inc.equipo = equipo[1].strip() if equipo else ""
        inc.campo_equipo = equipo[0] if equipo else ""

        descripcion = inc.buscar_campo(RE_CAMPO_DESCRIPCION)
        if descripcion:
            inc.descripcion = descripcion[1]
        elif inc.campos:   # Sin campo claro: el texto más largo
            inc.descripcion = max(inc.campos.values(), key=len)

        modelo = inc.buscar_campo(RE_CAMPO_MODELO, excluir=RE_CAMPO_MARCA)
        texto_equipo = normalizar(" ".join(filter(None, [
            inc.equipo, modelo[1] if modelo else ""])))
        texto_desc = normalizar(inc.descripcion)

        inc.tipo, inc.origen_tipo = self.categoria(inc, texto_equipo, texto_desc)
        inc.marca, inc.origen_marca = self.marca(inc, texto_equipo, texto_desc)
        fuentes = {"la descripción": texto_desc, "el equipo": texto_equipo,
                   "la categoría": normalizar(inc.tipo)}
        (inc.severidad, inc.severidad_inferida,
         inc.criterio_severidad, inc.regla_severidad) = self.severidad(inc, fuentes)

        inc.traza.append(Paso("Equipo", f"«{truncar(inc.equipo, 80)}» (campo «{inc.campo_equipo}»)."
                              if inc.equipo else "Ningún campo de equipo tiene valor."))
        inc.traza.append(Paso("Categoría", f"{inc.tipo} ← {inc.origen_tipo}"))
        inc.traza.append(Paso("Marca", f"{truncar(inc.marca, 60) or 'Sin marca'} ← {inc.origen_marca}"))
        inc.traza.append(Paso("Severidad", f"{inc.severidad} ← {inc.criterio_severidad}: "
                                           f"{inc.regla_severidad}"))
        if nota := self._nota_periferico(fuentes, inc.criterio_severidad):
            inc.traza.append(Paso("Severidad", nota, "aviso"))
        if not inc.valida:
            inc.traza.append(Paso("Severidad", "Al estar BLOQUEADA, esta clasificación es solo "
                                               "orientativa: no cuenta en las métricas.", "aviso"))
        return inc

    @staticmethod
    def _deducir(tabla, texto_equipo: str, texto_desc: str) -> tuple[str, str] | None:
        """(nombre, origen) buscando la tabla en el equipo y después en la descripción."""
        for donde, texto in (("del equipo/modelo", texto_equipo), ("de la descripción", texto_desc)):
            if encontrado := canonico_con_pista(texto, tabla):
                nombre, pista = encontrado
                return nombre, f'Deducida {donde}: patrón "{pista}"'
        return None

    @classmethod
    def categoria(cls, inc: Incidencia, texto_equipo: str, texto_desc: str) -> tuple[str, str]:
        """(categoría, origen).
        1) Valor real del campo de categoría (unificado si se reconoce).
        2) Si no hay campo o viene vacío / "-": se deduce del equipo y,
           si el equipo no aclara nada, de la descripción."""
        campo = inc.buscar_campo(RE_CAMPO_TIPO)
        if campo and (real := valor_real(campo[1])):
            if encontrado := canonico_con_pista(normalizar(real), TIPOS_DISPOSITIVO):
                return encontrado[0], f'Campo «{campo[0]}»: "{truncar(real, 60)}" (unificado)'
            return real, f'Campo «{campo[0]}»: "{truncar(real, 60)}" (valor literal)'
        if deducida := cls._deducir(TIPOS_DISPOSITIVO, texto_equipo, texto_desc):
            return deducida
        return (CATEGORIA_POR_DEFECTO,
                "Por defecto: ni el equipo ni la descripción encajan con ninguna categoría")

    @classmethod
    def marca(cls, inc: Incidencia, texto_equipo: str,
              texto_desc: str) -> tuple[str | None, str]:
        """(marca, origen).
        1) Lectura directa del nodo <camp nom="Marca d'equip"> (se unifica si
              es conocida: "hewlett packard" -> "HP"; si no, se respeta tal cual).
              "Marca de temps" queda excluida: es un timestamp, no una marca.
        2) Si falta, está vacío o es "-": REGEX de marcas conocidas sobre el
           equipo/modelo y después sobre la descripción.
        Las marcas basura (Pull & Bear...) no llegan aquí como válidas: el
        AnomalyDetector ya ha rechazado esas incidencias."""
        campo = inc.buscar_campo(RE_CAMPO_MARCA, excluir=RE_CAMPO_NO_MARCA)
        if campo and (real := valor_real(campo[1])):
            if encontrado := canonico_con_pista(normalizar(real), MARCAS_REALES):
                return encontrado[0], f'Campo «{campo[0]}»: "{truncar(real, 60)}"'
            return real, f'Campo «{campo[0]}»: "{truncar(real, 60)}" (marca no catalogada, literal)'
        if deducida := cls._deducir(MARCAS_REALES, texto_equipo, texto_desc):
            return deducida
        return None, "Campo de marca vacío y ninguna marca conocida en el equipo ni la descripción"

    @staticmethod
    def severidad(inc: Incidencia, fuentes: dict[str, str]) -> tuple[str, bool, str, str]:
        """Devuelve (nivel, inferida, criterio, regla exacta).

        Si el XML trae un campo de prioridad se usa su valor; si no, se recorre
        config.REGLAS_SEVERIDAD en orden y gana la primera que encaja."""
        campo = inc.buscar_campo(RE_CAMPO_SEVERIDAD)
        if campo:
            valor = normalizar(campo[1])
            for nivel, patron in MAPA_SEVERIDAD:
                if coincidencia := patron.search(valor):
                    return (nivel, False, f"Campo de prioridad «{campo[0]}»",
                            f'Valor "{truncar(campo[1], 60)}" (patrón "{coincidencia.group(0)}")')

        texto = " ".join(fuentes.values())
        for regla in REGLAS_SEVERIDAD:
            if coincidencia := regla.patron.search(texto):
                return (regla.nivel, True, f"Paso {regla.paso} · {regla.titulo}",
                        Clasificador._pista(regla.patron, fuentes, coincidencia.group(0)))
        return (SEVERIDAD_POR_DEFECTO, True, f"Paso {len(REGLAS_SEVERIDAD) + 1} · Sin pistas",
                "Por defecto: fallo genérico (ninguna palabra clave reconocida)")

    @staticmethod
    def _pista(patron, fuentes: dict[str, str], respaldo: str) -> str:
        """'Palabra clave: "no arrenca" (en la descripción)'."""
        for donde, texto in fuentes.items():
            if coincidencia := patron.search(texto):
                return f'Palabra clave: "{coincidencia.group(0)}" (en {donde})'
        return f'Palabra clave: "{respaldo}"'

    @staticmethod
    def _nota_periferico(fuentes: dict[str, str], criterio: str) -> str | None:
        """Explica el caso que más confunde: 'no arranca' en un periférico."""
        texto = " ".join(fuentes.values())
        if criterio.startswith("Paso 3") and (arranque := RE_SEV_ALTA_ARRANQUE.search(texto)):
            periferico = RE_SEV_LEVE.search(texto)
            return (f'También menciona "{arranque.group(0)}", pero al tratarse de un periférico '
                    f'("{periferico.group(0) if periferico else "?"}") prevalece Leve.')
        return None


def procesar(incidencias: Iterable[Incidencia], hoy: date | None = None) -> list[Incidencia]:
    """Valida y después clasifica cada incidencia (la validación fija la fecha)."""
    detector, clasificador = AnomalyDetector(hoy=hoy), Clasificador()
    resultado = []
    for inc in incidencias:
        detector.validar(inc)
        clasificador.enriquecer(inc)
        resultado.append(inc)
    return resultado
