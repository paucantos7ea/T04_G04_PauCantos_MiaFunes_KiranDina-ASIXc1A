"""Convierte un CSV con cabeceras a XML. Solo necesita Python 3.9 o superior."""
import csv
import io
from itertools import islice
from pathlib import Path
import xml.etree.ElementTree as ET


def detectar_separador(texto):
    # Se leen registros completos: una descripcion puede contener saltos de linea.
    candidatos = []
    for separador in (",", ";", "\t", "|"):
        filas = [f for f in islice(csv.reader(io.StringIO(texto, newline=""), delimiter=separador), 200) if any(f)]
        if not filas:
            continue
        columnas = len(filas[0])
        muestra = filas[1:] or filas
        regulares = sum(len(f) == columnas for f in muestra) / len(muestra)
        candidatos.append(((columnas > 1, regulares, columnas), separador))
    return max(candidatos, key=lambda c: c[0])[1] if candidatos else ","


def convertir(ruta_csv):
    ruta_csv = Path(ruta_csv).expanduser().resolve()
    with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
        texto = archivo.read()
    # Algunas exportaciones de Excel indican el separador en la primera linea.
    primera = texto.splitlines()[0] if texto else ""
    if primera.lower().startswith("sep=") and len(primera) == 5:
        separador = primera[-1]
        texto = texto.split("\n", 1)[1] if "\n" in texto else ""
    else:
        separador = detectar_separador(texto)
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
    cabeceras = next((f for f in lector if any(f)), None)
    if not cabeceras:
        raise ValueError("El CSV esta vacio o no tiene cabeceras.")
    raiz = ET.Element("incidencies")
    cantidad = irregulares = 0
    for fila in lector:
        if not fila:
            continue
        cantidad += 1
        irregular = len(fila) != len(cabeceras)
        irregulares += irregular
        incidencia = ET.SubElement(raiz, "incidencia", id=str(cantidad))
        if irregular:
            incidencia.set("columnes_originals", str(len(fila)))
        # Nunca se recortan valores: los sobrantes se conservan como campos extra.
        for i in range(max(len(cabeceras), len(fila))):
            titulo = cabeceras[i] if i < len(cabeceras) else f"columna_extra_{i - len(cabeceras) + 1}"
            campo = ET.SubElement(incidencia, "camp", nom=titulo)
            if i < len(fila):
                campo.text = fila[i]
            else:
                campo.set("absent", "true")
            if i >= len(cabeceras):
                campo.set("extra", "true")
    salida = ruta_csv.with_suffix(".xml")
    numero = 1
    while salida.exists():
        salida = ruta_csv.with_name(f"{ruta_csv.stem}_{numero}.xml")
        numero += 1
    ET.indent(raiz, space="  ")
    with salida.open("xb") as archivo:
        ET.ElementTree(raiz).write(archivo, encoding="utf-8", xml_declaration=True)
    if irregulares:
        print(f"Avis: {irregulares} registres amb columnes diferents; revisa els camps absents o extra a l'XML.")
    return salida, cantidad


if __name__ == "__main__":
    nombre = input("Ruta del CSV [incidencies.csv]: ").strip().strip("\"'")
    try:
        salida, cantidad = convertir(nombre or "incidencies.csv")
        print(f"Convertides {cantidad} incidencies. XML creat: {salida}")
    except (OSError, ValueError, csv.Error) as error:
        print(f"No s'ha pogut convertir: {error}")
