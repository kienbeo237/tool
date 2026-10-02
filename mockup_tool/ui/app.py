"""Giao diện Gradio. Chỉ gom input, gọi MockupService và hiển thị — không chứa logic dựng prompt."""

import functools
import html
import json
import logging
from datetime import datetime, timezone

import gradio as gr

from mockup_tool.config import Settings
from mockup_tool.engine.gemini_client import ModelError
from mockup_tool.engine.image_engines import GEMINI
from mockup_tool.engine.service import BatchItem, GenerateInput, MockupService, UserError
from mockup_tool.ui.theme import (card_header, empty_html, guide_html, header_html, meta_html, status_html,
                                  swatch_css)

log = logging.getLogger(__name__)

BG_MODES = [("Concept có sẵn", "preset"), ("Ảnh nền đã lưu", "saved"), ("Ảnh nền mới", "custom")]
# Lựa chọn hay lặp lại giữa các lần dùng — nhớ trong trình duyệt. Màu áo đổi theo từng thiết kế nên không nhớ.
PREF_KEYS = ("product_type", "placement", "aspect_ratio", "bg_preset")

# Cuộn tới khối kết quả khi màn hình hẹp (cột kết quả nằm dưới form) — chỉ khi đã có kết quả.
JS_SCROLL_RESULT = """() => { const guide = document.querySelector('#result-card .guide');
  if (window.innerWidth < 1000 && !(guide && guide.offsetParent !== null))
    document.querySelector('#result-card')?.scrollIntoView({behavior: 'smooth', block: 'start'}); }"""
JS_SCROLL_BATCH = """() => setTimeout(() =>
  document.querySelector('#batch-card')?.scrollIntoView({behavior: 'smooth', block: 'start'}), 250)"""
JS_COPY_PROMPT = """(text) => {
  const btn = document.querySelector('#copy-btn');
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    if (!btn) return;
    const old = btn.textContent; btn.textContent = 'Đã copy ✓'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = old; btn.classList.remove('copied'); }, 1600);
  });
}"""
# Ctrl/⌘ + Enter ở bất cứ đâu trong tab Tạo prompt = bấm Tạo prompt.
HEAD = """<script>
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key !== 'Enter') return;
  const btn = document.querySelector('#generate-btn');
  if (btn && btn.offsetParent !== null && !btn.disabled) { e.preventDefault(); btn.click(); }
});
</script>"""


# ---------------------------------------------------------------------------- tiện ích

def _guard(fn):
    """Đổi lỗi nghiệp vụ thành thông báo Gradio; lỗi lạ thì log đầy đủ."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (UserError, ModelError) as e:
            raise gr.Error(str(e), duration=None, print_exception=False) from e
        except gr.Error:
            raise
        except Exception as e:
            log.exception("Lỗi không lường trước trong %s", fn.__name__)
            raise gr.Error(f"Lỗi hệ thống: {e}", duration=None) from e
    return wrapper


def _guard_gen(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            yield from fn(*args, **kwargs)
        except (UserError, ModelError) as e:
            raise gr.Error(str(e), duration=None, print_exception=False) from e
        except Exception as e:
            log.exception("Lỗi không lường trước trong %s", fn.__name__)
            raise gr.Error(f"Lỗi hệ thống: {e}", duration=None) from e
    return wrapper


def _fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d/%m %H:%M")


def _int(value) -> int | None:
    try:
        value = str(value).strip().lstrip("#") if value is not None else ""
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _paths(files) -> list[str]:
    if not files:
        return []
    return [f if isinstance(f, str) else f.name for f in (files if isinstance(files, list) else [files])]


def _need(value, message: str) -> int:
    value = _int(value)
    if not value:
        raise UserError(message)
    return value


def _card(step, title: str, desc: str = ""):
    return gr.HTML(card_header(step, title, desc))


def _lock(label: str):
    """Khoá nút ngay khi bấm (chạy không qua hàng đợi) để không gửi trùng."""
    return lambda: gr.update(interactive=False, value=label)


def _unlock(label: str):
    return lambda: gr.update(interactive=True, value=label)


def _always(event, fn, inputs, outputs, js=None):
    """Chạy `fn` sau `event` dù thành công hay lỗi.

    Gradio 6.29: `.then` KHÔNG chạy khi bước trước raise gr.Error (trái với docstring), nên gắn
    cùng một bước vào cả `.success` và `.failure` — không thì nút bị khoá vĩnh viễn sau một lỗi.
    """
    event.success(fn, inputs, outputs, queue=False, js=js)
    event.failure(fn, inputs, outputs, queue=False)


def _pick(value, choices, default):
    keys = [c[1] if isinstance(c, (tuple, list)) else c for c in choices]
    return value if value in keys else default


# ---------------------------------------------------------------------------- app

def build_app(service: MockupService, settings: Settings) -> gr.Blocks:
    categories = service.categories
    default_category = next(iter(categories))
    single_category = len(categories) == 1

    def catalog_props(category_key: str, prefs: dict | None = None) -> list[dict]:
        """choices/value của mọi danh sách chọn, theo phiên bản quy tắc hiện tại của danh mục."""
        prefs = prefs or {}
        _, rules = service.active_rules(category_key)
        category = service.category(category_key)
        scenes = [(f"#{r['id']} · {r['label']}", r["id"]) for r in service.list_references("scene")]
        styles = [(f"#{r['id']} · {r['label']}", r["id"]) for r in service.list_references("style")]
        ptypes = [(p.label, p.key) for p in rules.product_types]
        places = [(p.label, p.key) for p in rules.placements]
        presets = [(b.label, b.key) for b in rules.backgrounds]
        return [
            {"choices": ptypes, "value": _pick(prefs.get("product_type"), ptypes, ptypes[0][1])},
            {"choices": [(c.label, c.key) for c in rules.colors], "value": rules.colors[0].key},
            {"choices": places, "value": _pick(prefs.get("placement"), places, places[0][1])},
            {"choices": presets, "value": _pick(prefs.get("bg_preset"), presets, presets[0][1])},
            {"choices": scenes, "value": scenes[0][1] if scenes else None,
             "info": None if scenes else "Chưa có ảnh nền nào. Dùng “Ảnh nền mới” một lần rồi bấm Lưu ảnh nền."},
            {"choices": styles, "value": [],
             "info": None if styles else "Chưa có ảnh style nào được lưu."},
            {"choices": rules.aspect_ratios,
             "value": _pick(prefs.get("aspect_ratio"), rules.aspect_ratios, rules.aspect_ratios[0])},
            {"choices": category.batch_options(rules), "value": []},
            {"value": swatch_css([(c.key, c.hex) for c in rules.colors])},
        ]

    def catalog(category_key: str, prefs: dict | None = None):
        return tuple(gr.update(**props) for props in catalog_props(category_key, prefs))

    (init_ptype, init_color, init_place, init_preset, init_saved, init_styles,
     init_aspect, init_batch, init_swatch) = catalog_props(default_category)

    def rules_view(cat):
        version, rules = service.active_rules(cat)
        spec_choices = [(f"{s.label}  ·  {k}", k) for k, s in service.category(cat).block_specs.items()]
        history = [[h["version"], _fmt_time(h["created_at"]), h["note"]] for h in service.rule_history(cat)]
        first = spec_choices[0][1]
        info = meta_html([f"Đang dùng <b>phiên bản {version}</b>", f"{len(history)} phiên bản đã lưu"])
        return (info, gr.update(choices=spec_choices, value=first), *block_view(cat, first),
                json.dumps(rules.model_dump(), ensure_ascii=False, indent=2), history)

    def block_view(cat, key):
        if not key:
            return "", ""
        spec = service.category(cat).block_specs[key]
        _, rules = service.active_rules(cat)
        lines = []
        if spec.invariant:
            lines.append("🔒 **Bất biến** — luôn có mặt nguyên văn trong prompt; Custom Note không ghi đè được.")
        lines.append("Placeholder được dùng: " + (", ".join(f"`{{{p}}}`" for p in sorted(spec.allowed)) or "_không có_"))
        if spec.required:
            lines.append("Bắt buộc có: " + ", ".join(f"`{{{p}}}`" for p in sorted(spec.required)))
        return "\n\n".join(lines), rules.blocks.get(key, "")

    init_info, init_block, init_help, init_text, init_json, init_history = rules_view(default_category)

    engine_choices = [(e.label if e.model.startswith("mock") else f"{e.label} · {e.model}", e.key)
                      for e in service.image_engines.values()]

    def names():
        """Mã → tên hiển thị cho bảng/chi tiết (DB lưu mã; người dùng đọc tên)."""
        _, rules = service.active_rules(default_category)
        products = {p.key: p.label for p in rules.product_types}
        colors = {c.key: c.label for c in rules.colors}
        return (lambda k: products.get(k, k or "")), (lambda k: colors.get(k, k or ""))

    with gr.Blocks(title="Mockup Prompt Tool", analytics_enabled=False) as demo:
        gr.HTML(header_html(settings.mock_gemini, service.client.text_model))
        swatch_style = gr.HTML(init_swatch["value"], padding=False, container=False)
        request_state = gr.State(None)
        prefs_state = gr.BrowserState({}, storage_key="mockup_tool_prefs")

        with gr.Tabs(elem_classes="main-tabs") as tabs:
            # ================================================================ TẠO PROMPT
            with gr.Tab("Tạo prompt", id="generate"):
                with gr.Row(equal_height=False):
                    # ---------------------------------------------------- cột nhập liệu
                    with gr.Column(scale=5, min_width=380):
                        with gr.Column(variant="panel", elem_classes="card"):
                            _card(1, "Sản phẩm")
                            category = gr.Dropdown(label="Danh mục", value=default_category, visible=not single_category,
                                                   choices=[(c.label, k) for k, c in categories.items()])
                            product_type = gr.Dropdown(label="Loại sản phẩm", **init_ptype)
                            placement = gr.Radio(label="Vị trí thêu", **init_place)
                            garment_color = gr.Radio(label="Màu áo", elem_classes="swatches", **init_color)

                        with gr.Column(variant="panel", elem_classes="card"):
                            _card(2, "Ý tưởng", "bắt buộc · 1–2 ảnh")
                            idea_files = gr.File(label="Ảnh ý tưởng", show_label=False, file_count="multiple",
                                                 file_types=["image"], type="filepath", height=110,
                                                 elem_classes="vi-upload")
                            gr.HTML('<div class="hint">2 ảnh = 2 ý tưởng được ghép thành một thiết kế. '
                                    'Tool chỉ lấy ý tưởng, không sao chép hình.</div>')
                            with gr.Accordion("Ảnh style tham khảo (tuỳ chọn, tối đa 3)", open=False):
                                style_files = gr.File(label="Tải ảnh style", show_label=False, file_count="multiple",
                                                      file_types=["image"], type="filepath", height=90,
                                                      elem_classes="vi-upload")
                                style_saved = gr.Dropdown(label="Hoặc chọn ảnh style đã lưu", multiselect=True,
                                                          **init_styles)

                        with gr.Column(variant="panel", elem_classes="card"):
                            _card(3, "Bối cảnh")
                            bg_mode = gr.Radio(show_label=False, choices=BG_MODES, value="preset", container=False)
                            with gr.Row():
                                bg_preset = gr.Dropdown(label="Concept bề mặt", scale=3, **init_preset)
                                bg_saved = gr.Dropdown(label="Ảnh nền đã lưu", scale=3, visible=False, **init_saved)
                                aspect_ratio = gr.Dropdown(label="Tỷ lệ khung", scale=1, min_width=110, **init_aspect)
                            bg_custom = gr.Image(label="Ảnh nền mới — tool đọc và lưu mô tả bối cảnh, không bắt chước",
                                                 type="filepath", visible=False, height=200, elem_classes="vi-upload")

                        with gr.Column(variant="panel", elem_classes="card"):
                            _card(4, "Màu chỉ & ghi chú", "tuỳ chọn")
                            thread_colors = gr.Textbox(
                                label="Màu chỉ", placeholder="Để trống = model tự chọn · vd: Cream, Burnt Orange, Sage Green",
                                info="Có nhập thì bắt buộc dùng đúng: 2–5 màu, tên tiếng Anh, cách nhau bằng dấu phẩy.")
                            custom_note = gr.Textbox(
                                label="Ghi chú tuỳ chỉnh (ưu tiên cao nhất)", lines=3,
                                placeholder="vd: chụp góc 45 độ, đặt trên bàn gỗ, bỏ nến…",
                                info="Đổi được góc chụp, mặt nền, props, ánh sáng, yêu cầu thiết kế. Viết tiếng Việt "
                                     "được. Không thể làm mất chất thêu.")

                        generate_btn = gr.Button("Tạo prompt", variant="primary", size="lg", elem_id="generate-btn")

                    # ---------------------------------------------------- cột kết quả
                    with gr.Column(scale=7, min_width=420):
                        with gr.Column(variant="panel", elem_classes="card", elem_id="result-card"):
                            _card(None, "Kết quả")
                            result_empty = gr.HTML(guide_html())
                            with gr.Column(visible=False) as result_body:
                                with gr.Row(equal_height=True, elem_classes="result-bar"):
                                    result_meta = gr.HTML()
                                    copy_btn = gr.Button("Copy prompt", variant="primary", size="sm", scale=0,
                                                         min_width=130, elem_id="copy-btn")
                                with gr.Tabs():
                                    with gr.Tab("Prompt"):
                                        prompt_box = gr.Textbox(
                                            show_label=False, lines=18, max_lines=40, interactive=True,
                                            elem_id="prompt-box",
                                            info="Sửa trực tiếp được — bản sửa là bản được copy và được duyệt.")
                                    with gr.Tab("Thiết kế (JSON)"):
                                        gr.Markdown("Sửa ở tầng thiết kế thì **làm theo lô dùng lại được**. Màu chỉ "
                                                    "trong `description` viết dạng `[T1]`, `[T2]`… trỏ vào `palette`.")
                                        design_code = gr.Code(language="json", interactive=True, lines=16,
                                                              show_label=False)
                                        rebuild_btn = gr.Button("Dựng lại prompt từ thiết kế", size="sm")
                                    with gr.Tab("Sinh ảnh"):
                                        gr.Markdown("Tuỳ chọn. Hai model nhận **cùng một prompt** ở tab Prompt — "
                                                    "sinh lần lượt để so sánh, mỗi ảnh ghi tên model. Không gửi ảnh "
                                                    "ý tưởng (tránh sao chép); ảnh nền đã lưu/mới được gửi kèm.",
                                                    elem_classes="hint")
                                        with gr.Row(equal_height=True, elem_classes="image-row"):
                                            image_engine = gr.Radio(engine_choices, value=GEMINI, show_label=False,
                                                                    container=False, scale=3, min_width=260)
                                            image_btn = gr.Button("Sinh ảnh", variant="primary", size="sm",
                                                                  scale=1, min_width=140)
                                        image_gallery = gr.Gallery(show_label=False, columns=2, height=440,
                                                                   buttons=["download", "fullscreen"])
                                with gr.Row(equal_height=True, elem_classes="approve-row"):
                                    canonical = gr.Checkbox(label="Mẫu chuẩn", scale=0, min_width=120,
                                                            info="model học theo")
                                    approve_note = gr.Textbox(show_label=False, placeholder="Ghi chú khi duyệt (tuỳ chọn)",
                                                              container=False, scale=4)
                                    approve_btn = gr.Button("Duyệt & lưu", variant="primary", scale=0, min_width=150)
                                approve_status = gr.HTML()
                                with gr.Accordion("Lưu ảnh tham chiếu vào thư viện", open=False,
                                                  visible=False) as refs_box:
                                    with gr.Row(equal_height=True):
                                        ref_label = gr.Textbox(show_label=False, container=False, scale=3,
                                                               placeholder="Tên gợi nhớ, vd: Sàn gỗ trắng")
                                        save_bg_btn = gr.Button("Lưu ảnh nền", size="sm", scale=1, visible=False)
                                        save_style_btn = gr.Button("Lưu ảnh style", size="sm", scale=1, visible=False)

                        with gr.Column(variant="panel", elem_classes="card", elem_id="batch-card",
                                       visible=False) as batch_card:
                            _card("↻", "Làm lại theo lô", "giữ nguyên thiết kế, chỉ đổi màu áo")
                            with gr.Row(equal_height=True):
                                batch_source = gr.Textbox(label="Từ request #", scale=0, min_width=120, max_lines=1,
                                                          placeholder="vd: 12")
                                batch_colors = gr.CheckboxGroup(label="Màu áo cần làm", elem_classes="swatches",
                                                                scale=5, min_width=300, **init_batch)
                            with gr.Row():
                                batch_all_btn = gr.Button("Chọn tất cả màu còn lại", size="sm", scale=0, min_width=180)
                                batch_clear_btn = gr.Button("Bỏ chọn", size="sm", scale=0, min_width=90)
                                batch_btn = gr.Button("Tạo lô", variant="primary", scale=1, interactive=False)
                            batch_md = gr.Markdown(elem_classes="batch-out")
                            batch_file = gr.File(label="Tải tất cả prompt của lô (.txt)", visible=False)

            # ================================================================ THƯ VIỆN
            with gr.Tab("Thư viện", id="library") as lib_tab:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=6, variant="panel", elem_classes="card"):
                        _card(None, "Prompt đã duyệt", "bấm một dòng để xem")
                        lib_canonical_only = gr.Checkbox(label="Chỉ hiện mẫu chuẩn")
                        lib_empty = gr.HTML(empty_html("Chưa có prompt nào được duyệt. "
                                                       "Tạo prompt rồi bấm “Duyệt & lưu” để đưa vào đây."))
                        lib_table = gr.Dataframe(
                            headers=["ID", "Ngày", "Sản phẩm", "Màu áo", "Motif", "★", "Ghi chú"],
                            interactive=False, wrap=True, max_height=520, elem_classes="tbl", visible=False,
                            column_widths=["7%", "12%", "16%", "13%", "32%", "5%", "15%"])
                    with gr.Column(scale=5, variant="panel", elem_classes="card"):
                        _card(None, "Chi tiết")
                        lib_selected = gr.State(None)
                        lib_meta = gr.HTML(empty_html("Chọn một dòng ở bảng bên trái để xem prompt."))
                        with gr.Column(visible=False) as lib_body:
                            lib_prompt = gr.Textbox(show_label=False, lines=14, buttons=["copy"], interactive=False)
                            lib_images = gr.Gallery(label="Ảnh đã sinh", columns=3, height=220, visible=False,
                                                    buttons=["download", "fullscreen"])
                            with gr.Row():
                                lib_batch_btn = gr.Button("Dùng làm nguồn cho lô", size="sm", variant="primary")
                                lib_toggle_btn = gr.Button("Đặt làm mẫu chuẩn", size="sm")
                                lib_delete_btn = gr.Button("Xoá…", size="sm", variant="stop")
                            with gr.Row(visible=False, elem_classes="confirm-row") as lib_confirm:
                                gr.HTML('<div class="confirm-text">Xoá prompt này khỏi thư viện? '
                                        'Model sẽ không còn học theo nó.</div>')
                                lib_confirm_btn = gr.Button("Xoá", size="sm", variant="stop", scale=0, min_width=90)
                                lib_cancel_btn = gr.Button("Huỷ", size="sm", scale=0, min_width=90)

                with gr.Column(variant="panel", elem_classes="card"):
                    _card(None, "Ảnh tham chiếu đã lưu", "bấm một ảnh để xem mô tả")
                    ref_kind = gr.Radio([("Ảnh nền", "scene"), ("Style", "style")], value="scene",
                                        show_label=False, container=False)
                    ref_selected = gr.State(None)
                    ref_empty = gr.HTML(empty_html("Chưa có ảnh nào. Ảnh nền/style lưu từ phần Kết quả sẽ hiện ở đây."))
                    with gr.Row(equal_height=False, visible=False) as ref_body:
                        ref_gallery = gr.Gallery(show_label=False, columns=5, height=300, scale=3,
                                                 buttons=["download", "fullscreen"])
                        with gr.Column(scale=2):
                            ref_desc = gr.JSON(label="Mô tả bối cảnh đã lưu", visible=False)
                            ref_remove_btn = gr.Button("Bỏ ảnh đang chọn khỏi thư viện…", size="sm",
                                                       variant="stop", interactive=False)
                            with gr.Row(visible=False, elem_classes="confirm-row") as ref_confirm:
                                gr.HTML('<div class="confirm-text">Bỏ ảnh này? Request cũ vẫn giữ nguyên.</div>')
                                ref_confirm_btn = gr.Button("Bỏ", size="sm", variant="stop", scale=0, min_width=80)
                                ref_cancel_btn = gr.Button("Huỷ", size="sm", scale=0, min_width=80)

            # ================================================================ LỊCH SỬ
            with gr.Tab("Lịch sử", id="history") as hist_tab:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=6, variant="panel", elem_classes="card"):
                        _card(None, "Mọi lần tạo prompt", "100 lần gần nhất · bấm một dòng để xem")
                        hist_empty = gr.HTML(empty_html("Chưa tạo prompt nào."))
                        hist_table = gr.Dataframe(
                            headers=["ID", "Ngày", "Sản phẩm", "Màu áo", "Motif", "Trạng thái", "Lô từ #"],
                            interactive=False, wrap=True, max_height=560, elem_classes="tbl", visible=False,
                            column_widths=["7%", "12%", "17%", "13%", "31%", "11%", "9%"])
                    with gr.Column(scale=5, variant="panel", elem_classes="card"):
                        _card(None, "Chi tiết")
                        hist_selected = gr.State(None)
                        hist_info = gr.HTML(empty_html("Chọn một dòng ở bảng bên trái để xem prompt."))
                        with gr.Column(visible=False) as hist_body:
                            hist_prompt = gr.Textbox(show_label=False, lines=12, buttons=["copy"], interactive=False)
                            hist_batch_btn = gr.Button("Dùng làm nguồn cho lô", size="sm", variant="primary")
                            with gr.Accordion("Chi tiết kỹ thuật — thiết kế, output thô của model", open=False):
                                hist_design = gr.JSON(label="Thiết kế")
                                hist_raw = gr.JSON(label="Output thô của model")

            # ================================================================ QUY TẮC
            with gr.Tab("Quy tắc", id="rules"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=4, variant="panel", elem_classes="card"):
                        _card(None, "Phiên bản", "mỗi lần lưu tạo một phiên bản mới")
                        rules_category = gr.Dropdown(label="Danh mục", value=default_category,
                                                     visible=not single_category,
                                                     choices=[(c.label, k) for k, c in categories.items()])
                        rules_info = gr.HTML(init_info)
                        rules_history = gr.Dataframe(init_history, headers=["Bản", "Ngày", "Ghi chú"],
                                                     interactive=False, max_height=300, elem_classes="tbl",
                                                     column_widths=["14%", "26%", "60%"])
                        with gr.Row(equal_height=False, elem_classes="bottom-row"):
                            restore_version = gr.Textbox(label="Khôi phục bản số", placeholder="vd: 1", max_lines=1,
                                                         scale=1, min_width=120,
                                                         info="tạo phiên bản mới, không xoá bản nào")
                            restore_btn = gr.Button("Khôi phục", scale=0, min_width=120)
                    with gr.Column(scale=6, variant="panel", elem_classes="card"):
                        _card(None, "Sửa quy tắc", "100% tiếng Anh")
                        block_key = gr.Dropdown(label="Đoạn quy tắc", choices=init_block["choices"],
                                                value=init_block["value"])
                        block_help = gr.Markdown(init_help)
                        block_text = gr.Textbox(show_label=False, lines=10, value=init_text)
                        with gr.Row(equal_height=True):
                            block_note = gr.Textbox(show_label=False, placeholder="Ghi chú thay đổi (vd: tăng độ nổi chỉ)",
                                                    container=False, scale=3)
                            block_save_btn = gr.Button("Lưu phiên bản mới", variant="primary", scale=0, min_width=210)
                        with gr.Accordion("Danh mục chọn & toàn bộ quy tắc — JSON nâng cao", open=False):
                            gr.Markdown("Sửa loại sản phẩm, bảng màu áo (kèm mã hex), vị trí thêu, concept nền, tỷ lệ "
                                        "khung. `surface` của concept nền bắt đầu bằng giới từ (vd. `laid flat on ...`).")
                            rules_json = gr.Code(init_json, language="json", interactive=True, lines=24, show_label=False)
                            with gr.Row(equal_height=True):
                                rules_json_note = gr.Textbox(show_label=False, placeholder="Ghi chú thay đổi",
                                                             container=False, scale=3)
                                rules_json_save_btn = gr.Button("Lưu JSON thành phiên bản mới", variant="primary", scale=1)

        catalog_outputs = [product_type, garment_color, placement, bg_preset, bg_saved, style_saved,
                           aspect_ratio, batch_colors, swatch_style]

        # ------------------------------------------------------------------ handlers: tạo prompt

        def on_bg_mode(mode):
            return (gr.update(visible=mode == "preset"), gr.update(visible=mode == "saved"),
                    gr.update(visible=mode == "custom"))

        def result_chips(request_id, version, example_ids, extra=None):
            examples = ", ".join(f"#{i}" for i in example_ids) or "chưa có"
            chips = [f"Request <b>#{request_id}</b>", f"Quy tắc <b>v{version}</b>", f"Học theo mẫu: {examples}"]
            return chips + ([extra] if extra else [])

        @_guard
        def on_generate(cat, ptype, color, place, ideas, styles, styles_saved, mode, preset, saved, custom,
                        threads, note, aspect):
            result = service.generate(GenerateInput(
                category=cat, product_type=ptype,
                fields={"garment_color": color, "placement": place,
                        "thread_colors": [t for t in (threads or "").split(",") if t.strip()]},
                aspect_ratio=aspect, background_mode=mode, background_preset=preset,
                background_reference_id=_int(saved), background_image=custom,
                idea_images=_paths(ideas), style_images=_paths(styles),
                style_reference_ids=[int(i) for i in styles_saved or []], custom_note=note or "",
            ))
            meta = meta_html(result_chips(result.request_id, result.rules_version, result.used_example_ids),
                             result.warnings)
            can_save_bg, can_save_style = mode == "custom", bool(_paths(styles))
            return (
                result.request_id, gr.update(visible=False), gr.update(visible=True), meta, result.prompt,
                result.design_json, [], gr.update(value="Duyệt & lưu", interactive=True), "", False, "",
                gr.update(visible=can_save_bg or can_save_style, open=False),
                gr.update(visible=can_save_bg), gr.update(visible=can_save_style),
                # Lô: nguồn = request vừa tạo, gợi sẵn mọi màu khác màu vừa làm.
                gr.update(visible=True), str(result.request_id), other_colors(cat, color),
                "", gr.update(value=None, visible=False),
            )

        def other_colors(cat, source_color):
            _, rules = service.active_rules(cat)
            return [k for _, k in service.category(cat).batch_options(rules) if k != source_color]

        @_guard
        def on_rebuild(request_id, design_text):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            result = service.rebuild_from_design(request_id, design_text or "")
            meta = meta_html(result_chips(result.request_id, result.rules_version, result.used_example_ids,
                                          "Đã dựng lại từ thiết kế"), result.warnings)
            gr.Info("Đã dựng lại prompt từ thiết kế.")
            return meta, result.prompt, result.design_json, gr.update(value="Duyệt & lưu", interactive=True), ""

        @_guard
        def on_approve(request_id, prompt, is_canonical, note, canonical_only):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            example_id, warnings = service.approve(request_id, prompt or "", bool(is_canonical), note or "")
            for w in warnings:
                gr.Warning(w)
            status = status_html(f"Đã lưu vào thư viện <b>#{example_id}</b>"
                                 + (" · ★ mẫu chuẩn — model sẽ ưu tiên học theo" if is_canonical else ""))
            return (gr.update(value="Đã duyệt ✓", interactive=False), status, *library_view(canonical_only))

        def on_prompt_edit():
            # Sửa sau khi duyệt = một bản mới cần duyệt lại.
            return gr.update(value="Duyệt bản đã sửa", interactive=True), ""

        @_guard
        def on_save_bg(request_id, label, cat, prefs):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            ref_id = service.save_scene_reference(request_id, label or "")
            gr.Info(f"Đã lưu ảnh nền #{ref_id} — lần sau chọn ở “Ảnh nền đã lưu”.")
            return catalog(cat, prefs)

        @_guard
        def on_save_style(request_id, label, cat, prefs):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            ids = service.save_style_references(request_id, label or "")
            gr.Info(f"Đã lưu {len(ids)} ảnh style vào thư viện.")
            return catalog(cat, prefs)

        @_guard
        def on_batch_all(cat, source_id):
            source_color = None
            if _int(source_id):
                try:
                    source_color = service.get_request(_int(source_id))["fields"].get("garment_color")
                except UserError:
                    pass
            return other_colors(cat, source_color)

        def batch_ready(colors):
            n = len(colors or [])
            return gr.update(interactive=n > 0, value=f"Tạo lô · {n} màu" if n else "Chọn ít nhất 1 màu")

        @_guard_gen
        def on_batch(source_id, keys):
            source_id = _need(source_id, "Nhập request nguồn (mặc định là request vừa tạo)")
            keys = list(keys or [])
            blocks, warnings, texts = [], [], []
            yield _batch_md(warnings, blocks, len(keys), done=False), gr.update(visible=False)
            for item in service.regenerate_batch(source_id, keys):
                if isinstance(item, str):
                    warnings.append(item)
                    continue
                assert isinstance(item, BatchItem)
                blocks.append(f"#### {item.label} · request #{item.request_id}\n```text\n{item.prompt}\n```")
                texts.append(f"===== {item.label} (request #{item.request_id}) =====\n\n{item.prompt}\n")
                yield _batch_md(warnings, blocks, len(keys), done=False), gr.update(visible=False)
            path = service.files.write_export(f"batch_{source_id}_{datetime.now():%Y%m%d_%H%M%S}.txt", "\n\n".join(texts))
            yield _batch_md(warnings, blocks, len(keys), done=True), gr.update(value=str(path), visible=True)

        def _batch_md(warnings, blocks, total, done):
            head = "".join(f"> ⚠ {w}\n\n" for w in warnings)
            status = (f"**✓ Xong {len(blocks)} màu** — tải file .txt bên dưới hoặc copy từng prompt."
                      if done else f"_Đang làm… {len(blocks)}/{total} màu._")
            return head + status + "\n\n" + "\n\n".join(blocks)

        @_guard
        def on_image(request_id, prompt, engine):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            service.generate_image(request_id, prompt or "", engine or GEMINI)
            return service.generation_items(request_id)

        def save_prefs(prefs, ptype, place, aspect, preset):
            return {**(prefs or {}), **dict(zip(PREF_KEYS, (ptype, place, aspect, preset)))}

        category.change(catalog, [category, prefs_state], catalog_outputs)
        bg_mode.change(on_bg_mode, bg_mode, [bg_preset, bg_saved, bg_custom])
        gr.on([product_type.input, placement.input, aspect_ratio.input, bg_preset.input], save_prefs,
              [prefs_state, product_type, placement, aspect_ratio, bg_preset], prefs_state, queue=False)
        image_engine.input(lambda prefs, engine: {**(prefs or {}), "image_engine": engine},
                           [prefs_state, image_engine], prefs_state, queue=False)

        generate = generate_btn.click(_lock("Đang tạo prompt…"), None, generate_btn, queue=False).then(
            on_generate,
            [category, product_type, garment_color, placement, idea_files, style_files, style_saved, bg_mode,
             bg_preset, bg_saved, bg_custom, thread_colors, custom_note, aspect_ratio],
            [request_state, result_empty, result_body, result_meta, prompt_box, design_code, image_gallery,
             approve_btn, approve_status, canonical, approve_note, refs_box, save_bg_btn, save_style_btn,
             batch_card, batch_source, batch_colors, batch_md, batch_file],
            concurrency_limit=2,
        )
        _always(generate, _unlock("Tạo prompt"), None, generate_btn, js=JS_SCROLL_RESULT)

        copy_btn.click(None, prompt_box, None, js=JS_COPY_PROMPT)
        prompt_box.input(on_prompt_edit, None, [approve_btn, approve_status], queue=False)
        rebuild = rebuild_btn.click(_lock("Đang dựng lại…"), None, rebuild_btn, queue=False).then(
            on_rebuild, [request_state, design_code], [result_meta, prompt_box, design_code, approve_btn,
                                                       approve_status])
        _always(rebuild, _unlock("Dựng lại prompt từ thiết kế"), None, rebuild_btn)
        save_bg_btn.click(on_save_bg, [request_state, ref_label, category, prefs_state], catalog_outputs)
        save_style_btn.click(on_save_style, [request_state, ref_label, category, prefs_state], catalog_outputs)

        batch_colors.change(batch_ready, batch_colors, batch_btn, queue=False)
        batch_all_btn.click(on_batch_all, [category, batch_source], batch_colors)
        batch_clear_btn.click(lambda: [], None, batch_colors, queue=False)
        batch = batch_btn.click(_lock("Đang làm lô…"), None, batch_btn, queue=False).then(
            on_batch, [batch_source, batch_colors], [batch_md, batch_file], concurrency_limit=1)
        _always(batch, batch_ready, batch_colors, batch_btn)
        image = image_btn.click(_lock("Đang sinh ảnh…"), None, image_btn, queue=False).then(
            on_image, [request_state, prompt_box, image_engine], image_gallery, concurrency_limit=1)
        _always(image, _unlock("Sinh ảnh"), None, image_btn)

        # ------------------------------------------------------------------ handlers: thư viện

        def library_view(canonical_only):
            product, color = names()
            rows = [[r["id"], _fmt_time(r["created_at"]), product(r["product_type"]), color(r["garment_color"]),
                     r["motif"], "★" if r["is_canonical"] else "", r["note"]]
                    for r in service.list_approved(canonical_only=bool(canonical_only))]
            empty = ("Chưa có mẫu chuẩn nào. Chọn một prompt rồi bấm “Bật/tắt mẫu chuẩn”." if canonical_only else
                     "Chưa có prompt nào được duyệt. Tạo prompt rồi bấm “Duyệt & lưu” để đưa vào đây.")
            return gr.update(value=rows, visible=bool(rows)), gr.update(value=empty_html(empty), visible=not rows)

        def lib_detail(example_id):
            ex = service.get_approved(example_id)
            product, color = names()
            chips = [f"<b>#{ex['id']}</b>", html.escape(product(ex["product_type"])),
                     html.escape(color(ex["garment_color"])),
                     f"Quy tắc v{ex['rules_version']}", _fmt_time(ex["created_at"])]
            if ex["is_canonical"]:
                chips.insert(1, "★ Mẫu chuẩn")
            if ex["note"]:
                chips.append(html.escape(ex["note"]))
            return (example_id, meta_html(chips), ex["prompt_text"],
                    gr.update(value=ex["images"], visible=bool(ex["images"])), gr.update(visible=True),
                    "Bỏ mẫu chuẩn" if ex["is_canonical"] else "Đặt làm mẫu chuẩn")

        lib_cleared = (None, empty_html("Chọn một dòng ở bảng bên trái để xem prompt."), "", gr.update(value=[]),
                       gr.update(visible=False), "Đặt làm mẫu chuẩn")

        approve_btn.click(on_approve, [request_state, prompt_box, canonical, approve_note, lib_canonical_only],
                          [approve_btn, approve_status, lib_table, lib_empty])

        @_guard
        def on_lib_select(evt: gr.SelectData):
            example_id = _int((evt.row_value or [None])[0])
            if not example_id:
                return (*lib_cleared, gr.update(visible=False), gr.update(visible=True))
            return (*lib_detail(example_id), gr.update(visible=False), gr.update(visible=True))

        @_guard
        def on_lib_toggle(example_id, canonical_only):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            ex = service.get_approved(example_id)
            service.set_canonical(example_id, not ex["is_canonical"])
            gr.Info(f"#{example_id}: {'đã bỏ khỏi' if ex['is_canonical'] else 'đã đặt làm'} mẫu chuẩn.")
            detail = lib_detail(example_id)
            return (*library_view(canonical_only), detail[1], detail[5])

        @_guard
        def on_lib_delete(example_id, canonical_only):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            service.delete_approved(example_id)
            gr.Info(f"Đã xoá #{example_id} khỏi thư viện.")
            return (*library_view(canonical_only), *lib_cleared, gr.update(visible=False), gr.update(visible=True))

        @_guard
        def on_lib_batch(example_id, cat):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            ex = service.get_approved(example_id)
            source = service.get_request(ex["request_id"])
            gr.Info(f"Đã chọn request #{ex['request_id']} làm nguồn — chọn màu rồi bấm Tạo lô.")
            return (gr.Tabs(selected="generate"), gr.update(visible=True), str(ex["request_id"]),
                    other_colors(cat, source["fields"].get("garment_color")), "", gr.update(visible=False))

        def refs_view(kind):
            refs = service.list_references(kind)
            items = [(r["path"], f"#{r['id']} · {r['label']}") for r in refs]
            return (gr.update(visible=bool(items)), items, gr.update(visible=not items), None,
                    gr.update(value=None, visible=False), gr.update(interactive=False), gr.update(visible=False))

        refs_outputs = [ref_body, ref_gallery, ref_empty, ref_selected, ref_desc, ref_remove_btn, ref_confirm]

        def on_ref_select(kind, evt: gr.SelectData):
            refs = service.list_references(kind)
            if evt.index is None or evt.index >= len(refs):
                return None, gr.update(visible=False), gr.update(interactive=False)
            ref = refs[evt.index]
            return (ref["id"], gr.update(value=ref["description"], visible=bool(ref["description"])),
                    gr.update(interactive=True))

        @_guard
        def on_ref_remove(ref_id, kind, cat, prefs):
            ref_id = _need(ref_id, "Bấm chọn một ảnh trước")
            service.remove_reference(ref_id)
            gr.Info(f"Đã bỏ ảnh #{ref_id} khỏi thư viện.")
            return (*refs_view(kind), *catalog(cat, prefs))

        def show_confirm():
            return gr.update(visible=False), gr.update(visible=True)

        def hide_confirm():
            return gr.update(visible=True), gr.update(visible=False)

        lib_tab.select(library_view, lib_canonical_only, [lib_table, lib_empty], queue=False)
        lib_tab.select(refs_view, ref_kind, refs_outputs, queue=False)
        lib_canonical_only.change(library_view, lib_canonical_only, [lib_table, lib_empty])
        lib_detail_outputs = [lib_selected, lib_meta, lib_prompt, lib_images, lib_body, lib_toggle_btn]
        lib_table.select(on_lib_select, None, [*lib_detail_outputs, lib_confirm, lib_delete_btn])
        lib_toggle_btn.click(on_lib_toggle, [lib_selected, lib_canonical_only],
                             [lib_table, lib_empty, lib_meta, lib_toggle_btn])
        lib_delete_btn.click(show_confirm, None, [lib_delete_btn, lib_confirm], queue=False)
        lib_cancel_btn.click(hide_confirm, None, [lib_delete_btn, lib_confirm], queue=False)
        lib_confirm_btn.click(on_lib_delete, [lib_selected, lib_canonical_only],
                              [lib_table, lib_empty, *lib_detail_outputs, lib_confirm, lib_delete_btn])
        lib_batch_btn.click(on_lib_batch, [lib_selected, category],
                            [tabs, batch_card, batch_source, batch_colors, batch_md, batch_file]
                            ).success(None, None, None, js=JS_SCROLL_BATCH)

        ref_kind.change(refs_view, ref_kind, refs_outputs)
        ref_gallery.select(on_ref_select, ref_kind, [ref_selected, ref_desc, ref_remove_btn])
        ref_remove_btn.click(show_confirm, None, [ref_remove_btn, ref_confirm], queue=False)
        ref_cancel_btn.click(hide_confirm, None, [ref_remove_btn, ref_confirm], queue=False)
        ref_removed = ref_confirm_btn.click(on_ref_remove, [ref_selected, ref_kind, category, prefs_state],
                                            [*refs_outputs, *catalog_outputs])
        _always(ref_removed, hide_confirm, None, [ref_remove_btn, ref_confirm])

        # ------------------------------------------------------------------ handlers: lịch sử

        def history_view():
            status = {"ok": "Đã tạo", "approved": "Đã duyệt", "error": "Lỗi"}
            product, color = names()
            rows = [[r["id"], _fmt_time(r["created_at"]), product(r["product_type"]),
                     color(r["fields"].get("garment_color", "")),
                     r["motif"] or r["error"][:80], status.get(r["status"], r["status"]), r["source_request_id"] or ""]
                    for r in service.list_requests()]
            return gr.update(value=rows, visible=bool(rows)), gr.update(visible=not rows)

        @_guard
        def on_hist_select(evt: gr.SelectData):
            request_id = _int((evt.row_value or [None])[0])
            if not request_id:
                return (None, empty_html("Chọn một dòng ở bảng bên trái để xem prompt."), "", None, None,
                        gr.update(visible=False))
            r = service.get_request(request_id)
            status = {"ok": "Đã tạo", "approved": "Đã duyệt", "error": "Lỗi"}
            chips = [f"<b>#{r['id']}</b>", status.get(r["status"], r["status"]), f"Quy tắc v{r['rules_version']}"]
            if r["text_edited"]:
                chips.append("Đã sửa tay")
            if r["source_request_id"]:
                chips.append(f"Lô từ #{r['source_request_id']}")
            if r["custom_note"]:
                chips.append("Ghi chú: " + html.escape(r["custom_note"]))
            return (request_id, meta_html(chips, [r["error"]] if r["error"] else None), r["prompt_text"],
                    r["design_json"], r["model_raw"], gr.update(visible=True))

        @_guard
        def on_hist_batch(request_id, cat):
            request_id = _need(request_id, "Chọn một dòng trong bảng trước")
            source = service.get_request(request_id)
            if not source["design_json"]:
                raise UserError(f"Request #{request_id} không có thiết kế (có thể đã lỗi) — không làm lô được")
            gr.Info(f"Đã chọn request #{request_id} làm nguồn — chọn màu rồi bấm Tạo lô.")
            return (gr.Tabs(selected="generate"), gr.update(visible=True), str(request_id),
                    other_colors(cat, source["fields"].get("garment_color")), "", gr.update(visible=False))

        hist_tab.select(history_view, None, [hist_table, hist_empty], queue=False)
        hist_table.select(on_hist_select, None,
                          [hist_selected, hist_info, hist_prompt, hist_design, hist_raw, hist_body])
        hist_batch_btn.click(on_hist_batch, [hist_selected, category],
                             [tabs, batch_card, batch_source, batch_colors, batch_md, batch_file]
                             ).success(None, None, None, js=JS_SCROLL_BATCH)

        # ------------------------------------------------------------------ handlers: quy tắc

        rules_outputs = [rules_info, block_key, block_help, block_text, rules_json, rules_history]

        @_guard
        def on_block_save(cat, key, text, note, prefs):
            version = service.save_block(cat, key, text or "", note or "")
            gr.Info(f"Đã lưu phiên bản {version}. Lần tạo prompt tiếp theo dùng bản này.")
            view = rules_view(cat)
            return (*view[:1], gr.update(value=key), *block_view(cat, key), *view[4:], "", *catalog(cat, prefs))

        @_guard
        def on_json_save(cat, text, note, prefs):
            try:
                content = json.loads(text or "")
            except json.JSONDecodeError as e:
                raise UserError(f"JSON sai cú pháp: dòng {e.lineno}, cột {e.colno}: {e.msg}") from None
            version = service.save_rules(cat, content, note or "Sửa JSON")
            gr.Info(f"Đã lưu phiên bản {version}.")
            return (*rules_view(cat), "", *catalog(cat, prefs))

        @_guard
        def on_restore(cat, version, prefs):
            version = _need(version, "Nhập số phiên bản cần khôi phục")
            new_version = service.restore_rules(cat, version)
            gr.Info(f"Đã khôi phục nội dung bản {version} thành phiên bản {new_version}.")
            return (*rules_view(cat), "", *catalog(cat, prefs))

        def on_history_pick(evt: gr.SelectData):
            return str((evt.row_value or [""])[0])

        rules_category.change(rules_view, rules_category, rules_outputs)
        block_key.change(block_view, [rules_category, block_key], [block_help, block_text])
        block_save_btn.click(on_block_save, [rules_category, block_key, block_text, block_note, prefs_state],
                             [*rules_outputs, block_note, *catalog_outputs])
        rules_json_save_btn.click(on_json_save, [rules_category, rules_json, rules_json_note, prefs_state],
                                  [*rules_outputs, rules_json_note, *catalog_outputs])
        rules_history.select(on_history_pick, None, restore_version, queue=False)
        restore_btn.click(on_restore, [rules_category, restore_version, prefs_state],
                          [*rules_outputs, restore_version, *catalog_outputs])

        # ------------------------------------------------------------------ nạp lần đầu

        def on_load(prefs):
            engine = _pick((prefs or {}).get("image_engine"), engine_choices, GEMINI)
            return *catalog(default_category, prefs), engine

        demo.load(on_load, prefs_state, [*catalog_outputs, image_engine])

    return demo
