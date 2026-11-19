# -*- coding: utf-8 -*-
"""Motor de reparación, detección de anomalías, marcas y severidad.

Orden de la tubería (procesar):
    1. Reparador        -> normaliza lo que se puede arreglar sin inventar datos
                           (fechas alternativas, espacios, mayúsculas de marca).
    2. AnomalyDetector  -> decide VÁLIDA / ANÓMALA y por qué (rellena `anomalias`).
    3. Clasificador     -> deduce equipo, descripción, categoría, marca y severidad.

Las palabras clave (severidad, marcas, léxico técnico) y el rango de años se
leen de rules.json a través de app.rules. Todo deja TRAZABILIDAD en la
incidencia: reparaciones, motivo de cada rechazo, regla exacta de severidad
y una traza paso a paso que la web muestra en la auditoría.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date

from app.config import (CAMPOS_OBLIGATORIOS, CAT_BASURA, CAT_DESBORDE, CAT_FECHA,
                        CAT_SIN_SENTIDO, CAT_VACIO, CATEGORIA_POR_DEFECTO, MAPA_SEVERIDAD,
                        MAX_LONGITUD_CORTO, MIN_PALABRAS_FAKER, MIN_PALABRAS_PARRAFO,
                        MIN_PALABRAS_PROSA,
                        NOMBRES_PROPIOS_FAKER, NUMEROS_ROMANOS, PALABRAS_BASURA, RE_AMARICO,
                        RE_ANYO, RE_BASURA, RE_BINARIO, RE_BYTE, RE_CAMPO_AFECTADOS,
                        RE_CAMPO_CORTO, RE_CAMPO_DESCRIPCION, RE_CAMPO_EQUIPO, RE_CAMPO_FECHA,
                        RE_CAMPO_MARCA, RE_CAMPO_MODELO, RE_CAMPO_NO_EQUIPO, RE_CAMPO_NO_MARCA,
                        RE_CAMPO_OPCIONAL, RE_CAMPO_SEVERIDAD, RE_CAMPO_TIPO, RE_FECHA,
                        RE_FECHA_REPARABLE_EU, RE_FECHA_REPARABLE_ISO, RE_FRASES_FAKER,
                        RE_PALABRA, SEVERIDAD_POR_DEFECTO, TIPOS_DISPOSITIVO)
from app.models import Anomalia, Incidencia, Paso, Reparacion
from app.rules import Reglas, cargar_reglas, normalizar_clave
from app.utils import canonico_con_pista, decodificar_binario, normalizar, truncar, valor_real

Regla = Callable[[Incidencia, str, str], "Anomalia | None"]
RE_TOKEN = re.compile(r"[^\W\d_]+")
LETRAS_QUE_SON_PALABRA = {"a", "e", "i", "o", "u", "y"}


def _campo_marca(inc: Incidencia) -> tuple[str, str] | None:
    return inc.buscar_campo(RE_CAMPO_MARCA, excluir=RE_CAMPO_NO_MARCA)


# ══════════════════════════════════════════════════════════════════════════
# 1. Auto-reparación
# ══════════════════════════════════════════════════════════════════════════

class Reparador:
    """Corrige formatos sin inventar datos. Lo que no puede arreglar lo deja
    tal cual para que el AnomalyDetector lo rechace con su motivo."""

    def __init__(self, reglas: Reglas | None = None, hoy: date | None = None):
        self.reglas = reglas or cargar_reglas()
        self.hoy = hoy or date.today()
        self.anyo_minimo = self.reglas.anyo_minimo
        self.anyo_maximo = self.reglas.anyo_maximo(self.hoy)
        self.marcas = {normalizar_clave(n): n for n in self.reglas.nombres_marcas()}

    def reparar(self, inc: Incidencia) -> Incidencia:
        inc.reparaciones = []
        marca = _campo_marca(inc)
        for nombre, valor in list(inc.campos.items()):
            nuevo = " ".join(valor.split())          # Tabuladores, saltos y espacios dobles
            if nuevo != valor:
                inc.reparaciones.append(Reparacion(
                    nombre, valor, nuevo, "Espacios duplicados, tabulaciones o saltos de "
                                          "línea eliminados"))
            if RE_CAMPO_FECHA.search(nombre) and (fecha := self._fecha(nuevo)) and fecha != nuevo:
                inc.reparaciones.append(Reparacion(
                    nombre, nuevo, fecha, "Fecha normalizada al formato DD/MM/AAAA"))
                nuevo = fecha
            if marca and nombre == marca[0]:
                canonica = self.marcas.get(normalizar_clave(nuevo))
                if canonica and canonica != nuevo:
                    inc.reparaciones.append(Reparacion(
                        nombre, nuevo, canonica, "Mayúsculas de marca conocida normalizadas"))
                    nuevo = canonica
            inc.campos[nombre] = nuevo
        return inc

    def _fecha(self, valor: str) -> str | None:
        """DD/MM/AAAA si `valor` es una fecha real y coherente en otro formato."""
        if m := RE_FECHA_REPARABLE_ISO.match(valor):
            anyo, mes, dia = m.groups()
        elif m := RE_FECHA_REPARABLE_EU.match(valor):
            dia, mes, anyo = m.groups()
        else:
            return None
        try:
            fecha = date(int(anyo), int(mes), int(dia))
        except ValueError:
            return None                          # 31/02: que lo rechace el detector
        if not self.anyo_minimo <= fecha.year <= self.anyo_maximo or fecha > self.hoy:
            return None                          # Año incoherente: no se "arregla"
        return f"{fecha:%d/%m/%Y}"


# ══════════════════════════════════════════════════════════════════════════
# 2. Detección de anomalías
# ══════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """Aplica todas las reglas y rellena `incidencia.anomalias`.

    Cada regla recibe (incidencia, nombre_campo, valor) y devuelve None si el
    campo está bien, o una Anomalia con la causa precisa y el motivo detallado.
    """

    def __init__(self, reglas: Reglas | None = None, hoy: date | None = None,
                 anyo_minimo: int | None = None):
        self.reglas = reglas or cargar_reglas()
        self.hoy = hoy or date.today()
        self.anyo_minimo = anyo_minimo or self.reglas.anyo_minimo
        self.anyo_maximo = self.reglas.anyo_maximo(self.hoy)
        self.obligatorios = {normalizar(c): c for c in CAMPOS_OBLIGATORIOS}
        self.reglas_campo: tuple[Regla, ...] = (
            self._regla_fecha,
            self._regla_binario,
            self._regla_amarico,
            self._regla_palabras,
            self._regla_sin_sentido,
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
            for regla in self.reglas_campo:
                anomalia = regla(inc, nombre, valor)
                if anomalia:
                    inc.anomalias.append(anomalia)

        self._trazar(inc, avisos)
        return inc

    def _trazar(self, inc: Incidencia, avisos: list[Paso]) -> None:
        """Resume la reparación y la validación en pasos legibles (auditoría)."""
        for r in inc.reparaciones:
            inc.traza.append(Paso("Auto-reparación", f"«{r.campo}»: «{truncar(r.antes, 60)}» → "
                                                     f"«{truncar(r.despues, 60)}» ({r.motivo}).",
                                  "reparacion"))
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
                f"hoy, descripción con intención técnica, sin spam (binario, amárico, "
                f"palabras prohibidas) y ningún campo breve de más de {MAX_LONGITUD_CORTO} "
                "caracteres.", "ok"))
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
                    f"Año {anyo:04d} fuera de rango válido ({self.anyo_minimo}–{self.anyo_maximo}).")
        if anyo > self.anyo_maximo:
            if self.anyo_maximo < self.hoy.year:
                return (f"Fecha fuera de rango: {anyo}",
                        f"Año {anyo} posterior al máximo permitido ({self.anyo_maximo}).")
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

    def _regla_sin_sentido(self, inc: Incidencia, nombre: str, valor: str) -> Anomalia | None:
        """Coherencia e intención técnica: solo sobre EL campo de descripción."""
        descripcion = inc.buscar_campo(RE_CAMPO_DESCRIPCION)
        if not descripcion or descripcion[0] != nombre:
            return None
        if (veredicto := self.evaluar_coherencia(valor)) is None:
            return None
        regla, motivo, extra = veredicto
        return Anomalia(CAT_SIN_SENTIDO, regla, nombre, valor, extra, motivo=motivo)

    def evaluar_coherencia(self, texto: str) -> tuple[str, str, str] | None:
        """None si el texto describe un problema técnico; si no, (regla, motivo, pistas).

        Fuerza técnica = 2 × síntomas de avería + dispositivos/conceptos.
          * Fuerza ≥ 2 -> se acepta ("No funciona", "Teclat trencat", "No encèn").
            Un párrafo largo (≥ 25 palabras) necesita fuerza ≥ 3: una palabra de
            pasada en un párrafo sobre otra cosa no demuestra una avería.
          * Micro-frases planas tipo Faker con fuerza insuficiente -> texto aleatorio.
          * Prosa larga con fuerza insuficiente -> sin relación con soporte.
          * Sin ninguna palabra ("69", "...") -> sin contenido.
        """
        norm = normalizar(texto.replace("’", "'"))
        sintomas = sorted({m.group(0) for m in self.reglas.patron("sintomas").finditer(norm)})
        dispositivos = sorted({m.group(0)
                               for m in self.reglas.patron("dispositivos").finditer(norm)})
        fuerza = 2 * len(sintomas) + len(dispositivos)
        palabras = RE_PALABRA.findall(texto)

        if not palabras:
            return ("Descripción sin palabras",
                    f"«{truncar(texto, 40)}» no contiene ninguna palabra: no describe ninguna "
                    "avería.", "")
        tokens = [normalizar(t) for t in RE_TOKEN.findall(texto)]
        largo = len(tokens) >= MIN_PALABRAS_PARRAFO
        if fuerza >= (3 if largo else 2):   # Un párrafo largo necesita más evidencia
            return None

        tecnico = (f"solo aparece «{dispositivos[0]}», sin ningún síntoma de avería"
                   if dispositivos else "ninguna palabra técnica ni síntoma de avería")
        if RE_FRASES_FAKER.match(texto.strip()):
            sueltas = sorted({t for t in tokens if t in NUMEROS_ROMANOS
                              or (len(t) == 1 and t not in LETRAS_QUE_SON_PALABRA)})
            nombres = sorted({t for t in tokens if t in NOMBRES_PROPIOS_FAKER})
            senales = []
            if nombres:
                senales.append("nombres propios/lugares al azar: " + ", ".join(nombres))
            if sueltas:
                senales.append("letras o números romanos sueltos: " + ", ".join(sueltas))
            if len(tokens) < MIN_PALABRAS_FAKER and not senales:
                return None                     # "Ajuda." / "Urgent.": demasiado corto para juzgar
            frases = max(1, texto.count("."))
            motivo = (f"{tecnico[0].upper()}{tecnico[1:]}; {frases} micro-frase"
                      f"{'s' if frases > 1 else ''} de palabras inconexas sin conectores ni "
                      "puntuación interna (patrón de generador aleatorio tipo Faker)"
                      + (f"; {'; '.join(senales)}" if senales else "") + ".")
            return ("Texto aleatorio / sin sentido (tipo Faker)", motivo,
                    "Señales: " + "; ".join(senales) if senales else "")
        if largo or (fuerza == 0 and len(tokens) >= MIN_PALABRAS_PROSA):
            pistas = sintomas + dispositivos
            detalle = (f"solo {len(pistas)} término técnico de pasada ({', '.join(pistas)})"
                       if pistas else tecnico)
            return ("Texto sin relación con soporte técnico",
                    f"{len(tokens)} palabras y {detalle}: no describe una incidencia "
                    "informática.", "")
        return None

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
# 3. Clasificación: equipo, categoría, marca y severidad
# ══════════════════════════════════════════════════════════════════════════

class Clasificador:
    """Deduce equipo, descripción, categoría, marca y severidad de cada incidencia."""

    def __init__(self, reglas: Reglas | None = None):
        self.reglas = reglas or cargar_reglas()

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
            inc.equipo, modelo[1] if modelo else ""])).replace("’", "'"))
        texto_desc = normalizar(inc.descripcion.replace("’", "'"))

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
        for nota in self._notas(fuentes, inc):
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

    def marca(self, inc: Incidencia, texto_equipo: str,
              texto_desc: str) -> tuple[str | None, str]:
        """(marca, origen).
        1) Lectura directa del nodo <camp nom="Marca d'equip"> (se unifica si
              es conocida: "hewlett packard" -> "HP"; si no, se respeta tal cual).
              "Marca de temps" queda excluida: es un timestamp, no una marca.
        2) Si falta, está vacío o es "-": marcas de rules.json sobre el
           equipo/modelo y después sobre la descripción."""
        campo = _campo_marca(inc)
        if campo and (real := valor_real(campo[1])):
            if encontrado := canonico_con_pista(normalizar(real), self.reglas.marcas):
                return encontrado[0], f'Campo «{campo[0]}»: "{truncar(real, 60)}"'
            return real, f'Campo «{campo[0]}»: "{truncar(real, 60)}" (marca no catalogada, literal)'
        if deducida := self._deducir(self.reglas.marcas, texto_equipo, texto_desc):
            return deducida
        return None, "Campo de marca vacío y ninguna marca conocida en el equipo ni la descripción"

    def _afectados_multiples(self, inc: Incidencia) -> str | None:
        campo = inc.buscar_campo(RE_CAMPO_AFECTADOS)
        if campo and self.reglas.patron("afectados_multiples").search(
                normalizar(campo[1].replace("’", "'"))):
            return campo[1]
        return None

    def severidad(self, inc: Incidencia, fuentes: dict[str, str]) -> tuple[str, bool, str, str]:
        """Devuelve (nivel, inferida, criterio, regla exacta).

        Paso 0: campo de prioridad explícito del XML.
        Paso 1: CRÍTICA solo con contexto de caída EN LA DESCRIPCIÓN.
        Pasos 2-6: ver config.PASOS_SEVERIDAD. Paso 7: por defecto."""
        campo = inc.buscar_campo(RE_CAMPO_SEVERIDAD)
        if campo:
            valor = normalizar(campo[1])
            for nivel, patron in MAPA_SEVERIDAD:
                if coincidencia := patron.search(valor):
                    return (nivel, False, f"Campo de prioridad «{campo[0]}»",
                            f'Valor "{truncar(campo[1], 60)}" (patrón "{coincidencia.group(0)}")')

        r = self.reglas
        desc, equipo = fuentes["la descripción"], fuentes["el equipo"]
        texto = " ".join(fuentes.values())
        infra = self._buscar(r.patron("critica_infraestructura"), {"la descripción": desc,
                                                                  "el equipo": equipo})
        multi_desc = r.patron("critica_multiusuario").search(desc)

        # ── Paso 1 · Crítica ───────────────────────────────────────────────
        if general := r.patron("critica_caida_general").search(desc):
            return ("Crítica", True, "Paso 1 · Caída de infraestructura o corte general",
                    f'Caída general descrita: "{general.group(0)}" (en la descripción)')
        if caida := r.patron("critica_caida").search(desc):
            if infra:
                return ("Crítica", True, "Paso 1 · Caída de infraestructura o corte general",
                        f'Síntoma "{caida.group(0)}" (en la descripción) + infraestructura '
                        f'"{infra[0]}" (en {infra[1]})')
            if multi_desc:
                return ("Crítica", True, "Paso 1 · Caída de infraestructura o corte general",
                        f'Síntoma "{caida.group(0)}" + impacto multiusuario '
                        f'"{multi_desc.group(0)}" (en la descripción)')

        # ── Pasos 2-6 ──────────────────────────────────────────────────────
        if m := r.patron("alta_hardware").search(texto):
            return ("Alta", True, "Paso 2 · Hardware crítico del equipo",
                    self._pista(r.patron("alta_hardware"), fuentes, m.group(0)))
        if infra and (multi_desc or (afectados := self._afectados_multiples(inc))):
            impacto = (f'"{multi_desc.group(0)}" (en la descripción)' if multi_desc
                       else f'campo de afectados = "{afectados}"')
            return ("Alta", True, "Paso 3 · Infraestructura con impacto multiusuario",
                    f'Infraestructura "{infra[0]}" (en {infra[1]}) + {impacto}, '
                    "sin caída descrita")
        for paso, nivel, titulo, lista in ((4, "Leve", "Periféricos y consumibles",
                                            "leve_perifericos"),
                                           (5, "Alta", "El equipo no arranca", "alta_arranque"),
                                           (6, "Media", "Software o error genérico",
                                            "media_generico")):
            if m := r.patron(lista).search(texto):
                return (nivel, True, f"Paso {paso} · {titulo}",
                        self._pista(r.patron(lista), fuentes, m.group(0)))
        return (SEVERIDAD_POR_DEFECTO, True, "Paso 7 · Sin pistas",
                "Por defecto: fallo genérico (ninguna palabra clave reconocida)")

    @staticmethod
    def _buscar(patron, fuentes: dict[str, str]) -> tuple[str, str] | None:
        """(fragmento, dónde) de la primera fuente en la que encaja el patrón."""
        for donde, texto in fuentes.items():
            if m := patron.search(texto):
                return m.group(0), donde
        return None

    @classmethod
    def _pista(cls, patron, fuentes: dict[str, str], respaldo: str) -> str:
        """'Palabra clave: "no arrenca" (en la descripción)'."""
        if encontrado := cls._buscar(patron, fuentes):
            return f'Palabra clave: "{encontrado[0]}" (en {encontrado[1]})'
        return f'Palabra clave: "{respaldo}"'

    def _notas(self, fuentes: dict[str, str], inc: Incidencia) -> list[str]:
        """Explica los casos que más confunden."""
        notas = []
        texto = " ".join(fuentes.values())
        criterio = inc.criterio_severidad
        if criterio.startswith("Paso 4") and (
                arranque := self.reglas.patron("alta_arranque").search(texto)):
            periferico = self.reglas.patron("leve_perifericos").search(texto)
            notas.append(f'También menciona "{arranque.group(0)}", pero al tratarse de un '
                         f'periférico ("{periferico.group(0) if periferico else "?"}") '
                         "prevalece Leve.")
        infra = self._buscar(self.reglas.patron("critica_infraestructura"),
                             {"la descripción": fuentes["la descripción"],
                              "el equipo": fuentes["el equipo"]})
        if infra and not inc.severidad == "Crítica" and inc.severidad_inferida:
            notas.append(f'Equipo de infraestructura ("{infra[0]}"), pero la descripción no '
                         "describe ninguna caída ni corte general: no se marca Crítica.")
        return notas


def procesar(incidencias: Iterable[Incidencia], hoy: date | None = None,
             reglas: Reglas | None = None) -> list[Incidencia]:
    """Repara, valida y clasifica cada incidencia (en ese orden)."""
    reglas = reglas or cargar_reglas()
    reparador = Reparador(reglas, hoy)
    detector, clasificador = AnomalyDetector(reglas, hoy), Clasificador(reglas)
    resultado = []
    for inc in incidencias:
        reparador.reparar(inc)
        detector.validar(inc)
        clasificador.enriquecer(inc)
        resultado.append(inc)
    return resultado
