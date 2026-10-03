"""Khung chung cho mọi danh mục sản phẩm.

Mỗi danh mục gồm hai phần:
- Phần code (lớp con của `Category`): hàm dựng khung đoạn, các block nào bắt buộc,
  placeholder nào được phép. Phần này quyết định CẤU TRÚC prompt.
- Phần dữ liệu (`CategoryRules`, lưu trong DB, có phiên bản): câu chữ của từng block
  và danh mục chọn (loại sản phẩm, màu, vị trí, background). Khách sửa được qua tab Quy tắc.
"""

from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from mockup_tool.engine.schema import Design, ResolvedScene
from mockup_tool.text import non_english_chars, placeholders

KEY_PATTERN = r"^[a-z0-9_]+$"


class ProductType(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str
    phrase: str
    material: str = ""


class ColorItem(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")

    @property
    def phrase(self) -> str:
        return f"{self.label} ({self.hex.lower()})"


class PlacementItem(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str
    phrase: str


class BackgroundPreset(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str
    surface: str
    props: str = ""
    camera: str = ""
    lighting: str = ""
    arrangement: str = ""


class CategoryRules(BaseModel):
    product_types: list[ProductType] = Field(min_length=1)
    colors: list[ColorItem] = Field(min_length=1)
    placements: list[PlacementItem] = Field(min_length=1)
    backgrounds: list[BackgroundPreset] = Field(min_length=1)
    aspect_ratios: list[str] = Field(min_length=1)
    blocks: dict[str, str]

    @model_validator(mode="after")
    def _unique_keys(self):
        for name in ("product_types", "colors", "placements", "backgrounds"):
            keys = [item.key for item in getattr(self, name)]
            dupes = {k for k in keys if keys.count(k) > 1}
            if dupes:
                raise ValueError(f"{name}: khoá bị trùng {sorted(dupes)}")
        return self

    def product_type(self, key: str) -> ProductType:
        return _find(self.product_types, key, "Product Type")

    def color(self, key: str) -> ColorItem:
        return _find(self.colors, key, "Garment Color")

    def placement(self, key: str) -> PlacementItem:
        return _find(self.placements, key, "Placement")

    def background(self, key: str) -> BackgroundPreset:
        return _find(self.backgrounds, key, "Background")


def _find(items, key, what):
    for item in items:
        if item.key == key:
            return item
    raise KeyError(f"{what} '{key}' không có trong danh mục hiện tại")


@dataclass(frozen=True)
class BlockSpec:
    label: str
    allowed: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()
    # Bất biến: text của block phải xuất hiện nguyên văn trong prompt cuối (mục 6.2).
    invariant: bool = False
    # Hiện ở tab Quy tắc: block này dùng vào việc gì (tiếng Việt, cho người không đọc code).
    purpose: str = ""
    # instruction: gửi cho AI làm chỉ dẫn | default: giá trị mặc định | template: mẫu câu ghép vào prompt
    kind: str = "template"


@dataclass(frozen=True)
class ProductInputs:
    """Các trường người dùng nhập, đã chuẩn hoá. `fields` là phần riêng của danh mục."""

    product_type: str
    aspect_ratio: str
    fields: dict = field(default_factory=dict)


class Category:
    key: ClassVar[str]
    label: ClassVar[str]
    techniques: ClassVar[tuple[str, ...]]
    block_specs: ClassVar[dict[str, BlockSpec]]
    # Placeholder được phép trong phrase của từng placement.
    placement_placeholders: ClassVar[frozenset[str]] = frozenset()
    # Nghĩa của từng {placeholder}, hiện ở tab Quy tắc.
    placeholder_help: ClassVar[dict[str, str]] = {}

    def seed_rules(self) -> CategoryRules:
        raise NotImplementedError

    def normalize_fields(self, rules: CategoryRules, fields: dict) -> dict:
        """Kiểm tra và chuẩn hoá các trường riêng của danh mục. Ném ValueError nếu sai."""
        raise NotImplementedError

    def fixed_palette(self, fields: dict) -> list[str] | None:
        """Bảng màu người dùng bắt buộc (nếu có) — model phải tuân theo đúng thứ tự."""
        return None

    def batch_options(self, rules: CategoryRules) -> list[tuple[str, str]]:
        """Các giá trị (label, key) được phép thay khi làm lại theo lô."""
        raise NotImplementedError

    def batch_value(self, fields: dict) -> str:
        raise NotImplementedError

    def with_batch_value(self, fields: dict, key: str) -> dict:
        raise NotImplementedError

    def batch_phrase(self, rules: CategoryRules, key: str) -> str:
        raise NotImplementedError

    def build_prompt(self, rules: CategoryRules, inputs: ProductInputs, design: Design, scene: ResolvedScene) -> str:
        raise NotImplementedError

    def product_context(self, rules: CategoryRules, inputs: ProductInputs) -> str:
        """Một đoạn mô tả sản phẩm đưa cho model khi viết thiết kế."""
        raise NotImplementedError

    def design_part(self, prompt: str) -> str:
        """Trích phần thiết kế (đoạn do model sinh) từ prompt đã dựng."""
        raise NotImplementedError

    def validate_rules(self, rules: CategoryRules) -> list[str]:
        errors: list[str] = []
        for key, spec in self.block_specs.items():
            text = rules.blocks.get(key, "")
            if not text.strip():
                errors.append(f"“{spec.label}” [{key}] không được để trống")
                continue
            errors += _check_template(f"“{spec.label}” [{key}]", text, spec.allowed, spec.required)
        unknown = set(rules.blocks) - set(self.block_specs)
        if unknown:
            errors.append(f"Block không thuộc danh mục này: {sorted(unknown)}")
        for p in rules.placements:
            errors += _check_template(f"Placement '{p.key}'", p.phrase, self.placement_placeholders, frozenset())
        for item in [*rules.product_types, *rules.backgrounds]:
            for name, value in item.model_dump().items():
                if name in ("key", "label"):
                    continue
                bad = non_english_chars(value)
                if bad:
                    errors.append(f"'{item.key}.{name}' phải là tiếng Anh (có ký tự {''.join(bad)!r})")
                elif "{" in value or "}" in value:
                    errors.append(f"'{item.key}.{name}' không được chứa dấu {{ }}")
        return errors


def _check_template(where: str, text: str, allowed: frozenset[str], required: frozenset[str]) -> list[str]:
    errors = []
    bad = non_english_chars(text)
    if bad:
        errors.append(f"{where} phải là 100% tiếng Anh (có ký tự {''.join(bad)!r})")
    try:
        names = placeholders(text)
    except ValueError as e:
        return errors + [f"{where}: {e}. Muốn viết dấu ngoặc nhọn thật thì gõ {{{{ }}}}"]
    unknown = names - allowed
    if unknown:
        allowed_text = ", ".join("{%s}" % a for a in sorted(allowed)) or "không có ô nào"
        errors.append(f"{where}: có ô tự điền không hợp lệ {', '.join('{%s}' % u for u in sorted(unknown))} — "
                      f"đoạn này chỉ dùng được: {allowed_text}")
    missing = required - names
    if missing:
        errors.append(f"{where}: thiếu ô tự điền bắt buộc {', '.join('{%s}' % m for m in sorted(missing))} "
                      "— giữ nguyên các ô này khi sửa")
    return errors
