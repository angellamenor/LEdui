"""
LEdui API — adaptación de enunciados educativos a Lectura Educativa inclusiva.

Arranque local:   uvicorn app.main:app --reload
Documentación:    http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import adaptaciones, admin, auth, historial, sistema

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
settings.validate()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API de LEdui: adaptación de enunciados a Lectura Educativa inclusiva (es/en).",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
        expose_headers=["Content-Disposition"],
    )

    if settings.static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

    for module in (sistema, auth, adaptaciones, historial, admin):
        app.include_router(module.router)

    return app


app = create_app()
