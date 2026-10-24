"""Owned slicer execution and a durable, independently authorized print pipeline."""

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import time

from services.device_contracts import PrintRequest, PrintStage
from services.storage import scope_hash
from services.tools import ServiceError, ToolSpec, contained_path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def checked_file(root, path, suffixes, limit):
    value = contained_path(root, str(path))
    if (
        not value.is_file()
        or value.suffix.lower() not in suffixes
        or not 0 < value.stat().st_size <= limit
    ):
        raise ServiceError(
            "print_file_invalid", "Select a supported, bounded file inside this project."
        )
    return value


class OwnedSlicer:
    def __init__(self, process_factory=None, timeout=330):
        self.process_factory, self.timeout = process_factory, timeout

    async def run(self, plan):
        from resident.win32 import WorkspaceProcess

        factory = self.process_factory or WorkspaceProcess
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process = None
        try:
            process = factory(
                executable,
                Path(__file__).resolve().parents[1] / "workers/print_slice_worker.py",
                {
                    "staging": str(plan.staging),
                    "output_name": plan.gcode.name,
                    "profile": plan.profile.name if plan.profile else None,
                    "printer_name": plan.target[0],
                },
                plan.staging,
            )
            deadline = time.monotonic() + self.timeout
            while process.alive():
                if time.monotonic() > deadline:
                    raise ServiceError(
                        "slicer_timeout", "Slicing timed out; the owned process tree was stopped."
                    )
                await asyncio.sleep(0.05)
            code = process.exit_code()
            process.close()
            result = contained_path(
                plan.root, str((plan.staging / "result.json").relative_to(plan.root))
            )
            if code != 0 or not result.is_file() or result.stat().st_size > 4096:
                raise ServiceError(
                    "slicer_failed",
                    "The slicer worker could not complete. Check optional printer setup.",
                )
            if json.loads(result.read_text(encoding="utf-8")).get("ok") is not True:
                raise ServiceError(
                    "slicer_failed",
                    "Slicing is unavailable or failed. Check the installed slicer and profiles.",
                )
        finally:
            if process:
                process.close()


@dataclass
class PrintPlan:
    owner: str
    root: Path
    args: PrintRequest
    staging: Path
    source: Path
    gcode: Path
    profile: Path | None
    target: tuple
    source_hash: str
    source_name: str = ""
    profile_hash: str | None = None
    gcode_hash: str | None = None
    phase: str = "planned"


class PrintService:
    def __init__(self, database, governor, dispatcher, devices, publish, slicer=None):
        self.database, self.governor, self.dispatcher = database, governor, dispatcher
        self.devices, self.publish, self.slicer = devices, publish, slicer or OwnedSlicer()
        self.active = None
        dispatcher.register(
            ToolSpec(
                "print_stl",
                "Print a project STL through separate slice, upload and start permissions. No retries.",
                PrintRequest,
                self.print,
            )
        )
        for name in ("slice_stl", "upload_gcode", "start_print"):
            dispatcher.register(
                ToolSpec(
                    name,
                    f"Internal authorized print stage: {name}.",
                    PrintStage,
                    self.stage(name),
                    execution_timeout=340 if name == "slice_stl" else 35,
                    model_visible=False,
                )
            )

    def kind(self, owner, root):
        return "print." + scope_hash(owner + ":" + str(root.resolve()))

    def record(self, plan, state, result=None):
        with self.database.transaction() as db:
            self.database.put(
                db,
                self.kind(plan.owner, plan.root),
                str(plan.args.request_id),
                {
                    "arguments": plan.args.model_dump(mode="json"),
                    "state": state,
                    "phase": plan.phase,
                    "result": result,
                },
            )

    def target(self, args):
        printer = self.devices.activate_printer()._resolve_printer(args.printer)
        if not printer:
            raise ServiceError("printer_missing", "Select a configured printer.")
        kind = getattr(printer.printer_type, "value", printer.printer_type)
        if kind not in ("moonraker", "octoprint"):
            raise ServiceError(
                "printer_unsupported", "Select an explicit supported printer protocol."
            )
        return (printer.name, printer.host, printer.port, kind)

    def prepare(self, args, context):
        root = Path(context["project_path"]).resolve()
        if args.stl_path == "current":
            candidates = [*root.glob("cad/*.stl"), *root.glob("cad/designs/*/model.stl")]
            safe = [
                checked_file(root, str(p.relative_to(root)), {".stl"}, 50_000_000)
                for p in candidates
            ]
            if not safe:
                raise ServiceError(
                    "print_file_missing", "Build or select an STL in this project first."
                )
            source = max(safe, key=lambda p: p.stat().st_mtime_ns)
        else:
            source = contained_path(root, args.stl_path)
            if not source.exists() and not args.stl_path.replace("\\", "/").startswith("cad/"):
                source = contained_path(root, "cad/" + args.stl_path)
            source = checked_file(root, str(source.relative_to(root)), {".stl"}, 50_000_000)
        target = self.target(args)
        staging = contained_path(root, ".printing/" + str(args.request_id))
        staging.mkdir(parents=True, exist_ok=False)
        staging = contained_path(root, str(staging.relative_to(root)))
        snapshot = staging / "input.stl"
        # Bound the resident's copy buffer. The slicer and descendants run in their owned worker.
        with source.open("rb") as src, snapshot.open("xb") as dst:
            import shutil

            shutil.copyfileobj(src, dst, 1024 * 1024)
        profile = None
        if args.profile:
            candidate = contained_path(root, args.profile)
            profile_root = root
            if not candidate.is_file():
                catalog = self.devices.printer.get_available_profiles()
                if args.profile not in {item for group in catalog.values() for item in group}:
                    raise ServiceError(
                        "profile_missing",
                        "Select a project profile or an exact installed profile catalog entry.",
                    )
                profile_root = Path(self.devices.printer._orca_profiles_dir).resolve()
            original = checked_file(profile_root, args.profile, {".ini", ".json"}, 2_000_000)
            profile = staging / ("profile" + original.suffix)
            profile.write_bytes(original.read_bytes())
        remote_name = (
            scope_hash(context["principal"] + ":" + str(root) + ":" + str(args.request_id))[:32]
            + ".gcode"
        )
        return PrintPlan(
            context["principal"],
            root,
            args,
            staging,
            snapshot,
            staging / remote_name,
            profile,
            target,
            digest(snapshot),
            source_name=str(source.relative_to(root)),
            profile_hash=digest(profile) if profile else None,
        )

    def assert_plan(self, plan, context):
        self.devices.authorize(context)
        if (
            not isinstance(plan, PrintPlan)
            or plan.owner != context["principal"]
            or plan.root != Path(context["project_path"]).resolve()
        ):
            raise ServiceError(
                "print_scope", "Start print stages through a validated print request."
            )
        self.governor.require_heavy()
        if self.target(plan.args) != plan.target:
            raise ServiceError(
                "printer_changed", "Printer configuration changed; start a new reviewed request."
            )

    async def print(self, args, context):
        self.devices.authorize(context)
        self.governor.require_heavy()
        root = Path(context["project_path"]).resolve()
        with self.database.transaction() as db:
            prior = self.database.get(
                db, self.kind(context["principal"], root), str(args.request_id)
            )
            if prior:
                if prior["arguments"] != args.model_dump(mode="json"):
                    raise ServiceError(
                        "request_conflict", "This print request ID already has different arguments."
                    )
                if prior["state"] == "succeeded":
                    return prior["result"]
                raise ServiceError(
                    "request_uncertain",
                    "This print request was already attempted. Inspect printer state; it will not replay.",
                )
            if len(self.database.all(db, self.kind(context["principal"], root))) >= 32:
                raise ServiceError(
                    "print_history_limit",
                    "This project has reached its protected print history limit. Preserve its artifacts before creating more jobs.",
                )
            if self.active or self.governor.creative_active or self.governor.creative_lock.locked():
                raise ServiceError(
                    "creative_busy", "Another creative or print workflow is running."
                )
            self.database.put(
                db,
                self.kind(context["principal"], root),
                str(args.request_id),
                {
                    "arguments": args.model_dump(mode="json"),
                    "state": "preparing",
                    "phase": "preparing",
                    "result": None,
                },
            )
        self.active = asyncio.current_task()
        plan = None
        try:
            plan = self.prepare(args, context)
            self.record(plan, "running")
            async with self.governor.creative_lock:
                for phase, path, checksum in (
                    ("slice_stl", plan.source, plan.source_hash),
                    ("upload_gcode", plan.gcode, None),
                    ("start_print", plan.gcode, None),
                ):
                    self.assert_plan(plan, context)
                    if phase != "slice_stl":
                        path = checked_file(
                            root, str(path.relative_to(root)), {".gcode"}, 100_000_000
                        )
                        checksum = plan.gcode_hash
                    payload = PrintStage(
                        request_id=args.request_id,
                        printer=args.printer,
                        path=str(path.relative_to(root)),
                        sha256=checksum,
                        source=plan.source_name,
                        target=f"{plan.target[1]}:{plan.target[2]}",
                        profile_sha256=plan.profile_hash,
                    )
                    await self.dispatcher.dispatch(
                        plan.owner,
                        phase,
                        payload.model_dump(mode="json"),
                        {**context, "_print_plan": plan},
                        context.get("request_approval"),
                    )
            result = {
                "status": "success",
                "message": f"Print start accepted by {plan.target[0]}.",
                "request_id": str(args.request_id),
            }
            self.record(plan, "succeeded", result)
            self.devices.start_monitor(plan.owner)
            return result
        except BaseException:
            if plan:
                self.record(
                    plan,
                    "uncertain" if plan.phase in ("upload_gcode", "start_print") else "stopped",
                )
            raise
        finally:
            self.active = None

    def stage(self, name):
        async def execute(args, context):
            plan = context.get("_print_plan")
            self.assert_plan(plan, context)
            expected = plan.source if name == "slice_stl" else plan.gcode
            checked = checked_file(
                plan.root,
                args.path,
                {".stl"} if name == "slice_stl" else {".gcode"},
                50_000_000 if name == "slice_stl" else 100_000_000,
            )
            if (
                args.request_id != plan.args.request_id
                or args.printer != plan.args.printer
                or checked != expected
                or digest(checked) != args.sha256
                or args.source != plan.source_name
                or args.target != f"{plan.target[1]}:{plan.target[2]}"
            ):
                raise ServiceError(
                    "print_changed", "The reviewed print input changed; start a new request."
                )
            if args.profile_sha256 != plan.profile_hash:
                raise ServiceError("print_changed", "The reviewed profile identity changed.")
            if plan.profile:
                original = checked_file(
                    plan.root,
                    str(plan.profile.relative_to(plan.root)),
                    {".ini", ".json"},
                    2_000_000,
                )
                if digest(original) != plan.profile_hash:
                    raise ServiceError("print_changed", "The reviewed profile snapshot changed.")
            plan.phase = name
            self.record(plan, "running")  # Persist before any externally effective upload/start.
            if name == "slice_stl":
                await self.publish(
                    "slicing_progress",
                    plan.owner,
                    {
                        "printer": args.printer,
                        "percent": 5,
                        "message": "Slicing reviewed project snapshot",
                    },
                )
                await self.slicer.run(plan)
                checked_file(
                    plan.root, str(plan.gcode.relative_to(plan.root)), {".gcode"}, 100_000_000
                )
                plan.gcode_hash = digest(plan.gcode)
            elif name == "upload_gcode":
                if not await self.devices.printer.upload_gcode(
                    f"{plan.target[1]}:{plan.target[2]}", str(plan.gcode), start_print=False
                ):
                    raise ServiceError(
                        "upload_uncertain",
                        "Upload did not confirm success. Inspect printer state before a new request.",
                    )
            else:
                if not await self.devices.printer.start_print(f"{plan.target[1]}:{plan.target[2]}", plan.gcode.name):
                    raise ServiceError(
                        "start_uncertain",
                        "Print start did not confirm success. Inspect the printer; this request will not replay.",
                    )
            return {"stage": name, "complete": True}

        return execute

    async def close(self):
        if self.active and self.active is not asyncio.current_task():
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)
