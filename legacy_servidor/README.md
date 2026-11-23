# Archivos archivados del antiguo servidor local / externo

Esta carpeta conserva el código heredado del antiguo despliegue basado en servidor Python (**Streamlit + Plotly**) y túneles públicos (`cloudflared`, `pyngrok`, `localtunnel`), apartado de la raíz para dejar el proyecto enfocado **100 % en GitHub Pages**.

## Contenido archivado

- `web.py` — Antigua aplicación web interactiva con Streamlit y Plotly.
- `tunel.py` — Gestión de túneles HTTPS externos (`cloudflared`, `ngrok`, `localtunnel`) y código QR en terminal.
- `.streamlit/config.toml` — Configuración del servidor Streamlit.

El despliegue web oficial actual es el dashboard estático **`index.html`** generado con `python3 main.py --html` y publicado automáticamente por `.github/workflows/pages.yml`.
