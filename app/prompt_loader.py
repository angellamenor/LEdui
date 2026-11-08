"""
Carga de prompts desde ficheros o variables de entorno.

Cada prompt tiene un nombre (p. ej. "adaptar_system") y una versión por idioma.
Orden de búsqueda para el prompt <nombre> en el idioma <lang>:

  1. Variable de entorno PROMPT_<NOMBRE>_<LANG>        (texto completo)
  2. Variable de entorno PROMPT_<NOMBRE>_<LANG>_FILE   (ruta a un fichero)
  3. <PROMPTS_DIR>/<lang>/<nombre>.md
  4. <PROMPTS_DIR>/<idioma por defecto>/<nombre>.md
  5. Los mismos ficheros en la carpeta de prompts incluida en el código
     (así, una carpeta de experimento solo necesita los prompts que cambian)

Ejemplo: PROMPT_ADAPTAR_SYSTEM_EN_FILE=/datos/prueba_7/adaptar.md

Las plantillas usan marcadores {{variable}}. No se usan llaves simples para
que los ejemplos JSON del prompt no necesiten escaparse.

Cada prompt cargado tiene una huella (hash) corta. La combinación de huellas
de una llamada se guarda en la base de datos como `prompt_version`, de modo
que se puede saber con qué versión de los prompts se generó cada resultado.
Con PROMPT_SET_NAME=exp3 la versión queda como "exp3:1a2b3c4d".
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

BUILTIN_PROMPTS_DIR = BASE_DIR / "app" / "prompts"

PROMPT_NAMES = (
    "adaptar_system",
    "adaptar_user",
    "imagenes_system",
    "imagenes_user",
    "pictogramas_system",
    "pictogramas_user",
)

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class PromptNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    lang: str
    text: str
    source: str  # de dónde se cargó (variable de entorno o ruta)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:8]

    @property
    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.text))

    def render(self, **variables) -> str:
        missing = self.placeholders - variables.keys()
        if missing:
            logger.warning("Prompt %s/%s: variables sin valor %s", self.lang, self.name, sorted(missing))

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            return str(variables[key]) if key in variables else match.group(0)

        return _PLACEHOLDER.sub(_replace, self.text).strip()


class PromptLoader:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], PromptTemplate] = {}
        self._lock = Lock()

    # --- API pública ---------------------------------------------------------

    def get(self, name: str, lang: str) -> PromptTemplate:
        settings = get_settings()
        lang = settings.normalize_language(lang)
        key = (name, lang)
        if settings.prompts_hot_reload:
            return self._load(name, lang)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._load(name, lang)
            return self._cache[key]

    def render(self, name: str, lang: str, **variables) -> str:
        return self.get(name, lang).render(**variables)

    def version(self, names: list[str], lang: str) -> str:
        """Huella combinada de varios prompts, opcionalmente con el nombre del set."""
        combined = "|".join(self.get(n, lang).fingerprint for n in names)
        digest = hashlib.sha256(combined.encode()).hexdigest()[:8]
        set_name = os.environ.get("PROMPT_SET_NAME", "").strip()
        return f"{set_name}:{digest}" if set_name else digest

    def reload(self) -> None:
        with self._lock:
            self._cache.clear()
        logger.info("Caché de prompts vaciada")

    def describe(self) -> list[dict]:
        """Resumen de todos los prompts activos (para el panel de admin)."""
        settings = get_settings()
        out = []
        for lang in settings.supported_languages:
            for name in PROMPT_NAMES:
                try:
                    tpl = self.get(name, lang)
                    out.append({
                        "nombre": name,
                        "idioma": lang,
                        "origen": tpl.source,
                        "huella": tpl.fingerprint,
                        "variables": sorted(tpl.placeholders),
                        "caracteres": len(tpl.text),
                    })
                except PromptNotFoundError as exc:
                    out.append({"nombre": name, "idioma": lang, "error": str(exc)})
        return out

    # --- Internos ------------------------------------------------------------

    def _load(self, name: str, lang: str) -> PromptTemplate:
        settings = get_settings()
        env_base = f"PROMPT_{name.upper()}_{lang.upper()}"

        inline = os.environ.get(env_base)
        if inline:
            return PromptTemplate(name, lang, inline, f"env:{env_base}")

        env_file = os.environ.get(f"{env_base}_FILE")
        if env_file:
            path = Path(env_file)
            if not path.is_file():
                raise PromptNotFoundError(f"{env_base}_FILE apunta a un fichero que no existe: {path}")
            return PromptTemplate(name, lang, path.read_text(encoding="utf-8"), f"file:{path}")

        candidates: list[Path] = []
        for base in dict.fromkeys([settings.prompts_dir, BUILTIN_PROMPTS_DIR]):
            candidates.append(base / lang / f"{name}.md")
            if lang != settings.default_language:
                candidates.append(base / settings.default_language / f"{name}.md")

        for path in candidates:
            if path.is_file():
                if path.parent.name != lang:
                    logger.warning("Prompt %s no existe en '%s'; se usa %s", name, lang, path)
                return PromptTemplate(name, lang, path.read_text(encoding="utf-8"), f"file:{path}")

        raise PromptNotFoundError(f"No se encontró el prompt '{name}' para el idioma '{lang}'")


prompts = PromptLoader()


def _load_image_styles() -> dict[str, str]:
    settings = get_settings()
    for base in (settings.prompts_dir, BUILTIN_PROMPTS_DIR):
        path = base / "estilos_imagen.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if not k.startswith("_")}
    return {"educativo": "professional educational style, clean composition, high quality"}


def image_style_suffix(style: str | None) -> str:
    styles = _load_image_styles()
    return styles.get(style or "educativo") or styles.get("educativo") or next(iter(styles.values()))
