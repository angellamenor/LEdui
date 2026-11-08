"""Panel de administración (requiere usuario con is_admin=True)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_admin_user
from app.database import get_db
from app.i18n import request_language, t
from app.models import GeneracionImagenes, GeneracionPictogramas, TransformacionEnunciado, User
from app.prompt_loader import prompts
from app.routers.historial import docx_response, image_response

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin_user)])


@router.get("/users")
async def listar_usuarios(db: Session = Depends(get_db)):
    conteos = dict(
        db.query(TransformacionEnunciado.user_id, func.count(TransformacionEnunciado.id))
        .group_by(TransformacionEnunciado.user_id).all()
    )
    users = [{
        "id": u.id, "email": u.email, "name": u.name, "picture": u.picture, "is_admin": bool(u.is_admin),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "total_transformaciones": conteos.get(u.id, 0),
    } for u in db.query(User).order_by(User.id).all()]
    return {"ok": True, "total": len(users), "users": users}


@router.get("/transformaciones")
async def listar_transformaciones(exito: Optional[bool] = None, idioma: Optional[str] = None,
                                  prompt_version: Optional[str] = None, limit: int = 100,
                                  db: Session = Depends(get_db)):
    query = db.query(TransformacionEnunciado)
    if exito is not None:
        query = query.filter(TransformacionEnunciado.exito.is_(exito))
    if idioma:
        query = query.filter(TransformacionEnunciado.idioma == idioma)
    if prompt_version:
        query = query.filter(TransformacionEnunciado.prompt_version == prompt_version)
    rows = query.order_by(TransformacionEnunciado.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    lista = [crud.resumen_transformacion(tr, truncar=100) for tr in rows]
    return {"ok": True, "total": len(lista), "transformaciones": lista}


@router.get("/transformaciones/{transformacion_id}")
async def detalle(transformacion_id: int, request: Request, db: Session = Depends(get_db)):
    trans = crud.obtener_transformacion(db, transformacion_id)
    if trans is None:
        raise HTTPException(status_code=404, detail=t("error.no_encontrada", request_language(request)))
    return crud.detalle_transformacion(trans)


@router.get("/transformaciones/{transformacion_id}/download-docx")
async def descargar(transformacion_id: int, request: Request, db: Session = Depends(get_db)):
    trans = crud.obtener_transformacion(db, transformacion_id)
    if trans is None:
        raise HTTPException(status_code=404, detail=t("error.no_encontrada", request_language(request)))
    return docx_response(trans)


@router.get("/pictogramas/{pictogramas_id}/imagen")
async def imagen_pictogramas(pictogramas_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(GeneracionPictogramas, pictogramas_id)
    return image_response(p.imagen_pictogramas if p else None, p.imagen_mime_type if p else None,
                          f"pictogramas_{pictogramas_id}.png", request_language(request))


@router.get("/imagenes/{imagen_id}/imagen")
async def imagen_contexto(imagen_id: int, request: Request, db: Session = Depends(get_db)):
    i = db.get(GeneracionImagenes, imagen_id)
    return image_response(i.imagen_data if i else None, i.imagen_mime_type if i else None,
                          f"contexto_{imagen_id}.png", request_language(request))


@router.get("/prompts")
async def prompts_activos():
    """Qué prompts se están usando, de dónde se han cargado y su huella."""
    return {"ok": True, "prompts": prompts.describe()}


@router.post("/prompts/reload")
async def recargar_prompts():
    """Vuelve a leer los prompts del disco/entorno sin reiniciar el servidor."""
    prompts.reload()
    return {"ok": True, "prompts": prompts.describe()}
