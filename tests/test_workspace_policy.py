"""Retained wire compatibility with isolated adapters, never live media/providers."""

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from core.event_bus import Event, Events, event_owner
from services.tools import ServiceError
from services.workspace import WORKSPACE_TOOLS
from services.workspace_contracts import SaveMemory


PAYLOADS = {
    "save_memory": {"filename": "session-notes", "messages": [{"sender": "User", "text": "Hello"}]},
    "legacy_generate_cad": {"prompt": "create a box"},
    "iterate_cad": {"prompt": "make it wider"},
    "prompt_web_agent": {"prompt": "look at an example"},
}


@pytest.fixture
def workspace(application_factory):
    app = application_factory()
    app.sessions.principals.update(
        {
            "client": "owner",
            "sibling": "owner",
            "other": "intruder",
            "control": "owner",
            "tray": "owner",
        }
    )
    app.sessions.roles.update(
        {
            "client": "renderer",
            "sibling": "renderer",
            "other": "renderer",
            "control": "workspace",
            "tray": "resident",
        }
    )
    app.sessions.local_owner = "owner"
    app.workspace.preflight = lambda: None
    app.workspace.cad_factory = lambda **kwargs: pytest.fail("Unexpected CAD adapter")
    app.workspace.web_factory = lambda: pytest.fail("Unexpected browser adapter")
    for name, (_, permission, _) in WORKSPACE_TOOLS.items():
        app.settings["tool_permissions"][name] = False
        app.settings["tool_permissions"][permission] = False
    return app


def wire(name):
    return "generate_cad" if name == "legacy_generate_cad" else name


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAYLOADS)
@pytest.mark.parametrize("sid", ["missing", "other", "control", "tray", "locked"])
async def test_all_routes_require_authenticated_owner_renderer(workspace, name, sid):
    if sid == "locked":
        sid = "client"
        workspace.settings["face_auth_enabled"] = True
    await workspace.sio.handlers["/"][wire(name)](sid, PAYLOADS[name])
    assert workspace.sio.emit.await_args.kwargs["room"] == sid
    assert workspace.sio.emit.await_args.args[0] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAYLOADS)
async def test_direct_and_dispatcher_denial_precedes_adapters(workspace, name):
    permission = WORKSPACE_TOOLS[name][1]
    workspace.settings["tool_permissions"][permission] = "deny"
    await workspace.sio.handlers["/"][wire(name)]("client", PAYLOADS[name])
    assert workspace.sio.emit.await_args.args[1]["code"] == "permission_denied"
    with pytest.raises(ServiceError, match="disabled"):
        await workspace.dispatcher.dispatch(
            "owner", name, PAYLOADS[name], workspace.sessions.context("client").tools()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAYLOADS)
async def test_extra_identity_and_malformed_requests_rejected(workspace, name):
    await workspace.sio.handlers["/"][wire(name)](
        "client", {**PAYLOADS[name], "principal": "intruder"}
    )
    assert workspace.sio.emit.await_args.args[1]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "filename", ["../outside", "sub/file", "C:log", "NUL", "COM1.txt", "bad.", "bad ", "a:b", "x\n"]
)
def test_memory_filename_contract_rejects_ambiguous_or_escaping_names(filename):
    with pytest.raises(ValidationError):
        SaveMemory.model_validate({**PAYLOADS["save_memory"], "filename": filename})


@pytest.mark.asyncio
async def test_memory_is_project_scoped_preserves_existing_and_returns_origin_only(workspace):
    root = workspace.projects.get_current_project_path()
    await workspace.workspace_transport.save_memory("client", PAYLOADS["save_memory"])
    path = root / "long_term_memory/session-notes.txt"
    assert path.read_text() == "User: Hello\n"
    await workspace.workspace_transport.save_memory("client", PAYLOADS["save_memory"])
    assert workspace.sio.emit.await_args.args[1]["code"] == "memory_exists"
    assert path.read_text() == "User: Hello\n"
    assert all(call.kwargs["room"] == "client" for call in workspace.sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_redacted_memory_approval_without_export(workspace):
    workspace.settings["tool_permissions"]["save_memory"] = True
    task = asyncio.create_task(
        workspace.workspace_transport.save_memory("client", PAYLOADS["save_memory"])
    )
    await asyncio.sleep(0)
    payload = workspace.sio.emit.await_args.args[1]
    assert payload["args"]["messages"] == 1 and "Hello" not in str(payload)
    await workspace.disconnect("client")
    await asyncio.gather(task, return_exceptions=True)
    assert not workspace.dispatcher.pending
    assert not list(workspace.projects.get_current_project_path().glob("long_term_memory/*"))
    assert not workspace.dispatcher.resolve("owner", payload["id"], True)


@pytest.mark.asyncio
async def test_retired_browser_never_constructs_adapter(workspace):
    await workspace.workspace_transport.prompt_web_agent("client", PAYLOADS["prompt_web_agent"])
    assert workspace.sio.emit.await_args.args[1]["code"] == "browser_migrated"
    assert not workspace.workspace.requests


@pytest.mark.asyncio
async def test_legacy_cad_uses_captured_project_and_preserves_wire_result(workspace):
    original = workspace.projects.get_current_project_path().resolve()
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(prompt, output_dir):
        assert Path(output_dir) == original / "cad/legacy"
        entered.set()
        await release.wait()
        file = Path(output_dir) / "model.stl"
        file.write_bytes(b"fixture STL")
        return {"format": "stl", "data": "not trusted", "file_path": str(file)}

    workspace.workspace.cad_factory = lambda **kwargs: SimpleNamespace(generate_prototype=generate)
    task = asyncio.create_task(
        workspace.workspace_transport.generate_cad("client", {"prompt": "create a box"})
    )
    await entered.wait()
    workspace.projects.create_project("Second")
    workspace.projects.switch_project("Second")
    release.set()
    await task
    results = [c for c in workspace.sio.emit.await_args_list if c.args[0] == "cad_data"]
    assert len(results) == 2
    assert all(base64.b64decode(c.args[1]["data"]) == b"fixture STL" for c in results)
    assert all(c.kwargs["room"] in ("client", "sibling") for c in results)


@pytest.mark.asyncio
async def test_legacy_cad_rejects_adapter_output_outside_project(workspace, tmp_path):
    outside = tmp_path / "outside.stl"
    outside.write_bytes(b"private")
    workspace.workspace.cad_factory = lambda **kwargs: SimpleNamespace(
        generate_prototype=AsyncMock(return_value={"file_path": str(outside)})
    )
    await workspace.workspace_transport.generate_cad("client", {"prompt": "create"})
    assert workspace.sio.emit.await_args.args[1]["code"] == "artifact_invalid"
    assert not any(c.args[0] == "cad_data" for c in workspace.sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_unstamped_events_stay_internal_and_voice_events_capture_owner(workspace):
    await workspace.delivery.bridge_legacy(Event(Events.DEVICE_LIST, {"private": True}))
    workspace.sio.emit.assert_not_awaited()
    marker = event_owner.set("owner")
    event = Event(Events.DEVICE_LIST, {"private": True})
    event_owner.reset(marker)
    await workspace.delivery.bridge_legacy(event)
    assert {c.kwargs["room"] for c in workspace.sio.emit.await_args_list} == {"client", "sibling"}


@pytest.mark.asyncio
async def test_retired_browser_model_alias_cannot_revive_execution(workspace):
    with pytest.raises(ServiceError) as error:
        await workspace.dispatcher.dispatch("owner", "run_web_agent", {"prompt": "fixture"}, workspace.sessions.context("client").tools())
    assert error.value.code == "browser_migrated"
    assert not workspace.workspace.requests
