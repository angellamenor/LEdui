# LEdui API

Adapta enunciados educativos a **Lectura Educativa Inclusiva** (LEdui), con pictogramas de ARASAAC e imágenes de contexto generadas con IA. En español e inglés.

En producción en <https://www.ledui.org>. La versión principal de este documento, en inglés, es [README.md](README.md).

## Cómo funciona

Cada transformación tiene tres pasos:

1. **Texto adaptado.** Claude reescribe el enunciado siguiendo las 10 reglas LEdui y explica los cambios al docente.
2. **Pictogramas.** Claude extrae las acciones clave de la tarea, que se buscan en la API de [ARASAAC](https://arasaac.org) y se componen en una sola imagen.
3. **Imágenes de contexto.** Claude escribe los prompts y Gemini genera las imágenes.

Los pasos 2 y 3 se ejecutan en paralelo cuando termina el 1.

### Modelos de IA

| Tarea | Modelo (por defecto) | Variable de entorno |
|---|---|---|
| Adaptación, palabras clave de pictogramas, prompts de imagen | `claude-sonnet-4-5-20250929` | `CLAUDE_MODEL` |
| Generación de imágenes de contexto | `gemini-2.5-flash-image` | `GEMINI_IMAGE_MODEL` |

Cada transformación guarda el nombre del modelo que devolvió la API.

## Arrancar en local

Necesita Python 3.11.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # y rellena las claves
alembic upgrade head
uvicorn app.main:app --reload # http://localhost:8000  ·  docs: /docs
pytest                        # tests (no llaman a ninguna API real)
```

Para probar sin PostgreSQL, pon `DATABASE_URL=sqlite:///./ledui.db` en el `.env`. Copia también `logo-ledu2.png` a `static/`.

## Prompts

Cada prompt es un fichero en `app/prompts/<idioma>/<nombre>.md` (`adaptar_*`, `pictogramas_*`, `imagenes_*`). Orden de prioridad:

1. `PROMPT_<NOMBRE>_<IDIOMA>`: texto completo en una variable de entorno.
2. `PROMPT_<NOMBRE>_<IDIOMA>_FILE`: ruta a un fichero.
3. `PROMPTS_DIR/<idioma>/<nombre>.md`
4. Los ficheros incluidos en `app/prompts/`.

Con `PROMPTS_HOT_RELOAD=true` los cambios se aplican en la siguiente petición, y `PROMPT_SET_NAME` etiqueta cada transformación (`prompt_version`, p. ej. `exp3:1a2b3c4d`) para comparar experimentos. Más detalle en [README.md](README.md).

## Idiomas

- **Interfaz:** selector **ES | EN** de la cabecera.
- **Adaptación:** se elige en «Nueva transformación», independiente de la interfaz. Decide los prompts, el idioma de ARASAAC y el texto de las imágenes.

## Enunciados de ejemplo

En «Nueva transformación», con el cuadro vacío, aparece una línea discreta con un ejemplo por nivel. Los textos están en `static/data/ejemplos.json` (los de ESO, FP y Universidad proceden del Anexo B de la memoria del TFG).

## Administradores

```bash
python -m scripts.make_admin usuario@ejemplo.com           # dar permisos
python -m scripts.make_admin usuario@ejemplo.com --revoke  # quitarlos
```

## Despliegue

El `Dockerfile` ejecuta `alembic upgrade head` antes de arrancar. Variables necesarias en producción: `ENVIRONMENT=production`, `DATABASE_URL`, `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY`, `VALID_ACCESS_KEY` y `CORS_ORIGINS`. Lista completa en `.env.example`.

## Autor

Ángel Luis González Serrano. Trabajo Fin de Grado (Ingeniería Informática, UCLM), dirigido por Carlos González Morcillo.
