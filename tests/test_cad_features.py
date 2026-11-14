"""CAD feature trees: validation, owner-readable errors, stable hash, steps and today's parts."""

import copy
import json
import typing

import pytest

from creative.scene import transform
from services.cad import SceneObject
from services.cad_design import LivePart
from services.cad_features import (
    MATERIALS,
    FeatureTreeError,
    canonical,
    describe,
    from_parts,
    parse_tree,
    tree_hash,
)

SPEC = {
    "units": "mm",
    "features": [
        {"id": "body", "op": "box", "size": [60, 40, 20], "at": [0, 0, 10],
         "material": "titanium"},
        {"id": "h1", "op": "hole", "target": "body", "face": "top", "at": [10, 5],
         "diameter": 5, "depth": "through"},
        {"op": "pattern", "of": "h1", "kind": "linear", "count": [2, 2], "spacing": [40, 30]},
        {"op": "fillet", "target": "body", "edges": "vertical", "radius": 3},
        {"op": "chamfer", "target": "body", "edges": "top", "distance": 1},
        {"op": "cut", "target": "body",
         "tool": {"op": "box", "size": [20, 10, 30], "at": [0, 0, 10]}},
        {"op": "shell", "target": "body", "thickness": 2, "open": "top"},
        {"op": "text", "target": "body", "face": "top", "text": "JARVIS", "size": 8,
         "depth": 0.6, "mode": "engrave"},
    ],
    "export": ["glb", "stl", "step"],
}

BODY = {"id": "body", "op": "box", "size": [60, 40, 20]}


def tree(*features, export=None):
    data = {"features": [copy.deepcopy(BODY), *map(copy.deepcopy, features)]}
    if export is not None:
        data["export"] = export
    return data


def error(data):
    with pytest.raises(FeatureTreeError) as caught:
        parse_tree(data)
    return str(caught.value)


def spec(**changes):
    data = copy.deepcopy(SPEC)
    for index, fields in changes.items():
        data["features"][int(index.removeprefix("f"))].update(fields)
    return data


# --- the spec's example ------------------------------------------------------------------

def test_spec_example_parses_with_defaults_filled():
    parsed = parse_tree(SPEC)
    assert [feature.op for feature in parsed.features] == [
        "box", "hole", "pattern", "fillet", "chamfer", "cut", "shell", "text"
    ]
    body = parsed.features[0]
    assert body.size == [60.0, 40.0, 20.0] and body.rotate == [0, 0, 0]
    assert body.scale == [1, 1, 1] and body.material == "titanium"
    assert parsed.features[1].depth == "through" and parsed.features[1].cb_diameter is None
    assert parsed.features[7].at is None and parsed.export == ["glb", "stl", "step"]
    assert parse_tree(json.dumps(SPEC)) == parsed
    assert parse_tree(parsed) is parsed


def test_spec_example_describes_each_step():
    assert describe(SPEC) == [
        "Box 60 × 40 × 20 mm, titanium",
        "Through hole Ø5 mm on the top face at (10, 5)",
        "Repeat hole h1 in a 2 × 2 grid, 40 × 30 mm apart",
        "Round the vertical edges, 3 mm radius",
        "Chamfer the top edges by 1 mm",
        "Cut a box 20 × 10 × 30 mm at (0, 0, 10) from body",
        "Shell to 2 mm walls, open at the top",
        "Engrave “JARVIS” on the top face, centred, 8 mm tall, 0.6 mm deep",
    ]


def test_defaults_and_export_order():
    parsed = parse_tree(tree())
    assert parsed.units == "mm" and parsed.export == ["glb"]
    assert parse_tree(tree(export=["step", "glb"])).export == ["glb", "step"]
    assert "once" in error(tree(export=["glb", "glb"]))
    assert error(tree(export=["obj"])) == "The design: export must be 'glb', 'stl' or 'step'."
    assert error(tree(export=[])) == "The design: export must have at least 1 value(s)."
    assert error({**tree(), "units": "in"}) == "The design: units must be 'mm'."
    assert error({**tree(), "colour": "red"}) == "The design doesn't take colour."


def test_non_objects_are_refused_plainly():
    assert "valid JSON" in error("{nope")
    assert "must be an object" in error(["box"])
    assert error({"features": []}) == "A design needs at least one feature."
    assert error({"export": ["glb"]}) == "The design needs features."
    assert error({"features": ["box"]}) == "Feature 1 must be an object with an op."


# --- every op, valid and invalid ---------------------------------------------------------

VALID = [
    {"id": "peg", "op": "cylinder", "diameter": 10, "height": 30, "at": [0, 0, 35],
     "rotate": [90, 0, 0], "material": "amber"},
    {"id": "ball", "op": "sphere", "diameter": 12, "scale": [1, 1, 2]},
    {"id": "arm", "op": "l_bracket", "size": [40, 30, 25], "thickness": 3},
    {"id": "case", "op": "enclosure", "size": [80, 60, 30], "thickness": 2},
    {"op": "hole", "target": "body", "at": [10, 5], "diameter": 5},
    {"op": "hole", "target": "body", "face": "front", "at": [10, 5], "diameter": 5,
     "depth": 8},
    {"op": "hole", "target": "body", "at": [10, 5], "diameter": 5, "cb_diameter": 9,
     "cb_depth": 3},
    {"op": "slot", "target": "body", "at": [30, 20], "length": 20, "width": 5, "depth": 3,
     "angle": 45},
    {"op": "cut", "target": "body", "tool": {"op": "cylinder", "diameter": 8, "height": 50}},
    {"op": "union", "target": "body",
     "tool": {"op": "box", "size": [10, 10, 10], "at": [0, 0, 25]}},
    {"op": "fillet", "target": "body", "radius": 1000},
    {"op": "chamfer", "target": "body", "edges": "bottom", "distance": 0.1},
    {"op": "shell", "target": "body", "thickness": 2, "open": "bottom"},
    {"op": "text", "target": "body", "face": "front", "text": "A1 – ok!", "size": 6,
     "depth": 0.5, "mode": "emboss", "at": [30, 10]},
    {"op": "mirror", "target": "body", "plane": "YZ"},
]


@pytest.mark.parametrize("feature", VALID, ids=lambda feature: feature["op"])
def test_each_op_validates(feature):
    parsed = parse_tree(tree(feature))
    assert parsed.features[1].op == feature["op"]
    assert len(describe(parsed)) == 2


def test_patterns_linear_and_polar():
    hole = {"id": "h", "op": "hole", "target": "body", "at": [10, 5], "diameter": 3}
    linear = parse_tree(tree(hole, {"op": "pattern", "of": "h", "count": 4,
                                    "spacing": [10, 0]})).features[2]
    assert linear.kind == "linear" and linear.count == [4, 1] and linear.instances() == 4
    polar = parse_tree(tree(hole, {"op": "pattern", "of": "h", "kind": "polar", "count": 6,
                                   "radius": 15})).features[2]
    assert polar.angle == 360 and polar.instances() == 6
    assert describe(tree(hole, {"op": "pattern", "of": "h", "kind": "polar", "count": 3,
                                "radius": 15, "angle": 90}))[2] == (
        "Repeat hole h 3 times on a 15 mm radius over 90°"
    )
    # Solids, slots, text and cuts with a tool can be repeated too.
    for source in (
        {"id": "s", "op": "slot", "target": "body", "at": [5, 5], "length": 8, "width": 2},
        {"id": "s", "op": "text", "target": "body", "text": "A", "size": 5, "depth": 0.5},
        {"id": "s", "op": "cut", "target": "body", "tool": {"op": "sphere", "diameter": 4}},
        {"id": "s", "op": "cylinder", "diameter": 4, "height": 6},
    ):
        parse_tree(tree(source, {"op": "pattern", "of": "s", "count": [2, 1],
                                 "spacing": [10, 0]}))


INVALID = [
    ({"op": "cylinder", "diameter": 10}, "Feature 2 (cylinder) needs height."),
    ({"op": "sphere", "diameter": 10, "size": [1, 1, 1]}, "Feature 2 (sphere) doesn't take size."),
    ({"op": "l_bracket", "size": [40, 3, 25], "thickness": 3}, "L bracket's depth and height"),
    ({"op": "enclosure", "size": [4, 60, 30], "thickness": 2}, "opening must be at least 0.5"),
    ({"op": "hole", "target": "body", "diameter": 5}, "Feature 2 (hole) needs at."),
    ({"op": "hole", "target": "body", "at": [1, 2, 3], "diameter": 5}, "at must have 2 values"),
    ({"op": "hole", "target": "body", "at": [1, 2], "diameter": 5, "depth": "thru"},
     'depth must be "through" or a depth of 0.1–2000 mm'),
    ({"op": "hole", "target": "body", "at": [1, 2], "diameter": 5, "cb_diameter": 9},
     "needs both cb_diameter and cb_depth"),
    ({"op": "hole", "target": "body", "at": [1, 2], "diameter": 5, "cb_diameter": 4,
      "cb_depth": 2}, "must be wider than the hole"),
    ({"op": "hole", "target": "body", "at": [1, 2], "diameter": 5, "depth": 2,
      "cb_diameter": 8, "cb_depth": 2}, "must be shallower than the hole"),
    ({"op": "hole", "target": "body", "face": "side", "at": [1, 2], "diameter": 5},
     "face must be 'top', 'bottom', 'front', 'back', 'left' or 'right'"),
    ({"op": "slot", "target": "body", "at": [1, 2], "length": 5, "width": 5},
     "a slot must be longer than it is wide"),
    ({"op": "cut", "target": "body"}, "give either a tool shape or bodies"),
    ({"op": "cut", "target": "body", "tool": {"op": "hole", "diameter": 3}},
     "Feature 2 (cut) has an unknown op 'hole'"),
    ({"op": "cut", "target": "body", "tool": {"op": "box", "size": [1, 2]}},
     "Feature 2 (cut): tool size must have 3 values."),
    ({"op": "cut", "target": "body", "tool": {"op": "box", "id": "t", "size": [1, 2, 3]}},
     "Feature 2 (cut): the tool shape doesn't take id."),
    ({"op": "union", "target": "body", "bodies": []}, "bodies must have at least 1 value(s)"),
    ({"op": "fillet", "target": "body", "radius": 1001}, "radius must be at most 1000 mm"),
    ({"op": "fillet", "target": "body", "edges": "outer", "radius": 1},
     "edges must be 'all', 'vertical', 'top' or 'bottom'"),
    ({"op": "chamfer", "target": "body", "distance": 1001}, "distance must be at most 1000 mm"),
    ({"op": "shell", "target": "body"}, "Feature 2 (shell) needs thickness."),
    ({"op": "text", "target": "body", "text": "   ", "size": 5, "depth": 1}, "can't be empty"),
    ({"op": "text", "target": "body", "text": "a\nb", "size": 5, "depth": 1},
     "printable characters"),
    ({"op": "text", "target": "body", "text": "A", "size": 5, "depth": 1, "mode": "etch"},
     "mode must be 'engrave' or 'emboss'"),
    ({"op": "pattern", "of": "body", "count": [2, 2]}, "needs spacing"),
    ({"op": "pattern", "of": "body", "kind": "polar", "count": 4}, "needs a radius"),
    ({"op": "pattern", "of": "body", "kind": "polar", "count": [2, 2], "radius": 5},
     "polar pattern's count is one whole number"),
    ({"op": "pattern", "of": "body", "count": [2, 2], "spacing": [10, 0]},
     "spacing along y must be at least 0.1 mm"),
    ({"op": "pattern", "of": "body", "count": [51, 1], "spacing": [10, 0]},
     "count must be a whole number of 1–50"),
    ({"op": "pattern", "of": "body", "count": True, "spacing": [10, 0]},
     "count must be a whole number"),
    ({"op": "pattern", "of": "body", "kind": "polar", "count": 4, "radius": 5, "angle": 0},
     "angle must be more than 0°"),
    ({"op": "mirror", "target": "body", "plane": "xy"}, "plane must be 'XY', 'YZ' or 'XZ'"),
    ({"op": "drill", "target": "body"}, "Feature 2 has an unknown op 'drill'"),
    ({"target": "body"}, "Feature 2 needs an op"),
]


@pytest.mark.parametrize("feature, words", INVALID, ids=[item[0].get("op", "none")
                                                        for item in INVALID])
def test_each_op_refuses_bad_values(feature, words):
    assert words in error(tree(feature))


def test_types_are_strict():
    assert error(tree({"op": "hole", "target": "body", "at": [1, 2], "diameter": "5"})) == (
        "Feature 2 (hole): diameter must be a number."
    )
    assert "must be a number" in error(
        {"features": [{"op": "box", "size": [60, True, 20]}]}
    )
    assert "finite number" in error({"features": [{"op": "sphere", "diameter": float("nan")}]})
    assert "rotate must be at most 360°" in error(
        {"features": [{"op": "sphere", "diameter": 5, "rotate": [0, 0, 400]}]}
    )
    assert "material must be 'cyan', 'titanium', 'amber' or 'ceramic'" in error(
        {"features": [{"op": "sphere", "diameter": 5, "material": "gold"}]}
    )


# --- limits ------------------------------------------------------------------------------

def test_feature_count_limit():
    fillet = {"op": "fillet", "target": "body", "radius": 1}
    assert len(parse_tree(tree(*[fillet] * 39)).features) == 40
    assert error(tree(*[fillet] * 40)) == (
        "A design can have at most 40 features; this one has 41."
    )


def test_size_limits():
    assert parse_tree({"features": [{"op": "box", "size": [0.1, 2000, 10]}]})
    assert error({"features": [{"id": "b", "op": "box", "size": [0.05, 10, 10]}]}) == (
        "Feature b: size must be at least 0.1 mm."
    )
    assert error({"features": [{"op": "sphere", "diameter": 2001}]}) == (
        "Feature 1 (sphere): diameter must be at most 2000 mm."
    )
    assert "depth must be" in error(
        tree({"op": "hole", "target": "body", "at": [1, 2], "diameter": 5, "depth": 0.05})
    )
    assert "thickness must be at least 0.1 mm" in error(
        tree({"op": "shell", "target": "body", "thickness": 0.05})
    )


def test_text_limit():
    text = {"op": "text", "target": "body", "text": "J" * 40, "size": 5, "depth": 0.5}
    assert parse_tree(tree(text))
    assert error(tree({**text, "text": "J" * 41})) == (
        "Feature 2 (text feature): text can be at most 40 characters (this is 41)."
    )


def test_pattern_instance_limits():
    hole = {"id": "h", "op": "hole", "target": "body", "at": [1, 1], "diameter": 1}
    grid = {"op": "pattern", "of": "h", "count": [40, 5], "spacing": [1, 1]}
    assert parse_tree(tree(hole, grid)).features[2].instances() == 200
    assert error(tree(hole, {**grid, "count": [41, 5]})) == (
        "Feature 3 (pattern): a pattern can make at most 200 instances (this one makes 205)."
    )
    # 201 can't be one grid of at most 50 per axis, so the whole-tree count catches it.
    polar = {"op": "pattern", "of": "h", "kind": "polar", "count": 1, "radius": 5}
    assert error(tree(hole, grid, polar)) == (
        "The patterns in this design make 201 instances in all; the limit is 200."
    )


# --- references --------------------------------------------------------------------------

def test_missing_reference_names_the_feature_and_a_close_match():
    assert error(spec(f1={"target": "bodyy"})) == (
        "Feature h1 targets 'bodyy', which doesn't exist. Did you mean 'body'?"
    )
    assert error(tree({"op": "fillet", "target": "lid", "radius": 1})) == (
        "Feature 2 (fillet) targets 'lid', which doesn't exist."
    )
    assert error(spec(f2={"of": "h2"})).startswith(
        "Feature 3 (pattern) repeats 'h2', which doesn't exist."
    )


def test_forward_and_self_references():
    data = copy.deepcopy(SPEC)
    data["features"][1], data["features"][2] = data["features"][2], data["features"][1]
    assert error(data) == (
        "Feature 2 (pattern) repeats 'h1', which comes later in the tree. Put 'h1' before it."
    )
    assert error(tree({"id": "p", "op": "pattern", "of": "p", "count": 2,
                       "spacing": [5, 0]})) == "Feature p repeats itself."


def test_first_feature_must_make_a_solid():
    data = copy.deepcopy(SPEC)
    data["features"].insert(0, data["features"].pop(1))
    assert error(data) == (
        "The first feature must make a solid (a box, cylinder, sphere, L bracket or "
        "enclosure); feature h1 is a hole."
    )


def test_targets_and_sources_must_be_the_right_kind():
    hole = {"id": "h", "op": "hole", "target": "body", "at": [1, 1], "diameter": 1}
    assert error(tree(hole, {"op": "fillet", "target": "h", "radius": 1})) == (
        "Feature 3 (fillet) targets 'h', which is a hole, not a solid. Use a box, cylinder, "
        "sphere, L bracket or enclosure."
    )
    round_ = {"id": "r", "op": "fillet", "target": "body", "radius": 1}
    assert "A pattern repeats a hole, slot, text" in error(
        tree(round_, {"op": "pattern", "of": "r", "count": 2, "spacing": [5, 0]})
    )
    lid = {"id": "lid", "op": "box", "size": [5, 5, 5]}
    joined = {"id": "u", "op": "cut", "target": "body", "bodies": ["lid"]}
    assert "a cut with a tool shape" in error(
        tree(lid, joined, {"op": "pattern", "of": "u", "count": 2, "spacing": [5, 0]})
    )


def test_bodies_merge_and_are_consumed():
    boss = {"id": "boss", "op": "cylinder", "diameter": 8, "height": 10, "at": [0, 0, 25]}
    union = {"id": "u1", "op": "union", "target": "body", "bodies": ["boss"]}
    parsed = parse_tree(tree(boss, union, {"op": "fillet", "target": "body", "radius": 1}))
    assert describe(parsed)[2] == "Join boss to body"
    assert error(tree(boss, union, {"op": "fillet", "target": "boss", "radius": 1})) == (
        "Feature 4 (fillet) targets 'boss', which feature u1 already merged into 'body'. "
        "Use 'body' instead."
    )
    assert error(tree(boss, {"op": "union", "target": "body", "bodies": ["body"]})) == (
        "Feature 3 (union) joins its own target 'body'."
    )
    assert error(tree(boss, {"op": "cut", "target": "body", "bodies": ["boss", "boss"]})) == (
        "Feature 3 (cut) lists 'boss' twice."
    )
    hole = {"id": "h", "op": "hole", "target": "boss", "at": [1, 1], "diameter": 1}
    assert "Repeat it before the merge" in error(
        tree(boss, hole, union, {"op": "pattern", "of": "h", "count": 2, "spacing": [3, 0]})
    )


def test_ids_are_unique_and_well_formed():
    assert error(spec(f1={"id": "body"})) == (
        "Two features are called 'body'. Give each feature its own id."
    )
    assert error(spec(f1={"id": "a b"})) == (
        "Feature 2 (hole): id 'a b' must be 1–32 letters, digits, '-' or '_'."
    )
    assert "must be 1–32" in error(spec(f1={"id": "x" * 33}))
    assert "must be 1–32" in error(spec(f1={"id": ""}))
    assert parse_tree(spec(f3={"id": "A-z_09" + "x" * 26}))


def test_shell_thickness_is_checked_when_knowable():
    assert error(spec(f6={"thickness": 10})) == (
        "Feature 7 (shell) makes walls 10 mm thick, but 'body' is only 20 mm at its "
        "thinnest. Keep the walls under 10 mm."
    )
    assert parse_tree(spec(f6={"thickness": 9.9}))
    shell = {"op": "shell", "target": "body", "thickness": 15}
    assert "only 30 mm" in error({"features": [{"id": "body", "op": "cylinder", "diameter": 30,
                                                "height": 40}, shell]})
    # After a union, or on an enclosure, the kernel decides.
    union = {"op": "union", "target": "body", "tool": {"op": "box", "size": [60, 40, 40]}}
    assert parse_tree(tree(union, shell))
    assert parse_tree({"features": [{"id": "body", "op": "enclosure", "size": [80, 60, 20],
                                     "thickness": 2}, shell]})


# --- hash --------------------------------------------------------------------------------

def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reordered(item) for item in value]
    return value


def floats(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, dict):
        return {key: item if key == "count" else floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [floats(item) for item in value]
    return value


def test_hash_is_stable():
    digest = tree_hash(SPEC)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert tree_hash(reordered(SPEC)) == digest
    assert tree_hash(floats(SPEC)) == digest
    assert tree_hash(json.dumps(SPEC, indent=4)) == digest
    assert tree_hash(json.dumps(SPEC, separators=(",", ":"))) == digest
    assert tree_hash(parse_tree(SPEC)) == digest
    # Defaults filled: explicit defaults hash like omitted ones.
    explicit = copy.deepcopy(SPEC)
    explicit["features"][0].update(rotate=[0, 0, -0.0], scale=[1, 1, 1])
    explicit["features"][7]["at"] = None
    assert tree_hash(explicit) == digest
    assert tree_hash({**SPEC, "export": ["step", "stl", "glb"]}) == digest
    assert canonical(SPEC) == canonical(reordered(SPEC))
    assert '"size":[60,40,20]' in canonical(floats(SPEC))


def test_hash_changes_with_any_value():
    digest = tree_hash(SPEC)
    assert tree_hash(spec(f1={"diameter": 5.5})) != digest
    assert tree_hash(spec(f0={"at": [0, 0, 10.001]})) != digest
    assert tree_hash(spec(f7={"text": "JARVIS2"})) != digest
    assert tree_hash({**SPEC, "export": ["glb"]}) != digest


# --- describe ----------------------------------------------------------------------------

def test_describe_each_op():
    lines = describe(tree(*VALID))
    assert lines == [
        "body: Box 60 × 40 × 20 mm",
        "peg: Cylinder Ø10 mm, 30 mm tall, rotated 90°, 0°, 0°, amber",
        "ball: Sphere Ø12 mm, scaled 1 × 1 × 2",
        "arm: L bracket 40 × 30 × 25 mm, 3 mm thick",
        "case: Open enclosure 80 × 60 × 30 mm, 2 mm walls",
        "Through hole Ø5 mm on the top face of body at (10, 5)",
        "Blind hole Ø5 mm, 8 mm deep, on the front face of body at (10, 5)",
        "Counterbored hole Ø5 mm (through), Ø9 × 3 mm counterbore, on the top face of body "
        "at (10, 5)",
        "Slot 20 × 5 mm, 3 mm deep, turned 45°, on the top face of body at (30, 20)",
        "Cut a cylinder Ø8 mm, 50 mm tall at (0, 0, 0) from body",
        "Join a box 10 × 10 × 10 mm at (0, 0, 25) to body",
        "Round all edges of body, 1000 mm radius",
        "Chamfer the bottom edges of body by 0.1 mm",
        "Shell body to 2 mm walls, open at the bottom",
        "Emboss “A1 – ok!” on the front face of body at (30, 10), 6 mm tall, 0.5 mm high",
        "Mirror body across the YZ plane",
    ]


def test_describe_patterns_and_slots():
    hole = {"id": "h", "op": "hole", "target": "body", "at": [10, 5], "diameter": 3,
            "depth": 4}
    assert describe(tree(
        hole,
        {"op": "pattern", "of": "h", "count": [4, 1], "spacing": [12.5, 0]},
        {"op": "pattern", "of": "h", "count": [1, 3], "spacing": [0, 7]},
        {"op": "slot", "target": "body", "at": [1, 2], "length": 9, "width": 3},
    ))[1:] == [
        "Blind hole Ø3 mm, 4 mm deep, on the top face at (10, 5)",
        "Repeat hole h 4 times, 12.5 mm apart",
        "Repeat hole h 3 times, 7 mm apart",
        "Through slot 9 × 3 mm on the top face at (1, 2)",
    ]


# --- today's live design parts -----------------------------------------------------------

def test_materials_are_the_live_design_names():
    assert MATERIALS == typing.get_args(SceneObject.model_fields["material"].annotation)


PARTS = [
    {"name": "Base plate", "shape": "box", "width": 120.0, "depth": 80.0, "height": 6.0,
     "position": [-60.0, -40.0, 0.0], "material": "titanium"},
    {"name": "Arm", "shape": "bracket", "width": 40.0, "depth": 30.0, "height": 50.0,
     "thickness": 4.0, "position": [10.0, 5.0, 6.0], "rotation": [0.0, 0.0, 90.0],
     "scale": [1.0, 2.0, 0.5], "material": "amber"},
    {"name": "Arm", "shape": "enclosure", "width": 160.0, "depth": 200.0, "height": 180.0,
     "thickness": 3.0, "position": [300.0, -20.0, 15.0], "rotation": [30.0, -45.0, 10.0],
     "scale": [1.5, 1.0, 0.8], "material": "ceramic"},
    {"name": "!!!", "shape": "box", "width": 1000.0, "depth": 1000.0, "height": 1000.0,
     "position": [2000.0, 2000.0, 2000.0], "rotation": [360.0, 360.0, 360.0],
     "scale": [5.0, 5.0, 5.0]},
]


def corners(size):
    return [(x, y, z) for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]


def placed_corners(feature):
    """World corners of a tree solid: centred, scaled, rotated X/Y/Z, moved to ``at``."""
    placement = {"scale": feature.scale, "rotation": feature.rotate, "position": feature.at}
    return [
        transform([value - extent / 2 for value, extent in zip(corner, feature.size,
                                                                strict=True)], placement)
        for corner in corners(feature.size)
    ]


@pytest.mark.parametrize("part", PARTS, ids=["box", "bracket", "enclosure", "extreme"])
def test_from_parts_round_trip_per_kind(part):
    live = LivePart.model_validate(part).model_dump()
    converted = from_parts([live])
    (feature,) = converted.features
    assert feature.op == {"box": "box", "bracket": "l_bracket", "enclosure": "enclosure"}[
        live["shape"]
    ]
    assert feature.size == [live["width"], live["depth"], live["height"]]
    assert feature.rotate == live["rotation"] and feature.scale == live["scale"]
    assert feature.material == live["material"]
    if live["shape"] != "box":
        assert feature.thickness == live["thickness"]
    else:
        assert not hasattr(feature, "thickness")
    expected = [transform(corner, live) for corner in corners(feature.size)]
    for got, want in zip(placed_corners(feature), expected, strict=True):
        assert got == pytest.approx(want, abs=1e-5)
    # Through JSON and back: the same tree, the same hash.
    again = parse_tree(json.loads(canonical(converted)))
    assert again == converted and tree_hash(again) == tree_hash(converted)
    assert converted.export == ["glb", "stl"]


def test_from_parts_keeps_every_part_and_names_them():
    converted = from_parts([LivePart.model_validate(part) for part in PARTS])
    assert [feature.id for feature in converted.features] == [
        "Base-plate", "Arm", "Arm-2", "box"
    ]
    assert describe(converted)[:2] == [
        "Base-plate: Box 120 × 80 × 6 mm, titanium",
        "Arm: L bracket 40 × 30 × 50 mm, 4 mm thick, scaled 1 × 2 × 0.5, rotated 0°, 0°, 90°, "
        "amber",
    ]
    long = from_parts([{**PARTS[0], "name": "x" * 60}, {**PARTS[0], "name": "x" * 60}])
    assert [feature.id for feature in long.features] == ["x" * 32, "x" * 30 + "-2"]
    assert from_parts(PARTS[:1], export=["step"]).export == ["step"]
    with pytest.raises(FeatureTreeError):
        from_parts([{**PARTS[0], "shape": "scene"}])
    with pytest.raises(FeatureTreeError):
        from_parts([])
