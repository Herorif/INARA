"""Voice/direct/typed schema and policy parity, with no audio/provider imports."""

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.event_bus import Event, Events
from services.voice import VoiceBridge, VOICE_TARGETS


VALID = {
    "generate_cad": {"prompt": "box"},
    "generate_cad_prototype": {"prompt": "box"},
    "run_web_agent": {"prompt": "fixture"},
    "create_project": {"name": "Second"},
    "switch_project": {"name": "temp"},
    "list_projects": {},
    "list_smart_devices": {},
    "control_light": {"target": "127.0.0.2", "action": "turn_on"},
    "discover_printers": {},
    "print_stl": {"printer": "fixture"},
    "get_print_status": {"printer": "fixture"},
    "iterate_cad": {"prompt": "wider"},
    "write_file": {"path": "note.txt", "content": "fixture"},
    "read_directory": {},
    "read_file": {"path": "note.txt"},
    "create_reminder": {"task": "fixture", "when": "in 10 minutes"},
    "list_reminders": {},
    "cancel_reminder": {"reminder_id": "fixture"},
    "snooze_reminder": {"reminder_id": "fixture", "minutes": 5},
    "create_routine": {"name": "fixture", "trigger": "manual", "actions": "check status"},
    "list_routines": {},
    "get_system_info": {},
    "launch_app": {"name": "fixture"},
    "list_running_apps": {},
    "focus_window": {"name": "fixture"},
    "take_screenshot": {},
    "search_files": {"query": "*.txt"},
    "read_clipboard": {},
    "write_clipboard": {"text": "fixture"},
    "describe_camera": {},
    "detect_presence": {},
    "watch_for": {"description": "fixture"},
    "stop_watching": {"watch_id": "fixture"},
    "list_watches": {},
    "list_all_devices": {},
    "control_device": {"device_id": "light.fixture", "action": "turn_on"},
    "get_device_state": {"device_id": "light.fixture"},
}


@pytest.fixture
def voice(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer"})
    app.sessions.local_owner = "owner"
    binding = {
        "owner": "owner",
        "sid": "client",
        "project_path": app.projects.get_current_project_path().resolve(),
    }
    app.workspace.binding = binding
    bridge = VoiceBridge(app, binding)
    app.workspace.voice_bridge = bridge
    for name in app.dispatcher.tools:
        app.settings["tool_permissions"][name] = False
    fake = SimpleNamespace(
        handle_tool_call=AsyncMock(
            return_value=SimpleNamespace(success=True, message="fixture", data={})
        )
    )
    app.desktop = app.devices = app.vision = app.scheduler = fake
    app.local_actions.desktop = app.local_actions.devices = app.local_actions.vision = fake
    return app, bridge, fake


def test_every_voice_name_is_mapped_and_sdk_accepts_generated_shared_schemas(voice):
    from google.genai import types

    app, bridge, _ = voice
    assert set(VALID) == set(VOICE_TARGETS)
    config = types.LiveConnectConfig(tools=[{"function_declarations": bridge.schemas()}])
    assert len(config.tools[0].function_declarations) == 37
    for source, target in VOICE_TARGETS.items():
        assert target in app.dispatcher.tools
        from services.tools import inline_tool_schema

        assert next(s for s in bridge.schemas() if s["name"] == source)[
            "parameters"
        ] == inline_tool_schema(app.dispatcher.tools[target].arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
async def test_all_voice_calls_use_shared_canonical_deny_and_validate_arguments(voice, name):
    app, bridge, fake = voice
    target = VOICE_TARGETS[name]
    spec = app.dispatcher.tools[target]
    app.settings["tool_permissions"][spec.permission or target] = "deny"
    assert (await bridge.call(name, VALID[name]))["error"] == "permission_denied"
    assert (await bridge.call(name, {**VALID[name], "principal": "intruder"}))[
        "error"
    ] == "invalid_arguments"
    fake.handle_tool_call.assert_not_called()
    assert not app.dispatcher.pending


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
@pytest.mark.parametrize("state", ["locked", "stopped", "wrong_role", "gaming"])
async def test_every_voice_tool_rechecks_session_owner_role_and_resources(voice, name, state):
    app, bridge, fake = voice
    if state == "locked":
        app.settings["face_auth_enabled"] = True
    elif state == "stopped":
        app.workspace.binding = None
    elif state == "wrong_role":
        app.sessions.roles["client"] = "resident"
    else:
        app.resources.select("gaming")
    assert "error" in await bridge.call(name, VALID[name])
    fake.handle_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_voice_and_typed_paths_write_same_validated_snapshot_and_reject_escape(voice):
    app, bridge, _ = voice
    root = app.projects.get_current_project_path().resolve()
    (root / "keep.txt").write_text("keep")
    app.projects.create_project("Other")
    app.projects.switch_project("Other")
    assert not (await bridge.call("write_file", VALID["write_file"])).get("error")
    assert (root / "note.txt").read_text() == "fixture"
    result = await app.dispatcher.dispatch(
        "owner", "read_file", {"path": "note.txt"}, {"project_path": root}
    )
    assert result["text"] == "fixture"
    assert (await bridge.call("write_file", {"path": "../escape", "content": "x"}))[
        "error"
    ] == "path_denied"
    listing = await bridge.call("read_directory", {})
    assert "keep.txt" in listing["paths"]
    assert not (await bridge.call("search_files", {"query": "*.txt"})).get("error")


@pytest.mark.asyncio
async def test_voice_approval_is_shared_owner_bound_and_stop_cancels_it(voice):
    app, bridge, fake = voice
    app.settings["tool_permissions"]["launch_app"] = True
    task = asyncio.create_task(bridge.call("launch_app", {"name": "fixture"}))
    await asyncio.sleep(0)
    payload = app.sio.emit.await_args.args[1]
    assert app.sio.emit.await_args.kwargs["room"] == "client"
    assert not app.dispatcher.resolve("intruder", payload["id"], True)
    await app.workspace.stop_audio()
    await asyncio.gather(task, return_exceptions=True)
    assert not app.dispatcher.pending
    assert not app.dispatcher.resolve("owner", payload["id"], True)
    fake.handle_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_alias_and_target_denials_survive_approval(voice):
    app, bridge, fake = voice
    app.settings["tool_permissions"]["control_device"] = True
    task = asyncio.create_task(bridge.call("control_light", VALID["control_light"]))
    await asyncio.sleep(0)
    identifier = app.sio.emit.await_args.args[1]["id"]
    app.settings["tool_permissions"]["control_light"] = "deny"
    assert app.dispatcher.resolve("owner", identifier, True)
    assert (await task)["error"] == "permission_denied"
    fake.handle_tool_call.assert_not_called()
    app.settings["tool_permissions"]["run_web_agent"] = False
    app.settings["tool_permissions"]["prompt_web_agent"] = "deny"
    assert (await bridge.call("run_web_agent", VALID["run_web_agent"]))[
        "error"
    ] == "permission_denied"


@pytest.mark.asyncio
async def test_voice_delayed_agent_event_is_invalid_after_session_stop(voice):
    app, bridge, fake = voice
    events = []

    async def invoke(*args, **kwargs):
        events.append(Event(Events.DEVICE_LIST, {"private": True}))
        return SimpleNamespace(success=True, message="fixture", data={})

    fake.handle_tool_call.side_effect = invoke
    await bridge.call("list_all_devices", {})
    await app.workspace.stop_audio()
    app.sio.emit.reset_mock()
    await app.delivery.bridge_legacy(events[0])
    app.sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_expiry_invalid_alias_unknown_function_and_project_switch(voice):
    app, bridge, _ = voice
    app.dispatcher.timeout = 0.001
    app.settings["tool_permissions"]["read_file"] = True
    assert (await bridge.call("read_file", {"path": "x"}))["error"] == "approval_expired"
    assert (
        await bridge.call("control_light", {"target": "lamp", "action": "set", "brightness": True})
    )["error"] == "invalid_arguments"
    assert (await bridge.call("not_a_tool", {}))["error"] == "tool_unavailable"
    await bridge.call("create_project", {"name": "Second"})
    await bridge.call("switch_project", {"name": "Second"})
    assert bridge.binding["project_path"].name == bridge.projects.current_project == "Second"
    assert "error" not in await bridge.call("write_file", VALID["write_file"])
    assert (bridge.binding["project_path"] / "note.txt").exists()


def test_live_receiver_has_only_the_injected_dispatch_path():
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "backend/inara.py").read_text(encoding="utf-8")
    )
    receiver = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "receive_audio"
    )
    attributes = {node.attr for node in ast.walk(receiver) if isinstance(node, ast.Attribute)}
    assert "tool_bridge" in attributes and "call" in attributes
    assert (
        not {
            "cad_agent",
            "web_agent",
            "handle_tool_call",
            "approve_voice",
            "_pending_confirmations",
        }
        & attributes
    )


def test_live_audio_resource_close_releases_streams_client_and_engine_once():
    from unittest.mock import Mock

    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "backend/inara.py").read_text(encoding="utf-8")
    )
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AudioLoop")
    close = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "close")
    namespace = {}
    exec(
        compile(ast.Module(body=[close], type_ignores=[]), "audio-close-contract", "exec"),
        namespace,
    )
    audio = SimpleNamespace(
        audio_stream=SimpleNamespace(close=Mock()),
        output_stream=SimpleNamespace(close=Mock()),
        pya=SimpleNamespace(terminate=Mock()),
        client=SimpleNamespace(close=Mock()),
    )
    stream, output, engine, client = (
        audio.audio_stream,
        audio.output_stream,
        audio.pya,
        audio.client,
    )
    namespace["close"](audio)
    namespace["close"](audio)
    stream.close.assert_called_once()
    output.close.assert_called_once()
    engine.terminate.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_voice_print_uuid_review_is_socket_serializable_and_stop_prevents_effects(voice):
    import json
    app, bridge, _ = voice
    app.settings["tool_permissions"]["print_stl"] = True
    captured = asyncio.Queue()
    async def emit(event, payload, room=None):
        json.dumps(payload)
        await captured.put(payload)
    app.sio.emit = emit
    task = asyncio.create_task(bridge.call("print_stl", {"printer": "fixture"}))
    payload = await asyncio.wait_for(captured.get(), 1)
    assert isinstance(payload["args"]["request_id"], str)
    assert app.printer.instance is None
    await app.workspace.stop_audio()
    await asyncio.gather(task, return_exceptions=True)
    assert app.printer.instance is None and not app.dispatcher.pending
