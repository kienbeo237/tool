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
        "design_instruction": BlockSpec(
            "Chỉ dẫn cho AI khi vẽ lại thiết kế", kind="instruction",
            purpose="Gửi cho AI cùng ảnh ý tưởng. Quyết định AI vẽ lại hình thêu thế nào: phong cách, độ đơn giản, "
                    "số màu chỉ, cách gộp 2 ý tưởng. Kết quả thành đoạn 3 của prompt.",
        ),
        "scene_instruction": BlockSpec(
            "Chỉ dẫn cho AI khi đọc ảnh nền", kind="instruction",
            purpose="Gửi cho AI khi bạn tải “Ảnh nền mới”. Quyết định AI mô tả bối cảnh trong ảnh ra sao "
                    "(góc máy, bề mặt, đạo cụ, ánh sáng) để đưa vào đoạn 1.",
        ),
        "default_camera": BlockSpec(
            "Góc máy mặc định", kind="default",
            purpose="Dùng khi concept nền / ảnh nền không nói góc máy. Điền vào chỗ {camera} của đoạn 1.",
        ),
        "default_lighting": BlockSpec(
            "Ánh sáng mặc định", kind="default",
            purpose="Dùng khi concept nền / ảnh nền không nói ánh sáng. Điền vào chỗ {lighting} của đoạn 1.",
        ),
        "default_arrangement": BlockSpec(
            "Cách đặt áo mặc định", kind="default",
            purpose="Dùng khi concept nền / ảnh nền không nói cách đặt áo (gấp, trải phẳng…). "
                    "Điền vào chỗ {arrangement} của đoạn 1.",
        ),
        "para1": BlockSpec(
            "Đoạn 1 — bối cảnh chụp",
            allowed=_GARMENT | {"camera", "arrangement", "surface", "props", "lighting", "extra", "aspect_ratio"},
            required=frozenset({"camera", "garment", "color", "surface", "props", "lighting", "extra"}),
            purpose="Mẫu câu của đoạn 1 trong prompt: góc máy, áo nằm trên bề mặt nào, đạo cụ, ánh sáng, tỷ lệ khung.",
        ),
        "para2": BlockSpec(
            "Đoạn 2 — chất liệu áo",
            allowed=_GARMENT | {"puckering"},
            required=frozenset({"garment", "puckering"}),
            purpose="Mẫu câu của đoạn 2: chất liệu vải, khung hình, và hiệu ứng vải bị kéo căng quanh hình thêu.",
        ),
        "puckering": BlockSpec(
            "Hiệu ứng kéo căng vải", invariant=True,
            purpose="Câu mô tả vải hơi nhăn, lõm quanh đường thêu — dấu hiệu của thêu thật. Chèn vào đoạn 2.",
        ),
        "para3_intro": BlockSpec(
            "Đoạn 3 — câu mở đầu thiết kế",
            allowed=_GARMENT | {"motif", "placement_clause"},
            required=frozenset({"motif", "placement_clause"}),
            purpose="Câu đầu đoạn 3: hình thêu là gì, đặt ở đâu và nhỏ cỡ nào trên áo. "
                    "Sau câu này là các gạch đầu dòng do AI viết.",
        ),
        "para3_palette": BlockSpec(
            "Đoạn 3 — dòng màu chỉ",
            allowed=frozenset({"threads", "thread_count"}),
            required=frozenset({"threads"}),
            purpose="Dòng cuối đoạn 3: liệt kê màu chỉ và phong cách màu (màu đặc, không chuyển sắc).",
        ),
        "para4": BlockSpec(
            "Đoạn 4 — kỹ thuật thêu và chốt",
            allowed=_GARMENT | {"technique_sentences", "thread_physics", "anti_print"},
            required=frozenset({"technique_sentences", "thread_physics", "anti_print"}),
            purpose="Mẫu câu của đoạn 4: các câu kỹ thuật mũi thêu, độ nổi của sợi chỉ, "
                    "và câu khẳng định đây là thêu thật chứ không phải in.",
        ),
        "satin_sentence": BlockSpec(
            "Câu mũi satin", allowed=frozenset({"parts"}), required=frozenset({"parts"}),
            purpose="Chỉ xuất hiện khi thiết kế có phần thêu satin (thường là chữ, viền). Ghép vào đoạn 4.",
        ),
        "tatami_sentence": BlockSpec(
            "Câu mũi tatami", allowed=frozenset({"parts"}), required=frozenset({"parts"}),
            purpose="Chỉ xuất hiện khi thiết kế có mảng lớn thêu tatami (lấp đầy). Ghép vào đoạn 4.",
        ),
        "running_sentence": BlockSpec(
            "Câu mũi chạy (running stitch)", allowed=frozenset({"parts"}), required=frozenset({"parts"}),
            purpose="Chỉ xuất hiện khi thiết kế có nét mảnh thêu running stitch. Ghép vào đoạn 4.",
        ),
        "thread_physics": BlockSpec(
            "Độ bóng và độ nổi của sợi chỉ", invariant=True,
            purpose="Câu mô tả sợi chỉ bóng, nổi 3D trên vải. Chèn vào đoạn 4.",
        ),
        "anti_print": BlockSpec(
            "Câu chống ra hình in", invariant=True,
            purpose="Câu cấm in lụa / DTG / vector phẳng, để ảnh ra phải trông như thêu thật. Chèn vào đoạn 4.",
        ),
    }
    placeholder_help = {
        "garment": "tên loại áo (vd. Gildan 18000 crewneck sweatshirt)",
        "material": "chất liệu của loại áo",
        "color": "màu áo kèm mã hex, vd. Maroon (#5b2333)",
        "color_name": "tên màu áo, vd. Maroon",
        "camera": "góc máy — từ concept nền / ảnh nền, thiếu thì lấy “Góc máy mặc định”",
        "arrangement": "cách đặt áo — từ concept nền / ảnh nền, thiếu thì lấy mặc định",
        "surface": "bề mặt đặt áo — từ concept nền / ảnh nền",
        "props": "đạo cụ xung quanh — từ concept nền / ảnh nền",
        "lighting": "ánh sáng — từ concept nền / ảnh nền, thiếu thì lấy mặc định",
        "extra": "yêu cầu thêm về bối cảnh từ Ghi chú tuỳ chỉnh (trống nếu không có)",
        "aspect_ratio": "tỷ lệ khung đã chọn, vd. 4:5",
        "puckering": "nguyên văn đoạn “Hiệu ứng kéo căng vải”",
        "motif": "tóm tắt hình thêu do AI viết",
        "placement_clause": "câu mô tả vị trí thêu (giữa ngực / ngực trái)",
        "threads": "danh sách màu chỉ, vd. Cream, Navy and Rust",
        "thread_count": "số màu chỉ",
        "technique_sentences": "các câu mũi satin / tatami / running mà thiết kế có dùng",
        "thread_physics": "nguyên văn đoạn “Độ bóng và độ nổi của sợi chỉ”",
        "anti_print": "nguyên văn đoạn “Câu chống ra hình in”",
        "parts": "các phần của thiết kế dùng mũi này, vd. the \"GOOD DAYS\" lettering",
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
