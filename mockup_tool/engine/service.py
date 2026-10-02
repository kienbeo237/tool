"""Tầng nghiệp vụ: generate, làm lại theo lô, approve, thư viện, quản lý quy tắc.

Không phụ thuộc Gradio — giao diện (hoặc một API sau này) chỉ gọi các hàm ở đây.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from mockup_tool.categories.base import BackgroundPreset, Category, CategoryRules, ProductInputs
from mockup_tool.categories.registry import CATEGORIES
from mockup_tool.engine import context_builder as cb
from mockup_tool.engine.gemini_client import InvalidOutput, ModelClient, ModelError, NoImageError, mime_for
from mockup_tool.engine.image_engines import GEMINI, ImageEngine
from mockup_tool.engine.schema import (
    Design,
    DesignOutput,
    RecolorOutput,
    ResolvedScene,
    SceneDescription,
    validate_design,
)
from mockup_tool.storage.db import ApprovedExample, Generation, ReferenceAsset, Request, RuleVersion
from mockup_tool.storage.files import FileStore
from mockup_tool.text import non_english_chars

log = logging.getLogger(__name__)

FEW_SHOT_LIMIT = 3
MAX_IDEA_IMAGES = 2
MAX_STYLE_IMAGES = 3


class UserError(ValueError):
    """Lỗi do đầu vào — hiển thị nguyên văn cho người dùng."""


@dataclass
class GenerateInput:
    category: str
    product_type: str
    fields: dict
    aspect_ratio: str
    background_mode: str  # preset | saved | custom
    background_preset: str | None = None
    background_reference_id: int | None = None
    background_image: str | None = None
    idea_images: list[str] = field(default_factory=list)
    style_images: list[str] = field(default_factory=list)
    style_reference_ids: list[int] = field(default_factory=list)
    custom_note: str = ""


@dataclass
class PromptResult:
    request_id: int
    prompt: str
    design_json: str
    rules_version: int
    warnings: list[str]
    used_example_ids: list[int]
    scene: dict


@dataclass
class BatchItem:
    request_id: int
    key: str
    label: str
    prompt: str


@dataclass
class _Background:
    mode: str
    key: str | None
    preset: BackgroundPreset | None
    description: SceneDescription | None


class MockupService:
    def __init__(self, sessions: sessionmaker, files: FileStore, client: ModelClient,
                 categories: dict[str, Category] | None = None,
                 image_engines: dict[str, ImageEngine] | None = None):
        self.sessions = sessions
        self.files = files
        self.client = client
        self.categories = categories or CATEGORIES
        self.image_engines = image_engines or {GEMINI: ImageEngine(GEMINI, "Gemini", client.image_model, client)}

    # ------------------------------------------------------------------ quy tắc

    def category(self, key: str) -> Category:
        try:
            return self.categories[key]
        except KeyError:
            raise UserError(f"Danh mục '{key}' chưa được đăng ký") from None

    def active_rules(self, category_key: str) -> tuple[int, CategoryRules]:
        category = self.category(category_key)
        with self.sessions() as s:
            row = s.scalars(
                select(RuleVersion).where(RuleVersion.category == category_key)
                .order_by(RuleVersion.version.desc()).limit(1)
            ).first()
            if row is None:
                rules = category.seed_rules()
                errors = category.validate_rules(rules)
                if errors:
                    raise RuntimeError(f"Seed rules của '{category_key}' không hợp lệ: {errors}")
                row = RuleVersion(category=category_key, version=1, content=rules.model_dump(), note="Khởi tạo từ seed")
                s.add(row)
                s.commit()
            return row.version, CategoryRules.model_validate(row.content)

    def rules_at(self, category_key: str, version: int) -> CategoryRules:
        with self.sessions() as s:
            row = s.scalars(select(RuleVersion).where(
                RuleVersion.category == category_key, RuleVersion.version == version)).first()
            if row is None:
                raise UserError(f"Không có quy tắc phiên bản {version} của '{category_key}'")
            return CategoryRules.model_validate(row.content)

    def save_rules(self, category_key: str, content: dict, note: str = "") -> int:
        category = self.category(category_key)
        try:
            rules = CategoryRules.model_validate(content)
        except ValidationError as e:
            raise UserError("Quy tắc không hợp lệ:\n" + "\n".join(
                f"- {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from None
        errors = category.validate_rules(rules)
        if errors:
            raise UserError("Quy tắc không hợp lệ:\n" + "\n".join(f"- {e}" for e in errors))
        current_version, current = self.active_rules(category_key)
        if rules.model_dump() == current.model_dump():
            raise UserError("Không có thay đổi nào so với phiên bản hiện tại")
        with self.sessions() as s:
            row = RuleVersion(category=category_key, version=current_version + 1,
                              content=rules.model_dump(), note=note.strip())
            s.add(row)
            s.commit()
            return row.version

    def save_block(self, category_key: str, block_key: str, text: str, note: str = "") -> int:
        _, rules = self.active_rules(category_key)
        content = rules.model_dump()
        if block_key not in content["blocks"]:
            raise UserError(f"Không có block '{block_key}'")
        content["blocks"][block_key] = text.strip()
        return self.save_rules(category_key, content, note or f"Sửa block {block_key}")

    def restore_rules(self, category_key: str, version: int) -> int:
        rules = self.rules_at(category_key, version)
        return self.save_rules(category_key, rules.model_dump(), f"Khôi phục từ phiên bản {version}")

    def rule_history(self, category_key: str) -> list[dict]:
        with self.sessions() as s:
            rows = s.scalars(select(RuleVersion).where(RuleVersion.category == category_key)
                             .order_by(RuleVersion.version.desc())).all()
            return [{"version": r.version, "created_at": r.created_at, "note": r.note} for r in rows]

    # ------------------------------------------------------------------ generate

    def generate(self, inp: GenerateInput) -> PromptResult:
        category = self.category(inp.category)
        version, rules = self.active_rules(inp.category)
        inputs, fixed_palette = self._inputs(category, rules, inp)

        if not 1 <= len(inp.idea_images) <= MAX_IDEA_IMAGES:
            raise UserError(f"Cần 1–{MAX_IDEA_IMAGES} ảnh ý tưởng (đang có {len(inp.idea_images)})")
        if len(inp.style_images) + len(inp.style_reference_ids) > MAX_STYLE_IMAGES:
            raise UserError(f"Tối đa {MAX_STYLE_IMAGES} ảnh style reference (gồm cả ảnh đã lưu)")
        idea = [self._ingest(p).rel_path for p in inp.idea_images]
        style = [self._ingest(p).rel_path for p in inp.style_images] + self._saved_style_paths(inp.style_reference_ids)

        raws: list = []
        background = self._background(rules, inp, raws)
        base_scene = cb.scene_defaults(rules, background.preset, background.description)
        examples = self._examples(inp.category)

        request = cb.design_request(
            category, rules, inputs,
            idea_images=[self.files.abs(p) for p in idea],
            style_images=[self.files.abs(p) for p in style],
            examples=[e["design_json"] for e in examples],
            base_scene=base_scene,
            custom_note=inp.custom_note,
            fixed_palette=fixed_palette,
        )
        record = Request(
            category=inp.category, product_type=inputs.product_type, fields=inputs.fields,
            aspect_ratio=inputs.aspect_ratio, background_mode=background.mode, background_key=background.key,
            scene_json=base_scene.__dict__, scene_overrides=None, custom_note=inp.custom_note.strip(),
            idea_images=idea, style_images=style, rules_version=version, model_name=self.client.text_model,
            used_example_ids=[e["id"] for e in examples], model_raw=raws,
        )
        try:
            output, design = self._design_call(category, request, fixed_palette, raws)
        except ModelError as e:
            self._save_failed(record, raws, str(e))
            raise

        scene = cb.apply_overrides(base_scene, output.scene_overrides)
        prompt = category.build_prompt(rules, inputs, design, scene)
        warnings = cb.check_invariants(category, rules, prompt)
        record.scene_json = scene.__dict__
        record.scene_overrides = output.scene_overrides.model_dump() if output.scene_overrides else None
        record.design_json = design.model_dump()
        record.rendered_prompt = record.prompt_text = prompt
        record.model_raw = raws
        with self.sessions() as s:
            s.add(record)
            s.commit()
        return PromptResult(record.id, prompt, _pretty(design), version, warnings, record.used_example_ids, scene.__dict__)

    def _inputs(self, category: Category, rules: CategoryRules, inp: GenerateInput) -> tuple[ProductInputs, list[str] | None]:
        try:
            rules.product_type(inp.product_type)
            fields = category.normalize_fields(rules, inp.fields)
        except (KeyError, ValueError) as e:
            raise UserError(e.args[0]) from None
        if inp.aspect_ratio not in rules.aspect_ratios:
            raise UserError(f"Aspect Ratio '{inp.aspect_ratio}' không có trong danh mục")
        return ProductInputs(inp.product_type, inp.aspect_ratio, fields), category.fixed_palette(fields)

    def _ingest(self, path: str):
        try:
            return self.files.ingest_image(path)
        except ValueError as e:
            raise UserError(str(e)) from None

    def _saved_style_paths(self, ids: list[int]) -> list[str]:
        if not ids:
            return []
        with self.sessions() as s:
            rows = s.scalars(select(ReferenceAsset).where(
                ReferenceAsset.id.in_(ids), ReferenceAsset.kind == "style")).all()
            if len(rows) != len(set(ids)):
                raise UserError("Có ảnh style reference đã chọn không còn trong thư viện")
            return [r.image_path for r in rows]

    def _background(self, rules: CategoryRules, inp: GenerateInput, raws: list) -> _Background:
        mode = inp.background_mode
        if mode == "preset":
            try:
                preset = rules.background(inp.background_preset or "")
            except KeyError as e:
                raise UserError(e.args[0]) from None
            return _Background(mode, preset.key, preset, None)
        if mode == "saved":
            with self.sessions() as s:
                ref = s.get(ReferenceAsset, inp.background_reference_id or -1)
                if ref is None or ref.kind != "scene" or not ref.description:
                    raise UserError("Chưa chọn ảnh nền đã lưu, hoặc ảnh đó không còn")
                return _Background(mode, str(ref.id), None, SceneDescription.model_validate(ref.description))
        if mode == "custom":
            if not inp.background_image:
                raise UserError("Background Custom cần tải lên một ảnh nền")
            ref = self._scene_reference(rules, self._ingest(inp.background_image), raws)
            return _Background(mode, str(ref.id), None, SceneDescription.model_validate(ref.description))
        raise UserError(f"Background mode '{mode}' không hợp lệ")

    def _scene_reference(self, rules: CategoryRules, image, raws: list) -> ReferenceAsset:
        """Đọc ảnh nền Custom bằng vision, cache theo hash: cùng một ảnh chỉ gọi model một lần."""
        with self.sessions() as s:
            ref = s.scalars(select(ReferenceAsset).where(
                ReferenceAsset.sha256 == image.sha256, ReferenceAsset.kind == "scene")).first()
            if ref is not None and ref.description:
                return ref
        request = cb.scene_request(rules, self.files.abs(image.rel_path))
        description, errors = None, []
        for _ in range(2):
            try:
                description, raw = self.client.json_call(request, SceneDescription)
                raws.append({"call": "scene", "raw": raw})
                errors = [f"{k} must be English only" for k, v in description.model_dump().items() if non_english_chars(v)]
            except InvalidOutput as e:
                raws.append({"call": "scene", "raw": e.raw})
                errors = e.errors
            if not errors:
                break
            request = cb.retry_request(request, errors)
        if errors:
            raise ModelError("Không đọc được ảnh nền: " + "; ".join(errors))
        with self.sessions() as s:
            ref = s.scalars(select(ReferenceAsset).where(
                ReferenceAsset.sha256 == image.sha256, ReferenceAsset.kind == "scene")).first()
            if ref is None:
                ref = ReferenceAsset(sha256=image.sha256, kind="scene", image_path=image.rel_path)
                s.add(ref)
            ref.description = description.model_dump()
            s.commit()
            return ref

    def _examples(self, category_key: str) -> list[dict]:
        """Few-shot: ví dụ đã duyệt CÙNG DANH MỤC, ưu tiên mẫu chuẩn rồi mới nhất."""
        with self.sessions() as s:
            rows = s.scalars(
                select(ApprovedExample).where(ApprovedExample.category == category_key)
                .order_by(ApprovedExample.is_canonical.desc(), ApprovedExample.created_at.desc())
                .limit(FEW_SHOT_LIMIT)
            ).all()
            return [{"id": r.id, "design_json": r.design_json} for r in rows]

    def _design_call(self, category: Category, request: cb.ModelRequest, fixed_palette: list[str] | None,
                     raws: list) -> tuple[DesignOutput, Design]:
        """Một lệnh gọi; nếu output sai ràng buộc thì gửi lỗi lại cho model sửa đúng một lần."""
        errors: list[str] = []
        for _ in range(2):
            try:
                output, raw = self.client.json_call(request, DesignOutput)
                raws.append({"call": "design", "raw": raw})
            except InvalidOutput as e:
                raws.append({"call": "design", "raw": e.raw})
                errors = e.errors
            else:
                design = Design(motif_summary=output.motif_summary, elements=output.elements, palette=output.palette)
                errors = validate_design(design, category.techniques, fixed_palette) + cb.overrides_errors(output.scene_overrides)
                if not errors:
                    if fixed_palette:
                        design = design.model_copy(update={"palette": list(fixed_palette)})
                    return output, design
            request = cb.retry_request(request, errors)
        raise ModelError("Model trả thiết kế không hợp lệ sau 2 lần thử: " + "; ".join(errors))

    def _save_failed(self, record: Request, raws: list, error: str) -> None:
        record.status, record.error, record.model_raw = "error", error, raws
        with self.sessions() as s:
            s.add(record)
            s.commit()

    # ------------------------------------------------------------------ sửa thiết kế

    def rebuild_from_design(self, request_id: int, design_text: str) -> PromptResult:
        """Sửa ở tầng thiết kế (JSON) rồi dựng lại prompt — thay đổi này được lô dùng lại."""
        with self.sessions() as s:
            req = self._request(s, request_id)
            category = self.category(req.category)
            try:
                design = Design.model_validate_json(design_text)
            except ValidationError as e:
                raise UserError("JSON thiết kế không hợp lệ:\n" + "\n".join(
                    f"- {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from None
            errors = validate_design(design, category.techniques, category.fixed_palette(req.fields))
            if errors:
                raise UserError("Thiết kế không hợp lệ:\n" + "\n".join(f"- {e}" for e in errors))
            version, rules = self.active_rules(req.category)
            inputs = ProductInputs(req.product_type, req.aspect_ratio, req.fields)
            scene = ResolvedScene(**req.scene_json)
            prompt = category.build_prompt(rules, inputs, design, scene)
            req.design_json = design.model_dump()
            req.rendered_prompt = req.prompt_text = prompt
            req.text_edited = False
            req.rules_version = version
            s.commit()
            return PromptResult(req.id, prompt, _pretty(design), version,
                                cb.check_invariants(category, rules, prompt), req.used_example_ids, req.scene_json)

    # ------------------------------------------------------------------ làm lại theo lô

    def regenerate_batch(self, source_request_id: int, keys: list[str]) -> Iterator[BatchItem | str]:
        """Giữ nguyên thiết kế của request nguồn, chỉ đổi màu áo.

        Không gọi lại model cho thiết kế. Nếu palette do model tự chọn, gọi MỘT lệnh nhỏ
        để chỉnh palette cho tất cả màu áo mới (palette phụ thuộc độ tương phản với màu áo).
        Yield chuỗi = cảnh báo, BatchItem = một prompt xong.
        """
        with self.sessions() as s:
            src = self._request(s, source_request_id)
            if not src.design_json:
                raise UserError(f"Request #{src.id} không có thiết kế (có thể đã lỗi)")
            s.expunge(src)
        category = self.category(src.category)
        version, rules = self.active_rules(src.category)
        if not keys:
            raise UserError("Chọn ít nhất một màu để làm lại theo lô")
        valid = {k for _, k in category.batch_options(rules)}
        unknown = [k for k in keys if k not in valid]
        if unknown:
            raise UserError(f"Không có trong danh mục: {unknown}")

        if src.text_edited:
            yield (f"Prompt của #{src.id} từng được sửa tay; lô dựng từ thiết kế (JSON) nên phần sửa tay "
                   "không được mang theo. Muốn giữ, hãy sửa trong ô Thiết kế rồi bấm Dựng lại.")
        if version != src.rules_version:
            yield f"Quy tắc đã đổi từ v{src.rules_version} lên v{version} kể từ request nguồn; lô dùng v{version}."

        design = Design.model_validate(src.design_json)
        source_key = category.batch_value(src.fields)
        palettes: dict[str, list[str]] = {}
        raws: list = []
        if not category.fixed_palette(src.fields):
            targets = {k: category.batch_phrase(rules, k) for k in keys if k != source_key}
            if targets:
                palettes = self._recolor(design, category.batch_phrase(rules, source_key), targets, raws)

        scene = ResolvedScene(**src.scene_json)
        root_id = src.source_request_id or src.id
        for key in keys:
            item_design = design.model_copy(update={"palette": palettes[key]}) if key in palettes else design
            fields = category.with_batch_value(src.fields, key)
            prompt = category.build_prompt(rules, ProductInputs(src.product_type, src.aspect_ratio, fields), item_design, scene)
            record = Request(
                category=src.category, product_type=src.product_type, fields=fields, aspect_ratio=src.aspect_ratio,
                background_mode=src.background_mode, background_key=src.background_key, scene_json=src.scene_json,
                scene_overrides=src.scene_overrides, custom_note=src.custom_note, idea_images=src.idea_images,
                style_images=src.style_images, design_json=item_design.model_dump(), rendered_prompt=prompt,
                prompt_text=prompt, source_request_id=root_id, rules_version=version,
                model_name=self.client.text_model if key in palettes else "reuse",
                used_example_ids=[], model_raw=raws if key in palettes else [],
            )
            with self.sessions() as s:
                s.add(record)
                s.commit()
            yield BatchItem(record.id, key, category.batch_phrase(rules, key), prompt)

    def _recolor(self, design: Design, source_phrase: str, targets: dict[str, str], raws: list) -> dict[str, list[str]]:
        request = cb.recolor_request(design, source_phrase, targets)
        n = len(design.palette)
        errors: list[str] = []
        for _ in range(2):
            try:
                output, raw = self.client.json_call(request, RecolorOutput)
                raws.append({"call": "recolor", "raw": raw})
            except InvalidOutput as e:
                raws.append({"call": "recolor", "raw": e.raw})
                errors = e.errors
            else:
                result = {p.garment_color_key: [c.strip() for c in p.palette] for p in output.palettes}
                errors = [f"missing palette for {k}" for k in targets if k not in result]
                errors += [f"{k}: palette must have exactly {n} colors" for k, v in result.items()
                           if k in targets and len(v) != n]
                errors += [f"{k}: colors must be English" for k, v in result.items() if non_english_chars(" ".join(v))]
                if not errors:
                    return {k: result[k] for k in targets}
            request = cb.retry_request(request, errors)
        raise ModelError("Không chỉnh được palette cho các màu áo mới: " + "; ".join(errors))

    # ------------------------------------------------------------------ approve & thư viện

    def approve(self, request_id: int, final_prompt: str, canonical: bool, note: str = "") -> tuple[int, list[str]]:
        with self.sessions() as s:
            req = self._request(s, request_id)
            if not req.design_json:
                raise UserError(f"Request #{req.id} không có thiết kế để duyệt")
            category = self.category(req.category)
            rules = self.rules_at(req.category, req.rules_version)
            final = final_prompt.strip() or req.prompt_text
            warnings = cb.check_invariants(category, rules, final)
            req.prompt_text = final
            req.text_edited = final != req.rendered_prompt
            req.status = "approved"
            example = ApprovedExample(
                request_id=req.id, category=req.category, product_type=req.product_type,
                placement=req.fields.get("placement", ""), garment_color=req.fields.get("garment_color", ""),
                background_key=req.background_key, design_json=req.design_json,
                design_text=category.design_part(req.rendered_prompt), prompt_text=final,
                is_canonical=canonical, note=note.strip(), rules_version=req.rules_version,
            )
            s.add(example)
            s.commit()
            return example.id, warnings

    def save_scene_reference(self, request_id: int, label: str) -> int:
        with self.sessions() as s:
            req = self._request(s, request_id)
            if req.background_mode not in ("custom", "saved"):
                raise UserError("Request này dùng background preset, không có ảnh nền để lưu")
            ref = s.get(ReferenceAsset, int(req.background_key))
            ref.saved = True
            ref.label = label.strip() or ref.label or f"Ảnh nền #{ref.id}"
            s.commit()
            return ref.id

    def save_style_references(self, request_id: int, label: str) -> list[int]:
        with self.sessions() as s:
            req = self._request(s, request_id)
            if not req.style_images:
                raise UserError("Request này không có ảnh style reference")
            ids = []
            for rel in req.style_images:
                sha = Path(rel).stem
                ref = s.scalars(select(ReferenceAsset).where(
                    ReferenceAsset.sha256 == sha, ReferenceAsset.kind == "style")).first()
                if ref is None:
                    ref = ReferenceAsset(sha256=sha, kind="style", image_path=rel)
                    s.add(ref)
                ref.saved = True
                ref.label = label.strip() or ref.label or "Style reference"
                s.flush()
                ids.append(ref.id)
            s.commit()
            return ids

    def list_references(self, kind: str) -> list[dict]:
        with self.sessions() as s:
            rows = s.scalars(select(ReferenceAsset).where(ReferenceAsset.kind == kind, ReferenceAsset.saved)
                             .order_by(ReferenceAsset.created_at.desc())).all()
            return [{"id": r.id, "label": r.label, "path": str(self.files.abs(r.image_path)),
                     "description": r.description, "created_at": r.created_at} for r in rows]

    def remove_reference(self, reference_id: int) -> None:
        """Bỏ khỏi thư viện. Giữ file và mô tả vì các request cũ còn trỏ tới."""
        with self.sessions() as s:
            ref = s.get(ReferenceAsset, reference_id)
            if ref is None:
                raise UserError(f"Không có reference #{reference_id}")
            ref.saved = False
            s.commit()

    def list_approved(self, category_key: str | None = None, canonical_only: bool = False) -> list[dict]:
        with self.sessions() as s:
            q = select(ApprovedExample).order_by(ApprovedExample.is_canonical.desc(), ApprovedExample.created_at.desc())
            if category_key:
                q = q.where(ApprovedExample.category == category_key)
            if canonical_only:
                q = q.where(ApprovedExample.is_canonical)
            return [_example_dict(r) for r in s.scalars(q).all()]

    def get_approved(self, example_id: int) -> dict:
        with self.sessions() as s:
            row = s.get(ApprovedExample, example_id)
            if row is None:
                raise UserError(f"Không có prompt đã duyệt #{example_id}")
            data = _example_dict(row)
        data["images"] = self.generation_paths(data["request_id"])
        return data

    def set_canonical(self, example_id: int, canonical: bool) -> None:
        with self.sessions() as s:
            row = s.get(ApprovedExample, example_id)
            if row is None:
                raise UserError(f"Không có prompt đã duyệt #{example_id}")
            row.is_canonical = canonical
            s.commit()

    def delete_approved(self, example_id: int) -> None:
        with self.sessions() as s:
            row = s.get(ApprovedExample, example_id)
            if row is None:
                raise UserError(f"Không có prompt đã duyệt #{example_id}")
            s.delete(row)
            s.commit()

    def list_requests(self, limit: int = 100) -> list[dict]:
        with self.sessions() as s:
            rows = s.scalars(select(Request).order_by(Request.id.desc()).limit(limit)).all()
            return [{"id": r.id, "created_at": r.created_at, "category": r.category, "product_type": r.product_type,
                     "fields": r.fields, "status": r.status, "source_request_id": r.source_request_id,
                     "motif": (r.design_json or {}).get("motif_summary", ""), "error": r.error} for r in rows]

    def get_request(self, request_id: int) -> dict:
        with self.sessions() as s:
            r = self._request(s, request_id)
            data = {"id": r.id, "category": r.category, "product_type": r.product_type, "fields": r.fields,
                    "status": r.status, "prompt_text": r.prompt_text, "rendered_prompt": r.rendered_prompt,
                    "design_json": r.design_json, "text_edited": r.text_edited, "rules_version": r.rules_version,
                    "error": r.error, "model_raw": r.model_raw, "custom_note": r.custom_note,
                    "scene_json": r.scene_json, "source_request_id": r.source_request_id}
        data["images"] = self.generation_paths(request_id)
        return data

    def request_count(self) -> int:
        with self.sessions() as s:
            return s.scalar(select(func.count(Request.id)))

    # ------------------------------------------------------------------ sinh ảnh (tuỳ chọn)

    def generate_image(self, request_id: int, final_prompt: str = "", engine: str = GEMINI) -> str:
        """Sinh ảnh từ ĐÚNG prompt đã dựng. Không gửi ảnh ý tưởng (sẽ kéo về sao chép);
        ảnh nền đã duyệt thì gửi kèm vì nó chỉ chi phối bối cảnh."""
        chosen = self.image_engines.get(engine)
        if chosen is None:
            raise UserError(f"Không có engine sinh ảnh '{engine}'")
        if chosen.client is None:
            raise UserError(f"{chosen.label}: server chưa cấu hình {chosen.missing_key}. "
                            "Thêm vào file .env rồi khởi động lại app.")
        with self.sessions() as s:
            req = self._request(s, request_id)
            prompt = final_prompt.strip() or req.prompt_text
            scene_bytes, scene_mime = None, "image/png"
            if req.background_mode in ("saved", "custom") and req.background_key:
                ref = s.get(ReferenceAsset, int(req.background_key))
                if ref is not None:
                    path = self.files.abs(ref.image_path)
                    scene_bytes, scene_mime = path.read_bytes(), mime_for(path)
            aspect_ratio = req.aspect_ratio

        data, mime, error = None, "image/png", None
        for _ in range(2):  # model trả text thay vì ảnh (safety/quota): thử lại đúng một lần
            try:
                data, mime = chosen.client.generate_image(prompt, scene_bytes, scene_mime, aspect_ratio)
                break
            except NoImageError as e:
                error = e
            except ModelError as e:
                error = e
                break
        if data is None:
            with self.sessions() as s:
                s.add(Generation(request_id=request_id, model=chosen.model, status="error", error=str(error)))
                s.commit()
            raise error or ModelError("Không sinh được ảnh")

        with self.sessions() as s:
            gen = Generation(request_id=request_id, model=chosen.model, status="ok")
            s.add(gen)
            s.flush()
            gen.image_path = self.files.save_generation(request_id, gen.id, data, mime)
            s.commit()
            return str(self.files.abs(gen.image_path))

    def generation_paths(self, request_id: int) -> list[str]:
        return [path for path, _ in self.generation_items(request_id)]

    def generation_items(self, request_id: int) -> list[tuple[str, str]]:
        """(đường dẫn ảnh, model đã sinh) — để so sánh ảnh giữa các engine."""
        with self.sessions() as s:
            rows = s.scalars(select(Generation).where(Generation.request_id == request_id, Generation.status == "ok")
                             .order_by(Generation.id)).all()
            return [(str(self.files.abs(r.image_path)), r.model) for r in rows]

    # ------------------------------------------------------------------ tiện ích

    @staticmethod
    def _request(s, request_id: int) -> Request:
        req = s.get(Request, request_id)
        if req is None:
            raise UserError(f"Không có request #{request_id}")
        return req


def _pretty(design: Design) -> str:
    return json.dumps(design.model_dump(), ensure_ascii=False, indent=2)


def _example_dict(r: ApprovedExample) -> dict:
    return {"id": r.id, "request_id": r.request_id, "category": r.category, "product_type": r.product_type,
            "placement": r.placement, "garment_color": r.garment_color, "background_key": r.background_key,
            "motif": r.design_json.get("motif_summary", ""), "design_json": r.design_json,
            "design_text": r.design_text, "prompt_text": r.prompt_text, "is_canonical": r.is_canonical,
            "note": r.note, "rules_version": r.rules_version, "created_at": r.created_at}
