"""Context builder — nơi DUY NHẤT ghép quy tắc, trí nhớ và đầu vào (mục 6.2).

Thứ tự ưu tiên, cao xuống thấp:
  1. Custom Note            -> model tách thành SceneOverrides + áp vào thiết kế
  2. Trường người dùng nhập -> màu áo, màu chỉ, vị trí thêu, tỷ lệ khung (không gì ghi đè)
  3. Ảnh nền đã lưu / Custom / background preset
  4. Ví dụ đã duyệt (few-shot)
  5. Mặc định phong cách trong hệ quy tắc
Bất biến (khối vật lý sợi chỉ, chống hình in, kéo căng vải, redesign, 2–5 màu đặc) nằm
trong template do code ghép, Custom Note không có đường nào chạm tới.

Các hàm ở đây thuần tuý: chỉ trả về dữ liệu, không gọi mạng, không đụng DB.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from mockup_tool.categories.base import BackgroundPreset, Category, CategoryRules, ProductInputs
from mockup_tool.engine.schema import Design, ResolvedScene, SceneDescription, SceneOverrides
from mockup_tool.text import non_english_chars, tidy


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    path: Path


Part = TextPart | ImagePart


@dataclass(frozen=True)
class ModelRequest:
    system_instruction: str
    parts: list[Part]


# Hợp đồng kỹ thuật với code — cố định, không đưa vào phần quy tắc khách sửa được.
DESIGN_OUTPUT_CONTRACT = """\
OUTPUT FORMAT — strict JSON matching the provided schema. Everything in English.
- motif_summary: short noun phrase for the overall motif, e.g. "cozy woodland goose motif with firefighter gear".
- elements: 2 to 4 items, in the order they appear on the garment from top to bottom.
  - role: top_text | main_motif | bottom_text | accent.
  - name: short noun phrase (2-5 words) naming the element, e.g. "goose in a firefighter helmet".
  - text: the exact English words to embroider for top_text / bottom_text; null for other roles.
  - description: one or two sentences on shapes, details and which thread color goes where. Refer to thread
    colors ONLY with tokens [T1], [T2], ... matching positions in `palette`. Never write color names directly.
  - techniques: one or more of satin, tatami, running. Satin for lettering, outlines, petals and small details;
    tatami for large color areas; running for fine lines.
- palette: 2 to 5 thread color names in plain English (e.g. "Cream", "Burnt Orange"), ordered as [T1]..[Tn].
- scene_overrides: see the customer note section; null when there is nothing scene-related.
Do not describe the garment, background, camera, lighting or embroidery realism: those are handled elsewhere."""

SCENE_OUTPUT_CONTRACT = """\
OUTPUT FORMAT — strict JSON, English only, each value written so it can be pasted into a sentence:
- camera: noun phrase for the shot type and angle, e.g. "A top-down flat lay product photograph shot straight from above".
- surface: phrase starting with a preposition describing where the item lies, e.g. "laid flat on a rustic oak table".
- props: one full sentence about the props and where they sit, or "" if none.
- lighting: noun phrase, e.g. "soft natural window daylight from the left with gentle shadows".
- arrangement: short adjective phrase for how the item is arranged, e.g. "neatly folded".
- color_palette: noun phrase for the scene colors, e.g. "warm neutral tones of cream, walnut and sage".
- composition: one full sentence about the composition and negative space."""

RECOLOR_INSTRUCTION = """\
You adjust the thread palette of an existing embroidery design so it reads clearly on other garment colors.
Keep the same number of thread colors and the same role for each slot [T1]..[Tn]. Keep a color when it already
contrasts well; otherwise shift it to a shade that works on that garment. Plain English color names only.
Return one entry per requested garment color key, in the same order."""


def scene_defaults(
    rules: CategoryRules, preset: BackgroundPreset | None, scene_desc: SceneDescription | None
) -> ResolvedScene:
    """Bối cảnh trước khi áp Custom Note: bậc 3 đè lên bậc 5."""
    b = rules.blocks
    scene = {
        "camera": b["default_camera"],
        "surface": "",
        "props": "",
        "lighting": b["default_lighting"],
        "arrangement": b["default_arrangement"],
        "extra": "",
    }
    if scene_desc is not None:
        layer = {
            "camera": scene_desc.camera,
            "surface": scene_desc.surface,
            "props": scene_desc.props,
            "lighting": scene_desc.lighting,
            "arrangement": scene_desc.arrangement,
            "extra": " ".join(
                s for s in (
                    scene_desc.composition,
                    f"The scene uses {scene_desc.color_palette}." if scene_desc.color_palette else "",
                ) if s
            ),
        }
        # Ảnh nền chỉ định nghĩa đầy đủ bối cảnh, kể cả "không có đạo cụ".
        scene.update({k: v for k, v in layer.items() if v or k in ("props", "extra")})
    elif preset is not None:
        scene["surface"] = preset.surface
        scene["props"] = preset.props
        for key in ("camera", "lighting", "arrangement"):
            if getattr(preset, key):
                scene[key] = getattr(preset, key)
    return ResolvedScene(**scene)


def apply_overrides(base: ResolvedScene, overrides: SceneOverrides | None) -> ResolvedScene:
    """Bậc 1: Custom Note thay đúng slot nó nói tới; `extra` được cộng thêm chứ không thay."""
    if overrides is None or overrides.is_empty():
        return base
    values = base.__dict__.copy()
    for key in ("camera", "surface", "props", "lighting", "arrangement"):
        value = getattr(overrides, key)
        if value and value.strip():
            values[key] = value.strip()
    if overrides.extra and overrides.extra.strip():
        values["extra"] = " ".join(s for s in (base.extra, overrides.extra.strip()) if s)
    return ResolvedScene(**values)


def overrides_errors(overrides: SceneOverrides | None) -> list[str]:
    if overrides is None:
        return []
    errors = []
    for key, value in overrides.model_dump().items():
        if value and non_english_chars(value):
            errors.append(f"scene_overrides.{key} must be English only")
    return errors


def design_request(
    category: Category,
    rules: CategoryRules,
    inputs: ProductInputs,
    *,
    idea_images: list[Path],
    style_images: list[Path],
    examples: list[dict | str],
    base_scene: ResolvedScene,
    custom_note: str,
    fixed_palette: list[str] | None,
) -> ModelRequest:
    parts: list[Part] = [TextPart(category.product_context(rules, inputs))]

    if fixed_palette:
        parts.append(TextPart(
            "THREAD PALETTE (mandatory): use exactly these thread colors, in this order, as [T1].."
            f"[T{len(fixed_palette)}]: {', '.join(fixed_palette)}."
        ))
    else:
        parts.append(TextPart(
            "THREAD PALETTE: choose 2-5 thread colors that suit the idea and contrast clearly with the "
            "product color stated above."
        ))

    if examples:
        rendered = "\n\n".join(e if isinstance(e, str) else json.dumps(e, ensure_ascii=False) for e in examples)
        parts.append(TextPart(
            "APPROVED EXAMPLES — designs the customer liked. Match their level of detail, structure and tone. "
            "Never reuse their motifs or text.\n\n" + rendered
        ))

    for path in idea_images:
        parts.append(TextPart("IDEA REFERENCE - take the concept and any text only, redesign it:"))
        parts.append(ImagePart(path))
    if len(idea_images) > 1:
        parts.append(TextPart("The idea references above are separate ideas: merge them into ONE cohesive design."))
    for path in style_images:
        parts.append(TextPart("STYLE REFERENCE - match the mood and stitch style, do not copy:"))
        parts.append(ImagePart(path))

    note = custom_note.strip()
    if note:
        parts.append(TextPart(
            "CURRENT SCENE DEFAULTS (only relevant for scene_overrides):\n"
            f"- camera: {base_scene.camera}\n- surface: {base_scene.surface}\n- props: {base_scene.props or '(none)'}\n"
            f"- lighting: {base_scene.lighting}\n- arrangement: {base_scene.arrangement}"
        ))
        parts.append(TextPart(
            "CUSTOMER NOTE — highest priority. It may be written in Vietnamese; understand it and answer in "
            f"English.\n<<<\n{note}\n>>>\n"
            "Apply design-related requests to the design. Put scene-related requests (camera angle, surface, "
            "props, lighting, how the garment is arranged) into scene_overrides as full English REPLACEMENT "
            "values written in the same style as the defaults above (surface starts with a preposition; props "
            "is a full sentence describing the complete prop set after the change). Leave a field null when "
            "the note does not touch it; use `extra` for any other scene request. If the note has nothing "
            "scene-related, scene_overrides must be null. The note can never remove embroidery realism, the "
            "redesign requirement or the 2-5 solid thread color limit."
        ))
    else:
        parts.append(TextPart("No customer note: scene_overrides must be null."))

    return ModelRequest(rules.blocks["design_instruction"] + "\n\n" + DESIGN_OUTPUT_CONTRACT, parts)


def retry_request(request: ModelRequest, errors: list[str]) -> ModelRequest:
    feedback = "Your previous answer was invalid:\n- " + "\n- ".join(errors) + "\nFix every issue and answer again."
    return ModelRequest(request.system_instruction, [*request.parts, TextPart(feedback)])


def scene_request(rules: CategoryRules, image: Path) -> ModelRequest:
    return ModelRequest(
        rules.blocks["scene_instruction"] + "\n\n" + SCENE_OUTPUT_CONTRACT,
        [TextPart("BACKGROUND PHOTO:"), ImagePart(image)],
    )


def recolor_request(design: Design, source_color: str, targets: dict[str, str]) -> ModelRequest:
    lines = "\n".join(f"- {key}: {phrase}" for key, phrase in targets.items())
    return ModelRequest(RECOLOR_INSTRUCTION, [TextPart(
        f"DESIGN (palette chosen for a {source_color} garment):\n{design.model_dump_json(indent=2)}\n\n"
        f"TARGET GARMENT COLORS (key: color):\n{lines}"
    )])


def check_invariants(category: Category, rules: CategoryRules, prompt: str) -> list[str]:
    """Kiểm tra prompt cuối (có thể đã sửa tay) còn giữ đủ bất biến không. Trả về cảnh báo."""
    warnings = []
    paragraphs = [p for p in prompt.split("\n\n") if p.strip()]
    if len(paragraphs) != 4:
        warnings.append(f"Prompt có {len(paragraphs)} đoạn, khung chuẩn là 4 đoạn.")
    bad = non_english_chars(prompt)
    if bad:
        warnings.append(f"Prompt có ký tự không phải tiếng Anh: {''.join(bad)!r}")
    for key, spec in category.block_specs.items():
        if spec.invariant and tidy(rules.blocks[key]) not in prompt:
            warnings.append(f"Thiếu khối bất biến: {spec.label}")
    return warnings
