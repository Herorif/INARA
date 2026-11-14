"""Live voice with a fake Live session: no network, microphone, speaker or provider."""

import asyncio
from contextlib import asynccontextmanager
import uuid

import pytest
from google.genai import types

from llm.base import LLMResponse, ToolCall
from llm.pricing import estimate_microusd
from services.usage import live_usage_counts


class FakeLive:
    def __init__(self, model, config):
        self.model, self.config = model, config
        self.inbox = asyncio.Queue()
        self.sent = []
        self.tool_responses = []
        self.closed = False

    async def send_realtime_input(self, **values):
        self.sent.append(values)

    async def send_tool_response(self, *, function_responses):
        self.tool_responses.append(function_responses)

    async def receive(self):
        # Like the SDK: one call yields one model turn, then the caller receives again.
        while True:
            item = await self.inbox.get()
            if isinstance(item, BaseException):
                raise item
            yield item
            if item.server_content and item.server_content.turn_complete:
                return

    def push(self, **content):
        self.inbox.put_nowait(types.LiveServerMessage(server_content=types.LiveServerContent(**content)))

    def message(self, **values):
        self.inbox.put_nowait(types.LiveServerMessage(**values))


class FakeConnector:
    def __init__(self):
        self.connections = []
        self.fail = None

    @asynccontextmanager
    async def __call__(self, model, config):
        if self.fail:
            raise self.fail
        live = FakeLive(model, config)
        self.connections.append(live)
        try:
            yield live
        finally:
            live.closed = True


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append(list(messages))
        return next(self.responses)

    async def close(self):
        pass


@pytest.fixture
def voice(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update(
        {"client": "owner", "other": "owner", "tray": "owner", "intruder": "stranger"}
    )
    app.sessions.roles.update(
        {"client": "renderer", "other": "renderer", "tray": "resident", "intruder": "renderer"}
    )
    connector = FakeConnector()
    app.voice.connector = connector
    app.voice.preflight = lambda: None
    app.voice.retry_delay = 0
    app.voice.tick = 0.01
    return app, connector


async def until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(0.005)


def emitted(app, event):
    return [call.args[1] for call in app.sio.emit.await_args_list if call.args[0] == event]


def states(app):
    return [payload["state"] for payload in emitted(app, "voice_state")]


async def ended(app):
    await until(lambda: not app.voice.sessions and states(app)[-1] in ("ended", "error"))
    return emitted(app, "voice_state")[-1]


async def call(app, name, data, sid="client"):
    return await app.sio.handlers["/"]["voice_" + name](sid, data)


async def start(app, connector, mode="push_to_talk", conversation_id=None):
    count = len(connector.connections)
    ack = await call(
        app, "start", {"mode": mode, "conversation_id": str(conversation_id or uuid.uuid4())}
    )
    assert ack["ok"], ack
    await until(lambda: len(connector.connections) > count)
    live = connector.connections[-1]
    await until(lambda: app.voice.sessions["owner"].live is live)
    return ack, live


def audio(session_id, seq, size=640):
    return {"session_id": session_id, "seq": seq, "pcm": bytes(size)}


@pytest.mark.asyncio
async def test_start_ack_rates_and_stop_lifecycle(voice):
    app, connector = voice
    ack, live = await start(app, connector)
    assert set(ack) == {"ok", "session_id", "input_rate", "output_rate"}
    assert uuid.UUID(ack["session_id"]) and (ack["input_rate"], ack["output_rate"]) == (16000, 24000)
    assert live.model == "gemini-3.8-live"
    assert states(app)[-1] == "idle"
    assert all(call.kwargs["room"] == "client" for call in app.sio.emit.await_args_list)
    assert (await call(app, "stop", {"session_id": ack["session_id"]})) == {"ok": True}
    assert states(app)[-1] == "ended" and emitted(app, "voice_state")[-1]["code"] == "stopped"
    assert live.closed and not app.voice.sessions
    # Idempotent: stopping an unknown or finished session still acknowledges.
    assert (await call(app, "stop", {"session_id": ack["session_id"]})) == {"ok": True}


@pytest.mark.asyncio
async def test_start_refusal_codes(voice, monkeypatch):
    app, connector = voice
    conversation = str(uuid.uuid4())
    assert (await call(app, "start", {"mode": "shout", "conversation_id": conversation}))[
        "code"
    ] == "invalid_arguments"
    assert (await call(app, "start", {"mode": "push_to_talk"}))["code"] == "invalid_arguments"
    payload = {"mode": "push_to_talk", "conversation_id": conversation}
    assert (await call(app, "start", payload, sid="tray"))["code"] == "authentication_required"
    assert (await call(app, "start", payload, sid="intruder"))["code"] == "permission_denied"
    app.settings["tool_permissions"]["start_audio"] = "deny"
    assert (await call(app, "start", payload))["code"] == "permission_denied"
    app.settings["tool_permissions"]["start_audio"] = False
    app.resources.select("gaming")
    assert (await call(app, "start", payload))["code"] == "gaming_mode"
    app.resources.select("resident")
    assert (await call(app, "start", payload))["code"] == "resource_policy"
    app.resources.select("chat")
    import services.voice as voice_module

    monkeypatch.setattr(voice_module, "provider_key", lambda: None)
    app.voice.preflight = voice_module.ready
    failure = await call(app, "start", payload)
    assert failure == {
        "ok": False,
        "code": "provider_not_configured",
        "message": "Voice needs a Gemini API key. Add one in Setup, or type a message.",
    }
    assert not connector.connections and not app.voice.sessions
    app.voice.preflight = lambda: None
    ack, _ = await start(app, connector)
    # One voice session per owner, from any of the owner's renderers.
    assert (await call(app, "start", payload, sid="other"))["code"] == "voice_busy"
    assert (await call(app, "start", payload))["code"] == "voice_busy"
    await call(app, "stop", {"session_id": ack["session_id"]})
    assert (await call(app, "start", payload))["ok"]
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_push_to_talk_activity_and_audio_relay_both_ways(voice):
    app, connector = voice
    ack, live = await start(app, connector)
    session_id = ack["session_id"]
    # Outside a hold nothing is relayed: the microphone belongs to the hold.
    await call(app, "audio", audio(session_id, 0))
    assert await call(app, "activity", {"session_id": session_id, "state": "start"}) == {"ok": True}
    assert states(app)[-1] == "listening"
    for seq in (1, 2, 2, 1, 3):  # duplicates and stale frames are dropped
        await call(app, "audio", audio(session_id, seq, 1280))
    await call(app, "audio", audio(str(uuid.uuid4()), 9))  # unknown session
    await call(app, "audio", audio(session_id, 4), sid="other")  # another renderer
    await call(app, "audio", {"session_id": session_id, "seq": 5, "pcm": bytes(641)})  # odd bytes
    await call(app, "audio", {"session_id": session_id, "seq": 6, "pcm": bytes(6400)})  # >100 ms
    assert await call(app, "activity", {"session_id": session_id, "state": "end"}) == {"ok": True}
    assert states(app)[-1] == "thinking"
    await until(lambda: len(live.sent) == 5)
    assert list(live.sent[0]) == ["activity_start"] and list(live.sent[-1]) == ["activity_end"]
    blobs = [item["audio"] for item in live.sent[1:4]]
    assert all(blob.mime_type == "audio/pcm;rate=16000" and len(blob.data) == 1280 for blob in blobs)
    chunk = b"\x01\x00" * 1200
    live.push(
        model_turn=types.Content(
            role="model",
            parts=[types.Part(inline_data=types.Blob(data=chunk, mime_type="audio/pcm;rate=24000"))],
        )
    )
    await until(lambda: emitted(app, "voice_audio_out"))
    out = emitted(app, "voice_audio_out")[0]
    assert out == {"session_id": session_id, "seq": 1, "pcm": chunk}
    assert states(app)[-1] == "speaking"
    live.push(turn_complete=True)
    await until(lambda: states(app)[-1] == "idle")
    assert (await call(app, "activity", {"session_id": session_id, "state": "sideways"}))[
        "code"
    ] == "invalid_arguments"
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_conversation_mode_uses_server_vad_and_barge_in(voice):
    app, connector = voice
    ack, live = await start(app, connector, mode="conversation")
    assert live.config.realtime_input_config.automatic_activity_detection.disabled is False
    assert {item.name for item in live.config.tools[0].function_declarations} == {
        "ask_brain",
        "quick_weather",
        "quick_agenda",
        "end_conversation",
    }
    assert states(app)[-1] == "listening"
    await call(app, "audio", audio(ack["session_id"], 0))
    await until(lambda: live.sent)
    assert "audio" in live.sent[0]
    assert (await call(app, "activity", {"session_id": ack["session_id"], "state": "start"}))[
        "code"
    ] == "voice_mode"
    live.push(output_transcription=types.Transcription(text="The weather is"))
    live.push(interrupted=True)
    await until(lambda: emitted(app, "voice_interrupted"))
    assert emitted(app, "voice_interrupted") == [{"session_id": ack["session_id"]}]
    assert emitted(app, "voice_caption")[-1] == {
        "session_id": ack["session_id"],
        "role": "jarvis",
        "text": "The weather is",
        "final": True,
    }
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_captions_stream_and_append_to_the_shared_conversation(voice):
    app, connector = voice
    conversation_id = uuid.uuid4()
    ack, live = await start(app, connector, conversation_id=conversation_id)
    live.push(input_transcription=types.Transcription(text="What time"))
    live.push(input_transcription=types.Transcription(text=" is it?"))
    live.push(output_transcription=types.Transcription(text="It is"))
    live.push(output_transcription=types.Transcription(text=" nine."))
    live.push(turn_complete=True)
    project = app.projects.get_current_project_path().resolve()

    def history():
        return app.conversation.restore("owner", conversation_id, project)

    await until(lambda: len(history()) == 2)
    assert history() == [
        {"role": "user", "content": "What time is it?"},
        {"role": "assistant", "content": "It is nine."},
    ]
    captions = [(item["role"], item["text"], item["final"]) for item in emitted(app, "voice_caption")]
    assert captions == [
        ("user", "What time", False),
        ("user", "What time is it?", False),
        ("jarvis", "It is", False),
        ("jarvis", "It is nine.", False),
        ("user", "What time is it?", True),
        ("jarvis", "It is nine.", True),
    ]
    # A later exchange appends after the first; roles keep alternating.
    live.push(input_transcription=types.Transcription(text="Thanks"))
    live.push(output_transcription=types.Transcription(text="You're welcome."))
    live.push(turn_complete=True)
    await until(lambda: len(history()) == 4)
    assert [item["role"] for item in history()] == ["user", "assistant", "user", "assistant"]
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_ask_brain_runs_a_conversation_turn_with_unchanged_approvals(voice):
    app, connector = voice
    project = app.projects.get_current_project_path().resolve()
    app.settings["tool_permissions"]["write_file"] = True  # requires the owner's approval
    provider = FakeProvider(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "write_file", {"path": "note.txt", "content": "hi"})],
            ),
            LLMResponse(text="Saved note.txt with your text."),
        ]
    )
    app.conversation.provider_factory = lambda: provider
    conversation_id = uuid.uuid4()
    ack, live = await start(app, connector, conversation_id=conversation_id)
    live.push(input_transcription=types.Transcription(text="Save a note saying hi"))
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(
                    id="fc-1", name="ask_brain", args={"request": "Save a note saying hi"}
                )
            ]
        )
    )
    await until(lambda: emitted(app, "tool_confirmation_request"))
    assert states(app)[-1] == "working"
    approval = emitted(app, "tool_confirmation_request")[0]
    assert approval["voice_session_id"] == ack["session_id"] and approval["tool"] == "write_file"
    assert not (project / "note.txt").exists()
    assert not app.dispatcher.resolve("stranger", approval["id"], True)
    assert app.dispatcher.resolve("owner", approval["id"], True)
    await until(lambda: live.tool_responses)
    (response,) = live.tool_responses[0]
    assert (response.id, response.name) == ("fc-1", "ask_brain")
    assert response.response == {"result": "Saved note.txt with your text."}
    assert (project / "note.txt").read_text() == "hi"
    shown = emitted(app, "transcription")[-1]
    assert shown["text"] == "Saved note.txt with your text." and shown["sender"] == "JARVIS"
    assert shown["conversation_id"] == str(conversation_id)
    # The model speaks a condensed answer; the brain already recorded the exchange.
    live.push(output_transcription=types.Transcription(text="Done, the note is saved."))
    live.push(turn_complete=True)
    await until(lambda: states(app)[-1] == "idle")
    await asyncio.sleep(0.05)
    history = app.conversation.restore("owner", conversation_id, project)
    assert history == [
        {"role": "user", "content": "Save a note saying hi"},
        {"role": "assistant", "content": "Saved note.txt with your text."},
    ]
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_stopping_voice_cancels_a_pending_brain_approval(voice):
    app, connector = voice
    app.settings["tool_permissions"]["write_file"] = True
    provider = FakeProvider(
        [LLMResponse(text="", tool_calls=[ToolCall("c", "write_file", {"path": "x.txt", "content": "x"})])]
    )
    app.conversation.provider_factory = lambda: provider
    ack, live = await start(app, connector)
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="fc", name="ask_brain", args={"request": "write x"})]
        )
    )
    await until(lambda: app.dispatcher.pending)
    identifier = emitted(app, "tool_confirmation_request")[0]["id"]
    await call(app, "stop", {"session_id": ack["session_id"]})
    assert not app.dispatcher.pending and not app.dispatcher.resolve("owner", identifier, True)
    assert not (app.projects.get_current_project_path() / "x.txt").exists()
    assert not live.tool_responses


@pytest.mark.asyncio
async def test_unknown_tools_and_bad_brain_arguments_are_refused(voice):
    app, connector = voice
    _, live = await start(app, connector)
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(id="a", name="write_file", args={"path": "x"}),
                types.FunctionCall(id="b", name="ask_brain", args={"request": 5}),
                types.FunctionCall(id="c", name="end_conversation", args={}),
            ]
        )
    )
    await until(lambda: len(live.tool_responses) == 3)
    responses = {item[0].id: item[0].response for item in live.tool_responses}
    assert responses["a"]["error"] == "tool_unavailable"
    assert responses["b"]["error"] == "invalid_arguments"
    assert responses["c"]["error"] == "tool_unavailable"  # push-to-talk has no end_conversation
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_end_conversation_finishes_the_goodbye_then_ends(voice):
    app, connector = voice
    _, live = await start(app, connector, mode="conversation")
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="bye", name="end_conversation", args={})]
        )
    )
    await until(lambda: live.tool_responses)
    assert app.voice.sessions
    live.push(output_transcription=types.Transcription(text="Goodbye."))
    live.push(turn_complete=True)
    assert (await ended(app))["code"] == "conversation_ended"


@pytest.mark.asyncio
async def test_go_away_and_dropped_connection_resume_with_the_stored_handle(voice):
    app, connector = voice
    ack, first = await start(app, connector, mode="conversation")
    assert first.config.session_resumption.handle is None
    assert first.config.context_window_compression.sliding_window is not None
    first.message(
        session_resumption_update=types.LiveServerSessionResumptionUpdate(
            new_handle="handle-1", resumable=True
        )
    )
    first.message(go_away=types.LiveServerGoAway(time_left="5s"))
    await until(lambda: len(connector.connections) == 2)
    second = connector.connections[1]
    assert first.closed and second.config.session_resumption.handle == "handle-1"
    await until(lambda: app.voice.sessions["owner"].live is second)
    second.message(
        session_resumption_update=types.LiveServerSessionResumptionUpdate(
            new_handle="handle-2", resumable=True
        )
    )
    second.inbox.put_nowait(ConnectionResetError("dropped"))
    await until(lambda: len(connector.connections) == 3)
    third = connector.connections[2]
    assert third.config.session_resumption.handle == "handle-2"
    await until(lambda: app.voice.sessions["owner"].live is third)
    # Audio sent during the reconnect is relayed by the resumed connection.
    await call(app, "audio", audio(ack["session_id"], 0))
    await until(lambda: third.sent)
    assert app.voice.sessions["owner"].id == ack["session_id"]
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_drop_without_a_handle_or_failed_connect_reports_an_error(voice):
    app, connector = voice
    _, live = await start(app, connector)
    live.inbox.put_nowait(ConnectionResetError("dropped"))
    assert (await ended(app)) == {
        "session_id": app.sio.emit.await_args.args[1]["session_id"],
        "state": "error",
        "code": "offline",
        "message": "Voice lost its connection. Check the network and try again.",
    }
    connector.fail = OSError("no network")
    ack = await call(app, "start", {"mode": "push_to_talk", "conversation_id": str(uuid.uuid4())})
    assert ack["ok"]
    assert (await ended(app))["code"] == "offline"


VOICE_MARKER = "LIVE-MESSAGE-MARKER-5521"


def raised_api_error(code, status, close=None):
    """The APIError the SDK raises, optionally while handling a websocket close."""
    from google.genai import errors

    body = {"error": {"code": code, "status": status, "message": VOICE_MARKER}}
    try:
        if close is not None:
            try:
                from websockets.exceptions import ConnectionClosedError
                from websockets.frames import Close

                raise ConnectionClosedError(Close(close, VOICE_MARKER), None)
            except ConnectionClosedError:
                errors.APIError.raise_error(code, body, None)
        errors.APIError.raise_error(code, body, None)
    except errors.APIError as exc:
        return exc


def voice_lines(caplog, prefix):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


@pytest.mark.asyncio
async def test_live_drop_and_failure_lines_carry_codes_never_the_message(voice, caplog):
    import logging

    caplog.set_level(logging.INFO)
    app, connector = voice
    _, live = await start(app, connector, mode="conversation")
    live.message(
        session_resumption_update=types.LiveServerSessionResumptionUpdate(
            new_handle="handle-1", resumable=True
        )
    )
    await until(lambda: app.voice.sessions["owner"].handle == "handle-1")
    live.inbox.put_nowait(raised_api_error(1011, "INTERNAL", close=1011))
    await until(lambda: len(connector.connections) == 2)
    assert voice_lines(caplog, "Live voice dropped") == [
        "Live voice dropped; resuming (APIError code=1011 status=INTERNAL close=1011)"
    ]
    await app.voice.stop_sid()

    connector.fail = raised_api_error(503, "UNAVAILABLE")
    ack = await call(app, "start", {"mode": "push_to_talk", "conversation_id": str(uuid.uuid4())})
    assert ack["ok"]
    await ended(app)
    assert voice_lines(caplog, "Live voice failed") == [
        "Live voice failed: ServerError code=503 status=UNAVAILABLE close=-"
    ]
    assert VOICE_MARKER not in caplog.text


def test_failure_fields_for_plain_errors():
    from services.voice import failure_fields

    assert failure_fields(ConnectionResetError(VOICE_MARKER)) == (
        "ConnectionResetError code=- status=- close=-"
    )


@pytest.mark.asyncio
async def test_silence_ends_the_session_but_not_while_the_brain_works(voice):
    app, connector = voice
    started = asyncio.Event()
    release = asyncio.Event()

    async def reply(*args, **kwargs):
        started.set()
        await release.wait()
        return type("Answer", (), {"text": "Done", "memory_sources": []})()

    app.conversation.reply = reply
    app.voice.silence = 0.1
    _, live = await start(app, connector, mode="conversation")
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="w", name="ask_brain", args={"request": "work"})]
        )
    )
    await started.wait()
    await asyncio.sleep(0.3)
    assert app.voice.sessions  # brain work is not silence
    release.set()
    await until(lambda: live.tool_responses)
    assert (await ended(app))["code"] == "silence_timeout"
    assert live.closed


@pytest.mark.asyncio
async def test_gaming_mode_lock_project_change_and_disconnect_stop_voice(voice):
    app, connector = voice
    _, live = await start(app, connector)
    await app.sio.handlers["/"]["set_resource_state"]("client", {"state": "gaming"})
    assert (await ended(app))["code"] == "gaming_mode" and live.closed
    app.resources.select("chat")
    await start(app, connector)
    app.projects.create_project("Second")
    app.projects.switch_project("Second")
    assert (await ended(app))["code"] == "voice_scope"
    await start(app, connector)
    app.settings["face_auth_enabled"] = True  # locked: the owner is no longer authenticated
    assert (await ended(app))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = False
    _, live = await start(app, connector)
    await app.disconnect("client")
    assert not app.voice.sessions and live.closed


@pytest.mark.asyncio
async def test_live_usage_metadata_becomes_priced_receipts(voice):
    app, connector = voice
    _, live = await start(app, connector)
    live.message(
        usage_metadata=types.UsageMetadata(
            prompt_token_count=1000,
            response_token_count=500,
            total_token_count=1500,
            prompt_tokens_details=[
                types.ModalityTokenCount(modality=types.MediaModality.AUDIO, token_count=800),
                types.ModalityTokenCount(modality=types.MediaModality.TEXT, token_count=200),
            ],
            response_tokens_details=[
                types.ModalityTokenCount(modality=types.MediaModality.AUDIO, token_count=500)
            ],
        )
    )
    project = app.projects.get_current_project_path().resolve()

    def receipts():
        return [
            item
            for item in app.usage.snapshot("owner", project)["records"]
            if item["feature"] == "voice_live"
        ]

    await until(lambda: any(item["tokens"] for item in receipts()))
    done = next(item for item in receipts() if item["tokens"])
    assert done["model"] == "gemini-3.8-live" and done["state"] == "completed"
    assert done["tokens"]["input_audio_tokens"] == 800
    assert done["tokens"]["output_audio_tokens"] == 500
    # 800*3.00 + 200*0.75 + 500*12.00 micro-USD
    assert done["estimated_cost_microusd"] == 2400 + 150 + 6000
    assert "voice_live" in app.usage.snapshot("owner", project)["coverage"]
    await app.voice.stop_sid()
    assert len(receipts()) == 2  # the open turn closes as uncertain (no counts)
    assert {item["state"] for item in receipts()} == {"completed", "uncertain"}


def test_live_usage_counts_and_price_table():
    counts = live_usage_counts(
        {
            "prompt_token_count": 10,
            "response_token_count": 4,
            "thoughts_token_count": 2,
            "prompt_tokens_details": [{"modality": "AUDIO", "token_count": 6}],
            "response_tokens_details": [{"modality": "TEXT", "token_count": 4}],
        }
    )
    assert counts == {
        "input_tokens": 10,
        "output_tokens": 4,
        "thinking_tokens": 2,
        "input_audio_tokens": 6,
        "output_text_tokens": 4,
    }
    # 6 audio @3.00, 4 unlabelled input @3.00 (audio, conservative), 4 text out @4.50,
    # 2 thinking @4.50 -> 18 + 12 + 18 + 9 micro-USD
    assert estimate_microusd("gemini-3.8-live", counts) == 57
    assert estimate_microusd("models/gemini-3.8-live", counts) == 57
    assert estimate_microusd("gemini-3.8-live", None) is None
    assert live_usage_counts(None) is None


@pytest.mark.asyncio
async def test_inert_fixture_provider_runs_a_full_turn_and_interruption(voice):
    from services.voice_fixture import JARVIS_CAPTION, USER_CAPTION, FixtureLive

    app, _ = voice
    fixture = FixtureLive(chunks=20, pace=0.02)
    app.voice.connector = fixture
    ack = await call(app, "start", {"mode": "push_to_talk", "conversation_id": str(uuid.uuid4())})
    session_id = ack["session_id"]
    await until(lambda: fixture.sessions and app.voice.sessions["owner"].live)
    await call(app, "activity", {"session_id": session_id, "state": "start"})
    await call(app, "audio", audio(session_id, 0))
    await call(app, "activity", {"session_id": session_id, "state": "end"})
    await until(lambda: len(emitted(app, "voice_audio_out")) >= 3)
    texts = {item["text"] for item in emitted(app, "voice_caption")}
    assert {USER_CAPTION, JARVIS_CAPTION} <= texts
    assert all(len(item["pcm"]) == 4800 for item in emitted(app, "voice_audio_out"))
    await call(app, "activity", {"session_id": session_id, "state": "start"})
    await until(lambda: emitted(app, "voice_interrupted"))
    assert app.voice.sessions["owner"].handle == "fixture-resumption-handle"
    await app.voice.stop_sid()
