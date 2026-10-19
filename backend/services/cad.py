"""Scoped durable CAD jobs. Geometry and exports live in an owned worker process."""

import asyncio
import os
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
from services.tools import ServiceError, ToolSpec


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


class ArtifactRequest(JobRequest):
    format: Literal["stl", "glb", "json", "blend", "png"] = "stl"


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: StrictStr = Field(min_length=1, max_length=2000)


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
    from llm.base import Message, MessageRole
    from services.conversation import create_text_provider

    provider = None
    try:
        provider = (provider_factory or create_text_provider)()
        async with asyncio.timeout(30):
            response = await provider.generate(
                [Message(MessageRole.USER, prompt)],
                tools=[
                    {
                        "function_declarations": [
                            {
                                "name": "propose_cad_recipe",
                                "description": "Propose one editable box, L bracket or open enclosure in millimetres.",
                                "parameters": SolidRecipe.model_json_schema(),
                            }
                        ]
                    }
                ],
                system_instruction="Return exactly one propose_cad_recipe call. Only supported parametric solids are available. Do not invent holes, fillets, arbitrary meshes or executable code. The user reviews dimensions before building.",
            )
            if len(response.tool_calls) != 1 or response.tool_calls[0].name != "propose_cad_recipe":
                raise ServiceError(
                    "plan_invalid", "The planner did not return a supported blueprint."
                )
            return SolidRecipe.model_validate(response.tool_calls[0].args).model_dump()
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
                pass


def register_cad_tools(dispatcher, service):
    dispatcher.register(
        ToolSpec(
            "generate_cad",
            "Build parametric solids or a typed scene of up to eight objects with transforms/materials. Offline STL/GLB; optional installed Blender projects and render.",
            BuildRequest,
            service.start,
        )
    )
