"""Feature trees for the JARVIS CAD kernel: validated models, plain-English steps, a stable hash.

The brain never writes Python: it emits a feature tree, this module validates it, and an
isolated worker (``.venv-cad``, build123d) later turns it into geometry. This module is pure:
no I/O and no build123d import. Spec: docs/handover/9NovWork-specs.md S3.

Conventions (millimetres, Z up)
- Faces: top +Z, bottom -Z, front -Y, back +Y, left -X, right +X. A body's face is that face
  of the body's bounding box.
- A solid's ``at`` is the centre of its bounding box. ``scale`` (the solid's own axes, about
  its centre) applies first, then ``rotate`` in degrees about the centre: X, then Y, then Z,
  about the fixed world axes. That is the order of today's scene parts (creative/scene.py).
- A face placement ``at`` is (u, v) in mm from the face's corner with the smallest world
  coordinates: top/bottom use (X, Y), front/back (X, Z), left/right (Y, Z). Text without
  ``at`` is centred on the face.
- Cylinders stand along Z. An L bracket has its base on the bottom and its upright along the
  front (-Y) edge. An enclosure has four walls and a floor of one thickness, open at the top.
  (These match the offline engine's bracket and enclosure, creative/geometry.py.)
- Holes and slots go into the body, normal to their face; a number ``depth`` is blind.
- Every solid feature starts a separate body. ``union`` and ``cut`` with ``bodies`` merge
  other bodies into their target; whatever bodies remain at the end are exported together.

Reference rules
- ``target`` names an earlier solid (box, cylinder, sphere, l_bracket, enclosure) that no
  ``union``/``cut`` has merged into another body yet. Ids of other features can't be targeted.
- ``bodies`` (union, cut) names other earlier live solids; they are consumed by that feature.
- ``of`` (pattern) names an earlier hole, slot, text, ``cut`` with an inline ``tool``, or a live
  solid. Repeating a feature repeats it on the same target (which must still be live);
  repeating a solid adds the copies to that solid. Patterns, fillets, chamfers, shells,
  unions, mirrors and ``cut`` with ``bodies`` can't be repeated.
- Patterns make at most 200 instances, counted over the whole tree.
- A linear pattern includes the original: count [2, 2] is four instances, offset by spacing
  in the face axes (u, v) for holes, slots and text, world (X, Y) for solids and cuts. A polar
  pattern places ``count`` instances on a circle of ``radius`` round the original's position,
  evenly over ``angle`` degrees (360 by default), turning about the face normal (holes, slots,
  text) or world Z (solids, cuts).
- ``mirror`` adds a mirrored copy of the target to itself across a plane through the origin.
"""

import difflib
import hashlib
import json
import math
import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    ValidationError,
    field_validator,
    model_validator,
)

from creative.scene import MATERIALS as SCENE_MATERIALS, transform

MAX_FEATURES = 40
MIN_MM, MAX_MM = 0.1, 2000
MAX_EDGE_MM = 1000  # fillet radius and chamfer distance
MAX_COORD = 10000  # positions are coordinates, not sizes: scaled parts reach past 2000 mm
MAX_TEXT = 40
MAX_AXIS_COUNT = 50
MAX_INSTANCES = 200
MAX_ID = 32
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}")

MATERIALS = tuple(SCENE_MATERIALS)  # the live design's names: cyan, titanium, amber, ceramic
EXPORTS = ("glb", "stl", "step")
SOLID_OPS = ("box", "cylinder", "sphere", "l_bracket", "enclosure")
FACE_FEATURES = ("hole", "slot", "text")
NOUNS = {
    "box": "box",
    "cylinder": "cylinder",
    "sphere": "sphere",
    "l_bracket": "L bracket",
    "enclosure": "enclosure",
    "hole": "hole",
    "slot": "slot",
    "cut": "cut",
    "union": "union",
    "fillet": "fillet",
    "chamfer": "chamfer",
    "shell": "shell",
    "text": "text feature",
    "pattern": "pattern",
    "mirror": "mirror",
}
OPS = tuple(NOUNS)
SHAPE_OPS = {"box": "box", "bracket": "l_bracket", "enclosure": "enclosure"}
SOLIDS_PHRASE = "a box, cylinder, sphere, L bracket or enclosure"


class FeatureTreeError(ValueError):
    """An invalid feature tree; ``str()`` is the first owner-readable message."""

    code = "cad_tree_invalid"

    def __init__(self, messages):
        self.messages = list(messages) or ["That feature tree isn't valid."]
        super().__init__(self.messages[0])


def number(value):
    return f"{round(float(value), 2):g}"


def article(noun):
    return "an" if noun in ("enclosure", "L bracket") else "a"


def lowered(text):
    return text[:1].lower() + text[1:]


def quoted_ref(value):
    text = value if isinstance(value, str) else str(value)
    return "'" + (text if len(text) <= 40 else text[:39] + "…") + "'"


# --- field types -------------------------------------------------------------------------

def finite(low, high, **bounds):
    return Annotated[float, Strict(), Field(ge=low, le=high, allow_inf_nan=False, **bounds)]


Mm = finite(MIN_MM, MAX_MM)
EdgeMm = finite(MIN_MM, MAX_EDGE_MM)
Coord = finite(-MAX_COORD, MAX_COORD)
Degrees = finite(-360, 360)
Factor = finite(0.1, 5)
Spacing = finite(-MAX_MM, MAX_MM)
Face = Literal["top", "bottom", "front", "back", "left", "right"]
Edges = Literal["all", "vertical", "top", "bottom"]
Material = Literal[MATERIALS]  # type: ignore[valid-type]


def checked_depth(value):
    if value == "through":
        return value
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not MIN_MM <= value <= MAX_MM
    ):
        raise ValueError(
            f"depth must be \"through\" or a depth of {number(MIN_MM)}–{number(MAX_MM)} mm"
        )
    return float(value)


def checked_count(value):
    def whole(item):
        return (
            isinstance(item, int)
            and not isinstance(item, bool)
            and 1 <= item <= MAX_AXIS_COUNT
        )

    if whole(value) or (isinstance(value, list) and len(value) == 2 and all(map(whole, value))):
        return value
    raise ValueError(
        f"count must be a whole number of 1–{MAX_AXIS_COUNT}, or [x, y] with each 1–"
        f"{MAX_AXIS_COUNT}"
    )


Depth = Annotated[Literal["through"] | float, BeforeValidator(checked_depth)]
PatternCount = Annotated[int | list[int], BeforeValidator(checked_count)]


def vector(length, default=None):
    if default is None:
        return Field(min_length=length, max_length=length)
    return Field(default_factory=lambda: list(default), min_length=length, max_length=length)


# --- models ------------------------------------------------------------------------------

class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Named(Spec):
    id: str | None = None

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        if value is not None and not ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"id {quoted_ref(value)} must be 1–{MAX_ID} letters, digits, '-' or '_'"
            )
        return value


class Placed(Spec):
    at: list[Coord] = vector(3, (0.0, 0.0, 0.0))
    rotate: list[Degrees] = vector(3, (0.0, 0.0, 0.0))
    scale: list[Factor] = vector(3, (1.0, 1.0, 1.0))


class BoxShape(Placed):
    op: Literal["box"]
    size: list[Mm] = vector(3)


class CylinderShape(Placed):
    op: Literal["cylinder"]
    diameter: Mm
    height: Mm


class SphereShape(Placed):
    op: Literal["sphere"]
    diameter: Mm


class LBracketShape(Placed):
    op: Literal["l_bracket"]
    size: list[Mm] = vector(3)
    thickness: Mm

    @model_validator(mode="after")
    def valid_legs(self):
        # The offline engine's rule (services/cad.py SolidRecipe).
        if min(self.size[1], self.size[2]) - self.thickness < 0.5:
            raise ValueError(
                "an L bracket's depth and height must each be at least 0.5 mm more than its "
                "thickness"
            )
        return self


class EnclosureShape(Placed):
    op: Literal["enclosure"]
    size: list[Mm] = vector(3)
    thickness: Mm

    @model_validator(mode="after")
    def valid_walls(self):
        width, depth, height = self.size
        if min(depth, height) - self.thickness < 0.5:
            raise ValueError(
                "an enclosure's depth and height must each be at least 0.5 mm more than its "
                "wall thickness"
            )
        if min(width, depth) - 2 * self.thickness < 0.5:
            raise ValueError("an enclosure's opening must be at least 0.5 mm wide")
        return self


Shape = Annotated[
    BoxShape | CylinderShape | SphereShape | LBracketShape | EnclosureShape,
    Field(discriminator="op"),
]


class Solid(Named):
    material: Material | None = None


class BoxFeature(BoxShape, Solid):
    pass


class CylinderFeature(CylinderShape, Solid):
    pass


class SphereFeature(SphereShape, Solid):
    pass


class LBracketFeature(LBracketShape, Solid):
    pass


class EnclosureFeature(EnclosureShape, Solid):
    pass


class Targeted(Named):
    target: str


class OnFace(Targeted):
    face: Face = "top"


class HoleFeature(OnFace):
    op: Literal["hole"]
    at: list[Coord] = vector(2)
    diameter: Mm
    depth: Depth = "through"
    cb_diameter: Mm | None = None
    cb_depth: Mm | None = None

    @model_validator(mode="after")
    def valid_counterbore(self):
        if (self.cb_diameter is None) != (self.cb_depth is None):
            raise ValueError("a counterbore needs both cb_diameter and cb_depth")
        if self.cb_diameter is not None:
            if self.cb_diameter <= self.diameter:
                raise ValueError(
                    f"the counterbore (Ø{number(self.cb_diameter)} mm) must be wider than the "
                    f"hole (Ø{number(self.diameter)} mm)"
                )
            if self.depth != "through" and self.cb_depth >= self.depth:
                raise ValueError(
                    f"the counterbore ({number(self.cb_depth)} mm) must be shallower than the "
                    f"hole ({number(self.depth)} mm)"
                )
        return self


class SlotFeature(OnFace):
    op: Literal["slot"]
    at: list[Coord] = vector(2)
    length: Mm
    width: Mm
    depth: Depth = "through"
    angle: Degrees = 0.0

    @model_validator(mode="after")
    def valid_shape(self):
        if self.width >= self.length:
            raise ValueError(
                f"a slot must be longer than it is wide ({number(self.length)} mm long, "
                f"{number(self.width)} mm wide)"
            )
        return self


class Combine(Targeted):
    tool: Shape | None = None
    bodies: list[str] | None = Field(default=None, min_length=1, max_length=MAX_FEATURES)

    @model_validator(mode="after")
    def one_source(self):
        if (self.tool is None) == (self.bodies is None):
            raise ValueError("give either a tool shape or bodies, not both and not neither")
        return self


class CutFeature(Combine):
    op: Literal["cut"]


class UnionFeature(Combine):
    op: Literal["union"]


class FilletFeature(Targeted):
    op: Literal["fillet"]
    edges: Edges = "all"
    radius: EdgeMm


class ChamferFeature(Targeted):
    op: Literal["chamfer"]
    edges: Edges = "all"
    distance: EdgeMm


class ShellFeature(Targeted):
    op: Literal["shell"]
    thickness: Mm
    open: Face = "top"


class TextFeature(OnFace):
    op: Literal["text"]
    text: str
    size: Mm
    depth: Mm
    mode: Literal["engrave", "emboss"] = "engrave"
    at: list[Coord] | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        if not value.strip():
            raise ValueError("text can't be empty")
        if len(value) > MAX_TEXT:
            raise ValueError(
                f"text can be at most {MAX_TEXT} characters (this is {len(value)})"
            )
        if not value.isprintable():
            raise ValueError("text can only use printable characters")
        return value


class PatternFeature(Named):
    op: Literal["pattern"]
    of: str
    kind: Literal["linear", "polar"] = "linear"
    count: PatternCount
    spacing: list[Spacing] | None = Field(default=None, min_length=2, max_length=2)
    radius: Mm | None = None
    angle: Annotated[float, Strict(), Field(gt=0, le=360, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def valid_kind(self):
        if self.kind == "linear":
            if isinstance(self.count, int):
                self.count = [self.count, 1]
            if self.spacing is None:
                raise ValueError("a linear pattern needs spacing as [x, y] in mm")
            if self.radius is not None or self.angle is not None:
                raise ValueError("radius and angle are for polar patterns")
            for axis, (count, gap) in enumerate(zip(self.count, self.spacing, strict=True)):
                if count > 1 and abs(gap) < MIN_MM:
                    raise ValueError(
                        f"spacing along {'xy'[axis]} must be at least {number(MIN_MM)} mm "
                        "when it repeats"
                    )
            total = self.count[0] * self.count[1]
            if total > MAX_INSTANCES:
                raise ValueError(
                    f"a pattern can make at most {MAX_INSTANCES} instances (this one makes "
                    f"{total})"
                )
        else:
            if not isinstance(self.count, int):
                raise ValueError("a polar pattern's count is one whole number")
            if self.radius is None:
                raise ValueError("a polar pattern needs a radius in mm")
            if self.spacing is not None:
                raise ValueError("spacing is for linear patterns")
            if self.angle is None:
                self.angle = 360.0
        return self

    def instances(self):
        return self.count[0] * self.count[1] if self.kind == "linear" else self.count


class MirrorFeature(Targeted):
    op: Literal["mirror"]
    plane: Literal["XY", "YZ", "XZ"]


Feature = Annotated[
    BoxFeature
    | CylinderFeature
    | SphereFeature
    | LBracketFeature
    | EnclosureFeature
    | HoleFeature
    | SlotFeature
    | CutFeature
    | UnionFeature
    | FilletFeature
    | ChamferFeature
    | ShellFeature
    | TextFeature
    | PatternFeature
    | MirrorFeature,
    Field(discriminator="op"),
]


class FeatureTree(Spec):
    units: Literal["mm"] = "mm"
    features: list[Feature] = Field(min_length=1, max_length=MAX_FEATURES)
    export: list[Literal["glb", "stl", "step"]] = Field(
        default_factory=lambda: ["glb"], min_length=1, max_length=len(EXPORTS)
    )

    @field_validator("export")
    @classmethod
    def canonical_export(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("list each export format once")
        return [name for name in EXPORTS if name in value]

    @model_validator(mode="after")
    def valid_references(self):
        check_references(self.features)
        return self


# --- references --------------------------------------------------------------------------

def label(feature, index):
    if feature.id:
        return f"Feature {feature.id}"
    return f"Feature {index + 1} ({NOUNS[feature.op]})"


def smallest_side(feature):
    """The solid's thinnest extent, when its kind makes that knowable."""
    sx, sy, sz = feature.scale
    if feature.op == "box":
        return min(feature.size[0] * sx, feature.size[1] * sy, feature.size[2] * sz)
    if feature.op == "cylinder":
        return min(feature.diameter * min(sx, sy), feature.height * sz)
    if feature.op == "sphere":
        return feature.diameter * min(sx, sy, sz)
    return None


def check_references(features):
    labels = [label(feature, index) for index, feature in enumerate(features)]
    where = {}
    for index, feature in enumerate(features):
        if feature.id is None:
            continue
        if feature.id in where:
            raise ValueError(
                f"Two features are called '{feature.id}'. Give each feature its own id."
            )
        where[feature.id] = index
    first = features[0]
    if first.op not in SOLID_OPS:
        noun = NOUNS[first.op]
        raise ValueError(
            f"The first feature must make a solid ({SOLIDS_PHRASE}); {lowered(labels[0])} is "
            f"{article(noun)} {noun}."
        )
    instances = sum(feature.instances() for feature in features if feature.op == "pattern")
    if instances > MAX_INSTANCES:
        raise ValueError(
            f"The patterns in this design make {instances} instances in all; the limit is "
            f"{MAX_INSTANCES}."
        )
    merged = {}  # solid index -> (label of the merging feature, id it merged into)
    grown = set()  # solids whose bounding box may have grown past the primitive

    def find(index, ref, verb):
        if ref not in where:
            message = f"{labels[index]} {verb} {quoted_ref(ref)}, which doesn't exist."
            close = difflib.get_close_matches(ref, list(where), n=1)
            if close:
                message += f" Did you mean '{close[0]}'?"
            raise ValueError(message)
        found = where[ref]
        if found == index:
            raise ValueError(f"{labels[index]} {verb} itself.")
        if found > index:
            raise ValueError(
                f"{labels[index]} {verb} '{ref}', which comes later in the tree. Put '{ref}' "
                "before it."
            )
        return found

    def live_solid(index, ref, verb):
        found = find(index, ref, verb)
        feature = features[found]
        if feature.op not in SOLID_OPS:
            noun = NOUNS[feature.op]
            raise ValueError(
                f"{labels[index]} {verb} '{ref}', which is {article(noun)} {noun}, not a solid. "
                f"Use {SOLIDS_PHRASE}."
            )
        if found in merged:
            by, into = merged[found]
            raise ValueError(
                f"{labels[index]} {verb} '{ref}', which {lowered(by)} already merged into "
                f"'{into}'. Use '{into}' instead."
            )
        return found

    for index, feature in enumerate(features):
        op = feature.op
        if op in SOLID_OPS:
            continue
        if op == "pattern":
            source = find(index, feature.of, "repeats")
            original = features[source]
            if original.op in SOLID_OPS:
                grown.add(live_solid(index, feature.of, "repeats"))
            elif original.op in FACE_FEATURES or (
                original.op == "cut" and original.tool is not None
            ):
                body = where[original.target]
                if body in merged:
                    by, into = merged[body]
                    raise ValueError(
                        f"{labels[index]} repeats '{feature.of}', but its body "
                        f"'{original.target}' was merged into '{into}' by {lowered(by)}. "
                        "Repeat it before the merge."
                    )
                if original.op == "text" and original.mode == "emboss":
                    grown.add(body)
            else:
                noun = NOUNS[original.op]
                raise ValueError(
                    f"{labels[index]} repeats '{feature.of}', which is {article(noun)} {noun}. "
                    "A pattern repeats a hole, slot, text, a cut with a tool shape, or a solid."
                )
            continue
        body = live_solid(index, feature.target, "targets")
        if op in ("cut", "union") and feature.bodies is not None:
            verb = "cuts with" if op == "cut" else "joins"
            seen = set()
            for ref in feature.bodies:
                other = live_solid(index, ref, verb)
                if other == body:
                    raise ValueError(f"{labels[index]} {verb} its own target '{ref}'.")
                if other in seen:
                    raise ValueError(f"{labels[index]} lists '{ref}' twice.")
                seen.add(other)
            for other in seen:
                merged[other] = (labels[index], feature.target)
                if other in grown:
                    grown.add(body)
            if op == "union":
                grown.add(body)
        elif op == "union" or op == "mirror" or (op == "text" and feature.mode == "emboss"):
            grown.add(body)
        elif op == "shell" and body not in grown:
            side = smallest_side(features[body])
            if side is not None and feature.thickness >= side / 2:
                raise ValueError(
                    f"{labels[index]} makes walls {number(feature.thickness)} mm thick, but "
                    f"'{feature.target}' is only {number(side)} mm at its thinnest. Keep the "
                    f"walls under {number(side / 2)} mm."
                )


# --- parsing and owner-readable errors ---------------------------------------------------

UNITS = {"rotate": "°", "angle": "°", "scale": "", "count": ""}
VECTORS = {"size": 3, "rotate": 3, "scale": 3, "spacing": 2}


def raw_feature(data, index):
    features = data.get("features") if isinstance(data, dict) else None
    if isinstance(features, list) and 0 <= index < len(features):
        item = features[index]
        return item if isinstance(item, dict) else {}
    return {}


def subject(data, loc):
    """("Feature h1", ["tool", "size"]) for a pydantic error location."""
    if len(loc) >= 2 and loc[0] == "features" and isinstance(loc[1], int):
        raw = raw_feature(data, loc[1])
        ident, op = raw.get("id"), raw.get("op")
        if isinstance(ident, str) and ID_PATTERN.fullmatch(ident):
            who = f"Feature {ident}"
        elif isinstance(op, str) and op in NOUNS:
            who = f"Feature {loc[1] + 1} ({NOUNS[op]})"
        else:
            who = f"Feature {loc[1] + 1}"
        rest = list(loc[2:])
        if rest and rest[0] in OPS:
            rest = rest[1:]
        names, skip = [], False
        for item in rest:
            if skip:
                skip = False
                if item in OPS:
                    continue
            if isinstance(item, str):
                names.append(item)
                skip = item == "tool"
        return who, names
    return "The design", [item for item in loc if isinstance(item, str)]


def sentence(text):
    text = text.strip()
    return text if text.endswith((".", "?", "!")) else text + "."


def readable(error, data):
    kind, loc, ctx = error.get("type", ""), tuple(error.get("loc", ())), error.get("ctx") or {}
    message = str(error.get("msg", "")).removeprefix("Value error, ")
    if kind == "value_error" and not loc:
        return sentence(message)
    if loc[:1] == ("features",) and len(loc) == 1:
        if kind == "too_long":
            return (
                f"A design can have at most {MAX_FEATURES} features; this one has "
                f"{ctx.get('actual_length')}."
            )
        if kind == "too_short":
            return "A design needs at least one feature."
        if kind == "list_type":
            return "The design's features must be a list."
    who, names = subject(data, loc)
    field = " ".join(names[-2:]) if names[:1] == ["tool"] else (names[-1] if names else "")
    unit = UNITS.get(names[-1] if names else "", " mm")
    if who == "The design" and not field:
        return "A feature tree must be an object with units, features and export."
    if kind == "union_tag_invalid":
        return (
            f"{who} has an unknown op {quoted_ref(ctx.get('tag', ''))}. Use one of: "
            + ", ".join(OPS)
            + "."
        )
    if kind == "union_tag_not_found":
        return f"{who} needs an op ({', '.join(OPS)})."
    if kind in ("model_attributes_type", "dict_type", "model_type"):
        return f"{who} must be an object with an op."
    if kind == "missing":
        return f"{who} needs {field}."
    if kind == "extra_forbidden":
        if names[:1] == ["tool"] and len(names) > 1:
            return f"{who}: the tool shape doesn't take {names[-1]}."
        return f"{who} doesn't take {field}."
    if kind == "value_error":
        return sentence(f"{who}: {message}")
    bounds = {
        "greater_than_equal": ("at least", "ge"),
        "greater_than": ("more than", "gt"),
        "less_than_equal": ("at most", "le"),
        "less_than": ("less than", "lt"),
    }
    if kind in bounds:
        words, key = bounds[kind]
        return f"{who}: {field} must be {words} {number(ctx.get(key, 0))}{unit}."
    if kind == "literal_error":
        return f"{who}: {field} must be {ctx.get('expected', 'one of the listed values')}."
    if kind == "finite_number":
        return f"{who}: {field} must be a finite number."
    if kind in ("float_type", "int_type", "float_parsing", "int_parsing"):
        return f"{who}: {field} must be a number."
    if kind == "string_type":
        return f"{who}: {field} must be text."
    if kind == "list_type":
        return f"{who}: {field} must be a list."
    if kind in ("too_short", "too_long"):
        last = names[-1] if names else ""
        exact = VECTORS.get(last)
        if last == "at":
            op = "box" if names[:1] == ["tool"] else raw_feature(data, loc[1]).get("op")
            exact = 2 if op in FACE_FEATURES else 3
        if exact:
            return f"{who}: {field} must have {exact} values."
        if kind == "too_short":
            return f"{who}: {field} must have at least {ctx.get('min_length')} value(s)."
        return f"{who}: {field} can have at most {ctx.get('max_length')} values."
    detail = " ".join(part for part in (field, message[:1].lower() + message[1:]) if part)
    return sentence(f"{who}: {detail}")


def parse_tree(data):
    """A validated ``FeatureTree`` from a dict (or JSON text); raises ``FeatureTreeError``."""
    if isinstance(data, FeatureTree):
        return data
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except ValueError:
            raise FeatureTreeError(["That feature tree isn't valid JSON."]) from None
    if not isinstance(data, dict):
        raise FeatureTreeError(
            ["A feature tree must be an object with units, features and export."]
        )
    try:
        return FeatureTree.model_validate(data)
    except ValidationError as exc:
        messages = list(
            dict.fromkeys(readable(error, data) for error in exc.errors(include_url=False))
        )
        raise FeatureTreeError(messages) from None


# --- hash --------------------------------------------------------------------------------

def normalised(value):
    """Numbers as the shortest stable form: 10 and 10.0 both become 10; -0.0 becomes 0."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 9)
        if rounded == 0:
            return 0
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        return {key: normalised(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalised(item) for item in value]
    return value


def canonical(tree):
    """Canonical JSON of the tree: defaults filled, keys sorted, numbers normalised."""
    tree = parse_tree(tree)
    return json.dumps(
        normalised(tree.model_dump(mode="json")),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def tree_hash(tree):
    """SHA-256 hex of ``canonical(tree)``; independent of key order, whitespace and 10 vs 10.0."""
    return hashlib.sha256(canonical(tree).encode("utf-8")).hexdigest()


# --- plain-English steps -----------------------------------------------------------------

EDGE_WORDS = {"all": "all edges", "vertical": "the vertical edges", "top": "the top edges",
              "bottom": "the bottom edges"}


def dims(values):
    return " × ".join(number(value) for value in values)


def point(values):
    return "(" + ", ".join(number(value) for value in values) + ")"


def shape_words(shape):
    op = shape.op
    if op == "box":
        text = f"Box {dims(shape.size)} mm"
    elif op == "cylinder":
        text = f"Cylinder Ø{number(shape.diameter)} mm, {number(shape.height)} mm tall"
    elif op == "sphere":
        text = f"Sphere Ø{number(shape.diameter)} mm"
    elif op == "l_bracket":
        text = f"L bracket {dims(shape.size)} mm, {number(shape.thickness)} mm thick"
    else:
        text = f"Open enclosure {dims(shape.size)} mm, {number(shape.thickness)} mm walls"
    if list(shape.scale) != [1, 1, 1]:
        text += f", scaled {dims(shape.scale)}"
    if any(shape.rotate):
        text += ", rotated " + ", ".join(number(value) + "°" for value in shape.rotate)
    return text


def tool_words(shape):
    text = shape_words(shape)
    return f"{article(NOUNS[shape.op])} {text[0].lower()}{text[1:]} at {point(shape.at)}"


def names(refs):
    refs = list(refs)
    return refs[0] if len(refs) == 1 else ", ".join(refs[:-1]) + " and " + refs[-1]


def describe(tree):
    """One plain-English line per feature, for the live design's step list."""
    tree = parse_tree(tree)
    features = tree.features
    several = sum(feature.op in SOLID_OPS for feature in features) > 1
    by_id = {feature.id: feature for feature in features if feature.id}

    def on(feature, at):
        of = f" of {feature.target}" if several else ""
        spot = f" at {point(at)}" if at is not None else ", centred"
        return f"on the {feature.face} face{of}{spot}"

    def of_target(feature):
        return f" of {feature.target}" if several else ""

    lines = []
    for feature in features:
        op = feature.op
        if op in SOLID_OPS:
            text = shape_words(feature)
            if feature.material:
                text += f", {feature.material}"
            if several and feature.id:
                text = f"{feature.id}: {text}"
        elif op == "hole":
            size = f"Ø{number(feature.diameter)} mm"
            blind = feature.depth != "through"
            if feature.cb_diameter is not None:
                reach = f"{number(feature.depth)} mm deep" if blind else "through"
                text = (
                    f"Counterbored hole {size} ({reach}), Ø{number(feature.cb_diameter)} × "
                    f"{number(feature.cb_depth)} mm counterbore, {on(feature, feature.at)}"
                )
            elif blind:
                text = (
                    f"Blind hole {size}, {number(feature.depth)} mm deep, "
                    f"{on(feature, feature.at)}"
                )
            else:
                text = f"Through hole {size} {on(feature, feature.at)}"
        elif op == "slot":
            blind = feature.depth != "through"
            text = ("Slot " if blind else "Through slot ") + (
                f"{number(feature.length)} × {number(feature.width)} mm"
            )
            if blind:
                text += f", {number(feature.depth)} mm deep"
            if feature.angle:
                text += f", turned {number(feature.angle)}°"
            text += ("," if blind or feature.angle else "") + f" {on(feature, feature.at)}"
        elif op in ("cut", "union"):
            what = tool_words(feature.tool) if feature.tool is not None else names(
                feature.bodies
            )
            text = (
                f"Cut {what} from {feature.target}"
                if op == "cut"
                else f"Join {what} to {feature.target}"
            )
        elif op == "fillet":
            text = (
                f"Round {EDGE_WORDS[feature.edges]}{of_target(feature)}, "
                f"{number(feature.radius)} mm radius"
            )
        elif op == "chamfer":
            text = (
                f"Chamfer {EDGE_WORDS[feature.edges]}{of_target(feature)} by "
                f"{number(feature.distance)} mm"
            )
        elif op == "shell":
            who = f" {feature.target}" if several else ""
            text = (
                f"Shell{who} to {number(feature.thickness)} mm walls, open at the "
                f"{feature.open}"
            )
        elif op == "text":
            verb, sense = ("Engrave", "deep") if feature.mode == "engrave" else ("Emboss", "high")
            text = (
                f"{verb} “{feature.text}” {on(feature, feature.at)}, "
                f"{number(feature.size)} mm tall, {number(feature.depth)} mm {sense}"
            )
        elif op == "pattern":
            source = by_id[feature.of]
            what = f"{NOUNS[source.op].removesuffix(' feature')} {feature.of}"
            if feature.kind == "polar":
                text = f"Repeat {what} {feature.count} times on a {number(feature.radius)} mm radius"
                if feature.angle != 360:
                    text += f" over {number(feature.angle)}°"
            else:
                (nx, ny), (dx, dy) = feature.count, feature.spacing
                if nx > 1 and ny > 1:
                    text = f"Repeat {what} in a {nx} × {ny} grid, {dims((dx, dy))} mm apart"
                elif ny > 1:
                    text = f"Repeat {what} {ny} times, {number(dy)} mm apart"
                elif nx > 1:
                    text = f"Repeat {what} {nx} times, {number(dx)} mm apart"
                else:
                    text = f"Keep a single {what}"
        else:
            text = f"Mirror {feature.target} across the {feature.plane} plane"
        lines.append(text)
    return lines


# --- today's live design parts -----------------------------------------------------------

def part_id(name, shape, used):
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "")).strip("-")[:MAX_ID] or (
        "bracket" if shape == "bracket" else shape
    )
    ident, n = base, 2
    while ident in used:
        suffix = f"-{n}"
        ident, n = base[: MAX_ID - len(suffix)] + suffix, n + 1
    used.add(ident)
    return ident


def from_parts(parts, export=("glb", "stl")):
    """An equivalent tree for LiveDesigns parts (boxes, L brackets, open enclosures).

    Each part becomes one separate solid: same size, wall thickness, scale, rotation and
    material. A part spans from its position (its corner), so ``at`` becomes the transformed
    centre of the part; the default export matches today's build (GLB and STL).
    """
    features, used = [], set()
    for part in parts:
        if hasattr(part, "model_dump"):
            part = part.model_dump()
        shape = part.get("shape", "box")
        if shape not in SHAPE_OPS:
            raise FeatureTreeError([f"A live design part can't be a {quoted_ref(shape)}."])
        size = [float(part.get(key, default)) for key, default in
                (("width", 80), ("depth", 60), ("height", 30))]
        placement = {
            "scale": [float(value) for value in part.get("scale", (1, 1, 1))],
            "rotation": [float(value) for value in part.get("rotation", (0, 0, 0))],
            "position": [float(value) for value in part.get("position", (0, 0, 0))],
        }
        centre = transform([value / 2 for value in size], placement)
        feature = {
            "id": part_id(part.get("name"), shape, used),
            "op": SHAPE_OPS[shape],
            "size": size,
            "at": [round(value, 6) + 0.0 for value in centre],
            "rotate": placement["rotation"],
            "scale": placement["scale"],
            "material": part.get("material"),
        }
        if shape != "box":
            feature["thickness"] = float(part.get("thickness", 3))
        features.append(feature)
    return parse_tree({"units": "mm", "features": features, "export": list(export)})
