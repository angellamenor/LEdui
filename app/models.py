"""
Modelos de base de datos de LEdui.

User y las tres tablas especializadas de transformaciones. Respecto a la versión
anterior se añaden dos columnas nullable a transformaciones_enunciado:

- idioma: idioma en que se generó la adaptación ('es', 'en').
- prompt_version: huella de los prompts usados, para poder comparar experimentos.

Las tablas existentes se actualizan con la migración de Alembic 0002.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """Usuario autenticado con Google."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    picture = Column(String(500), nullable=True)
    google_id = Column(String(255), unique=True, index=True, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    transformaciones = relationship("TransformacionEnunciado", back_populates="user")


class TransformacionEnunciado(Base):
    """Adaptación completa de un enunciado a Lectura Educativa."""
    __tablename__ = "transformaciones_enunciado"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    enunciado_original = Column(Text, nullable=False)
    nivel = Column(String(50), nullable=True)
    max_palabras = Column(Integer, nullable=True)
    idioma = Column(String(10), nullable=True)
    prompt_version = Column(String(64), nullable=True)

    enunciado_adaptado = Column(Text, nullable=False)
    indicaciones_docentes = Column(Text, nullable=True)

    tokens_entrada = Column(Integer, nullable=True)
    tokens_salida = Column(Integer, nullable=True)
    duracion_ms = Column(Integer, nullable=True)

    exito = Column(Boolean, default=True)
    error_mensaje = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="transformaciones")
    pictogramas = relationship("GeneracionPictogramas", back_populates="transformacion", uselist=False)
    imagenes_contexto = relationship("GeneracionImagenes", back_populates="transformacion")


class GeneracionPictogramas(Base):
    """Set de pictogramas de una transformación (relación 1:1)."""
    __tablename__ = "generacion_pictogramas"

    id = Column(Integer, primary_key=True, index=True)
    transformacion_id = Column(Integer, ForeignKey("transformaciones_enunciado.id"),
                               nullable=False, unique=True, index=True)

    enunciado_entrada = Column(Text, nullable=False)
    imagen_pictogramas = Column(LargeBinary, nullable=True)
    imagen_mime_type = Column(String(50), default="image/png")
    explicacion_habilidades = Column(Text, nullable=True)
    pasos_json = Column(JSON, nullable=True)

    tokens_entrada = Column(Integer, nullable=True)
    tokens_salida = Column(Integer, nullable=True)
    duracion_ms = Column(Integer, nullable=True)

    exito = Column(Boolean, default=True)
    error_mensaje = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    transformacion = relationship("TransformacionEnunciado", back_populates="pictogramas")


class GeneracionImagenes(Base):
    """Imágenes de contexto de una transformación (relación 1:N)."""
    __tablename__ = "generacion_imagenes"

    id = Column(Integer, primary_key=True, index=True)
    transformacion_id = Column(Integer, ForeignKey("transformaciones_enunciado.id"),
                               nullable=False, index=True)

    imagen_data = Column(LargeBinary, nullable=True)
    imagen_mime_type = Column(String(50), default="image/png")
    texto_explicativo = Column(Text, nullable=True)
    orden = Column(Integer, default=1)
    prompt_generacion = Column(Text, nullable=True)
    duracion_ms = Column(Integer, nullable=True)

    exito = Column(Boolean, default=True)
    error_mensaje = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    transformacion = relationship("TransformacionEnunciado", back_populates="imagenes_contexto")
