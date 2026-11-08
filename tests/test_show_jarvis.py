"""V2 Show JARVIS: vision_ask, look_through_camera and its capture plumbing.

Offline: provider clients are faked, no camera is opened, nothing binds a port.
"""

import asyncio
import base64
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from google.genai import types

from llm.base import LLMResponse, Message, MessageRole
from llm.claude import ClaudeProvider, message_to_api
from llm.gemini import GeminiProvider
from services import vision_ask
from services.tools import ServiceError
from tests.test_reply_streaming import ClaudeClient, GeminiClient, chunk, claude_message, words

PHOTO_MARKER = b"PHOTO-BYTES-MARKER-6620"
JPEG = b"\xff\xd8\xff\xe0" + PHOTO_MARKER * 8 + b"\xff\xd9"
IMAGE = base64.b64encode(JPEG).decode("ascii")
QUESTION = "QUESTION-MARKER-4410 what is this"
ANSWER = "ANSWER-MARKER-9921 a bracket"


# --- fixtures and fakes -----------------------------------------------------------------


class FakeVision:
    """A brain provider stand-in that records each request (messages and kwargs)."""

    def __init__(self, name="claude", answers=(ANSWER,)):
        self.name, self.answers, self.calls, self.closed = name, list(answers), [], 0
        self._model = "fake-vision"

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        return LLMResponse(text=self.answers.pop(0))

    async def close(self):
        self.closed += 1


@pytest.fixture
def show(monkeypatch, tmp_path, application_factory):
    app = application_factory()
    emitted = []

    async def emit(event, data=None, room=None):
        emitted.append((event, data, room))

    monkeypatch.setattr(app.sio, "emit", emit)
    project = app.projects.get_current_project_path().resolve()
    app.sessions.principals.update(
        {"client": "owner", "overlay": "owner", "tray": "owner", "control": "owner",
         "other": "intruder"}
    )
    app.sessions.roles.update(
        {"client": "renderer", "overlay": "overlay", "tray": "resident", "control": "workspace",
         "other": "renderer"}
    )
    app.sessions.local_owner = "owner"
    # Every value written to the private database, as the JSON that would be encrypted.
    written = []
    encode = app.database.encode

    def recording(context, value):
        written.append(json.dumps(value, ensure_ascii=False))
        return encode(context, value)

    monkeypatch.setattr(app.database, "encode", recording)
    return SimpleNamespace(app=app, emitted=emitted, project=project, written=written,
                           root=tmp_path)


def ask(show, **overrides):
    payload = {"conversation_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()),
               "question": QUESTION, "image": IMAGE, **overrides}
    return payload, show.app.sio.handlers["/"]["vision_ask"]


async def until(check):
    for _ in range(500):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


def events(show, *names):
    return [(event, data, room) for event, data, room in show.emitted if event in names]


def assert_photo_nowhere(show):
    """No photo bytes or base64 in any database write or any file under the test root."""
    text = "\n".join(show.written)
    assert show.written  # the recording hook saw the database writes
    assert IMAGE[:40] not in text and PHOTO_MARKER.decode() not in text
    for path in show.root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert PHOTO_MARKER not in data and IMAGE[:40].encode() not in data, path


# --- validation ------------------------------------------------------------------------


def test_decode_jpeg_checks_base64_size_and_magic_bytes():
    assert vision_ask.decode_jpeg(IMAGE) == JPEG
    for value, code in [
        ("", "image_invalid"),
        ("not base64 !!", "image_invalid"),
        (base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 20).decode(), "image_invalid"),
        (base64.b64encode(b"\xff\xd8").decode(), "image_invalid"),
        (base64.b64encode(b"\xff\xd8\xff" + b"x" * vision_ask.MAX_IMAGE_BYTES).decode(),
         "image_too_large"),
        ("A" * (vision_ask.MAX_IMAGE_TEXT + 4), "image_too_large"),
    ]:
        with pytest.raises(ServiceError) as error:
            vision_ask.decode_jpeg(value)
        assert error.value.code == code
    exact = b"\xff\xd8\xff" + b"x" * (vision_ask.MAX_IMAGE_BYTES - 3)
    assert vision_ask.decode_jpeg(base64.b64encode(exact).decode()) == exact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"question": ""}, "invalid_request"),
        ({"question": "   \n\t "}, "invalid_request"),
        ({"question": "x" * 501}, "invalid_request"),
        ({"image": base64.b64encode(b"GIF89a" + b"x" * 30).decode()}, "image_invalid"),
        ({"image": base64.b64encode(b"\xff\xd8\xff" + b"x" * 1_500_001).decode()},
         "image_too_large"),
        ({"extra": True}, "invalid_request"),
        ({"conversation_id": "not-a-uuid"}, "invalid_request"),
    ],
)
async def test_vision_ask_validates_before_any_provider(show, overrides, code):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    payload, handler = ask(show, **overrides)
    reply = await handler("client", payload)
    assert reply["ok"] is False and reply["code"] == code
    assert QUESTION not in reply["message"] and IMAGE[:20] not in reply["message"]
    assert provider.calls == [] and show.emitted == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sid, setup, code",
    [
        ("overlay", None, "authentication_required"),
        ("tray", None, "authentication_required"),
        ("control", None, "authentication_required"),
        ("unknown", None, "authentication_required"),
        ("other", None, "permission_denied"),
        ("client", "locked", "authentication_required"),
        ("client", "gaming", "gaming_mode"),
    ],
)
async def test_vision_ask_is_for_the_unlocked_owner_renderer_outside_gaming(show, sid, setup, code):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    if setup == "locked":
        show.app.settings["face_auth_enabled"] = True
    if setup == "gaming":
        show.app.resources.state = "gaming"
    payload, handler = ask(show)
    reply = await handler(sid, payload)
    assert reply == {"ok": False, "code": code, "message": reply["message"]}
    assert provider.calls == [] and show.emitted == []


@pytest.mark.asyncio
async def test_vision_ask_refuses_a_provider_that_cannot_take_images(show):
    provider = FakeVision(name="local")
    show.app.conversation.provider_factory = lambda: provider
    payload, handler = ask(show)
    reply = await handler("client", payload)
    assert reply["ok"] is False and reply["code"] == "image_unsupported"
    assert "can't look at photos" in reply["message"]
    assert provider.calls == []
    # The chat shows why there is no answer; the turn ends idle.
    assert events(show, "error")[0][1]["code"] == "image_unsupported"
    assert show.emitted[-1][1]["state"] == "idle"


# --- Claude and Gemini message shapes, history -----------------------------------------


@pytest.mark.asyncio
async def test_claude_gets_an_image_block_and_history_keeps_only_the_text_line(show, caplog):
    caplog.set_level(logging.DEBUG)
    client = ClaudeClient(
        (["ANSWER-MARKER-9921 ", "a bracket"],
         claude_message([{"type": "text", "text": ANSWER}])),
        (["It is steel."], claude_message([{"type": "text", "text": "It is steel."}])),
    )
    show.app.conversation.provider_factory = lambda: ClaudeProvider(
        api_key="sk-ant-offline", client=client
    )
    payload, handler = ask(show)
    reply = await handler("client", payload)
    assert reply == {"ok": True, "request_id": payload["request_id"],
                     "conversation_id": payload["conversation_id"], "project": show.project.name,
                     "text": ANSWER}

    (user, *_rest) = [m for m in client.requests[0]["messages"] if m["role"] == "user"]
    image, text = user["content"]
    assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": IMAGE}}
    assert text == {"type": "text", "text": "📷 photo · " + QUESTION}

    # Streamed like typed chat, with the same events and scope.
    names = [event for event, _, room in show.emitted if room == "client"]
    assert names[0] == "text_status" and "transcription_delta" in names
    assert names[-3:] == ["conversation_result", "transcription", "text_status"]
    (final,) = [data for _, data, _ in events(show, "transcription")]
    assert final["text"] == ANSWER and final["request_id"] == payload["request_id"]

    # History holds the text line and the answer; nothing image-shaped anywhere.
    history = show.app.conversation.restore(
        "owner", uuid.UUID(payload["conversation_id"]), show.project
    )
    assert history == [{"role": "user", "content": "📷 photo · " + QUESTION},
                       {"role": "assistant", "content": ANSWER}]

    # A typed follow-up replays the photo turn as text only.
    await show.app.conversation_transport.user_input(
        "client", {"text": "What metal?", "conversation_id": payload["conversation_id"]}
    )
    replay = client.requests[1]["messages"]
    assert replay[0] == {"role": "user", "content": "📷 photo · " + QUESTION}
    assert "image" not in json.dumps(replay)
    assert_photo_nowhere(show)
    assert any("📷 photo · " + QUESTION in item for item in show.written)  # the text line is kept
    for marker in (QUESTION, "QUESTION-MARKER", "ANSWER-MARKER", IMAGE[:40]):
        assert marker not in caplog.text


@pytest.mark.asyncio
async def test_gemini_gets_the_image_part_and_history_keeps_only_the_text_line(show):
    client = GeminiClient([chunk(words(ANSWER))])
    provider = GeminiProvider(api_key="AQ.offline-test-key", model="gemini-3.8-flash")
    provider._GeminiProvider__client = client
    show.app.conversation.provider_factory = lambda: provider
    payload, handler = ask(show)
    reply = await handler("client", payload)
    assert reply["ok"] is True and reply["text"] == ANSWER
    user = client.requests[0][-1]
    assert user.role == "user"
    assert user.parts[0].text == "📷 photo · " + QUESTION
    assert user.parts[1].inline_data.data == JPEG
    assert user.parts[1].inline_data.mime_type == "image/jpeg"
    assert show.app.conversation.restore(
        "owner", uuid.UUID(payload["conversation_id"]), show.project
    ) == [{"role": "user", "content": "📷 photo · " + QUESTION},
          {"role": "assistant", "content": ANSWER}]
    assert_photo_nowhere(show)


def test_message_attachments_become_claude_image_blocks():
    message = Message(MessageRole.USER, "What is it?",
                      attachments=[{"type": "image", "data": JPEG, "mime_type": "image/jpeg"}])
    assert message_to_api(message) == {
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": IMAGE}},
            {"type": "text", "text": "What is it?"},
        ],
    }
    assert message_to_api(Message(MessageRole.USER, "Plain")) == {"role": "user",
                                                                   "content": "Plain"}
    # Assistant messages never carry images.
    assert message_to_api(Message(MessageRole.ASSISTANT, "Hi", attachments=[
        {"type": "image", "data": JPEG}])) == {"role": "assistant", "content": "Hi"}


def test_gemini_message_attachment_is_part_from_bytes():
    from llm.gemini import _messages_to_gemini_contents

    (content,) = _messages_to_gemini_contents([Message(
        MessageRole.USER, "What is it?",
        attachments=[{"type": "image", "data": JPEG, "mime_type": "image/jpeg"}])])
    assert isinstance(content, types.Content)
    assert content.parts[0].text == "What is it?"
    assert content.parts[1].inline_data.data == JPEG


# --- look_through_camera ---------------------------------------------------------------


def test_tool_is_model_visible_and_always_asks(show):
    spec = show.app.dispatcher.tools["look_through_camera"]
    assert spec.always_ask is True and spec.model_visible is True
    assert spec.arguments is vision_ask.LookArguments
    (schema,) = [item for item in show.app.dispatcher.schemas()
                 if item["name"] == "look_through_camera"]
    assert schema["parameters"]["required"] == ["question"]


async def approving(show, approvals):
    async def approve(payload):
        approvals.append(payload)
        assert show.app.dispatcher.resolve("owner", payload["id"], True)

    return approve


async def answer_capture(show, sid="client", image=IMAGE, error=None, wait=True):
    """Wait for the core's vision_capture_request, then answer it as the renderer."""
    for _ in range(200):
        requests = events(show, "vision_capture_request")
        if requests:
            break
        await asyncio.sleep(0.01)
    _, data, room = requests[-1]
    payload = {"request_id": data["request_id"], **({"error": error} if error else
                                                   {"image": image})}
    return room, data, await show.app.sio.handlers["/"]["vision_capture_result"](sid, payload)


def dispatch(show, approve, question=QUESTION, sid="client"):
    return show.app.dispatcher.dispatch(
        "owner", "look_through_camera", {"question": question},
        {**show.app.sessions.context(sid).tools(), "origin_sid": sid,
         "usage_operation": f"{uuid.uuid4()}:0:0"},
        approve,
    )


@pytest.mark.asyncio
async def test_tool_needs_approval_and_its_card_carries_only_the_question(show):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    with pytest.raises(ServiceError) as error:
        await show.app.dispatcher.dispatch(
            "owner", "look_through_camera", {"question": QUESTION},
            show.app.sessions.context("client").tools(),
        )
    assert error.value.code == "approval_required"
    show.app.settings["tool_permissions"]["look_through_camera"] = False  # "never ask" still asks

    async def decline(payload):
        assert payload["tool"] == "look_through_camera"
        assert payload["args"] == {"question": QUESTION}
        show.app.dispatcher.resolve("owner", payload["id"], False)

    with pytest.raises(ServiceError) as error:
        await dispatch(show, decline)
    assert error.value.code == "permission_denied"
    assert events(show, "vision_capture_request") == [] and provider.calls == []


@pytest.mark.asyncio
async def test_one_approval_one_frame_one_vision_request(show, caplog):
    caplog.set_level(logging.DEBUG)
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    approvals = []
    task = asyncio.create_task(dispatch(show, await approving(show, approvals)))
    room, request, reply = await answer_capture(show)
    assert reply == {"ok": True}
    assert room == "client" and request["question"] == QUESTION
    assert uuid.UUID(request["request_id"])
    result = await task
    assert result == {"answer": ANSWER}
    assert len(approvals) == 1 and len(events(show, "vision_capture_request")) == 1
    ((messages, kwargs),) = provider.calls
    (message,) = messages
    assert message.content == QUESTION
    assert message.attachments == [{"type": "image", "data": JPEG, "mime_type": "image/jpeg"}]
    assert "one still photo" in kwargs["system_instruction"]
    assert provider.closed == 1
    # The request is one-use: a second frame for it is refused.
    again = await show.app.sio.handlers["/"]["vision_capture_result"](
        "client", {"request_id": request["request_id"], "image": IMAGE})
    assert again["ok"] is False and again["code"] == "unknown_request"
    assert show.app.show_jarvis.pending == {}
    assert_photo_nowhere(show)
    for marker in ("QUESTION-MARKER", "ANSWER-MARKER", IMAGE[:40]):
        assert marker not in caplog.text


@pytest.mark.asyncio
async def test_capture_is_answered_only_by_the_renderer_it_went_to(show):
    show.app.conversation.provider_factory = lambda: FakeVision()
    show.app.sessions.principals["second"] = "owner"
    show.app.sessions.roles["second"] = "renderer"
    task = asyncio.create_task(dispatch(show, await approving(show, [])))
    _, request, _ = await answer_capture(show, sid="second")
    assert _["code"] == "unknown_request"
    other = await show.app.sio.handlers["/"]["vision_capture_result"](
        "overlay", {"request_id": request["request_id"], "image": IMAGE})
    assert other["ok"] is False
    malformed = await show.app.sio.handlers["/"]["vision_capture_result"](
        "client", {"request_id": request["request_id"], "image": IMAGE, "error": "hidden"})
    assert malformed["code"] == "invalid_request"
    _, _, reply = await answer_capture(show)
    assert reply == {"ok": True}
    assert (await task) == {"answer": ANSWER}


@pytest.mark.asyncio
async def test_capture_times_out_after_twenty_seconds(show, monkeypatch):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    assert vision_ask.CAPTURE_TIMEOUT == 20.0
    monkeypatch.setattr(vision_ask, "CAPTURE_TIMEOUT", 0.3)
    with pytest.raises(ServiceError) as error:
        await dispatch(show, await approving(show, []))
    assert error.value.code == "capture_timeout"
    assert provider.calls == [] and provider.closed == 1
    # A frame after the timeout is refused and never reaches a provider.
    (_, request, _), = events(show, "vision_capture_request")
    late = await show.app.sio.handlers["/"]["vision_capture_result"](
        "client", {"request_id": request["request_id"], "image": IMAGE})
    assert late["code"] == "unknown_request" and provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, code, words",
    [
        ("hidden", "capture_hidden", "JARVIS's window was hidden"),
        ("denied", "capture_denied", "camera access was denied"),
        ("busy", "capture_busy", "camera is busy"),
        ("failed", "capture_failed", "couldn't take the photo"),
    ],
)
async def test_capture_errors_become_plain_messages(show, error, code, words):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    task = asyncio.create_task(dispatch(show, await approving(show, [])))
    _, _, reply = await answer_capture(show, error=error)
    assert reply == {"ok": True}
    with pytest.raises(ServiceError) as failure:
        await task
    assert failure.value.code == code and words in str(failure.value)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_a_bad_frame_is_refused_without_a_provider_request(show):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    task = asyncio.create_task(dispatch(show, await approving(show, [])))
    _, _, reply = await answer_capture(show, image=base64.b64encode(b"GIF89a....").decode())
    assert reply["code"] == "image_invalid"
    with pytest.raises(ServiceError) as failure:
        await task
    assert failure.value.code == "capture_invalid" and provider.calls == []


@pytest.mark.asyncio
async def test_refusals_without_workspace_in_gaming_locked_or_without_image_support(show):
    provider = FakeVision()
    show.app.conversation.provider_factory = lambda: provider
    approve = await approving(show, [])
    # No owner workspace renderer (the tray only).
    roles = dict(show.app.sessions.roles)
    show.app.sessions.roles.update({"client": "resident"})
    with pytest.raises(ServiceError) as error:
        await show.app.dispatcher.dispatch(
            "owner", "look_through_camera", {"question": QUESTION},
            {"project_path": show.project, "origin_sid": "tray"}, approve)
    assert error.value.code == "workspace_unavailable" and "Open JARVIS" in str(error.value)
    show.app.sessions.roles.update(roles)
    # Gaming mode.
    show.app.resources.state = "gaming"
    with pytest.raises(ServiceError) as error:
        await dispatch(show, approve)
    assert error.value.code == "gaming_mode"
    show.app.resources.state = "chat"
    # A provider that can't take images.
    show.app.conversation.provider_factory = lambda: FakeVision(name="local")
    with pytest.raises(ServiceError) as error:
        await dispatch(show, approve)
    assert error.value.code == "image_unsupported"
    # Locked (face lock): refused before the approval card.
    show.app.settings["face_auth_enabled"] = True
    with pytest.raises(ServiceError) as error:
        await dispatch(show, approve)
    assert error.value.code == "authentication_required"
    assert events(show, "vision_capture_request") == [] and provider.calls == []


@pytest.mark.asyncio
async def test_gaming_or_closing_during_the_capture_ends_it(show):
    show.app.conversation.provider_factory = lambda: FakeVision()
    task = asyncio.create_task(dispatch(show, await approving(show, [])))
    await until(lambda: events(show, "vision_capture_request"))
    show.app.resources.state = "gaming"
    with pytest.raises(ServiceError) as error:
        await task
    assert error.value.code == "gaming_mode"
    show.app.resources.state = "chat"
    task = asyncio.create_task(dispatch(show, await approving(show, [])))
    await until(lambda: len(events(show, "vision_capture_request")) == 2)
    show.app.sessions.remove("client")
    with pytest.raises(ServiceError) as error:
        await task
    assert error.value.code == "workspace_closed"
    assert show.app.show_jarvis.pending == {}


@pytest.mark.asyncio
async def test_brain_tool_result_reaches_claude_as_text_only(show):
    """The brain's turn: tool_use -> approval -> one frame -> answer text in the tool result."""
    first = claude_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "look_through_camera",
          "input": {"question": QUESTION}}], stop="tool_use")
    second = claude_message([{"type": "text", "text": "It is a bracket, sir."}])
    client = ClaudeClient(([], first), (["It is a bracket, sir."], second))
    vision = FakeVision()
    providers = iter([ClaudeProvider(api_key="sk-ant-offline", client=client), vision])
    show.app.conversation.provider_factory = lambda: next(providers)

    async def renderer():
        await until(lambda: events(show, "tool_confirmation_request"))
        (_, card, _), = events(show, "tool_confirmation_request")
        assert card["tool"] == "look_through_camera"
        show.app.dispatcher.resolve("owner", card["id"], True)
        await answer_capture(show)

    helper = asyncio.create_task(renderer())
    await show.app.conversation_transport.user_input(
        "client", {"text": "Hey Jarvis, what's this?", "conversation_id": str(uuid.uuid4())})
    await helper
    (final,) = [data for _, data, _ in events(show, "transcription")]
    assert final["text"] == "It is a bracket, sir."
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and json.loads(result["content"]) == {"answer": ANSWER}
    assert "image" not in json.dumps(client.requests[1]["messages"])
    assert len(vision.calls) == 1
    assert_photo_nowhere(show)
