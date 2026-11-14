import base64
from io import BytesIO

import httpx
import pytest
from docx import Document
from PIL import Image

from app.models import TransformacionEnunciado
from app.services import adaptacion, imagenes, pictogramas
from app.services.llm import AIServiceError, LLMResult
from tests.conftest import auth_headers

HTML = "<h1>Título</h1><h2>¿Qué vas a aprender?</h2><p>Hola <strong>mundo</strong></p><ol><li>Paso</li></ol>"


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGBA", (50, 50), (255, 0, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


class FakeLLM:
    """Replaces complete_json and records the prompts it receives."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    async def __call__(self, system, user, max_tokens):
        self.calls.append({"system": system, "user": user})
        return LLMResult(data=self.data, raw_text="", model="claude-test", input_tokens=10, output_tokens=20)


@pytest.fixture
def fake_adaptacion(monkeypatch):
    fake = FakeLLM({"texto_adaptado": HTML, "explicacion_cambios": "**Regla 1 (Claridad) - Nivel 1**: ok"})
    monkeypatch.setattr(adaptacion, "complete_json", fake)
    return fake


def test_health_and_config(client):
    assert client.get("/salud").json()["idiomas"] == ["es", "en"]
    cfg = client.get("/config/public").json()
    assert cfg["requiere_clave"] is True
    assert "valid_key" not in cfg and "admin_key" not in str(cfg)


def test_check_key(client):
    assert client.post("/auth/check-key", json={"access_key": "clave-buena"}).json() == {"valida": True}
    assert client.post("/auth/check-key", json={"access_key": "mala"}).json() == {"valida": False}


def test_login_without_key_is_rejected_by_server(client, monkeypatch):
    called = False

    async def fake_verify(token):
        nonlocal called
        called = True
        return {"sub": "1", "email": "x@y.z"}

    monkeypatch.setattr("app.routers.auth.verify_google_token", fake_verify)
    r = client.post("/auth/google", json={"token": "t", "access_key": "mala"}, headers={"Accept-Language": "en"})
    assert r.status_code == 403 and "access key" in r.json()["detail"]
    assert not called
    r = client.post("/auth/google", json={"token": "t", "access_key": "clave-buena"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "x@y.z"


@pytest.mark.parametrize("idioma,marker", [("es", "en español"), ("en", "in English")])
def test_adapt_uses_language_in_prompt_and_stores_it(client, user, db, fake_adaptacion, idioma, marker):
    r = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user),
                    json={"enunciado": "Investiga la revolución industrial", "nivel": "fp", "idioma": idioma})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idioma"] == idioma and body["tokens_entrada"] == 10
    call = fake_adaptacion.calls[0]
    assert marker in call["system"]
    assert ("Formación Profesional" if idioma == "es" else "Vocational training") in call["user"]

    trans = db.get(TransformacionEnunciado, body["transformacion_id"])
    assert trans.idioma == idioma and trans.nivel == "fp"
    assert trans.prompt_version == body["prompt_version"]


def test_adapt_takes_language_from_accept_language(client, user, fake_adaptacion):
    r = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user, "en-GB"), json={"enunciado": "Do the task"})
    assert r.json()["idioma"] == "en"


def test_adaptation_language_independent_of_interface(client, user, fake_adaptacion):
    """Spanish interface (Accept-Language) but adaptation requested in English."""
    r = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user, "es-ES"),
                    json={"enunciado": "Investiga la Revolución Industrial", "idioma": "en"})
    assert r.json()["idioma"] == "en"
    assert "in English" in fake_adaptacion.calls[0]["system"]


def test_adapt_error_is_stored_and_translated(client, user, db, monkeypatch):
    async def boom(*a, **k):
        raise AIServiceError("caído")

    monkeypatch.setattr(adaptacion, "complete_json", boom)
    r = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user),
                    json={"enunciado": "Una tarea", "idioma": "en"})
    assert r.status_code == 502 and "AI service" in r.json()["detail"]
    trans = db.query(TransformacionEnunciado).one()
    assert trans.exito is False and "caído" in trans.error_mensaje


def test_short_statement_message_in_language(client, user):
    r = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user), json={"enunciado": "a", "idioma": "en"})
    assert r.status_code == 400 and r.json()["detail"] == "The task statement is too short."


def _arasaac_transport(seen_urls):
    def handler(request: httpx.Request):
        seen_urls.append(str(request.url))
        if "/search/" in request.url.path:
            return httpx.Response(200, json=[{"_id": 123}])
        return httpx.Response(200, content=_png())
    return httpx.MockTransport(handler)


def test_english_pictograms_query_arasaac_in_english(client, user, db, fake_adaptacion, monkeypatch):
    trans_id = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user),
                           json={"enunciado": "Research the topic", "idioma": "en"}).json()["transformacion_id"]

    fake = FakeLLM({"acciones": [
        {"accion_original": "research", "accion_simplificada": "search", "keyword_arasaac": "search",
         "etiqueta": "Search", "explicacion_alumno": "You are going to search..."},
        {"accion_original": "look up", "accion_simplificada": "search", "keyword_arasaac": "Search"},  # duplicate
    ]})
    monkeypatch.setattr(pictogramas, "complete_json", fake)
    seen = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(pictogramas.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=_arasaac_transport(seen), **kw))

    # No 'idioma' in the request: inherited from the transformation (en)
    r = client.post("/generar_pictogramas", headers=auth_headers(user),
                    json={"enunciado": "<p>Research the Industrial Revolution online</p>", "transformacion_id": trans_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idioma"] == "en" and body["num_pictogramas_encontrados"] == 1
    assert any("/pictograms/en/search/search" in u for u in seen)
    assert "in English" in fake.calls[0]["system"]
    assert base64.b64decode(body["imagen_compuesta_base64"])[:4] == b"\x89PNG"

    trans = db.get(TransformacionEnunciado, trans_id)
    assert "Action 1 - Search" in trans.pictogramas.explicacion_habilidades
    assert "imagen_base64" not in trans.pictogramas.pasos_json[0]


def test_cannot_write_to_another_users_transformation(client, user, other_user, fake_adaptacion):
    trans_id = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user),
                           json={"enunciado": "Tarea de prueba"}).json()["transformacion_id"]
    r = client.post("/generar_pictogramas", headers=auth_headers(other_user),
                    json={"enunciado": "x" * 30, "transformacion_id": trans_id})
    assert r.status_code == 404
    assert client.get(f"/mi-historial/{trans_id}", headers=auth_headers(other_user)).status_code == 404


def test_context_images_and_docx_download(client, user, db, fake_adaptacion, monkeypatch):
    trans_id = client.post("/adaptar_enunciado_ledu", headers=auth_headers(user),
                           json={"enunciado": "Explica la fotosíntesis", "idioma": "es"}).json()["transformacion_id"]
    fake = FakeLLM({"prompts_imagenes": [{"descripcion": "Leaf diagram", "concepto_clave": "Fotosíntesis",
                                          "justificacion": "Verás dónde ocurre."}]})
    monkeypatch.setattr(imagenes, "complete_json", fake)

    class FakeModels:
        async def generate_content(self, **kwargs):
            self.kwargs = kwargs
            part = type("P", (), {"inline_data": type("D", (), {"data": _png()})()})()
            return type("R", (), {"candidates": [type("C", (), {"content": type("X", (), {"parts": [part]})()})()]})()

    fake_models = FakeModels()
    fake_client = type("G", (), {"aio": type("A", (), {"models": fake_models})()})()
    monkeypatch.setattr(imagenes, "get_genai_client", lambda: fake_client)

    r = client.post("/generar_imagenes_contexto", headers=auth_headers(user),
                    json={"enunciado": "Explica la fotosíntesis paso a paso", "transformacion_id": trans_id})
    assert r.status_code == 200, r.text
    assert r.json()["num_imagenes_generadas"] == 1
    assert "all text labels in Spanish" in fake.calls[0]["system"]
    assert "16:9" in fake_models.kwargs["contents"]

    detalle = client.get(f"/mi-historial/{trans_id}", headers=auth_headers(user)).json()
    img_id = detalle["imagenes_contexto"][0]["id"]
    assert client.get(f"/mi-historial/imagenes/{img_id}/imagen", headers=auth_headers(user)).status_code == 200

    r = client.get(f"/mi-historial/{trans_id}/download-docx", headers=auth_headers(user))
    assert r.status_code == 200 and r.content[:2] == b"PK"
    doc = Document(BytesIO(r.content))
    textos = [p.text for p in doc.paragraphs]
    assert "Transformación LEdui" in textos
    assert "Enunciado adaptado" in textos and "Título" in textos
    assert any("Regla 1" in t for t in textos)
    assert len(doc.inline_shapes) == 1


def test_admin_requires_permission(client, user, admin_user):
    assert client.get("/admin/users", headers=auth_headers(user)).status_code == 403
    r = client.get("/admin/users", headers=auth_headers(admin_user))
    assert r.status_code == 200 and r.json()["total"] == 2
    prompts_info = client.get("/admin/prompts", headers=auth_headers(admin_user)).json()["prompts"]
    assert len(prompts_info) == 12 and all("huella" in p for p in prompts_info)


def test_stats_and_history(client, user, fake_adaptacion):
    client.post("/adaptar_enunciado_ledu", headers=auth_headers(user), json={"enunciado": "Tarea uno"})
    stats = client.get("/auth/stats", headers=auth_headers(user)).json()
    assert stats["total_transformaciones"] == 1 and stats["tokens_usados"] == 30
    hist = client.get("/mi-historial", headers=auth_headers(user)).json()
    item = hist["transformaciones"][0]
    assert hist["total"] == 1 and item["idioma"] == "es"
    assert item["titulo"] == "Título"                 # taken from the adaptation's <h1>
    assert item["created_at"].endswith("+00:00")      # dates always include a time zone


def test_favicon(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_interface_is_always_revalidated(client):
    """Prevents the browser from mixing new HTML with old cached JS."""
    for path in ("/static/js/app.js", "/static/i18n/es.json", "/static/css/ledui.css"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_invalid_token(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


def test_examples_per_level(client):
    datos = client.get("/static/data/ejemplos.json").json()
    niveles = {"primaria", "secundaria", "bachillerato", "fp", "universidad"}
    for idioma in ("es", "en"):
        assert set(datos[idioma]) == niveles
        assert all(len(texto) < 15000 for texto in datos[idioma].values())
