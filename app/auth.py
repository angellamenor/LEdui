"""Autenticación: verificación de tokens de Google y emisión/validación de JWT propios."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.i18n import request_language, t
from app.models import User

logger = logging.getLogger(__name__)
security = HTTPBearer()

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        # No se devuelve el detalle de la excepción al cliente
        raise _unauthorized("Token inválido o caducado")


async def verify_google_token(token: str) -> dict:
    """Valida un ID token de Google y devuelve su contenido."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": token})
    except httpx.HTTPError as exc:
        logger.error("Error contactando con Google: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="No se pudo verificar el token con Google")

    if response.status_code != 200:
        raise _unauthorized("Token de Google inválido")

    info = response.json()
    if settings.google_client_id and info.get("aud") != settings.google_client_id:
        raise _unauthorized("El token no corresponde a esta aplicación")
    if str(info.get("email_verified")).lower() != "true":
        raise _unauthorized("Email no verificado")
    return info


def get_or_create_user(db: Session, google_info: dict) -> User:
    google_id = google_info["sub"]
    email = google_info["email"]

    user = db.query(User).filter(User.google_id == google_id).first()
    try:
        if user:
            user.name = google_info.get("name")
            user.picture = google_info.get("picture")
            user.email = email
        else:
            user = User(
                google_id=google_id,
                email=email,
                name=google_info.get("name"),
                picture=google_info.get("picture"),
                is_admin=False,
            )
            db.add(user)
            logger.info("Nuevo usuario registrado (id pendiente)")
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        logger.exception("Error guardando usuario")
        raise HTTPException(status_code=500, detail="Error al registrar el usuario")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise _unauthorized("Token inválido")

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("Usuario no encontrado")
    return user


def get_current_admin_user(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=t("error.no_admin", request_language(request)))
    return current_user


def make_first_user_admin(db: Session) -> User | None:
    """Convierte en admin al primer usuario si todavía no hay ninguno (ver scripts/hacer_admin.py)."""
    if db.query(User).filter(User.is_admin.is_(True)).first():
        return None
    first = db.query(User).order_by(User.id).first()
    if first:
        first.is_admin = True
        db.commit()
    return first
