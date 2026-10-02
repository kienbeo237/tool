"""Lưu ảnh trên đĩa. Ảnh upload được chuẩn hoá (xoay theo EXIF, bỏ metadata, giới hạn
kích thước) và đặt tên theo SHA-256 nội dung, nên upload trùng không tốn thêm chỗ."""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 2048


@dataclass(frozen=True)
class StoredImage:
    rel_path: str
    sha256: str


class FileStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def abs(self, rel_path: str) -> Path:
        return self.root / rel_path

    def ingest_image(self, src: str | Path) -> StoredImage:
        try:
            with Image.open(src) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
                img.thumbnail((MAX_SIDE, MAX_SIDE))
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError(f"File '{Path(src).name}' không phải ảnh hợp lệ") from e
        data = buf.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        rel = f"uploads/{sha[:2]}/{sha}.png"
        path = self.abs(rel)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return StoredImage(rel, sha)

    def save_generation(self, request_id: int, generation_id: int, data: bytes, mime: str) -> str:
        ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        rel = f"generations/{request_id}/{generation_id}.{ext}"
        path = self.abs(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel

    def write_export(self, name: str, text: str) -> Path:
        path = self.abs(f"exports/{name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
