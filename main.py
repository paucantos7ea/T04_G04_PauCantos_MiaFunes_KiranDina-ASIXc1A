
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
import unicodedata
import os

# ==========================================
# CONFIGURACIÓN
# ==========================================

ARCHIVO_XML = "incidencies.xml"


# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

def normalizar(texto):
    """Pasa el texto a minúsculas y elimina acentos."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )


def buscar_campo(incidencia, nombres):
    """Busca un campo aunque tenga un nombre parecido."""
    for campo, valor in incidencia.items():
        if normalizar(campo) in nombres:
            return valor.strip()
    return ""


# ==========================================
# 1. LEER EL ARCHIVO XML
# ==========================================

def leer_xml():
    if not os.path.exists(ARCHIVO_XML):
        print("ERROR: No se encuentra incidencies.xml")
        return []

    try:
        arbol = ET.parse(ARCHIVO_XML)
        raiz = arbol.getroot()

        incidencias = []

        for elemento in raiz.iter():
            campos = {}

            for hijo in elemento:
                # Solo recogemos campos de texto directos
                if len(hijo) == 0 and hijo.text:
                    etiqueta = hijo.tag.split("}")[-1]
                    campos[etiqueta] = hijo.text.strip()

            if len(campos) >= 2:
                incidencias.append(campos)

        return incidencias

    except ET.ParseError as error:
        print("ERROR al leer el XML:", error)
        return []


# ==========================================
# 2. VALIDAR Y FILTRAR INCIDENCIAS
# ==========================================

def validar_incidencias(incidencias):
    validas = []
    descartadas = []
    ids = set()

    campos_id = {"id", "identificador", "idincidencia",
                 "codigo", "codigoincidencia"}

    campos_fecha = {"fecha", "fechacreacion",
                    "fechaincidencia", "fechaalta"}

    for incidencia in incidencias:

        identificador = buscar_campo(incidencia, campos_id)
        fecha = buscar_campo(incidencia, campos_fecha)

        # Comprobar que tenga identificador
        if not identificador:
            descartadas.append((incidencia, "Falta el ID"))
            continue

        # Comprobar duplicados
        if identificador in ids:
            descartadas.append((incidencia, "ID duplicado"))
            continue

        # Comprobar fecha, si existe ese campo
        if fecha:
            fecha_valida = False

            formatos = [
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%Y/%m/%d"
            ]

            for formato in formatos:
                try:
                    fecha_obj = datetime.strptime(fecha, formato)

                    if 2000 <= fecha_obj.year <= datetime.now().year:
                        fecha_valida = True
                        break
                except ValueError:
                    pass

            if not fecha_valida:
                descartadas.append(
                    (incidencia, "Fecha incorrecta")
                )
                continue

        ids.add(identificador)
        validas.append(incidencia)

    return validas, descartadas


# ==========================================
# 3. CALCULAR ESTADÍSTICAS
# ==========================================

def obtener_estadisticas(incidencias):

    estados = Counter()
    dispositivos = Counter()
    prioridades = Counter()
    departamentos = Counter()

    for incidencia in incidencias:

        estado = buscar_campo(
            incidencia,
            {"estado", "situacion"}
        )

        dispositivo = buscar_campo(
            incidencia,
            {"dispositivo", "equipo", "tipoequipo",
             "tipodispositivo"}
        )

        prioridad = buscar_campo(
            incidencia,
            {"prioridad", "urgencia"}
        )

        departamento = buscar_campo(
            incidencia,
            {"departamento", "seccion", "area"}
        )

        if estado:
            estados[estado] += 1

        if dispositivo:
            dispositivos[dispositivo] += 1

        if prioridad:
            prioridades[prioridad] += 1

        if departamento:
            departamentos[departamento] += 1

    return estados, dispositivos, prioridades, departamentos


# ==========================================
# 4. MOSTRAR RESULTADOS
# ==========================================

def mostrar_estadisticas(titulo, estadisticas):

    print("\n" + titulo)
    print("-" * 40)

    if not estadisticas:
        print("No hay datos disponibles.")
        return

    for nombre, cantidad in estadisticas.most_common():
        print(f"{nombre:<25} {cantidad:>5}")


def mostrar_informe(validas, descartadas):

    print("\n")
    print("=" * 50)
    print("          INFORME DE INCIDENCIAS")
    print("=" * 50)

    print(f"\nTotal de incidencias leídas: {len(validas) + len(descartadas)}")
    print(f"Incidencias válidas:         {len(validas)}")
    print(f"Incidencias descartadas:     {len(descartadas)}")

    estados, dispositivos, prioridades, departamentos = (
        obtener_estadisticas(validas)
    )

    mostrar_estadisticas("ESTADÍSTICAS POR ESTADO", estados)

    mostrar_estadisticas("ESTADÍSTICAS POR DISPOSITIVO", dispositivos)

    mostrar_estadisticas("ESTADÍSTICAS POR PRIORIDAD", prioridades)

    mostrar_estadisticas("ESTADÍSTICAS POR DEPARTAMENTO", departamentos)

    if dispositivos:
        print("\nDISPOSITIVO CON MÁS INCIDENCIAS")
        print("-" * 40)
        print(dispositivos.most_common(1)[0][0])

    print("\n" + "=" * 50)
    print("             FIN DEL INFORME")
    print("=" * 50)


# ==========================================
# PROGRAMA PRINCIPAL
# ==========================================

def main():

    print("Leyendo archivo XML...")

    incidencias = leer_xml()

    if not incidencias:
        print("No se han encontrado incidencias.")
        return

    validas, descartadas = validar_incidencias(incidencias)

    mostrar_informe(validas, descartadas)

    if descartadas:
        print("\nINCIDENCIAS DESCARTADAS:")
        for incidencia, motivo in descartadas:
            print(f"- {motivo}")


if __name__ == "__main__":
    main()
