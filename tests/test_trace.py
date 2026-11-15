"""S4.1 flight recorder (services/trace.py): ring buffer, brain and voice spans, no text
unless diagnostics.include_text, owner-only routes. Fake providers and a fake Live session;
no network, audio or real clock waits beyond a few milliseconds."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
import uuid

import pytest
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from llm.base import LLMResponse, ToolCall
from services.conversation import ConversationRequest, ConversationService
from services.settings import (
    DIAGNOSTICS_DEFAULTS,
    SettingsPatch,
    SettingsService,
    diagnostics_settings,
)
from services.tools import ServiceError, ToolDispatcher, ToolSpec
from services.trace import TEXT_LIMIT, TRACE_LIMIT, TraceService

MARKER = "TRACE-MARKER-93kq in Seremban for Aisyah"


def all_text(value):
    return json.dumps(value, ensure_ascii=False)


# --- fakes ------------------------------------------------------------------------------


class Script:
    def __init__(self, steps, name="claude", model="claude-sonnet-5-5"):
        self.name, self._model, self.reports_progress = name, model, True
        self.effort = "high"
        self.steps = list(steps)

    async def generate(self, messages, **kwargs):
        step = self.steps.pop(0)
        return await step(kwargs) if callable(step) else step

    async def close(self):
        pass


def claude_usage(input_tokens, output_tokens):
    return SimpleNamespace(content=[], usage=SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0,
    ))


def text(value, raw=None):
    return LLMResponse(text=value, content_blocks=[{"type": "text", "text": value}], raw=raw)


def tools(*names, raw=None):
    calls = [ToolCall(f"call-{index}", name, {"place": MARKER}) for index, name in enumerate(names)]
    blocks = [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
              for call in calls]
    return LLMResponse(tool_calls=calls, content_blocks=blocks, raw=raw)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: str


def make_dispatcher():
    made = ToolDispatcher(lambda: {"weather": False, "send_note": "ask"})

    async def weather(args, context):
        await asyncio.sleep(0.01)
        return {"forecast": "clear"}

    async def send_note(args, context):
        return {"sent": True}

    made.register(ToolSpec("weather", "Forecast.", Args, weather))
    made.register(ToolSpec("send_note", "Send a note.", Args, send_note, always_ask=True))
    return made


def traced(provider, settings=None):
    trace = TraceService(settings=lambda: settings or {})
    dispatcher = make_dispatcher()
    service = ConversationService(dispatcher, lambda: provider, fast_provider_factory=lambda: provider)
    service.tracer = trace
    return service, dispatcher, trace


def approver(dispatcher, answer, delay=0.02):
    async def approve(payload):
        async def later():
            await asyncio.sleep(delay)
            if answer is not None:
                dispatcher.resolve("owner", payload["id"], answer)

        asyncio.get_running_loop().create_task(later())

    return approve


# --- ring buffer --------------------------------------------------------------------------


def fake_timing(index):
    return {"request_id": f"id-{index}", "origin": "chat", "provider": "claude", "model": "m",
            "effort": None, "first_token_ms": 1, "total_ms": 10, "outcome": "ok",
            "input_tokens": 1, "output_tokens": 1}


def test_ring_buffer_keeps_the_last_200_newest_first():
    trace = TraceService(settings=lambda: {})
    for index in range(TRACE_LIMIT + 25):
        trace.record_turn(fake_timing(index), SimpleNamespace(steps=[]))
    assert len(trace.traces) == TRACE_LIMIT
    newest = trace.recent(limit=3)
    assert [item["id"] for item in newest] == ["id-224", "id-223", "id-222"]
    assert len(trace.recent()) == 50 and len(trace.recent(limit=500)) == TRACE_LIMIT
    assert trace.get("id-0") is None and trace.get("id-25")["id"] == "id-25"
    # get/recent hand out copies: changing one never changes the recorder.
    trace.get("id-25")["spans"].append({"kind": "x"})
    assert trace.get("id-25")["spans"] == []
    trace.clear()
    assert trace.recent() == [] and trace.get("id-30") is None


# --- brain turns --------------------------------------------------------------------------


async def test_a_turn_records_model_tool_and_approval_spans_without_text(tmp_path):
    provider = Script([
        tools("weather", raw=claude_usage(100, 20)),
        tools("send_note", raw=claude_usage(120, 10)),
        text(f"Done. {MARKER}", raw=claude_usage(50, 10)),
    ])
    service, dispatcher, trace = traced(provider)
    request = ConversationRequest(text=f"Weather, then a note. {MARKER}")
    result = await service.reply("owner", request, tmp_path, approver(dispatcher, True))
    assert result.text.startswith("Done")
    (item,) = trace.recent()
    assert item["id"] == str(request.request_id)
    assert item["origin"] == "chat" and item["outcome"] == "ok"
    assert item["provider"] == "claude" and item["model"] == "claude-sonnet-5-5"
    assert item["effort"] == "high"
    assert item["tokens"] == {"input": 270, "output": 40}
    assert isinstance(item["cost_usd"], float) and item["cost_usd"] > 0
    assert item["total_ms"] >= 0 and isinstance(item["first_token_ms"], int)
    kinds = [(span["kind"], span.get("name")) for span in item["spans"]]
    assert kinds == [
        ("model", "claude"), ("tool", "weather"), ("model", "claude"),
        ("tool", "send_note"), ("approval", "send_note"), ("model", "claude"),
    ]
    for span in item["spans"]:
        assert isinstance(span["start_ms"], int) and span["start_ms"] >= 0
        assert isinstance(span["ms"], int) and span["ms"] >= 0
    weather = item["spans"][1]
    assert weather["outcome"] == "ok" and weather["ms"] >= 5
    approval = item["spans"][4]
    assert approval["outcome"] == "approved" and approval["ms"] >= 10
    assert item["approvals"] == [
        {"tool": "send_note", "asked_ms": approval["start_ms"], "answer": "approved"}
    ]
    starts = [span["start_ms"] for span in item["spans"]]
    assert starts == sorted(starts)
    # No message text, tool arguments, places or names anywhere in the trace.
    dumped = all_text(item)
    for word in ("TRACE-MARKER", "Seremban", "Aisyah", "Weather, then"):
        assert word not in dumped
    assert "request_text" not in item and "answer_text" not in item


@pytest.mark.parametrize("answer, expected", [(False, "denied"), (None, "timeout")])
async def test_declined_and_expired_approvals(tmp_path, answer, expected):
    provider = Script([tools("send_note"), text("Not sent.")])
    service, dispatcher, trace = traced(provider)
    dispatcher.timeout = 0.05
    await service.reply("owner", ConversationRequest(text="Send it"), tmp_path,
                        approver(dispatcher, answer))
    (item,) = trace.recent()
    assert item["approvals"][0]["answer"] == expected
    tool = next(span for span in item["spans"] if span["kind"] == "tool")
    assert tool["outcome"] == "error"


async def test_include_text_keeps_request_and_answer_truncated(tmp_path):
    long_answer = MARKER + " " + "x" * 900
    provider = Script([text(long_answer)])
    service, _, trace = traced(provider, {"diagnostics": {"include_text": True}})
    request = ConversationRequest(text=MARKER + " " + "y" * 900)
    await service.reply("owner", request, tmp_path, usage_feature="phone_chat")
    (item,) = trace.recent()
    assert item["origin"] == "phone"
    assert item["request_text"] == request.text[:TEXT_LIMIT]
    assert item["answer_text"] == long_answer[:TEXT_LIMIT]
    assert len(item["request_text"]) == TEXT_LIMIT == 500


async def test_a_failing_tracer_never_breaks_the_turn(tmp_path, caplog):
    provider = Script([text(f"Fine. {MARKER}")])
    service, _, _ = traced(provider)

    class Broken:
        def record_turn(self, *args, **kwargs):
            raise RuntimeError(MARKER)

    service.tracer = Broken()
    result = await service.reply("owner", ConversationRequest(text=MARKER), tmp_path)
    assert result.text.startswith("Fine")
    assert "The turn trace could not be recorded (RuntimeError)" in caplog.text
    assert "TRACE-MARKER" not in caplog.text


async def test_failed_turns_are_traced_with_their_outcome(tmp_path):
    async def boom(kwargs):
        raise RuntimeError("provider exploded")

    provider = Script([boom])
    service, _, trace = traced(provider)
    with pytest.raises(ServiceError):
        await service.reply("owner", ConversationRequest(text="hello"), tmp_path)
    assert trace.recent()[0]["outcome"] == "error"


# --- voice --------------------------------------------------------------------------------


class FakeLive:
    def __init__(self, model, config):
        self.inbox = asyncio.Queue()
        self.tool_responses = []

    async def send_realtime_input(self, **values):
        pass

    async def send_tool_response(self, *, function_responses):
        self.tool_responses.append(function_responses)

    async def receive(self):
        while True:
            item = await self.inbox.get()
            yield item
            if item.server_content and item.server_content.turn_complete:
                return

    def push(self, **content):
        self.inbox.put_nowait(
            types.LiveServerMessage(server_content=types.LiveServerContent(**content))
        )

    def message(self, **values):
        self.inbox.put_nowait(types.LiveServerMessage(**values))

    def speak(self, words):
        self.push(model_turn=types.Content(role="model", parts=[types.Part(
            inline_data=types.Blob(data=bytes(480), mime_type="audio/pcm;rate=24000"),
        )]))
        self.push(output_transcription=types.Transcription(text=words))


class FakeConnector:
    def __init__(self):
        self.connections = []

    @asynccontextmanager
    async def __call__(self, model, config):
        live = FakeLive(model, config)
        self.connections.append(live)
        yield live


@pytest.fixture
def voice(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "second": "other", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "second": "renderer", "tray": "resident"})
    connector = FakeConnector()
    app.voice.connector = connector
    app.voice.preflight = lambda: None
    app.voice.tick = 0.01
    return app, connector


async def until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(0.005)


async def start_voice(app, connector):
    ack = await app.sio.handlers["/"]["voice_start"](
        "client", {"mode": "push_to_talk", "conversation_id": str(uuid.uuid4())}
    )
    assert ack["ok"], ack
    await until(lambda: connector.connections and app.voice.sessions["owner"].live)
    return connector.connections[-1]


async def test_a_live_only_reply_is_a_voice_trace_with_speech_spans(voice):
    app, connector = voice
    live = await start_voice(app, connector)
    live.push(input_transcription=types.Transcription(text=f"Hello {MARKER}"))
    await asyncio.sleep(0.01)
    live.speak(f"Good evening. {MARKER}")
    await asyncio.sleep(0.01)
    live.push(turn_complete=True)
    await until(lambda: app.trace.recent())
    (item,) = app.trace.recent()
    assert item["origin"] == "voice" and item["outcome"] == "ok"
    assert item["provider"] == "gemini_live" and item["model"]
    assert [span["kind"] for span in item["spans"]] == ["speech_in", "speech_out"]
    speech_out = item["spans"][1]
    assert speech_out["ms"] >= 5 and speech_out["start_ms"] >= item["spans"][0]["start_ms"]
    assert item["total_ms"] >= speech_out["ms"]
    assert "TRACE-MARKER" not in all_text(item) and "request_text" not in item
    await until(lambda: any(c.args[0] == "trace_added" for c in app.sio.emit.await_args_list))
    added = [c for c in app.sio.emit.await_args_list if c.args[0] == "trace_added"][-1]
    assert added.args[1] == {"id": item["id"], "origin": "voice", "outcome": "ok",
                             "total_ms": item["total_ms"]}
    assert added.kwargs["room"] == "client"
    await app.voice.stop_sid()


async def test_voice_text_only_with_include_text(voice):
    app, connector = voice
    app.settings["diagnostics"] = {"include_text": True}
    live = await start_voice(app, connector)
    live.push(input_transcription=types.Transcription(text="Hello there"))
    live.speak("Good evening.")
    live.push(turn_complete=True)
    await until(lambda: app.trace.recent())
    item = app.trace.recent()[0]
    assert item["request_text"] == "Hello there" and item["answer_text"] == "Good evening."
    await app.voice.stop_sid()


async def test_a_quick_answer_is_a_tool_span(voice, monkeypatch):
    from services import voice_quick

    app, connector = voice

    async def answer(app_, name, args):
        await asyncio.sleep(0.01)
        return {"result": "Sunny."}

    monkeypatch.setattr(voice_quick, "answer", answer)
    live = await start_voice(app, connector)
    live.push(input_transcription=types.Transcription(text="Weather?"))
    name = sorted(voice_quick.QUICK_TOOLS)[0]
    live.message(tool_call=types.LiveServerToolCall(function_calls=[
        types.FunctionCall(id="q-1", name=name, args={})
    ]))
    await until(lambda: live.tool_responses)
    live.speak("Sunny.")
    live.push(turn_complete=True)
    await until(lambda: app.trace.recent())
    spans = app.trace.recent()[0]["spans"]
    tool = next(span for span in spans if span["kind"] == "tool")
    assert tool["name"] == name and tool["outcome"] == "ok" and tool["ms"] >= 5
    await app.voice.stop_sid()


async def test_ask_brain_speech_spans_join_the_brain_turn_trace(voice):
    app, connector = voice
    provider = Script([text(f"It is nine. {MARKER}")], name="claude")
    app.conversation.provider_factory = lambda: provider
    live = await start_voice(app, connector)
    live.push(input_transcription=types.Transcription(text="What time is it?"))
    await asyncio.sleep(0.01)
    live.message(tool_call=types.LiveServerToolCall(function_calls=[
        types.FunctionCall(id="fc-1", name="ask_brain", args={"request": "What time is it?"})
    ]))
    await until(lambda: live.tool_responses)
    (item,) = app.trace.recent()
    assert item["origin"] == "voice" and [s["kind"] for s in item["spans"]] == ["model"]
    live.speak("It is nine.")
    await asyncio.sleep(0.01)
    live.push(turn_complete=True)
    await until(lambda: len(app.trace.recent()[0]["spans"]) == 3)
    (item,) = app.trace.recent()  # the same trace, not a second one
    assert [span["kind"] for span in item["spans"]] == ["speech_in", "model", "speech_out"]
    speech_in, model, speech_out = item["spans"]
    assert speech_in["start_ms"] < 0 <= model["start_ms"] < speech_out["start_ms"]
    assert "TRACE-MARKER" not in all_text(item)
    await app.voice.stop_sid()


async def test_wake_span_on_the_first_exchange():
    trace = TraceService(settings=lambda: {})
    session = SimpleNamespace(id="s-1", owner="owner", source="wake")
    trace.voice_event(session, "started", model="live-model")
    trace.voice_event(session, "connected")
    trace.voice_event(session, "speech_in")
    trace.voice_event(session, "audio_out")
    trace.voice_event(session, "turn_complete", pending=False, final=False)
    trace.voice_event(session, "speech_in")
    trace.voice_event(session, "turn_complete", pending=False, final=True)
    second, first = trace.recent()
    assert [span["kind"] for span in first["spans"]] == ["wake", "speech_in", "speech_out"]
    assert first["spans"][0]["start_ms"] <= 0
    assert [span["kind"] for span in second["spans"]] == ["speech_in"]
    assert trace._voice == {}
    # A hook that fails is logged by type and never raises.
    trace.voice_event(session, "no_such_event")
    trace.voice_event(None, "speech_in")


async def test_voice_spans_that_arrive_first_wait_for_the_brain_trace():
    trace = TraceService(settings=lambda: {})
    session = SimpleNamespace(id="s-2", owner="owner", source="tray")
    trace.voice_event(session, "speech_in")
    trace.voice_event(session, "tool", call_id="fc", name="ask_brain")
    trace.voice_event(session, "brain", call_id="fc", request_id="brain-1")
    trace.voice_event(session, "turn_complete", final=True)  # session ended first
    assert trace.recent() == []
    trace.record_turn({**fake_timing(0), "request_id": "brain-1"}, SimpleNamespace(steps=[]))
    (item,) = trace.recent()
    assert [span["kind"] for span in item["spans"]] == ["speech_in"]


async def test_a_broken_trace_service_never_breaks_voice(voice):
    app, connector = voice

    class Broken:
        def voice_event(self, *args, **kwargs):
            raise RuntimeError("boom")

    app.trace = Broken()
    live = await start_voice(app, connector)
    live.push(input_transcription=types.Transcription(text="Hello"))
    live.speak("Hi.")
    live.push(turn_complete=True)
    await until(lambda: app.voice.sessions["owner"].state == "idle")
    await app.voice.stop_sid()


# --- routes and settings ------------------------------------------------------------------


async def test_trace_routes_are_owner_only(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "tray": "owner", "second": "other"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "second": "renderer"})
    app.sessions.local_owner = "owner"
    app.trace.record_turn(fake_timing(1), SimpleNamespace(steps=[]), owner="owner")
    handlers = app.sio.handlers["/"]
    for name in ("trace_recent", "trace_clear"):
        for sid, code in (("unknown", "authentication_required"),
                          ("tray", "authentication_required"),
                          ("second", "permission_denied")):
            result = await handlers[name](sid, {})
            assert result["ok"] is False and result["code"] == code, (name, sid, result)
    assert len(app.trace.recent()) == 1
    for bad in ({"limit": 0}, {"limit": 201}, {"limit": "5"}, {"extra": 1}):
        assert (await handlers["trace_recent"]("client", bad))["code"] == "invalid_arguments"
    result = await handlers["trace_recent"]("client", {"limit": 5})
    assert result["ok"] is True and [item["id"] for item in result["traces"]] == ["id-1"]
    assert (await handlers["trace_recent"]("client"))["ok"] is True
    assert await handlers["trace_clear"]("client", {}) == {"ok": True}
    assert (await handlers["trace_recent"]("client", {}))["traces"] == []
    app.settings["face_auth_enabled"] = True
    assert (await handlers["trace_recent"]("client", {}))["code"] == "authentication_required"


def test_trace_routes_are_in_the_route_policy_matrix():
    from pathlib import Path

    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text()
    )
    for name in ("trace_recent", "trace_clear"):
        assert matrix["socket_routes"][name]["status"] == "implemented"


def test_application_wires_the_recorder(application_factory):
    app = application_factory()
    assert isinstance(app.trace, TraceService)
    assert app.conversation.tracer is app.trace and app.mobile.chat.tracer is app.trace


def test_include_text_setting_default_and_validation():
    assert DIAGNOSTICS_DEFAULTS == {"include_text": False, "folder": ""}
    assert diagnostics_settings({}) == {"include_text": False, "folder": ""}
    assert diagnostics_settings({"diagnostics": {"include_text": "yes"}}) == {"include_text": False, "folder": ""}
    assert diagnostics_settings({"diagnostics": {"include_text": True}}) == {"include_text": True, "folder": ""}
    for bad in ({"include_text": None}, {"include_text": "true"}, {"include_text": 1}, {},
                {"other": True}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"diagnostics": bad})
    saved = []
    service = SettingsService({}, SimpleNamespace(save=saved.append), [])
    snapshot = service.apply(SettingsPatch.model_validate({"diagnostics": {"include_text": True}}))
    assert snapshot["diagnostics"] == {"include_text": True, "folder": ""}
    trace = TraceService(settings=service.snapshot)
    assert trace.include_text() is True
