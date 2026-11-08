"""Pictogramas: Claude identifica acciones, ARASAAC aporta los pictogramas y Pillow los compone."""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.i18n import language_name, t
from app.prompt_loader import prompts
from app.services.llm import AIResponseError, complete_json

logger = logging.getLogger(__name__)

PICTO_SIZE = 200
PADDING = 20
FONT_SIZE = 24
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


@dataclass
class ResultadoPictogramas:
    pictogramas: list[dict] = field(default_factory=list)
    imagen_compuesta: bytes | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def encontrados(self) -> int:
        return sum(1 for p in self.pictogramas if p.get("exito"))


def _load_font():
    settings = get_settings()
    paths = ([settings.pictogram_font_path] if settings.pictogram_font_path else []) + list(_FONT_CANDIDATES)
    for path in paths:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=FONT_SIZE)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def componer_imagen(items: list[tuple[Image.Image, str]]) -> bytes:
    """Coloca los pictogramas en fila con su etiqueta debajo y devuelve un PNG."""
    font = _load_font()
    text_height = FONT_SIZE + 16
    width = len(items) * PICTO_SIZE + (len(items) + 1) * PADDING
    height = PICTO_SIZE + text_height + PADDING * 2
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    x = PADDING
    for img, label in items:
        canvas.paste(img.resize((PICTO_SIZE, PICTO_SIZE), Image.Resampling.LANCZOS), (x, PADDING))
        bbox = draw.textbbox((0, 0), label, font=font)
        text_x = x + (PICTO_SIZE - (bbox[2] - bbox[0])) // 2
        draw.text((text_x, PADDING + PICTO_SIZE + 10), label, fill="black", font=font)
        x += PICTO_SIZE + PADDING

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _to_rgb(content: bytes) -> Image.Image:
    img = Image.open(BytesIO(content))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


async def _buscar_pictograma(client: httpx.AsyncClient, accion: dict, lang: str) -> dict:
    settings = get_settings()
    keyword = str(accion.get("keyword_arasaac", "")).strip()
    simplificada = accion.get("accion_simplificada", "") or keyword
    info = {
        "accion_original": accion.get("accion_original", ""),
        "accion_simplificada": simplificada,
        "accion_en_ingles": accion.get("accion_en_ingles") or simplificada,
        "etiqueta": accion.get("etiqueta") or simplificada,
        "keyword": keyword,
        "idioma": lang,
        "explicacion_alumno": accion.get("explicacion_alumno") or t("fallback.vas_a", lang, accion=simplificada),
        "exito": False,
    }
    try:
        search = await client.get(f"{settings.arasaac_api_url}/pictograms/{lang}/search/{quote(keyword)}")
        if search.status_code != 200 or not search.json():
            info["error"] = t("error.picto_no_encontrado", lang, keyword=keyword)
            return info
        picto_id = search.json()[0].get("_id")
        image = await client.get(f"{settings.arasaac_api_url}/pictograms/{picto_id}")
        image.raise_for_status()
        img = await asyncio.to_thread(_to_rgb, image.content)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        info.update({
            "id": picto_id,
            "url": f"{settings.arasaac_api_url}/pictograms/{picto_id}",
            "imagen_base64": base64.b64encode(buffer.getvalue()).decode(),
            "exito": True,
            "_img": img,
        })
    except Exception as exc:
        logger.warning("ARASAAC falló para '%s': %s", keyword, exc)
        info["error"] = str(exc)
    return info


async def generar_pictogramas(enunciado: str, lang: str) -> ResultadoPictogramas:
    settings = get_settings()
    variables = {
        "enunciado": enunciado.strip(),
        "idioma": lang,
        "idioma_nombre": language_name(lang),
        "idioma_nombre_en": language_name(lang, in_english=True),
    }
    system = prompts.render("pictogramas_system", lang, **variables)
    user = prompts.render("pictogramas_user", lang, **variables)
    result = await complete_json(system, user, settings.max_tokens_pictogramas)

    acciones = result.data.get("acciones") or []
    if not isinstance(acciones, list) or not acciones:
        raise AIResponseError(t("error.sin_acciones", lang))

    # Quitar duplicados por keyword manteniendo el orden
    vistas, unicas = set(), []
    for accion in acciones:
        key = str(accion.get("keyword_arasaac", "")).strip().lower()
        if key and key not in vistas:
            vistas.add(key)
            unicas.append(accion)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        infos = await asyncio.gather(*(_buscar_pictograma(client, a, lang) for a in unicas[:6]))

    salida = ResultadoPictogramas(input_tokens=result.input_tokens, output_tokens=result.output_tokens)
    composicion = []
    for info in infos:
        img = info.pop("_img", None)
        if img is not None:
            composicion.append((img, info["etiqueta"]))
        salida.pictogramas.append(info)

    if composicion:
        salida.imagen_compuesta = await asyncio.to_thread(componer_imagen, composicion)
    return salida


def explicacion_habilidades(pictogramas: list[dict], lang: str) -> str:
    return "\n\n".join(
        t("picto.accion", lang, n=i, accion=p.get("etiqueta", ""), explicacion=p.get("explicacion_alumno", ""))
        for i, p in enumerate((p for p in pictogramas if p.get("exito")), start=1)
    )
