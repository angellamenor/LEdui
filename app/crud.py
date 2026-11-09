"""Acceso a datos: guardado y lectura de transformaciones, pictogramas e imágenes."""
from __future__ import annotations

import html
import logging
import re
from datetime import timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GeneracionImagenes, GeneracionPictogramas, TransformacionEnunciado, User

logger = logging.getLogger(__name__)


def _save(db: Session, obj):
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    except Exception:
        db.rollback()
        logger.exception("Error guardando %s", type(obj).__name__)
        return None


def guardar_transformacion(db: Session, **fields) -> TransformacionEnunciado | None:
    fields.setdefault("enunciado_adaptado", "")
    return _save(db, TransformacionEnunciado(**fields))


def obtener_transformacion(db: Session, transformacion_id: int, user: User | None = None) -> TransformacionEnunciado | None:
    """Devuelve la transformación; si se pasa `user` (no admin), solo si es suya."""
    query = db.query(TransformacionEnunciado).filter(TransformacionEnunciado.id == transformacion_id)
    if user is not None and not user.is_admin:
        query = query.filter(TransformacionEnunciado.user_id == user.id)
    return query.first()


def guardar_pictogramas(db: Session, transformacion_id: int, **fields) -> GeneracionPictogramas | None:
    """Crea o sustituye el set de pictogramas (la relación es 1:1)."""
    existente = db.query(GeneracionPictogramas).filter(
        GeneracionPictogramas.transformacion_id == transformacion_id
    ).first()
    if existente:
        for key, value in fields.items():
            setattr(existente, key, value)
        return _save(db, existente)
    return _save(db, GeneracionPictogramas(transformacion_id=transformacion_id, **fields))


def guardar_imagenes(db: Session, transformacion_id: int, imagenes: list[dict[str, Any]],
                     duracion_ms: int | None = None, exito: bool = True,
                     error_mensaje: str | None = None) -> list[GeneracionImagenes]:
    """Guarda las imágenes de contexto. Si no hay imágenes y hubo error, se guarda un registro de error."""
    try:
        objetos = []
        if not imagenes and not exito:
            objetos.append(GeneracionImagenes(transformacion_id=transformacion_id, orden=1,
                                              exito=False, error_mensaje=error_mensaje,
                                              duracion_ms=duracion_ms))
        for i, img in enumerate(imagenes, start=1):
            objetos.append(GeneracionImagenes(
                transformacion_id=transformacion_id,
                imagen_data=img.get("imagen"),
                imagen_mime_type=img.get("mime_type", "image/png"),
                texto_explicativo=img.get("texto"),
                orden=i,
                prompt_generacion=img.get("prompt"),
                duracion_ms=duracion_ms if i == 1 else None,
                exito=exito,
                error_mensaje=error_mensaje if i == 1 else None,
            ))
        db.add_all(objetos)
        db.commit()
        return objetos
    except Exception:
        db.rollback()
        logger.exception("Error guardando imágenes de contexto")
        return []


def _iso(dt) -> str | None:
    """ISO 8601 con zona horaria. SQLite devuelve fechas sin zona: se asume UTC."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def titulo_adaptacion(enunciado_adaptado: str | None) -> str | None:
    """Texto del primer <h1> de la adaptación (el título motivador), sin etiquetas."""
    if not enunciado_adaptado:
        return None
    match = _H1.search(enunciado_adaptado)
    if not match:
        return None
    titulo = html.unescape(_TAGS.sub("", match.group(1))).strip()
    return titulo[:200] or None


def resumen_transformacion(trans: TransformacionEnunciado, truncar: int = 80) -> dict:
    texto = trans.enunciado_original or ""
    if len(texto) > truncar:
        texto = texto[:truncar] + "..."
    return {
        "id": trans.id,
        "user_id": trans.user_id,
        "user_email": trans.user.email if trans.user else None,
        "enunciado_original": texto,
        "titulo": titulo_adaptacion(trans.enunciado_adaptado),
        "nivel": trans.nivel,
        "idioma": trans.idioma,
        "prompt_version": trans.prompt_version,
        "tokens_entrada": trans.tokens_entrada,
        "tokens_salida": trans.tokens_salida,
        "duracion_ms": trans.duracion_ms,
        "exito": trans.exito,
        "tiene_pictogramas": trans.pictogramas is not None,
        "num_imagenes_contexto": len(trans.imagenes_contexto or []),
        "created_at": _iso(trans.created_at),
    }


def detalle_transformacion(trans: TransformacionEnunciado) -> dict:
    resultado = {
        "id": trans.id,
        "user_id": trans.user_id,
        "user_email": trans.user.email if trans.user else None,
        "enunciado_original": trans.enunciado_original,
        "nivel": trans.nivel,
        "max_palabras": trans.max_palabras,
        "idioma": trans.idioma,
        "prompt_version": trans.prompt_version,
        "titulo": titulo_adaptacion(trans.enunciado_adaptado),
        "enunciado_adaptado": trans.enunciado_adaptado,
        "indicaciones_docentes": trans.indicaciones_docentes,
        "tokens_entrada": trans.tokens_entrada,
        "tokens_salida": trans.tokens_salida,
        "duracion_ms": trans.duracion_ms,
        "exito": trans.exito,
        "error_mensaje": trans.error_mensaje,
        "created_at": _iso(trans.created_at),
        "pictogramas": None,
        "imagenes_contexto": [],
    }
    if trans.pictogramas:
        p = trans.pictogramas
        resultado["pictogramas"] = {
            "id": p.id,
            "explicacion_habilidades": p.explicacion_habilidades,
            "pasos": p.pasos_json,
            "tiene_imagen": p.imagen_pictogramas is not None,
            "tokens_entrada": p.tokens_entrada,
            "tokens_salida": p.tokens_salida,
            "duracion_ms": p.duracion_ms,
            "exito": p.exito,
            "error_mensaje": p.error_mensaje,
            "created_at": _iso(p.created_at),
        }
    for img in sorted(trans.imagenes_contexto or [], key=lambda x: x.orden or 0):
        resultado["imagenes_contexto"].append({
            "id": img.id,
            "orden": img.orden,
            "texto_explicativo": img.texto_explicativo,
            "prompt": img.prompt_generacion,
            "tiene_imagen": img.imagen_data is not None,
            "mime_type": img.imagen_mime_type,
            "exito": img.exito,
            "error_mensaje": img.error_mensaje,
            "created_at": _iso(img.created_at),
        })
    return resultado


def estadisticas_usuario(db: Session, user: User) -> dict:
    base = db.query(TransformacionEnunciado).filter(TransformacionEnunciado.user_id == user.id)
    total = base.count()
    exitosas = base.filter(TransformacionEnunciado.exito.is_(True)).count()
    tokens = db.query(
        func.coalesce(func.sum(TransformacionEnunciado.tokens_entrada), 0)
        + func.coalesce(func.sum(TransformacionEnunciado.tokens_salida), 0)
    ).filter(TransformacionEnunciado.user_id == user.id).scalar() or 0

    def _contar(model):
        return db.query(model).join(TransformacionEnunciado).filter(
            TransformacionEnunciado.user_id == user.id, model.exito.is_(True)
        ).count()

    return {
        "total_transformaciones": total,
        "transformaciones_exitosas": exitosas,
        "tokens_usados": int(tokens),
        "pictogramas_generados": _contar(GeneracionPictogramas),
        "imagenes_generadas": _contar(GeneracionImagenes),
        "usuario": {
            "email": user.email,
            "name": user.name,
            "member_since": _iso(user.created_at),
        },
    }
