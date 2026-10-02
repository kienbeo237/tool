"""Lớp gọi Gemini. Chỉ lo I/O: dựng request, retry lỗi tạm thời, parse JSON.

Kiểm tra nghiệp vụ (token màu, số phần tử, tiếng Anh…) nằm ở service để có thể gửi
lỗi ngược lại cho model sửa trong một lần gọi lại.
"""

import copy
import io
import logging
import re
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from mockup_tool.engine.context_builder import ImagePart, ModelRequest, TextPart
from mockup_tool.engine.schema import (
    DesignElement,
    DesignOutput,
    GarmentPalette,
    RecolorOutput,
    SceneDescription,
    SceneOverrides,
)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE = {429, 500, 502, 503, 504}
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class ModelError(RuntimeError):
    """Lỗi từ phía model, thông điệp hiển thị được cho người dùng."""


class InvalidOutput(ModelError):
    def __init__(self, errors: list[str], raw: str):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.raw = raw


class NoImageError(ModelError):
    pass


class ModelClient(Protocol):
    text_model: str
    image_model: str

    def json_call(self, request: ModelRequest, schema: type[T]) -> tuple[T, str]: ...

    def generate_image(self, prompt: str, scene_image: bytes | None, scene_mime: str, aspect_ratio: str) -> tuple[bytes, str]: ...


def mime_for(path) -> str:
    return _MIME.get(str(path).lower()[str(path).rfind("."):], "image/png")


def inline_refs(schema: dict) -> dict:
    """Bung $ref/$defs của JSON schema Pydantic để model nào cũng đọc được."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, image_model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.text_model = text_model
        self.image_model = image_model

    def _parts(self, request: ModelRequest):
        from google.genai import types

        out = []
        for part in request.parts:
            if isinstance(part, TextPart):
                out.append(types.Part.from_text(text=part.text))
            elif isinstance(part, ImagePart):
                out.append(types.Part.from_bytes(data=part.path.read_bytes(), mime_type=mime_for(part.path)))
        return out

    def _call(self, **kwargs):
        from google.genai import errors

        delay = 2.0
        for attempt in range(1, 4):
            try:
                return self._client.models.generate_content(**kwargs)
            except errors.APIError as e:
                if e.code not in _RETRYABLE or attempt == 3:
                    if e.code == 429:
                        raise ModelError("Gemini báo hết quota / quá giới hạn tốc độ (429). Thử lại sau ít phút.") from e
                    raise ModelError(f"Gemini lỗi {e.code}: {e.message}") from e
                log.warning("Gemini %s, thử lại sau %.0fs (lần %d)", e.code, delay, attempt)
                time.sleep(delay)
                delay *= 2

    def json_call(self, request: ModelRequest, schema: type[T]) -> tuple[T, str]:
        from google.genai import types

        response = self._call(
            model=self.text_model,
            contents=self._parts(request),
            config=types.GenerateContentConfig(
                system_instruction=request.system_instruction,
                response_mime_type="application/json",
                response_json_schema=inline_refs(schema.model_json_schema()),
                temperature=0.8,
            ),
        )
        raw = response.text or ""
        if not raw:
            raise ModelError(f"Gemini không trả nội dung ({_block_reason(response)})")
        try:
            return schema.model_validate_json(raw), raw
        except ValidationError as e:
            raise InvalidOutput([f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()], raw) from e

    def generate_image(self, prompt: str, scene_image: bytes | None, scene_mime: str, aspect_ratio: str) -> tuple[bytes, str]:
        from google.genai import types

        contents = []
        if scene_image:
            contents.append(types.Part.from_text(
                text="SCENE REFERENCE - recreate only this background setting and lighting; "
                     "ignore any garment, artwork or text in it:"
            ))
            contents.append(types.Part.from_bytes(data=scene_image, mime_type=scene_mime))
        contents.append(types.Part.from_text(text=prompt))
        response = self._call(
            model=self.image_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data, part.inline_data.mime_type or "image/png"
        raise NoImageError(f"Model trả về text thay vì ảnh: {response.text or _block_reason(response)}")


def _block_reason(response) -> str:
    feedback = getattr(response, "prompt_feedback", None)
    if feedback and feedback.block_reason:
        return f"bị chặn: {feedback.block_reason}"
    for candidate in response.candidates or []:
        if candidate.finish_reason:
            return f"finish_reason={candidate.finish_reason}"
    return "không rõ lý do"


class MockGeminiClient:
    """Giả lập Gemini khi chưa có API key: trả dữ liệu cố định, đủ để chạy UI và test."""

    text_model = "mock-text"
    image_model = "mock-image"

    def __init__(self):
        self.calls: list[str] = []

    def json_call(self, request: ModelRequest, schema: type[T]) -> tuple[T, str]:
        self.calls.append(schema.__name__)
        texts = [p.text for p in request.parts if isinstance(p, TextPart)]
        if schema is DesignOutput:
            value = self._design(texts)
        elif schema is SceneDescription:
            value = SceneDescription(
                camera="A top-down flat lay product photograph shot straight from above",
                surface="laid flat on a weathered whitewashed wooden plank floor",
                props="A small bundle of dried lavender rests in the top corner.",
                lighting="soft diffused morning window light from the left",
                arrangement="neatly folded",
                color_palette="soft neutral tones of off-white, driftwood and lilac",
                composition="The item sits slightly below center with generous empty space above.",
            )
        elif schema is RecolorOutput:
            keys = re.findall(r"^- ([a-z0-9_]+): ", texts[-1], flags=re.M)
            n = len(re.search(r'"palette": \[(.*?)\]', texts[-1], flags=re.S).group(1).split(","))
            shades = ["Cream", "Navy", "Mustard", "Rust", "Sage Green"]
            value = RecolorOutput(palettes=[GarmentPalette(garment_color_key=k, palette=shades[:n]) for k in keys])
        else:
            raise NotImplementedError(schema)
        return value, value.model_dump_json()

    def _design(self, texts: list[str]) -> DesignOutput:
        fixed = next((t for t in texts if t.startswith("THREAD PALETTE (mandatory)")), None)
        palette = fixed.rsplit(": ", 1)[1].rstrip(".").split(", ") if fixed else ["Cream", "Burnt Orange", "Sage Green"]
        t3 = "[T3]" if len(palette) >= 3 else "[T1]"
        has_note = any(t.startswith("CUSTOMER NOTE") for t in texts)
        return DesignOutput(
            motif_summary="cozy mock goose motif (mock mode, no GEMINI_API_KEY)",
            elements=[
                DesignElement(role="top_text", name="arched title", text="GOOD DAYS",
                              description="Rounded arched lettering in [T1] with two tiny [T2] stars at the ends.",
                              techniques=["satin"]),
                DesignElement(role="main_motif", name="chubby goose", text=None,
                              description=f"A chubby goose silhouette filled in [T1] with a [T2] beak and a small {t3} scarf.",
                              techniques=["tatami", "satin"]),
                DesignElement(role="accent", name="grass line", text=None,
                              description=f"A short wavy grass line beneath the goose in {t3}.",
                              techniques=["running"]),
            ],
            palette=palette,
            scene_overrides=SceneOverrides(camera=None, surface=None, props=None, lighting=None,
                                           arrangement=None, extra="(mock) customer note applied.")
            if has_note else None,
        )

    def generate_image(self, prompt: str, scene_image: bytes | None, scene_mime: str, aspect_ratio: str) -> tuple[bytes, str]:
        from PIL import Image, ImageDraw

        self.calls.append("image")
        w, h = (int(x) for x in aspect_ratio.split(":"))
        size = (1024, int(1024 * h / w)) if w >= h else (int(1024 * w / h), 1024)
        img = Image.new("RGB", size, "#e9e2d4")
        draw = ImageDraw.Draw(img)
        draw.text((40, 40), "MOCK IMAGE (no GEMINI_API_KEY)", fill="#333333")
        for i, line in enumerate(re.findall(r".{1,90}(?:\s|$)", prompt[:900])):
            draw.text((40, 80 + i * 18), line.strip(), fill="#555555")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
