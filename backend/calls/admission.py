"""Core-owned local call admission. No public live-start route or auto-answer loop.

A later controlled-device integration must supply and continuously revalidate its
trusted physical acceptance check. Enrollment booleans alone cannot enable calls.
"""

import asyncio
import time
import uuid

from calls.contracts import BridgeProfile
from calls.supervisor import CallSupervisor
from services.storage import scope_hash
from services.tools import ServiceError


class CallAdmission:
    kind = "call_admission_v1"

    def __init__(self, app):
        self.app, self.active = app, None
        self.supervisor_factory = CallSupervisor

    def context(self, sid):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        return owner, self.app.studio_context(sid)["project_path"]

    def scope(self, owner, project):
        return scope_hash(owner + "\n" + str(project.resolve()))

    def availability(self, sid, *, components_ready):
        owner, project = self.context(sid)
        with self.app.database.transaction() as db:
            self.load(db, self.scope(owner, project))
        blockers = []
        if not components_ready:
            blockers.append("call_components_missing")
        if self.active or self.app.resources.reservations or self.app.resources.runner is not None:
            blockers.append("call_resources_busy")
        if self.app.resources.state in {"resident", "gaming"}:
            blockers.append("resource_policy")
        if self.app.resources.fault:
            blockers.append("resource_fault")
        try:
            self.app.resources.check_capacity("call_local")
        except ServiceError:
            blockers.append("resource_capacity")
        return {"admission_ready": not blockers, "active": self.active is not None,
                "blockers": [*blockers, "call_physical_unverified"],
                "live_enabled": False, "voice_mode": "local_structured_english", "cloud_fallback": False}

    def records_directory(self, owner, project):
        base = self.app.database.directory.resolve() / "call-bridge-live"
        directory = base / self.scope(owner, project)
        if base.resolve() != base or directory.resolve() != directory:
            raise ServiceError("call_admission_path", "The local call record path is linked.")
        return directory

    def load(self, db, key):
        book = self.app.database.get(db, self.kind, key) or {"seen": [], "runs": []}
        changed = False
        for item in book["runs"]:
            if item["state"] == "running" and (not self.active or self.active["id"] != item["id"]):
                item.update(state="uncertain", code="core_restarted", finished_at=time.time())
                changed = True
        if changed:
            self.app.database.put(db, self.kind, key, book)
        return book

    def authorize(self, run):
        owner, project = self.context(run["sid"])
        if owner != run["owner"] or project != run["project"]:
            raise ServiceError("call_scope_changed", "Call workspace changed; stopping the session.")
        resources = self.app.resources
        if (resources.state in {"resident", "gaming"} or resources.fault
                or resources.runner != run["reservation"]):
            raise ServiceError("resource_policy", "Call admission was withdrawn by resource policy.")
        if run["acceptance_check"](run["profile"]) is not True:
            raise ServiceError("call_physical_unverified", "Physical call acceptance is missing or changed.")

    def start(self, sid, identifier, profile, *, acceptance_check=None, arm_seconds=30, dialogue_mode="structured"):
        """Internal controlled-test seam; never accepts renderer-supplied verification."""
        owner, project = self.context(sid)
        identifier = str(uuid.UUID(str(identifier)))
        profile = BridgeProfile.model_validate(profile).model_copy(deep=True)
        if (acceptance_check is None or acceptance_check(profile) is not True
                or not profile.controls_confirmed or not profile.route_confirmed):
            raise ServiceError("call_physical_unverified", "Complete controlled physical acceptance before starting live calls.")
        if type(arm_seconds) is not int or not 1 <= arm_seconds <= 120:
            raise ServiceError("call_arm_invalid", "Use a one-call lease from 1 to 120 seconds.")
        if self.active:
            raise ServiceError("call_session_busy", "Another core-owned call session is active.")
        from calls.local_voice import ready
        ready()  # Presence only, before admitting a worker. No audio is opened.
        if dialogue_mode not in {"structured", "model"}:
            raise ServiceError("call_dialogue_mode", "Choose structured or evaluated local model dialogue.")
        if dialogue_mode == "model":
            from calls.local_model import require_evaluation, ready as model_ready
            require_evaluation()
            model_id = model_ready()["model"]["id"]
        reservation = "local-call:" + identifier
        key = self.scope(owner, project)
        run = {"id": identifier, "sid": sid, "owner": owner, "project": project,
               "profile": profile, "acceptance_check": acceptance_check,
               "reservation": reservation, "key": key, "stop": asyncio.Event(),
               "started": time.monotonic(), "ticket": None, "arm_seconds": arm_seconds,
               "dialogue_mode": dialogue_mode}
        self.app.resources.reserve_call(reservation, "call_model" if dialogue_mode == "model" else "call_local")
        recorded = False
        try:
            with self.app.database.transaction() as db:
                book = self.load(db, key)
                if identifier in book["seen"]:
                    raise ServiceError("call_duplicate", "This call request was already admitted; it will not replay.")
                if len(book["seen"]) >= 256:
                    raise ServiceError("call_admission_capacity", "This workspace's call admission ledger is full.")
                book["runs"] = book["runs"][-23:]
                book["seen"].append(identifier)
                book["runs"].append({"id": identifier, "source": profile.channel, "state": "running", "code": None,
                                     "record_id": None, "started_at": time.time(), "finished_at": None})
                self.app.database.put(db, self.kind, key, book)
            recorded = True
            run["ticket"] = self.app.usage.begin_local_call(
                owner, project, identifier, **({"model": model_id} if dialogue_mode == "model" else {}))
            self.active = run
            run["task"] = asyncio.create_task(self.drive(run), name="core-local-call")
            run["task"].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        except BaseException:
            try:
                if recorded:
                    self.finish(run, None, "call_admission_failed")
            finally:
                self.app.resources.release(reservation)
                if self.active is run:
                    self.active = None
            raise
        return identifier

    def finish(self, run, result, code, record_id=None):
        state = result["state"] if result else "uncertain"
        try:
            with self.app.database.transaction() as db:
                book = self.app.database.get(db, self.kind, run["key"])
                for item in book["runs"]:
                    if item["id"] == run["id"]:
                        item.update(state=state, code=result.get("code") if result else code,
                                    record_id=(result or {}).get("id") or record_id, finished_at=time.time())
                self.app.database.put(db, self.kind, run["key"], book)
        finally:
            if run["ticket"]:
                self.app.usage.finish(run["ticket"], state, None, time.monotonic() - run["started"])

    async def drive(self, run):
        result, code, supervisor = None, "call_session_interrupted", None
        try:
            self.authorize(run)
            supervisor = self.supervisor_factory()
            result = await supervisor.run(
                {"mode": "live", "voice_mode": "local", "profile": run["profile"].model_dump(),
                 "dialogue_mode": run["dialogue_mode"],
                 "records_directory": str(self.records_directory(run["owner"], run["project"])),
                 "arm_seconds": run["arm_seconds"]},
                run["stop"], lambda: self.authorize(run),
                timeout=run["arm_seconds"] + run["profile"].max_seconds + 35,
            )
        except asyncio.CancelledError:
            code = "owner_stopped"
        except Exception as exc:
            code = exc.code if isinstance(exc, ServiceError) else "call_session_failed"
        finally:
            try:
                self.finish(run, result, code, getattr(supervisor, "last_record_id", None))
            finally:
                self.app.resources.release(run["reservation"])
                if self.active is run:
                    self.active = None

    async def stop_sid(self, sid=None):
        run = self.active
        if not run or sid is not None and run["sid"] != sid:
            return
        run["stop"].set()
        try:
            await asyncio.wait_for(asyncio.shield(run["task"]), 7)
        except TimeoutError:
            run["task"].cancel()
            await asyncio.gather(run["task"], return_exceptions=True)
