"""Pydantic input/output models for the API."""
from typing import Optional

from pydantic import BaseModel, Field

IDIOMA_DESC = "Output language: 'es' or 'en'. If omitted, Accept-Language or the default language is used."


class AdaptarEntrada(BaseModel):
    enunciado: str = Field(..., max_length=15000, description="Original task statement")
    nivel: Optional[str] = Field(default="secundaria", description="Educational level (primaria, secundaria, bachillerato, fp, universidad)")
    max_palabras: Optional[int] = Field(default=350, ge=50, le=2000, description="Approximate word limit")
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC)


class ImagenContextoEntrada(BaseModel):
    enunciado: str = Field(..., max_length=20000)
    num_imagenes: Optional[int] = Field(default=1, ge=1, le=3, description="Number of images (1-3)")
    estilo: Optional[str] = Field(default="educativo", description="educativo, ilustrativo, realista, esquematico")
    transformacion_id: Optional[int] = None
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC + " If transformacion_id is given, the transformation's language is used.")


class PictogramasEntrada(BaseModel):
    enunciado: str = Field(..., max_length=20000)
    transformacion_id: Optional[int] = None
    idioma: Optional[str] = Field(default=None, description=IDIOMA_DESC + " If transformacion_id is given, the transformation's language is used.")


class GoogleTokenInput(BaseModel):
    token: str
    access_key: Optional[str] = Field(default=None, description="Access key (if the server requires one)")


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
