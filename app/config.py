"""
Configuración centralizada de LEdui API.

Todo lo configurable se lee de variables de entorno (o de un fichero .env en
desarrollo). Ningún otro módulo debería llamar a os.environ directamente.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

_INSECURE_DEFAULT_SECRET = "dev-insecure-secret-change-me"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Variable %s=%r no es un entero; se usa %s", name, value, default)
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _database_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/lectura_educativa",
    )
    # Railway/Heroku usan postgres:// pero SQLAlchemy necesita postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    # --- Aplicación ---
    app_name: str = "LEdui API"
    app_version: str = "12.0.0"
    environment: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    static_dir: Path = field(default_factory=lambda: Path(os.environ.get("STATIC_DIR", BASE_DIR / "static")))
    frontend_file: str = field(default_factory=lambda: os.environ.get("FRONTEND_FILE", "LEdu_front.html"))

    # --- Idiomas ---
    supported_languages: tuple[str, ...] = ("es", "en")
    default_language: str = field(default_factory=lambda: os.environ.get("DEFAULT_LANGUAGE", "es"))

    # --- Base de datos ---
    database_url: str = field(default_factory=_database_url)
    db_echo: bool = field(default_factory=lambda: _env_bool("DB_ECHO"))

    # --- CORS ---
    cors_origins: list[str] = field(default_factory=lambda: _env_list(
        "CORS_ORIGINS",
        [
            "http://localhost:8080",
            "http://localhost:8000",
            "http://localhost:3000",
            "http://127.0.0.1:8080",
            "http://127.0.0.1:8000",
        ],
    ))

    # --- Autenticación ---
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", _INSECURE_DEFAULT_SECRET))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = field(default_factory=lambda: _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7))
    google_client_id: str | None = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID"))

    # Clave de acceso que se pide antes de entrar con Google. Se comprueba en el
    # servidor (POST /auth/google). Si no se define, no se pide clave.
    # ADMIN_ACCESS_KEY se sigue aceptando como clave válida por compatibilidad,
    # pero ya NO da permisos: el rol de admin sale de users.is_admin.
    valid_access_key: str | None = field(default_factory=lambda: os.environ.get("VALID_ACCESS_KEY") or None)
    admin_access_key: str | None = field(default_factory=lambda: os.environ.get("ADMIN_ACCESS_KEY") or None)

    # --- Proveedores de IA ---
    # Se acepta ANTHROPIC_API_KEY (nombre estándar) y MI_ANTHROPIC_KEY (nombre antiguo)
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MI_ANTHROPIC_KEY"))
    google_ai_api_key: str | None = field(default_factory=lambda: os.environ.get("GOOGLE_AI_API_KEY"))
    claude_model: str = field(default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"))
    gemini_image_model: str = field(default_factory=lambda: os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"))
    max_tokens_adaptacion: int = field(default_factory=lambda: _env_int("MAX_TOKENS_ADAPTACION", 5000))
    max_tokens_imagenes: int = field(default_factory=lambda: _env_int("MAX_TOKENS_IMAGENES", 1500))
    max_tokens_pictogramas: int = field(default_factory=lambda: _env_int("MAX_TOKENS_PICTOGRAMAS", 1500))

    # --- Prompts ---
    # Carpeta con los prompts. Permite apuntar a otra carpeta para experimentos
    # sin tocar el código: PROMPTS_DIR=/ruta/a/prompts_experimento_3
    prompts_dir: Path = field(default_factory=lambda: Path(os.environ.get("PROMPTS_DIR", BASE_DIR / "app" / "prompts")))
    # Si está activo, los prompts se releen del disco en cada petición (útil para afinar)
    prompts_hot_reload: bool = field(default_factory=lambda: _env_bool("PROMPTS_HOT_RELOAD"))

    # --- Servicios externos ---
    arasaac_api_url: str = field(default_factory=lambda: os.environ.get("ARASAAC_API_URL", "https://api.arasaac.org/api"))
    http_timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("HTTP_TIMEOUT_SECONDS", "60")))
    pictogram_font_path: str | None = field(default_factory=lambda: os.environ.get("PICTOGRAM_FONT_PATH"))

    @property
    def requires_access_key(self) -> bool:
        return bool(self.valid_access_key or self.admin_access_key)

    def is_valid_access_key(self, key: str | None) -> bool:
        if not self.requires_access_key:
            return True
        if not key:
            return False
        return any(hmac.compare_digest(key.encode(), k.encode()) for k in (self.valid_access_key, self.admin_access_key) if k)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def normalize_language(self, lang: str | None) -> str:
        """Devuelve un código de idioma soportado ('es', 'en') o el idioma por defecto."""
        if not lang:
            return self.default_language
        code = lang.strip().lower().replace("_", "-").split("-")[0]
        return code if code in self.supported_languages else self.default_language

    def validate(self) -> None:
        """Avisa (o falla en producción) ante configuraciones peligrosas."""
        if self.secret_key == _INSECURE_DEFAULT_SECRET:
            msg = "SECRET_KEY no está definida: se usa una clave insegura de desarrollo."
            if self.is_production:
                raise RuntimeError(msg + " Define SECRET_KEY en producción.")
            logger.warning(msg)
        if not self.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY no definida: los endpoints de IA devolverán error.")
        if not self.google_ai_api_key:
            logger.warning("GOOGLE_AI_API_KEY no definida: no se podrán generar imágenes de contexto.")
        if not self.google_client_id:
            msg = "GOOGLE_CLIENT_ID no definida: no se comprobará la audiencia de los tokens de Google."
            if self.is_production:
                raise RuntimeError(msg + " Defínela en producción.")
            logger.warning(msg)
        if self.default_language not in self.supported_languages:
            raise RuntimeError(f"DEFAULT_LANGUAGE debe ser uno de {self.supported_languages}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
