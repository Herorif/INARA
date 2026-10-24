"""Core/transport ownership and supervised worker fixtures; no physical calls."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from calls.lab_contracts import LabState
from calls.supervisor import CallSupervisor
from calls.records import CallRecords
from calls.fixture import FixtureControl
from services.storage import Database
from services.tools import ServiceError


@pytest.fixture
def owner_app(application_factory):
    app = application_factory()
    assert app.sessions.accept("owner", {"client_id": str(uuid.uuid4())})
    app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    return app


class FixtureSupervisor:
    def __init__(self):
        self.last_record_id = None
        self.entered = asyncio.Event()

    async def run(self, bootstrap, stop, authorize, **kwargs):
        self.entered.set()
        while not stop.is_set():
            try:
                authorize()
            except ServiceError:
                stop.set()
            await asyncio.sleep(0)
        return {"ok": True, "mode": "offline_fixture", "id": None,
                "state": "interrupted", "code": "owner_stopped"}


async def start_fixture(app):
    supervisor = FixtureSupervisor()
    app.call_lab.supervisor_factory = lambda: supervisor
    identifier = uuid.uuid4()
    app.call_lab.start("owner", identifier)
    await asyncio.wait_for(supervisor.entered.wait(), 1)
    return supervisor, identifier


@pytest.mark.asyncio
async def test_metadata_is_owner_only_strict_and_does_not_start_worker(owner_app):
    app = owner_app
    app.call_lab.supervisor_factory = lambda: pytest.fail("Metadata must not construct a worker")
    for role in ("resident", "workspace"):
        app.sessions.accept(role, {"client_id": app.sessions.local_owner, "role": role})
        assert not (await app.call_lab_transport.state(role, {}))["ok"]
    app.sessions.accept("foreign", {"client_id": str(uuid.uuid4())})
    assert not (await app.call_lab_transport.state("foreign", {}))["ok"]
    assert not (await app.call_lab_transport.state("missing", {}))["ok"]
    assert not (await app.call_lab_transport.state("owner", {"live": True}))["ok"]
    result = await app.call_lab_transport.state("owner", {})
    assert result["ok"] and not result["live_enabled"] and not result["physical_verified"]
    LabState.model_validate({key: value for key, value in result.items() if key != "ok"})
    assert app.call_lab.active is None and not app.resources.reservations


@pytest.mark.parametrize("configured", [True, False])
def test_voice_presence_is_local_and_never_arms_a_call(owner_app, monkeypatch, configured):
    import calls.lab as module

    def local():
        if not configured:
            raise ServiceError("call_local_setup", "synthetic missing local components")
        return "synthetic local model path"

    monkeypatch.setattr(module, "local_ready", local)
    monkeypatch.setenv("GEMINI_API_KEY", "INERT_NOT_A_KEY")
    monkeypatch.setenv("INARA_CALL_MODEL", "INERT_CLOUD_MODEL")
    value = owner_app.call_lab.state("owner")
    assert value["voice_configured"] is configured
    assert value["live_enabled"] is False and value["physical_verified"] is False
    assert owner_app.call_lab.active is None


@pytest.mark.asyncio
async def test_stop_is_origin_bound_and_duplicate_check_never_replays(owner_app):
    app = owner_app
    supervisor, identifier = await start_fixture(app)
    app.sessions.accept("second", {"client_id": app.sessions.local_owner})
    result = await app.call_lab_transport.stop("second", {"id": str(identifier)})
    assert result["code"] == "call_lab_origin"
    assert app.call_lab.active is not None
    result = await app.call_lab_transport.stop("owner", {"id": str(identifier)})
    assert result["ok"] and result["runs"][0]["state"] == "interrupted"
    assert app.call_lab.active is None and not app.resources.reservations
    result = await app.call_lab_transport.check("owner", {"id": str(identifier)})
    assert result["code"] == "call_lab_duplicate"
    assert supervisor.entered.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["project", "lock", "gaming", "disconnect", "close"])
async def test_scope_and_lifecycle_changes_stop_owned_check(owner_app, cause):
    app = owner_app
    await start_fixture(app)
    task = app.call_lab.active["task"]
    if cause == "project":
        app.projects.create_project("different")
        app.projects.switch_project("different")
    elif cause == "lock":
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    elif cause == "gaming":
        app.resources.select("gaming")
    elif cause == "disconnect":
        await app.disconnect("owner")
    else:
        await app.close()
    await asyncio.wait_for(asyncio.shield(task), 1)
    assert app.call_lab.active is None and not app.resources.reservations


@pytest.mark.asyncio
async def test_gaming_blocks_launch_and_unknown_live_arguments_are_rejected(owner_app):
    app = owner_app
    app.resources.select("gaming")
    result = await app.call_lab_transport.check("owner", {"id": str(uuid.uuid4())})
    assert result["code"] == "resource_policy"
    app.resources.select("chat")
    result = await app.call_lab_transport.check("owner", {"id": str(uuid.uuid4()), "mode": "live"})
    assert result["code"] == "invalid_arguments" and app.call_lab.active is None


def test_records_cannot_cross_project_or_owner_scope(owner_app):
    app = owner_app
    owner, project = app.call_lab.context("owner")
    records = CallRecords(Database(app.call_lab.records_directory(owner, project)))
    observation = asyncio.run(FixtureControl().observe())
    key, record = records.claim("sim", observation)
    record.update(state="completed", code=None, transcript=[{"role": "caller", "text": "PRIVATE FIXTURE"}])
    records.finish(key, record)
    identifier = str(uuid.uuid4())
    with app.database.transaction() as db:
        scope, book = app.call_lab.load(db, owner, project)
        book["runs"].append({"id": identifier, "mode": "offline_fixture", "state": "completed", "code": None,
                             "started_at": 1, "finished_at": 2, "record_id": record["id"]})
        app.database.put(db, app.call_lab.kind, scope, book)
    assert app.call_lab.record("owner", identifier)["transcript"][0]["text"] == "PRIVATE FIXTURE"
    app.projects.create_project("different")
    app.projects.switch_project("different")
    with pytest.raises(ServiceError, match="No finished"):
        app.call_lab.record("owner", identifier)
    assert app.call_lab.state("owner")["runs"] == []


@pytest.mark.asyncio
async def test_supervisor_always_closes_process_and_rejects_missing_receipt():
    processes = []
    class Process:
        def __init__(self, executable, entrypoint, bootstrap, cwd):
            self.closed = False
            processes.append(self)
        def alive(self):
            return False
        def exit_code(self):
            return 1
        def close(self):
            self.closed = True
    supervisor = CallSupervisor(Process)
    with pytest.raises(ServiceError, match="without a valid"):
        await supervisor.run({"mode": "offline_fixture"}, asyncio.Event())
    assert processes[0].closed and not supervisor.running


@pytest.mark.asyncio
async def test_supervisor_hard_stall_and_cancel_close_the_owned_job():
    processes = []
    class Process:
        def __init__(self, *args):
            self.closed = False
            processes.append(self)
        def alive(self):
            return True
        def close(self):
            self.closed = True
    supervisor = CallSupervisor(Process, heartbeat_timeout=0.01)
    with pytest.raises(ServiceError, match="stopped responding"):
        await supervisor.run({"mode": "offline_fixture"}, asyncio.Event())
    assert processes[-1].closed and not supervisor.running
    supervisor = CallSupervisor(Process, stop_timeout=0.01)
    task = asyncio.create_task(supervisor.run({"mode": "offline_fixture"}, asyncio.Event()))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[-1].closed and not supervisor.running


@pytest.mark.asyncio
async def test_supervisor_accepts_only_matching_mode_and_bounded_result():
    class Process:
        def __init__(self, executable, entrypoint, bootstrap, cwd):
            self.closed = False
            Path(bootstrap["directory"], "result.json").write_text(json.dumps({"ok": True, "mode": "live", "state": "completed"}))
        def alive(self):
            return False
        def exit_code(self):
            return 0
        def close(self):
            self.closed = True
    with pytest.raises(ServiceError, match="wrong diagnostic"):
        await CallSupervisor(Process).run({"mode": "offline_fixture"}, asyncio.Event())
