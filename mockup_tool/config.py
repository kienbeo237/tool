"""Cấu hình đọc từ biến môi trường (và file .env nếu có)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    database_url: str
    upload_dir: Path
    text_model: str
    image_model: str
    mock_gemini: bool
    host: str
    port: int


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    upload_dir = Path(os.getenv("UPLOAD_DIR", "./data")).resolve()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    return Settings(
        gemini_api_key=api_key,
        database_url=os.getenv("DATABASE_URL") or f"sqlite:///{(upload_dir / 'mockup.db').as_posix()}",
        upload_dir=upload_dir,
        text_model=os.getenv("TEXT_MODEL", "gemini-2.5-flash"),
        image_model=os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image"),
        # Không có key thì tự chạy chế độ giả lập để dựng/thử giao diện được.
        mock_gemini=_truthy(os.getenv("MOCK_GEMINI")) or not api_key,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "7860")),
    )
