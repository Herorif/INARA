"""Live CAD co-design: one in-memory draft per owner, changed part by part, built on approval.

The draft lives in core memory only (it survives renderer reloads, not core restarts) and is
tied to the project that was current when it started. Nothing is written until the owner
builds; a build is an ordinary offline CAD job (``generate_cad``) in that project. The
owner's words are conversation content: this module never logs them. See docs/LIVE_DESIGN.md.
"""

import copy
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

from services.cad import BuildRequest, Recipe, SceneObject
from services.tools import ServiceError, ToolSpec
from services.log import get_logger

logger = get_logger(__name__)

MAX_PARTS = 8
MAX_STEPS = 40  # The snapshot keeps the newest steps; only the newest is ever undone.
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


class ChangeDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: StrictStr = Field(min_length=1, max_length=200)
    add: list[LivePart] = Field(default_factory=list, max_length=MAX_PARTS)
    update: list[PartEdit] = Field(default_factory=list, max_length=16)
    remove: list[Annotated[StrictInt, Field(ge=0, le=MAX_PARTS - 1)]] = Field(
        default_factory=list, max_length=MAX_PARTS
    )
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
    priors: dict = field(default_factory=dict)  # step n -> recipe before that step
    job: dict | None = None
    built_through: int = 0  # Steps up to here were built; they are never undone.
    version: int = 0  # Increments with every recipe change.
    next_n: int = 1
    updated: float = field(default_factory=time.time)


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

    def __init__(self, sio, sessions, cad, dispatcher, context, authorize=None):
        self.sio, self.sessions, self.cad, self.dispatcher = sio, sessions, cad, dispatcher
        self.context, self.authorize = context, authorize
        self.designs = {}
        self.reviewed = {}  # owner -> (design id, version) shown in the build approval
        # callable(owner, active) told when an owner's design starts or ends; the talking
        # overlay uses it to offer "Open JARVIS" while JARVIS designs (application.py).
        self.observer = None
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
                "part spans from its position), rotations are degrees. Parts can only be boxes, "
                "L brackets ('bracket') or open enclosures ('enclosure'); at most eight parts; "
                "materials cyan, titanium, amber or ceramic. Give each part a short name. It "
                "saves nothing and never asks for approval. Holes, fillets, rounded edges, "
                "threads, cut-outs, text and curves can't be made yet: say so plainly. "
                "Afterwards, say in one or two short sentences what was placed and ask if the "
                "owner wants changes.",
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
                "parts. Put holes, fillets, rounded edges, threads, cut-outs, text, curves and "
                "anything else the offline engine can't make into unsupported with a short "
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
                "Build the live design as STL and GLB files in the owner's project, as a new "
                "revision. Call it only when the owner asks to build it. The owner approves the "
                "build on screen first.",
                NoArguments,
                self.tool_build,
                permission="generate_cad",
                review=self.review_build,
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
                None if index == 0 else scene(args.name, design.recipe["objects"][:index])
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
        await self.emit(owner)
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
        if not (args.add or args.update or args.remove or args.unsupported):
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
        recorded = []
        if changed or added_at or removed:
            prior = design.recipe
            design.recipe = recipe
            self.record(
                design,
                {
                    "who": "owner",
                    "kind": "change",
                    "title": words,
                    "detail": change_summary(
                        old,
                        parts,
                        [(old[kept[after]], parts[after]) for after in changed],
                        removed,
                        [parts[after] for after in added_at],
                    ),
                    "added": added_at,
                    "changed": changed,
                    "removed": removed,
                    "before": {str(after): copy.deepcopy(old[kept[after]]) for after in changed},
                },
                prior,
            )
            recorded.append("change")
        if args.unsupported:
            reasons = list(dict.fromkeys(item.reason for item in args.unsupported))
            self.record(
                design,
                {
                    "who": "owner",
                    "kind": "unsupported",
                    "title": words,
                    "detail": clip("not possible yet: " + "; ".join(reasons), 160),
                    "added": [],
                    "changed": [],
                    "removed": [],
                    "before": {},
                },
                None,
            )
            recorded.append("unsupported")
        if not recorded:
            raise ServiceError("design_unchanged", "That leaves the design as it was.")
        await self.emit(owner)
        return self.summary(
            design,
            steps=[step["detail"] for step in design.steps[-len(recorded):]],
            unsupported=[item.model_dump() for item in args.unsupported],
        )

    async def tool_undo(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        step = self.undo(self.current(owner))
        await self.emit(owner)
        return self.summary(self.designs[owner], undone=step["title"])

    def review_build(self, args, context):
        self.allowed(context)
        owner = context["principal"]
        design = self.current(owner)
        self.buildable(design)
        self.reviewed[owner] = (design.id, design.version)
        parts = len(design.recipe["objects"])
        noun = "part" if parts == 1 else "parts"
        return {
            "design_id": design.id,
            "design_name": design.name,
            "parts": parts,
            "exports": ["stl", "glb"],
            "project": design.project.name,
            "summary": f"Build “{design.name}”? {parts} {noun} · STL and GLB on this PC",
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
        design.recipe = design.priors.pop(step["n"])
        design.steps.remove(step)
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

    async def build(self, design):
        """Submit the draft through generate_cad, the studio's cad_submit service path.

        The caller already holds the owner's consent (the approved build_live_design call, or
        the panel's Build click), so the nested dispatch answers its own approval request.
        Denial, authentication rechecks and the heavy-resource rules still apply.
        """
        self.buildable(design)
        owner = design.owner
        request = BuildRequest.model_validate({**design.recipe, "request_id": uuid.uuid4()})
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
                owner,
                "generate_cad",
                request.model_dump(mode="json"),
                {"principal": owner, "project_path": design.project},
                consent,
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
        return self.snapshot(context["principal"])

    async def rpc_undo(self, sid, data, context):
        args = UndoRequest.model_validate(data)
        owner = context["principal"]
        self.undo(self.referenced(owner, args.design_id), args.step)
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
