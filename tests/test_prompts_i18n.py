from pathlib import Path

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.i18n import nivel_label, normalize_nivel, resolve_language, t
from app.prompt_loader import PROMPT_NAMES, prompts
from app.services.llm import AIResponseError, extract_json_object


def _request(headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "query_string": b""})


# ---------------------------------------------------------------- prompts

@pytest.mark.parametrize("lang", ["es", "en"])
@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_all_prompts_exist_in_both_languages(name, lang):
    tpl = prompts.get(name, lang)
    assert tpl.text.strip()
    assert f"/{lang}/" in tpl.source


def test_render_replaces_placeholders_and_keeps_json():
    texto = prompts.render("adaptar_user", "es", nivel="FP", max_palabras=300,
                           enunciado="Haz X", idioma_nombre="español")
    assert "Nivel educativo: FP" in texto and "Haz X" in texto and "{{" not in texto
    system = prompts.render("adaptar_system", "en", idioma_nombre="English")
    assert '"texto_adaptado"' in system and "in English" in system


def test_override_with_environment_variable(monkeypatch):
    monkeypatch.setenv("PROMPT_ADAPTAR_USER_EN", "Custom {{enunciado}}")
    prompts.reload()
    tpl = prompts.get("adaptar_user", "en")
    assert tpl.source == "env:PROMPT_ADAPTAR_USER_EN"
    assert tpl.render(enunciado="hi") == "Custom hi"
    # the other language is not affected
    assert prompts.get("adaptar_user", "es").source.startswith("file:")


def test_override_with_file(monkeypatch, tmp_path):
    f = tmp_path / "mio.md"
    f.write_text("Desde fichero {{enunciado}}", encoding="utf-8")
    monkeypatch.setenv("PROMPT_PICTOGRAMAS_USER_ES_FILE", str(f))
    prompts.reload()
    assert prompts.render("pictogramas_user", "es", enunciado="E") == "Desde fichero E"


def test_partial_experiment_folder(monkeypatch, tmp_path):
    """A PROMPTS_DIR folder with a single prompt falls back to the built-in ones for the rest."""
    (tmp_path / "es").mkdir()
    (tmp_path / "es" / "adaptar_system.md").write_text("EXPERIMENTO", encoding="utf-8")
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        prompts.reload()
        assert prompts.get("adaptar_system", "es").text == "EXPERIMENTO"
        assert prompts.get("adaptar_user", "es").source != f"file:{tmp_path}"
        assert "Nivel educativo" in prompts.get("adaptar_user", "es").text
    finally:
        monkeypatch.delenv("PROMPTS_DIR")
        get_settings.cache_clear()
        prompts.reload()


def test_version_changes_with_prompt_and_accepts_set_name(monkeypatch):
    v1 = prompts.version(["adaptar_system", "adaptar_user"], "es")
    monkeypatch.setenv("PROMPT_ADAPTAR_SYSTEM_ES", "otro")
    prompts.reload()
    v2 = prompts.version(["adaptar_system", "adaptar_user"], "es")
    assert v1 != v2
    monkeypatch.setenv("PROMPT_SET_NAME", "exp3")
    assert prompts.version(["adaptar_system"], "es").startswith("exp3:")


def test_hot_reload(monkeypatch, tmp_path):
    f = tmp_path / "p.md"
    f.write_text("v1", encoding="utf-8")
    monkeypatch.setenv("PROMPT_ADAPTAR_USER_ES_FILE", str(f))
    monkeypatch.setenv("PROMPTS_HOT_RELOAD", "true")
    get_settings.cache_clear()
    try:
        assert prompts.get("adaptar_user", "es").text == "v1"
        f.write_text("v2", encoding="utf-8")
        assert prompts.get("adaptar_user", "es").text == "v2"
    finally:
        monkeypatch.delenv("PROMPTS_HOT_RELOAD")
        get_settings.cache_clear()


# ---------------------------------------------------------------- language

def test_resolve_language():
    assert resolve_language("en") == "en"
    assert resolve_language("EN-gb") == "en"
    assert resolve_language("fr") == "es"  # unsupported -> default
    assert resolve_language(None, _request({"Accept-Language": "en-US,en;q=0.9"})) == "en"
    assert resolve_language(None, _request({"Accept-Language": "fr-FR,en;q=0.5"})) == "en"
    assert resolve_language(None, _request()) == "es"


def test_messages_and_levels():
    assert t("error.enunciado_corto", "en").startswith("The task")
    assert t("fallback.vas_a", "es", accion="leer") == "Vas a leer."
    assert normalize_nivel("Vocational Training") == "fp"
    assert nivel_label("fp", "en") == "Vocational training"
    assert nivel_label("algo raro", "es") == "algo raro"


# ---------------------------------------------------------------- JSON

def test_extract_json_with_code_fence_and_braces_in_text():
    raw = 'Aquí va:\n```json\n{"texto_adaptado": "<p>usa {llaves}</p>", "n": {"a": 1}}\n```'
    assert extract_json_object(raw)["n"] == {"a": 1}


def test_extract_incomplete_json():
    with pytest.raises(AIResponseError):
        extract_json_object('{"texto_adaptado": "cortado')


def test_frontend_translations_have_same_keys():
    import json
    base = Path(__file__).resolve().parent.parent / "static" / "i18n"
    es = json.loads((base / "es.json").read_text(encoding="utf-8"))
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))
    assert set(es) == set(en)
