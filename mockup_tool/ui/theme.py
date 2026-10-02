"""Theme + CSS cho giao diện. Màu lấy từ biến CSS của theme nên tự đúng ở cả chế độ sáng/tối."""

import html

import gradio as gr

THEME = gr.themes.Base(
    primary_hue="indigo",
    secondary_hue="indigo",
    neutral_hue="slate",
    radius_size="md",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "Consolas", "monospace"],
).set(
    body_background_fill="*neutral_50",
    body_background_fill_dark="*neutral_950",
    # Thẻ (card) là đơn vị bố cục; block bên trong không viền để tránh khung lồng khung.
    panel_background_fill="white",
    panel_background_fill_dark="*neutral_900",
    panel_border_width="1px",
    panel_border_color="*neutral_200",
    panel_border_color_dark="*neutral_800",
    block_background_fill="transparent",
    block_background_fill_dark="transparent",
    block_border_width="0px",
    block_shadow="none",
    block_padding="6px 2px",
    # Nhãn: chữ thường, không nền "chip".
    block_label_background_fill="transparent",
    block_label_background_fill_dark="transparent",
    block_label_border_width="0px",
    block_label_text_color="*neutral_600",
    block_label_text_color_dark="*neutral_300",
    block_label_text_size="*text_sm",
    block_label_padding="0 0 4px 0",
    block_title_background_fill="transparent",
    block_title_background_fill_dark="transparent",
    block_title_border_width="0px",
    block_title_text_color="*neutral_700",
    block_title_text_color_dark="*neutral_200",
    block_title_text_size="*text_sm",
    block_title_text_weight="600",
    block_title_padding="0 0 6px 0",
    block_info_text_color="*neutral_500",
    input_background_fill="white",
    input_background_fill_dark="*neutral_800",
    input_border_width="1px",
    input_border_color="*neutral_300",
    input_border_color_dark="*neutral_700",
    input_border_color_focus="*primary_500",
    input_shadow_focus="0 0 0 3px *primary_100",
    input_shadow_focus_dark="0 0 0 3px *primary_900",
    checkbox_label_background_fill="white",
    checkbox_label_background_fill_dark="*neutral_800",
    checkbox_label_background_fill_selected="*primary_50",
    checkbox_label_background_fill_selected_dark="*primary_950",
    checkbox_label_border_width="1px",
    checkbox_label_border_color="*neutral_200",
    checkbox_label_border_color_dark="*neutral_700",
    checkbox_label_border_color_selected="*primary_500",
    checkbox_label_text_color_selected="*primary_700",
    checkbox_label_text_color_selected_dark="*primary_200",
    checkbox_label_shadow="none",
    checkbox_label_padding="7px 12px",
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
    button_primary_text_color="white",
    button_secondary_background_fill="white",
    button_secondary_background_fill_dark="*neutral_800",
    button_secondary_border_color="*neutral_300",
    button_secondary_border_color_dark="*neutral_700",
    button_border_width="1px",
    button_primary_border_color="*primary_600",
    button_primary_border_color_hover="*primary_700",
    # Nút nguy hiểm (variant="stop"): đỏ đặc, không nhầm với nút thường.
    button_cancel_background_fill="#dc2626",
    button_cancel_background_fill_hover="#b91c1c",
    button_cancel_background_fill_dark="#b91c1c",
    button_cancel_background_fill_hover_dark="#991b1b",
    button_cancel_border_color="#dc2626",
    button_cancel_border_color_dark="#b91c1c",
    button_cancel_text_color="white",
    button_cancel_text_color_dark="white",
    button_large_radius="*radius_md",
    button_large_text_weight="600",
    layout_gap="14px",
)

CSS = """
/* overflow:hidden mặc định của Gradio làm hỏng position:sticky; clip cắt tràn mà không tạo vùng cuộn. */
.gradio-container { width: 100% !important; max-width: 1440px !important; margin: 0 auto !important; overflow: clip !important; }
footer { display: none !important; }

/* Gradio gom các input liền nhau vào .form có nền xám làm đường kẻ — bỏ đi, card đã đủ phân nhóm. */
.card .form { background: transparent !important; border: 0 !important; box-shadow: none !important;
  gap: 12px !important; overflow: visible !important; }
.card .form > * { border-radius: 0 !important; }
.card .block.padded:has(> label input[type=checkbox]) { padding-top: 10px !important; }

/* ---------- header ---------- */
.app-header { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 4px 2px 10px; flex-wrap: wrap; }
.app-title { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; color: var(--body-text-color); }
.app-sub { font-size: 13px; color: var(--body-text-color-subdued); margin-top: 2px; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600; border: 1px solid transparent; white-space: nowrap; }
.badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.badge-ok { color: #047857; background: #ecfdf5; border-color: #a7f3d0; }
.badge-warn { color: #b45309; background: #fffbeb; border-color: #fde68a; }
.dark .badge-ok { color: #6ee7b7; background: #022c22; border-color: #065f46; }
.dark .badge-warn { color: #fcd34d; background: #2d1a03; border-color: #92400e; }

/* ---------- tabs ---------- */
.main-tabs > .tab-wrapper button { font-weight: 600; }
/* Tab chỉ có bảng trống sẽ co theo nội dung nếu không ép rộng. */
.main-tabs, .main-tabs > .tabitem { width: 100% !important; }

/* ---------- card ---------- */
.card { border-radius: 12px !important; padding: 14px 16px 10px !important; gap: 8px !important; }
.card-h { display: flex; align-items: center; gap: 10px; margin: 0 0 2px; }
.card-t { font-size: 15px; font-weight: 650; color: var(--body-text-color); }
.card-d { font-size: 12.5px; color: var(--body-text-color-subdued); margin-left: auto; }
.step { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px;
  border-radius: 50%; font-size: 12px; font-weight: 700; color: var(--primary-700);
  background: var(--primary-100); }
.dark .step { color: var(--primary-200); background: var(--primary-900); }

/* ---------- nút tạo prompt dính đáy cột trái ---------- */
#generate-btn { position: sticky; bottom: 12px; z-index: 20;
  box-shadow: 0 8px 24px -8px rgba(79, 70, 229, .55); }

/* ---------- ô màu (swatch) cho màu áo ---------- */
.swatches .wrap { gap: 6px !important; }
.swatches label { position: relative; padding: 6px 10px 6px 8px !important; border-radius: 999px !important;
  font-size: 13px !important; cursor: pointer; }
.swatches input { position: absolute !important; opacity: 0 !important; width: 1px !important;
  height: 1px !important; margin: 0 !important; }
.swatches label span { margin-left: 0 !important; display: inline-flex; align-items: center; gap: 7px; }
.swatches label span::before { content: ""; width: 16px; height: 16px; border-radius: 50%;
  border: 1px solid rgba(15, 23, 42, .18); box-shadow: inset 0 0 0 1px rgba(255,255,255,.35);
  background: var(--sw, #ccc); flex: none; }
.swatches label:has(input:checked) { border-color: var(--primary-500) !important;
  box-shadow: 0 0 0 2px var(--primary-200) !important; }
.dark .swatches label:has(input:checked) { box-shadow: 0 0 0 2px var(--primary-800) !important; }
.swatches label:has(input:focus-visible) { outline: 2px solid var(--primary-500); outline-offset: 2px; }

/* ---------- kết quả ---------- */
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { font-size: 12px; padding: 3px 9px; border-radius: 6px; color: var(--body-text-color);
  background: var(--background-fill-secondary); border: 1px solid var(--border-color-primary); }
.chip b { font-weight: 650; }
.empty { font-size: 13.5px; color: var(--body-text-color-subdued); padding: 2px 0; }
.callout { margin-top: 8px; font-size: 13px; padding: 8px 12px; border-radius: 8px;
  color: #92400e; background: #fffbeb; border: 1px solid #fde68a; }
.dark .callout { color: #fcd34d; background: #2d1a03; border-color: #92400e; }
#prompt-box textarea { font-size: 14px !important; line-height: 1.65 !important; }
/* Mỗi prompt của lô: xuống dòng thay vì cuộn ngang, giới hạn chiều cao để lướt nhanh cả lô. */
.batch-out pre { max-height: 150px; overflow: auto; white-space: pre-wrap !important; word-break: break-word; }
.batch-out pre code { white-space: pre-wrap !important; font-size: 12px; }
.batch-out h4 { margin: 14px 0 4px !important; font-size: 14px !important; }

/* Nút cạnh ô nhập có nhãn: căn đáy thẳng với ô nhập. */
.bottom-row { align-items: flex-end !important; }

/* ---------- khung tải ảnh: Gradio không có tiếng Việt — thay chữ bằng CSS ---------- */
.vi-upload [data-testid="upload-text"] { font-size: 0 !important; gap: 6px; }
.vi-upload [data-testid="upload-text"] .or { display: none !important; }
.vi-upload [data-testid="upload-text"]::after { content: "Kéo thả ảnh vào đây hoặc bấm để chọn";
  font-size: 13.5px; color: var(--body-text-color-subdued); }
.hint { font-size: 12.5px; color: var(--body-text-color-subdued); margin-top: -4px; }

/* ---------- nút tạo prompt: gợi ý phím tắt ---------- */
#generate-btn::after { content: "Ctrl + Enter"; margin-left: 10px; font-size: 11px; font-weight: 500;
  opacity: .7; padding: 1px 6px; border: 1px solid rgba(255,255,255,.45); border-radius: 4px; }
#generate-btn:disabled { opacity: .75; cursor: progress; }
#generate-btn:disabled::after { display: none; }
@media (hover: none) { #generate-btn::after, .guide .kbd-hint { display: none; } }

/* ---------- hướng dẫn khi chưa có kết quả ---------- */
.guide { padding: 18px 4px 10px; }
.guide-t { font-size: 14px; color: var(--body-text-color-subdued); margin-bottom: 12px; }
.guide ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; counter-reset: g; }
.guide li { counter-increment: g; display: flex; gap: 10px; align-items: baseline; font-size: 14px;
  color: var(--body-text-color); }
.guide li::before { content: counter(g); flex: none; width: 22px; height: 22px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
  color: var(--primary-700); background: var(--primary-100); }
.dark .guide li::before { color: var(--primary-200); background: var(--primary-900); }
.guide li span { color: var(--body-text-color-subdued); font-size: 13px; }
.guide kbd { font: 600 11.5px var(--font-mono); padding: 1px 6px; border-radius: 4px;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-secondary); }

/* ---------- thanh kết quả, copy, trạng thái duyệt ---------- */
.result-bar { align-items: center !important; }
button.copied { background: #059669 !important; border-color: #059669 !important; color: #fff !important; }
.sub-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap;
  font-weight: 600; font-size: 13.5px; margin-top: 6px; padding-top: 10px;
  border-top: 1px solid var(--border-color-primary); }
.sub-head.flush { border-top: 0; padding-top: 0; }
.hint p, .hint .prose { font-size: 12.5px !important; color: var(--body-text-color-subdued); }
.sub-head span { font-weight: 400; font-size: 12px; color: var(--body-text-color-subdued); }
.status-ok { font-size: 13px; padding: 8px 12px; border-radius: 8px; color: #065f46; background: #ecfdf5;
  border: 1px solid #a7f3d0; }
.dark .status-ok { color: #6ee7b7; background: #022c22; border-color: #065f46; }

/* ---------- xác nhận thao tác xoá ---------- */
.confirm-row { align-items: center !important; padding: 8px 10px !important; border-radius: 8px;
  background: #fef2f2; border: 1px solid #fecaca; }
.dark .confirm-row { background: #2a0f0f; border-color: #7f1d1d; }
.confirm-text { font-size: 13px; color: #991b1b; }
.dark .confirm-text { color: #fca5a5; }

/* ---------- bảng ---------- */
.tbl table { font-size: 13px; }
/* Bảng mặc định dùng font mono → chữ dài bị ngắt giữa từ. */
.tbl, .tbl * { font-family: var(--font) !important; }
.tbl .body-cell, .tbl td { word-break: normal !important; overflow-wrap: anywhere; }
"""


def header_html(mock: bool, text_model: str) -> str:
    badge = ('<span class="badge badge-warn" title="Chưa có GEMINI_API_KEY — kết quả model là dữ liệu mẫu cố định">'
             'Chế độ giả lập</span>' if mock else
             f'<span class="badge badge-ok">Gemini · {html.escape(text_model)}</span>')
    return (f'<div class="app-header"><div><div class="app-title">Mockup Prompt Tool</div>'
            f'<div class="app-sub">Dựng prompt mockup áo thêu · khung 4 đoạn · 100% tiếng Anh</div></div>{badge}</div>')


def card_header(step: str | int | None, title: str, desc: str = "") -> str:
    step_html = f'<span class="step">{step}</span>' if step is not None else ""
    desc_html = f'<span class="card-d">{html.escape(desc)}</span>' if desc else ""
    return f'<div class="card-h">{step_html}<span class="card-t">{html.escape(title)}</span>{desc_html}</div>'


def swatch_css(colors: list[tuple[str, str]]) -> str:
    """CSS gắn màu thật cho từng lựa chọn màu áo (radio dùng value=, checkbox dùng name=)."""
    rules = "\n".join(
        f'.swatches input[value="{key}"] + span, .swatches input[name="{key}"] + span {{ --sw: {hexcode}; }}'
        for key, hexcode in colors
    )
    return f"<style>{rules}</style>"


def meta_html(chips: list[str], warnings: list[str] | None = None) -> str:
    body = '<div class="meta">' + "".join(f'<span class="chip">{c}</span>' for c in chips) + "</div>"
    for w in warnings or []:
        body += f'<div class="callout">⚠ {html.escape(w)}</div>'
    return body


def empty_html(text: str) -> str:
    return f'<div class="empty">{html.escape(text)}</div>'


def guide_html() -> str:
    return ('<div class="guide"><div class="guide-t">Chưa có prompt. Ba bước:</div><ol>'
            '<li><div>Chọn sản phẩm, vị trí thêu và màu áo</div></li>'
            '<li><div>Tải 1–2 ảnh ý tưởng <span>· bối cảnh, màu chỉ, ghi chú là tuỳ chọn</span></div></li>'
            '<li><div>Bấm <b>Tạo prompt</b> <span class="kbd-hint">hoặc <kbd>Ctrl</kbd> + <kbd>Enter</kbd></span></div></li>'
            '</ol></div>')


def status_html(text: str) -> str:
    """Dòng xác nhận thành công (đã escape phía gọi nếu cần)."""
    return f'<div class="status-ok">✓ {text}</div>'
