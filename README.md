# Escáner de incidencias XML

Aplicación de terminal **y web** que analiza un XML de incidencias (`respotes.xml` / `incidencies.xml`), separa los registros válidos de los anómalos, explica por qué se ha rechazado cada uno y permite explorarlos con filtros, gráficas y exportación a JSON.

Funciona igual en **Windows, Linux y macOS** y se puede lanzar desde cualquier carpeta.

## Requisitos

- Python 3.9 o superior
- Las librerías de `requirements.txt` (`rich`, `questionary` y, para la interfaz web, `streamlit` y `plotly`)
- La interfaz web necesita Python 3.10 o superior (requisito de Streamlit)

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

## Uso

```bash
python main.py                              # busca el XML automáticamente
python main.py --file datos/incidencies.xml # ruta relativa al directorio actual
python /ruta/al/proyecto/main.py -f C:\Users\yo\respotes.xml
python main.py --help
```

En Windows puedes usar `py` en lugar de `python`; en Linux/macOS, `python3`.

**Si no se pasa `--file`**, el programa busca `respotes.xml` o `incidencies.xml`, por este orden:

1. En el directorio desde el que lanzas el comando.
2. En la carpeta del proyecto (donde está `main.py`).
3. Si no lo encuentra, te pide la ruta (puedes escribirla, completarla con Tab o arrastrar el archivo a la terminal) y no continúa hasta que el archivo exista.

### Menú principal

| Opción | Qué hace |
|---|---|
| Incidencias válidas | Listado paginado de las que pasan todas las reglas |
| Registro de anomalías | Filtra por fechas imposibles, contenido basura, desbordamiento o campos vacíos |
| Explorar por severidad | Crítica · Alta · Media · Leve, y entrar a revisar cada nivel |
| Gráficas de averías | Barras por categoría de equipo, top de equipos y severidad |
| Filtrar por marca o categoría | Marca leída del XML o deducida por regex; sin marca → por categoría |
| Filtrar por fechas | Año/mes presentes en los datos o rango `AAAA-MM-DD` |
| Buscar por texto o ID | ID exacto abre la ficha; si no, busca el texto en todos los campos |
| Guardar en JSON | Crea o actualiza `incidencies.json` junto al XML (sobrescribir o añadir sin duplicar) |

### Controles de las tablas

`[N]` siguiente · `[P]` anterior · `[G]` ir a una página · `[I]` ficha detallada por ID · `[Q]` volver

`Ctrl+C` cierra el programa limpiamente en cualquier momento.

### Severidad

| Nivel | Cuándo |
|---|---|
| Crítica | Servidores, bases de datos, routers/switches, caída general de red |
| Alta | Hardware crítico de un equipo (disco, placa, BSOD…) o que no arranca |
| Media | Software y errores genéricos |
| Leve | Periféricos: teclado, ratón, cables, altavoces, impresora |

Las palabras clave y expresiones regulares se ajustan en `app/config.py` (`REGLAS_SEVERIDAD` fija el orden de decisión).

## Interfaz web en tiempo real (Chrome en PC y móvil)

```bash
python main.py --web                       # busca respotes.xml / incidencies.xml
python main.py --web -f datos/respotes.xml # XML concreto
python main.py --web --port 8502           # otro puerto (si 8501 está ocupado se busca uno libre)
```

La consola muestra las URLs exactas para abrir en Chrome:

```
💻 PC (este equipo)       http://localhost:8501
📱 Móvil (misma Wi-Fi)    http://192.168.1.20:8501
```

También se puede lanzar directamente con Streamlit desde la carpeta del proyecto:

```bash
streamlit run web.py --server.address 0.0.0.0
streamlit run web.py --server.address 0.0.0.0 -- --file ruta/al/respotes.xml
```

**Qué ofrece**

- **En vivo**: comprueba el XML cada 2 s (fecha de modificación y tamaño). Al guardar o añadir `<incidencia>`, métricas, gráficos y tablas se actualizan solos, sin perder los filtros, y aparece un aviso con las incidencias nuevas. La insignia de la cabecera muestra `🟢 En vivo · Última lectura: HH:MM:SS`.
- **A prueba de guardados a medias**: si el XML se está escribiendo y no se puede leer, se mantiene el último estado válido (`🟡 Reintentando lectura`) y se reintenta en el siguiente ciclo.
- **Panel**: KPIs (procesadas, válidas %, bloqueadas %, críticas/altas), anillo de validez vs anomalías, evolución temporal por día/semana/mes, top equipos y categorías, y distribución por severidad.
- **Filtros táctiles**: búsqueda libre (`#42` = ID exacto), estado, severidad, tipo de anomalía, categoría, marca y rango de fechas.
- **🔍 Cómo se categoriza (Auditoría y Reglas)**: mapa de las reglas activas (generado desde `app/config.py`) y un inspector por ID que explica, paso a paso, por qué cada incidencia se validó o rechazó y qué palabra clave fijó su severidad.
- **Menú lateral** (☰): subir otro XML a mano (útil desde el móvil), pausar la actualización en vivo y ver la URL para el móvil.

**Si el móvil no conecta**: comprueba que está en la misma Wi-Fi y permite el puerto 8501 en el cortafuegos del PC (Windows lo pregunta la primera vez). Para acceder desde fuera de la red local usa un túnel, p. ej. `cloudflared tunnel --url http://localhost:8501`.

## Estructura

```
main.py              Punto de entrada CLI (argparse + bucle protegido, --web)
web.py               Interfaz web Streamlit + Plotly (solo presentación)
.streamlit/          Configuración de Streamlit (sin telemetría, modo headless)
app/
  config.py          Constantes, colores, palabras clave y regex
  models.py          Incidencia, Anomalia, EstadisticasResumen
  utils.py           Utilidades de texto, rutas y fechas
  parser.py          Carga y validación de estructura del XML
  validator.py       Anomalías, fechas, marca, categoría y severidad
  analytics.py       Métricas, rankings y filtros
  exporter.py        Lectura/escritura del JSON
  ui/
    console.py       Consola Rich única con UTF-8 forzado
    dashboard.py     Dashboard, tarjetas KPI, barras y sparklines
    paginator.py     Tablas zebra paginadas y fichas por ID
    menus.py         Menús questionary y controlador de la app
legacy/              Versión monolítica anterior (solo referencia)
```

## Problemas frecuentes

- **Caracteres raros en CMD antiguo**: el programa fuerza UTF-8 al arrancar. Si aun así ves `?` en los bordes, usa Windows Terminal o cambia la fuente de la consola a una con soporte Unicode (Cascadia Mono, Consolas).
- **`Faltan dependencias`**: activa el entorno virtual y repite `pip install -r requirements.txt`.
- **Sin terminal interactiva** (salida redirigida, IDE sin TTY): los menús con flechas se sustituyen automáticamente por menús numerados.
