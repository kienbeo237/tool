"""Tiện ích chuỗi dùng chung: kiểm tra tiếng Anh, placeholder, dọn khoảng trắng."""

import re
import string

# Ký tự ngoài ASCII vẫn hợp lệ trong prompt tiếng Anh (dấu câu kiểu chữ in, ký hiệu).
_ALLOWED_NON_ASCII = set(" °×®©™…") | {
    chr(c) for c in range(0x2010, 0x2028)  # gạch nối, gạch ngang, nháy cong, bullet
}


def non_english_chars(text: str) -> list[str]:
    """Trả về các ký tự không thuộc văn bản tiếng Anh (vd. chữ có dấu tiếng Việt)."""
    seen: list[str] = []
    for ch in text:
        if ord(ch) < 128 or ch in _ALLOWED_NON_ASCII:
            continue
        if ch not in seen:
            seen.append(ch)
    return seen


def placeholders(template: str) -> set[str]:
    """Tên các placeholder {name} trong template. Ném ValueError nếu dấu ngoặc sai cú pháp."""
    names = set()
    for _, field, _, _ in string.Formatter().parse(template):
        if field is None:
            continue
        if not field.isidentifier():
            raise ValueError(f"placeholder không hợp lệ: {{{field}}}")
        names.add(field)
    return names


def fill(template: str, **values: str) -> str:
    return tidy(template.format(**values))


_SPACES = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT = re.compile(r" +([.,;:!?])")
_DOUBLE_PERIOD = re.compile(r"\.(\s*\.)+")


def tidy(text: str) -> str:
    """Dọn chỗ trống do placeholder rỗng để lại: khoảng trắng kép, ' .', '. .'."""
    text = _SPACES.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _DOUBLE_PERIOD.sub(".", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def join_list(items: list[str]) -> str:
    """['a','b','c'] -> 'a, b, and c'."""
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]
