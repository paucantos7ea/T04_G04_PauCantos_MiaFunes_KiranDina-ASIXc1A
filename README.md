# Escáner de incidencias XML (CLI + GitHub Pages)

Aplicación de terminal y **dashboard web estático para GitHub Pages** que analiza un XML de incidencias (`respotes.xml` / `incidencies.xml`), **auto-repara** lo que se puede arreglar, separa los registros válidos de los anómalos (incluido texto aleatorio generado con Faker), detecta incidencias masivas y duplicadas por planta/oficina, controla tiempos **MTTR/SLA**, explica por qué se clasificó cada registro y exporta informes ejecutivos, XML limpio, CSV y JSON.

El despliegue web oficial es **exclusivamente GitHub Pages** (`index.html` autocontenido generado con `python3 main.py --html` y publicado automáticamente por `.github/workflows/pages.yml`).

Funciona igual en **Windows, Linux y macOS** y se puede lanzar desde cualquier carpeta.

## Requisitos

- Python 3.10 o superior (el generador `--html` y `--demo` solo usan la biblioteca estándar).
- Dependencias ligeras de `requirements.txt`: `rich`, `questionary` (menú interactivo de terminal) y `pytest` (tests).

## Instalación

Se recomienda un entorno virtual dentro de la carpeta del proyecto.

**Windows (PowerShell o CMD)**

```powershell
cd ruta\al\proyecto
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

**Linux / macOS**

```bash
cd ruta/al/proyecto
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Uso

```bash
python3 main.py                              # menú interactivo de terminal; busca el XML automáticamente
python3 main.py --file datos/incidencies.xml # ruta concreta al archivo XML
python3 main.py --html                       # genera index.html estático para GitHub Pages
python3 main.py --html --salida web.html     # genera el dashboard en una ruta personalizada
python3 main.py --demo                       # inyecta 1 crítica + 1 anomalía de prueba en el XML
python3 main.py --help
```

**Si no se pasa `--file`**, el programa busca `respotes.xml` o `incidencies.xml`, por este orden:

1. En el directorio actual (`Path.cwd()`).
2. En la carpeta raíz del proyecto (donde está `main.py`).
3. Si no lo encuentra, en el modo terminal solicita la ruta de forma interactiva.

## Dashboard público en GitHub Pages (`index.html`)

GitHub Pages solo sirve archivos estáticos: `python3 main.py --html` ejecuta el motor completo (`parser -> validator -> analytics`) y genera un **`index.html` autocontenido** (CSS, JavaScript y datos embebidos en un único archivo; solo Chart.js se carga desde CDN).

### Diseño basado en acordeones (PC y móvil)

La interfaz está organizada para ofrecer máxima claridad sin saturar la pantalla:

- **Cabecera fija compacta**: título, fecha y hora de actualización, selector de tema **`☀️ Claro / 🌙 Oscuro`** (Claro por defecto), botón **`📄 Informe Ejecutivo`**, carga de XML local, insignia de rol activo (**`👁️ Consultor`** o **`🛠️ Técnico`**) y botón **`Cerrar sesión`**.
- **Fila de KPIs ejecutivos siempre visible**: `Total Procesadas`, `Válidas %`, `Anomalías %`, `Críticas`, `⏰ Fuera de SLA` y `⏱️ MTTR`, más una alerta compacta de tickets fuera de SLA.
- **Barra de navegación rápida**: selector de salto rápido (`Ir a sección…`) ideal para móvil y botones **`Expandir todo`** / **`Contraer todo`**.
- **5 secciones desplegables (acordeones)** que arrancan contraídas con contadores dinámicos en cada cabecera y redimensionado automático de `Chart.js` al abrirse:
  1. **`📊 Gráficos de Validez y Severidad`** — Donut de Validez vs. Anomalías y distribución por severidad.
  2. **`📈 Evolución Temporal y Top Equipos`** — Evolución mensual apilada y Top por Equipo, Zona, Categoría o Marca.
  3. **`⚡ Incidencias Masivas y Duplicadas`** — Badge destacado en cabecera con tormentas y duplicados activos, gráfico por planta y desglose interactivo por Planta/Oficina con IDs clicables.
  4. **`📋 Explorador de Incidencias y Filtros`** — Filtros rápidos y detallados, gestión táctil de estados de reparación (en Modo Técnico) y tabla/tarjetas paginadas con salto de página y modal de trazabilidad.
  5. **`🛡️ Reglas de Clasificación y Auditoría`** — Criterios activos del motor, editor de reglas + palabras emergentes y, visible únicamente en **Modo Técnico**, **`📜 Auditoría de Cambios`** con descarga de `audit.log`, `gestion.json` y `rules.json`.

### Acceso por PIN y roles

Al abrir `index.html`, la pantalla bloqueante de PIN impide ver el panel hasta autenticarse:

| PIN (de fábrica) | Rol | Permisos |
|---|---|---|
| `1234` | **👁️ Consultor** | Lectura completa de KPIs, gráficos, masivas/duplicadas, explorador, reglas activas y descarga de **`📄 Informe Ejecutivo`**. |
| `12345` | **🛠️ Técnico** | Todo lo anterior más gestión táctil de reparaciones (MTTR/SLA), editor de `rules.json` en vivo con recálculo en navegador, problemas emergentes y visor **`📜 Auditoría de Cambios`** (`audit.log` + `localStorage`). |

**Dónde se configuran los PINs** (por prioridad):

1. Variables de entorno `PIN_CONSULTA` y `PIN_TECNICO` (recomendado en GitHub Actions mediante *Settings → Secrets and variables → Actions*).
2. `pins.json` en la raíz del proyecto (se genera automáticamente con `1234` / `12345` si no existe y está en `.gitignore` para no exponerlo en repositorios públicos).

En `index.html` nunca se incrustan los PINs en texto plano: solo su huella **SHA-256 con sal aleatoria**. Incluye freno contra fuerza bruta (5 intentos fallidos) y registro de auditoría en formato `[YYYY-MM-DD HH:MM:SS] [ROL] [ACCIÓN] Detalle`.

> ⚠️ **Nota de privacidad:** Una página estática en GitHub Pages es pública y los datos van embebidos en el archivo HTML. No publiques datos personales confidenciales.

### Despliegue automático (GitHub Actions)

El flujo `.github/workflows/pages.yml` se dispara en cada `push` a `main` / `master` (o manualmente con *Run workflow*):

1. Instala las dependencias ligeras de `requirements.txt`.
2. Ejecuta toda la batería de tests (`pytest`), incluida la paridad exacta Python ↔ JavaScript si hay navegador disponible.
3. Regenera `index.html` con `python3 main.py --html` (usando `secrets.PIN_CONSULTA` / `secrets.PIN_TECNICO` si existen).
4. Empaqueta `_site/` (`index.html`, copia de `datos.xml` para recálculo de reglas en navegador y `.nojekyll`) y lo publica en **GitHub Pages**.

Configuración única en GitHub: **Settings → Pages → Build and deployment → Source: `GitHub Actions`**.

## Motor de análisis (`rules.json`, masivas, duplicados y SLA)

- **Auto-reparación** (antes de validar): normaliza fechas válidas a `DD/MM/AAAA`, espacios redundantes y capitalización de marcas conocidas.
- **Validación**: bloquea fechas imposibles, campos obligatorios vacíos, spam/binario/amárico, texto aleatorio tipo Faker (puntuación por léxico técnico) y desbordamientos (> 200 caracteres en campos breves).
- **Severidad** (`Crítica`, `Alta`, `Media`, `Leve`): evaluada por pasos ordenados con `rules.json` editable.
- **Tormentas**: ≥ 3 incidencias válidas de la misma categoría en la misma planta/oficina en el mismo día (o ventana configurada).
- **Duplicados**: mismo equipo, fechas a ≤ 3 días y similitud de descripción (`difflib.SequenceMatcher`) ≥ 0,75.
- **SLA / MTTR**: alertas para Críticas (> 4 h) y Altas (> 24 h) sin resolver y cálculo automático de MTTR desde *En curso* → *Resuelta*.

## Menú de terminal (`python3 main.py`)

Permite explorar válidas, anomalías, severidades, gráficas ASCII, filtros por marca/categoría/fechas, búsqueda por ID o texto, exportación a JSON y regeneración directa de `index.html`.

## Inyector de pruebas (`--demo`)

```bash
python3 main.py --demo
python3 main.py --html
```

Inyecta 1 incidencia válida Crítica (fecha de hoy) y 1 anomalía evidente en el XML para probar el motor y regenerar el dashboard. Para revertir en Git: `git checkout -- incidencies.xml`.

## Tests

```bash
python3 -m compileall .
python3 -m pytest
```

Cubren el motor de validación y auto-reparación, `rules.json`, `gestion.json`, detección de tormentas y duplicados, MTTR/SLA, informe ejecutivo, autenticación por PIN y `audit.log`, así como el dashboard estático (`index.html`), pantalla de PIN, estructura en acordeones y paridad exacta Python ↔ JavaScript.

## Estructura del repositorio

```text
main.py                    Punto de entrada CLI (--html, --demo y menú interactivo)
rules.json                 Reglas editables de clasificación y léxico técnico
requirements.txt           Dependencias ligeras (CLI + tests)
.github/workflows/
  pages.yml                CI/CD: ejecuta tests, regenera index.html y despliega en GitHub Pages
app/
  config.py                Constantes, regex de campos y reglas por defecto
  rules.py                 Carga, validación y guardado de rules.json
  models.py                Modelos de datos (Incidencia, Anomalia, Reparacion, etc.)
  utils.py                 Utilidades de texto, rutas y fechas
  parser.py                Carga y validación estructural del XML
  validator.py             Auto-reparación, anomalías, coherencia técnica y severidad
  analytics.py             Métricas, radar, tormentas, duplicados, MTTR y SLA
  exporter.py              XML limpio, cuarentena CSV, JSON e informe_estado.html
  gestion.py               Seguimiento de reparaciones y marcas de tiempo
  demo.py                  Inyector de incidencias de prueba (--demo)
  auth.py                  Gestión de PINs (pins.json / env) y freno de fuerza bruta
  audit.py                 Registro de auditoría en formato audit.log
  html_builder.py          Generador de index.html autocontenido para GitHub Pages
  estatico/                Plantilla HTML en acordeones, CSS Claro/Oscuro y JS (motor, operaciones, técnico, acceso)
  ui/                      Menú interactivo de terminal (Rich + questionary)
tests/                     Suite de pruebas pytest
legacy_servidor/           Código archivado del antiguo servidor Streamlit y túneles (web.py, tunel.py, .streamlit/)
legacy/                    Versión monolítica anterior (referencia histórica)
```

> **Archivos locales no versionados (`.gitignore`):** `index.html` (regenerado en cada despliegue por GitHub Actions), `pins.json`, `audit.log`, `gestion.json` y cachés de Python/pytest.
