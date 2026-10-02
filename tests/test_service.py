import json

import pytest

from mockup_tool.engine.service import UserError


def test_generate_saves_request_with_rules_version(service, base_input, client):
    result = service.generate(base_input())
    assert len(result.prompt.split("\n\n")) == 4
    assert result.rules_version == 1
    assert result.warnings == []
    assert client.calls == ["DesignOutput"]
    req = service.get_request(result.request_id)
    assert req["rules_version"] == 1 and req["status"] == "ok"


def test_fixed_thread_colors_are_used_verbatim(service, base_input):
    inp = base_input(fields={"garment_color": "sand", "placement": "left_chest", "thread_colors": ["Navy", "Cream"]})
    result = service.generate(inp)
    assert "Palette & Style: Navy and Cream" in result.prompt


@pytest.mark.parametrize("threads", [["Navy"], ["a", "b", "c", "d", "e", "f"], ["Xanh lá", "Đỏ"]])
def test_invalid_thread_colors_rejected(service, base_input, threads):
    with pytest.raises(UserError):
        service.generate(base_input(fields={"garment_color": "sand", "placement": "center_chest", "thread_colors": threads}))


def test_idea_image_count_enforced(service, base_input, make_image):
    with pytest.raises(UserError):
        service.generate(base_input(idea_images=[]))
    with pytest.raises(UserError):
        service.generate(base_input(idea_images=[make_image(), make_image(), make_image()]))


def test_batch_reuses_design_without_design_call(service, base_input, client):
    src = service.generate(base_input(fields={"garment_color": "sand", "placement": "center_chest",
                                              "thread_colors": ["Navy", "Cream"]}))
    client.calls.clear()
    items = [i for i in service.regenerate_batch(src.request_id, ["forest_green", "maroon", "white"]) if not isinstance(i, str)]
    assert client.calls == []  # palette cố định: không gọi model lần nào
    assert [i.key for i in items] == ["forest_green", "maroon", "white"]
    src_para3 = src.prompt.split("\n\n")[2]
    for item in items:
        assert item.prompt.split("\n\n")[2].replace(item.label.split(" (")[0], "Sand") == src_para3
        assert service.get_request(item.request_id)["source_request_id"] == src.request_id


def test_batch_with_auto_palette_makes_one_recolor_call(service, base_input, client):
    src = service.generate(base_input())
    client.calls.clear()
    items = [i for i in service.regenerate_batch(src.request_id, ["sand", "black", "white"]) if not isinstance(i, str)]
    assert client.calls == ["RecolorOutput"]
    by_key = {i.key: i for i in items}
    assert by_key["sand"].prompt == src.prompt  # màu gốc giữ nguyên palette gốc
    assert "Palette & Style: Cream, Navy, and Mustard" in by_key["black"].prompt


def test_batch_warns_when_source_text_edited(service, base_input):
    src = service.generate(base_input())
    service.approve(src.request_id, src.prompt + " Extra manual tweak.", canonical=False)
    out = list(service.regenerate_batch(src.request_id, ["white"]))
    assert isinstance(out[0], str) and "sửa tay" in out[0]


def test_approve_flags_edits_and_invariant_warnings(service, base_input):
    src = service.generate(base_input())
    broken = src.prompt.replace(service.active_rules("embroidered_apparel")[1].blocks["anti_print"], "")
    example_id, warnings = service.approve(src.request_id, broken, canonical=True, note="x")
    assert any("chống hình in" in w for w in warnings)
    ex = service.get_approved(example_id)
    assert ex["is_canonical"] and ex["design_text"].startswith("The embroidered design is")
    assert service.get_request(src.request_id)["text_edited"] is True


def test_few_shot_uses_canonical_examples_of_same_category(service, base_input, client):
    first = service.generate(base_input())
    service.approve(first.request_id, first.prompt, canonical=True)
    second = service.generate(base_input())
    assert second.used_example_ids == [1]


def test_custom_background_is_described_once_then_cached(service, base_input, make_image, client):
    bg = make_image("#336699")
    r1 = service.generate(base_input(background_mode="custom", background_image=bg))
    r2 = service.generate(base_input(background_mode="custom", background_image=bg))
    assert client.calls.count("SceneDescription") == 1
    assert "whitewashed wooden plank floor" in r1.prompt and r1.scene == r2.scene
    ref_id = service.save_scene_reference(r1.request_id, "Sàn gỗ trắng")
    r3 = service.generate(base_input(background_mode="saved", background_reference_id=ref_id))
    assert "whitewashed" in r3.prompt
    assert [r["label"] for r in service.list_references("scene")] == ["Sàn gỗ trắng"]


def test_rebuild_from_edited_design(service, base_input):
    src = service.generate(base_input())
    design = json.loads(src.design_json)
    design["elements"][0]["text"] = "HELLO FALL"
    result = service.rebuild_from_design(src.request_id, json.dumps(design))
    assert '"HELLO FALL"' in result.prompt
    with pytest.raises(UserError):
        design["palette"] = ["Cream"]
        service.rebuild_from_design(src.request_id, json.dumps(design))


def test_rules_versioning_and_restore(service, base_input):
    v1, rules = service.active_rules("embroidered_apparel")
    v2 = service.save_block("embroidered_apparel", "default_lighting", "warm golden hour sunlight", "test")
    assert v2 == v1 + 1
    result = service.generate(base_input(background_preset="grass"))
    assert "warm golden hour sunlight" in result.prompt and result.rules_version == v2
    with pytest.raises(UserError):
        service.save_block("embroidered_apparel", "para2", "No placeholders here.")
    with pytest.raises(UserError):
        service.save_block("embroidered_apparel", "default_lighting", "warm golden hour sunlight")  # không đổi
    v3 = service.restore_rules("embroidered_apparel", v1)
    assert service.active_rules("embroidered_apparel")[1] == rules and v3 == v2 + 1


def test_custom_note_reaches_model_and_overrides(service, base_input):
    result = service.generate(base_input(custom_note="chụp góc 45 độ, bỏ nến"))
    assert "(mock) customer note applied." in result.prompt.split("\n\n")[0]
    assert service.get_request(result.request_id)["custom_note"] == "chụp góc 45 độ, bỏ nến"


def test_generate_image_mock(service, base_input):
    src = service.generate(base_input())
    path = service.generate_image(src.request_id)
    assert path.endswith(".png")
    assert service.get_request(src.request_id)["images"] == [path]
