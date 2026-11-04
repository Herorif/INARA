"""Lifecycle and error hardening: bus delivery, task ownership, eviction, cleanup
isolation, cancellation propagation and redacted diagnostics. No live model or media."""

import asyncio
import logging
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.event_bus import Event, EventBus
from llm.base import LLMResponse
from services import conversation as conversation_module
from services import log as log_module
from services.cancellation import acknowledge_stop, request_stop
from services.conversation import ConversationRequest, ConversationService
from services.sessions import SessionStore
from services.storage import Database
from services.tools import ServiceError
from tests.test_workspace_policy import workspace as workspace_fixture


@pytest.fixture
def workspace(application_factory):
    return workspace_fixture.__wrapped__(application_factory)


def records(caplog, text):
    return [r for r in caplog.records if text in r.getMessage()]


# --- M1 / M2: event bus -------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_failure_is_logged_and_other_handlers_still_run(caplog):
    bus, seen = EventBus(), []

    async def broken(event):
        raise RuntimeError("handler exploded")

    async def healthy(event):
        seen.append(event.type)

    bus.on("demo.event", broken)
    bus.on("demo.event", healthy)
    with caplog.at_level(logging.ERROR, logger="inara"):
        await bus.emit(Event("demo.event"))
    assert seen == ["demo.event"]
    failures = records(caplog, "Event demo.event handler")
    assert len(failures) == 1 and "broken" in failures[0].getMessage()
    assert failures[0].exc_info[0] is RuntimeError


@pytest.mark.asyncio
async def test_background_emits_are_referenced_until_done_and_failures_logged(caplog):
    bus, release = EventBus(), asyncio.Event()

    async def slow(event):
        await release.wait()

    bus.on("demo.slow", slow)
    bus.emit_nowait(Event("demo.slow"))
    assert len(bus.pending) == 1  # strongly referenced while in flight
    release.set()
    await asyncio.gather(*bus.pending)
    await asyncio.sleep(0)
    assert not bus.pending


@pytest.mark.asyncio
async def test_drain_cancels_deliveries_that_outlast_shutdown(caplog):
    bus, cancelled = EventBus(), asyncio.Event()

    async def stuck(event):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    bus.on("demo.stuck", stuck)
    bus.emit_nowait(Event("demo.stuck"))
    await asyncio.sleep(0)
    with caplog.at_level(logging.WARNING, logger="inara"):
        await bus.drain(timeout=0.05)
    assert cancelled.is_set()
    await asyncio.sleep(0)
    assert not bus.pending
    assert records(caplog, "Cancelled 1 background event")


@pytest.mark.asyncio
async def test_application_close_drains_pending_bus_tasks(application_factory):
    runtime = application_factory()
    await runtime.start()
    stopped = asyncio.Event()

    async def stuck(event):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    runtime.bus.on("demo.stuck", stuck)
    runtime.bus.emit_nowait(Event("demo.stuck"))
    await asyncio.sleep(0)
    assert runtime.bus.pending
    original = runtime.bus.drain
    runtime.bus.drain = lambda timeout=0.05: original(timeout)
    await runtime.close()
    assert stopped.is_set() and not runtime.bus.pending


# --- M3: conversation LRU eviction ---------------------------------------------------


class RecordingProvider:
    name = "fixture"

    def __init__(self):
        self.messages = []
        self.gates = {}

    async def generate(self, messages, **kwargs):
        self.messages.append([m.content for m in messages])
        gate = self.gates.get(messages[-1].content)
        if gate:
            await gate.wait()
        return LLMResponse(text="reply to " + messages[-1].content)

    async def close(self):
        pass


def conversation_service(application_factory, store=True):
    runtime = application_factory()
    provider = RecordingProvider()
    service = ConversationService(
        runtime.dispatcher,
        lambda: provider,
        store=SessionStore(runtime.database) if store else None,
    )
    return service, provider, runtime.projects.get_current_project_path()


@pytest.mark.asyncio
async def test_lru_eviction_skips_busy_conversations_and_evicted_ones_reload(
    application_factory, monkeypatch
):
    monkeypatch.setattr(conversation_module, "CONVERSATION_LIMIT", 2)
    service, provider, project = conversation_service(application_factory)
    busy, idle, fresh = (uuid.uuid4() for _ in range(3))
    provider.gates["hold"] = gate = asyncio.Event()
    held = asyncio.create_task(
        service.reply("owner", ConversationRequest(text="hold", conversation_id=busy), project)
    )
    while not provider.messages:  # noqa: ASYNC110  waits for the task under test to reach the fake
        await asyncio.sleep(0)
    await service.reply("owner", ConversationRequest(text="first", conversation_id=idle), project)
    # The busy conversation is least recently used, but in flight: the idle one goes.
    await service.reply("owner", ConversationRequest(text="new", conversation_id=fresh), project)
    assert str(busy) in service.conversations and str(idle) not in service.conversations
    gate.set()
    await held
    # The evicted conversation reloads transparently from the durable store.
    await service.reply("owner", ConversationRequest(text="again", conversation_id=idle), project)
    assert provider.messages[-1] == ["first", "reply to first", "again"]
    assert len(service.conversations) == 2


@pytest.mark.asyncio
async def test_limit_still_refuses_when_every_conversation_is_busy_or_not_durable(
    application_factory, monkeypatch
):
    monkeypatch.setattr(conversation_module, "CONVERSATION_LIMIT", 1)
    service, provider, project = conversation_service(application_factory)
    provider.gates["hold"] = gate = asyncio.Event()
    held = asyncio.create_task(
        service.reply("owner", ConversationRequest(text="hold"), project)
    )
    while not provider.messages:  # noqa: ASYNC110  waits for the task under test to reach the fake
        await asyncio.sleep(0)
    with pytest.raises(ServiceError) as error:
        await service.reply("owner", ConversationRequest(text="other"), project)
    assert error.value.code == "conversation_limit"
    gate.set()
    await held

    memory_only, _, project = conversation_service(application_factory, store=False)
    await memory_only.reply("owner", ConversationRequest(text="kept"), project)
    with pytest.raises(ServiceError) as error:
        await memory_only.reply("owner", ConversationRequest(text="other"), project)
    assert error.value.code == "conversation_limit"


# --- M4 / M5: application root -------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_removes_session_even_when_a_cleanup_raises(application_factory, caplog):
    runtime = application_factory()
    runtime.sessions.principals["one"] = "owner"
    runtime.sessions.roles["one"] = "renderer"
    runtime.task_queue.stop_sid = AsyncMock(side_effect=RuntimeError("cleanup broke"))
    runtime.call_testing.invalidate = lambda sid: (_ for _ in ()).throw(ValueError("sync broke"))
    runtime.workspace.disconnect = AsyncMock()
    runtime.cad_transport.stop_owner = AsyncMock(side_effect=OSError("owner cleanup broke"))
    runtime.image_transport.stop_owner = AsyncMock()
    with caplog.at_level(logging.ERROR, logger="inara"):
        await runtime.disconnect("one")
    assert "one" not in runtime.sessions.principals and "one" not in runtime.sessions.roles
    runtime.workspace.disconnect.assert_awaited_once_with("one")  # later cleanups still ran
    runtime.image_transport.stop_owner.assert_awaited_once_with("owner")
    logged = {r.getMessage() for r in caplog.records}
    assert {
        "Disconnect cleanup task_queue failed",
        "Disconnect cleanup call_testing failed",
        "Disconnect cleanup cad failed",
    } <= logged


def test_quality_is_owned_by_the_application_not_the_usage_transport(application_factory):
    from services.quality import QualityService
    from transport.usage import UsageTransport

    runtime = application_factory()
    assert isinstance(runtime.quality, QualityService)
    fake = SimpleNamespace(sio=SimpleNamespace(on=lambda *args, **kwargs: None))
    UsageTransport(fake)
    assert not hasattr(fake, "quality")


# --- M11: cancellation propagates ----------------------------------------------------


@pytest.mark.asyncio
async def test_deliberate_stop_is_acknowledged_but_other_cancels_are_not():
    async def worker():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not acknowledge_stop():
                raise
            return "stopped"

    stopped = asyncio.create_task(worker())
    await asyncio.sleep(0)
    request_stop(stopped)
    assert await stopped == "stopped"

    both = asyncio.create_task(worker())
    await asyncio.sleep(0)
    request_stop(both)
    both.cancel()  # e.g. shutdown on top of the owner stop
    with pytest.raises(asyncio.CancelledError):
        await both

    external = asyncio.create_task(worker())
    await asyncio.sleep(0)
    external.cancel()
    with pytest.raises(asyncio.CancelledError):
        await external


@pytest.mark.asyncio
async def test_quality_handler_propagates_external_cancellation(workspace, monkeypatch):
    import services.quality as quality_module

    entered = asyncio.Event()

    async def run():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(quality_module, "run_offline_suite", run)
    task = asyncio.create_task(workspace.sio.handlers["/"]["quality_run"]("client", {}))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not workspace.quality.running


@pytest.mark.asyncio
async def test_browser_handler_propagates_external_cancellation(workspace):
    entered = asyncio.Event()

    async def run(args):
        entered.set()
        await asyncio.Event().wait()

    workspace.browser.runner = run
    task = asyncio.create_task(
        workspace.sio.handlers["/"]["browser_inspect"]("client", {"url": "https://example.com/"})
    )
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not workspace.browser_transport.running


@pytest.mark.asyncio
async def test_task_queue_handler_propagates_external_cancellation(workspace):
    entered = asyncio.Event()

    async def run(*args):
        entered.set()
        await asyncio.Event().wait()

    workspace.task_queue.run = run
    task = asyncio.create_task(
        workspace.sio.handlers["/"]["task_queue_run"]("client", {"id": str(uuid.uuid4())})
    )
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_creative_job_cancellation_records_state_then_propagates(tmp_path):
    from services.cad import BuildRequest, CadService
    from services.resources import ResourceGovernor

    class SlowProcess:
        def __init__(self, *args):
            self.closed = False

        def alive(self):
            return not self.closed

        def close(self):
            self.closed = True

        def exit_code(self):
            return 0

    project = tmp_path / "project"
    project.mkdir()
    governor = ResourceGovernor(
        probe=lambda: {"cpu_count": 8, "ram_available_mb": 16000, "vram_mb": None}
    )
    service = CadService(Database(tmp_path / "database"), governor, process_factory=SlowProcess)
    args = BuildRequest()
    await service.start(args, {"principal": "owner", "project_path": project})
    await asyncio.sleep(0.05)
    (running,) = service.active.values()
    running["task"].cancel()
    with pytest.raises(asyncio.CancelledError):
        await running["task"]
    assert service.load("owner", project, args.request_id)["state"] == "cancelled"
    assert not service.active


@pytest.fixture
def call_app(application_factory, monkeypatch):
    app = application_factory()
    app.sessions.accept(
        "owner",
        {"token": "test-session-token", "client_id": str(uuid.uuid4())},
        "test-session-token",
    )
    app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    monkeypatch.setattr("calls.local_voice.ready", lambda: None)
    return app


class BlockingSupervisor:
    last_record_id = None

    def __init__(self):
        self.entered = asyncio.Event()

    async def run(self, bootstrap, stop, authorize, **kwargs):
        self.entered.set()
        await asyncio.Event().wait()


def run_book(service, app):
    owner, project = service.context("owner")
    with app.database.connection() as db:
        return app.database.get(db, service.kind, service.scope(owner, project))


@pytest.mark.asyncio
async def test_call_admission_cancellation_records_stop_then_propagates(call_app):
    from calls.fixture import fixture_profile

    supervisor = BlockingSupervisor()
    call_app.call_admission.supervisor_factory = lambda: supervisor
    call_app.call_admission.start(
        "owner", uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True
    )
    task = call_app.call_admission.active["task"]
    await asyncio.wait_for(supervisor.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run_book(call_app.call_admission, call_app)["runs"][-1]["code"] == "owner_stopped"
    assert call_app.call_admission.active is None and not call_app.resources.reservations


@pytest.mark.asyncio
async def test_call_lab_cancellation_records_stop_then_propagates(call_app):
    supervisor = BlockingSupervisor()
    call_app.call_lab.supervisor_factory = lambda: supervisor
    call_app.call_lab.start("owner", uuid.uuid4())
    task = call_app.call_lab.active["task"]
    await asyncio.wait_for(supervisor.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run_book(call_app.call_lab, call_app)["runs"][-1]["code"] == "call_lab_stopped"
    assert call_app.call_lab.active is None and not call_app.resources.reservations


# --- M6: redacted logging ------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-AbCdEf0123456789_xyz-QWERTY",
        "AIzaSyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv",
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "Authorization: Basic dXNlcjpwYXNz",
        "x-api-key: plainvalue123",
        "session_token=tok_9f8e7d6c",
        "'token': 'Zx81-short'",
        "QmFzZTY0IHNlY3JldCB2YWx1ZSB0aGF0IGlzIGxvbmcgZW5vdWdo1234",
    ],
)
def test_redaction_filter_masks_each_secret_shape(secret, caplog):
    logger = log_module.get_logger("tests.redaction")
    with caplog.at_level(logging.INFO, logger="inara"):
        logger.info("context %s end", secret)
    (record,) = [r for r in caplog.records if r.name == "inara.tests.redaction"]
    message = record.getMessage()
    assert log_module.MASK in message and message.startswith("context ")
    for fragment in ("AbCdEf0123", "SyA1b2C3", "eyJhbGci", "dXNlcjpw", "plainvalue123",
                     "tok_9f8e", "Zx81-short", "QmFzZTY0"):
        assert fragment not in message


def test_redaction_keeps_ordinary_text_and_masks_tracebacks(caplog):
    logger = log_module.get_logger("tests.traceback")
    assert log_module.redact("Event voice.connected handler Foo.bar failed") == (
        "Event voice.connected handler Foo.bar failed"
    )
    with caplog.at_level(logging.ERROR, logger="inara"):
        try:
            raise RuntimeError("provider said key=sk-ant-api03-leakedvalue")
        except RuntimeError:
            logger.exception("Provider call failed")
    (record,) = [r for r in caplog.records if r.name == "inara.tests.traceback"]
    assert "leakedvalue" not in record.exc_text and log_module.MASK in record.exc_text


def test_file_handler_writes_rotating_log_under_user_data_directory(tmp_path, monkeypatch):
    import io
    import logging.handlers

    monkeypatch.setenv("INARA_DATA_DIR", str(tmp_path))
    log_module.reset_logging()
    stream = io.StringIO()
    try:
        path = log_module.configure_logging(stream=stream)
        assert path == tmp_path / "logs" / "inara.log"
        assert log_module.configure_logging() == path  # configured once
        (handler,) = [
            h for h in logging.getLogger("inara").handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert handler.maxBytes == 2 * 1024 * 1024 and handler.backupCount == 3
        log_module.get_logger("tests.file").warning("written with sk-ant-api03-secretvalue")
        handler.flush()
        text = path.read_text(encoding="utf-8")
        assert "inara.tests.file" in text and "secretvalue" not in text and "[REDACTED]" in text
        assert "secretvalue" not in stream.getvalue() and "inara.tests.file" in stream.getvalue()
    finally:
        log_module.reset_logging()


# --- L5: resident host thread-to-loop calls ------------------------------------------


def test_host_thread_call_failures_are_logged(caplog):
    from resident.host import NativeHost

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        host = object.__new__(NativeHost)
        host.loop = loop

        async def broken():
            raise RuntimeError("emit failed")

        with caplog.at_level(logging.ERROR, logger="inara"):
            future = host._submit(broken(), "announce resident state")
            with pytest.raises(RuntimeError):
                future.result(2)
            done = threading.Event()
            loop.call_soon_threadsafe(done.set)
            done.wait(2)
        failures = records(caplog, "Resident core call announce resident state failed")
        assert failures and failures[0].exc_info[0] is RuntimeError
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
        loop.close()


def test_no_transport_module_still_creates_quality_as_a_side_effect():
    source = (Path(__file__).resolve().parents[1] / "backend/transport/usage.py").read_text()
    assert "QualityService(" not in source
