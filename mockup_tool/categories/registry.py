"""Đăng ký danh mục. Thêm danh mục mới = thêm một package + một dòng ở đây; không sửa engine."""

from mockup_tool.categories.base import Category
from mockup_tool.categories.embroidery import EmbroideryCategory

CATEGORIES: dict[str, Category] = {c.key: c for c in (EmbroideryCategory(),)}


def get_category(key: str) -> Category:
    try:
        return CATEGORIES[key]
    except KeyError:
        raise KeyError(f"Danh mục '{key}' chưa được đăng ký") from None
