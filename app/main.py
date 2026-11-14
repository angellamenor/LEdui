"""
LEdui API: adapts educational task statements to Inclusive Educational Reading.

Run locally:   uvicorn app.main:app --reload
API docs:      http://localhost:8000/docs
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
        description="LEdui API: adaptation of task statements to Inclusive Educational Reading (es/en).",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def no_stale_frontend(request, call_next):
        """
        Force the browser to revalidate the interface (HTML, JS, CSS, texts) on every
        load. Without this, after a deployment the browser could mix a new HTML file
        with old cached JavaScript and the page was left blank.
        Revalidation uses ETags, so unchanged files are not downloaded again.
        """
        response = await call_next(request)
        path = request.url.path
        if path in ("/", "/demo") or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    if settings.static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

    for module in (sistema, auth, adaptaciones, historial, admin):
        app.include_router(module.router)

    return app


app = create_app()
