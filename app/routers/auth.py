"""Endpoints de autenticación."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import crud
from app.auth import create_access_token, get_current_user, get_or_create_user, verify_google_token
from app.database import get_db
from app.i18n import request_language, t
from app.models import User
from app.config import get_settings
from app.schemas import AccessKeyInput, GoogleTokenInput, TokenResponse, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["autenticación"])


def _user_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name,
            "picture": user.picture, "is_admin": bool(user.is_admin)}


@router.post("/google", response_model=TokenResponse)
async def login_with_google(data: GoogleTokenInput, request: Request, db: Session = Depends(get_db)):
    """Recibe el ID token de Google (y la clave de acceso) y devuelve un JWT propio de la API."""
    lang = request_language(request)
    if not get_settings().is_valid_access_key(data.access_key):
        raise HTTPException(status_code=403, detail=t("error.clave_acceso", lang))
    try:
        info = await verify_google_token(data.token)
        user = get_or_create_user(db, info)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en autenticación")
        raise HTTPException(status_code=500, detail=t("error.auth", lang))
    logger.info("Usuario autenticado: id=%s", user.id)
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": _user_dict(user)}


@router.post("/check-key")
async def check_access_key(data: AccessKeyInput):
    """Permite a la interfaz validar la clave antes de mostrar el botón de Google."""
    return {"valida": get_settings().is_valid_access_key(data.access_key)}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return _user_dict(current_user)


@router.get("/stats")
async def stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return crud.estadisticas_usuario(db, current_user)
