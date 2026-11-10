"""Envia respostes simulades al formulari de classe. Python 3, sense pip.
Executa: python generar_respuestas.py
Comprova sense enviar: python generar_respuestas.py --comprobar
Cada execucio inicia un lot nou amb la quantitat indicada.
"""
import random
import sys
from datetime import date, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, Request

URL_FORMULARIO = 'https://docs.google.com/forms/d/e/1FAIpQLSe6m4tJ5e8Kp38V5nbX651s2WCypnH4eR8u9I28BCXBz8BzHw/viewform'
URL_ENVIO = 'https://docs.google.com/forms/d/e/1FAIpQLSe6m4tJ5e8Kp38V5nbX651s2WCypnH4eR8u9I28BCXBz8BzHw/formResponse'
CAMPOS = ('Correo', 'Informació relativa sobre la protecció de dades', "Data d'incidència", "En quina zona de l'empresa es troba l'equip?", 'Quin departament ha detectat la incidència', "Quin equip presenta l'incidència?", "Quin codi d'identificació té l'equip?", 'Descripció del problema', "Marca d'equip", 'Amb quina freqüència passa el problema?', 'Quantes persones estan afectades pel problema?', "S’ha provat de reiniciar l’equip? (Si el problema es amb l'ordinador)", 'En quin horari es pot revisar o reparar l’equip?')
TEXTO_AVISO = 'He llegit la informació relativa sobre la protecció de dades'
DEPARTAMENTOS = {'Administració': ('ADM', ('Planta baixa', 'Primera planta', 'Recepció')), 'Recursos Humans': ('RH', ('Primera planta',)), 'Màrqueting': ('MAR', ('Primera planta', 'Segona planta')), 'Informàtica': ('INF', ('Planta baixa', 'Segona planta')), 'Logística': ('LOG', ('Planta baixa',)), 'Direcció': ('DIR', ('Segona planta',)), 'Comptabilitat': ('COM', ('Primera planta',))}
MARCAS = {'PC': ('HP', 'Dell', 'Lenovo', 'Apple', 'Asus'), 'Monitor': ('HP', 'Dell', 'Lenovo', 'Apple', 'Asus'), 'Impressora': ('HP', 'Epson'), 'Ratolí': ('Logitech', 'HP', 'Dell', 'Lenovo'), 'Teclat': ('Logitech', 'HP', 'Dell', 'Lenovo'), 'Cablejat': ('Digitus', 'Ugreen'), 'Router/Switch': ('Cisco', 'TP-Link'), 'Projector': ('Epson',), 'Altaveus': ('Logitech',)}
PREFIJOS = {'PC': 'PC', 'Monitor': 'MON', 'Impressora': 'IMP', 'Ratolí': 'RAT', 'Teclat': 'TEC', 'Cablejat': 'CAB', 'Router/Switch': 'NET', 'Projector': 'PRO', 'Altaveus': 'ALT'}
ALCANCES = {'persona': ('Només jo',), 'departament': ('Entre 2 i 10 persones', 'Més de 10 persones', 'Tot el departament'), 'reunio': ('Entre 2 i 10 persones', 'Més de 10 persones'), 'organitzacio': ('Tota l’organització',)}
ENTRADAS = {'Informació relativa sobre la protecció de dades': '1032525705', "Data d'incidència": '1378032154', "En quina zona de l'empresa es troba l'equip?": '412917247', 'Quin departament ha detectat la incidència': '839647098', "Quin equip presenta l'incidència?": '1933472921', "Quin codi d'identificació té l'equip?": '1729226021', 'Descripció del problema': '1541231339', "Marca d'equip": '1736161462', 'Amb quina freqüència passa el problema?': '623699748', 'Quantes persones estan afectades pel problema?': '252163206', "S’ha provat de reiniciar l’equip? (Si el problema es amb l'ordinador)": '2063370891', 'En quin horari es pot revisar o reparar l’equip?': '1158943398'}
TIPOS_DIRECTOS = ('Cablejat', 'Impressora', 'Monitor', 'PC', "Programari de l'ordinador", 'Ratolí', 'Router/Switch', 'Teclat')
MARCAS_DIRECTAS = ('Apple', 'Asus', 'Dell', 'Epson', 'HP', 'Lenovo', 'Logitech')
HORARIOS = ('Al matí', 'Al migdia', 'A la tarda', 'En qualsevol moment')
(CORREO, AVISO, FECHA, ZONA, DEPARTAMENTO, TIPO, CODIGO, DESCRIPCION, MARCA, FRECUENCIA, AFECTADOS, REINICIO, HORARIO) = CAMPOS

# Casos por equipo: texto e indicador de fallo intermitente.
CASOS = {
    'PC': [
        ("L'ordinador no s'encén en prémer el botó i no es veu cap senyal d'engegada.", False),
        ("L'ordinador s'encén, però el sistema operatiu no arriba a iniciar-se.", False),
        ("L'ordinador queda bloquejat durant l'ús i deixa de respondre.", True),
        ("L'ordinador es reinicia inesperadament mentre s'està utilitzant.", True),
        ('El sistema operatiu tarda molt a iniciar-se i a obrir les aplicacions.', False),
    ],
    'Monitor': [
        ("La pantalla del monitor es manté apagada tot i tenir l'alimentació connectada.", False),
        ("El monitor s'encén, però no mostra imatge amb l'ordinador en funcionament.", False),
        ("La imatge del monitor parpelleja durant l'ús.", True),
        ('Apareixen línies verticals a la pantalla que dificulten la lectura.', False),
    ],
    'Impressora': [
        ("La impressora està encesa, però els documents queden a la cua i no s'imprimeixen.", False),
        ("El paper queda encallat dins de la impressora i la impressió s'atura.", False),
        ('La impressora expulsa els fulls en blanc tot i que el document conté text.', False),
        ('Els documents impresos presenten taques i línies sobre el text.', False),
        ("La impressora no s'encén en prémer el botó d'alimentació.", False),
    ],
    'Ratolí': [
        ('El cursor no es mou quan es desplaça el ratolí.', False),
        ('El botó esquerre del ratolí no registra els clics.', False),
        ('La roda del ratolí no desplaça el contingut de les finestres.', False),
        ("El cursor es mou a salts durant l'ús del ratolí.", True),
    ],
    'Teclat': [
        ("El teclat no registra cap pulsació quan s'intenta escriure.", False),
        ('Algunes tecles no escriuen el caràcter corresponent en prémer-les.', False),
        ("La tecla d'espai queda encallada i dificulta l'escriptura.", False),
        ('Algunes pulsacions es registren dues vegades de manera intermitent.', True),
    ],
    'Cablejat': [
        ('El connector del cable de xarxa té la pestanya trencada i no queda fixat al port.', False),
        ('La coberta del cable de xarxa està oberta i deixa els fils interiors exposats.', False),
        ("El cable de xarxa presenta un tall visible i l'enllaç no s'estableix.", False),
        ("L'enllaç de xarxa es perd quan es mou lleugerament el cable.", True),
    ],
    'Router/Switch': [
        ("L'equip de xarxa no s'encén i els dispositius que en depenen perden la connexió.", False),
        ("Els dispositius connectats a l'equip de xarxa perden la connexió de manera intermitent.", True),
        ("L'equip de xarxa es reinicia inesperadament i interromp la connexió.", True),
        ("Els dispositius connectats a l'equip de xarxa no obtenen una adreça IP.", False),
    ],
    "Programari de l'ordinador": [
        ("L'aplicació de gestió no s'obre i mostra un missatge d'error.", False),
        ('El navegador es tanca inesperadament mentre es consulten pàgines.', True),
        ('El processador de textos queda bloquejat en obrir un document.', True),
        ("L'aplicació de fulls de càlcul no permet desar els canvis i mostra un error.", False),
        ('El lector de PDF es tanca inesperadament en obrir un document.', True),
    ],
    'Projector': [
        ("El projector està encès, però no mostra la imatge de l'ordinador connectat.", False),
        ("La imatge projectada continua desenfocada tot i ajustar l'enfocament.", False),
        ("El projector s'apaga inesperadament durant la projecció.", True),
        ("El projector no s'encén en prémer el botó d'alimentació.", False),
    ],
    'Altaveus': [
        ('Els altaveus estan encesos, però no emeten so quan es reprodueix àudio.', False),
        ('El so dels altaveus se sent distorsionat fins i tot amb el volum baix.', False),
        ('Només un dels dos altaveus emet so quan es reprodueix àudio estèreo.', False),
        ('El so dels altaveus es talla durant la reproducció.', True),
    ],
}

def inventario():
    # Semilla fija: el mismo codigo conserva marca, zona y departamento.
    azar, equipos = random.Random(42), []
    for depto, (sigla, zonas) in DEPARTAMENTOS.items():
        for tipo, marcas in MARCAS.items():
            for numero in range(1, 21):
                zona = "Sala de reunions" if tipo == "Projector" else azar.choice(zonas)
                alcance = "departament" if tipo in ("Impressora", "Router/Switch") else "persona"
                if tipo == "Projector": alcance = "reunio"
                codigo = f"{PREFIJOS[tipo]}-{sigla}-{numero:03d}"
                equipos.append((tipo, codigo, azar.choice(marcas), depto, zona, alcance))
    equipos.append(("Router/Switch", "NET-CORE-001", "Cisco", "Informàtica", "Planta baixa", "organitzacio"))
    return equipos


def generar(cantidad):
    equipos, filas, vistas, historial = inventario(), [], set(), set()
    tipos = tuple(CASOS)
    pesos = (20, 11, 12, 7, 7, 7, 10, 20, 4, 2)
    grupos = {t: [e for e in equipos if e[0] == ("PC" if t == "Programari de l'ordinador" else t)] for t in tipos}
    fechas = [date.today() - timedelta(days=n) for n in range(365) if (date.today() - timedelta(days=n)).weekday() < 5]
    while len(filas) < cantidad:
        tipo = random.choices(tipos, weights=pesos)[0]
        _, codigo, marca, depto, zona, alcance = random.choice(grupos[tipo])
        texto, intermitente = random.choice(CASOS[tipo])
        fecha = random.choice(fechas).isoformat()
        if (fecha, codigo) in vistas: continue
        vistas.add((fecha, codigo))
        filas.append((fecha, codigo, tipo, marca, depto, zona, alcance, texto, intermitente))
    respuestas = []
    for fecha, codigo, tipo, marca, depto, zona, alcance, texto, intermitente in sorted(filas):
        clave = (codigo, tipo, texto)
        frecuencia = random.choice(("De tant en tant", "Cada dia")) if intermitente else "Constantment"
        if not intermitente and clave not in historial:
            frecuencia = random.choice(("És la primera vegada", "Constantment"))
        historial.add(clave)
        reinicio = ""
        if tipo in ("PC", "Programari de l'ordinador"):
            reinicio = "No" if "no s'encén" in texto else random.choice(("Sí", "No"))
            if reinicio == "Sí": texto += " S'ha reiniciat l'ordinador, però el problema persisteix."
        correo = codigo.lower() + "@example.com"
        valores = (correo, TEXTO_AVISO, fecha, zona, depto, tipo, codigo, texto, marca, frecuencia, random.choice(ALCANCES[alcance]), reinicio, random.choice(HORARIOS))
        respuestas.append(dict(zip(CAMPOS, valores)))
    return respuestas


class Pagina(HTMLParser):
    def __init__(self, texto):
        super().__init__(); self.ocultos = {}; self.confirmada = False; self.formulario = False
        self.feed(texto)

    def handle_starttag(self, tag, atributos):
        a = dict(atributos)
        if tag == "input" and a.get("type") == "hidden" and a.get("name"):
            self.ocultos[a["name"]] = a.get("value", "")
        if tag == "form" and "/formResponse" in a.get("action", ""): self.formulario = True
        if tag == "div" and "vHW8K" in a.get("class", "").split(): self.confirmada = True
        if tag == "a" and "usp=form_confirm" in a.get("href", ""): self.confirmada = True


def payload(fila, ocultos):
    datos = {k: v for k, v in ocultos.items() if k in ("fvv", "fbzx", "partialResponse", "submissionTimestamp")}
    datos.update({"fvv": datos.get("fvv", "1"), "pageHistory": "0,1,2", "emailAddress": fila[CORREO]})
    for campo, identificador in ENTRADAS.items():
        valor, clave = fila[campo], "entry." + identificador
        if not valor: continue
        if campo == FECHA:
            f = date.fromisoformat(valor)
            datos.update({clave + "_year": str(f.year), clave + "_month": str(f.month), clave + "_day": str(f.day)})
        elif (campo == TIPO and valor not in TIPOS_DIRECTOS) or (campo == MARCA and valor not in MARCAS_DIRECTAS):
            datos.update({clave: "__other_option__", clave + ".other_option_response": valor})
        else: datos[clave] = valor
    return datos


def enviar(respuestas):
    sesion = build_opener(HTTPCookieProcessor(CookieJar()))
    # Una sola carga inicial; despues un POST por respuesta, sin pausa artificial.
    with sesion.open(URL_FORMULARIO, timeout=30) as r:
        pagina = Pagina(r.read().decode("utf-8"))
    if not pagina.formulario or not pagina.ocultos.get("fbzx"):
        raise RuntimeError("Google no permite acceder al formulario con este metodo.")
    confirmadas = 0
    for numero, fila in enumerate(respuestas, 1):
        try:
            peticion = Request(URL_ENVIO, data=urlencode(payload(fila, pagina.ocultos)).encode("utf-8"))
            with sesion.open(peticion, timeout=45) as r:
                resultado = Pagina(r.read().decode("utf-8"))
            if not resultado.confirmada or resultado.formulario:
                raise RuntimeError("Google no ha devuelto la confirmacion.")
            confirmadas += 1
            print(f"[{numero}/{len(respuestas)}] Enviada i confirmada: {fila[TIPO]}", flush=True)
        except (Exception, KeyboardInterrupt) as error:
            print(f"\nAturat a la resposta {numero}: {error or 'interrupcio manual'}.")
            print("Comprova aquesta ultima resposta al Forms abans de repetir-la.")
            break
    print(f"TOTAL CONFIRMADES EN AQUESTA EXECUCIO: {confirmadas}")


def main():
    while True:
        valor = input("Quantes respostes vols enviar? [4000]: ").strip() or "4000"
        if valor.isdecimal() and 1 <= int(valor) <= 100000: break
        print("Escriu un nombre enter entre 1 i 100000.")
    respuestas = generar(int(valor))
    if "--comprobar" in sys.argv:
        for fila in respuestas: payload(fila, {})
        print(f"{len(respuestas)} respostes validades. Cap enviament realitzat.")
        return
    try: enviar(respuestas)
    except (Exception, KeyboardInterrupt) as error: print(f"Proces aturat: {error or 'interrupcio manual'}")


if __name__ == "__main__":
    main()
