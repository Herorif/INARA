"""Direct and model policy parity for the first R2b feature group."""

import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from core.event_bus import Event, Events, event_owner
from services.local_actions import ACTION_MODELS
from services.tools import ServiceError


VALID = {
    "launch_app": {"name": "calculator"},
    "take_screenshot": {"prompt": "describe"},
    "read_clipboard": {},
    "get_system_info": {},
    "list_all_devices": {},
    "control_device": {"device_id": "light.office", "action": "turn_on"},
    "stop_watching": {"watch_id": "desk"},
}
INVALID = {
    "launch_app": {"name": 2},
    "take_screenshot": {"prompt": ["x"]},
    "read_clipboard": {"text": "inject"},
    "get_system_info": [],
    "list_all_devices": {"unexpected": True},
    "control_device": {"device_id": "x", "action": "set", "brightness": True},
    "stop_watching": {"watch_id": "x", "principal": "other"},
}


@pytest.fixture
def local_runtime(application_factory):
    app = application_factory()
    app.sessions.principals.update(
        {"client": "owner", "second": "other", "tray": "owner", "control": "owner"}
    )
    app.sessions.roles.update(
        {"client": "renderer", "second": "renderer", "tray": "resident", "control": "workspace"}
    )
    fake = SimpleNamespace(
        handle_tool_call=AsyncMock(
            return_value=SimpleNamespace(success=True, message="done", data={"value": "result"})
        )
    )
    app.local_actions.desktop = app.local_actions.devices = app.local_actions.vision = fake
    app.local_actions.vision_loop = SimpleNamespace(list_watches=lambda: [])
    app.settings["tool_permissions"].update({name: False for name in VALID})
    return app, fake


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "locked"])
async def test_direct_route_requires_authenticated_renderer(local_runtime, name, sid):
    app, fake = local_runtime
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
    await app.sio.handlers["/"][name](sid, VALID[name])
    fake.handle_tool_call.assert_not_called()
    assert app.sio.emit.await_args.args[1]["code"] == "authentication_required"
    assert app.sio.emit.await_args.kwargs["room"] == sid


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
async def test_direct_and_model_denial_before_any_adapter(local_runtime, name):
    app, fake = local_runtime
    app.settings["tool_permissions"][name] = "deny"
    await app.sio.handlers["/"][name]("client", VALID[name])
    assert app.sio.emit.await_args.args[1]["code"] == "permission_denied"
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", name, VALID[name], app.sessions.context("client").tools()
        )
    assert error.value.code == "permission_denied"
    fake.handle_tool_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
async def test_malformed_direct_and_model_arguments_do_not_reach_adapter(local_runtime, name):
    app, fake = local_runtime
    await app.sio.handlers["/"][name]("client", INVALID[name])
    assert app.sio.emit.await_args.args[1]["code"] == "invalid_arguments"
    assert app.sio.emit.await_args.kwargs["room"] == "client"
    with pytest.raises(ValidationError):
        await app.dispatcher.dispatch(
            "owner", name, INVALID[name], app.sessions.context("client").tools()
        )
    fake.handle_tool_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
async def test_valid_direct_action_preserves_scoped_contract(local_runtime, name):
    app, fake = local_runtime
    await app.sio.handlers["/"][name]("client", VALID[name])
    fake.handle_tool_call.assert_awaited_once_with(name, VALID[name])
    assert all(call.kwargs["room"] == "client" for call in app.sio.emit.await_args_list)
    assert not app.local_transport.running and event_owner.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"id": "x", "confirmed": "false"},
        {"id": "x", "confirmed": 1},
        {"id": "x", "confirmed": True, "owner": "other"},
    ],
)
async def test_confirmation_is_strict_not_truthy(local_runtime, payload):
    app, _ = local_runtime
    assert await app.local_transport.validate_confirmation("client", payload) is None
    assert app.sio.emit.await_args.args[1]["code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_approval_owner_binding_and_permission_recheck(local_runtime):
    app, fake = local_runtime
    app.settings["tool_permissions"]["launch_app"] = True
    requested = asyncio.Event()
    captured = {}

    async def emit(name, data, room=None):
        if name == "tool_confirmation_request":
            captured.update(data)
            requested.set()

    app.sio.emit = emit
    task = asyncio.create_task(app.local_transport.launch_app("client", VALID["launch_app"]))
    await asyncio.wait_for(requested.wait(), 1)
    assert not app.dispatcher.resolve("other", captured["id"], True)
    assert not app.dispatcher.resolve("owner", captured["id"], "true")
    app.settings["tool_permissions"]["launch_app"] = "deny"
    assert app.dispatcher.resolve("owner", captured["id"], True)
    await task
    fake.handle_tool_call.assert_not_called()
    assert not app.dispatcher.pending


@pytest.mark.asyncio
async def test_expiry_and_disconnect_do_not_execute_or_replay(local_runtime):
    app, fake = local_runtime
    app.settings["tool_permissions"]["launch_app"] = True
    app.dispatcher.timeout = 0.01
    await app.local_transport.launch_app("client", VALID["launch_app"])
    assert app.sio.emit.await_args.args[1]["code"] == "approval_expired"
    app.dispatcher.timeout = 60
    requested = asyncio.Event()
    ids = []

    async def emit(name, data, room=None):
        if name == "tool_confirmation_request":
            ids.append(data["id"])
            requested.set()

    app.sio.emit = emit
    task = asyncio.create_task(app.local_transport.launch_app("client", VALID["launch_app"]))
    await asyncio.wait_for(requested.wait(), 1)
    # Another owner channel remains; only the originating request is cancelled.
    await app.disconnect("client")
    assert task.cancelled() and not app.dispatcher.pending and not app.local_transport.running
    assert not app.dispatcher.resolve("owner", ids[0], True)
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    await asyncio.sleep(0)
    fake.handle_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_execution_timeout_and_error_sanitization(local_runtime):
    app, fake = local_runtime
    app.dispatcher.tools["read_clipboard"].execution_timeout = 0.01
    started = asyncio.Event()

    async def slow(*args):
        started.set()
        await asyncio.sleep(60)

    fake.handle_tool_call.side_effect = slow
    await app.local_transport.read_clipboard("client")
    assert started.is_set()
    assert app.sio.emit.await_args.args[1]["code"] == "action_timeout"
    assert not app.local_transport.running and event_owner.get() is None
    fake.handle_tool_call.side_effect = RuntimeError("secret API key and clipboard contents")
    await app.local_transport.read_clipboard("client")
    assert app.sio.emit.await_args.args[1]["code"] == "action_failed"
    assert "secret" not in str(app.sio.emit.await_args)


@pytest.mark.asyncio
async def test_agent_emit_nowait_events_capture_owner_before_scope_resets(local_runtime):
    app, fake = local_runtime
    events = []

    def emit_nowait(event):
        events.append(event)

    # Exercise the real Event stamping; delayed delivery occurs after adapter scope resets.
    async def produce(name, args):
        emit_nowait(Event(Events.DEVICE_LIST, {"devices": [event_owner.get()]}))
        return SimpleNamespace(success=True, message="listed", data={})

    fake.handle_tool_call.side_effect = produce
    await app.local_transport.list_all_devices("client")
    await app.local_transport.list_all_devices("second")
    assert event_owner.get() is None
    for event in events:
        await app.delivery.bridge_legacy(event)
    calls = app.sio.emit.await_args_list
    assert [(c.args[1]["devices"], c.kwargs["room"]) for c in calls] == [
        (["owner"], "client"),
        (["other"], "second"),
    ]
    app.sessions.principals.pop("client")
    app.sio.emit.reset_mock()
    await app.delivery.bridge_legacy(events[0])
    app.sio.emit.assert_not_called()


def test_matrix_covers_registered_routes_and_shared_tools():
    import server

    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text()
    )
    assert set(matrix["socket_routes"]) == set(server.sio.handlers["/"])
    assert set(matrix["shared_tools"]) == set(server.dispatcher.tools)
    for name, spec in server.dispatcher.tools.items():
        assert matrix["shared_tools"][name]["schema"] == spec.arguments.__name__
    from fastapi.routing import APIRoute

    assert set(matrix["http_routes"]) == {
        route.path for route in server.app.routes if isinstance(route, APIRoute)
    }
    for item in matrix["socket_routes"].values():
        assert all(
            item.get(key)
            for key in (
                "schema",
                "caller",
                "context",
                "effects",
                "policy",
                "response",
                "lifetime",
                "replacement",
                "status",
            )
        )
    # Voice declarations remain separately inventoried, not mistaken for migrated shared tools.
    tree = ast.parse((Path(__file__).resolve().parents[1] / "backend/tools.py").read_text())
    declared = {
        value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == "name" and isinstance(value, ast.Constant)
    }
    assert declared == set(matrix["legacy_voice_declarations"])
    from services.voice import VOICE_TARGETS
    assert set(matrix["voice_declarations"]) == set(VOICE_TARGETS)
    for source, target in VOICE_TARGETS.items():
        assert matrix["voice_declarations"][source]["target"] == target
        assert matrix["voice_declarations"][source]["schema"] == server.dispatcher.tools[target].arguments.__name__
    assert set(ACTION_MODELS).issubset(matrix["shared_tools"])


@pytest.mark.asyncio
async def test_approved_direct_action_executes_once(local_runtime):
    app, fake = local_runtime
    app.settings["tool_permissions"]["control_device"] = True

    async def approve_event(event, data, room=None):
        if event == "tool_confirmation_request":
            checked = await app.local_transport.validate_confirmation(
                room, {"id": data["id"], "confirmed": True}
            )
            assert checked
            assert app.dispatcher.resolve("owner", checked["id"], checked["confirmed"])
            assert not app.dispatcher.resolve("owner", checked["id"], checked["confirmed"])

    app.sio.emit = approve_event
    await app.local_transport.control_device("client", VALID["control_device"])
    fake.handle_tool_call.assert_awaited_once()
    assert not app.dispatcher.pending


@pytest.mark.asyncio
async def test_blank_name_is_rejected_before_approval(local_runtime):
    app, fake = local_runtime
    app.settings["tool_permissions"]["launch_app"] = True
    await app.local_transport.launch_app("client", {"name": "   "})
    assert [call.args[0] for call in app.sio.emit.await_args_list] == ["error"]
    fake.handle_tool_call.assert_not_called()
