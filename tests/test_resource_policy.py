from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from services.resources import ResourceGovernor
from services.tools import ServiceError


def test_resource_policy_blocks_heavy_activation_in_resident_and_gaming():
    policy = ResourceGovernor()
    for state in ("resident", "gaming"):
        policy.select(state)
        with pytest.raises(ServiceError):
            policy.require_heavy()
    policy.select("chat")
    policy.require_heavy()
    assert policy.state == "studio"


@pytest.mark.asyncio
async def test_gaming_blocks_legacy_camera_before_audio_or_worker_access(monkeypatch):
    import server

    policy = ResourceGovernor()
    policy.select("gaming")
    monkeypatch.setattr(server, "resource_governor", policy)
    emit = AsyncMock()
    monkeypatch.setattr(server.sio, "emit", emit)
    await server.video_frame("client", {"image": "fake-frame"})
    assert emit.call_args.args[1]["code"] == "resource_policy"


@pytest.mark.asyncio
async def test_reminder_prefers_renderer_then_resident_on_close(tmp_path, monkeypatch, application_factory):
    runtime = application_factory()
    from core.reminder_store import ReminderStore

    store = ReminderStore(tmp_path)
    store.add_reminder("test reminder", 1)
    runtime.delivery.reminders = runtime.reminder_transport.store = store
    runtime.sessions.principals.update({"tray": "owner", "window": "owner"})
    runtime.sessions.roles.update({"tray": "resident", "window": "renderer"})
    runtime.resources.select("studio")
    monkeypatch.setattr(runtime.dispatcher, "authenticated", lambda _: True)
    emit = AsyncMock()
    monkeypatch.setattr(runtime.sio, "emit", emit)
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: 100)
    await runtime.delivery.deliver_reminders_once()
    first = emit.call_args.args[1]
    assert emit.call_args.kwargs["room"] == "window"
    runtime.sessions.principals.pop("window")
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: 131)
    await runtime.delivery.deliver_reminders_once()
    assert emit.call_args.kwargs["room"] == "tray"
    assert emit.call_args.args[1]["delivery_id"] == first["delivery_id"]


@pytest.mark.asyncio
async def test_shutdown_requires_connected_identity_and_cleans_before_exit(monkeypatch):
    import server

    cleanup = AsyncMock()
    instance = SimpleNamespace(should_exit=False)
    monkeypatch.setattr(server, "uvicorn_server", instance)
    monkeypatch.setattr(server, "close_services", cleanup)
    monkeypatch.setattr(server, "client_principals", {"owner": "identity"})
    await server.shutdown("unknown")
    cleanup.assert_not_called()
    await server.shutdown("owner")
    cleanup.assert_awaited_once()
    assert instance.should_exit


@pytest.mark.asyncio
async def test_direct_reminder_creation_needs_no_ai_configuration(tmp_path, monkeypatch, application_factory):
    runtime = application_factory()
    from agents.scheduler_agent import SchedulerAgent
    from core.event_bus import EventBus
    from core.reminder_store import ReminderStore
    from services.scheduler_tools import register_scheduler_tools
    from services.tools import ToolDispatcher

    store = ReminderStore(tmp_path)
    dispatcher = ToolDispatcher(lambda: {"create_reminder": False})
    register_scheduler_tools(dispatcher, SchedulerAgent(EventBus(), store), store)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    runtime.reminder_transport.dispatcher = dispatcher
    runtime.sessions.principals["client"] = "owner"
    runtime.delivery.reminders = runtime.reminder_transport.store = store
    monkeypatch.setattr(runtime.sio, "emit", AsyncMock())
    await runtime.reminder_transport.create_reminder(
        "client",
        {
            "task": "offline local reminder",
            "when": "2099-01-01T09:00",
            "timezone": "Asia/Kuala_Lumpur",
        },
    )
    assert store.list_reminders()[0].task == "offline local reminder"
