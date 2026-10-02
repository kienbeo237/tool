"""Schema dữ liệu trao đổi với model và giữa các tầng.

Model chỉ trả về JSON theo các lớp *Output ở đây; code tự dựng câu từ JSON đó.
Màu chỉ trong mô tả luôn viết dạng token [T1]..[T5] trỏ vào `palette`, nhờ vậy
đổi palette (làm lại theo lô) chỉ là thay chuỗi, không phải gọi lại model.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from mockup_tool.text import non_english_chars

Role = Literal["top_text", "main_motif", "bottom_text", "accent"]
TEXT_ROLES = ("top_text", "bottom_text")
TOKEN_RE = re.compile(r"\[T(\d)\]")


class DesignElement(BaseModel):
    role: Role
    name: str
    text: str | None
    description: str
    techniques: list[str]


class SceneOverrides(BaseModel):
    """Phần bối cảnh tách ra từ Custom Note. Trường nào null thì giữ mặc định."""

    camera: str | None
    surface: str | None
    props: str | None
    lighting: str | None
    arrangement: str | None
    extra: str | None

    def is_empty(self) -> bool:
        return not any(v and v.strip() for v in self.model_dump().values())


class DesignOutput(BaseModel):
    """Đúng một lệnh gọi model cho đường đi chính trả về đối tượng này."""

    motif_summary: str
    elements: list[DesignElement]
    palette: list[str]
    scene_overrides: SceneOverrides | None


class Design(BaseModel):
    """Phần thiết kế lưu trong DB (design_json) — không chứa bối cảnh."""

    motif_summary: str
    elements: list[DesignElement]
    palette: list[str]


class GarmentPalette(BaseModel):
    garment_color_key: str
    palette: list[str]


class RecolorOutput(BaseModel):
    palettes: list[GarmentPalette]


class SceneDescription(BaseModel):
    """Mô tả có cấu trúc của một ảnh nền, sinh bởi vision và lưu lại dạng chữ."""

    camera: str
    surface: str
    props: str
    lighting: str
    arrangement: str
    color_palette: str
    composition: str


@dataclass(frozen=True)
class ResolvedScene:
    camera: str
    surface: str
    props: str
    lighting: str
    arrangement: str
    extra: str


def validate_design(design: Design, techniques: tuple[str, ...], fixed_palette: list[str] | None) -> list[str]:
    """Kiểm tra ràng buộc nghiệp vụ mà JSON schema không diễn đạt được. Trả về danh sách lỗi."""
    errors: list[str] = []
    n = len(design.palette)
    if not 2 <= len(design.elements) <= 4:
        errors.append(f"elements must have 2-4 items, got {len(design.elements)}")
    if not 2 <= n <= 5:
        errors.append(f"palette must have 2-5 thread colors, got {n}")
    if len({p.strip().lower() for p in design.palette}) != n or any(not p.strip() for p in design.palette):
        errors.append("palette entries must be unique and non-empty")
    if fixed_palette and [p.strip().lower() for p in design.palette] != [p.strip().lower() for p in fixed_palette]:
        errors.append(f"palette must be exactly {fixed_palette} in that order")
    for i, el in enumerate(design.elements, 1):
        tokens = [int(t) for t in TOKEN_RE.findall(el.description)]
        if not tokens:
            errors.append(f"element {i} ({el.name}): description must reference thread colors with [T1]..[T{n}]")
        bad = sorted({t for t in tokens if not 1 <= t <= n})
        if bad:
            errors.append(f"element {i} ({el.name}): tokens {['T%d' % t for t in bad]} do not exist in palette")
        if el.role in TEXT_ROLES and not (el.text and el.text.strip()):
            errors.append(f"element {i} ({el.name}): role {el.role} requires the exact text to embroider")
        if not el.techniques or any(t not in techniques for t in el.techniques):
            errors.append(f"element {i} ({el.name}): techniques must be a non-empty subset of {list(techniques)}")
    for field, value in _iter_strings(design):
        bad_chars = non_english_chars(value)
        if bad_chars:
            errors.append(f"{field} must be English only, found {''.join(bad_chars)!r}")
    return errors


def _iter_strings(design: Design):
    yield "motif_summary", design.motif_summary
    for i, p in enumerate(design.palette, 1):
        yield f"palette[{i}]", p
    for i, el in enumerate(design.elements, 1):
        yield f"elements[{i}].name", el.name
        yield f"elements[{i}].description", el.description
        if el.text:
            yield f"elements[{i}].text", el.text


def render_tokens(text: str, palette: list[str]) -> str:
    return TOKEN_RE.sub(lambda m: palette[int(m.group(1)) - 1], text)
