"""Scoped durable CAD jobs. Geometry and exports live in an owned worker process."""

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Literal
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StrictInt,
    field_validator,
    model_validator,
)
from services.creative_jobs import CreativeJobService, ExportMetadata, JobRequest, read_export  # noqa: F401
from services.revisions import RevisionParent
from services.handoff_contracts import CreativeReference
from services.usage import metered_generate
from services.tools import ServiceError, ToolSpec
from services.log import get_logger

logger = get_logger(__name__)

KERNEL_EXPORTS = ("glb", "stl", "step")
EXPORT_LIMIT = 16_777_216  # ExportMetadata's bound
# Worker start (up to 90 s on a cold disk) plus the kernel's 120 s final build, with slack.
KERNEL_DEADLINE = 215
TREE_CONTEXT = "cad_tree"  # the dispatch-context key LiveDesigns puts a feature tree under


class SolidRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: StrictStr = Field(default="Untitled design", min_length=1, max_length=60)
    shape: Literal["box", "bracket", "enclosure"] = "box"
    width: float = Field(default=80, ge=1, le=1000, strict=True)
    depth: float = Field(default=60, ge=1, le=1000, strict=True)
    height: float = Field(default=30, ge=1, le=1000, strict=True)
    thickness: float = Field(default=3, ge=0.5, le=100, strict=True)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Use a readable design name")
        return value.strip()

    @model_validator(mode="after")
    def valid_walls(self):
        if (
            self.shape in ("bracket", "enclosure")
            and min(self.depth, self.height) - self.thickness < 0.5
        ):
            raise ValueError("Leave at least 0.5 mm beyond the base/wall thickness")
        if self.shape == "enclosure" and min(self.width, self.depth) - 2 * self.thickness < 0.5:
            raise ValueError("Enclosure openings must be at least 0.5 mm wide")
        return self


class SceneObject(SolidRecipe):
    position: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3
    )
    rotation: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3
    )
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    material: Literal["cyan", "titanium", "amber", "ceramic"] = "cyan"

    @field_validator("position", "rotation", "scale", mode="before")
    @classmethod
    def valid_vector(cls, value, info):
        import math

        low, high = {"position": (-2000, 2000), "rotation": (-360, 360), "scale": (0.1, 5)}[
            info.field_name
        ]
        if (
            not isinstance(value, list)
            or len(value) != 3
            or any(
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or not math.isfinite(x)
                or not low <= x <= high
                for x in value
            )
        ):
            raise ValueError("Use three finite numeric transform values within the supported range")
        return value


class ScenePresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: Literal["isometric", "top", "front"] = "isometric"
    lighting: Literal["soft", "studio", "contrast"] = "studio"
    quality: Literal["preview", "standard"] = "preview"
    background: Literal["dark", "neutral"] = "dark"


class Recipe(SolidRecipe):
    shape: Literal["box", "bracket", "enclosure", "scene"] = "box"
    objects: list[SceneObject] | None = Field(default=None, min_length=1, max_length=8)
    engine: Literal["offline", "blender"] = "offline"
    presentation: ScenePresentation = Field(default_factory=ScenePresentation)

    @model_validator(mode="after")
    def valid_scene(self):
        if (self.shape == "scene") != (self.objects is not None):
            raise ValueError(
                "Scenes require one to eight objects; solids do not accept scene objects"
            )
        return self


class BuildRequest(Recipe, RevisionParent):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class TreeBuildRequest(BuildRequest):
    """A live design built on the CAD kernel: the parts recipe plus its feature tree.

    The recipe stays the revision's recipe (studio history, fingerprints); the tree is what
    the kernel builds, always exporting GLB, STL and STEP.
    """

    tree: dict

    @field_validator("tree")
    @classmethod
    def valid_tree(cls, value):
        from services.cad_features import FeatureTreeError, canonical

        try:
            data = json.loads(canonical(value))
        except FeatureTreeError as exc:
            raise ValueError(str(exc)) from None
        data["export"] = list(KERNEL_EXPORTS)
        return data


class ArtifactRequest(JobRequest):
    format: Literal["stl", "glb", "json", "blend", "png", "step"] = "stl"


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: StrictStr = Field(min_length=1, max_length=2000)
    target: Literal["solid", "scene"] = "solid"
    reference: CreativeReference | None = None


class SceneBlueprint(BaseModel):
    """Provider data only: engine selection and execution stay with the owner."""
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=60)
    shape: Literal["scene"]
    objects: list[SceneObject] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validated_recipe(self):
        Recipe.model_validate(self.model_dump())
        return self


class MeshStats(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    vertices: StrictInt = Field(ge=4, le=8192)
    triangles: StrictInt = Field(ge=4, le=4096)
    watertight: bool = Field(strict=True)
    volume_mm3: float = Field(gt=0, le=1_000_000_000_000, strict=True)
    bounds_mm: list[list[float]] = Field(min_length=2, max_length=2)


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stats: MeshStats
    artifacts: dict[str, ExportMetadata]


class KernelStats(BaseModel):
    """Facts of a CAD-kernel build (B-rep, so no vertex limit like the offline mesh)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    engine: Literal["kernel"]
    volume_mm3: float = Field(gt=0, le=1_000_000_000_000, strict=True)
    bounds_mm: list[list[float]] = Field(min_length=2, max_length=2)
    triangles: StrictInt | None = Field(default=None, ge=0)
    faces: StrictInt = Field(ge=0)
    edges: StrictInt = Field(ge=0)
    solids: StrictInt = Field(ge=0)
    valid: bool = Field(strict=True)


class KernelResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stats: KernelStats
    artifacts: dict[str, ExportMetadata]


def stl_triangles(raw):
    """The triangle count of a binary STL, or None when it isn't one."""
    if len(raw) >= 84:
        count = int.from_bytes(raw[80:84], "little")
        if len(raw) == 84 + 50 * count:
            return count
    return None


class KernelProcess:
    """A feature-tree job's "worker": the CAD kernel's final build, run in this process.

    It has the ``alive``/``exit_code``/``close`` surface of ``WorkspaceProcess``, so the
    creative job keeps its queue, deadline, gaming-mode cancel, staging and revision
    rename. The kernel's files are copied into the staging folder as ``model.<ext>``, with
    the canonical tree as ``model.json``. ``error`` holds the kernel's plain message.
    """

    def __init__(self, kernel, tree, staging):
        self.error = None
        self.ok = False
        self.task = asyncio.get_running_loop().create_task(
            self.run(kernel, tree, Path(staging)), name="cad-kernel-final"
        )

    async def run(self, kernel, tree, staging):
        from services.cad_features import canonical

        try:
            result = await kernel.build(tree, export=list(KERNEL_EXPORTS), quality="final")
            artifacts, payloads = {}, {}
            for extension in KERNEL_EXPORTS:
                path = Path(result["files"][extension])
                if path.stat().st_size > EXPORT_LIMIT:
                    raise ServiceError(
                        "artifact_too_large",
                        f"The {extension.upper()} file is larger than 16 MB. Simplify the design.",
                    )
                payloads[extension] = path.read_bytes()
            payloads["json"] = canonical(tree).encode("utf-8")
            for extension, raw in payloads.items():
                (staging / f"model.{extension}").write_bytes(raw)
                artifacts[extension] = {
                    "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                }
            facts = result.get("facts") or {}
            low = [float(value) for value in facts.get("min") or (0, 0, 0)]
            size = [float(value) for value in facts.get("bbox") or (0, 0, 0)]
            stats = {
                "engine": "kernel",
                "volume_mm3": float(facts.get("volume") or 0),
                "bounds_mm": [low, [a + b for a, b in zip(low, size, strict=True)]],
                "triangles": stl_triangles(payloads["stl"]),
                "faces": int(facts.get("faces") or 0),
                "edges": int(facts.get("edges") or 0),
                "solids": int(facts.get("solids") or 0),
                "valid": bool(facts.get("valid")),
            }
            (staging / "result.json").write_text(
                json.dumps({"stats": stats, "artifacts": artifacts}), encoding="utf-8"
            )
            folders = {Path(path).parent for path in result["files"].values()}
            for folder in folders:  # final builds aren't cached: drop the kernel's copy
                if folder.name.endswith("-final"):
                    shutil.rmtree(folder, ignore_errors=True)
            self.ok = True
        except ServiceError as exc:  # CadKernelError included: a plain message
            self.error = exc
        except Exception:
            logger.warning("CAD kernel final build could not be saved", exc_info=True)
            self.error = ServiceError(
                "worker_failed", "The CAD engine's build couldn't be saved. Try again."
            )

    def alive(self):
        return not self.task.done()

    def exit_code(self):
        return 0 if self.task.done() and self.ok else 1

    def close(self):
        if not self.task.done():
            self.task.cancel()  # the kernel kills its worker's tree on cancellation


def blender_executable():
    """Discover an installed application without importing it or running a probe."""
    import shutil

    found = shutil.which("blender")
    if found:
        return str(Path(found).resolve())
    root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation"
    if root.is_dir():
        candidates = sorted(root.glob("Blender */blender.exe"), reverse=True)
        if candidates:
            return str(candidates[0].resolve())
    return None


class CadService(CreativeJobService):
    namespace = "cad_jobs:"
    artifact_root = "cad"
    recipe_model = Recipe
    worker_script = "workers/cad_worker.py"
    phases = (*CreativeJobService.phases, "blender")
    kernel = None  # the CAD kernel (services/cad_kernel.py), set by LiveDesigns

    async def start(self, args, context):
        # A live design built on the CAD kernel passes its feature tree in the context
        # (server code only: LiveDesigns' nested generate_cad dispatch), never in arguments,
        # so the studio's cad_submit contract is unchanged.
        tree = context.get(TREE_CONTEXT)
        if tree is None:
            return await super().start(args, context)
        if not (self.kernel is not None and self.kernel.available()):
            from services.cad_kernel import SETUP_HINT

            raise ServiceError("cad_kernel_unavailable", SETUP_HINT)
        request = TreeBuildRequest.model_validate({**args.model_dump(), "tree": tree})
        return await super().start(request, context)

    def worker_factory(self, value):
        if value.get("tree") is None:
            return self.process_factory
        kernel, tree = self.kernel, value["tree"]
        if kernel is None:
            raise ServiceError("cad_kernel_unavailable", "The CAD engine isn't available.")
        return lambda executable, script, bootstrap, project: KernelProcess(
            kernel, tree, bootstrap["staging"]
        )

    def job_deadline(self, value):
        if value.get("tree") is not None:
            return KERNEL_DEADLINE
        return super().job_deadline(value)

    def validate_job(self, raw, value):
        if value.get("tree") is None:
            return super().validate_job(raw, value)
        result = KernelResult.model_validate_json(raw).model_dump()
        if set(result["artifacts"]) != {*KERNEL_EXPORTS, "json"}:
            raise ServiceError("worker_failed", "Artifact validation failed.")
        return result

    def admit(self, recipe):
        executable = blender_executable() if recipe["engine"] == "blender" else None
        if recipe["engine"] == "blender" and not executable:
            raise ServiceError(
                "blender_unavailable",
                "Blender is not installed. Choose the offline engine to build this scene.",
            )
        return executable

    def bootstrap(self, staging, recipe, backend):
        return {"staging": str(staging), "recipe": recipe, "blender": backend}

    def deadline_seconds(self, recipe):
        return max(self.timeout, 120) if recipe.get("engine") == "blender" else self.timeout

    def artifact_label(self, recipe):
        return recipe["shape"]

    def validate_result(self, raw, recipe):
        result = WorkerResult.model_validate_json(raw).model_dump()
        expected = (
            {"stl", "glb", "json", "blend", "png"}
            if recipe.get("engine") == "blender"
            else {"stl", "glb", "json"}
        )
        if set(result["artifacts"]) != expected or result["stats"]["watertight"] is not True:
            raise ServiceError("worker_failed", "Artifact validation failed.")
        return result


async def plan_recipe(prompt, provider_factory=None):
    """Optional provider proposes data only. It cannot write files or execute code."""
    return await _plan_blueprint(prompt, SolidRecipe, provider_factory)


async def plan_scene(prompt, provider_factory=None):
    proposal = await _plan_blueprint(prompt, SceneBlueprint, provider_factory)
    return Recipe.model_validate(proposal).model_dump(mode="json")


async def _plan_blueprint(prompt, model, provider_factory):
    from llm.base import Message, MessageRole
    from services.conversation import create_text_provider

    provider = None
    try:
        provider = (provider_factory or create_text_provider)()
        async with asyncio.timeout(30):
            response = await metered_generate(
                provider,
                [Message(MessageRole.USER, prompt)],
                tools=[
                    {
                        "function_declarations": [
                            {
                                "name": "propose_cad_recipe",
                                "description": "Propose editable boxes, L brackets or open enclosures in millimetres. Scene proposals contain one to eight placed parts.",
                                "parameters": model.model_json_schema(),
                            }
                        ]
                    }
                ],
                system_instruction="Return exactly one propose_cad_recipe call matching the supplied schema. Only boxes, L brackets and open enclosures are available. For a scene use one to eight parts, dimensions/translation in millimetres, XYZ rotations in degrees and positive scale. Materials are cyan, titanium, amber or ceramic. Place parts deliberately; overlaps remain separate meshes, not boolean unions. Do not invent holes, fillets, arbitrary meshes, scripts, paths or executable code. Never choose an engine or start a build. The user previews and reviews the proposal before applying it.",
            )
            if len(response.tool_calls) != 1 or response.tool_calls[0].name != "propose_cad_recipe":
                raise ServiceError(
                    "plan_invalid", "The planner did not return a supported blueprint."
                )
            return model.model_validate(response.tool_calls[0].args).model_dump()
    except ServiceError:
        raise
    except TimeoutError as exc:
        raise ServiceError("provider_timeout", "The blueprint request timed out.") from exc
    except Exception as exc:
        raise ServiceError(
            "plan_invalid", "The provider could not propose valid supported dimensions."
        ) from exc
    finally:
        if provider:
            try:
                await asyncio.wait_for(provider.close(), 5)
            except Exception:
                logger.warning("AI provider client did not close cleanly", exc_info=True)


def register_cad_tools(dispatcher, service, designs=None):
    # generate_cad serves the 3D studio's cad_submit; the brain designs through the live
    # design tools (services/cad_design.py), so it stays model-invisible.
    dispatcher.register(
        ToolSpec(
            "generate_cad",
            "Build parametric solids or a typed scene of up to eight objects with transforms/materials. Offline STL/GLB; optional installed Blender projects and render.",
            BuildRequest,
            service.start,
            model_visible=False,
            long_running=True,
        )
    )
    if designs is not None:
        designs.register(dispatcher)
