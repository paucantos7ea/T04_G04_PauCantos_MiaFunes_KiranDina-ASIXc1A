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
python3 main.py --demo                       # inyecta 1 crítica + 1 anomalía de prueba
python3 main.py --help
```

**Si no se pasa `--file`**, el programa busca `respotes.xml` o `incidencies.xml`, por este orden:

1. En el directorio desde el que lanzas el comando.
2. En la carpeta del proyecto (donde está `main.py`).
3. Si no lo encuentra, te pide la ruta (puedes escribirla, completarla con Tab o arrastrar el archivo a la terminal) y no continúa hasta que el archivo exista.

### Inyector de pruebas en tiempo real (`--demo`)

Con la web abierta, ejecuta en otra terminal:

```bash
python3 main.py --demo
```

Añade al final del XML vigilado (el mismo que encontraría `--web`, o el de `--file`) dos incidencias con los siguientes IDs libres:

1. Una **válida y Crítica** con la fecha de hoy: caída general de la red en la *Primera planta*.
2. Una **anomalía evidente**: fecha imposible (1668) y texto aleatorio tipo Faker.

La consola muestra los dos IDs y en ~2 s la web avisa de las nuevas incidencias y actualiza KPIs y gráficos. La escritura es segura: los nombres de los campos se copian de la última incidencia del archivo, los valores se escapan, el resultado se vuelve a parsear antes de guardarlo y se escribe de forma atómica. **Modifica el XML de verdad**: para deshacerlo, `git checkout -- incidencies.xml`.

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

> ⚠️ **La URL del túnel es pública**: la web siempre pide PIN, pero **cambia los PINs de fábrica** (1234 / 12345) antes de abrir el túnel (ver «Acceso por PIN» más abajo). Si no lo haces, la consola te avisa en rojo.

### Acceso por PIN y registro de auditoría

Al abrir la web **lo único que se carga es la pantalla del PIN**: sin sesión no se lee el XML ni se pinta ningún dato, gráfico o menú (`st.stop()`). Hay dos niveles:

| PIN (de fábrica) | Modo | Qué puede hacer |
|---|---|---|
| `1234` | 👁️ **Consultor** | Ver todo (gráficos, filtros, radar, masivas, reglas, fichas) y descargar el informe ejecutivo, `respotes_limpio.xml` y `cuarentena.csv`. **No** puede editar reglas ni reparaciones. |
| `12345` | 🛠️ **Técnico** | Además, editar `rules.json` (editor y palabras emergentes), cambiar estados y notas de reparación y consultar la pestaña **📜 Auditoría de Cambios**. |

En la cabecera se ven siempre el rol activo, el indicador en vivo y el botón **🔑 Cerrar sesión**.

**Dónde se configuran los PINs**, por prioridad:

1. Variables de entorno `PIN_CONSULTA` y `PIN_TECNICO` (recomendado en servidores y en Streamlit Cloud).
2. `pins.json` en la raíz del proyecto. Se crea solo con los valores de fábrica si no existe:
   ```json
   { "consulta": "4821", "tecnico": "730915" }
   ```

Cada PIN debe tener de 4 a 12 cifras, y los dos tienen que ser distintos. Tras **5 intentos fallidos en 1 minuto**, se rechaza cualquier PIN durante 60 s, para frenar la fuerza bruta. `pins.json` está en `.gitignore`: el repositorio es público y nunca debe subirse.

**`audit.log`** (raíz del proyecto, UTF-8, solo se añaden líneas) registra con el formato `[YYYY-MM-DD HH:MM:SS] [ROL] [ACCIÓN] Detalle`:

- Accesos correctos, intentos fallidos y cierres de sesión. El PIN tecleado **no** se guarda, solo su longitud.
- Cambios de reparación: ID, estado anterior → nuevo y nota.
- Cambios en `rules.json`: palabras añadidas o quitadas por lista, marcas y años.
- Descargas del informe ejecutivo, `respotes_limpio.xml`, `cuarentena.csv`, el CSV filtrado y el propio `audit.log`.

En Modo Técnico, la pestaña **📜 Auditoría de Cambios** lo muestra del más reciente al más antiguo y **se refresca sola cada 3 s**, con filtros por tipo de acción, rol y texto, y botón para descargar `audit.log`.

### Qué ofrece

- **Cabecera**: rol activo, indicador en vivo, selector **☀️ Claro / 🌙 Oscuro** (Claro por defecto; cada usuario elige el suyo y los gráficos cambian a `plotly_white` / `plotly_dark`), botón **📄 Descargar Informe Ejecutivo** y cerrar sesión.
- **En vivo**: comprueba el XML (y `rules.json`) cada 2 s. Al guardar o añadir `<incidencia>`, todo se actualiza solo, sin perder los filtros, y avisa de las incidencias nuevas. Si el XML se está escribiendo a medias, mantiene el último estado válido y reintenta.
- **📊 Panel**: KPIs (incluido el **MTTR**), **⏰ alerta de tickets Críticos y Altos fuera de SLA**, validez vs anomalías, severidad, evolución temporal, top equipos y categorías, **progreso de reparaciones** y **🛰️ radar de puntos calientes**:
  - Zonas cuyo ritmo reciente (ventana de 30, 60 o 90 días) supera su ritmo histórico (×1,3 = punto caliente).
  - Equipos crónicos o reincidentes por código de inventario (`PC-ADM-016`, `EQ-1234`…).
  - Mapa de calor de zona × mes.
- **📋 Incidencias**: tabla con ficha explicada al tocar una fila, o **🛠️ tarjetas de reparación** táctiles (las que incumplen el SLA llevan **⏰ FUERA DE SLA** en el título). En cada tarjeta, el técnico marca *Pendiente / En curso / Resuelta* y deja una nota. Se guarda en **`gestion.json`**; el XML original **nunca** se modifica. Descargas:
  - **`respotes_limpio.xml`**: misma estructura que el original, solo con las válidas y ya auto-reparadas.
  - **`cuarentena.csv`**: una fila por regla incumplida, con el campo afectado y el motivo exacto.
  - CSV del filtro actual.
- **⚡ Incidencias Masivas y Duplicadas**: tarjetas con las tormentas activas, los tickets duplicados, las plantas afectadas y los «fallos reales estimados» (contando cada tormenta y cada grupo de duplicados como un solo fallo). Debajo, el desglose por **planta / oficina**, fecha, categoría, síntoma principal y número de incidencias, con un desplegable con los IDs afectados. Ver [Incidencias masivas, duplicados y SLA](#incidencias-masivas-duplicados-y-sla).
- **Filtros táctiles**: búsqueda (`#42` = ID exacto), estado, severidad, **estado de reparación**, tipo de anomalía, categoría, marca y fechas.
- **🔍 Auditoría y Reglas**:
  - Inspector paso a paso de cada incidencia (reparaciones, validación, categoría, marca y regla exacta de severidad).
  - **🧪 Problemas emergentes**: palabras y bigramas frecuentes en las incidencias sin clasificar bien. Se añaden a `rules.json` con un clic.
  - **✏️ Editor de reglas**: palabras clave, marcas y rango de años, con botón para restaurar los valores de fábrica.
  - Mapa de todas las reglas.
- **Menú lateral** (☰): subir otro XML a mano, pausar el modo en vivo y ver la URL de la red local.

También se puede lanzar directamente con Streamlit: `streamlit run web.py --server.address 0.0.0.0 -- --file ruta/al/respotes.xml`.

### Incidencias masivas, duplicados y SLA

Los umbrales están en `app/config.py` y los de detección se pueden ajustar en la propia pestaña (⚙️ *Ajustar la detección*):

| Concepto | Regla | Ajuste |
|---|---|---|
| **Tormenta** | ≥ 3 incidencias válidas de la misma **categoría** en la misma **planta u oficina** el mismo día (o encadenadas a ≤ N días). Síntoma principal = paso del motor que decidió la severidad más repetido. | `MIN_TORMENTA`, `VENTANA_TORMENTA_DIAS` |
| **Duplicado** | Mismo equipo (código de inventario o, si falta, equipo + zona), fechas a ≤ 3 días y descripción con `difflib.SequenceMatcher` ≥ 0,75. Se encadenan: si A≈B y B≈C, es un solo grupo; el más antiguo es el original. | `UMBRAL_DUPLICADO`, `MARGEN_DUPLICADO_DIAS` |
| **SLA** | Crítica abierta más de 4 h o Alta más de 24 h sin estar *Resuelta*, contando desde la «Marca de temps» del formulario. | `SLA_HORAS` |

**Tiempos de resolución en `gestion.json`.** Cada ID guarda, además de `estado` y `nota`:

```json
"42": {"estado": "Resuelta", "nota": "Cambiado el cable",
       "fecha_inicio": "2026-11-19T09:00:00",
       "fecha_resolucion": "2026-11-19T10:40:00",
       "duracion_minutos": 100.0, "historial": [ ... ]}
```

- `fecha_inicio` se fija la **primera** vez que pasa a *En curso* y ya no cambia.
- Al pasar a *Resuelta* se fijan `fecha_resolucion` y `duracion_minutos`. Si se resuelve sin haber pasado por *En curso*, no hay duración medible y no cuenta para el MTTR.
- Reabrirla borra la resolución; editar solo la nota de una resuelta no toca sus tiempos.

El **MTTR** (tiempo medio de resolución) se calcula global y por severidad y aparece en el panel y en el informe.

### Informe ejecutivo (`informe_estado.html`)

El botón **📄 Descargar Informe Ejecutivo** (Consultor y Técnico) genera un HTML autocontenido, sin JavaScript, listo para imprimir o para *Imprimir → Guardar como PDF*. Incluye:

- Fecha y hora de emisión y un resumen ejecutivo en lenguaje claro.
- KPIs: total procesadas, % válidas, % basura bloqueada y MTTR.
- Ranking de plantas y oficinas, tormentas y duplicados, desglose por severidad con su SLA y los tickets fuera de SLA.

Cada descarga queda en `audit.log`.

### Alternativa permanente: Streamlit Community Cloud

Para tener la web siempre disponible sin el PC encendido:

1. Sube el proyecto a GitHub (con `incidencies.xml` o `respotes.xml` y `rules.json`).
2. En <https://share.streamlit.io>: **Create app** → repositorio, rama `main`, archivo principal **`web.py`**.
3. En **Advanced settings**, elige Python 3.12 y, en *Secrets*:
   ```toml
   PIN_CONSULTA = "4821"
   PIN_TECNICO = "730915"
   ```
4. **Deploy**. Streamlit instala `requirements.txt` y la web lee el XML del repositorio: cada `git push` con el XML actualizado se refleja solo.

> En la nube, los cambios hechos desde la web en `rules.json`, `gestion.json` y `audit.log` duran mientras la app esté activa: se pierden al reiniciarse. Para conservarlos, edita `rules.json` en el repositorio.

**Si el móvil no conecta en la red local**: comprueba que está en la misma Wi-Fi y permite el puerto 8501 en el cortafuegos del PC (Windows lo pregunta la primera vez).

## Dashboard público en GitHub Pages (sin PC encendido)

GitHub Pages solo sirve archivos estáticos: no ejecuta Python. Por eso `python3 main.py --html` analiza el XML con el mismo motor que el resto del programa y escribe un **`index.html` autocontenido**: datos, estilos y código van dentro del propio archivo, y solo Chart.js se carga desde un CDN. Se abre con doble clic o desde cualquier móvil.

Qué incluye:

- **KPIs**: procesadas, válidas y bloqueadas (%), y el recuento por severidad.
- **Gráficos táctiles**: validez vs. anomalías, evolución mensual, severidad y top de equipos, zonas, categorías o marcas.
- **Filtros instantáneos** y **lista paginada** (15 por página, con salto a una página): tarjetas en el móvil y tabla en el escritorio.
- **Ficha «¿por qué se clasificó así?»**: al tocar cualquier incidencia se ven sus campos originales y la regla exacta que decidió.
- **⏰ SLA y ⏱️ MTTR**: tarjetas y aviso con las incidencias Críticas (más de 4 h) y Altas (más de 24 h) sin resolver, contadas desde la «Marca de temps» del formulario. Cada una lleva un ⏰ en la lista. Dejan de contar al marcarlas como *Resuelta*.
- **⚡ Masivas y duplicadas**: tormentas por planta u oficina y tickets duplicados, con las mismas reglas que la versión Python (el motor JS se ha comprobado con un test de paridad). Muestra tarjetas resumen, un gráfico por planta y la lista de grupos con sus IDs: al tocar uno se abre su ficha. Respeta los filtros y también funciona con un XML cargado en local.
- **☀️ Claro / 🌙 Oscuro**: Claro por defecto. El navegador recuerda el tema elegido y los gráficos cambian con él.
- **📄 Descargar Informe Ejecutivo** (los dos roles): `informe_estado.html` generado en el navegador en el momento de pulsar, con las reglas, las reparaciones y el SLA vigentes. Listo para imprimir o guardar como PDF.
- **Pestaña de reglas** con el mapa de reglas activas.
- **Filtro por estado de reparación** y columna «Reparación» en la lista.

**Modo Técnico (PIN de técnico)**, todo dentro de la propia página:

| Función | Dónde | Qué hace |
|---|---|---|
| ✏️ **Editor de reglas** | Pestaña *Reglas* | Años válidos, todas las listas de palabras clave (Crítica, Alta, Leve, Media, léxico técnico) y marcas. **Aplicar y recalcular** vuelve a analizar todo el XML en el navegador con las reglas nuevas (unos 1-2 s). El resultado es idéntico al de Python con esas mismas reglas, comprobado por un test. También permite restaurar los valores de fábrica. |
| 🧪 **Problemas emergentes** | Pestaña *Reglas* | Palabras y parejas frecuentes que aún no son palabra clave. Con ➕ se añaden a la lista elegida y todo se recalcula. |
| 🛠️ **Reparaciones** | Ficha de cada incidencia válida | Estado *Pendiente / En curso / Resuelta* y nota, con `fecha_inicio`, `fecha_resolucion` y `duracion_minutos` automáticos (mismas reglas que `gestion.json`). Alimentan el MTTR, el SLA y el informe. El Consultor solo los ve. |
| 📜 **Auditoría** | Pestaña *Auditoría* (solo Técnico) | Accesos, PINs fallidos, cierres de sesión, cambios de reglas y reparaciones y descargas, con el formato de `audit.log`. Se puede filtrar por acción, rol y texto. |

> **Dónde se guardan los cambios del Técnico.** Una página de GitHub Pages no puede escribir en el repositorio, así que todo se guarda en **el navegador donde se hace** (`localStorage`) y sobrevive a recargas. Para que lo vea todo el mundo:
> 1. En la pestaña *Auditoría*, descarga `rules.json` (y, si quieres conservarlos, `gestion.json` y `audit.log`).
> 2. Sustituye `rules.json` en el repositorio y haz `git push`.
> 3. El workflow regenera y publica la página con las reglas nuevas en 1-2 minutos.
>
> El workflow publica también una copia del XML (`datos.xml`) junto a `index.html`, para que el navegador pueda volver a analizarlo con reglas nuevas.
- **Botón «Cargar otro XML local»**: analiza otro archivo en el propio navegador con las mismas reglas, sin subirlo a ningún sitio.

**Activarlo (una sola vez):**

1. Sube el proyecto a GitHub con la carpeta `.github/workflows/` incluida (`git add .`, `git commit`, `git push`).
2. En el repositorio: **Settings → Pages → Build and deployment → Source: «GitHub Actions»**.
3. Ve a la pestaña **Actions**: el workflow *Publicar dashboard en GitHub Pages* se ejecuta solo con cada `git push` que cambie el XML, `rules.json` o el código (o pulsa *Run workflow*). Al terminar (1-2 min), la URL pública aparece en el resumen del workflow y en *Settings → Pages*: `https://<usuario>.github.io/<repositorio>/`.

El workflow instala las dependencias, ejecuta los tests, regenera `index.html` y lo publica. Si un test falla, no se publica nada y se conserva la versión anterior.

**Pantalla de PIN.** `index.html` se abre bloqueado y pide el PIN de Consultor o de Técnico; tras entrar se ven el rol y un botón «Cerrar sesión». El rol se recuerda solo mientras la pestaña está abierta. Los PINs salen de `pins.json` o de `PIN_CONSULTA` / `PIN_TECNICO`. En GitHub Actions, créalos como secretos en *Settings → Secrets and variables → Actions*; sin ellos se usan los de fábrica. En el HTML **no** va ningún PIN, solo su SHA-256 con una sal aleatoria.

> ⚠️ **Es una barrera de cortesía, no seguridad real.** Un sitio estático no puede esconder sus propios datos: las incidencias van dentro de la página, y quien abra el código fuente las ve sin PIN. Además, un PIN de 4-5 cifras se prueba entero contra la huella en segundos. Para datos confidenciales usa la web con servidor (`python3 main.py --web`), donde el PIN sí se comprueba en el servidor.
>
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
- PIN: Consultor (`1234`) y Técnico (`12345`), variables de entorno, configuración inválida, freno de fuerza bruta y escritura en `audit.log`.
- Web Streamlit de extremo a extremo (AppTest): al abrir solo se ve el PIN, PIN incorrecto auditado, permisos de cada rol, tema oscuro y cierre de sesión.
- Tormentas por planta/oficina, duplicados (incluidas cadenas A≈B≈C), marcas de tiempo de `gestion.json`, MTTR, SLA, `informe_estado.html` e inyección de `main.py --demo`.
- Dashboard estático: pantalla de PIN (sin PINs en claro, SHA-256 en JS idéntico al de Python) y HTML autocontenido y seguro frente a contenido malicioso del XML y, si hay Chromium o Chrome instalado, **paridad exacta** entre el motor JavaScript del navegador y el de Python en todas las incidencias.

Los tests no tocan los archivos reales: trabajan en carpetas temporales.

## Estructura

```
main.py              Punto de entrada CLI (argparse + bucle protegido, --web con túnel, --html, --demo)
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
  analytics.py       Métricas, radar, minería, tormentas, duplicados, MTTR y SLA
  exporter.py        JSON de válidas, respotes_limpio.xml, cuarentena.csv e informe_estado.html
  gestion.py         Estados de reparación y marcas de tiempo en gestion.json
  demo.py            Inyector de pruebas de main.py --demo
  auth.py            PINs (pins.json / variables de entorno), roles y freno de fuerza bruta
  audit.py           Registro de auditoría en audit.log
  tunel.py           Túnel público (cloudflared / ngrok / localtunnel) y QR en ASCII
  html_builder.py    Generador del dashboard estático index.html (GitHub Pages)
  estatico/          Plantilla, CSS y JavaScript del dashboard (motor.js = motor en el navegador,
                     acceso.js = pantalla de PIN)
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
