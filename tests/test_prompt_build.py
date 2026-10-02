from mockup_tool.categories.embroidery import EmbroideryCategory
from mockup_tool.engine import context_builder as cb
from mockup_tool.engine.schema import Design, DesignElement, SceneOverrides, validate_design
from mockup_tool.categories.base import ProductInputs

CAT = EmbroideryCategory()
RULES = CAT.seed_rules()


def design(palette=("Cream", "Burnt Orange")):
    return Design(
        motif_summary="cozy goose motif",
        elements=[
            DesignElement(role="top_text", name="title", text="HONK", description="Bold letters in [T1].", techniques=["satin"]),
            DesignElement(role="main_motif", name="goose", text=None, description="A goose in [T1] with a [T2] beak.",
                          techniques=["tatami", "satin"]),
        ],
        palette=list(palette),
    )


def inputs(color="sand", placement="center_chest"):
    return ProductInputs("gildan_sweatshirt", "1:1", {"garment_color": color, "placement": placement, "thread_colors": []})


def test_seed_rules_are_valid():
    assert CAT.validate_rules(RULES) == []


def test_four_paragraphs_with_invariants_and_hex():
    scene = cb.scene_defaults(RULES, RULES.background("wooden_table"), None)
    prompt = CAT.build_prompt(RULES, inputs(), design(), scene)
    paragraphs = prompt.split("\n\n")
    assert len(paragraphs) == 4
    assert "Sand (#cbb999)" in paragraphs[0]
    assert "top-down flat lay" in paragraphs[0]
    assert '- Top text "HONK": Bold letters in Cream.' in paragraphs[2]
    assert "A goose in Cream with a Burnt Orange beak." in paragraphs[2]
    assert paragraphs[2].splitlines()[-1].startswith("Palette & Style: Cream and Burnt Orange")
    assert 'satin stitches are used for the "HONK" lettering and the goose' in paragraphs[3]
    assert "tatami fill stitches cover the goose" in paragraphs[3]
    assert "running" not in paragraphs[3].lower().split("technique:")[1].split("stitched")[0]
    assert cb.check_invariants(CAT, RULES, prompt) == []
    assert "  " not in prompt and " ." not in prompt


def test_placement_clause_switches():
    scene = cb.scene_defaults(RULES, RULES.background("grass"), None)
    center = CAT.build_prompt(RULES, inputs(placement="center_chest"), design(), scene)
    left = CAT.build_prompt(RULES, inputs(placement="left_chest"), design(), scene)
    assert "vast expanse of clean, plain Sand fabric" in center
    assert "strictly on the left chest area" in left


def test_custom_note_overrides_beat_preset_and_defaults():
    preset = RULES.background("wooden_table")
    base = cb.scene_defaults(RULES, preset, None)
    overrides = SceneOverrides(camera="A 45-degree angled product photograph", surface=None,
                               props="No candles or other props appear in the frame.", lighting=None,
                               arrangement=None, extra="A soft vignette frames the edges.")
    scene = cb.apply_overrides(base, overrides)
    assert scene.camera == "A 45-degree angled product photograph"
    assert scene.surface == preset.surface  # không bị note chạm tới thì giữ preset
    assert scene.props.startswith("No candles")
    assert scene.lighting == RULES.blocks["default_lighting"]
    prompt = CAT.build_prompt(RULES, inputs(), design(), scene)
    assert "top-down" not in prompt.split("\n\n")[0]
    # Note không có đường nào xoá khối chất thêu
    assert cb.check_invariants(CAT, RULES, prompt) == []


def test_empty_preset_props_leave_no_gap():
    scene = cb.scene_defaults(RULES, RULES.background("gingham_denim"), None)
    prompt = CAT.build_prompt(RULES, inputs(), design(), scene)
    assert ". The scene is lit" in prompt and ". ." not in prompt


def test_validate_design_catches_bad_tokens_and_vietnamese():
    d = design()
    bad = d.model_copy(update={"elements": [
        d.elements[0].model_copy(update={"description": "Letters in [T3]."}),
        d.elements[1].model_copy(update={"description": "Con ngỗng màu kem."}),
    ]})
    errors = validate_design(bad, CAT.techniques, None)
    assert any("T3" in e for e in errors)
    assert any("must reference thread colors" in e for e in errors)
    assert any("English only" in e for e in errors)


def test_validate_design_fixed_palette():
    assert validate_design(design(), CAT.techniques, ["cream", "burnt orange"]) == []
    assert validate_design(design(), CAT.techniques, ["Navy", "Cream"])


def test_rules_validation_rejects_missing_invariant_placeholder():
    content = RULES.model_dump()
    content["blocks"]["para2"] = "The {garment} is soft."
    content["blocks"]["anti_print"] = "Thêu thật 100%."
    from mockup_tool.categories.base import CategoryRules
    errors = CAT.validate_rules(CategoryRules.model_validate(content))
    assert any("{puckering}" in e for e in errors)
    assert any("anti_print" in e and "tiếng Anh" in e for e in errors)


def test_rules_validation_rejects_unknown_placeholder_and_bad_braces():
    from mockup_tool.categories.base import CategoryRules
    content = RULES.model_dump()
    content["blocks"]["satin_sentence"] = "Satin for {parts} and {oops}."
    content["blocks"]["running_sentence"] = "Running {parts"
    errors = CAT.validate_rules(CategoryRules.model_validate(content))
    assert any("oops" in e for e in errors)
    assert any("running_sentence" in e for e in errors)
