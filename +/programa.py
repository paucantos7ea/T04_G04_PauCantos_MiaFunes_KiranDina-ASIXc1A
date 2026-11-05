import datetime
import os
import xml.etree.ElementTree as ET

# Codis de colors ANSI per a la consola
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
WHITE = "\033[37m"


def validar_incidencia(incidencia):
    """Funció per filtrar dades errònies o no útils (ex: dates me futur o camps buits)"""
    id_inc = incidencia.findtext("id")
    data_str = incidencia.findtext("data")
    equip = incidencia.findtext("equip")
    estat = incidencia.findtext("estat")

    # Validar que existeixin els camps bàsics
    if not id_inc or not data_str or not equip or not estat:
        return False, "Camps obligatoris buits"

    # Validar coherència de la data
    try:
        data_obj = datetime.datetime.strptime(data_str, "%Y-%m-%d").date()
        avui = datetime.date.today()

        # Filtratge: No acceptem dates futures (ex: any 2064) ni anteriors a 2010
        if data_obj > avui:
            return False, f"Data futura invàlida ({data_str})"
        if data_obj.year < 2010:
            return False, f"Data antiga invàlida ({data_str})"
    except ValueError:
        return False, f"Format de data incorrecte ({data_str})"

    return True, "Ok"


def analitzar_i_mostrar_dades(fitxer_xml):
    if not os.path.exists(fitxer_xml):
        print(
            f"{RED}{BOLD}Error:{RESET} El fitxer '{fitxer_xml}' no existeix."
        )
        return

    try:
        tree = ET.parse(fitxer_xml)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"{RED}{BOLD}Error en llegir l'XML:{RESET} {e}")
        return

    total_registres = 0
    valids = []
    descartats = 0
    motius_descart: dict[str, int] = {}

    # Lectura i filtratge de dades
    for inc in root.findall("incidencia"):
        total_registres += 1
        es_valid, motiu = validar_incidencia(inc)

        if es_valid:
            valids.append(
                {
                    "id": inc.findtext("id"),
                    "data": inc.findtext("data"),
                    "equip": inc.findtext("equip"),
                    "categoria": inc.findtext("categoria", "Altres"),
                    "prioritat": inc.findtext("prioritat", "Mitjana"),
                    "estat": inc.findtext("estat"),
                    "ubicacio": inc.findtext("ubicacio", "No especificada"),
                }
            )
        else:
            descartats += 1
            motius_descart[motiu] = motius_descart.get(motiu, 0) + 1

    # Càlcul d'estadístiques
    estats_count: dict[str, int] = {}
    categories_count: dict[str, int] = {}
    prioritats_count: dict[str, int] = {}

    for item in valids:
        estats_count[item["estat"]] = estats_count.get(item["estat"], 0) + 1
        categories_count[item["categoria"]] = (
            categories_count.get(item["categoria"], 0) + 1
        )
        prioritats_count[item["prioritat"]] = (
            prioritats_count.get(item["prioritat"], 0) + 1
        )

    # IMPRESSIÓ AMB FORMAT PER CONSOLA
    print("\n" + "=" * 65)
    print(
        f"{CYAN}{BOLD}  ANÀLISI I ESTADÍSTIQUES DE GESTIÓ D'INCIDÈNCIES{RESET}"
    )
    print("=" * 65)

    print(f"\n{BOLD}1. RESUM DE VALIDACIÓ DE DADES:{RESET}")
    print(f"   • Total registres llegits : {WHITE}{total_registres}{RESET}")
    print(
        f"   • Registres vàlids        : {GREEN}{BOLD}{len(valids)}{RESET}"
    )
    print(f"   • Registres descartats    : {RED}{BOLD}{descartats}{RESET}")

    if descartats > 0:
        print(f"     {YELLOW}Motius de descart:{RESET}")
        for motiu, num in motius_descart.items():
            print(f"      - {motiu}: {num}")

    print(f"\n{BOLD}2. DISTRIBUCIÓ PER ESTAT DE LA INCIDÈNCIA:{RESET}")
    for estat, quantitat in estats_count.items():
        pct = (quantitat / len(valids)) * 100 if valids else 0
        barreta = "█" * int(pct // 5)
        print(
            f"   • {estat:<15} : {quantitat:>3} ({pct:>5.1f}%) {BLUE}{barreta}{RESET}"
        )

    print(f"\n{BOLD}3. INCIDÈNCIES PER CATEGORIA D'EQUIP:{RESET}")
    for cat, quantitat in categories_count.items():
        pct = (quantitat / len(valids)) * 100 if valids else 0
        print(f"   • {cat:<15} : {quantitat:>3} ({pct:>5.1f}%)")

    print(f"\n{BOLD}4. NIVELL DE PRIORITAT:{RESET}")
    for prio, quantitat in prioritats_count.items():
        color_prio = (
            RED
            if prio.lower() in ["alta", "crítica"]
            else (YELLOW if prio.lower() == "mitjana" else GREEN)
        )
        print(
            f"   • {color_prio}{prio:<15}{RESET} : {quantitat:>3} d'incidències"
        )

    print("\n" + "=" * 65 + "\n")


if __name__ == "__main__":
    # Nom del fitxer obtingut a l'apartat 2
    FITXER_XML = "incidencies.xml"
    analitzar_i_mostrar_dades(FITXER_XML)