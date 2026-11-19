# Escáner de incidencias XML

Aplicación de terminal **y web** que analiza un XML de incidencias (`respotes.xml` / `incidencies.xml`), **repara** lo que se puede arreglar, separa los registros válidos de los anómalos (incluido el texto aleatorio generado con Faker), explica por qué se ha rechazado cada uno y permite explorarlos con filtros, gráficas, radar de puntos calientes, seguimiento de reparaciones y exportación a XML limpio, CSV y JSON.

Funciona igual en **Windows, Linux y macOS** y se puede lanzar desde cualquier carpeta.

## Requisitos

- Python 3.9 o superior para el menú de terminal; **3.11 o superior para la interfaz web** (requisito de Streamlit 1.67).
- Las librerías de `requirements.txt`: `rich`, `questionary`, `streamlit`, `plotly`, `pandas`, `qrcode` y `pytest`.

## Instalación

Se recomienda un entorno virtual dentro de la carpeta del proyecto.

**Windows (PowerShell o CMD)**

```powershell
cd ruta\al\proyecto
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

> Si PowerShell bloquea `activate`, ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Linux / macOS**

```bash
cd ruta/al/proyecto
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

> **¿«python: no se encontró la orden»?** En muchas distribuciones Linux y en macOS el comando es `python3`, no `python`. En Windows suele ser `python` o `py`. En el resto de esta guía se escribe `python3`.

## Uso

```bash
python3 main.py                              # menú de terminal; busca el XML automáticamente
python3 main.py --file datos/incidencies.xml # ruta relativa al directorio actual
python3 main.py --web                        # interfaz web + túnel público con QR
python3 main.py --html                       # index.html estático para GitHub Pages
python3 main.py --help
```

**Si no se pasa `--file`**, el programa busca `respotes.xml` o `incidencies.xml`, por este orden:

1. En el directorio desde el que lanzas el comando.
2. En la carpeta del proyecto (donde está `main.py`).
3. Si no lo encuentra, te pide la ruta (puedes escribirla, completarla con Tab o arrastrar el archivo a la terminal) y no continúa hasta que el archivo exista.

### Menú de terminal

| Opción | Qué hace |
|---|---|
| Incidencias válidas | Listado paginado de las que pasan todas las reglas |
| Registro de anomalías | Fechas imposibles, contenido basura, texto aleatorio, desbordamiento o campos vacíos |
| Explorar por severidad | Crítica · Alta · Media · Leve, y entrar a revisar cada nivel |
| Gráficas de averías | Barras por categoría de equipo, top de equipos y severidad |
| Filtrar por marca o categoría | Marca leída del XML o deducida; sin marca → por categoría |
| Filtrar por fechas | Año/mes presentes en los datos o rango `AAAA-MM-DD` |
| Buscar por texto o ID | ID exacto abre la ficha; si no, busca el texto en todos los campos |
| Guardar en JSON | Crea o actualiza `incidencies.json` junto al XML (sobrescribir o añadir sin duplicar) |
| Regenerar index.html | Escribe el dashboard estático para GitHub Pages con los datos cargados |

Controles de las tablas: `[N]` siguiente · `[P]` anterior · `[G]` ir a una página · `[I]` ficha detallada por ID · `[Q]` volver. `Ctrl+C` cierra el programa limpiamente en cualquier momento.

## Cómo decide el motor

### 1. Auto-reparación (antes de validar)

Lo que se puede corregir sin inventar datos se corrige y queda anotado en la ficha de la incidencia (🔧):

- Fechas `AAAA-MM-DD`, `DD.MM.AAAA`, `DD-MM-AAAA` o `D/M/AAAA` → `DD/MM/AAAA`, **solo** si es una fecha real dentro del rango de años permitido.
- Espacios duplicados, tabulaciones y saltos de línea en todos los campos.
- Mayúsculas de marcas conocidas: `hp` → `HP`, `lenovo` → `Lenovo`, `Tp-link` → `TP-Link`…

### 2. Validación

Una sola regla incumplida bloquea la incidencia:

| Anomalía | Ejemplos |
|---|---|
| Fecha imposible | año < mínimo (`1668`), futura (`2040`), `31/02`, sin formato |
| Campo vacío | `<camp nom="X"/>` en un campo obligatorio (marca y modelo son opcionales) |
| Spam / Contenido basura | binario, amárico, «Fox News», «cerditos»… |
| **Texto aleatorio / sin sentido** | ensaladas de palabras de Faker: «Cuba ciudad medios ii.», «Peso conocer presenta.» |
| Desbordamiento | más de 200 caracteres en un campo breve (código, equipo…) |

**Filtro de texto aleatorio.** Cada descripción recibe una *fuerza técnica* = 2 × síntomas de avería (`no funciona`, `trencat`, `no encén`, `lent`…) + dispositivos (`teclat`, `impressora`, `wifi`…), según el léxico de `rules.json`:

- Fuerza ≥ 2 → se acepta. Por eso pasan «No funciona», «No respon», «No encèn» o «Teclat trencat».
- Micro-frases planas (Mayúscula + palabras sueltas + punto, sin comas ni apóstrofos) con fuerza < 2 → **texto aleatorio (tipo Faker)**. El motivo cita las señales encontradas: nombres o lugares al azar (`méxico`, `juan`…) y letras o números romanos sueltos (`ii`).
- Párrafo de 25 palabras o más con fuerza < 3, o 12 palabras o más sin ningún término técnico → **sin relación con soporte técnico**.
- Sin ninguna palabra («69») → bloqueada.

### 3. Severidad

Se evalúa en orden y gana la primera regla que encaja:

| Paso | Nivel | Cuándo |
|---|---|---|
| 0 | (el del XML) | Si el XML trae un campo de prioridad, manda su valor |
| 1 | **Crítica** | La **descripción** habla de caída general («xarxa caiguda», «tall general»), o de un síntoma de caída («caigut», «sense internet», «no respon», «fum»…) en un **equipo de infraestructura** (servidor, router, switch…) o con **impacto multiusuario** («tota la planta», «tothom»…) |
| 2 | Alta | Hardware crítico del equipo (disco, placa, BSOD, cremat, virus…) |
| 3 | Alta | Infraestructura que afecta a varias personas (campo de afectados o descripción), sin caída descrita |
| 4 | Leve | Periféricos y consumibles (va antes que «no arranca»: «no arrenca la impressora» es Leve) |
| 5 | Alta | El equipo no arranca o no carga el sistema |
| 6 | Media | Software o error genérico |
| 7 | Media | Sin pistas |

Un `Router/Switch` con un fallo menor («Va molt lent», «No funciona») **ya no es Crítica**: queda en Media (o en Alta si afecta a muchas personas), y la traza de auditoría lo explica.

### Reglas editables: `rules.json`

Las palabras clave de cada nivel de severidad, las marcas reconocidas, el léxico técnico y el rango de años viven en **`rules.json`**, en la raíz del proyecto. Si no existe, se genera solo con los valores de fábrica (`app/config.py` → `REGLAS_POR_DEFECTO`). Si está dañado, el programa usa los valores de fábrica y avisa, pero no lo sobrescribe.

- Una palabra o expresión por elemento, sin tildes ni mayúsculas (se normalizan solas).
- Se buscan al **inicio de palabra**: `impressor` encaja con impressora e impressores.
- Las marcas se buscan como **palabra completa**: `acer` no encaja en «acerca».

Se pueden editar a mano o desde la web (pestaña *Auditoría y Reglas*), que recalcula todo al instante.

## Interfaz web en tiempo real (PC y móvil)

```bash
python3 main.py --web                       # red local + túnel público con QR
python3 main.py --web --sin-tunel           # solo red local
python3 main.py --web -f datos/respotes.xml # XML concreto
python3 main.py --web --port 8502           # otro puerto (si 8501 está ocupado se busca uno libre)
python3 main.py --web --tunel cloudflared   # forzar una herramienta de túnel
```

La consola muestra las direcciones y un **código QR** para escanear con la cámara del móvil:

```
PC (este equipo)        http://localhost:8501
Móvil (misma Wi-Fi)     http://192.168.1.20:8501
Cualquier red (4G/5G)   https://palabras-al-azar.trycloudflare.com
```

### Acceso desde cualquier red: túnel público automático

La «External URL» que muestra Streamlit es la IP pública del router y **no funciona** desde fuera (NAT/cortafuegos). Por eso `--web` abre un túnel HTTPS con la primera herramienta disponible:

| Herramienta | Cuenta | Instalación |
|---|---|---|
| **cloudflared** (recomendada) | No | Windows: `winget install --id Cloudflare.cloudflared` · macOS: `brew install cloudflared` · Linux: binario `cloudflared-linux-amd64` de [GitHub releases](https://github.com/cloudflare/cloudflared/releases) en `~/.local/bin/cloudflared` con `chmod +x` |
| ngrok (pyngrok) | Sí (gratis) | `pip install pyngrok` y variable `NGROK_AUTHTOKEN` |
| localtunnel | No | `npm i -g localtunnel` (o tener `npx`); la primera visita pide la IP pública del PC |

Si no hay ninguna, la web arranca igualmente en la red local y la consola explica qué instalar.

> ⚠️ **La URL del túnel es pública**: cualquiera que la tenga ve los datos. Protégela con contraseña. Es mejor usar la variable de entorno que `--clave`, porque `--clave` queda en el historial de la terminal:
> ```bash
> MONITOR_CLAVE='tu-contraseña' python3 main.py --web          # Linux/macOS
> $env:MONITOR_CLAVE='tu-contraseña'; py main.py --web          # Windows PowerShell
> ```

### Qué ofrece

- **En vivo**: comprueba el XML (y `rules.json`) cada 2 s. Al guardar o añadir `<incidencia>`, todo se actualiza solo, sin perder los filtros, y avisa de las incidencias nuevas. Si el XML se está escribiendo a medias, mantiene el último estado válido y reintenta.
- **📊 Panel**: KPIs, validez vs anomalías, severidad, evolución temporal, top equipos y categorías, **progreso de reparaciones** y **🛰️ radar de puntos calientes**:
  - Zonas cuyo ritmo reciente (ventana de 30, 60 o 90 días) supera su ritmo histórico (×1,3 = punto caliente).
  - Equipos crónicos o reincidentes por código de inventario (`PC-ADM-016`, `EQ-1234`…).
  - Mapa de calor de zona × mes.
- **📋 Incidencias**: tabla con ficha explicada al tocar una fila, o **🛠️ tarjetas de reparación** táctiles. En cada tarjeta, el técnico marca *Pendiente / En curso / Resuelta* y deja una nota. Se guarda en **`gestion.json`**; el XML original **nunca** se modifica. Descargas:
  - **`respotes_limpio.xml`**: misma estructura que el original, solo con las válidas y ya auto-reparadas.
  - **`cuarentena.csv`**: una fila por regla incumplida, con el campo afectado y el motivo exacto.
  - CSV del filtro actual.
- **Filtros táctiles**: búsqueda (`#42` = ID exacto), estado, severidad, **estado de reparación**, tipo de anomalía, categoría, marca y fechas.
- **🔍 Auditoría y Reglas**:
  - Inspector paso a paso de cada incidencia (reparaciones, validación, categoría, marca y regla exacta de severidad).
  - **🧪 Problemas emergentes**: palabras y bigramas frecuentes en las incidencias sin clasificar bien. Se añaden a `rules.json` con un clic.
  - **✏️ Editor de reglas**: palabras clave, marcas y rango de años, con botón para restaurar los valores de fábrica.
  - Mapa de todas las reglas.
- **Menú lateral** (☰): subir otro XML a mano, pausar el modo en vivo y ver la URL de la red local.

También se puede lanzar directamente con Streamlit: `streamlit run web.py --server.address 0.0.0.0 -- --file ruta/al/respotes.xml`.

### Alternativa permanente: Streamlit Community Cloud

Para tener la web siempre disponible sin el PC encendido:

1. Sube el proyecto a GitHub (con `incidencies.xml` o `respotes.xml` y `rules.json`).
2. En <https://share.streamlit.io>: **Create app** → repositorio, rama `main`, archivo principal **`web.py`**.
3. En **Advanced settings**, elige Python 3.12 y, en *Secrets*:
   ```toml
   MONITOR_CLAVE = "tu-contraseña"
   ```
4. **Deploy**. Streamlit instala `requirements.txt` y la web lee el XML del repositorio: cada `git push` con el XML actualizado se refleja solo.

> En la nube, los cambios hechos desde la web en `rules.json` y `gestion.json` duran mientras la app esté activa: se pierden al reiniciarse. Para conservarlos, edita `rules.json` en el repositorio.

**Si el móvil no conecta en la red local**: comprueba que está en la misma Wi-Fi y permite el puerto 8501 en el cortafuegos del PC (Windows lo pregunta la primera vez).

## Dashboard público en GitHub Pages (sin PC encendido)

GitHub Pages solo sirve archivos estáticos: no ejecuta Python. Por eso `python3 main.py --html` analiza el XML con el mismo motor que el resto del programa y escribe un **`index.html` autocontenido**: datos, estilos y código van dentro del propio archivo, y solo Chart.js se carga desde un CDN. Se abre con doble clic o desde cualquier móvil.

Qué incluye:

- **KPIs**: procesadas, válidas y bloqueadas (%), y el recuento por severidad.
- **Gráficos táctiles**: validez vs. anomalías, evolución mensual, severidad y top de equipos, zonas, categorías o marcas.
- **Filtros instantáneos** y **lista paginada** (15 por página, con salto a una página): tarjetas en el móvil y tabla en el escritorio.
- **Ficha «¿por qué se clasificó así?»**: al tocar cualquier incidencia se ven sus campos originales y la regla exacta que decidió.
- **Pestaña de reglas activas.**
- **Botón «Cargar otro XML local»**: analiza otro archivo en el propio navegador con las mismas reglas, sin subirlo a ningún sitio.

**Activarlo (una sola vez):**

1. Sube el proyecto a GitHub con la carpeta `.github/workflows/` incluida (`git add .`, `git commit`, `git push`).
2. En el repositorio: **Settings → Pages → Build and deployment → Source: «GitHub Actions»**.
3. Ve a la pestaña **Actions**: el workflow *Publicar dashboard en GitHub Pages* se ejecuta solo con cada `git push` que cambie el XML, `rules.json` o el código (o pulsa *Run workflow*). Al terminar (1-2 min), la URL pública aparece en el resumen del workflow y en *Settings → Pages*: `https://<usuario>.github.io/<repositorio>/`.

El workflow instala las dependencias, ejecuta los tests, regenera `index.html` y lo publica. Si un test falla, no se publica nada y se conserva la versión anterior.

> ⚠️ **Una web de GitHub Pages es pública**: cualquiera con la URL puede ver las incidencias (descripciones, zonas, códigos de equipo…), aunque el repositorio sea privado. No subas datos personales.

## Tests

```bash
python3 -m pytest
```

Cubren:
- Incidencias reales válidas, incluidos mensajes cortos en catalán y castellano.
- Rechazo del texto aleatorio tipo Faker.
- Router con fallo menor que no debe ser Crítica.
- Auto-reparación de fechas, espacios y marcas.
- Fechas imposibles, etiquetas vacías, desbordamiento, binario y amárico.
- Generación y relectura de `respotes_limpio.xml` y `cuarentena.csv`.
- `rules.json`, `gestion.json`, radar, minería de palabras y túnel (con un `cloudflared` simulado).
- Dashboard estático: HTML autocontenido y seguro frente a contenido malicioso del XML y, si hay Chromium o Chrome instalado, **paridad exacta** entre el motor JavaScript del navegador y el de Python en todas las incidencias.

Los tests no tocan los archivos reales: trabajan en carpetas temporales.

## Estructura

```
main.py              Punto de entrada CLI (argparse + bucle protegido, --web con túnel, --html)
web.py               Interfaz web Streamlit + Plotly (solo presentación)
rules.json           Reglas editables (se genera solo si no existe)
gestion.json         Seguimiento de reparaciones (se crea al guardar el primer estado)
requirements.txt     Dependencias (también las usa Streamlit Community Cloud)
.streamlit/          Configuración de Streamlit (sin telemetría, modo headless)
app/
  config.py          Constantes, regex de campos, valores de fábrica de las reglas
  rules.py           Carga, validación, compilación y guardado de rules.json
  models.py          Incidencia, Anomalia, Reparacion, Paso, EstadisticasResumen
  utils.py           Utilidades de texto, rutas y fechas
  parser.py          Carga y validación de estructura del XML
  validator.py       Auto-reparación, anomalías, coherencia técnica, marca y severidad
  analytics.py       Métricas, filtros, radar de zonas/equipos y minería de palabras
  exporter.py        JSON de válidas, respotes_limpio.xml y cuarentena.csv
  gestion.py         Estados de reparación en gestion.json
  tunel.py           Túnel público (cloudflared / ngrok / localtunnel) y QR en ASCII
  html_builder.py    Generador del dashboard estático index.html (GitHub Pages)
  estatico/          Plantilla, CSS y JavaScript del dashboard (motor.js = motor en el navegador)
  ui/                Menú de terminal (Rich + questionary)
tests/               Tests de pytest
.github/workflows/   pages.yml: regenera y publica index.html en GitHub Pages en cada push
index.html           Dashboard generado (no se versiona: lo crea el workflow)
legacy/              Versión monolítica anterior (solo referencia)
```

## Problemas frecuentes

- **«python: no se encontró la orden»**: usa `python3` (Linux/macOS) o `py` (Windows).
- **Caracteres raros en CMD antiguo**: el programa fuerza UTF-8 al arrancar. Si aun así ves `?` en los bordes, usa Windows Terminal o una fuente con soporte Unicode (Cascadia Mono, Consolas).
- **El QR no se lee**: está pensado para terminales de fondo oscuro. Con fondo claro, abre la URL `https://…` a mano.
- **`Faltan dependencias`**: activa el entorno virtual y repite `pip install -r requirements.txt`.
- **Sin terminal interactiva** (salida redirigida, IDE sin TTY): los menús con flechas se sustituyen por menús numerados.

## Próximas mejoras (Roadmap)

- **Notificaciones push de incidencias críticas**: un bot de Telegram o Discord que avise automáticamente cuando entre una incidencia **Crítica** nueva. La web ya detecta las incidencias nuevas en vivo; faltaría enviar el aviso al canal del equipo técnico. *(Solo documentado: todavía no implementado.)*
