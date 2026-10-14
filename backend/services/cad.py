"""Scoped durable CAD jobs. Geometry and exports live in an owned worker process."""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
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
from services.storage import scope_hash, StorageError
from services.tools import ServiceError, ToolSpec, contained_path


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


class Recipe(SolidRecipe):
    shape: Literal["box", "bracket", "enclosure", "scene"] = "box"
    objects: list[SceneObject] | None = Field(default=None, min_length=1, max_length=8)
    engine: Literal["offline", "blender"] = "offline"

    @model_validator(mode="after")
    def valid_scene(self):
        if (self.shape == "scene") != (self.objects is not None):
            raise ValueError(
                "Scenes require one to eight objects; solids do not accept scene objects"
            )
        return self


class BuildRequest(Recipe):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID


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


class ExportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bytes: StrictInt = Field(gt=0, le=16_777_216)
    sha256: StrictStr = Field(pattern="^[a-f0-9]{64}$")


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stats: MeshStats
    artifacts: dict[str, ExportMetadata]


def read_export(path, metadata):
    """Bound the actual read as well as stat, so an edited file cannot grow the core."""
    if (
        not path.is_file()
        or path.stat().st_size != metadata["bytes"]
        or not 0 < metadata["bytes"] <= 16_777_216
    ):
        raise ServiceError("artifact_invalid", "The export changed or is missing.")
    with path.open("rb") as stream:
        raw = stream.read(metadata["bytes"] + 1)
    if len(raw) != metadata["bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ServiceError(
            "artifact_invalid", "The export changed; preserve it and inspect the project."
        )
    return raw


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


class CadService:
    def __init__(self, database, governor, on_update=None, process_factory=None, timeout=30):
        self.database, self.governor = database, governor
        self.on_update, self.process_factory, self.timeout = on_update, process_factory, timeout
        self.active = {}
        self.lock = asyncio.Lock()

    def kind(self, owner, project):
        return "cad_jobs:" + scope_hash(owner + ":" + str(Path(project).resolve()))

    def load(self, owner, project, request_id):
        with self.database.connection() as db:
            value = self.database.get(db, self.kind(owner, project), str(request_id))
        if (
            value
            and value["state"] in ("queued", "running")
            and (self.kind(owner, project), str(request_id)) not in self.active
        ):
            value = {
                **value,
                "state": "interrupted",
                "phase": "interrupted",
                "error": "This build was interrupted. Inspect project artifacts before starting a new build.",
            }
        return value

    def save(self, owner, project, value):
        with self.database.transaction() as db:
            self.database.put(db, self.kind(owner, project), value["request_id"], value)

    def public(self, value):
        return {
            key: value[key]
            for key in (
                "request_id",
                "project",
                "recipe",
                "state",
                "phase",
                "created_at",
                "error",
                "stats",
                "artifacts",
            )
            if key in value
        }

    async def publish(self, owner, value):
        if self.on_update:
            try:
                await self.on_update(owner, self.public(value))
            except Exception:
                pass  # Transport loss does not erase the committed result.

    def list(self, owner, project):
        with self.database.connection() as db:
            values = self.database.all(db, self.kind(owner, project))
        return [
            self.public(self.load(owner, project, value["request_id"]))
            for value in sorted(values, key=lambda value: value["created_at"], reverse=True)[:12]
        ]

    async def start(self, args, context):
        owner, project = context["principal"], Path(context["project_path"]).resolve()
        key = str(args.request_id)
        recipe = Recipe.model_validate(args.model_dump(exclude={"request_id"})).model_dump()
        async with self.lock:
            previous = self.load(owner, project, key)
            if previous:
                if Recipe.model_validate(previous["recipe"]).model_dump() != recipe:
                    raise ServiceError(
                        "request_conflict", "This build ID was already used with other dimensions."
                    )
                return self.public(previous)
            self.governor.require_heavy()
            if recipe["engine"] == "blender" and not blender_executable():
                raise ServiceError(
                    "blender_unavailable",
                    "Blender is not installed. Choose the offline engine to build this scene.",
                )
            if self.active:
                raise ServiceError(
                    "worker_busy", "One creative build is already running. Wait or cancel it first."
                )
            kind = self.kind(owner, project)
            with self.database.transaction() as db:
                # Atomic claim prevents another service from replaying this scoped request.
                previous = self.database.get(db, kind, key)
                if previous:
                    raise ServiceError(
                        "request_uncertain", "This build was already claimed. Refresh its status."
                    )
                count = db.execute(
                    "SELECT count(*) FROM documents WHERE kind=?", (kind,)
                ).fetchone()[0]
                if count >= 128:
                    raise ServiceError(
                        "job_limit",
                        "This project has reached its build-history limit. Preserve its artifacts and use another project.",
                    )
                value = {
                    "request_id": key,
                    "project": project.name,
                    "recipe": recipe,
                    "state": "queued",
                    "phase": "queued",
                    "created_at": time.time(),
                    "error": None,
                }
                self.database.put(db, kind, key, value)
            running = {
                "owner": owner,
                "project": project,
                "cancel": asyncio.Event(),
                "process": None,
                "key": (kind, key),
            }
            self.active[running["key"]] = running
            running["task"] = asyncio.create_task(self.run(value, running))
            return self.public(value)

    async def run(self, value, running):
        owner, project = running["owner"], running["project"]
        staging = None
        try:
            staging = contained_path(project, f"cad/.work/{uuid.uuid4()}")
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging = contained_path(project, str(staging.relative_to(project)))
            staging.mkdir()
            self.governor.require_heavy()
            if running["cancel"].is_set():
                raise ServiceError("job_cancelled", "Build cancelled.")
            if self.process_factory is None:
                from resident.win32 import WorkspaceProcess

                factory = WorkspaceProcess
            else:
                factory = self.process_factory
            executable = Path(sys.executable)
            if executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            running["process"] = factory(
                executable,
                Path(__file__).resolve().parents[1] / "workers/cad_worker.py",
                {
                    "staging": str(staging),
                    "recipe": value["recipe"],
                    "blender": blender_executable()
                    if value["recipe"].get("engine") == "blender"
                    else None,
                },
                project,
            )
            value.update(state="running", phase="building")
            self.save(owner, project, value)
            await self.publish(owner, value)
            deadline = time.monotonic() + (
                max(self.timeout, 120)
                if value["recipe"].get("engine") == "blender"
                else self.timeout
            )
            while running["process"].alive():
                if running["cancel"].is_set() or self.governor.state in ("gaming", "resident"):
                    raise ServiceError(
                        "job_cancelled", "Build cancelled; worker resources released."
                    )
                if time.monotonic() > deadline:
                    raise ServiceError(
                        "worker_timeout", "The build timed out; its worker was stopped."
                    )
                progress = contained_path(
                    project, str((staging / "progress.json").relative_to(project))
                )
                if progress.exists() and progress.stat().st_size < 1000:
                    try:
                        phase = json.loads(progress.read_text())["phase"]
                    except (ValueError, KeyError, OSError):
                        phase = value["phase"]
                    if (
                        phase in ("building", "validating", "saving", "blender")
                        and phase != value["phase"]
                    ):
                        value["phase"] = phase
                        await self.publish(owner, value)
                await asyncio.sleep(0.05)
            # Close the entire owned tree before publishing any completed artifact.
            exit_code = running["process"].exit_code()
            running["process"].close()
            if exit_code != 0:
                raise ServiceError(
                    "worker_failed", "The geometry worker stopped before completing validation."
                )
            if running["cancel"].is_set() or self.governor.state in ("gaming", "resident"):
                raise ServiceError("job_cancelled", "Build cancelled before saving.")
            result_path = contained_path(
                project, str((staging / "result.json").relative_to(project))
            )
            if not result_path.exists() or result_path.stat().st_size > 8000:
                raise ServiceError("worker_failed", "The worker did not produce a valid result.")
            with result_path.open("rb") as stream:
                result_bytes = stream.read(8001)
            if len(result_bytes) > 8000:
                raise ServiceError("worker_failed", "Worker metadata exceeded its limit.")
            result = WorkerResult.model_validate_json(result_bytes).model_dump()
            artifacts = result["artifacts"]
            if (
                set(artifacts)
                != (
                    {"stl", "glb", "json", "blend", "png"}
                    if value["recipe"].get("engine") == "blender"
                    else {"stl", "glb", "json"}
                )
                or result["stats"]["watertight"] is not True
                or not 1 <= result["stats"]["triangles"] <= 4096
            ):
                raise ServiceError("worker_failed", "Artifact validation failed.")
            for extension, metadata in artifacts.items():
                path = contained_path(
                    project, str((staging / f"model.{extension}").relative_to(project))
                )
                read_export(path, metadata)
            relative = f"cad/designs/{uuid.uuid5(uuid.NAMESPACE_URL, self.kind(owner, project) + value['request_id'])}"
            destination = contained_path(project, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = contained_path(project, relative)
            os.rename(staging, destination)  # Never replace an existing revision.
            staging = None
            value.update(
                state="succeeded",
                phase="ready",
                stats=result["stats"],
                artifacts=artifacts,
                directory=relative,
            )
        except asyncio.CancelledError:
            value.update(
                state="cancelled", phase="cancelled", error="Build stopped with the workspace/core."
            )
        except ServiceError as exc:
            value.update(
                state="cancelled" if exc.code == "job_cancelled" else "failed",
                phase="stopped",
                error=str(exc),
            )
        except Exception:
            value.update(
                state="failed",
                phase="stopped",
                error="The worker could not complete this build. Existing designs were preserved.",
            )
        finally:
            if running["process"]:
                running["process"].close()
            if (
                staging
                and staging.resolve() == staging
                and not staging.is_symlink()
                and not staging.is_junction()
            ):
                # Delete only known temporary files, never recurse through user directories.
                for name in (
                    "progress.tmp",
                    "progress.json",
                    "result.json",
                    "model.stl",
                    "model.glb",
                    "model.json",
                    "model.blend",
                    "model.png",
                    "blender.glb",
                ):
                    try:
                        (staging / name).unlink(missing_ok=True)
                    except OSError:
                        pass  # Preserve unexpected entries; do not recurse through them.
                try:
                    staging.rmdir()
                except OSError:
                    pass
            try:
                self.save(owner, project, value)
            except StorageError:
                value.update(
                    state="interrupted",
                    phase="interrupted",
                    error="Build history could not save. Inspect project artifacts before starting a new build.",
                )
            finally:
                self.active.pop(running["key"], None)
            await self.publish(owner, value)

    async def cancel(self, owner, project, request_id):
        key = str(request_id)
        value = self.load(owner, project, key)
        if not value:
            raise ServiceError("job_missing", "This build is not available in this project.")
        running = self.active.get((self.kind(owner, project), key))
        if running and running["owner"] == owner and running["project"] == Path(project).resolve():
            running["cancel"].set()
            await running["task"]
        return self.public(self.load(owner, project, key))

    async def cancel_owner(self, owner):
        for running in tuple(self.active.values()):
            if running["owner"] == owner:
                running["cancel"].set()
                await running["task"]

    async def close(self):
        tasks = []
        for running in tuple(self.active.values()):
            running["cancel"].set()
            tasks.append(running["task"])
        await asyncio.gather(*tasks, return_exceptions=True)

    def artifact(self, owner, project, args):
        value = self.load(owner, project, args.request_id)
        if not value or value["state"] != "succeeded":
            raise ServiceError(
                "artifact_missing", "Build this design successfully before exporting it."
            )
        if args.format not in value["artifacts"]:
            raise ServiceError("artifact_missing", "This revision does not contain that export.")
        metadata = value["artifacts"][args.format]
        path = contained_path(Path(project), f"{value['directory']}/model.{args.format}")
        raw = read_export(path, metadata)
        return {
            "format": args.format,
            "filename": f"inara-{value['recipe']['shape']}-{value['request_id'][:8]}.{args.format}",
            "data": base64.b64encode(raw).decode(),
            **metadata,
        }


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
