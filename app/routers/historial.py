"""User history and shared download endpoints (document and images)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_user
from app.database import get_db
from app.i18n import request_language, t
from app.models import GeneracionImagenes, GeneracionPictogramas, TransformacionEnunciado, User
from app.services.documento import generar_docx

router = APIRouter(prefix="/mi-historial", tags=["history"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_response(trans: TransformacionEnunciado) -> Response:
    prefix = (trans.user.email.split("@")[0] if trans.user and trans.user.email else "usuario")
    prefix = "".join(c for c in prefix if c.isalnum() or c in "._-") or "usuario"
    filename = f"transformacion_{trans.id}_{prefix}_LEdui.docx"
    return Response(content=generar_docx(trans), media_type=DOCX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def image_response(data: bytes | None, mime: str | None, filename: str, lang: str) -> Response:
    if not data:
        raise HTTPException(status_code=404, detail=t("error.imagen_no_encontrada", lang))
    return Response(content=data, media_type=mime or "image/png",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


def _own_or_404(db: Session, transformacion_id: int, user: User, lang: str) -> TransformacionEnunciado:
    trans = crud.obtener_transformacion(db, transformacion_id, user)
    if trans is None:
        raise HTTPException(status_code=404, detail=t("error.no_encontrada", lang))
    return trans


@router.get("")
async def mi_historial(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    transformaciones = (
        db.query(TransformacionEnunciado)
        .filter(TransformacionEnunciado.user_id == current_user.id)
        .order_by(TransformacionEnunciado.created_at.desc())
        .limit(50)
        .all()
    )
    lista = [crud.resumen_transformacion(tr) for tr in transformaciones]
    return {"ok": True, "total": len(lista), "transformaciones": lista}


@router.get("/{transformacion_id}")
async def mi_transformacion(transformacion_id: int, request: Request,
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trans = _own_or_404(db, transformacion_id, current_user, request_language(request))
    return crud.detalle_transformacion(trans)


@router.get("/{transformacion_id}/download-docx")
async def descargar_mi_transformacion(transformacion_id: int, request: Request,
                                      current_user: User = Depends(get_current_user),
                                      db: Session = Depends(get_db)):
    return docx_response(_own_or_404(db, transformacion_id, current_user, request_language(request)))


@router.get("/pictogramas/{pictogramas_id}/imagen")
async def mi_imagen_pictogramas(pictogramas_id: int, request: Request,
                                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lang = request_language(request)
    picto = db.get(GeneracionPictogramas, pictogramas_id)
    if picto is None or (not current_user.is_admin and picto.transformacion.user_id != current_user.id):
        raise HTTPException(status_code=404, detail=t("error.imagen_no_encontrada", lang))
    return image_response(picto.imagen_pictogramas, picto.imagen_mime_type, f"pictogramas_{pictogramas_id}.png", lang)


@router.get("/imagenes/{imagen_id}/imagen")
async def mi_imagen_contexto(imagen_id: int, request: Request,
                             current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lang = request_language(request)
    img = db.get(GeneracionImagenes, imagen_id)
    if img is None or (not current_user.is_admin and img.transformacion.user_id != current_user.id):
        raise HTTPException(status_code=404, detail=t("error.imagen_no_encontrada", lang))
    return image_response(img.imagen_data, img.imagen_mime_type, f"contexto_{imagen_id}.png", lang)
