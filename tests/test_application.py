"""Composition/session regression contracts; isolated storage, no live model or media."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from core.event_bus import Event, Events
from llm.base import LLMResponse
from services.conversation import ConversationRequest, ConversationService
from services.sessions import SessionStore
from services.tools import ServiceError


class Provider:
    def __init__(self):
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        return LLMResponse(text="Persisted reply")

    async def close(self):
        pass


def test_import_has_no_runtime_or_server_side_effects(tmp_path):
    env = {**os.environ, "INARA_DATA_DIR": str(tmp_path / "not-created"), "PYTHONPATH": "backend"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import application,sys; "
            "assert 'server' not in sys.modules; "
            "assert not any(x in sys.modules for x in "
            "['inara','cv2','torch','pyaudio','build123d','diffusers'])",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "not-created").exists()


def test_composition_instances_have_isolated_state_and_registered_transports(application_factory):
    a, b = application_factory(), application_factory()
    a.sessions.principals["one"] = "owner"
    a.settings["tool_permissions"]["read_file"] = "deny"
    assert not b.sessions.principals
    assert "read_file" not in b.settings["tool_permissions"]
    assert a.cad.governor is a.images.governor is a.resources
    assert a.resources is not b.resources
    assert a.cad.lock is a.images.lock
    for transport in (a.conversation_transport, a.reminder_transport):
        for name in transport.events:
            assert a.sio.handlers["/"][name] == getattr(transport, name)
    assert a.sio.handlers["/"]["cad_submit"]
    assert a.sio.handlers["/"]["image_submit"]


@pytest.mark.parametrize(
    "auth",
    [
        {},
        {"token": "wrong"},
        {"token": "\u2603"},
        {"token": "secret", "client_id": "broken"},
        {"token": "secret", "client_id": [1]},
    ],
)
def test_rejected_handshake_never_registers_a_channel(application_factory, auth):
    runtime = application_factory()
    assert runtime.sessions.accept("untrusted", auth, "secret") is False
    assert not runtime.sessions.principals and not runtime.sessions.roles


def test_native_owner_roles_and_project_snapshot(application_factory):
    runtime = application_factory()
    owner = str(uuid.uuid4())
    runtime.sessions.native_desktop = SimpleNamespace(
        state=SimpleNamespace(identity=SimpleNamespace(owner=owner))
    )
    assert not runtime.sessions.accept(
        "other", {"client_id": str(uuid.uuid4()), "token": "secret"}, "secret"
    )
    assert runtime.sessions.accept("renderer", {"client_id": owner, "token": "secret"}, "secret")
    assert runtime.sessions.accept(
        "control", {"client_id": owner, "token": "secret", "role": "workspace"}, "secret"
    )
    context = runtime.sessions.context("renderer", renderer=True)
    runtime.projects.create_project("Second")
    runtime.projects.switch_project("Second")
    assert context.project == "temp" and context.project_path.name == "temp"
    assert runtime.sessions.context("renderer").project == "Second"
    with pytest.raises(ServiceError):
        runtime.sessions.context("control", renderer=True)
    runtime.sessions.attach_native(owner)
    assert runtime.sessions.roles["native-resident"] == "resident"
    assert runtime.sessions.authenticated(owner)
    runtime.settings["face_auth_enabled"] = True
    assert not runtime.sessions.authenticated(owner)


@pytest.mark.asyncio
async def test_job_delivery_is_owner_renderer_scoped(application_factory):
    runtime = application_factory()
    runtime.sessions.principals.update(
        {"one": "owner", "two": "owner", "tray": "owner", "other": "intruder"}
    )
    runtime.sessions.roles.update(
        {"one": "renderer", "two": "workspace", "tray": "resident", "other": "renderer"}
    )
    for event in ("cad_job", "image_job"):
        await runtime.delivery.publish_job(event, "owner", {"state": "running"})
    assert [call.kwargs["room"] for call in runtime.sio.emit.await_args_list] == ["one", "one"]


@pytest.mark.asyncio
async def test_request_captures_project_before_processing_emit(application_factory):
    runtime = application_factory()
    runtime.sessions.principals["client"] = "owner"
    original = runtime.projects.get_current_project_path().resolve()
    runtime.projects.create_project("Second")
    provider = Provider()
    service = ConversationService(
        runtime.dispatcher, lambda: provider, store=SessionStore(runtime.database)
    )
    runtime.conversation_transport.service = service

    async def emit(event, *args, **kwargs):
        if event == "text_status":
            runtime.projects.switch_project("Second")

    runtime.sio.emit = emit
    request = ConversationRequest(text="hello")
    await runtime.conversation_transport.user_input("client", request.model_dump(mode="json"))
    assert service.conversations[str(request.conversation_id)].project == str(original)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_reconnect_restore_duplicate_and_foreign_project_without_replay(application_factory):
    runtime = application_factory()
    provider = Provider()
    runtime.conversation_transport.service = ConversationService(
        runtime.dispatcher, lambda: provider, store=SessionStore(runtime.database)
    )
    owner = str(uuid.uuid4())
    runtime.sessions.accept("first", {"client_id": owner})
    request = ConversationRequest(text="hello")
    payload = request.model_dump(mode="json")
    await runtime.conversation_transport.user_input("first", payload)
    await runtime.disconnect("first")
    runtime.sessions.accept("second", {"client_id": owner})
    # Recreate service to exercise the durable ledger, not just its in-memory cache.
    runtime.conversation_transport.service = ConversationService(
        runtime.dispatcher, lambda: provider, store=SessionStore(runtime.database)
    )
    await runtime.conversation_transport.user_input("second", payload)
    await runtime.conversation_transport.resume_conversation(
        "second", {"conversation_id": str(request.conversation_id)}
    )
    assert provider.calls == 1
    assert runtime.sio.emit.await_args.args[0] == "conversation_restored"
    assert runtime.sio.emit.await_args.kwargs["room"] == "second"
    runtime.sessions.accept("intruder", {"client_id": str(uuid.uuid4())})
    await runtime.conversation_transport.resume_conversation(
        "intruder", {"conversation_id": str(request.conversation_id)}
    )
    assert runtime.sio.emit.await_args.args[0] == "conversation_restore_failed"
    runtime.projects.create_project("Second")
    runtime.projects.switch_project("Second")
    await runtime.conversation_transport.user_input("second", payload)
    errors = [c for c in runtime.sio.emit.await_args_list if c.args[0] == "error"]
    assert errors[-1].args[1]["code"] == "conversation_scope"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_disconnect_preserves_other_channels_and_cancels_last_renderer(application_factory):
    runtime = application_factory()
    runtime.sessions.principals.update({"one": "owner", "two": "owner", "control": "owner"})
    runtime.sessions.roles.update({"one": "renderer", "two": "renderer", "control": "workspace"})
    runtime.cad_transport.stop_owner = AsyncMock()
    runtime.image_transport.stop_owner = AsyncMock()
    future = asyncio.get_running_loop().create_future()
    runtime.dispatcher.pending["approval"] = ("owner", future)
    await runtime.disconnect("control")
    await runtime.disconnect("one")
    assert not future.done()
    runtime.cad_transport.stop_owner.assert_not_called()
    await runtime.disconnect("two")
    runtime.cad_transport.stop_owner.assert_awaited_once_with("owner")
    runtime.image_transport.stop_owner.assert_awaited_once_with("owner")
    assert future.result() is False


@pytest.mark.asyncio
async def test_lifetime_restarts_without_duplicate_pollers_or_bus_delivery(application_factory):
    runtime = application_factory()

    async def poll():
        await asyncio.sleep(3600)

    runtime.delivery.poll_reminders = poll
    for _ in range(2):
        await runtime.start()
        tasks = tuple(runtime.tasks)
        await runtime.start()
        assert tuple(runtime.tasks) == tasks and len(tasks) == 1
        await runtime.bus.emit(Event(Events.VISION_ALERT, {"message": "local legacy event"}))
        await runtime.close()
        assert all(task.done() for task in tasks) and not runtime.tasks
        calls = runtime.sio.emit.await_count
        await runtime.bus.emit(Event(Events.VISION_ALERT, {}))
        assert runtime.sio.emit.await_count == calls
    assert runtime.sio.emit.await_count == 0  # Unstamped events stay internal.


@pytest.mark.asyncio
async def test_cleanup_failure_still_stops_other_owners_and_unsubscribes(application_factory):
    runtime = application_factory()
    runtime.workspace.close = AsyncMock()
    await runtime.start()
    tasks = tuple(runtime.tasks)
    runtime.cad_transport.close = AsyncMock(side_effect=RuntimeError("test cleanup failure"))
    runtime.image_transport.close = AsyncMock()
    with pytest.raises(RuntimeError, match="test cleanup failure"):
        await runtime.close()
    runtime.image_transport.close.assert_awaited_once()
    runtime.workspace.close.assert_awaited_once()
    assert not runtime.started and not runtime.tasks and all(task.done() for task in tasks)
    await runtime.bus.emit(Event(Events.VISION_ALERT, {}))
    runtime.sio.emit.assert_not_called()


@pytest.mark.asyncio
async def test_failed_start_rolls_back_subscription_and_poller(application_factory):
    def fail():
        raise RuntimeError("test startup failure")

    runtime = application_factory(startup_summary=fail)
    with pytest.raises(RuntimeError, match="test startup failure"):
        await runtime.start()
    assert not runtime.started and not runtime.tasks
    await runtime.bus.emit(Event(Events.VISION_ALERT, {}))
    runtime.sio.emit.assert_not_called()
