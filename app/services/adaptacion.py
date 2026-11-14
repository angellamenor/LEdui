"""Adaptation of task statements to Educational Reading with Claude."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.i18n import language_name, nivel_label, t
from app.prompt_loader import prompts
from app.services.llm import AIResponseError, complete_json

PROMPTS_USADOS = ["adaptar_system", "adaptar_user"]


@dataclass
class Adaptacion:
    texto_adaptado: str
    explicacion: str
    model: str
    input_tokens: int
    output_tokens: int
    prompt_version: str


async def adaptar_enunciado(enunciado: str, nivel: str | None, max_palabras: int | None, lang: str) -> Adaptacion:
    settings = get_settings()
    variables = {
        "enunciado": enunciado.strip(),
        "nivel": nivel_label(nivel, lang),
        "max_palabras": max_palabras or 350,
        "idioma": lang,
        "idioma_nombre": language_name(lang),
        "idioma_nombre_en": language_name(lang, in_english=True),
    }
    system = prompts.render("adaptar_system", lang, **variables)
    user = prompts.render("adaptar_user", lang, **variables)

    result = await complete_json(system, user, settings.max_tokens_adaptacion)

    texto = str(result.data.get("texto_adaptado") or "").strip()
    explicacion = str(result.data.get("explicacion_cambios") or "").strip()
    if not texto:
        raise AIResponseError("The response does not include 'texto_adaptado'")
    if texto.startswith("{"):
        raise AIResponseError("'texto_adaptado' contains JSON instead of HTML")

    return Adaptacion(
        texto_adaptado=texto,
        explicacion=explicacion or t("fallback.explicacion", lang),
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        prompt_version=prompts.version(PROMPTS_USADOS, lang),
    )
