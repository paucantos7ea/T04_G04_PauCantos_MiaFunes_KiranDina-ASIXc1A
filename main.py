import json
import os




def desar_incidencies_json(noves_incidencies, ruta_fitxer="incidencies.json"):
    """Dematxa i emmagatzema una llista d'incidències en un fitxer JSON


    gestionant l'existència prèvia del fitxer i evitant duplicats per ID.
    """
    # Si el fitxer no existeix, es crea directament amb les noves incidències
    if not os.path.exists(ruta_fitxer):
        print(f"El fitxer '{ruta_fitxer}' no existeix. Creant-lo de nou...")
        dades_a_desar = noves_incidencies


    else:
        # Si existeix, es demana a l'usuari quina acció vol realitzar
        print(f"\nEl fitxer '{ruta_fitxer}' ja existeix.")
        print("1. Sobreescriure'l (esborra el contingut anterior)")
        print("2. Afegir les noves incidències (evitant duplicats per ID)")


        opcio = ""
        while opcio not in ["1", "2"]:
            opcio = input("Tria una opció (1 o 2): ").strip()


        if opcio == "1":
            # Opció 1: Sobreescriure
            dades_a_desar = noves_incidencies
            print("S'ha triat sobreescriure el fitxer.")


        elif opcio == "2":
            # Opció 2: Carregar dades existents i afegir sense duplicats
            try:
                with open(ruta_fitxer, "r", encoding="utf-8") as f:
                    dades_existents = json.load(f)
                    # Si el fitxer no conté una llista vàlida, s'inicialitza buit
                    if not isinstance(dades_existents, list):
                        dades_existents = []
            except (json.JSONDecodeError, FileNotFoundError):
                # Si el fitxer està buit o corrupte, es comença de zero
                dades_existents = []


            # Obtenim el conjunt (set) d'IDs ja existents per a una cerca ràpida O(1)
            ids_existents = {
                incidencia.get("id")
                for incidencia in dades_existents
                if "id" in incidencia
            }


            # Filtrem les noves incidències per afegir només les que no tenen l'ID repetit
            incidencies_afegides = 0
            for inc in noves_incidencies:
                inc_id = inc.get("id")
                if inc_id not in ids_existents:
                    dades_existents.append(inc)
                    ids_existents.add(inc_id)
                    incidencies_afegides += 1


            dades_a_desar = dades_existents
            print(
                f"S'han afegit {incidencies_afegides} noves incidències sense duplicats."
            )


    # Escriptura final de les dades en el fitxer JSON
    try:
        with open(ruta_fitxer, "w", encoding="utf-8") as f:
            json.dump(dades_a_desar, f, ensure_ascii=False, indent=4)
        print(
            f"La informació s'ha emmagatzemat correctament a '{ruta_fitxer}'."
        )
    except Exception as e:
        print(f"Error en desar el fitxer: {e}")




# ==========================================
# Exemple d'ús / Prova de funcionament
# ==========================================
if __name__ == "__main__":
    # Dades de prova (suposant que cada incidència té un camp 'id')
    incidencies_noves_exemple = [
        {
            "id": 101,
            "títol": "Error de connexió",
            "estat": "Oberta",
            "prioritat": "Alta",
        },
        {
            "id": 102,
            "títol": "Falta de memòria a servidor",
            "estat": "Pendent",
            "prioritat": "Mitjana",
        },
        {
            "id": 103,
            "títol": "Falla impressora planta 2",
            "estat": "Oberta",
            "prioritat": "Baixa",
        },
    ]


    desar_incidencies_json(incidencies_noves_exemple)