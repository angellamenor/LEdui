"""
Backend internationalisation.

- Resolves the language of each request (`idioma` field in the body,
  Accept-Language header or default language).
- Translates the messages the backend returns to the user (errors, fallback
  texts, labels of the downloadable documents).

The web interface texts live in static/i18n/<language>.json.
"""
from __future__ import annotations

from fastapi import Request

from app.config import get_settings

# Name of each language, written in that language and in English.
# Passed to the prompts as {{idioma_nombre}} / {{idioma_nombre_en}}.
LANGUAGE_NAMES = {
    "es": {"native": "español", "en": "Spanish"},
    "en": {"native": "English", "en": "English"},
}

MESSAGES: dict[str, dict[str, str]] = {
    "es": {
        "error.enunciado_corto": "El enunciado es demasiado corto.",
        "error.falta_anthropic": "El servicio de IA de texto no está configurado (falta ANTHROPIC_API_KEY).",
        "error.falta_gemini": "El servicio de generación de imágenes no está configurado (falta GOOGLE_AI_API_KEY).",
        "error.ia_servicio": "Error al procesar la petición con el servicio de IA.",
        "error.ia_respuesta": "La respuesta del servicio de IA no tiene el formato esperado.",
        "error.interno": "Error interno del servidor.",
        "error.sin_prompts_imagenes": "No se generaron descripciones de imágenes.",
        "error.sin_acciones": "No se identificaron acciones en el enunciado.",
        "error.no_encontrada": "Transformación no encontrada o no tienes acceso.",
        "error.imagen_no_encontrada": "Imagen no encontrada.",
        "error.no_admin": "No tienes permisos de administrador.",
        "error.auth": "Error en el proceso de autenticación.",
        "error.clave_acceso": "La clave de acceso no es correcta.",
        "error.imagen_no_recibida": "No se recibió imagen en la respuesta del modelo.",
        "error.picto_no_encontrado": "No se encontró pictograma para '{keyword}'.",
        "fallback.explicacion": "Adaptación realizada siguiendo los principios de Lectura Educativa.",
        "fallback.vas_a": "Vas a {accion}.",
        "picto.accion": "Acción {n} - {accion}: {explicacion}",
        "doc.titulo": "Transformación LEdui",
        "doc.id": "ID",
        "doc.usuario": "Usuario",
        "doc.nivel": "Nivel",
        "doc.idioma": "Idioma",
        "doc.fecha": "Fecha",
        "doc.enunciado_adaptado": "Enunciado adaptado",
        "doc.indicaciones": "Docente, ¿qué le faltaba a tu enunciado?",
        "doc.pictogramas": "Pictogramas y habilidades",
        "doc.explicacion_habilidades": "Explicación de habilidades",
        "doc.imagenes_contexto": "Imágenes de contexto",
        "doc.imagen": "Imagen {n}",
        "doc.por_que_imagen": "¿Por qué es útil esta imagen?",
    },
    "en": {
        "error.enunciado_corto": "The task statement is too short.",
        "error.falta_anthropic": "The text AI service is not configured (ANTHROPIC_API_KEY missing).",
        "error.falta_gemini": "The image generation service is not configured (GOOGLE_AI_API_KEY missing).",
        "error.ia_servicio": "Error processing the request with the AI service.",
        "error.ia_respuesta": "The AI service response did not have the expected format.",
        "error.interno": "Internal server error.",
        "error.sin_prompts_imagenes": "No image descriptions were generated.",
        "error.sin_acciones": "No actions were identified in the task.",
        "error.no_encontrada": "Transformation not found or you do not have access.",
        "error.imagen_no_encontrada": "Image not found.",
        "error.no_admin": "You do not have administrator permissions.",
        "error.auth": "Error during authentication.",
        "error.clave_acceso": "The access key is not correct.",
        "error.imagen_no_recibida": "No image was received from the model.",
        "error.picto_no_encontrado": "No pictogram found for '{keyword}'.",
        "fallback.explicacion": "Adaptation carried out following Educational Reading principles.",
        "fallback.vas_a": "You are going to {accion}.",
        "picto.accion": "Action {n} - {accion}: {explicacion}",
        "doc.titulo": "LEdui Transformation",
        "doc.id": "ID",
        "doc.usuario": "User",
        "doc.nivel": "Level",
        "doc.idioma": "Language",
        "doc.fecha": "Date",
        "doc.enunciado_adaptado": "Adapted task",
        "doc.indicaciones": "Teacher, what was your task missing?",
        "doc.pictogramas": "Pictograms and skills",
        "doc.explicacion_habilidades": "Skills explanation",
        "doc.imagenes_contexto": "Context images",
        "doc.imagen": "Image {n}",
        "doc.por_que_imagen": "Why is this image useful?",
    },
}


# Educational levels: the frontend sends a code and the prompt receives the name
# in the adaptation language. Legacy values are also accepted.
NIVELES = {
    "primaria": {"es": "Educación Primaria", "en": "Primary education"},
    "secundaria": {"es": "Educación Secundaria (ESO)", "en": "Secondary education"},
    "bachillerato": {"es": "Bachillerato", "en": "Upper secondary (Bachillerato)"},
    "fp": {"es": "Formación Profesional", "en": "Vocational training"},
    "universidad": {"es": "Universidad", "en": "University"},
}
_NIVEL_ALIASES = {
    "primary": "primaria",
    "secondary": "secundaria",
    "vocational training": "fp",
    "formación profesional": "fp",
    "formacion profesional": "fp",
    "university": "universidad",
}


def normalize_nivel(value: str | None) -> str | None:
    """Return the level code if recognised; otherwise the value unchanged."""
    if not value:
        return value
    key = value.strip().lower()
    if key in NIVELES:
        return key
    return _NIVEL_ALIASES.get(key, value.strip())


def nivel_label(value: str | None, lang: str) -> str:
    code = normalize_nivel(value)
    if code in NIVELES:
        return NIVELES[code][lang] if lang in NIVELES[code] else NIVELES[code]["es"]
    return value or "-"


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Translate a key into the given language (falling back to the default language)."""
    settings = get_settings()
    lang = settings.normalize_language(lang)
    text = MESSAGES.get(lang, {}).get(key) or MESSAGES[settings.default_language].get(key, key)
    return text.format(**kwargs) if kwargs else text


def language_name(lang: str, in_english: bool = False) -> str:
    names = LANGUAGE_NAMES.get(lang, LANGUAGE_NAMES[get_settings().default_language])
    return names["en"] if in_english else names["native"]


def resolve_language(explicit: str | None, request: Request | None = None) -> str:
    """Priority: explicit field > Accept-Language header > default language."""
    settings = get_settings()
    if explicit:
        return settings.normalize_language(explicit)
    if request is not None:
        header = request.headers.get("accept-language", "")
        for part in header.split(","):
            code = part.split(";")[0].strip()
            if code:
                normalized = settings.normalize_language(code)
                if code.lower().startswith(normalized):
                    return normalized
    return settings.default_language


def request_language(request: Request) -> str:
    """FastAPI dependency for endpoints without a body (GET): ?idioma=en or Accept-Language."""
    return resolve_language(request.query_params.get("idioma") or request.query_params.get("lang"), request)
