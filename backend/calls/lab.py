"""Owner/project-scoped UI diagnostics. The desktop API cannot start a live call."""

import asyncio
import importlib.util
import os
import time

from calls.lab_contracts import LabState, LabRecord
from calls.records import CallRecords
from calls.supervisor import CallSupervisor, ROOT
from calls.local_voice import ready as local_ready
from calls.local_model import ready as model_ready, require_evaluation
from services.storage import Database, scope_hash
from services.tools import ServiceError


class CallLab:
    kind = "call_bridge_checks_v1"

    def __init__(self, app):
        self.app, self.active = app, None
        self.supervisor_factory = CallSupervisor

    def context(self, sid):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        context = self.app.studio_context(sid)
        return owner, context["project_path"]

    def scope(self, owner, project):
        return scope_hash(owner + "\n" + str(project.resolve()))

    def load(self, db, owner, project):
        key = self.scope(owner, project)
        value = self.app.database.get(db, self.kind, key) or {"runs": [], "seen": []}
        changed = False
        for item in value["runs"]:
            if item["state"] == "running" and (not self.active or self.active["id"] != item["id"]):
                item.update(state="uncertain", code="core_restarted", finished_at=time.time())
                changed = True
        if changed:
            self.app.database.put(db, self.kind, key, value)
        return key, value

    def records_directory(self, owner, project):
        base = self.app.database.directory.resolve() / "call-bridge-checks"
        directory = base / self.scope(owner, project)
        if base.resolve() != base or directory.resolve() != directory:
            raise ServiceError("call_lab_path", "The call check data path is linked.")
        return directory

    def state(self, sid):
        owner, project = self.context(sid)
        with self.app.database.transaction() as db:
            _, book = self.load(db, owner, project)
        try:
            local_ready()
            voice_configured = True
        except ServiceError:
            voice_configured = False
        helper = (ROOT / ".runtime/call-bridge/bin/CallControl.exe").is_file()
        audio = importlib.util.find_spec("sounddevice") is not None
        try:
            model_ready()
            model_installed = True
        except ServiceError:
            model_installed = False
        try:
            require_evaluation()
            model_accepted = True
        except ServiceError:
            model_accepted = False
        return LabState(
            project=project.name, helper_built=helper,
            audio_installed=audio,
            voice_configured=voice_configured,
            model_installed=model_installed, model_accepted=model_accepted,
            worker_supported=os.name == "nt", worker_busy=self.active is not None or self.app.call_admission.active is not None,
            admission=self.app.call_admission.availability(
                sid, components_ready=helper and audio and voice_configured and os.name == "nt"),
            runs=sorted(book["runs"], key=lambda item: item["started_at"], reverse=True),
        ).model_dump(mode="json")

    def start(self, sid, identifier):
        owner, project = self.context(sid)
        if self.active:
            raise ServiceError("call_lab_busy", "A bridge check is already running. Stop it or wait.")
        if os.name != "nt":
            raise ServiceError("call_lab_platform", "The owned bridge check requires Windows.")
        identifier = str(identifier)
        with self.app.database.transaction() as db:
            key, book = self.load(db, owner, project)
            if identifier in book["seen"]:
                raise ServiceError("call_lab_duplicate", "This check was already requested; it will not replay.")
            if len(book["seen"]) >= 256:
                raise ServiceError("call_lab_capacity", "This project's 256-check request ledger is full.")
            if len(book["runs"]) >= 24:
                book["runs"].remove(min(book["runs"], key=lambda item: item["started_at"]))
            reservation = "call-check:" + identifier
            self.app.resources.reserve(reservation, "verification_fixture")
            try:
                book["runs"].append({"id": identifier, "mode": "offline_fixture", "state": "running",
                                    "code": None, "started_at": time.time(), "finished_at": None, "record_id": None})
                book["seen"].append(identifier)
                self.app.database.put(db, self.kind, key, book)
            except BaseException:
                self.app.resources.release(reservation)
                raise
        run = {"id": identifier, "sid": sid, "owner": owner, "project": project,
               "stop": asyncio.Event(), "reservation": reservation}
        self.active = run
        run["task"] = asyncio.create_task(self.drive(run), name="call-bridge-check")
        run["task"].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return self.state(sid)

    def authorize(self, run):
        owner, project = self.context(run["sid"])
        if owner != run["owner"] or project != run["project"]:
            raise ServiceError("call_lab_scope", "The call check scope changed.")
        if self.app.resources.state in {"resident", "gaming"} or self.app.resources.fault:
            raise ServiceError("resource_policy", "The call check was stopped by resource policy.")

    async def drive(self, run):
        result, code = None, "call_lab_interrupted"
        supervisor = self.supervisor_factory()
        try:
            await self.app.resources.acquire(run["reservation"], run["stop"])
            self.authorize(run)
            result = await supervisor.run(
                {"mode": "offline_fixture", "records_directory": str(self.records_directory(run["owner"], run["project"]))},
                run["stop"], lambda: self.authorize(run), timeout=20,
            )
        except asyncio.CancelledError:
            code = "call_lab_stopped"
        except Exception as exc:
            code = exc.code if isinstance(exc, ServiceError) else "call_lab_failed"
        finally:
            record_id = (result or {}).get("id") or supervisor.last_record_id
            try:
                with self.app.database.transaction() as db:
                    key = self.scope(run["owner"], run["project"])
                    book = self.app.database.get(db, self.kind, key)
                    for item in book["runs"]:
                        if item["id"] == run["id"]:
                            item.update(state=result["state"] if result else "uncertain",
                                        code=result.get("code") if result else code,
                                        record_id=record_id, finished_at=time.time())
                    self.app.database.put(db, self.kind, key, book)
            finally:
                self.app.resources.release(run["reservation"])
                if self.active is run:
                    self.active = None

    async def stop(self, sid, identifier):
        self.context(sid)
        if self.active and self.active["id"] == str(identifier):
            if self.active["sid"] != sid:
                raise ServiceError("call_lab_origin", "Stop this check from its owning workspace.")
            await self.stop_sid(sid)
        return self.state(sid)

    async def stop_sid(self, sid=None):
        run = self.active
        if not run or sid is not None and run["sid"] != sid:
            return
        run["stop"].set()
        task = run["task"]
        try:
            await asyncio.wait_for(asyncio.shield(task), 7)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def record(self, sid, identifier):
        owner, project = self.context(sid)
        with self.app.database.transaction() as db:
            _, book = self.load(db, owner, project)
        run = next((item for item in book["runs"] if item["id"] == str(identifier)), None)
        if not run or not run["record_id"] or run["state"] == "running":
            raise ServiceError("call_lab_record", "No finished local record is available for this check.")
        directory = self.records_directory(owner, project)
        if not (directory / "assistant.sqlite3").is_file():
            raise ServiceError("call_lab_record", "The check record is unavailable.")
        records = CallRecords(Database(directory)).recent()
        item = next((item for item in records if item["id"] == run["record_id"]), None)
        if not item:
            raise ServiceError("call_lab_record", "The retained check record has expired.")
        return LabRecord(id=item["id"], source=item["source"], state=run["state"],
                         transcript=item["transcript"]).model_dump(mode="json")
