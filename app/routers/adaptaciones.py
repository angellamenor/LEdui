"""Endpoints de IA: adaptación del enunciado, pictogramas e imágenes de contexto."""
import base64
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_user
from app.database import get_db
from app.i18n import normalize_nivel, resolve_language, t
from app.models import User
from app.routers.errors import describe_error, to_http_error
from app.schemas import AdaptarEntrada, ImagenContextoEntrada, PictogramasEntrada
from app.services.adaptacion import adaptar_enunciado
from app.services.imagenes import generar_imagenes
from app.services.pictogramas import explicacion_habilidades, generar_pictogramas

logger = logging.getLogger(__name__)
router = APIRouter(tags=["adaptación"])


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _resolver_transformacion(db: Session, transformacion_id: int | None, user: User, lang: str):
    """Comprueba que la transformación existe y es del usuario. Devuelve (trans, idioma)."""
    if transformacion_id is None:
        return None, lang
    trans = crud.obtener_transformacion(db, transformacion_id, user)
    if trans is None:
        raise HTTPException(status_code=404, detail=t("error.no_encontrada", lang))
    # La continuación de una transformación usa siempre su mismo idioma
    return trans, (trans.idioma or lang)


@router.post("/adaptar_enunciado_ledu")
async def adaptar_enunciado_ledu(
    data: AdaptarEntrada,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adapta un enunciado a Lectura Educativa (HTML con estructura fija) en el idioma pedido."""
    lang = resolve_language(data.idioma, request)
    if not data.enunciado or len(data.enunciado.strip()) < 5:
        raise HTTPException(status_code=400, detail=t("error.enunciado_corto", lang))

    nivel = normalize_nivel(data.nivel)
    start = time.perf_counter()
    try:
        resultado = await adaptar_enunciado(data.enunciado, nivel, data.max_palabras, lang)
    except Exception as exc:
        crud.guardar_transformacion(
            db, user_id=current_user.id, enunciado_original=data.enunciado, nivel=nivel,
            max_palabras=data.max_palabras, idioma=lang, exito=False, error_mensaje=describe_error(exc),
            duracion_ms=_ms_since(start),
        )
        raise to_http_error(exc, lang)

    trans = crud.guardar_transformacion(
        db,
        user_id=current_user.id,
        enunciado_original=data.enunciado,
        nivel=nivel,
        max_palabras=data.max_palabras,
        idioma=lang,
        prompt_version=resultado.prompt_version,
        enunciado_adaptado=resultado.texto_adaptado,
        indicaciones_docentes=resultado.explicacion,
        tokens_entrada=resultado.input_tokens,
        tokens_salida=resultado.output_tokens,
        duracion_ms=_ms_since(start),
        exito=True,
    )
    return {
        "ok": True,
        "transformacion_id": trans.id if trans else None,
        "idioma": lang,
        "prompt_version": resultado.prompt_version,
        "modelo": resultado.model,
        "tokens_entrada": resultado.input_tokens,
        "tokens_salida": resultado.output_tokens,
        "enunciado_adaptado": resultado.texto_adaptado,
        "indicaciones_docentes": resultado.explicacion,
    }


@router.post("/generar_pictogramas")
async def generar_pictogramas_endpoint(
    data: PictogramasEntrada,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Identifica las acciones de la tarea y las representa con pictogramas de ARASAAC."""
    lang = resolve_language(data.idioma, request)
    trans, lang = _resolver_transformacion(db, data.transformacion_id, current_user, lang)
    if not data.enunciado or len(data.enunciado.strip()) < 20:
        raise HTTPException(status_code=400, detail=t("error.enunciado_corto", lang))

    start = time.perf_counter()
    try:
        res = await generar_pictogramas(data.enunciado, lang)
    except Exception as exc:
        if trans:
            crud.guardar_pictogramas(db, trans.id, enunciado_entrada=data.enunciado, imagen_pictogramas=None,
                                     explicacion_habilidades="", pasos_json=[], exito=False,
                                     error_mensaje=describe_error(exc), duracion_ms=_ms_since(start))
        raise to_http_error(exc, lang)

    imagen_b64 = base64.b64encode(res.imagen_compuesta).decode() if res.imagen_compuesta else None
    if trans:
        # En la BD no se guardan las miniaturas en base64 de cada pictograma
        pasos = [{k: v for k, v in p.items() if k != "imagen_base64"} for p in res.pictogramas]
        crud.guardar_pictogramas(
            db, trans.id,
            enunciado_entrada=data.enunciado,
            imagen_pictogramas=res.imagen_compuesta,
            imagen_mime_type="image/png",
            explicacion_habilidades=explicacion_habilidades(res.pictogramas, lang),
            pasos_json=pasos,
            tokens_entrada=res.input_tokens,
            tokens_salida=res.output_tokens,
            duracion_ms=_ms_since(start),
            exito=True,
            error_mensaje=None,
        )
    return {
        "ok": True,
        "transformacion_id": data.transformacion_id,
        "idioma": lang,
        "enunciado_original": data.enunciado,
        "pictogramas": res.pictogramas,
        "num_pictogramas_encontrados": res.encontrados,
        "num_pictogramas_totales": len(res.pictogramas),
        "imagen_compuesta_base64": imagen_b64,
        "tokens_analisis": {"entrada": res.input_tokens, "salida": res.output_tokens},
    }


@router.post("/generar_imagenes_contexto")
async def generar_imagenes_contexto(
    data: ImagenContextoEntrada,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Genera imágenes de contexto (16:9) con valor pedagógico usando Claude + Gemini."""
    lang = resolve_language(data.idioma, request)
    trans, lang = _resolver_transformacion(db, data.transformacion_id, current_user, lang)
    if not data.enunciado or len(" ".join(data.enunciado.split())) < 10:
        raise HTTPException(status_code=400, detail=t("error.enunciado_corto", lang))

    start = time.perf_counter()
    try:
        res = await generar_imagenes(data.enunciado, data.num_imagenes or 1, data.estilo, lang)
    except Exception as exc:
        if trans:
            crud.guardar_imagenes(db, trans.id, [], exito=False, error_mensaje=describe_error(exc),
                                  duracion_ms=_ms_since(start))
        raise to_http_error(exc, lang, servicio="gemini")

    if trans:
        para_bd = [
            {"imagen": base64.b64decode(img["imagen_base64"]), "mime_type": "image/png",
             "texto": img.get("justificacion", ""), "prompt": img.get("prompt_usado", "")}
            for img in res.imagenes if img.get("exito") and img.get("imagen_base64")
        ]
        if para_bd:
            crud.guardar_imagenes(db, trans.id, para_bd, duracion_ms=_ms_since(start))

    return {
        "ok": True,
        "transformacion_id": data.transformacion_id,
        "idioma": lang,
        "enunciado_original": " ".join(data.enunciado.split()),
        "num_imagenes_solicitadas": data.num_imagenes,
        "num_imagenes_generadas": sum(1 for i in res.imagenes if i.get("exito")),
        "imagenes": res.imagenes,
        "tokens_analisis": {"entrada": res.input_tokens, "salida": res.output_tokens},
    }
