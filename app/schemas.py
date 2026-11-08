"""Modelos Pydantic de entrada/salida de la API."""
from typing import Optional

from pydantic import BaseModel, Field

IDIOMA_DESC = "Idioma de la salida: 'es' o 'en'. Si se omite, se usa Accept-Language o el idioma por defecto."


class AdaptarEntrada(BaseModel):
    enunciado: str = Field(..., max_length=15000, description="Enunciado original de la actividad")
    nivel: Optional[str] = Field(default="secundaria", description="Nivel educativo (primaria, secundaria, bachillerato, fp, universidad)")
    max_palabras: Optional[int] = Field(default=350, ge=50, le=2000, description="Límite aproximado de palabras")
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC)


class ImagenContextoEntrada(BaseModel):
    enunciado: str = Field(..., max_length=20000)
    num_imagenes: Optional[int] = Field(default=1, ge=1, le=3, description="Número de imágenes (1-3)")
    estilo: Optional[str] = Field(default="educativo", description="educativo, ilustrativo, realista, esquematico")
    transformacion_id: Optional[int] = None
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC + " Si hay transformacion_id, se usa el de la transformación.")


class PictogramasEntrada(BaseModel):
    enunciado: str = Field(..., max_length=20000)
    transformacion_id: Optional[int] = None
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC + " Si hay transformacion_id, se usa el de la transformación.")


class GoogleTokenInput(BaseModel):
    token: str
    access_key: Optional[str] = Field(default=None, description="Clave de acceso (si el servidor la exige)")


class AccessKeyInput(BaseModel):
    access_key: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    is_admin: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
