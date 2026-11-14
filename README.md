# LEdui API

Adapts educational task statements to **Inclusive Educational Reading** (*Lectura Educativa Inclusiva*, LEdui), adding ARASAAC pictograms and AI-generated context images. Available in Spanish and English.

Live at <https://www.ledui.org>. A Spanish version of this file is available in [README.es.md](README.es.md).

## How it works

Each transformation runs in three steps:

1. **Adapted text.** Claude rewrites the task statement following the 10 LEdui rules and explains the changes for the teacher.
2. **Pictograms.** Claude extracts the key actions of the task, which are looked up in the [ARASAAC](https://arasaac.org) API and composed into a single image.
3. **Context images.** Claude writes image prompts and Gemini generates the images.

Steps 2 and 3 run in parallel once step 1 has finished.

### AI models

| Task | Model (default) | Environment variable |
|---|---|---|
| Text adaptation, pictogram keywords, image prompts | `claude-sonnet-4-5-20250929` | `CLAUDE_MODEL` |
| Context image generation | `gemini-2.5-flash-image` | `GEMINI_IMAGE_MODEL` |

The model name returned by the API is stored with every transformation.

## Project structure

```
app/
  main.py            FastAPI application factory
  config.py          all settings (environment variables)
  i18n.py            request language and backend messages
  prompt_loader.py   loads prompts from files / environment variables
  prompts/
    es/  en/         one .md file per prompt and language
    estilos_imagen.json
  models.py  database.py  crud.py  schemas.py  auth.py
  routers/           auth, adaptaciones, historial, admin, sistema
  services/          llm (Claude), adaptacion, pictogramas, imagenes, documento (.docx)
migrations/          Alembic (0001 initial schema, 0002 language + prompt_version)
static/
  LEdu_front.html    user interface
  css/ledui.css
  js/i18n.js  js/app.js
  i18n/es.json  i18n/en.json   interface texts
  data/ejemplos.json           example task statements
scripts/make_admin.py
tests/
```

### Naming

The domain vocabulary in the code (routes, database tables, module names) is in Spanish, because the project was designed for Spanish schools. Main terms:

| Spanish | English |
|---|---|
| enunciado | task statement |
| adaptación / transformación | adaptation / transformation |
| nivel (educativo) | (educational) level |
| idioma | language |
| pictogramas | pictograms |
| imágenes | images |
| historial | history |
| estilo | style |
| docente | teacher |

## Running locally

Requires Python 3.11.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # then fill in the keys
alembic upgrade head
uvicorn app.main:app --reload # http://localhost:8000  ·  API docs: /docs
pytest                        # tests (no real API is called)
```

For a quick local setup without PostgreSQL, set `DATABASE_URL=sqlite:///./ledui.db` in `.env`.

Also copy `logo-ledu2.png` into `static/`.

## Prompts

Each prompt is a file in `app/prompts/<language>/<name>.md`:

| Name | Purpose |
|---|---|
| `adaptar_system`, `adaptar_user` | Task statement adaptation |
| `pictogramas_system`, `pictogramas_user` | Actions to look up in ARASAAC |
| `imagenes_system`, `imagenes_user` | Prompts for Gemini |

Available placeholders: `{{enunciado}}`, `{{nivel}}`, `{{max_palabras}}`, `{{num_imagenes}}`, `{{estilo}}`, `{{idioma}}` (`es`/`en`), `{{idioma_nombre}}` (`español`/`English`), `{{idioma_nombre_en}}` (`Spanish`/`English`). Single braces `{ }` can be used freely for JSON examples.

Lookup order for each prompt:

1. `PROMPT_<NAME>_<LANG>`: full text in an environment variable.
2. `PROMPT_<NAME>_<LANG>_FILE`: path to a file.
3. `PROMPTS_DIR/<lang>/<name>.md`
4. The files shipped in `app/prompts/`.

**Experimenting with prompts:**

```bash
mkdir -p experiments/exp3/es
cp app/prompts/es/adaptar_system.md experiments/exp3/es/   # only the ones you change
PROMPTS_DIR=experiments/exp3 PROMPT_SET_NAME=exp3 PROMPTS_HOT_RELOAD=true uvicorn app.main:app --reload
```

With `PROMPTS_HOT_RELOAD=true`, changes to the `.md` files apply on the next request. Every transformation stores `idioma` and `prompt_version` (e.g. `exp3:1a2b3c4d`), so results can later be filtered by experiment: `GET /admin/transformaciones?prompt_version=exp3:1a2b3c4d`. `GET /admin/prompts` shows which prompts are in use, where they come from and their fingerprint; `POST /admin/prompts/reload` reloads them without restarting.

## Languages

- **Interface language:** the **ES | EN** switch in the header (remembered in the browser). It only changes the web texts and error messages.
- **Adaptation language:** chosen in the "New transformation" dialog, independently of the interface language (the last choice is remembered). It is sent as `idioma` and selects the prompts used for the adaptation, the teacher notes, the pictograms (ARASAAC is queried in that language), and the labels and text inside the images.
- Steps 2 and 3 (pictograms and images) inherit the language of their transformation.
- Backend errors are returned in that language too (`idioma` or the `Accept-Language` header).
- To add a language: `app/prompts/<xx>/`, `static/i18n/<xx>.json`, `MESSAGES` and `LANGUAGE_NAMES` in `app/i18n.py`, plus the code in `supported_languages` in `config.py` and `SUPPORTED` in `static/js/i18n.js`.

## Example task statements

In the "New transformation" dialog, while the text box is empty, a small line offers one example per educational level. Clicking one fills in the task statement and selects the level; the example is shown in the chosen adaptation language. The texts live in `static/data/ejemplos.json` (the secondary, vocational and university examples come from Annex B of the author's bachelor's thesis) and can be edited without touching the code.

## Sign-in screen

The sign-in box has five tabs: *Sign in*, *Why LEdui?*, *LEdui rules*, *Demo video* and *Contact*. Their texts are in `static/i18n/es.json` and `en.json` (`info.*` keys). After signing in, users go straight to their transformations.

## Administrators

The admin role comes from the `users.is_admin` column, not from a key. The "Administration" tab is only shown to those users.

```bash
python -m scripts.make_admin user@example.com          # grant
python -m scripts.make_admin user@example.com --revoke # revoke
python -m scripts.make_admin --first                 # first registered user
```

## Deployment

The `Dockerfile` (Python 3.11, DejaVu fonts for the pictogram labels) runs `alembic upgrade head` before starting the server. Migrations are idempotent.

Environment variables required in production: `ENVIRONMENT=production`, `DATABASE_URL`, `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY`, `VALID_ACCESS_KEY` and `CORS_ORIGINS` (your domain). See `.env.example` for the full list.

## Author

Ángel Luis González Serrano. Developed as a bachelor's thesis (Computer Engineering, University of Castilla-La Mancha), supervised by Carlos González Morcillo.
