"""Các engine sinh ảnh người dùng chọn được: Gemini hoặc ChatGPT (OpenAI gpt-image).

Chỉ phần SINH ẢNH đổi theo engine. Prompt vẫn do model text (Gemini) dựng, nên hai
engine nhận đúng một prompt và so sánh được với nhau.

Không tự chuyển sang engine khác khi một bên lỗi: giá và chất lượng khác nhau, người
dùng phải biết ảnh nào do model nào sinh.
"""

import base64
import io
import logging
from dataclasses import dataclass
from typing import Protocol

from mockup_tool.config import Settings
from mockup_tool.engine.gemini_client import SCENE_REFERENCE_NOTE, ModelError, NoImageError, mock_image

log = logging.getLogger(__name__)

GEMINI = "gemini"
OPENAI = "openai"

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
# gpt-image-1 / 1.5 / 1-mini chỉ nhận ba kích thước cố định; gpt-image-2 trở đi nhận kích thước tuỳ ý.
_LEGACY_SIZES = {"1024x1024": 1.0, "1536x1024": 1.5, "1024x1536": 2 / 3}
_LONG_SIDE = 1536


class ImageClient(Protocol):
    def generate_image(self, prompt: str, scene_image: bytes | None, scene_mime: str,
                       aspect_ratio: str) -> tuple[bytes, str]: ...


@dataclass(frozen=True)
class ImageEngine:
    key: str
    label: str              # hiện trên giao diện
    model: str              # ghi vào bảng generations
    client: ImageClient | None
    missing_key: str = ""   # tên biến môi trường còn thiếu; khác rỗng = chưa dùng được


def _ratio(aspect_ratio: str) -> float:
    w, h = (int(x) for x in aspect_ratio.split(":"))
    return w / h


def openai_size(model: str, aspect_ratio: str) -> str:
    """Kích thước gửi OpenAI. Model mới: đúng tỷ lệ (cạnh chia hết cho 16).
    Model cũ: kích thước cố định gần nhất, sau đó cắt giữa cho đúng tỷ lệ."""
    ratio = _ratio(aspect_ratio)
    if model.startswith("gpt-image-1"):
        return min(_LEGACY_SIZES, key=lambda size: abs(_LEGACY_SIZES[size] - ratio))
    if ratio >= 1:
        w, h = _LONG_SIDE, _LONG_SIDE / ratio
    else:
        w, h = _LONG_SIDE * ratio, _LONG_SIDE
    return f"{round(w / 16) * 16}x{round(h / 16) * 16}"


def crop_to_ratio(data: bytes, aspect_ratio: str) -> bytes:
    """Cắt giữa về đúng tỷ lệ khung. Đã đúng (lệch < 1%) thì trả nguyên ảnh."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    w, h = img.size
    target = _ratio(aspect_ratio)
    if abs(w / h - target) / target < 0.01:
        return data
    if w / h > target:
        new_w = round(h * target)
        box = ((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h)
    else:
        new_h = round(w / target)
        box = (0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h)
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    return buf.getvalue()


class OpenAIImageClient:
    def __init__(self, api_key: str, model: str, quality: str, client=None):
        if client is None:
            from openai import OpenAI

            # SDK tự thử lại 429/5xx/timeout. Ảnh chất lượng cao có thể mất 1–2 phút.
            client = OpenAI(api_key=api_key, timeout=300, max_retries=2)
        self._client = client
        self.model = model
        self.quality = quality

    def generate_image(self, prompt: str, scene_image: bytes | None, scene_mime: str,
                       aspect_ratio: str) -> tuple[bytes, str]:
        import openai

        params = dict(model=self.model, size=openai_size(self.model, aspect_ratio), quality=self.quality, n=1)
        try:
            if scene_image:
                name = "scene" + _EXT.get(scene_mime, ".png")
                response = self._client.images.edit(image=[(name, scene_image, scene_mime)],
                                                    prompt=f"{SCENE_REFERENCE_NOTE}\n\n{prompt}", **params)
            else:
                response = self._client.images.generate(prompt=prompt, **params)
        except openai.APIStatusError as e:
            raise ModelError(_status_message(e)) from e
        except openai.APIConnectionError as e:
            raise ModelError("Không kết nối được OpenAI (mạng hoặc quá thời gian chờ). Thử lại sau.") from e

        b64 = response.data[0].b64_json if response.data else None
        if not b64:
            raise NoImageError("OpenAI không trả ảnh")
        return crop_to_ratio(base64.b64decode(b64), aspect_ratio), "image/png"


def _status_message(e) -> str:
    body = e.body if isinstance(e.body, dict) else {}
    code = body.get("code") or ""
    message = body.get("message") or e.message
    if code == "moderation_blocked" or "safety system" in message:
        return "OpenAI từ chối prompt này (bộ lọc an toàn). Sửa prompt hoặc dùng Gemini."
    if e.status_code == 401:
        return "OPENAI_API_KEY sai hoặc đã bị thu hồi (401)."
    if e.status_code == 403:
        return (f"OpenAI từ chối truy cập (403): {message} — model gpt-image cần tổ chức đã xác minh "
                "(Organization verification) trên platform.openai.com.")
    if e.status_code == 429:
        if code == "insufficient_quota":
            return "Tài khoản OpenAI hết credit (429 insufficient_quota). Nạp thêm tại platform.openai.com/billing."
        return "OpenAI báo quá giới hạn tốc độ (429). Thử lại sau ít phút."
    return f"OpenAI lỗi {e.status_code}: {message}"


def build_image_engines(settings: Settings, gemini_client: ImageClient) -> dict[str, ImageEngine]:
    """Engine thiếu key: ở chế độ giả lập thì trả ảnh giả; ở chế độ thật thì vẫn hiện
    nhưng báo rõ thiếu key khi bấm, để người dùng biết có lựa chọn này."""
    engines = {GEMINI: ImageEngine(
        GEMINI, "Gemini (giả lập)" if settings.mock_gemini else "Gemini",
        "mock-image" if settings.mock_gemini else settings.image_model, gemini_client)}

    model = settings.openai_image_model
    if settings.openai_api_key:
        engines[OPENAI] = ImageEngine(OPENAI, "ChatGPT", model, OpenAIImageClient(
            settings.openai_api_key, model, settings.openai_image_quality))
    elif settings.mock_gemini:
        engines[OPENAI] = ImageEngine(OPENAI, "ChatGPT (giả lập)", "mock-openai", _MockOpenAI())
    else:
        engines[OPENAI] = ImageEngine(OPENAI, "ChatGPT (chưa có key)", model, None,
                                      missing_key="OPENAI_API_KEY")
    return engines


class _MockOpenAI:
    def generate_image(self, prompt, scene_image, scene_mime, aspect_ratio):
        return mock_image(prompt, aspect_ratio, "MOCK IMAGE · ChatGPT (no OPENAI_API_KEY)")
