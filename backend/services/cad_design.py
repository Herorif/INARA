"""Live CAD co-design: one in-memory draft per owner, changed part by part, built on approval.

The draft lives in core memory only (it survives renderer reloads, not core restarts) and is
tied to the project that was current when it started. Nothing is written until the owner
builds; a build is an ordinary offline CAD job (``generate_cad``) in that project. The
owner's words are conversation content: this module never logs them. See docs/LIVE_DESIGN.md.

With the CAD kernel (services/cad_kernel.py, ``.venv-cad``) a draft is also a feature tree:
its parts (``cad_features.from_parts``) followed by feature steps (holes, slots, fillets,
chamfers, cuts, shells, text, patterns, mirrors). Every change is checked with
``parse_tree`` and then built as a draft GLB by the kernel (debounced, one build at a time per
design); a step the tree or the kernel refuses becomes a plain "not possible" row and the
draft stays as it was. The ``cad_design`` snapshot then carries ``preview`` (state, the draft
GLB's ``cad_artifact`` reference, facts, warnings). Without the kernel the box engine path is
unchanged and feature steps are refused. Trees, text and paths are never logged.
"""

import asyncio
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from typing import Annotated, Literal

from services.cad import TREE_CONTEXT, BuildRequest, Recipe, SceneObject
from services.cad_features import (
    MAX_FEATURES,
    FeatureTreeError,
    canonical,
    describe,
    from_parts,
    parse_tree,
    part_id,
)
from services.cad_kernel import SETUP_HINT, CadKernelError
from services.creative_jobs import read_export
from services.tools import ServiceError, ToolSpec
from services.log import get_logger

logger = get_logger(__name__)

MAX_PARTS = 8
MAX_STEPS = 40  # The snapshot keeps the newest steps; only the newest is ever undone.
FEATURE_OPS = ("hole", "slot", "fillet", "chamfer", "cut", "shell", "text", "pattern", "mirror")
DEBOUNCE = 0.15  # s of quiet before a draft build starts; rapid changes build once
DRAFT_WAIT = 8.0  # s a brain tool waits for its draft (a cold worker start takes 3-6 s)
STARTING = "Starting the CAD engine…"
# Kernel failures that belong to the newest step: that step is taken back. A missing engine
# or gaming mode is never the step's fault.
STEP_FAULTS = {"cad_tree_invalid", "cad_kernel_failed", "cad_kernel_timeout", "cad_kernel_crashed"}
EXPORTS = ["stl", "glb"]
KERNEL_EXPORTS = ["stl", "glb", "step"]
# The drafting tools share this permission key; server DEFAULT_SETTINGS sets it to False
# (no approval). Building uses the existing generate_cad permission.
LIVE_PERMISSION = "live_design"
SHAPE_WORDS = {"box": "box", "bracket": "L bracket", "enclosure": "open enclosure"}
FINISHED = {"failed", "cancelled", "interrupted"}


def clean_text(value):
    """Remove control characters, collapse whitespace and trim; non-strings pass through."""
    if not isinstance(value, str):
        return value
    value = "".join(" " if unicodedata.category(char) == "Cc" else char for char in value)
    return re.sub(r"\s+", " ", value).strip()


def number(value):
    return f"{round(float(value), 2):g}"


def clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def quoted(words):
    # 78 characters inside the quotes (ellipsis included) keeps the title within 80.
    return "“" + clip(words, 78) + "”"


def size(part):
    return " × ".join(number(part[key]) for key in ("width", "depth", "height"))


def part_detail(part):
    walls = f", {number(part['thickness'])} mm walls" if part["shape"] != "box" else ""
    return clip(f"{SHAPE_WORDS[part['shape']]} {size(part)} mm{walls}, {part['material']}", 160)


def transform(point, part):
    """Scale, then X/Y/Z rotation in degrees, then translation (creative/scene.py)."""
    x, y, z = (point[i] * part["scale"][i] for i in range(3))
    for axis, angle in enumerate(part["rotation"]):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        if axis == 0:
            y, z = c * y - s * z, s * y + c * z
        elif axis == 1:
            x, z = c * x + s * z, -s * x + c * z
        else:
            x, y = c * x - s * y, s * x + c * y
    return [v + offset for v, offset in zip((x, y, z), part["position"], strict=True)]


def bounds(parts):
    """Overall width, depth and height in mm of the placed parts."""
    corners = [
        transform((x, y, z), part)
        for part in parts
        for x in (0, part["width"])
        for y in (0, part["depth"])
        for z in (0, part["height"])
    ]
    return [round(max(c[i] for c in corners) - min(c[i] for c in corners), 1) for i in range(3)]


class LivePart(SceneObject):
    """One part of the live design, with a short name."""

    name: StrictStr = Field(min_length=1, max_length=60)

    @field_validator("name", mode="before")
    @classmethod
    def cleaned_name(cls, value):
        return clean_text(value)


class PartFields(BaseModel):
    """Fields to change on an existing part; leave out the rest."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: StrictStr | None = Field(default=None, min_length=1, max_length=60)
    width: float | None = Field(default=None, strict=True, ge=1, le=1000)
    depth: float | None = Field(default=None, strict=True, ge=1, le=1000)
    height: float | None = Field(default=None, strict=True, ge=1, le=1000)
    thickness: float | None = Field(default=None, strict=True, ge=0.5, le=100)
    position: list[float] | None = Field(default=None, min_length=3, max_length=3)
    rotation: list[float] | None = Field(default=None, min_length=3, max_length=3)
    scale: list[float] | None = Field(default=None, min_length=3, max_length=3)
    material: Literal["cyan", "titanium", "amber", "ceramic"] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def cleaned_name(cls, value):
        return clean_text(value)

    @field_validator("position", "rotation", "scale", mode="before")
    @classmethod
    def valid_vectors(cls, value, info):
        return None if value is None else SceneObject.valid_vector(value, info)


class PartEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_index: StrictInt = Field(ge=0, le=MAX_PARTS - 1)
    fields: PartFields

    @model_validator(mode="after")
    def nonempty(self):
        if not self.fields.model_dump(exclude_none=True):
            raise ValueError("Provide at least one supported field")
        return self


class Unsupported(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: StrictStr = Field(min_length=1, max_length=60)
    reason: StrictStr = Field(min_length=1, max_length=100)

    @field_validator("feature", "reason", mode="before")
    @classmethod
    def cleaned(cls, value):
        return clean_text(value)


class StartDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=60)
    objects: list[LivePart] = Field(min_length=1, max_length=MAX_PARTS)

    @field_validator("name", mode="before")
    @classmethod
    def cleaned_name(cls, value):
        return clean_text(value)


class FeatureStep(BaseModel):
    """One feature-tree step; its other fields are checked with the whole tree (parse_tree)."""

    model_config = ConfigDict(extra="allow")
    op: Literal[FEATURE_OPS]  # type: ignore[valid-type]


class ChangeDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: StrictStr = Field(min_length=1, max_length=200)
    add: list[LivePart] = Field(default_factory=list, max_length=MAX_PARTS)
    update: list[PartEdit] = Field(default_factory=list, max_length=16)
    remove: list[Annotated[StrictInt, Field(ge=0, le=MAX_PARTS - 1)]] = Field(
        default_factory=list, max_length=MAX_PARTS
    )
    features: list[FeatureStep] = Field(default_factory=list, max_length=MAX_FEATURES)
    unsupported: list[Unsupported] = Field(default_factory=list, max_length=4)

    @field_validator("request", mode="before")
    @classmethod
    def cleaned_request(cls, value):
        return clean_text(value)

    @field_validator("remove")
    @classmethod
    def valid_removals(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Remove each part once")
        return value


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_id: uuid.UUID


class UndoRequest(DesignReference):
    step: StrictInt = Field(ge=1)


@dataclass
class Design:
    id: str
    owner: str
    project: Path
    name: str
    recipe: dict
    status: str = "draft"
    steps: list = field(default_factory=list)
    priors: dict = field(default_factory=dict)  # step n -> state() before that step
    job: dict | None = None
    built_through: int = 0  # Steps up to here were built; they are never undone.
    version: int = 0  # Increments with every recipe change.
    next_n: int = 1
    updated: float = field(default_factory=time.time)
    # CAD kernel only: feature steps after the parts (references resolved to part ids), the
    # draft preview the snapshot carries, and the draft build's bookkeeping.
    features: list = field(default_factory=list)
    preview: dict | None = None
    glb: Path | None = None  # the preview GLB in the kernel's temp folder (never sent)
    unverified: set = field(default_factory=set)  # steps no draft build has accepted yet
    rejected: dict = field(default_factory=dict)  # step n -> why the kernel refused it
    task: asyncio.Task | None = None
    due: float = 0.0


def state(design):
    return {"recipe": design.recipe, "features": design.features}


def restore(design, prior):
    design.recipe, design.features = prior["recipe"], prior["features"]


def part_ids(parts):
    """The feature-tree ids of the parts (as ``from_parts`` names them)."""
    used = set()
    return [part_id(part["name"], part["shape"], used) for part in parts]


def compose(parts, features):
    """The validated feature tree of parts plus feature steps; raises FeatureTreeError."""
    base = json.loads(canonical(from_parts(parts, export=("glb",))))
    return parse_tree({"units": "mm", "features": [*base["features"], *features],
                       "export": ["glb"]})


def resolve(feature, parts, ids):
    """A feature step with part names in target/bodies/of replaced by the parts' ids."""
    names = {clean_text(part["name"]).casefold(): ids[index] for index, part in enumerate(parts)}

    def ref(value):
        if isinstance(value, str) and value not in ids:
            return names.get(clean_text(value).casefold(), value)
        return value

    data = feature.model_dump()
    for key in ("target", "of"):
        if key in data:
            data[key] = ref(data[key])
    if isinstance(data.get("bodies"), list):
        data["bodies"] = [ref(value) for value in data["bodies"]]
    return data


def renamed(features, mapping):
    """Feature steps with references to renamed or moved parts following them."""
    if not mapping:
        return features
    result = []
    for feature in features:
        feature = copy.deepcopy(feature)
        for key in ("target", "of"):
            if isinstance(feature.get(key), str) and feature[key] in mapping:
                feature[key] = mapping[feature[key]]
        if isinstance(feature.get("bodies"), list):
            feature["bodies"] = [
                mapping.get(value, value) if isinstance(value, str) else value
                for value in feature["bodies"]
            ]
        result.append(feature)
    return result


def draft_token(design, digest):
    """The ``cad_artifact`` request_id of a draft GLB: stable for this design and tree."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis-live-draft:{design.id}:{digest}"))


def plain_facts(facts):
    def numbers(key):
        values = facts.get(key)
        if isinstance(values, list) and len(values) == 3:
            return [round(float(value), 2) for value in values]
        return None

    return {
        "volume_mm3": round(float(facts.get("volume") or 0), 2),
        "bbox_mm": numbers("bbox"),
        "min_mm": numbers("min"),
        "faces": int(facts.get("faces") or 0),
        "edges": int(facts.get("edges") or 0),
        "solids": int(facts.get("solids") or 0),
        "valid": bool(facts.get("valid")),
    }


def plain_warnings(warnings, tree):
    lines = describe(tree)
    result = []
    for item in warnings[:8]:
        code = item.get("code") if isinstance(item, dict) else None
        index = item.get("index") if isinstance(item, dict) else None
        line = lines[index] if isinstance(index, int) and 0 <= index < len(lines) else None
        if code == "no_effect" and line:
            message = f"{line} doesn't change the part."
        elif code == "invalid_solid":
            message = "The result isn't a valid solid. Check it before printing it."
        else:
            message = "The CAD engine noted a problem with this design."
        result.append({
            "code": str(code or "warning")[:40],
            "index": index if line else None,
            "message": clip(message, 200),
        })
    return result


def scene(name, parts):
    try:
        return Recipe.model_validate(
            {"name": name, "shape": "scene", "objects": parts, "engine": "offline"}
        ).model_dump(mode="json")
    except ValidationError as exc:
        raise ServiceError("design_invalid", "Those parts don't make a valid design.") from exc


def first_error(exc):
    message = exc.errors()[0].get("msg", "") if exc.errors() else ""
    return message.removeprefix("Value error, ") or "unsupported values"


def change_summary(old, new, edited, removed, added):
    segments = []
    labels = {"width": "wide", "depth": "deep", "height": "tall", "thickness": "walls"}
    for before, after in edited:
        changes = []
        if before["name"] != after["name"]:
            changes.append(f"was {before['name']}")
        for key, label in labels.items():
            if before[key] != after[key]:
                unit = " mm walls" if key == "thickness" else f" mm {label}"
                changes.append(f"{number(before[key])} → {number(after[key])}{unit}")
        if before["position"] != after["position"]:
            changes.append("moved to " + ", ".join(map(number, after["position"])) + " mm")
        if before["rotation"] != after["rotation"]:
            changes.append("rotated to " + ", ".join(number(v) + "°" for v in after["rotation"]))
        if before["scale"] != after["scale"]:
            changes.append("scaled " + " × ".join(map(number, after["scale"])))
        if before["material"] != after["material"]:
            changes.append(f"{before['material']} → {after['material']}")
        segments.append(f"{after['name']} " + ", ".join(changes))
    segments += [f"+ {part['name']} {size(part)} mm, {part['material']}" for part in added]
    segments += [f"− {part['name']}" for part in removed]
    return clip(" · ".join(segments), 160)


class LiveDesigns:
    """The owner's live design, its brain tools, renderer RPCs and ``cad_design`` events."""

    def __init__(self, sio, sessions, cad, dispatcher, context, authorize=None, kernel=None):
        self.sio, self.sessions, self.cad, self.dispatcher = sio, sessions, cad, dispatcher
        self.context, self.authorize = context, authorize
        self.designs = {}
        self.reviewed = {}  # owner -> (design id, version) shown in the build approval
        # callable(owner, active) told when an owner's design starts or ends; the talking
        # overlay uses it to offer "Open JARVIS" while JARVIS designs (application.py).
        self.observer = None
        # The CAD kernel (services/cad_kernel.py), or None for the box engine only. The CAD
        # service builds feature-tree jobs with it ("generate_cad_tree").
        self.kernel = kernel
        if kernel is not None:
            cad.kernel = kernel
        self.debounce, self.wait = DEBOUNCE, DRAFT_WAIT
        self.tasks = set()
        artifact = cad.artifact

        def draft_or_revision(owner, project, args):
            # The draft GLB is fetched like a revision's export (cad_artifact), by its token.
            found = self.draft_artifact(owner, args)
            return found if found is not None else artifact(owner, project, args)

        cad.artifact = draft_or_revision
        previous = cad.on_update

        async def on_update(owner, job):
            # The studio's cad_job delivery is unchanged; the live design mirrors its own job.
            if previous:
                await previous(owner, job)
            try:
                await self.follow(owner, job)
            except Exception:
                logger.warning("Live design job update could not be delivered", exc_info=True)

        cad.on_update = on_update
        for name in ("get", "undo", "build", "end"):
            sio.on(f"cad_design_{name}", handler=self.guard(getattr(self, f"rpc_{name}")))

    # --- tools -----------------------------------------------------------------------

    def register(self, dispatcher):
        dispatcher.register(
            ToolSpec(
                "start_live_design",
                "Start the owner's live design in the workspace with these parts, replacing any "
                "current one. Use it for any request to design, model or make a physical part or "
                "3D model. Sizes and positions are millimetres (width X, depth Y, height Z; each "
                "part spans from its position), rotations are degrees. Parts are boxes, L "
                "brackets ('bracket') or open enclosures ('enclosure'); at most eight parts; "
                "materials cyan, titanium, amber or ceramic. Give each part a short name: "
                "features target parts by name. Add holes, slots, fillets, chamfers, cut-outs, "
                "shells, text, patterns and mirrors afterwards with change_live_design. Threads "
                "and free-form curves can't be made: say so plainly. It saves nothing and never "
                "asks for approval. Afterwards, say in one or two short sentences what was "
                "placed and ask if the owner wants changes.",
                StartDesign,
                self.tool_start,
                permission=LIVE_PERMISSION,
            )
        )
        dispatcher.register(
            ToolSpec(
                "change_live_design",
                "Apply a change the owner asks for to the live design at once. Use it for every "
                "change they ask for, passing their words as request. Part indices start at 0 "
                "and refer to the design before this change. add places new parts, update edits "
                "fields of existing parts, remove deletes parts; the design keeps one to eight "
                "parts. features adds feature steps in order, after the parts; all sizes are "
                "mm and a design holds at most 40 features, parts included. Ops: hole {target, "
                "face, at [u, v], diameter, depth 'through' or mm, optional cb_diameter and "
                "cb_depth for a counterbore}; slot {target, face, at, length, width, depth, "
                "angle}; fillet {target, edges, radius}; chamfer {target, edges, distance}; cut "
                "{target, tool: {op box, size [x, y, z]} or {op cylinder, diameter, height} or "
                "{op sphere, diameter}, each with at [x, y, z] its centre} or {target, bodies: "
                "part names}; shell {target, thickness, open: the open face}; text {target, "
                "face, text (at most 40 characters), size, depth, mode engrave or emboss, "
                "optional at}; pattern {of: the id of an earlier hole, slot, text or cut, kind "
                "linear with count [nx, ny] and spacing [dx, dy], or polar with count, radius "
                "and optional angle}; mirror {target, plane XY, YZ or XZ}. target is a part's "
                "name. Faces: top, bottom, front (-Y), back (+Y), left (-X), right (+X); at "
                "[u, v] is mm from the face's corner with the smallest coordinates (top and "
                "bottom use X, Y; front and back X, Z; left and right Y, Z). Edges: all, "
                "vertical, top or bottom. Give a feature an id when a pattern repeats it. Put "
                "shells before fillets and chamfers. A step that can't be made comes back in "
                "not_possible with a plain reason: tell the owner. Put threads, free-form "
                "curves and anything else that can't be made into unsupported with a short "
                "reason, and tell the owner plainly it can't be done yet. Saves nothing and "
                "never asks for approval. Afterwards, say briefly what changed.",
                ChangeDesign,
                self.tool_change,
                permission=LIVE_PERMISSION,
            )
        )
        dispatcher.register(
            ToolSpec(
                "undo_live_design",
                "Undo the newest change to the live design when the owner asks to undo or go "
                "back. Never asks for approval.",
                NoArguments,
                self.tool_undo,
                permission=LIVE_PERMISSION,
            )
        )
        dispatcher.register(
            ToolSpec(
                "build_live_design",
                "Build the live design in the owner's project as a new revision: STL and GLB "
                "files, plus STEP when the CAD engine is installed. Call it only when the owner "
                "asks to build it. The owner approves the build on screen first.",
                NoArguments,
                self.tool_build,
                permission="generate_cad",
                review=self.review_build,
                long_running=True,
            )
        )

    def allowed(self, context):
        if self.authorize:
            self.authorize(context)

    def current(self, owner):
        design = self.designs.get(owner)
        if design is None:
            raise ServiceError("design_missing", "There's no live design. Start one first.")
        return design

    def summary(self, design, **extra):
        parts = design.recipe["objects"]
        overall = bounds(parts)
        noun = "part" if len(parts) == 1 else "parts"
        extent = " × ".join(map(number, overall))
        if design.preview is not None:
            # The kernel's view for the brain: feature lines, draft state, facts, warnings.
            extra = {
                "features": self.feature_lines(design),
                "preview": {
                    key: copy.deepcopy(design.preview[key])
                    for key in ("state", "message", "facts")
                }
                | {"warnings": [item["message"] for item in design.preview["warnings"]]},
                **extra,
            }
        return {
            "design_id": design.id,
            "name": design.name,
            "status": design.status,
            "parts": [
                {
                    "index": index,
                    "name": part["name"],
                    "shape": part["shape"],
                    "size_mm": [part["width"], part["depth"], part["height"]],
                    "position_mm": part["position"],
                    "material": part["material"],
                }
                for index, part in enumerate(parts)
            ],
            "bounds_mm": overall,
            **extra,
            "summary": clip(
                f"{len(parts)} {noun}: "
                + ", ".join(part["name"] for part in parts)
                + f". Overall {extent} mm.",
                400,
            ),
        }

    def feature_lines(self, design):
        if not design.features:
            return []
        try:
            return describe(compose(design.recipe["objects"], design.features))[
                -len(design.features):
            ]
        except FeatureTreeError:
            return []

    async def tool_start(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        parts = [part.model_dump() for part in args.objects]
        design = Design(
            id=str(uuid.uuid4()),
            owner=owner,
            project=Path(context["project_path"]).resolve(),
            name=args.name,
            recipe=scene(args.name, parts),
        )
        for index, part in enumerate(design.recipe["objects"]):
            prior = (
                None
                if index == 0
                else {"recipe": scene(args.name, design.recipe["objects"][:index]),
                      "features": []}
            )
            self.record(
                design,
                {
                    "who": "jarvis",
                    "kind": "add",
                    "title": clip(f"+ {part['name']}", 80),
                    "detail": part_detail(part),
                    "added": [index],
                    "changed": [],
                    "removed": [],
                    "before": {},
                },
                prior,
            )
        self.designs[owner] = design
        self.notify(owner, True)
        drafting = self.request_draft(design)
        await self.emit(owner)
        if drafting:
            await self.settle(design)
        return self.summary(design)

    async def tool_change(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        design = self.current(owner)
        old = design.recipe["objects"]
        count = len(old)
        listing = ", ".join(f"{index} {part['name']}" for index, part in enumerate(old))
        indices = [edit.object_index for edit in args.update] + list(args.remove)
        for index in indices:
            if index >= count:
                raise ServiceError(
                    "design_index",
                    f"There's no part at index {index}. Current parts: {listing}.",
                )
        if set(args.remove) & {edit.object_index for edit in args.update}:
            raise ServiceError("design_index", "A part can't be changed and removed at once.")
        if not (args.add or args.update or args.remove or args.features or args.unsupported):
            raise ServiceError("design_unchanged", "Describe at least one change.")
        work = copy.deepcopy(old)
        for edit in args.update:
            target = work[edit.object_index]
            try:
                work[edit.object_index] = SceneObject.model_validate(
                    {**target, **edit.fields.model_dump(exclude_none=True)}
                ).model_dump()
            except ValidationError as exc:
                raise ServiceError(
                    "design_invalid",
                    f"Part {edit.object_index} ({target['name']}) can't take that change: "
                    f"{first_error(exc)}.",
                ) from exc
        kept = [index for index in range(count) if index not in args.remove]
        added = [part.model_dump() for part in args.add]
        parts = [work[index] for index in kept] + added
        if not parts:
            raise ServiceError("design_empty", "A live design needs at least one part.")
        if len(parts) > MAX_PARTS:
            raise ServiceError("design_full", "A live design holds at most eight parts.")
        recipe = scene(design.name, parts)
        parts = recipe["objects"]
        changed = [
            after for after, index in enumerate(kept) if parts[after] != old[index]
        ]
        added_at = list(range(len(kept), len(parts)))
        removed = [copy.deepcopy(old[index]) for index in sorted(args.remove)]
        words = quoted(args.request)
        first = design.next_n
        kernel = self.kernel_on()
        reshaped = bool(changed or added_at or removed)
        featured = bool(args.features) and kernel
        features, not_possible, lines = design.features, [], []
        if design.features and reshaped:
            before, after = part_ids(old), part_ids(parts)
            features = renamed(design.features, {
                before[index]: after[position]
                for position, index in enumerate(kept)
                if before[index] != after[position]
            })
        if featured:
            ids = part_ids(parts)
            features = [*features, *(resolve(item, parts, ids) for item in args.features)]
        apply = reshaped or featured
        if apply and (kernel or features):
            try:
                tree = compose(parts, features)
            except FeatureTreeError as exc:
                apply = False
                not_possible.append(str(exc))
            else:
                if featured:
                    lines = describe(tree)[-len(args.features):]
        if apply:
            prior = state(design)
            design.recipe, design.features = recipe, features
            details = []
            if reshaped:
                details.append(change_summary(
                    old,
                    parts,
                    [(old[kept[after]], parts[after]) for after in changed],
                    removed,
                    [parts[after] for after in added_at],
                ))
            details += lines
            self.record(
                design,
                {
                    "who": "owner",
                    "kind": "change",
                    "title": words,
                    "detail": clip(" · ".join(details), 160),
                    "added": added_at,
                    "changed": changed,
                    "removed": removed,
                    "before": {str(after): copy.deepcopy(old[kept[after]]) for after in changed},
                },
                prior,
            )
            step = design.steps[-1]
            if kernel:
                design.unverified.add(step["n"])
        refusals = [f"not possible: {message}" for message in not_possible]
        if args.features and not kernel:
            refusals.append(f"not possible yet: {SETUP_HINT}")
            not_possible.append(SETUP_HINT)
        for detail in refusals:
            self.row(design, "owner", words, detail)
        if args.unsupported:
            reasons = list(dict.fromkeys(item.reason for item in args.unsupported))
            self.row(design, "owner", words, "not possible yet: " + "; ".join(reasons))
        if design.next_n == first:
            raise ServiceError("design_unchanged", "That leaves the design as it was.")
        drafting = apply and self.request_draft(design)
        await self.emit(owner)
        if drafting:
            await self.settle(design)
            refused = design.rejected.pop(step["n"], None)
            if refused is not None:
                not_possible.append(refused)
        extra = {"not_possible": not_possible} if not_possible else {}
        return self.summary(
            design,
            steps=[item["detail"] for item in design.steps if item["n"] >= first],
            unsupported=[item.model_dump() for item in args.unsupported],
            **extra,
        )

    def row(self, design, who, title, detail):
        """A "not possible" row: recorded, never undoable, the design unchanged."""
        self.record(
            design,
            {
                "who": who,
                "kind": "unsupported",
                "title": title,
                "detail": clip(detail, 160),
                "added": [],
                "changed": [],
                "removed": [],
                "before": {},
            },
            None,
        )

    async def tool_undo(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        design = self.current(owner)
        step = self.undo(design)
        drafting = self.request_draft(design)
        await self.emit(owner)
        if drafting:
            await self.settle(design)
        return self.summary(self.designs[owner], undone=step["title"])

    def review_build(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        design = self.current(owner)
        self.buildable(design)
        self.reviewed[owner] = (design.id, design.version)
        parts = len(design.recipe["objects"])
        noun = "part" if parts == 1 else "parts"
        kernel = self.kernel_on()
        return {
            "design_id": design.id,
            "design_name": design.name,
            "parts": parts,
            "exports": list(KERNEL_EXPORTS if kernel else EXPORTS),
            "project": design.project.name,
            "summary": f"Build “{design.name}”? {parts} {noun} · "
            + ("STL, GLB and STEP" if kernel else "STL and GLB")
            + " on this PC",
        }

    async def tool_build(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        design = self.current(owner)
        reviewed = self.reviewed.pop(owner, None)
        if reviewed is not None and reviewed != (design.id, design.version):
            raise ServiceError(
                "design_changed",
                "The design changed while waiting for approval. Ask again to build it.",
            )
        return await self.build(design)

    # --- model -----------------------------------------------------------------------

    def record(self, design, step, prior):
        step = {"n": design.next_n, **step}
        design.next_n += 1
        design.steps.append(step)
        if step["kind"] != "unsupported":
            design.priors[step["n"]] = prior
            design.version += 1
            if design.status != "draft":
                # A change after (or during) a build makes a new draft; the job keeps running.
                design.status = "draft"
        while len(design.steps) > MAX_STEPS:
            design.priors.pop(design.steps.pop(0)["n"], None)
        design.updated = time.time()

    def latest_undoable(self, design):
        if design.status != "draft":
            return None
        for step in reversed(design.steps):
            if step["kind"] == "unsupported":
                continue
            if step["n"] > design.built_through and design.priors.get(step["n"]) is not None:
                return step
            return None
        return None

    def undo(self, design, n=None):
        if design.status != "draft":
            raise ServiceError("design_undo", "There's nothing to undo since the last build.")
        step = self.latest_undoable(design)
        if step is None:
            raise ServiceError("design_undo", "There's nothing to undo.")
        if n is not None and step["n"] != n:
            raise ServiceError("design_stale", "That change is no longer the latest.")
        restore(design, design.priors.pop(step["n"]))
        design.steps.remove(step)
        design.unverified.discard(step["n"])
        design.version += 1
        design.updated = time.time()
        return step

    def buildable(self, design):
        if design.status == "building":
            raise ServiceError("design_building", "This design is already building.")
        if design.status == "saved":
            raise ServiceError(
                "design_saved", "This version is already saved. Change it to build again."
            )
        if not design.project.is_dir():
            raise ServiceError("design_project", "The design's project is no longer available.")
        if design.features and not self.kernel_on():
            raise ServiceError("cad_kernel_unavailable", SETUP_HINT)

    async def build(self, design):
        """Submit the draft through generate_cad, the studio's cad_submit service path. With
        the CAD kernel installed the feature tree goes along in the dispatch context and the
        job builds on the kernel (GLB, STL and STEP).

        The caller already holds the owner's consent (the approved build_live_design call, or
        the panel's Build click), so the nested dispatch answers its own approval request.
        Denial, authentication rechecks and the heavy-resource rules still apply.
        """
        self.buildable(design)
        owner = design.owner
        request = BuildRequest.model_validate({**design.recipe, "request_id": uuid.uuid4()})
        context = {"principal": owner, "project_path": design.project}
        if self.kernel_on():
            try:
                tree = compose(design.recipe["objects"], design.features)
            except FeatureTreeError as exc:
                raise ServiceError("design_invalid", str(exc)) from None
            context[TREE_CONTEXT] = json.loads(canonical(tree))
        saved = design.status, design.job, design.built_through
        design.status = "building"
        design.built_through = design.steps[-1]["n"] if design.steps else 0
        design.job = {
            "request_id": str(request.request_id),
            "state": "queued",
            "phase": "queued",
            "error": None,
        }

        async def consent(payload):
            self.dispatcher.resolve(owner, payload["id"], True)

        try:
            job = await self.dispatcher.dispatch(
                owner, "generate_cad", request.model_dump(mode="json"), context, consent
            )
        except BaseException:
            if design.job and design.job["request_id"] == str(request.request_id):
                design.status, design.job, design.built_through = saved
            raise
        self.mirror(design, job)
        await self.emit(owner)
        return {
            "design_id": design.id,
            "status": design.status,
            "job": copy.deepcopy(design.job),
            "message": "Building now. The files save to the project when the build finishes.",
        }

    # --- draft builds on the CAD kernel ----------------------------------------------

    def kernel_on(self):
        return self.kernel is not None and self.kernel.available()

    def paused(self):
        governor = getattr(self.cad, "governor", None)
        return governor is not None and (
            bool(governor.fault) or governor.state in ("gaming", "resident")
        )

    def set_preview(self, design, **fields):
        preview = design.preview or {
            "engine": "kernel", "state": "building", "message": None, "current": False,
            "glb": None, "facts": None, "warnings": [], "seconds": None, "cached": False,
        }
        design.preview = {**preview, **fields}

    def request_draft(self, design):
        """Ask for a draft GLB of the design as it is now (debounced). False when the kernel
        isn't installed and the design has no features: the box engine path, untouched."""
        if self.kernel is None or (design.preview is None and not self.kernel_on()):
            return False
        if self.paused():
            self.set_preview(design, state="paused", message=None, current=False)
            return False
        if not self.kernel.available():
            self.set_preview(design, state="unavailable", message=self.kernel.reason,
                             current=False)
            return False
        loop = asyncio.get_running_loop()
        design.due = loop.time() + self.debounce
        starting = not self.kernel.running()
        self.set_preview(design, state="starting" if starting else "building",
                         message=STARTING if starting else None, current=False)
        if design.task is None or design.task.done():
            task = loop.create_task(self.draft_loop(design), name="live-design-draft")
            design.task = task
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return True

    async def settle(self, design):
        """Wait (at most ``self.wait`` s) for the draft builds the design has asked for."""
        task = design.task
        if task is not None and not task.done():
            await asyncio.wait({task}, timeout=self.wait)

    async def draft_loop(self, design):
        loop = asyncio.get_running_loop()
        try:
            while self.designs.get(design.owner) is design:
                delay = design.due - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                    continue
                version = design.version
                await self.draft_once(design, version)
                if design.version == version and design.due <= loop.time():
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Live design draft build stopped (%s)", type(exc).__name__)
        finally:
            if design.task is asyncio.current_task():
                design.task = None

    async def draft_once(self, design, version):
        owner = design.owner
        if self.paused():
            self.set_preview(design, state="paused", message=None, current=False)
            await self.emit(owner)
            return
        try:
            tree = compose(design.recipe["objects"], design.features)
        except FeatureTreeError as exc:
            self.set_preview(design, state="failed", message=str(exc), current=False)
            await self.emit(owner)
            return
        if not self.kernel.running() and design.preview["state"] != "starting":
            self.set_preview(design, state="starting", message=STARTING, current=False)
            await self.emit(owner)
        try:
            result = await self.kernel.build(tree, quality="draft")
        except CadKernelError as exc:
            if self.designs.get(owner) is not design or design.version != version:
                return  # superseded: the newer draft decides
            if self.paused():
                self.set_preview(design, state="paused", message=None, current=False)
            elif exc.code == "cad_kernel_unavailable":
                self.set_preview(design, state="unavailable", message=str(exc), current=False)
            else:
                step = self.latest_undoable(design)
                if exc.code in STEP_FAULTS and step is not None and step["n"] in design.unverified:
                    self.reject(design, step, str(exc))
                    design.due = 0.0  # build the restored draft at once (usually cached)
                    self.set_preview(design, state="building", message=None, current=False)
                else:
                    self.set_preview(design, state="failed", message=str(exc), current=False)
            await self.emit(owner)
            return
        if self.designs.get(owner) is not design or design.version != version:
            return
        design.unverified.clear()
        glb = Path(result["files"]["glb"])
        raw = glb.read_bytes()
        design.glb = glb
        self.set_preview(
            design,
            state="ready",
            message=None,
            current=True,
            glb={
                "request_id": draft_token(design, result["hash"]),
                "format": "glb",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            facts=plain_facts(result.get("facts") or {}),
            warnings=plain_warnings(result.get("warnings") or [], tree),
            seconds=result.get("seconds"),
            cached=bool(result.get("cached")),
        )
        await self.emit(owner)

    def reject(self, design, step, message):
        """Take back a step the kernel couldn't build; it becomes a "not possible" row."""
        restore(design, design.priors.pop(step["n"]))
        design.steps.remove(step)
        design.unverified.discard(step["n"])
        design.rejected[step["n"]] = message
        design.version += 1
        self.row(design, step["who"], step["title"], f"not possible: {message}")

    def draft_artifact(self, owner, args):
        """The draft GLB for ``cad_artifact`` when ``args.request_id`` is its token."""
        design = self.designs.get(owner)
        glb = (design.preview or {}).get("glb") if design is not None else None
        if not glb or str(args.request_id) != glb["request_id"]:
            return None
        if args.format != "glb":
            raise ServiceError("artifact_missing", "A draft preview has only a GLB.")
        if design.glb is None:
            raise ServiceError("artifact_missing", "The draft preview is no longer available.")
        raw = read_export(design.glb, {"bytes": glb["bytes"], "sha256": glb["sha256"]})
        return {
            "format": "glb",
            "filename": f"jarvis-draft-{glb['request_id'][:8]}.glb",
            "data": base64.b64encode(raw).decode(),
            "bytes": glb["bytes"],
            "sha256": glb["sha256"],
        }

    def resume(self, design):
        """After gaming mode: a paused draft builds again when the owner looks at it."""
        if design.preview is not None and design.preview["state"] == "paused":
            self.request_draft(design)

    def mirror(self, design, job):
        if not design.job or job.get("request_id") != design.job["request_id"]:
            return False
        design.job = {
            "request_id": design.job["request_id"],
            "state": str(job.get("state", design.job["state"])),
            "phase": str(job.get("phase", design.job["phase"])),
            "error": job.get("error") if isinstance(job.get("error"), str) else None,
        }
        if design.status == "building":
            if design.job["state"] == "succeeded":
                design.status = "saved"
            elif design.job["state"] in FINISHED:
                design.status = "failed"
        design.updated = time.time()
        return True

    async def follow(self, owner, job):
        design = self.designs.get(owner)
        if design is not None and isinstance(job, dict) and self.mirror(design, job):
            await self.emit(owner)

    def notify(self, owner, active):
        observer = self.observer
        if observer is None:
            return
        try:
            observer(owner, active)
        except Exception:
            logger.warning("Live design observer could not be told", exc_info=True)

    def snapshot(self, owner):
        design = self.designs.get(owner)
        if design is None:
            return {"design": None}
        undoable = self.latest_undoable(design)
        return {
            "design": {
                "id": design.id,
                "project": design.project.name,
                "name": design.name,
                "status": design.status,
                "recipe": copy.deepcopy(design.recipe),
                "steps": [
                    {**copy.deepcopy(step), "undoable": step is undoable}
                    for step in design.steps
                ],
                "job": copy.deepcopy(design.job),
                "updated": design.updated,
                # CAD kernel only (absent on the box engine path): the draft preview.
                **({"preview": copy.deepcopy(design.preview)} if design.preview else {}),
            }
        }

    async def emit(self, owner):
        if not self.dispatcher.authenticated(owner):
            return
        payload = self.snapshot(owner)
        for sid in self.sessions.rooms(owner, "renderer"):
            try:
                await self.sio.emit("cad_design", payload, room=sid)
            except Exception:
                logger.warning("Live design update could not be delivered", exc_info=True)

    async def hydrate(self, sid, owner):
        """On renderer connect (or unlock): the snapshot, when a design exists."""
        if owner in self.designs and self.dispatcher.authenticated(owner):
            self.resume(self.designs[owner])
            await self.sio.emit("cad_design", self.snapshot(owner), room=sid)

    # --- renderer RPCs ---------------------------------------------------------------

    def guard(self, operation):
        async def handle(sid, data=None):
            try:
                context = self.context(sid)
                if not self.dispatcher.authenticated(context["principal"]):
                    raise ServiceError("authentication_required", "Authentication is required.")
                self.allowed(context)
                return {"ok": True, **await operation(sid, data, context)}
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {
                    "ok": False,
                    "code": "invalid_arguments",
                    "message": "Check the live design request.",
                }
            except Exception:
                logger.warning("Live design action failed", exc_info=True)
                return {
                    "ok": False,
                    "code": "design_failed",
                    "message": "The live design action could not complete.",
                }

        return handle

    def referenced(self, owner, design_id):
        design = self.current(owner)
        if design.id != str(design_id):
            raise ServiceError("design_stale", "That design is no longer open.")
        return design

    async def rpc_get(self, sid, data, context):
        design = self.designs.get(context["principal"])
        if design is not None:
            self.resume(design)
        return self.snapshot(context["principal"])

    async def rpc_undo(self, sid, data, context):
        args = UndoRequest.model_validate(data)
        owner = context["principal"]
        design = self.referenced(owner, args.design_id)
        self.undo(design, args.step)
        self.request_draft(design)  # the panel follows the cad_design events
        await self.emit(owner)
        return self.snapshot(owner)

    async def rpc_build(self, sid, data, context):
        # The panel's Build click is the owner's consent: no second approval prompt.
        args = DesignReference.model_validate(data)
        owner = context["principal"]
        await self.build(self.referenced(owner, args.design_id))
        return self.snapshot(owner)

    async def rpc_end(self, sid, data, context):
        # A running build continues and lands in the studio history.
        args = DesignReference.model_validate(data)
        owner = context["principal"]
        self.referenced(owner, args.design_id)
        self.designs.pop(owner, None)
        self.reviewed.pop(owner, None)
        self.notify(owner, False)
        await self.emit(owner)
        return self.snapshot(owner)
