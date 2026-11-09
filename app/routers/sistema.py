"""Frontend, salud y configuración pública."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings

router = APIRouter(tags=["sistema"])


def _frontend() -> FileResponse:
    settings = get_settings()
    path = settings.static_dir / settings.frontend_file
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Frontend no encontrado")
    return FileResponse(path)


@router.get("/", include_in_schema=False)
async def root():
    return _frontend()


@router.get("/demo", include_in_schema=False)
async def demo():
    return _frontend()


@router.get("/salud")
def salud():
    s = get_settings()
    return {
        "ok": True,
        "servicio": s.app_name,
        "version": s.app_version,
        "idiomas": list(s.supported_languages),
        "idioma_por_defecto": s.default_language,
    }


@router.get("/config/public")
def config_publica():
    """Configuración que necesita el frontend (nada secreto)."""
    s = get_settings()
    return {
        "idiomas": list(s.supported_languages),
        "idioma_por_defecto": s.default_language,
        "requiere_clave": s.requires_access_key,
        "google_client_id": s.google_client_id,
        "version": s.app_version,
    }
