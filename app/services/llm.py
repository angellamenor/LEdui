"""Cliente de Claude y utilidades para extraer el JSON de sus respuestas."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from anthropic import APIError, AsyncAnthropic

from app.config import get_settings

logger = logging.getLogger(__name__)


class AIServiceNotConfigured(RuntimeError):
    """Falta la API key del proveedor."""


class AIServiceError(RuntimeError):
    """El proveedor devolvió un error (red, cuota, 5xx...)."""


class AIResponseError(ValueError):
    """La respuesta llegó, pero no tiene el formato esperado."""


@dataclass
class LLMResult:
    data: dict
    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int


@lru_cache
def get_anthropic_client() -> AsyncAnthropic | None:
    settings = get_settings()
    return AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None


def extract_json_object(text: str) -> dict:
    """
    Extrae el primer objeto JSON de un texto, tolerando bloques ```json y texto alrededor.
    Cuenta llaves fuera de las cadenas para encontrar el cierre correcto.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1:] if first_newline != -1 else cleaned[3:]
        if "```" in cleaned:
            cleaned = cleaned[: cleaned.rfind("```")]
    cleaned = cleaned.strip()

    start = cleaned.find("{")
    if start == -1:
        raise AIResponseError("La respuesta no contiene un objeto JSON")

    depth, in_string, escaped = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(cleaned[start: i + 1])
                except json.JSONDecodeError as exc:
                    raise AIResponseError(f"JSON inválido: {exc}") from exc
                if not isinstance(data, dict):
                    raise AIResponseError("El JSON no es un objeto")
                return data
    raise AIResponseError("JSON incompleto (¿respuesta cortada por max_tokens?)")


async def complete_json(system: str, user: str, max_tokens: int) -> LLMResult:
    client = get_anthropic_client()
    if client is None:
        raise AIServiceNotConfigured("ANTHROPIC_API_KEY no configurada")

    settings = get_settings()
    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except APIError as exc:
        logger.error("Error de la API de Anthropic: %s", exc)
        raise AIServiceError(str(exc)) from exc

    text = "".join(getattr(part, "text", "") for part in response.content or []).strip()
    if not text:
        raise AIResponseError("Respuesta vacía del modelo")
    if response.stop_reason == "max_tokens":
        logger.warning("La respuesta de Claude se cortó por max_tokens=%s", max_tokens)

    return LLMResult(
        data=extract_json_object(text),
        raw_text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
