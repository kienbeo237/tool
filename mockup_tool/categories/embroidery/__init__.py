"""Danh mục áo thêu: khung bốn đoạn (mục 6.2–6.3 của tài liệu thiết kế)."""

from mockup_tool.categories.base import BlockSpec, Category, CategoryRules, ProductInputs
from mockup_tool.categories.embroidery.seed import seed_dict
from mockup_tool.engine.schema import TEXT_ROLES, Design, DesignElement, ResolvedScene, render_tokens
from mockup_tool.text import fill, join_list, non_english_chars

_GARMENT = frozenset({"garment", "material", "color", "color_name"})

_ROLE_LABELS = {
    "top_text": "Top text",
    "main_motif": "Main motif",
    "bottom_text": "Bottom text",
    "accent": "Accent detail",
}

_TECHNIQUE_BLOCKS = {"satin": "satin_sentence", "tatami": "tatami_sentence", "running": "running_sentence"}


class EmbroideryCategory(Category):
    key = "embroidered_apparel"
    label = "Áo thêu"
    techniques = ("satin", "tatami", "running")
    placement_placeholders = frozenset({"color_name"})
    block_specs = {
        "design_instruction": BlockSpec("Chỉ dẫn cho model khi viết thiết kế (đoạn 3)"),
        "scene_instruction": BlockSpec("Chỉ dẫn cho model khi đọc ảnh nền Custom"),
        "default_camera": BlockSpec("Góc máy mặc định"),
        "default_lighting": BlockSpec("Ánh sáng mặc định"),
        "default_arrangement": BlockSpec("Cách đặt áo mặc định"),
        "para1": BlockSpec(
            "Đoạn 1 — góc máy, áo, bề mặt, đạo cụ, ánh sáng",
            allowed=_GARMENT | {"camera", "arrangement", "surface", "props", "lighting", "extra", "aspect_ratio"},
            required=frozenset({"camera", "garment", "color", "surface", "props", "lighting", "extra"}),
        ),
        "para2": BlockSpec(
            "Đoạn 2 — chất liệu, khung hình, kéo căng vải",
            allowed=_GARMENT | {"puckering"},
            required=frozenset({"garment", "puckering"}),
        ),
        "puckering": BlockSpec("Hiệu ứng kéo căng vải (bất biến)", invariant=True),
        "para3_intro": BlockSpec(
            "Đoạn 3 — dòng mở đầu ép tỷ lệ",
            allowed=_GARMENT | {"motif", "placement_clause"},
            required=frozenset({"motif", "placement_clause"}),
        ),
        "para3_palette": BlockSpec(
            "Đoạn 3 — dòng Palette & Style",
            allowed=frozenset({"threads", "thread_count"}),
            required=frozenset({"threads"}),
        ),
        "para4": BlockSpec(
            "Đoạn 4 — kỹ thuật mũi thêu và tổng kết",
            allowed=_GARMENT | {"technique_sentences", "thread_physics", "anti_print"},
            required=frozenset({"technique_sentences", "thread_physics", "anti_print"}),
        ),
        "satin_sentence": BlockSpec("Câu satin", allowed=frozenset({"parts"}), required=frozenset({"parts"})),
        "tatami_sentence": BlockSpec("Câu tatami", allowed=frozenset({"parts"}), required=frozenset({"parts"})),
        "running_sentence": BlockSpec("Câu running stitch", allowed=frozenset({"parts"}), required=frozenset({"parts"})),
        "thread_physics": BlockSpec("Vật lý sợi chỉ + độ nổi 3D (bất biến)", invariant=True),
        "anti_print": BlockSpec("Mệnh đề chống hình in (bất biến)", invariant=True),
    }

    def seed_rules(self) -> CategoryRules:
        return CategoryRules.model_validate(seed_dict())

    def normalize_fields(self, rules: CategoryRules, fields: dict) -> dict:
        try:
            rules.color(fields.get("garment_color") or "")
            rules.placement(fields.get("placement") or "")
        except KeyError as e:
            raise ValueError(e.args[0]) from None
        threads = [t.strip() for t in fields.get("thread_colors") or [] if t and t.strip()]
        if threads and not 2 <= len(threads) <= 5:
            raise ValueError(f"Thread Color: cần 2–5 màu (đang có {len(threads)}), hoặc để trống cho model đề xuất")
        if len({t.lower() for t in threads}) != len(threads):
            raise ValueError("Thread Color: có màu bị trùng")
        bad = non_english_chars(" ".join(threads))
        if bad:
            raise ValueError(f"Thread Color phải viết tên màu tiếng Anh (có ký tự {''.join(bad)!r})")
        return {"garment_color": fields["garment_color"], "placement": fields["placement"], "thread_colors": threads}

    def fixed_palette(self, fields: dict) -> list[str] | None:
        return list(fields.get("thread_colors") or []) or None

    def batch_options(self, rules: CategoryRules) -> list[tuple[str, str]]:
        return [(c.label, c.key) for c in rules.colors]

    def batch_value(self, fields: dict) -> str:
        return fields["garment_color"]

    def with_batch_value(self, fields: dict, key: str) -> dict:
        return {**fields, "garment_color": key}

    def batch_phrase(self, rules: CategoryRules, key: str) -> str:
        return rules.color(key).phrase

    def _garment_values(self, rules: CategoryRules, inputs: ProductInputs) -> dict:
        pt = rules.product_type(inputs.product_type)
        color = rules.color(inputs.fields["garment_color"])
        return {
            "garment": pt.phrase,
            "material": pt.material or "soft cotton-blend fabric",
            "color": color.phrase,
            "color_name": color.label,
        }

    def product_context(self, rules: CategoryRules, inputs: ProductInputs) -> str:
        g = self._garment_values(rules, inputs)
        placement = rules.placement(inputs.fields["placement"])
        return f"PRODUCT: {g['garment']} in {g['color']}. Embroidery placement: {placement.label}."

    def build_prompt(self, rules: CategoryRules, inputs: ProductInputs, design: Design, scene: ResolvedScene) -> str:
        b = rules.blocks
        g = self._garment_values(rules, inputs)
        placement = rules.placement(inputs.fields["placement"])

        para1 = fill(
            b["para1"], **g,
            camera=scene.camera, arrangement=scene.arrangement, surface=scene.surface,
            props=scene.props, lighting=scene.lighting, extra=scene.extra, aspect_ratio=inputs.aspect_ratio,
        )
        para2 = fill(b["para2"], **g, puckering=b["puckering"])

        intro = fill(
            b["para3_intro"], **g,
            motif=design.motif_summary,
            placement_clause=fill(placement.phrase, color_name=g["color_name"]),
        )
        bullets = [_bullet(el, design.palette) for el in design.elements]
        palette_line = fill(b["para3_palette"], threads=join_list(design.palette), thread_count=str(len(design.palette)))
        para3 = "\n".join([intro, *bullets, palette_line])

        sentences = []
        for technique, block in _TECHNIQUE_BLOCKS.items():
            parts = [_part_name(el) for el in design.elements if technique in el.techniques]
            if parts:
                sentences.append(fill(b[block], parts=join_list(parts)))
        para4 = fill(
            b["para4"], **g,
            technique_sentences=" ".join(sentences), thread_physics=b["thread_physics"], anti_print=b["anti_print"],
        )
        return "\n\n".join([para1, para2, para3, para4])

    def design_part(self, prompt: str) -> str:
        paragraphs = prompt.split("\n\n")
        return paragraphs[2] if len(paragraphs) >= 3 else ""


def _bullet(el: DesignElement, palette: list[str]) -> str:
    description = render_tokens(el.description, palette)
    head = _ROLE_LABELS[el.role]
    if el.role in TEXT_ROLES:
        return f'- {head} "{el.text}": {description}'
    return f"- {head} ({el.name}): {description}"


def _part_name(el: DesignElement) -> str:
    if el.role in TEXT_ROLES and el.text:
        return f'the "{el.text}" lettering'
    return f"the {el.name}"
