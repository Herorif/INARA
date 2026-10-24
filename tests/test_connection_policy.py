"""Scoped startup/face lifecycle using injected workers, never a real camera."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from services.face_worker import FaceWorker
from services.tools import ServiceError


PRIVATE = {
    "settings",
    "printer_list",
    "project_update",
    "reminder_list",
    "reminder_deliveries",
    "vision_watches",
    "auth_frame",
}


class Worker:
    def __init__(self):
        self.entered = asyncio.Event()
        self.status = self.frame = None
        self.closed = 0

    async def run(self, status, frame):
        self.status, self.frame = status, frame
        self.entered.set()
        await asyncio.Event().wait()

    async def close(self):
        self.closed += 1


@pytest.fixture
def connection(application_factory, monkeypatch):
    monkeypatch.delenv("INARA_SESSION_TOKEN", raising=False)
    app = application_factory()
    workers = []

    def create():
        worker = Worker()
        workers.append(worker)
        return worker

    app.connection.worker_factory = create
    return app, str(uuid.uuid4()), workers


@pytest.mark.asyncio
async def test_control_resident_and_foreign_connections_receive_no_private_hydration(connection):
    app, owner, _ = connection
    await app.connection.connect("control", {}, {"client_id": owner, "role": "workspace"})
    await app.connection.connect("resident", {}, {"client_id": owner, "role": "resident"})
    assert all(c.args[0] not in PRIVATE for c in app.sio.emit.await_args_list)
    count = app.sio.emit.await_count
    assert await app.connection.connect("foreign", {}, {"client_id": str(uuid.uuid4())}) is False
    assert app.sio.emit.await_count == count and "foreign" not in app.sessions.principals
    await app.connection.connect("renderer", {}, {"client_id": owner})
    assert PRIVATE - {"auth_frame"} <= {
        c.args[0] for c in app.sio.emit.await_args_list if c.kwargs["room"] == "renderer"
    }
    await app.close()


@pytest.mark.asyncio
async def test_locked_start_single_worker_unlock_hydrates_only_owner_renderers(connection):
    app, owner, workers = connection
    app.settings["face_auth_enabled"] = True
    await asyncio.gather(
        app.connection.connect("one", {}, {"client_id": owner}),
        app.connection.connect("two", {}, {"client_id": owner}),
    )
    await app.connection.connect("control", {}, {"client_id": owner, "role": "workspace"})
    assert len(workers) == 1
    await workers[0].entered.wait()
    assert not any(c.args[0] in PRIVATE for c in app.sio.emit.await_args_list)
    await workers[0].frame("fixture base64")
    frames = [c for c in app.sio.emit.await_args_list if c.args[0] == "auth_frame"]
    assert {c.kwargs["room"] for c in frames} == {"one", "two"}
    await workers[0].status(True)
    assert app.sessions.authenticated(owner)
    events = [c for c in app.sio.emit.await_args_list if c.args[0] in PRIVATE - {"auth_frame"}]
    assert {c.kwargs["room"] for c in events} == {"one", "two"}
    await app.close()
    assert workers[0].closed and app.connection.task is None


@pytest.mark.asyncio
async def test_last_renderer_disconnect_cancels_face_even_with_native_or_resident_channel(
    connection,
):
    app, owner, workers = connection
    app.settings["face_auth_enabled"] = True
    await app.connection.connect("one", {}, {"client_id": owner})
    await workers[0].entered.wait()
    await app.connection.connect("two", {}, {"client_id": owner})
    await app.connection.connect("resident", {}, {"client_id": owner, "role": "resident"})
    await app.connection.disconnect("one")
    assert not workers[0].closed
    old = workers[0]
    await app.connection.disconnect("two")
    assert old.closed and app.connection.task is None
    await app.connection.connect("new", {}, {"client_id": owner})
    await workers[1].entered.wait()
    app.sio.emit.reset_mock()
    await old.frame("late private frame")
    await old.status(True)
    assert not app.connection.authenticated
    app.sio.emit.assert_not_awaited()
    await app.close()


@pytest.mark.asyncio
async def test_resource_stop_and_resume_face_and_disabling_auth_hydrates(connection):
    app, owner, workers = connection
    app.settings["face_auth_enabled"] = True
    await app.connection.connect("client", {}, {"client_id": owner})
    await workers[0].entered.wait()
    app.resources.select("gaming")
    await app.restrict_resources()
    await app.connection.resource_changed("gaming")
    assert workers[0].closed and app.connection.task is None
    app.resources.select("chat")
    await app.connection.resource_changed("chat")
    await workers[1].entered.wait()
    app.settings["face_auth_enabled"] = False
    await app.connection.settings_changed({"face_auth_enabled": False})
    assert workers[1].closed and app.connection.task is None
    assert any(c.args[0] == "settings" for c in app.sio.emit.await_args_list)
    await app.close()


@pytest.mark.asyncio
async def test_setup_rejected_before_persisting_face_enable(connection):
    app, owner, _ = connection
    await app.connection.connect("client", {}, {"client_id": owner})

    def missing():
        raise ServiceError("face_setup_required", "Fixture setup missing")

    app.connection.check_setup = missing
    result = await app.settings_transport.update_settings("client", {"face_auth_enabled": True})
    assert result["code"] == "face_setup_required"
    assert not app.settings["face_auth_enabled"] and app.connection.task is None
    await app.close()


@pytest.mark.asyncio
async def test_native_owner_registration_before_renderer_has_no_private_early_state(connection):
    app, owner, _ = connection
    identity = SimpleNamespace(owner=None)
    app.sessions.native_desktop = SimpleNamespace(state=SimpleNamespace(identity=identity))
    await app.connection.connect("control", {}, {"client_id": owner, "role": "workspace"})
    assert not any(c.args[0] in PRIVATE for c in app.sio.emit.await_args_list)
    identity.owner = owner
    app.sessions.attach_native(owner)
    await app.connection.connect("renderer", {}, {"client_id": owner})
    assert any(
        c.args[0] == "settings" and c.kwargs["room"] == "renderer"
        for c in app.sio.emit.await_args_list
    )
    await app.close()


@pytest.mark.asyncio
async def test_face_failure_is_scoped_sanitized_and_does_not_retry_on_duplicate_connect(connection):
    app, owner, _ = connection
    app.settings["face_auth_enabled"] = True

    class Failure:
        async def run(self, *args):
            raise RuntimeError("private path or provider detail")

        async def close(self):
            pass

    starts = []

    def create():
        starts.append(True)
        return Failure()

    app.connection.worker_factory = create
    await app.connection.connect("one", {}, {"client_id": owner})
    await app.connection.task
    await app.connection.connect("two", {}, {"client_id": owner})
    assert len(starts) == 1 and not app.connection.authenticated
    errors = [c for c in app.sio.emit.await_args_list if c.args[0] == "error"]
    assert errors and "private path" not in str(errors)
    await app.close()


@pytest.mark.asyncio
async def test_owned_face_fixture_process_is_cleaned_after_result(connection):
    from resident.win32 import WorkspaceProcess

    app, _, _ = connection
    fixture = Path(__file__).parent / "fixtures/face_worker_fixture.py"
    processes = []

    def create(executable, entry, bootstrap, cwd):
        process = WorkspaceProcess(executable, fixture.resolve(), bootstrap, cwd)
        processes.append(process)
        return process

    worker = FaceWorker(app, process_factory=create, timeout=5)
    statuses, frames = [], []

    async def status(value):
        statuses.append(value)

    async def frame(value):
        frames.append(value)

    await worker.run(status, frame)
    assert statuses == [True]
    assert processes[0].process is None and worker.process is None
    assert not worker.folder.exists()


@pytest.mark.asyncio
async def test_owned_face_worker_deadline_closes_process_and_drops_partial_reports(connection):
    app, _, _ = connection
    processes = []

    class Slow:
        def __init__(self, executable, entry, bootstrap, cwd):
            self.closed = False
            processes.append(self)
            (Path(bootstrap["output"]) / "state.json").write_text("[]")

        def alive(self):
            return True

        def close(self):
            self.closed = True

    worker = FaceWorker(app, process_factory=Slow, timeout=0.01)

    async def unexpected(*args):
        pytest.fail("Partial reports must not hydrate or unlock")

    with pytest.raises(TimeoutError):
        await worker.run(unexpected, unexpected)
    assert processes[0].closed and worker.process is None


def test_face_worker_bootstrap_is_fixed_and_contains_no_provider_or_download_path():
    source = (Path(__file__).resolve().parents[1] / "backend/workers/face_worker.py").read_text()
    assert "read(4097)" in source and "reference" in source
    assert "GEMINI_API_KEY" not in source and "urlretrieve" not in source
