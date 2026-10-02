import pytest
from PIL import Image

from mockup_tool.engine.gemini_client import MockGeminiClient
from mockup_tool.engine.service import GenerateInput, MockupService
from mockup_tool.storage.db import make_session_factory
from mockup_tool.storage.files import FileStore


@pytest.fixture
def client():
    return MockGeminiClient()


@pytest.fixture
def service(tmp_path, client):
    sessions = make_session_factory(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    return MockupService(sessions, FileStore(tmp_path / "files"), client)


@pytest.fixture
def make_image(tmp_path):
    counter = {"n": 0}

    def _make(color="#c08040"):
        counter["n"] += 1
        path = tmp_path / f"img{counter['n']}.png"
        Image.new("RGB", (64, 64), color).save(path)
        return str(path)

    return _make


@pytest.fixture
def base_input(make_image):
    def _input(**overrides):
        values = dict(
            category="embroidered_apparel",
            product_type="gildan_sweatshirt",
            fields={"garment_color": "sand", "placement": "center_chest", "thread_colors": []},
            aspect_ratio="1:1",
            background_mode="preset",
            background_preset="wooden_table",
            idea_images=[make_image()],
        )
        values.update(overrides)
        return GenerateInput(**values)

    return _input
