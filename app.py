"""Điểm chạy: `python app.py`."""

import logging
import os
import sys

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from mockup_tool.config import load_settings
from mockup_tool.engine.gemini_client import GeminiClient, MockGeminiClient
from mockup_tool.engine.service import MockupService
from mockup_tool.storage.db import make_session_factory
from mockup_tool.storage.files import FileStore
from mockup_tool.ui.app import build_app
from mockup_tool.ui.theme import CSS, THEME


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    log = logging.getLogger("mockup_tool")

    if not settings.app_password and settings.host not in ("127.0.0.1", "localhost"):
        sys.exit("APP_PASSWORD bắt buộc khi HOST không phải localhost.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    client = (MockGeminiClient() if settings.mock_gemini
              else GeminiClient(settings.gemini_api_key, settings.text_model, settings.image_model))
    if settings.mock_gemini:
        log.warning("Chạy chế độ GIẢ LẬP (không có GEMINI_API_KEY hoặc MOCK_GEMINI=1).")
    service = MockupService(make_session_factory(settings.database_url), FileStore(settings.upload_dir), client)

    demo = build_app(service, settings)
    demo.queue(default_concurrency_limit=1, max_size=32)
    demo.launch(
        server_name=settings.host,
        server_port=settings.port,
        auth=(lambda _user, password: password == settings.app_password) if settings.app_password else None,
        auth_message="Nhập mật khẩu chung (tên đăng nhập gõ gì cũng được).",
        allowed_paths=[str(settings.upload_dir)],
        max_file_size="20mb",
        theme=THEME,
        css=CSS,
        show_error=True,
        footer_links=[],
    )


if __name__ == "__main__":
    main()
