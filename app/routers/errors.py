"""Maps internal errors to localised HTTP responses."""
import logging

from fastapi import HTTPException

from app.i18n import t
from app.prompt_loader import PromptNotFoundError
from app.services.llm import AIResponseError, AIServiceError, AIServiceNotConfigured

logger = logging.getLogger(__name__)


def to_http_error(exc: Exception, lang: str, servicio: str = "anthropic") -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AIServiceNotConfigured):
        key = "error.falta_gemini" if servicio == "gemini" else "error.falta_anthropic"
        return HTTPException(status_code=503, detail=t(key, lang))
    if isinstance(exc, AIServiceError):
        return HTTPException(status_code=502, detail=t("error.ia_servicio", lang))
    if isinstance(exc, AIResponseError):
        return HTTPException(status_code=502, detail=t("error.ia_respuesta", lang))
    if isinstance(exc, PromptNotFoundError):
        logger.error("Prompt not found: %s", exc)
        return HTTPException(status_code=500, detail=t("error.interno", lang))
    logger.exception("Unexpected error")
    return HTTPException(status_code=500, detail=t("error.interno", lang))


def describe_error(exc: Exception) -> str:
    """Message stored in the database (for the admin panel)."""
    return f"{type(exc).__name__}: {exc}"[:2000]
