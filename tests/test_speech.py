"""R6 uses fixtures only: no microphone, provider, or playback device."""

import asyncio
import base64
import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from services.speech import SpeechFrame, SpeechSend
from services.tools import ServiceError


@pytest.fixture
def speech(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "other": "owner", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.settings["tool_permissions"]["start_audio"] = False
    app.speech.preflight = lambda: None

    async def transcribe(raw, partial):
        assert len(raw) == 3200
        await partial("Fixture")
        await partial("Fixture transcript")
        return "Fixture transcript"

    app.speech.transcriber = transcribe
    app.conversation.reply = AsyncMock(
        return_value=type("Answer", (), {"text": "Fixture answer"})()
    )
    return app


def args():
    return {"turn_id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4())}


async def call(app, name, data, sid="client"):
    return await app.sio.handlers["/"]["speech_" + name](sid, data)


async def recorded(app):
    value = args()
    assert (await call(app, "begin", value))["ok"]
    for sequence in range(5):
        assert (
            await call(
                app,
                "frame",
                {
                    "turn_id": value["turn_id"],
                    "sequence": sequence,
                    "timestamp_ms": sequence * 20,
                    "data": base64.b64encode(bytes(640)).decode(),
                },
            )
        )["ok"]
    return {"turn_id": value["turn_id"]}


@pytest.mark.asyncio
async def test_review_precedes_shared_conversation_and_release_discards_pcm(speech):
    turn = await recorded(speech)
    result = await call(speech, "finish", turn)
    assert result["text"] == "Fixture transcript"
    assert not speech.speech.turn.pcm
    speech.conversation.reply.assert_not_awaited()
    result = await call(speech, "send", {**turn, "text": "Edited by owner"})
    assert result["text"] == "Fixture answer" and speech.speech.turn is None
    request = speech.conversation.reply.await_args.args[1]
    assert request.text == "Edited by owner" and str(request.request_id) == turn["turn_id"]
    assert callable(speech.conversation.reply.await_args.kwargs["authorize"])


@pytest.mark.asyncio
async def test_reviewed_speech_returns_project_memory_sources(speech):
    from services.memory_contracts import MemorySource

    source = MemorySource(id=uuid.uuid4(), title="Fixture note", source="Owner review", version=2)
    speech.conversation.reply.return_value.memory_sources = [source]
    turn = await recorded(speech)
    await call(speech, "finish", turn)
    result = await call(speech, "send", {**turn, "text": "Reviewed question"})
    assert result["memory_sources"] == [source.model_dump(mode="json")]


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["other", "tray", "unknown"])
async def test_frame_owner_and_turn_isolation(speech, sid):
    turn = await recorded(speech)
    assert not (await call(speech, "finish", turn, sid))["ok"]
    assert speech.speech.turn is not None
    await speech.speech.stop()


@pytest.mark.asyncio
async def test_order_mismatch_fails_closed_and_does_not_transcribe(speech):
    value = args()
    await call(speech, "begin", value)
    result = await call(
        speech,
        "frame",
        {
            "turn_id": value["turn_id"],
            "sequence": 1,
            "timestamp_ms": 20,
            "data": base64.b64encode(bytes(640)).decode(),
        },
    )
    assert result["code"] == "speech_sequence" and speech.speech.turn is None
    speech.conversation.reply.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["project", "permission", "gaming", "gap"])
async def test_scope_and_resource_changes_invalidate_capture(speech, change):
    turn = await recorded(speech)
    if change == "project":
        speech.projects.create_project("Second")
        speech.projects.switch_project("Second")
    elif change == "permission":
        speech.settings["tool_permissions"]["start_audio"] = "deny"
    elif change == "gaming":
        speech.resources.state = "gaming"
    else:
        speech.speech.turn.touched -= 16
    assert not (await call(speech, "finish", turn))["ok"]
    assert speech.speech.turn is None


@pytest.mark.asyncio
async def test_cancel_pending_capture_approval_cannot_open_later(speech):
    speech.settings["tool_permissions"]["start_audio"] = True
    value = args()
    task = asyncio.create_task(call(speech, "begin", value))
    await asyncio.sleep(0)
    assert speech.dispatcher.pending
    await call(speech, "cancel", {"turn_id": value["turn_id"]})
    assert (
        task.cancelled() and not speech.dispatcher.pending and not speech.speech_transport.pending
    )
    assert speech.speech.turn is None


@pytest.mark.asyncio
async def test_disconnect_cancels_transcription_and_no_replay(speech):
    turn = await recorded(speech)
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def waiting(raw, partial):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    speech.speech.transcriber = waiting
    task = asyncio.create_task(call(speech, "finish", turn))
    await entered.wait()
    await speech.speech_transport.stop_sid("client")
    assert task.cancelled() and closed.is_set() and speech.speech.turn is None
    assert not (await call(speech, "finish", turn))["ok"]


@pytest.mark.asyncio
async def test_preflight_failure_never_allocates_or_prompts(speech):
    def missing():
        raise ServiceError("provider_unconfigured", "Configure later; use typed input.")

    speech.speech.preflight = missing
    assert (await call(speech, "begin", args()))["code"] == "provider_unconfigured"
    assert speech.speech.turn is None and not speech.dispatcher.pending


@pytest.mark.parametrize(
    "field,value",
    [
        ("channels", True),
        ("sample_rate", "16000"),
        ("duration_ms", True),
        ("sequence", False),
        ("timestamp_ms", 1.5),
        ("data", "x" * 857),
        ("codec", "opus"),
    ],
)
def test_pcm_contract_rejects_coercion_and_unbounded_data(field, value):
    frame = {
        "turn_id": uuid.uuid4(),
        "sequence": 0,
        "timestamp_ms": 0,
        "data": base64.b64encode(bytes(640)).decode(),
        field: value,
    }
    with pytest.raises(ValidationError):
        SpeechFrame.model_validate(frame)


def test_empty_review_rejected():
    with pytest.raises(ValidationError):
        SpeechSend(turn_id=uuid.uuid4(), text="   ")


@pytest.mark.asyncio
async def test_capture_denial_and_permission_revocation_after_approval(speech):
    for name in ("start_audio", "speech_capture"):
        speech.settings["tool_permissions"][name] = "deny"
        assert (await call(speech, "begin", args()))["code"] == "permission_denied"
        assert speech.speech.turn is None
        speech.settings["tool_permissions"][name] = False
    turn = await recorded(speech)
    speech.settings["tool_permissions"]["speech_capture"] = "deny"
    assert (await call(speech, "finish", turn))["code"] == "permission_denied"
    assert speech.speech.turn is None
    speech.settings["tool_permissions"]["speech_capture"] = False
    speech.settings["tool_permissions"]["start_audio"] = True
    task = asyncio.create_task(call(speech, "begin", args()))
    await asyncio.sleep(0)
    identifier = next(iter(speech.dispatcher.pending))
    speech.settings["tool_permissions"]["start_audio"] = "deny"
    speech.dispatcher.resolve("owner", identifier, True)
    assert (await task)["code"] == "permission_denied"
    assert speech.speech.turn is None


@pytest.mark.asyncio
async def test_typed_interruption_is_origin_bound_and_owner_gated(speech):
    waiting = asyncio.create_task(asyncio.Event().wait())
    speech.conversation_transport.running[waiting] = "client"
    handler = speech.sio.handlers["/"]["cancel_conversation"]
    assert not (await handler("tray", {}))["ok"]
    assert not waiting.done()
    assert (await handler("other", {}))["ok"]
    assert not waiting.done()
    assert (await handler("client", {}))["ok"]
    assert waiting.cancelled()
    speech.conversation_transport.running.clear()


@pytest.mark.asyncio
async def test_speech_tools_use_normal_dispatcher_and_provider_cleanup(speech):
    from services.conversation import ConversationService
    from llm.base import LLMResponse, ToolCall

    speech.settings["tool_permissions"]["write_file"] = "deny"

    class Provider:
        closed = False
        index = 0

        async def generate(self, messages, **kwargs):
            self.index += 1
            assert "speech_capture" not in {
                item["name"] for item in kwargs["tools"][0]["function_declarations"]
            }
            if self.index == 1:
                return LLMResponse(
                    tool_calls=[
                        ToolCall("one", "write_file", {"path": "blocked.txt", "content": "no"})
                    ]
                )
            assert "permission_denied" in messages[-1].content
            return LLMResponse(text="Write was declined")

        async def close(self):
            self.closed = True

    provider = Provider()
    speech.conversation = ConversationService(speech.dispatcher, lambda: provider)
    turn = await recorded(speech)
    await call(speech, "finish", turn)
    assert (await call(speech, "send", {**turn, "text": "Write a file"}))[
        "text"
    ] == "Write was declined"
    assert (
        provider.closed
        and not (speech.projects.get_current_project_path() / "blocked.txt").exists()
    )


@pytest.mark.asyncio
async def test_transcription_adapter_wraps_wav_streams_and_closes(monkeypatch):
    import io
    import wave
    from types import SimpleNamespace
    from google import genai
    from services import speech_provider

    closed = []
    partials = []

    async def generate(**kwargs):
        with wave.open(io.BytesIO(kwargs["contents"][0].inline_data.data)) as audio:
            assert (
                audio.getframerate(),
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getnframes(),
            ) == (16000, 1, 2, 1600)

        async def stream():
            for text in ["Fixture ", "words"]:
                yield SimpleNamespace(text=text)

        return stream()

    async def close():
        closed.append(True)

    async def partial(value):
        partials.append(value)

    monkeypatch.setattr(speech_provider, "ready", lambda: None)
    monkeypatch.setattr(speech_provider, "provider_key", lambda: "fixture-key")
    monkeypatch.setattr(
        genai,
        "Client",
        lambda **kwargs: SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content_stream=generate), aclose=close
            )
        ),
    )
    assert await speech_provider.transcribe(bytes(3200), partial) == "Fixture words"
    assert partials == ["Fixture ", "Fixture words"] and closed == [True]


def test_speech_model_override_is_independent_and_falls_back_to_text(monkeypatch):
    from services.capability_profiles import model_id

    monkeypatch.setenv("INARA_TEXT_MODEL", "fixture-text")
    monkeypatch.delenv("INARA_TRANSCRIPTION_MODEL", raising=False)
    assert model_id("speech") == "fixture-text"
    monkeypatch.setenv("INARA_TRANSCRIPTION_MODEL", "fixture-transcriber")
    assert model_id("speech") == "fixture-transcriber"
    assert model_id("text") == "fixture-text"


def test_native_hotkey_requests_quick_and_tray_open_requests_full():
    from resident.win32 import Tray

    actions = []
    tray = object.__new__(Tray)
    tray.on_action = actions.append
    assert tray._message(None, 0x312, 0, 0) == 0
    assert tray._message(None, tray.OPEN, 0, 0) == 0
    assert actions == ["quick", "open"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["disconnect", "restrict", "close"])
async def test_root_lifecycle_cancels_pending_speech_approval(speech, operation):
    speech.settings["tool_permissions"]["start_audio"] = True
    task = asyncio.create_task(call(speech, "begin", args()))
    await asyncio.sleep(0)
    assert speech.dispatcher.pending
    if operation == "disconnect":
        await speech.disconnect("client")
    elif operation == "restrict":
        await speech.restrict_resources()
    else:
        await speech.close()
    assert (
        task.cancelled() and not speech.dispatcher.pending and not speech.speech_transport.pending
    )
    assert speech.speech.turn is None
