import sys
import re
import json
import random
import time
import requests
from datetime import datetime
from faker import Faker


# Inicialització del generador de dades
fake = Faker('es_ES')


def generar_resposta_automatica(titol_pregunta):
    """Genera respostes coherents segons el text del títol."""
    titol_lower = titol_pregunta.lower()


    if any(k in titol_lower for k in ['descripció', 'descripcion', 'problema']):
        return fake.paragraph(nb_sentences=2)
    elif any(k in titol_lower for k in ['codi', 'identificació', 'id', 'serie']):
        return f"EQ-{random.randint(1000, 9999)}"
    elif any(k in titol_lower for k in ['horari', 'revisar']):
        return random.choice(['De 8:00 a 14:00', 'De 15:00 a 18:00', 'A qualsevol hora', 'A partir de les 12:00'])
    elif any(k in titol_lower for k in ['data', 'fecha']):
        return datetime.now().strftime("%Y-%m-%d")
    else:
        return fake.sentence(nb_words=4)




def processar_i_enviar(url_formulario, num_respuestas):
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }


    # 1. Resoldre URL i extreure estructura
    res_init = session.get(url_formulario, headers=headers, allow_redirects=True)
    url_real = res_init.url
    print(f"\n[HTTP] Obtenint estructura des de: {url_real}\n")


    if res_init.status_code != 200:
        print(f"Error en carregar el formulari. Codi HTTP: {res_init.status_code}")
        return


    html_content = res_init.text
    match_data = re.search(r'FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);</script>', html_content, re.DOTALL)
    match_fbzx = re.search(r'name="fbzx"\s+value="([^"]+)"', html_content)


    if not match_data:
        print("Error: No s'ha pogut extreure la informació de les preguntes.")
        return


    fbzx_token = match_fbzx.group(1) if match_fbzx else ""
    data = json.loads(match_data.group(1))
    preguntas = data[1][1]


    entries = []
    print(f"S'han detectat {len(preguntas)} preguntes en total:")


    for p in preguntas:
        if p and len(p) > 4 and p[4]:
            entry_id = p[4][0][0]
            titol = p[1]
            opciones = p[4][0][1] if len(p[4][0]) > 1 and p[4][0][1] else []
            is_date = (p[3] == 9)


            entries.append({
                'id': entry_id,
                'titol': titol,
                'opciones': [op[0] for op in opciones] if opciones else [],
                'is_date': is_date
            })
            print(f"  - [entry.{entry_id}] {titol} (Opcions: {len(opciones)})")


    form_response_url = re.sub(r'/viewform.*', '/formResponse', url_real)


    print(f"\nIniciant enviament automàtic de {num_respuestas} respostes...\n")


    correctas = 0
    errores = 0


    for i in range(1, num_respuestas + 1):
        payload = {}


        if fbzx_token:
            payload['fbzx'] = fbzx_token
            payload['pageHistory'] = '0,1,2'


        for entry in entries:
            entry_key = f"entry.{entry['id']}"


            if entry['is_date']:
                payload[f"{entry_key}_year"] = str(random.randint(2024, 2026))
                payload[f"{entry_key}_month"] = f"{random.randint(1, 12):02d}"
                payload[f"{entry_key}_day"] = f"{random.randint(1, 28):02d}"
            elif entry['opciones']:
                payload[entry_key] = random.choice(entry['opciones'])
            else:
                payload[entry_key] = generar_resposta_automatica(entry['titol'])


        try:
            res_post = session.post(form_response_url, data=payload, headers=headers)


            # Codi 200 confirma que Google ha rebut i processat la resposta
            if res_post.status_code == 200:
                print(f"[{i}/{num_respuestas}] Enviada amb èxit.")
                correctas += 1
            else:
                print(f"[{i}/{num_respuestas}] Error d'enviament (Codi: {res_post.status_code}).")
                errores += 1
        except Exception as e:
            print(f"[{i}/{num_respuestas}] Error de connexió: {e}")
            errores += 1


        # Pausa breu (0.05s) per poder fer milers d'enviaments ràpidament sense bloquejar el sistema
        time.sleep(0.05)


    print("\n==================================================")
    print(f"PROCÉS FINALITZAT: {correctas} correctes, {errores} errors.")
    print("==================================================")




if __name__ == '__main__':
    url_input = input("Introdueix la URL del formulari: ") or "https://forms.gle/xN5qiFX6QqndkBFw7"
    num_input = input("Quantes respostes vols enviar? [Exemple: 4000]: ")


    num_resp = int(num_input) if num_input.strip().isdigit() else 4000
    processar_i_enviar(url_input, num_resp)