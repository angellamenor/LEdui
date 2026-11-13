# LEdui API

Adaptación de enunciados educativos a **Lectura Educativa inclusiva** (LEdui), con pictogramas de ARASAAC e imágenes de contexto. Español e inglés.

## Estructura

```
app/
  main.py            crea la aplicación FastAPI
  config.py          toda la configuración (variables de entorno)
  i18n.py            idioma de la petición y mensajes del backend
  prompt_loader.py   carga de prompts desde ficheros / entorno
  prompts/
    es/  en/         un .md por prompt e idioma
    estilos_imagen.json
  models.py  database.py  crud.py  schemas.py  auth.py
  routers/           auth, adaptaciones, historial, admin, sistema
  services/          llm (Claude), adaptacion, pictogramas, imagenes, documento (.docx)
migrations/          Alembic (0001 esquema, 0002 idioma + prompt_version)
static/
  LEdu_front.html    interfaz
  css/ledui.css
  js/i18n.js  js/app.js
  i18n/es.json  i18n/en.json   textos de la interfaz
scripts/hacer_admin.py
tests/
```

## Arrancar en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # y rellena las claves
alembic upgrade head
uvicorn app.main:app --reload # http://localhost:8000  ·  docs: /docs
pytest                        # tests (no llaman a ninguna API real)
```

Copia también `logo-ledu2.png` a `static/`.

## Prompts

Cada prompt es un fichero en `app/prompts/<idioma>/<nombre>.md`:

| Nombre | Uso |
|---|---|
| `adaptar_system`, `adaptar_user` | Adaptación del enunciado |
| `pictogramas_system`, `pictogramas_user` | Acciones para ARASAAC |
| `imagenes_system`, `imagenes_user` | Prompts para Gemini |

Marcadores disponibles: `{{enunciado}}`, `{{nivel}}`, `{{max_palabras}}`, `{{num_imagenes}}`, `{{estilo}}`, `{{idioma}}` (`es`/`en`), `{{idioma_nombre}}` (`español`/`English`), `{{idioma_nombre_en}}` (`Spanish`/`English`). Las llaves simples `{ }` se pueden usar libremente para ejemplos JSON.

Orden de prioridad para cada prompt:

1. `PROMPT_<NOMBRE>_<IDIOMA>`: texto completo en una variable de entorno.
2. `PROMPT_<NOMBRE>_<IDIOMA>_FILE`: ruta a un fichero.
3. `PROMPTS_DIR/<idioma>/<nombre>.md`
4. Los ficheros incluidos en `app/prompts/`.

**Flujo para experimentar:**

```bash
mkdir -p experimentos/exp3/es
cp app/prompts/es/adaptar_system.md experimentos/exp3/es/   # solo lo que cambias
PROMPTS_DIR=experimentos/exp3 PROMPT_SET_NAME=exp3 PROMPTS_HOT_RELOAD=true uvicorn app.main:app --reload
```

Con `PROMPTS_HOT_RELOAD=true` los cambios en los `.md` se aplican en la siguiente petición. Cada transformación guarda `idioma` y `prompt_version` (p. ej. `exp3:1a2b3c4d`), así que luego puedes filtrar resultados por experimento: `GET /admin/transformaciones?prompt_version=exp3:1a2b3c4d`. `GET /admin/prompts` muestra qué prompts se están usando, de dónde salen y su huella; `POST /admin/prompts/reload` los vuelve a leer sin reiniciar.

## Idiomas

- **Idioma de la interfaz:** selector **ES | EN** de la cabecera (se recuerda en el navegador). Solo cambia los textos de la web y los mensajes de error.
- **Idioma de la adaptación:** se elige en la ventana «Nueva transformación», independiente del de la interfaz (se recuerda el último elegido). Se envía como `idioma` y decide qué prompts se usan: la adaptación, la explicación para el docente, los pictogramas (ARASAAC se consulta en ese idioma), las etiquetas y el texto dentro de las imágenes.
- Los pasos 2 y 3 (pictogramas e imágenes) heredan el idioma de su transformación.
- Los errores del backend también se devuelven en ese idioma (`idioma` o cabecera `Accept-Language`).
- Añadir un idioma: `app/prompts/<xx>/`, `static/i18n/<xx>.json`, `MESSAGES` y `LANGUAGE_NAMES` en `app/i18n.py`, y el código en `supported_languages` de `config.py` y en `SUPPORTED` de `static/js/i18n.js`.

## Pantalla de acceso

La caja de acceso tiene cinco pestañas: *Acceder*, *¿Por qué LEdui?*, *Reglas LEdui*, *Vídeo demo* y *Contacto*. Los textos están en `static/i18n/es.json` y `en.json` (claves `info.*`). Al iniciar sesión se va directamente a las transformaciones.

## Administradores

El rol de admin sale de la columna `users.is_admin`, no de una clave. La pestaña «Administración» aparece solo a esos usuarios.

```bash
python -m scripts.hacer_admin usuario@educastillalamancha.es
```

## Despliegue (Railway)

`nixpacks.toml` y `Procfile` ejecutan `alembic upgrade head` antes de arrancar. Las migraciones son idempotentes: sobre la base de datos actual solo añaden las columnas `idioma` y `prompt_version`.

Variables a revisar en Railway: renombra `MI_ANTHROPIC_KEY` a `ANTHROPIC_API_KEY` (el nombre antiguo sigue funcionando), define `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `CORS_ORIGINS` (tu dominio) y `ENVIRONMENT=production`.

### Enunciados de ejemplo

En el modal de *Nueva transformación*, mientras el cuadro de texto está vacío, aparece una línea discreta con un ejemplo por nivel. Al pulsarlo se rellena el enunciado y se selecciona el nivel; el idioma del ejemplo es el elegido para la adaptación. Los textos están en `static/data/ejemplos.json` (los de ESO, FP y Universidad proceden del Anexo B de la memoria) y se pueden cambiar sin tocar el código.
