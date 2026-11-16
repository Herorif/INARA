"""S7.5 screen help: look_at_screen, one screenshot per approval, never stored.

Offline: provider clients are faked, the desktop (lock screen, active window) is faked and
the workspace's capture is a fake ``sio.call``. No real screen is captured, no camera opens,
nothing binds a port.
"""

import asyncio
import base64
import gc
import json
import logging
import uuid
import weakref
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict
from socketio.exceptions import TimeoutError as CallTimeout

from llm.base import LLMResponse
from llm.claude import ClaudeProvider
from services import screen_help
from services.tools import ServiceError, ToolSpec
from tests.test_reply_streaming import ClaudeClient, claude_message

SHOT_MARKER = b"SCREENSHOT-BYTES-MARKER-7731"
JPEG = b"\xff\xd8\xff\xe0" + SHOT_MARKER * 8 + b"\xff\xd9"
IMAGE = base64.b64encode(JPEG).decode("ascii")
QUESTION = "QUESTION-MARKER-5120 what's this error"
ANSWER = "ANSWER-MARKER-3388 the file is missing"


class FakeVision:
    """A brain provider stand-in; keeps a weak reference to each request's messages only."""

    def __init__(self, name="claude", answers=(ANSWER,)):
        self.name, self.answers, self.calls, self.closed = name, list(answers), [], 0
        self.seen = []
        self._model = "fake-vision"

    async def generate(self, messages, **kwargs):
        (message,) = messages
        self.calls.append((message.content, [dict(item) for item in message.attachments],
                           kwargs))
        self.seen.append(weakref.ref(message))
        return LLMResponse(text=self.answers.pop(0))

    async def close(self):
        self.closed += 1


class FakeDesktop:
    def __init__(self, locked=False, window=4242):
        self.is_locked, self.window, self.asked = locked, window, 0

    def locked(self):
        return self.is_locked

    def active_window(self):
        self.asked += 1
        return self.window


class Workspace:
    """The workspace main process's side of ``sio.call('screen_capture', ...)``."""

    def __init__(self, reply=None, raises=None):
        self.reply = {"image": IMAGE} if reply is None else reply
        self.raises, self.calls = raises, []

    async def __call__(self, event, data=None, to=None, timeout=None, **_):
        self.calls.append((event, data, to, timeout))
        if self.raises is not None:
            raise self.raises
        return self.reply


@pytest.fixture
def screen(monkeypatch, tmp_path, application_factory):
    app = application_factory()
    emitted = []

    async def emit(event, data=None, room=None):
        emitted.append((event, data, room))

    monkeypatch.setattr(app.sio, "emit", emit)
    workspace = Workspace()
    monkeypatch.setattr(app.sio, "call", workspace)
    desktop = FakeDesktop()
    app.screen_help.desktop = desktop
    app.sessions.principals.update({"client": "owner", "tray": "owner", "control": "owner"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "control": "workspace"})
    app.sessions.local_owner = "owner"
    written = []
    encode = app.database.encode

    def recording(context, value):
        written.append(json.dumps(value, ensure_ascii=False))
        return encode(context, value)

    monkeypatch.setattr(app.database, "encode", recording)
    return SimpleNamespace(app=app, emitted=emitted, workspace=workspace, desktop=desktop,
                           written=written, root=tmp_path)


def events(screen, *names):
    return [(event, data, room) for event, data, room in screen.emitted if event in names]


def assert_screenshot_nowhere(screen):
    """No screenshot bytes or base64 in any database write or any file under the test root."""
    text = "\n".join(screen.written)
    assert IMAGE[:40] not in text and SHOT_MARKER.decode() not in text
    for path in screen.root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert SHOT_MARKER not in data and IMAGE[:40].encode() not in data, path


async def approving(screen, approvals):
    async def approve(payload):
        approvals.append(payload)
        assert screen.app.dispatcher.resolve("owner", payload["id"], True)

    return approve


def dispatch(screen, approve, question=QUESTION, region=None, sid="client"):
    arguments = {"question": question, **({"region": region} if region else {})}
    return screen.app.dispatcher.dispatch(
        "owner", "look_at_screen", arguments,
        {**screen.app.sessions.context(sid).tools(), "origin_sid": sid,
         "usage_operation": f"{uuid.uuid4()}:0:0"},
        approve,
    )


# --- registration and the approval card --------------------------------------------------


def test_tool_is_model_visible_always_asks_and_is_untrusted(screen):
    spec = screen.app.dispatcher.tools["look_at_screen"]
    assert spec.always_ask is True and spec.model_visible is True
    assert spec.untrusted_output is True and spec.untrusted_source == "your screen"
    assert spec.long_running is False and spec.execution_timeout == 30
    assert spec.outward is False
    (schema,) = [item for item in screen.app.dispatcher.schemas()
                 if item["name"] == "look_at_screen"]
    assert schema["parameters"]["required"] == ["question"]
    assert set(schema["parameters"]["properties"]["region"]["enum"]) == {"whole", "window"}


@pytest.mark.asyncio
async def test_it_always_asks_and_the_card_carries_the_question_and_region(screen):
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    with pytest.raises(ServiceError) as error:
        await screen.app.dispatcher.dispatch(
            "owner", "look_at_screen", {"question": QUESTION},
            screen.app.sessions.context("client").tools(),
        )
    assert error.value.code == "approval_required"
    screen.app.settings["tool_permissions"]["look_at_screen"] = False  # "never ask" still asks
    approvals = []
    await dispatch(screen, await approving(screen, approvals), region="window")
    (card,) = approvals
    assert card["tool"] == "look_at_screen"
    assert card["args"] == {"question": QUESTION, "region": "window"}


@pytest.mark.asyncio
async def test_denied_takes_no_screenshot(screen):
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider

    async def decline(payload):
        screen.app.dispatcher.resolve("owner", payload["id"], False)

    with pytest.raises(ServiceError) as error:
        await dispatch(screen, decline)
    assert error.value.code == "permission_denied"
    assert screen.workspace.calls == [] and provider.calls == []
    assert events(screen, "screen_look") == [] and screen.desktop.asked == 0


# --- one approval, one screenshot ---------------------------------------------------------


@pytest.mark.asyncio
async def test_one_approval_one_screenshot_one_vision_request(screen, caplog):
    caplog.set_level(logging.DEBUG)
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    approvals = []
    result = await dispatch(screen, await approving(screen, approvals))
    assert result == {"answer": ANSWER}
    assert len(approvals) == 1
    ((event, request, room, timeout),) = screen.workspace.calls
    assert event == "screen_capture" and room == "control" and timeout == 10
    assert request["region"] == "whole" and "hwnd" not in request
    assert uuid.UUID(request["request_id"])
    assert screen.desktop.asked == 0  # the whole screen needs no window
    ((content, attachments, kwargs),) = provider.calls
    assert content == QUESTION
    assert attachments == [{"type": "image", "data": JPEG, "mime_type": "image/jpeg"}]
    assert "one screenshot" in kwargs["system_instruction"]
    assert provider.closed == 1
    # "Looking at your screen…" on the owner's renderer, then cleared.
    assert [(data["state"], room) for _, data, room in events(screen, "screen_look")] == [
        ("capturing", "client"), ("done", "client")]
    assert screen.app.screen_help.busy is False
    for marker in ("QUESTION-MARKER", "ANSWER-MARKER", IMAGE[:40]):
        assert marker not in caplog.text


@pytest.mark.asyncio
async def test_the_screenshot_never_touches_disk_and_is_dropped_after_the_answer(
        screen, monkeypatch):
    import builtins
    import os
    import pathlib

    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    writes = []
    real_open = builtins.open

    def watching_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            writes.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    before = {path: path.stat().st_mtime_ns for path in screen.root.rglob("*") if path.is_file()}
    monkeypatch.setattr(builtins, "open", watching_open)
    monkeypatch.setattr(pathlib.Path, "write_bytes",
                        lambda self, data: writes.append(str(self)) or 0)
    real_os_open = os.open
    monkeypatch.setattr(os, "open", lambda path, flags, *a, **k: (
        writes.append(str(path)) if flags & (os.O_WRONLY | os.O_RDWR) else None)
        or real_os_open(path, flags, *a, **k))
    assert await dispatch(screen, await approving(screen, [])) == {"answer": ANSWER}
    monkeypatch.undo()
    assert writes == []
    after = {path: path.stat().st_mtime_ns for path in screen.root.rglob("*") if path.is_file()}
    # No new file; only the private database changed (the usage meter's row, checked below).
    assert set(after) == set(before)
    assert {path.name for path in after if after[path] != before[path]} <= {
        "assistant.sqlite3", "assistant.sqlite3-wal", "assistant.sqlite3-shm"}
    assert_screenshot_nowhere(screen)
    # Nothing in the core still holds the request that carried the screenshot.
    provider.calls.clear()
    gc.collect()
    assert all(ref() is None for ref in provider.seen)
    assert not any(isinstance(value, (bytes, bytearray)) and SHOT_MARKER in value
                   for value in vars(screen.app.screen_help).values())


@pytest.mark.asyncio
async def test_window_region_sends_the_active_window(screen):
    screen.app.conversation.provider_factory = lambda: FakeVision()
    assert await dispatch(screen, await approving(screen, []), region="window")
    ((_, request, _, _),) = screen.workspace.calls
    assert request["region"] == "window" and request["hwnd"] == "4242"
    screen.desktop.window = None
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, []), region="window")
    assert error.value.code == "no_window" and "Click the window" in str(error.value)
    assert len(screen.workspace.calls) == 1


# --- refusals ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("setup, code", [
    ("gaming", "gaming_mode"),
    ("screen_locked", "screen_locked"),
    ("face_locked", "authentication_required"),
])
async def test_gaming_and_locks_refuse_before_the_card(screen, setup, code):
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    if setup == "gaming":
        screen.app.resources.state = "gaming"
    elif setup == "screen_locked":
        screen.desktop.is_locked = True
    else:
        screen.app.settings["face_auth_enabled"] = True
    approvals = []
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, approvals))
    assert error.value.code == code
    assert approvals == [] and screen.workspace.calls == [] and provider.calls == []


@pytest.mark.asyncio
async def test_a_lock_or_gaming_during_the_capture_drops_the_screenshot(screen):
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    workspace = screen.workspace

    async def locking_call(*args, **kwargs):
        screen.desktop.is_locked = True
        return await workspace(*args, **kwargs)

    screen.app.sio.call = locking_call
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, []))
    assert error.value.code == "screen_locked" and provider.calls == []


@pytest.mark.asyncio
async def test_a_provider_without_image_support_gets_a_plain_error(screen):
    screen.app.conversation.provider_factory = lambda: FakeVision(name="local")
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, []))
    assert error.value.code == "image_unsupported"
    assert "can't look at screenshots" in str(error.value)
    assert screen.workspace.calls == []


@pytest.mark.asyncio
async def test_without_a_workspace_it_says_open_jarvis(screen):
    screen.app.conversation.provider_factory = lambda: FakeVision()
    screen.app.sessions.roles["control"] = "resident"
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, []))
    assert error.value.code == "workspace_unavailable" and "Open JARVIS" in str(error.value)
    assert screen.workspace.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, raises, code", [
    ({"error": "locked"}, None, "capture_locked"),
    ({"error": "no_window"}, None, "capture_no_window"),
    ({"error": "own_window"}, None, "capture_own_window"),
    ({"error": "busy"}, None, "capture_busy"),
    ({"error": "something"}, None, "capture_failed"),
    ({"image": base64.b64encode(b"GIF89a....").decode()}, None, "capture_invalid"),
    ("not a dict", None, "capture_invalid"),
    (None, CallTimeout(), "capture_timeout"),
    (None, ConnectionError("gone"), "capture_failed"),
])
async def test_capture_failures_become_plain_messages(screen, reply, raises, code):
    provider = FakeVision()
    screen.app.conversation.provider_factory = lambda: provider
    screen.workspace.reply, screen.workspace.raises = reply, raises
    with pytest.raises(ServiceError) as error:
        await dispatch(screen, await approving(screen, []))
    assert error.value.code == code and str(error.value) == screen_help.MESSAGES[code]
    assert provider.calls == [] and provider.closed == 1
    assert screen.app.screen_help.busy is False
    assert [data["state"] for _, data, _ in events(screen, "screen_look")][-1] == "done"


# --- the brain's turn ----------------------------------------------------------------------


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@pytest.mark.asyncio
async def test_the_turn_is_tainted_and_history_keeps_no_image(screen):
    """tool_use look_at_screen -> answer as untrusted data -> an outward tool must ask."""
    sent = []
    screen.app.dispatcher.register(ToolSpec(
        "send_test_message", "Send a message.", NoArgs,
        lambda _args, _context: sent.append(1) or {"sent": True}, outward=True))
    screen.app.settings["tool_permissions"]["send_test_message"] = False  # normally never asks
    first = claude_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "look_at_screen",
          "input": {"question": QUESTION}}], stop="tool_use")
    second = claude_message(
        [{"type": "tool_use", "id": "toolu_2", "name": "send_test_message", "input": {}}],
        stop="tool_use")
    third = claude_message([{"type": "text", "text": "The file is missing, sir."}])
    client = ClaudeClient(([], first), ([], second), (["The file is missing, sir."], third))
    vision = FakeVision()
    providers = iter([ClaudeProvider(api_key="sk-ant-offline", client=client), vision])
    screen.app.conversation.provider_factory = lambda: next(providers)
    cards = []

    async def renderer():
        while len(cards) < 2:
            for _, card, _ in events(screen, "tool_confirmation_request"):
                if card["id"] not in {item["id"] for item in cards}:
                    cards.append(card)
                    screen.app.dispatcher.resolve("owner", card["id"], True)
            await asyncio.sleep(0.01)

    helper = asyncio.create_task(renderer())
    await screen.app.conversation_transport.user_input(
        "client", {"text": "What's this error?", "conversation_id": str(uuid.uuid4())})
    await asyncio.wait_for(helper, 5)
    assert [card["tool"] for card in cards] == ["look_at_screen", "send_test_message"]
    assert "taint" not in cards[0]
    assert cards[1]["taint"] == ["your screen"]  # forced to ask by the screen's content
    assert sent == [1] and len(screen.workspace.calls) == 1 and len(vision.calls) == 1
    result = client.requests[1]["messages"][-1]["content"][0]
    opening, closing = '<untrusted_content source="your screen">', "</untrusted_content>"
    assert result["type"] == "tool_result"
    assert result["content"].startswith(opening) and result["content"].endswith(closing)
    assert json.loads(result["content"][len(opening):-len(closing)]) == {"answer": ANSWER}
    for request in client.requests:
        assert '"image"' not in json.dumps(request["messages"], default=str)
    assert screen.written  # the turn was stored
    assert_screenshot_nowhere(screen)
