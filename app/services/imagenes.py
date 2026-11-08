"""Imágenes de contexto: Claude redacta los prompts y Gemini genera las imágenes."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from functools import lru_cache

from google import genai

from app.config import get_settings
from app.i18n import language_name, t
from app.prompt_loader import image_style_suffix, prompts
from app.services.llm import AIResponseError, AIServiceNotConfigured, complete_json

logger = logging.getLogger(__name__)


@lru_cache
def get_genai_client() -> genai.Client | None:
    settings = get_settings()
    return genai.Client(api_key=settings.google_ai_api_key) if settings.google_ai_api_key else None


@dataclass
class ResultadoImagenes:
    imagenes: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def _clean(text: str) -> str:
    return " ".join(text.split())


def _extract_image_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    return None


async def generar_imagenes(enunciado: str, num_imagenes: int, estilo: str | None, lang: str) -> ResultadoImagenes:
    settings = get_settings()
    client = get_genai_client()
    if client is None:
        raise AIServiceNotConfigured("GOOGLE_AI_API_KEY no configurada")

    variables = {
        "enunciado": _clean(enunciado),
        "num_imagenes": num_imagenes,
        "estilo": estilo or "educativo",
        "idioma": lang,
        "idioma_nombre": language_name(lang),
        "idioma_nombre_en": language_name(lang, in_english=True),
    }
    system = prompts.render("imagenes_system", lang, **variables)
    user = prompts.render("imagenes_user", lang, **variables)
    result = await complete_json(system, user, settings.max_tokens_imagenes)

    descripciones = result.data.get("prompts_imagenes") or []
    if not isinstance(descripciones, list) or not descripciones:
        raise AIResponseError(t("error.sin_prompts_imagenes", lang))

    salida = ResultadoImagenes(input_tokens=result.input_tokens, output_tokens=result.output_tokens)
    suffix = image_style_suffix(estilo)

    for idx, item in enumerate(descripciones[:num_imagenes], start=1):
        prompt = str(item.get("descripcion", "")).strip()
        if "16:9" not in prompt:
            prompt += ", 16:9 composition"
        prompt_completo = f"{prompt}, {suffix}"
        base = {
            "concepto_clave": item.get("concepto_clave", ""),
            "justificacion": item.get("justificacion", ""),
            "prompt_usado": prompt_completo,
        }
        try:
            response = await client.aio.models.generate_content(
                model=settings.gemini_image_model,
                contents=prompt_completo,
                config={"image_config": {"aspect_ratio": "16:9"}},
            )
            data = _extract_image_bytes(response)
            if data:
                salida.imagenes.append({
                    **base,
                    "exito": True,
                    "imagen_base64": base64.b64encode(data).decode(),
                    "modelo": settings.gemini_image_model,
                })
            else:
                salida.imagenes.append({**base, "exito": False, "error": t("error.imagen_no_recibida", lang)})
        except Exception as exc:  # un fallo en una imagen no debe tumbar las demás
            logger.error("Error generando imagen %s: %s", idx, exc)
            salida.imagenes.append({**base, "exito": False, "error": str(exc)})

    return salida
