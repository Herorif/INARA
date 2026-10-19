"""Shared durable creative-job lifetime. Adapters validate inputs and worker outputs."""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from services.capability_profiles import worker_profile
from services.storage import scope_hash, StorageError
from services.tools import ServiceError, contained_path


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID


class ExportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bytes: StrictInt = Field(gt=0, le=16_777_216)
    sha256: StrictStr = Field(pattern="^[a-f0-9]{64}$")


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


class CreativeJobService:
    namespace = "creative_jobs:"
    artifact_root = "creative"
    recipe_model = None
    worker_script = ""
    phases = ("building", "validating", "saving")
    default_timeout = 30

    def admit(self, recipe):
        return None

    def bootstrap(self, staging, recipe, backend):
        return {"staging": str(staging), "recipe": recipe}

    def validate_result(self, raw, recipe):
        raise NotImplementedError

    def validate_artifact(self, extension, raw, recipe):
        pass

    def artifact_label(self, recipe):
        return "creative"

    def deadline_seconds(self, recipe):
        return self.timeout

    def __init__(self, database, governor, on_update=None, process_factory=None, timeout=None):
        self.database, self.governor = database, governor
        self.on_update, self.process_factory, self.timeout = (
            on_update,
            process_factory,
            timeout if timeout is not None else self.default_timeout,
        )
        self.active = {}
        self.lock = governor.creative_lock

    def kind(self, owner, project):
        return self.namespace + scope_hash(owner + ":" + str(Path(project).resolve()))

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
                "resources",
                "background",
                "duration_seconds",
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
        recipe = self.recipe_model.model_validate(
            args.model_dump(exclude={"request_id"})
        ).model_dump()
        # The lock is otherwise held by legacy/print workflows. Reject rather
        # than building an unbounded second queue outside the owned reservations.
        if self.lock.locked():
            raise ServiceError(
                "worker_busy",
                "A legacy creative or print workflow is active. Wait for it to finish.",
            )
        async with self.lock:
            previous = self.load(owner, project, key)
            if previous:
                if self.recipe_model.model_validate(previous["recipe"]).model_dump() != recipe:
                    raise ServiceError(
                        "request_conflict", "This build ID was already used with other settings."
                    )
                return self.public(previous)
            self.governor.require_heavy()
            backend = self.admit(recipe)
            profile = worker_profile(
                self.namespace,
                recipe,
                getattr(self, "expected_backend", None) == "verification_fixture",
            )
            self.governor.check(profile)
            if len(self.governor.reservations) >= self.governor.max_jobs:
                raise ServiceError(
                    "worker_busy", "The creative queue is full. Cancel a job or wait."
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
            try:
                reservation = self.governor.reserve((kind, key), profile)
            except ServiceError as exc:
                value.update(state="failed", phase="stopped", error=str(exc))
                self.save(owner, project, value)
                raise
            value.update(resources=reservation, background=False)
            try:
                self.save(owner, project, value)
            except Exception:
                self.governor.release((kind, key))
                raise
            running = {
                "owner": owner,
                "project": project,
                "cancel": asyncio.Event(),
                "process": None,
                "backend": backend,
                "background": False,
                "value": value,
                "key": (kind, key),
            }
            self.active[running["key"]] = running
            running["task"] = asyncio.create_task(self.run(value, running))
        await self.publish(owner, value)
        return self.public(value)

    async def run(self, value, running):
        owner, project = running["owner"], running["project"]
        staging = None
        started = time.monotonic()
        try:
            await self.governor.acquire(running["key"], running["cancel"])
            staging = contained_path(project, f"{self.artifact_root}/.work/{uuid.uuid4()}")
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
                Path(__file__).resolve().parents[1] / self.worker_script,
                self.bootstrap(staging, value["recipe"], running["backend"]),
                project,
            )
            value.update(state="running", phase="building")
            self.save(owner, project, value)
            await self.publish(owner, value)
            previous = time.monotonic()
            deadline = previous + self.deadline_seconds(value["recipe"])
            while running["process"].alive():
                previous = self.governor.poll(previous)
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
                    if phase in self.phases and phase != value["phase"]:
                        value["phase"] = phase
                        await self.publish(owner, value)
                await asyncio.sleep(0.05)
            self.governor.poll(previous)
            # Close the entire owned tree before publishing any completed artifact.
            exit_code = running["process"].exit_code()
            running["process"].close()
            if exit_code != 0:
                raise ServiceError(
                    "worker_failed", "The creative worker stopped before completing validation."
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
            result = self.validate_result(result_bytes, value["recipe"])
            artifacts = result["artifacts"]
            for extension, metadata in artifacts.items():
                path = contained_path(
                    project, str((staging / f"model.{extension}").relative_to(project))
                )
                self.validate_artifact(extension, read_export(path, metadata), value["recipe"])
            relative = f"{self.artifact_root}/designs/{uuid.uuid5(uuid.NAMESPACE_URL, self.kind(owner, project) + value['request_id'])}"
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
                state="cancelled"
                if exc.code == "job_cancelled"
                else "interrupted"
                if exc.code == "job_interrupted"
                else "failed",
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
                try:
                    running["process"].close()
                except Exception:
                    value.update(
                        state="failed",
                        phase="stopped",
                        error="Worker cleanup failed; restart the core before more creative work.",
                    )
                    self.governor.fault = (
                        "Worker cleanup failed. Restart the core before more heavy work."
                    )
                    self.governor.select("resident")
            value["background"] = running["background"]
            value["duration_seconds"] = round(time.monotonic() - started, 3)
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
                self.governor.release(running["key"])
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

    async def set_background(self, owner, project, request_id, enabled):
        key = (self.kind(owner, project), str(request_id))
        running = self.active.get(key)
        if not running or running["owner"] != owner:
            raise ServiceError("job_missing", "This job is no longer active in this project.")
        value = {**running["value"], "background": enabled}
        self.save(owner, project, value)
        running["background"] = enabled
        running["value"]["background"] = enabled
        await self.publish(owner, value)
        return self.public(value)

    async def cancel_owner(self, owner, panel_only=False):
        tasks = []
        for running in tuple(self.active.values()):
            if running["owner"] == owner and not (panel_only and running["background"]):
                running["cancel"].set()
                tasks.append(running["task"])
        await asyncio.gather(*tasks, return_exceptions=True)

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
            "filename": f"inara-{self.artifact_label(value['recipe'])}-{value['request_id'][:8]}.{args.format}",
            "data": base64.b64encode(raw).decode(),
            **metadata,
        }
