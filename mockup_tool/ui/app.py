"""Giao diện Gradio. Chỉ gom input, gọi MockupService và hiển thị — không chứa logic dựng prompt."""

import functools
import html
import json
import logging
from datetime import datetime, timezone

import gradio as gr

from mockup_tool.config import Settings
from mockup_tool.engine.gemini_client import ModelError
from mockup_tool.engine.service import BatchItem, GenerateInput, MockupService, UserError
from mockup_tool.ui.theme import card_header, empty_html, header_html, meta_html, swatch_css

log = logging.getLogger(__name__)

BG_MODES = [("Concept có sẵn", "preset"), ("Ảnh nền đã lưu", "saved"), ("Ảnh nền mới", "custom")]


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


# ---------------------------------------------------------------------------- app

def build_app(service: MockupService, settings: Settings) -> gr.Blocks:
    categories = service.categories
    default_category = next(iter(categories))
    single_category = len(categories) == 1

    def catalog_props(category_key: str) -> list[dict]:
        """choices/value của mọi danh sách chọn, theo phiên bản quy tắc hiện tại của danh mục."""
        _, rules = service.active_rules(category_key)
        category = service.category(category_key)
        scenes = [(f"#{r['id']} · {r['label']}", r["id"]) for r in service.list_references("scene")]
        styles = [(f"#{r['id']} · {r['label']}", r["id"]) for r in service.list_references("style")]
        return [
            {"choices": [(p.label, p.key) for p in rules.product_types], "value": rules.product_types[0].key},
            {"choices": [(c.label, c.key) for c in rules.colors], "value": rules.colors[0].key},
            {"choices": [(p.label, p.key) for p in rules.placements], "value": rules.placements[0].key},
            {"choices": [(b.label, b.key) for b in rules.backgrounds], "value": rules.backgrounds[0].key},
            {"choices": scenes, "value": scenes[0][1] if scenes else None},
            {"choices": styles, "value": []},
            {"choices": rules.aspect_ratios, "value": rules.aspect_ratios[0]},
            {"choices": category.batch_options(rules), "value": []},
            {"value": swatch_css([(c.key, c.hex) for c in rules.colors])},
        ]

    def catalog(category_key: str):
        return tuple(gr.update(**props) for props in catalog_props(category_key))

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

    with gr.Blocks(title="Mockup Prompt Tool", analytics_enabled=False) as demo:
        gr.HTML(header_html(settings.mock_gemini, service.client.text_model))
        swatch_style = gr.HTML(init_swatch["value"], padding=False, container=False)
        request_state = gr.State(None)

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
                            _card(2, "Ý tưởng", "1–2 ảnh · 2 ảnh = 2 ý tưởng cần ghép")
                            idea_files = gr.File(label="Ảnh ý tưởng", show_label=False, file_count="multiple",
                                                 file_types=["image"], type="filepath", height=120)
                            with gr.Accordion("Ảnh style tham khảo (tuỳ chọn, tối đa 3)", open=False):
                                style_files = gr.File(label="Tải ảnh style", file_count="multiple",
                                                      file_types=["image"], type="filepath", height=100)
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
                                                 type="filepath", visible=False, height=200)

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
                        with gr.Column(variant="panel", elem_classes="card"):
                            _card(None, "Kết quả")
                            result_meta = gr.HTML(empty_html("Chưa có prompt. Điền thông tin bên trái rồi bấm Tạo prompt."))
                            with gr.Tabs():
                                with gr.Tab("Prompt"):
                                    prompt_box = gr.Textbox(
                                        show_label=False, lines=18, max_lines=40, buttons=["copy"], interactive=True,
                                        elem_id="prompt-box",
                                        placeholder="Prompt 4 đoạn sẽ hiện ở đây. Sửa trực tiếp được trước khi copy hoặc duyệt.")
                                with gr.Tab("Thiết kế (JSON)"):
                                    gr.Markdown("Sửa ở tầng thiết kế thì **làm theo lô dùng lại được**. Màu chỉ trong "
                                                "`description` viết dạng `[T1]`, `[T2]`… trỏ vào `palette`.")
                                    design_code = gr.Code(language="json", interactive=True, lines=16, show_label=False)
                                    rebuild_btn = gr.Button("Dựng lại prompt từ thiết kế", size="sm")
                                with gr.Tab("Sinh ảnh"):
                                    gr.Markdown("Tuỳ chọn. Dùng đúng prompt ở tab Prompt; không gửi ảnh ý tưởng để tránh "
                                                "sao chép. Ảnh nền đã lưu/mới được gửi kèm làm tham chiếu bối cảnh.")
                                    image_btn = gr.Button("Sinh ảnh", size="sm")
                                    image_gallery = gr.Gallery(show_label=False, columns=2, height=440,
                                                               buttons=["download", "fullscreen"])
                            with gr.Row(equal_height=True):
                                canonical = gr.Checkbox(label="Mẫu chuẩn", scale=0, min_width=120)
                                approve_note = gr.Textbox(show_label=False, placeholder="Ghi chú khi duyệt (tuỳ chọn)",
                                                          container=False, scale=4)
                                approve_btn = gr.Button("Duyệt & lưu", variant="primary", scale=0, min_width=150)
                            with gr.Accordion("Lưu ảnh tham chiếu vào thư viện", open=False):
                                with gr.Row(equal_height=True):
                                    ref_label = gr.Textbox(show_label=False, placeholder="Tên gợi nhớ, vd: Sàn gỗ trắng",
                                                           container=False, scale=3)
                                    save_bg_btn = gr.Button("Lưu ảnh nền", size="sm", scale=1)
                                    save_style_btn = gr.Button("Lưu ảnh style", size="sm", scale=1)

                        with gr.Column(variant="panel", elem_classes="card"):
                            _card("↻", "Làm lại theo lô", "giữ nguyên thiết kế, chỉ đổi màu áo")
                            with gr.Row(equal_height=True):
                                batch_source = gr.Textbox(label="Từ request #", scale=0, min_width=120,
                                                          placeholder="tự điền", max_lines=1)
                                batch_colors = gr.CheckboxGroup(label="Màu áo cần làm", elem_classes="swatches",
                                                                scale=5, min_width=300, **init_batch)
                            with gr.Row():
                                batch_all_btn = gr.Button("Chọn tất cả màu còn lại", size="sm", scale=0, min_width=180)
                                batch_clear_btn = gr.Button("Bỏ chọn", size="sm", scale=0, min_width=90)
                                batch_btn = gr.Button("Tạo lô", variant="primary", scale=1)
                            batch_md = gr.Markdown(elem_classes="batch-out")
                            batch_file = gr.File(label="Tải tất cả prompt của lô (.txt)", visible=False)

            # ================================================================ THƯ VIỆN
            with gr.Tab("Thư viện", id="library"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=6, variant="panel", elem_classes="card"):
                        _card(None, "Prompt đã duyệt", "bấm một dòng để xem")
                        with gr.Row(equal_height=True):
                            lib_canonical_only = gr.Checkbox(label="Chỉ mẫu chuẩn", scale=0, min_width=150)
                            lib_refresh = gr.Button("Tải lại", size="sm", scale=0, min_width=90)
                        lib_table = gr.Dataframe(
                            headers=["ID", "Ngày", "Sản phẩm", "Màu áo", "Motif", "★", "Ghi chú"],
                            interactive=False, wrap=True, max_height=520, elem_classes="tbl",
                            column_widths=["7%", "12%", "16%", "13%", "32%", "5%", "15%"])
                    with gr.Column(scale=5, variant="panel", elem_classes="card"):
                        _card(None, "Chi tiết")
                        lib_selected = gr.State(None)
                        lib_meta = gr.HTML(empty_html("Chưa chọn prompt nào."))
                        lib_prompt = gr.Textbox(show_label=False, lines=14, buttons=["copy"], interactive=False,
                                                elem_id="lib-prompt")
                        lib_images = gr.Gallery(label="Ảnh đã sinh", columns=3, height=220,
                                                buttons=["download", "fullscreen"])
                        with gr.Row():
                            lib_batch_btn = gr.Button("Dùng làm nguồn cho lô", size="sm", variant="primary")
                            lib_toggle_btn = gr.Button("Bật/tắt mẫu chuẩn", size="sm")
                            lib_delete_btn = gr.Button("Xoá", size="sm", variant="stop")

                with gr.Column(variant="panel", elem_classes="card"):
                    _card(None, "Ảnh tham chiếu đã lưu", "bấm một ảnh để xem mô tả")
                    with gr.Row(equal_height=True):
                        ref_kind = gr.Radio([("Ảnh nền", "scene"), ("Style", "style")], value="scene",
                                            show_label=False, container=False, scale=0, min_width=220)
                        ref_remove_btn = gr.Button("Bỏ ảnh đang chọn khỏi thư viện", size="sm", variant="stop",
                                                   scale=0, min_width=240)
                    ref_selected = gr.State(None)
                    with gr.Row(equal_height=False):
                        ref_gallery = gr.Gallery(show_label=False, columns=5, height=300, scale=3,
                                                 buttons=["download", "fullscreen"])
                        ref_desc = gr.JSON(label="Mô tả bối cảnh đã lưu", scale=2)

            # ================================================================ LỊCH SỬ
            with gr.Tab("Lịch sử", id="history"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=6, variant="panel", elem_classes="card"):
                        _card(None, "Mọi lần tạo prompt", "100 lần gần nhất")
                        hist_refresh = gr.Button("Tải lại", size="sm", min_width=90)
                        hist_table = gr.Dataframe(
                            headers=["ID", "Ngày", "Sản phẩm", "Màu áo", "Motif", "Trạng thái", "Lô từ #"],
                            interactive=False, wrap=True, max_height=560, elem_classes="tbl",
                            column_widths=["7%", "12%", "17%", "13%", "31%", "11%", "9%"])
                    with gr.Column(scale=5, variant="panel", elem_classes="card"):
                        _card(None, "Chi tiết")
                        hist_selected = gr.State(None)
                        hist_info = gr.HTML(empty_html("Chưa chọn request nào."))
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
                                                         scale=1, min_width=120)
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
            chips = [f"Request <b>#{request_id}</b>", f"Quy tắc <b>v{version}</b>", f"Mẫu tham chiếu: {examples}"]
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
            return (result.request_id, meta, result.prompt, result.design_json, result.request_id, [],
                    gr.update(value=None, visible=False), "")

        @_guard
        def on_rebuild(request_id, design_text):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            result = service.rebuild_from_design(request_id, design_text or "")
            meta = meta_html(result_chips(result.request_id, result.rules_version, result.used_example_ids,
                                          "Đã dựng lại từ thiết kế"), result.warnings)
            return meta, result.prompt, result.design_json

        @_guard
        def on_approve(request_id, prompt, is_canonical, note):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            example_id, warnings = service.approve(request_id, prompt or "", bool(is_canonical), note or "")
            gr.Info(f"Đã lưu vào thư viện (#{example_id}){' — mẫu chuẩn' if is_canonical else ''}.")
            for w in warnings:
                gr.Warning(w)
            return library_rows(False)

        @_guard
        def on_save_bg(request_id, label, cat):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            ref_id = service.save_scene_reference(request_id, label or "")
            gr.Info(f"Đã lưu ảnh nền #{ref_id} vào thư viện.")
            return catalog(cat)

        @_guard
        def on_save_style(request_id, label, cat):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            ids = service.save_style_references(request_id, label or "")
            gr.Info(f"Đã lưu {len(ids)} ảnh style vào thư viện.")
            return catalog(cat)

        @_guard
        def on_batch_all(cat, source_id):
            _, rules = service.active_rules(cat)
            options = [k for _, k in service.category(cat).batch_options(rules)]
            source_color = None
            if _int(source_id):
                try:
                    source_color = service.get_request(int(source_id))["fields"].get("garment_color")
                except UserError:
                    pass
            return [k for k in options if k != source_color]

        @_guard_gen
        def on_batch(source_id, keys):
            source_id = _need(source_id, "Nhập request nguồn (mặc định là request vừa tạo)")
            blocks, warnings, texts = [], [], []
            yield "_Đang làm lô…_", gr.update(visible=False)
            for item in service.regenerate_batch(source_id, list(keys or [])):
                if isinstance(item, str):
                    warnings.append(item)
                    continue
                assert isinstance(item, BatchItem)
                blocks.append(f"#### {item.label} · request #{item.request_id}\n```text\n{item.prompt}\n```")
                texts.append(f"===== {item.label} (request #{item.request_id}) =====\n\n{item.prompt}\n")
                yield _batch_md(warnings, blocks, done=False), gr.update(visible=False)
            path = service.files.write_export(f"batch_{source_id}_{datetime.now():%Y%m%d_%H%M%S}.txt", "\n\n".join(texts))
            yield _batch_md(warnings, blocks, done=True), gr.update(value=str(path), visible=True)

        def _batch_md(warnings, blocks, done):
            head = "".join(f"> ⚠ {w}\n\n" for w in warnings)
            status = f"**✓ Xong {len(blocks)} màu.**" if done else f"_Đang làm… {len(blocks)} màu xong._"
            return head + status + "\n\n" + "\n\n".join(blocks)

        @_guard
        def on_image(request_id, prompt):
            request_id = _need(request_id, "Chưa có request — bấm Tạo prompt trước")
            service.generate_image(request_id, prompt or "")
            return service.generation_paths(request_id)

        category.change(catalog, category, catalog_outputs)
        bg_mode.change(on_bg_mode, bg_mode, [bg_preset, bg_saved, bg_custom])
        generate_btn.click(
            on_generate,
            [category, product_type, garment_color, placement, idea_files, style_files, style_saved, bg_mode,
             bg_preset, bg_saved, bg_custom, thread_colors, custom_note, aspect_ratio],
            [request_state, result_meta, prompt_box, design_code, batch_source, image_gallery, batch_file, batch_md],
            concurrency_limit=2,
        )
        rebuild_btn.click(on_rebuild, [request_state, design_code], [result_meta, prompt_box, design_code])
        save_bg_btn.click(on_save_bg, [request_state, ref_label, category], catalog_outputs)
        save_style_btn.click(on_save_style, [request_state, ref_label, category], catalog_outputs)
        batch_all_btn.click(on_batch_all, [category, batch_source], batch_colors)
        batch_clear_btn.click(lambda: [], None, batch_colors)
        batch_btn.click(on_batch, [batch_source, batch_colors], [batch_md, batch_file], concurrency_limit=1)
        image_btn.click(on_image, [request_state, prompt_box], image_gallery, concurrency_limit=1)

        # ------------------------------------------------------------------ handlers: thư viện

        def library_rows(canonical_only):
            return [[r["id"], _fmt_time(r["created_at"]), r["product_type"], r["garment_color"], r["motif"],
                     "★" if r["is_canonical"] else "", r["note"]]
                    for r in service.list_approved(canonical_only=bool(canonical_only))]

        def lib_detail(example_id):
            ex = service.get_approved(example_id)
            chips = [f"<b>#{ex['id']}</b>", html.escape(ex["product_type"]), html.escape(ex["garment_color"]),
                     f"Quy tắc v{ex['rules_version']}", _fmt_time(ex["created_at"])]
            if ex["is_canonical"]:
                chips.insert(1, "★ Mẫu chuẩn")
            if ex["note"]:
                chips.append(html.escape(ex["note"]))
            return example_id, meta_html(chips), ex["prompt_text"], ex["images"]

        approve_btn.click(on_approve, [request_state, prompt_box, canonical, approve_note], lib_table)

        @_guard
        def on_lib_select(evt: gr.SelectData):
            example_id = _int((evt.row_value or [None])[0])
            if not example_id:
                return None, empty_html("Chưa chọn prompt nào."), "", []
            return lib_detail(example_id)

        @_guard
        def on_lib_toggle(example_id, canonical_only):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            ex = service.get_approved(example_id)
            service.set_canonical(example_id, not ex["is_canonical"])
            return library_rows(canonical_only), *lib_detail(example_id)[1:2]

        @_guard
        def on_lib_delete(example_id, canonical_only):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            service.delete_approved(example_id)
            gr.Info(f"Đã xoá #{example_id} khỏi thư viện.")
            return library_rows(canonical_only), None, empty_html("Chưa chọn prompt nào."), "", []

        @_guard
        def on_lib_batch(example_id):
            example_id = _need(example_id, "Chọn một dòng trong bảng trước")
            return service.get_approved(example_id)["request_id"], gr.Tabs(selected="generate")

        def ref_items(kind):
            return [(r["path"], f"#{r['id']} · {r['label']}") for r in service.list_references(kind)]

        def on_ref_kind(kind):
            return ref_items(kind), None, None

        def on_ref_select(kind, evt: gr.SelectData):
            refs = service.list_references(kind)
            if evt.index is None or evt.index >= len(refs):
                return None, None
            ref = refs[evt.index]
            return ref["id"], ref["description"]

        @_guard
        def on_ref_remove(ref_id, kind, cat):
            ref_id = _need(ref_id, "Bấm chọn một ảnh trước")
            service.remove_reference(ref_id)
            gr.Info(f"Đã bỏ ảnh #{ref_id} khỏi thư viện.")
            return (ref_items(kind), None, None, *catalog(cat))

        lib_refresh.click(library_rows, lib_canonical_only, lib_table)
        lib_canonical_only.change(library_rows, lib_canonical_only, lib_table)
        lib_table.select(on_lib_select, None, [lib_selected, lib_meta, lib_prompt, lib_images])
        lib_toggle_btn.click(on_lib_toggle, [lib_selected, lib_canonical_only], [lib_table, lib_meta])
        lib_delete_btn.click(on_lib_delete, [lib_selected, lib_canonical_only],
                             [lib_table, lib_selected, lib_meta, lib_prompt, lib_images])
        lib_batch_btn.click(on_lib_batch, lib_selected, [batch_source, tabs])
        ref_kind.change(on_ref_kind, ref_kind, [ref_gallery, ref_selected, ref_desc])
        ref_gallery.select(on_ref_select, ref_kind, [ref_selected, ref_desc])
        ref_remove_btn.click(on_ref_remove, [ref_selected, ref_kind, category],
                             [ref_gallery, ref_selected, ref_desc, *catalog_outputs])

        # ------------------------------------------------------------------ handlers: lịch sử

        def history_rows():
            status = {"ok": "Đã tạo", "approved": "Đã duyệt", "error": "Lỗi"}
            return [[r["id"], _fmt_time(r["created_at"]), r["product_type"], r["fields"].get("garment_color", ""),
                     r["motif"] or r["error"][:80], status.get(r["status"], r["status"]), r["source_request_id"] or ""]
                    for r in service.list_requests()]

        @_guard
        def on_hist_select(evt: gr.SelectData):
            request_id = _int((evt.row_value or [None])[0])
            if not request_id:
                return None, empty_html("Chưa chọn request nào."), "", None, None
            r = service.get_request(request_id)
            chips = [f"<b>#{r['id']}</b>", html.escape(r["status"]), f"Quy tắc v{r['rules_version']}"]
            if r["text_edited"]:
                chips.append("Đã sửa tay")
            if r["source_request_id"]:
                chips.append(f"Lô từ #{r['source_request_id']}")
            if r["custom_note"]:
                chips.append("Ghi chú: " + html.escape(r["custom_note"]))
            return (request_id, meta_html(chips, [r["error"]] if r["error"] else None), r["prompt_text"],
                    r["design_json"], r["model_raw"])

        @_guard
        def on_hist_batch(request_id):
            request_id = _need(request_id, "Chọn một dòng trong bảng trước")
            return request_id, gr.Tabs(selected="generate")

        hist_refresh.click(history_rows, None, hist_table)
        hist_table.select(on_hist_select, None, [hist_selected, hist_info, hist_prompt, hist_design, hist_raw])
        hist_batch_btn.click(on_hist_batch, hist_selected, [batch_source, tabs])

        # ------------------------------------------------------------------ handlers: quy tắc

        rules_outputs = [rules_info, block_key, block_help, block_text, rules_json, rules_history]

        @_guard
        def on_block_save(cat, key, text, note):
            version = service.save_block(cat, key, text or "", note or "")
            gr.Info(f"Đã lưu phiên bản {version}.")
            view = rules_view(cat)
            return (*view[:1], gr.update(value=key), *block_view(cat, key), *view[4:], *catalog(cat))

        @_guard
        def on_json_save(cat, text, note):
            try:
                content = json.loads(text or "")
            except json.JSONDecodeError as e:
                raise UserError(f"JSON sai cú pháp: dòng {e.lineno}, cột {e.colno}: {e.msg}") from None
            version = service.save_rules(cat, content, note or "Sửa JSON")
            gr.Info(f"Đã lưu phiên bản {version}.")
            return (*rules_view(cat), *catalog(cat))

        @_guard
        def on_restore(cat, version):
            version = _need(version, "Nhập số phiên bản cần khôi phục")
            new_version = service.restore_rules(cat, version)
            gr.Info(f"Đã khôi phục nội dung bản {version} thành phiên bản {new_version}.")
            return (*rules_view(cat), *catalog(cat))

        rules_category.change(rules_view, rules_category, rules_outputs)
        block_key.change(block_view, [rules_category, block_key], [block_help, block_text])
        block_save_btn.click(on_block_save, [rules_category, block_key, block_text, block_note],
                             [*rules_outputs, *catalog_outputs])
        rules_json_save_btn.click(on_json_save, [rules_category, rules_json, rules_json_note],
                                  [*rules_outputs, *catalog_outputs])
        restore_btn.click(on_restore, [rules_category, restore_version], [*rules_outputs, *catalog_outputs])

        # ------------------------------------------------------------------ nạp lần đầu

        def on_load():
            return (*catalog(default_category), library_rows(False), history_rows(),
                    ref_items("scene"), *rules_view(default_category))

        demo.load(on_load, None, [*catalog_outputs, lib_table, hist_table, ref_gallery, *rules_outputs])

    return demo
