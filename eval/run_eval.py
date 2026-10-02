"""Phase 0 — đo lớp ngữ cảnh nào thật sự có giá trị (mục 9 tài liệu thiết kế).

Chạy cùng một ảnh ý tưởng qua 4 cấu hình, mỗi bậc thêm đúng một lớp:
  A: hệ quy tắc
  B: hệ quy tắc + đoạn 3 đã duyệt (few-shot)
  C: hệ quy tắc + ảnh nền tham chiếu (qua vision)
  D: hệ quy tắc + ví dụ đã duyệt + ảnh nền + Custom Note
Xuất một file HTML với nhãn bị xáo (khách chấm mù) và một file key để giải mã.

Ví dụ:
  python -m eval.run_eval --idea idea1.png --examples eval/examples.json \
      --scene bg.png --note "chụp góc 45 độ, bỏ nến" --out eval_out

examples.json: danh sách các đoạn 3 khách ưng nhất (chuỗi), chép từ file conversation.
"""

import argparse
import html
import json
import random
from pathlib import Path

from mockup_tool.categories.base import ProductInputs
from mockup_tool.categories.registry import get_category
from mockup_tool.config import load_settings
from mockup_tool.engine import context_builder as cb
from mockup_tool.engine.gemini_client import GeminiClient, InvalidOutput, MockGeminiClient
from mockup_tool.engine.schema import Design, DesignOutput, SceneDescription, validate_design


def design_call(client, category, request, fixed):
    errors = []
    for _ in range(2):
        try:
            output, _ = client.json_call(request, DesignOutput)
        except InvalidOutput as e:
            errors = e.errors
        else:
            design = Design(motif_summary=output.motif_summary, elements=output.elements, palette=output.palette)
            errors = validate_design(design, category.techniques, fixed)
            if not errors:
                return output, design
        request = cb.retry_request(request, errors)
    raise SystemExit(f"Model trả thiết kế không hợp lệ: {errors}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--idea", nargs="+", required=True, help="1-2 ảnh ý tưởng")
    ap.add_argument("--examples", required=True, help="JSON: list các đoạn 3 đã duyệt")
    ap.add_argument("--scene", required=True, help="ảnh nền tham chiếu")
    ap.add_argument("--note", default="", help="Custom Note cho bậc D")
    ap.add_argument("--category", default="embroidered_apparel")
    ap.add_argument("--product-type", default="gildan_sweatshirt")
    ap.add_argument("--color", default="sand")
    ap.add_argument("--placement", default="center_chest")
    ap.add_argument("--preset", default="wooden_table", help="background preset cho bậc A/B")
    ap.add_argument("--aspect", default="1:1")
    ap.add_argument("--out", default="eval_out")
    args = ap.parse_args()

    settings = load_settings()
    client = MockGeminiClient() if settings.mock_gemini else GeminiClient(
        settings.gemini_api_key, settings.text_model, settings.image_model)
    category = get_category(args.category)
    rules = category.seed_rules()
    inputs = ProductInputs(args.product_type, args.aspect,
                           {"garment_color": args.color, "placement": args.placement, "thread_colors": []})
    examples = json.loads(Path(args.examples).read_text(encoding="utf-8"))[:3]
    ideas = [Path(p) for p in args.idea]

    scene_desc, _ = client.json_call(cb.scene_request(rules, Path(args.scene)), SceneDescription)
    preset_scene = cb.scene_defaults(rules, rules.background(args.preset), None)
    image_scene = cb.scene_defaults(rules, None, scene_desc)

    configs = {
        "A": dict(examples=[], scene=preset_scene, note=""),
        "B": dict(examples=examples, scene=preset_scene, note=""),
        "C": dict(examples=[], scene=image_scene, note=""),
        "D": dict(examples=examples, scene=image_scene, note=args.note),
    }
    results = {}
    for name, cfg in configs.items():
        request = cb.design_request(category, rules, inputs, idea_images=ideas, style_images=[],
                                    examples=cfg["examples"], base_scene=cfg["scene"],
                                    custom_note=cfg["note"], fixed_palette=None)
        output, design = design_call(client, category, request, None)
        scene = cb.apply_overrides(cfg["scene"], output.scene_overrides)
        results[name] = category.build_prompt(rules, inputs, design, scene)
        print(f"[{name}] xong")

    labels = list(results)
    random.shuffle(labels)
    key = {f"Phương án {i}": name for i, name in enumerate(labels, 1)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cards = "\n".join(
        f"<section><h2>{html.escape(blind)}</h2><pre>{html.escape(results[name])}</pre></section>"
        for blind, name in key.items()
    )
    (out / "blind.html").write_text(f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>So sánh prompt</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;background:#fafafa;color:#222}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px;margin:16px 0}}
pre{{white-space:pre-wrap;font:13px/1.5 ui-monospace,monospace}}</style></head><body>
<h1>Phương án nào gần nhất với prompt bạn đang tự làm?</h1>{cards}</body></html>""", encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi {out / 'blind.html'} (gửi khách) và {out / 'key.json'} (giữ lại).")


if __name__ == "__main__":
    main()
