import base64
import io
from dataclasses import replace
from types import SimpleNamespace

import httpx
import openai
import pytest
from PIL import Image

from mockup_tool.config import load_settings
from mockup_tool.engine.gemini_client import ModelError
from mockup_tool.engine.image_engines import (
    GEMINI,
    OPENAI,
    ImageEngine,
    OpenAIImageClient,
    build_image_engines,
    crop_to_ratio,
    openai_size,
)
from mockup_tool.engine.service import UserError


def _png(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "#808080").save(buf, format="PNG")
    return buf.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


@pytest.mark.parametrize("ratio, expected", [
    ("1:1", "1536x1536"), ("4:5", "1232x1536"), ("2:3", "1024x1536"),
    ("9:16", "864x1536"), ("16:9", "1536x864"),
])
def test_openai_size_exact_ratio_for_new_models(ratio, expected):
    assert openai_size("gpt-image-2", ratio) == expected


@pytest.mark.parametrize("ratio, expected", [("1:1", "1024x1024"), ("4:5", "1024x1536"), ("16:9", "1536x1024")])
def test_openai_size_legacy_models_use_fixed_sizes(ratio, expected):
    assert openai_size("gpt-image-1.5", ratio) == expected


def test_crop_to_ratio_center_crops_only_when_needed():
    assert _size(crop_to_ratio(_png(1024, 1536), "4:5")) == (1024, 1280)
    assert _size(crop_to_ratio(_png(1536, 1024), "16:9")) == (1536, 864)
    exact = _png(1232, 1536)
    assert crop_to_ratio(exact, "4:5") is exact


class FakeImages:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def _respond(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_png(1024, 1536)).decode())])

    def generate(self, **kwargs):
        return self._respond("generate", **kwargs)

    def edit(self, **kwargs):
        return self._respond("edit", **kwargs)


def _client(error=None, model="gpt-image-1.5"):
    images = FakeImages(error)
    return OpenAIImageClient("k", model, "high", client=SimpleNamespace(images=images)), images


def test_openai_without_scene_uses_generate_and_crops():
    client, images = _client()
    data, mime = client.generate_image("PROMPT", None, "image/png", "4:5")
    kind, kwargs = images.calls[0]
    assert kind == "generate" and kwargs["prompt"] == "PROMPT"
    assert kwargs["size"] == "1024x1536" and kwargs["quality"] == "high"
    assert mime == "image/png" and _size(data) == (1024, 1280)


def test_openai_with_scene_uses_edit_and_scene_note():
    client, images = _client()
    client.generate_image("PROMPT", b"jpegbytes", "image/jpeg", "2:3")
    kind, kwargs = images.calls[0]
    assert kind == "edit"
    assert kwargs["image"] == [("scene.jpg", b"jpegbytes", "image/jpeg")]
    assert kwargs["prompt"].startswith("SCENE REFERENCE") and kwargs["prompt"].endswith("PROMPT")


def _status_error(cls, status, code, message="boom"):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/images"))
    return cls(message, response=response, body={"code": code, "message": message})


@pytest.mark.parametrize("error, needle", [
    (_status_error(openai.RateLimitError, 429, "insufficient_quota"), "hết credit"),
    (_status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "giới hạn tốc độ"),
    (_status_error(openai.BadRequestError, 400, "moderation_blocked"), "bộ lọc an toàn"),
    (_status_error(openai.PermissionDeniedError, 403, None), "Organization verification"),
    (_status_error(openai.AuthenticationError, 401, None), "OPENAI_API_KEY"),
])
def test_openai_errors_become_readable_model_errors(error, needle):
    client, _ = _client(error)
    with pytest.raises(ModelError, match=needle):
        client.generate_image("P", None, "image/png", "1:1")


def test_build_engines_mock_mode_offers_both_as_mock(monkeypatch, client):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = replace(load_settings(), mock_gemini=True, openai_api_key="")
    engines = build_image_engines(settings, client)
    assert list(engines) == [GEMINI, OPENAI]
    assert all(e.client is not None and e.model.startswith("mock") for e in engines.values())


def test_build_engines_real_mode_without_openai_key_reports_missing(client):
    settings = replace(load_settings(), mock_gemini=False, openai_api_key="")
    engine = build_image_engines(settings, client)[OPENAI]
    assert engine.client is None and engine.missing_key == "OPENAI_API_KEY"


def test_build_engines_with_openai_key(client):
    settings = replace(load_settings(), mock_gemini=False, openai_api_key="sk-test", openai_image_model="gpt-image-2")
    engine = build_image_engines(settings, client)[OPENAI]
    assert isinstance(engine.client, OpenAIImageClient) and engine.model == "gpt-image-2"


def test_service_records_engine_model_per_image(service, base_input, client):
    service.image_engines[OPENAI] = ImageEngine(OPENAI, "ChatGPT", "gpt-image-2", client)
    src = service.generate(base_input())
    service.generate_image(src.request_id)
    service.generate_image(src.request_id, engine=OPENAI)
    assert [model for _, model in service.generation_items(src.request_id)] == ["mock-image", "gpt-image-2"]


def test_service_engine_without_key_is_user_error_and_not_logged(service, base_input):
    service.image_engines[OPENAI] = ImageEngine(OPENAI, "ChatGPT", "gpt-image-2", None, missing_key="OPENAI_API_KEY")
    src = service.generate(base_input())
    with pytest.raises(UserError, match="OPENAI_API_KEY"):
        service.generate_image(src.request_id, engine=OPENAI)
    with pytest.raises(UserError, match="Không có engine"):
        service.generate_image(src.request_id, engine="midjourney")
    assert service.generation_items(src.request_id) == []
