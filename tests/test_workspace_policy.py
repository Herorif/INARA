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
from services.workspace_contracts import SaveMemory, StartAudio, VideoFrame


PAYLOADS = {
    "save_memory": {"filename": "session-notes", "messages": [{"sender": "User", "text": "Hello"}]},
    "upload_memory": {"memory": "private transcript"},
    "start_audio": {"device_index": None, "device_name": None, "muted": False},
    "resume_audio": {},
    "video_frame": {"image": base64.b64encode(b"\xff\xd8\xfffixture").decode()},
    "legacy_generate_cad": {"prompt": "create a box"},
    "iterate_cad": {"prompt": "make it wider"},
    "prompt_web_agent": {"prompt": "look at an example"},
}


class Audio:
    def __init__(self, **kwargs):
        self.callbacks = kwargs
        self.session = SimpleNamespace(send=AsyncMock())
        self.send_frame = AsyncMock()
        self.stopped = False
        self.paused = False

    def stop(self):
        self.stopped = True


    def set_paused(self, value):
        self.paused = value


    async def run(self):
        await asyncio.Event().wait()


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
    app.workspace.audio_factory = Audio
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
    assert workspace.workspace.audio is None


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


@pytest.mark.parametrize(
    "args", [{"muted": "false"}, {"device_index": True}, {"device_index": -1}, {"device_name": 1}]
)
def test_media_contract_does_not_coerce_control_values(args):
    with pytest.raises(ValidationError):
        StartAudio.model_validate(args)


@pytest.mark.parametrize(
    "image",
    [
        "not base64",
        base64.b64encode(b"not an image").decode(),
        b"\xff\xd8\xff" + b"x" * 1000000,
        [],
    ],
    ids=["base64", "signature", "size", "type"],
)
def test_frames_are_bounded_and_structurally_typed(image):
    with pytest.raises(ValidationError):
        VideoFrame(image=image)


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


async def audio_start(app):
    await app.workspace_transport.start_audio("client", PAYLOADS["start_audio"])
    assert app.workspace.audio
    return app.workspace.audio


@pytest.mark.asyncio
async def test_audio_callbacks_are_owner_session_bound(workspace):
    audio = await audio_start(workspace)
    audio.callbacks["on_transcription"]({"sender": "User", "text": "private"})
    await asyncio.sleep(0)
    events = [
        call
        for call in workspace.sio.emit.await_args_list
        if call.args[0] == "transcription"
    ]
    assert {call.kwargs["room"] for call in events} == {"client", "sibling"}
    old = audio.callbacks["on_transcription"]
    await workspace.disconnect("client")
    assert audio.stopped and not workspace.workspace.audio
    count = workspace.sio.emit.await_count
    old({"text": "late private text"})
    await asyncio.sleep(0)
    assert workspace.sio.emit.await_count == count


@pytest.mark.asyncio
async def test_frame_upload_memory_and_project_change_cannot_feed_previous_session(workspace):
    audio = await audio_start(workspace)
    await workspace.workspace_transport.upload_memory("client", PAYLOADS["upload_memory"])
    assert "private transcript" in audio.session.send.await_args.kwargs["input"]
    await workspace.workspace_transport.video_frame("client", PAYLOADS["video_frame"])
    audio.send_frame.assert_awaited_once()
    await workspace.workspace_transport.video_frame("client", PAYLOADS["video_frame"])
    assert workspace.sio.emit.await_args.args[1]["code"] == "frame_rate"
    workspace.projects.create_project("Second")
    workspace.projects.switch_project("Second")
    await workspace.workspace_transport.upload_memory("client", PAYLOADS["upload_memory"])
    assert workspace.sio.emit.await_args.args[1]["code"] == "audio_unavailable"
    audio.session.send.assert_awaited_once()
    await workspace.close()


@pytest.mark.asyncio
async def test_resource_restriction_cancels_voice_and_discards_callbacks(workspace):
    audio = await audio_start(workspace)
    client = SimpleNamespace(close=AsyncMock())
    workspace.vision_loop._client = client
    workspace.resources.select("gaming")
    await workspace.restrict_resources()
    assert audio.stopped and workspace.workspace.binding is None
    assert workspace.vision_loop._frame is None
    client.close.assert_awaited_once()
    assert workspace.vision_loop._client is None


@pytest.mark.asyncio
async def test_browser_forwards_only_scoped_updates_and_closes_on_cancel(workspace):
    started = asyncio.Event()
    browser = SimpleNamespace(close=AsyncMock())
    client = SimpleNamespace(close=lambda: None)

    async def run(prompt, update_callback):
        assert prompt == "look at an example"
        await update_callback("fixture image", "navigated")
        started.set()
        await asyncio.Event().wait()

    workspace.workspace.web_factory = lambda: SimpleNamespace(
        run_task=run, browser=browser, client=client
    )
    task = asyncio.create_task(
        workspace.workspace_transport.prompt_web_agent("client", PAYLOADS["prompt_web_agent"])
    )
    await started.wait()
    events = [c for c in workspace.sio.emit.await_args_list if c.args[0] == "browser_frame"]
    assert {c.kwargs["room"] for c in events} == {"client", "sibling"}
    await workspace.disconnect("client")
    await asyncio.gather(task, return_exceptions=True)
    browser.close.assert_awaited_once()
    assert not workspace.workspace.browsing


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
async def test_stop_voice_cancels_sibling_media_approval_without_cancelling_other_tools(workspace):
    await audio_start(workspace)
    workspace.settings["tool_permissions"]["upload_memory"] = True
    task = asyncio.create_task(
        workspace.workspace_transport.upload_memory("sibling", PAYLOADS["upload_memory"])
    )
    await asyncio.sleep(0)
    assert workspace.dispatcher.pending
    await workspace.workspace_transport.stop_audio("client")
    await asyncio.gather(task, return_exceptions=True)
    assert not workspace.dispatcher.pending and workspace.workspace.audio is None


@pytest.mark.asyncio
async def test_typed_browser_origin_disconnect_cancels_execution_and_closes_adapter(workspace):
    from services.conversation import ConversationRequest, ConversationService
    from llm.base import LLMResponse, ToolCall

    started = asyncio.Event()
    browser = SimpleNamespace(close=AsyncMock())

    async def browse(prompt, update_callback):
        started.set()
        await asyncio.Event().wait()

    workspace.workspace.web_factory = lambda: SimpleNamespace(run_task=browse, browser=browser)
    provider = SimpleNamespace(
        generate=AsyncMock(
            return_value=LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(id="browser-call", name="prompt_web_agent", args={"prompt": "fixture"})
                ],
            )
        ),
        close=AsyncMock(),
    )
    workspace.conversation_transport.service = ConversationService(
        workspace.dispatcher, lambda: provider
    )
    task = asyncio.create_task(
        workspace.conversation_transport.user_input(
            "client", ConversationRequest(text="Browse fixture").model_dump(mode="json")
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    assert "client" in workspace.workspace.requests.values()
    await workspace.disconnect("client")
    await asyncio.gather(task, return_exceptions=True)
    assert not workspace.conversation_transport.running and not workspace.workspace.requests
    browser.close.assert_awaited_once()
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_locked_owner_can_pause_and_stop_but_malformed_stop_preserves_session(workspace):
    audio = await audio_start(workspace)
    workspace.settings["face_auth_enabled"] = True
    await workspace.workspace_transport.pause_audio("client")
    assert audio.paused
    await workspace.workspace_transport.stop_audio("client", {"unexpected": True})
    assert not audio.stopped
    assert workspace.sio.emit.await_args.args[1]["code"] == "invalid_arguments"
    await workspace.workspace_transport.stop_audio("client")
    assert audio.stopped and workspace.workspace.audio is None

@pytest.mark.asyncio
async def test_stopped_voice_approval_cannot_resolve_replacement_session(workspace):
    old = await audio_start(workspace)
    workspace.settings["tool_permissions"]["launch_app"] = True
    requested = asyncio.Event()
    captured = {}
    original_emit = workspace.sio.emit

    async def emit(event, payload, **kwargs):
        await original_emit(event, payload, **kwargs)
        if event == "tool_confirmation_request":
            captured.update(payload)
            requested.set()

    workspace.sio.emit = emit
    bridge = old.callbacks["tool_bridge"]
    task = asyncio.create_task(bridge.call("launch_app", {"name": "fixture"}))
    await asyncio.wait_for(requested.wait(), 2)
    await workspace.workspace_transport.stop_audio("client")
    replacement = await audio_start(workspace)
    assert replacement.callbacks["tool_bridge"] is not bridge
    assert not workspace.dispatcher.resolve("owner", captured["id"], True)
    await asyncio.gather(task, return_exceptions=True)
    assert not workspace.dispatcher.pending
    await workspace.close()
