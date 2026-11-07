"""Typed replies stream to the desktop as they are written. Offline: provider clients are faked."""

import asyncio
import logging
import re
import uuid
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage
from google.genai import errors, types

from llm import gemini
from llm.claude import ClaudeProvider
from llm.gemini import GeminiProvider
from services.conversation import ConversationRequest, ConversationService
from services.tools import ToolDispatcher, register_project_tools
from transport.conversation import DELTA_INTERVAL, ReplyDeltas

REPLY_MARKER = "REPLY-TEXT-MARKER-5512"
USER_MARKER = "USER-TEXT-MARKER-9034"
UNAVAILABLE = "Gemini is temporarily unavailable. Try again shortly."
TIMING = re.compile(
    r"AI provider request: provider=(\w+) model=([\w.\-]+) elapsed_ms=(\d+) "
    r"first_text_ms=(\d+|-) outcome=([\w\-]+)"
)


# --- fakes ---------------------------------------------------------------------------


async def play(script):
    """Yield the script's items; numbers sleep, events wait, exceptions raise."""
    for item in script:
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, (int, float)):
            await asyncio.sleep(item)
        elif isinstance(item, asyncio.Event):
            await item.wait()
        else:
            yield item


def claude_message(content, stop="end_turn"):
    return BetaMessage.model_validate(
        {
            "id": "msg_" + uuid.uuid4().hex[:8],
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )


class ClaudeStream:
    def __init__(self, script, final):
        self.script, self.final, self.exited = script, final, None

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, exc, trace):
        self.exited = kind or "clean"
        return False

    async def __aiter__(self):
        async for item in play(self.script):
            yield SimpleNamespace(type="text", text=item)

    async def get_final_message(self):
        return self.final


class ClaudeClient:
    """``AsyncAnthropic`` stand-in: each request plays one (script, final message)."""

    def __init__(self, *turns):
        self.turns, self.requests, self.streams = list(turns), [], []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **params):
        self.requests.append(params)
        script, final = self.turns.pop(0)
        self.streams.append(ClaudeStream(script, final))
        return self.streams[-1]

    async def close(self):
        pass


class GeminiClient:
    """google-genai stand-in: each streamed request plays one script of chunks."""

    def __init__(self, *attempts):
        self.attempts, self.requests, self.closed = list(attempts), [], []
        self.aio = self
        self.models = self

    async def generate_content_stream(self, **kwargs):
        self.requests.append(list(kwargs["contents"]))
        script = self.attempts.pop(0)
        if isinstance(script, BaseException):
            raise script

        async def chunks():
            try:
                async for item in play(script):
                    yield item
            finally:
                self.closed.append(True)

        return chunks()

    async def aclose(self):
        pass


def chunk(*parts):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


def words(text):
    return types.Part(text=text)


def overloaded():
    return errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE",
                                              "message": "provider-private"}})


def dispatcher():
    tools = ToolDispatcher(lambda: {"read_file": False, "write_file": False})
    register_project_tools(tools)
    return tools


def claude_service(client):
    return ConversationService(
        dispatcher(), lambda: ClaudeProvider(api_key="sk-ant-offline", client=client)
    )


def gemini_service(client):
    provider = GeminiProvider(api_key="AQ.offline-test-key", model="gemini-3.8-flash")
    provider._GeminiProvider__client = client
    return ConversationService(dispatcher(), lambda: provider)


@pytest.fixture
def desk(monkeypatch, tmp_path, application_factory):
    """A runtime whose socket emits are recorded as (event, payload, room)."""
    runtime = application_factory()
    emitted = []

    async def emit(event, data=None, room=None):
        emitted.append((event, data, room))

    monkeypatch.setattr(runtime.sio, "emit", emit)
    monkeypatch.setattr(
        runtime.sessions, "projects",
        SimpleNamespace(get_current_project_path=lambda: tmp_path, current_project="temp"),
    )
    monkeypatch.setitem(runtime.sessions.principals, "client", "owner")
    monkeypatch.setitem(runtime.settings, "face_auth_enabled", False)
    (tmp_path / "notes.txt").write_text("Bracket 40 mm", encoding="utf-8")
    return SimpleNamespace(runtime=runtime, emitted=emitted, project=tmp_path)


async def send(desk, service, text="How long is the bracket?"):
    desk.runtime.conversation_transport.service = service
    request = ConversationRequest(text=text)
    await desk.runtime.conversation_transport.user_input("client", request.model_dump(mode="json"))
    return request


def events(desk, *names):
    return [(event, data) for event, data, _ in desk.emitted if not names or event in names]


def deltas(desk):
    return [data["text"] for event, data in events(desk, "transcription_delta")]


def steps(desk):
    return [(data["step"], data["text"]) for event, data in events(desk, "transcription_delta")]


def assert_cumulative(pairs):
    """Steps never go back; within a step each text extends the one before."""
    assert pairs, "no transcription_delta was sent"
    for (step, before), (later, after) in zip(pairs, pairs[1:], strict=False):
        assert later >= step
        if later == step:
            assert after.startswith(before) and after != before


def assert_nothing_after_final(desk):
    names = [event for event, _ in events(desk)]
    final = names.index("transcription")
    assert "transcription_delta" not in names[final:]


# --- the core contract, both turn paths -------------------------------------------


@pytest.mark.asyncio
async def test_claude_reply_streams_cumulative_text_across_a_tool_step(desk):
    first = claude_message(
        [{"type": "text", "text": "Checking the notes."},
         {"type": "tool_use", "id": "toolu_1", "name": "read_file",
          "input": {"path": "notes.txt"}}],
        stop="tool_use",
    )
    second = claude_message([{"type": "text", "text": "The bracket is 40 mm."}])
    client = ClaudeClient(
        (["Checking ", 0.06, "the notes."], first),
        ([0.06, "The bracket ", 0.06, "is 40 mm."], second),
    )
    service = claude_service(client)
    request = await send(desk, service)

    pairs = steps(desk)
    assert_cumulative(pairs)
    # Each step's text is its own: the narration before the tool call, then the answer.
    assert pairs == [(0, "Checking "), (0, "Checking the notes."),
                     (1, "The bracket "), (1, "The bracket is 40 mm.")]
    scope = {"request_id": str(request.request_id), "conversation_id": str(request.conversation_id)}
    for _, data in events(desk, "transcription_delta"):
        assert data == {**scope, "step": data["step"], "text": data["text"]}

    # The step's text reaches the desktop before the tool step says JARVIS is working.
    order = [(event, data.get("phase"), data.get("text")) for event, data in events(
        desk, "transcription_delta", "text_status")]
    tool = order.index(("text_status", "tool", None))
    assert order[tool - 1] == ("transcription_delta", None, "Checking the notes.")
    assert order[tool + 1] == ("transcription_delta", None, "The bracket ")

    # The final transcription is unchanged in shape, authoritative, and last.
    (final,) = [data for event, data in events(desk, "transcription")]
    assert final == {"sender": "JARVIS", "text": "The bracket is 40 mm.", **scope,
                     "project": desk.project.name}
    assert final["text"] == pairs[-1][1]  # the final replace never shrinks the message
    assert_nothing_after_final(desk)
    assert events(desk)[-1] == ("text_status", {"state": "idle", **scope,
                                                "project": desk.project.name})
    assert service.restore("owner", request.conversation_id, desk.project)[-1] == {
        "role": "assistant", "content": "The bracket is 40 mm."}


@pytest.mark.asyncio
async def test_gemini_reply_streams_and_keeps_signed_tool_parts(desk):
    signed = types.Part(
        function_call=types.FunctionCall(name="read_file", args={"path": "notes.txt"}, id="c1"),
        thought_signature=b"offline-signature",
    )
    client = GeminiClient(
        [chunk(words("Let me look.")), 0.06, chunk(signed)],
        [chunk(words("It is ")), 0.06, chunk(words("40 mm.")),
         chunk(types.Part(text="", thought_signature=b"tail-signature"))],
    )
    service = gemini_service(client)
    request = await send(desk, service)

    pairs = steps(desk)
    assert_cumulative(pairs)
    assert pairs == [(0, "Let me look."), (1, "It is "), (1, "It is 40 mm.")]
    assert ("text_status", "tool") in [
        (event, data.get("phase")) for event, data in events(desk, "text_status")]
    (final,) = [data["text"] for event, data in events(desk, "transcription")]
    assert final == "It is 40 mm."
    assert_nothing_after_final(desk)

    # The assembled model turn replays every streamed part, signature included.
    replayed = client.requests[1][-2]
    assert replayed.role == "model"
    assert [part.text for part in replayed.parts][0] == "Let me look."
    assert replayed.parts[-1].thought_signature == b"offline-signature"
    assert client.requests[1][-1].parts[0].function_response.name == "read_file"
    assert service.restore("owner", request.conversation_id, desk.project) == [
        {"role": "user", "content": "How long is the bracket?"},
        {"role": "assistant", "content": "It is 40 mm."},
    ]


@pytest.mark.asyncio
async def test_a_tool_call_without_text_first_streams_only_the_answer_step(desk):
    first = claude_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "notes.txt"}}],
        stop="tool_use",
    )
    second = claude_message([{"type": "text", "text": "It is 40 mm."}])
    client = ClaudeClient(([], first), (["It is 40 mm."], second))
    await send(desk, claude_service(client))
    assert steps(desk) == [(1, "It is 40 mm.")]
    phases = [data.get("phase") for _, data in events(desk, "text_status")]
    assert phases == [None, "tool", None]  # processing, the tool step, idle
    assert [data["text"] for _, data in events(desk, "transcription")] == ["It is 40 mm."]
    assert_nothing_after_final(desk)


@pytest.mark.asyncio
async def test_deltas_are_coalesced_to_one_per_50_ms_and_the_latest_wins(desk):
    pieces = [f"w{index} " for index in range(40)]
    script = []
    for piece in pieces:
        script += [piece, 0.004]
    stamps = []
    original = desk.runtime.sio.emit

    async def stamped(event, data=None, room=None):
        if event == "transcription_delta":
            stamps.append(asyncio.get_running_loop().time())
        await original(event, data, room)

    desk.runtime.sio.emit = stamped
    full = "".join(pieces)
    client = ClaudeClient((script, claude_message([{"type": "text", "text": full}])))
    await send(desk, claude_service(client))

    texts = deltas(desk)
    assert_cumulative(steps(desk))
    assert {step for step, _ in steps(desk)} == {0}
    assert len(texts) < len(pieces) / 2  # many chunks, few events
    assert all(b - a >= DELTA_INTERVAL - 0.005 for a, b in zip(stamps, stamps[1:], strict=False))
    # The trailing send delivers the latest text, or the final arrives first.
    assert texts[-1] == full or len(full) > len(texts[-1])
    assert_nothing_after_final(desk)


# --- failures ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_failure_before_text_retries_once(desk, caplog, monkeypatch):
    monkeypatch.setattr(gemini, "RETRY_DELAY", 0)
    caplog.set_level(logging.INFO)
    client = GeminiClient(
        [chunk(types.Part(text="planning", thought=True)), overloaded()],
        [chunk(words("Hello."))],
    )
    await send(desk, gemini_service(client))
    assert len(client.requests) == 2
    assert "AI provider request retrying: provider=gemini status=503 kind=UNAVAILABLE" in caplog.text
    assert deltas(desk) == ["Hello."]
    assert [data["text"] for _, data in events(desk, "transcription")] == ["Hello."]


@pytest.mark.asyncio
async def test_failure_before_any_text_is_todays_mapped_error(desk, monkeypatch):
    monkeypatch.setattr(gemini, "RETRY_DELAY", 0)
    client = GeminiClient(overloaded(), overloaded())
    await send(desk, gemini_service(client))
    assert len(client.requests) == 2  # the one retry, as before streaming
    assert deltas(desk) == []
    (error,) = [data for _, data in events(desk, "error")]
    assert (error["code"], error["msg"]) == ("provider_unavailable", UNAVAILABLE)


@pytest.mark.parametrize("path", ["gemini", "claude"])
@pytest.mark.asyncio
async def test_failure_after_text_ends_with_the_mapped_error_and_stores_nothing(
    desk, monkeypatch, path
):
    monkeypatch.setattr(gemini, "RETRY_DELAY", 0)
    if path == "gemini":
        client = GeminiClient([chunk(words(f"Partial {REPLY_MARKER}")), overloaded()],
                              [chunk(words("never"))])
        service = gemini_service(client)
        code, message = "provider_unavailable", UNAVAILABLE
    else:
        import anthropic
        import httpx2

        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        failure = anthropic.InternalServerError(
            "provider-private", response=httpx2.Response(500, request=request),
            body={"type": "error", "error": {"type": "api_error", "message": "private"}},
        )
        client = ClaudeClient(([f"Partial {REPLY_MARKER}", failure], None))
        service = claude_service(client)
        code, message = ("provider_unavailable",
                         "Claude is temporarily unavailable. Try again shortly.")
    request = await send(desk, service)

    assert deltas(desk) == [f"Partial {REPLY_MARKER}"]
    if path == "gemini":
        assert len(client.requests) == 1  # text already shown: never retried
    (error,) = [data for _, data in events(desk, "error")]
    assert (error["code"], error["msg"]) == (code, message)
    names = [event for event, _ in events(desk)]
    assert "transcription_delta" not in names[names.index("error"):]
    assert "transcription" not in names
    assert service.restore("owner", request.conversation_id, desk.project) == []


# --- cancel ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["claude", "gemini"])
@pytest.mark.asyncio
async def test_cancel_mid_stream_stops_at_once_and_emits_nothing_more(desk, path):
    forever = asyncio.Event()
    if path == "claude":
        client = ClaudeClient((["Working on ", 0.01, "it", forever, "never"], None))
        service = claude_service(client)
    else:
        client = GeminiClient([chunk(words("Working on ")), 0.01, chunk(words("it")), forever,
                               chunk(words("never"))])
        service = gemini_service(client)
    transport = desk.runtime.conversation_transport
    transport.service = service
    request = ConversationRequest(text="Write a long answer")
    task = asyncio.create_task(transport.user_input("client", request.model_dump(mode="json")))
    for _ in range(200):
        if "Working on it" in deltas(desk):
            break
        await asyncio.sleep(0.005)
    assert deltas(desk)[-1] == "Working on it"
    count = len(desk.emitted)
    await transport.stop_sid("client")
    assert task.done()
    if path == "claude":
        assert client.streams[0].exited is asyncio.CancelledError
    else:
        assert client.closed == [True]  # the streamed response was closed, not left open
    after = [event for event, _, _ in desk.emitted[count:]]
    assert after == ["text_status"]  # idle, so the desktop stops waiting; nothing else
    assert desk.emitted[-1][1]["state"] == "idle"
    await asyncio.sleep(DELTA_INTERVAL * 2)
    assert len(desk.emitted) == count + 1
    assert service.restore("owner", request.conversation_id, desk.project) == []


@pytest.mark.asyncio
async def test_closed_deltas_send_nothing_more_even_with_a_send_pending():
    sent = []

    async def emit(event, payload):
        sent.append((event, payload["text"]))

    stream = ReplyDeltas(emit, {"request_id": "r", "conversation_id": "c", "project": "p"})
    await stream.text("One")
    await stream.text("One two")  # inside the window: a trailing send is scheduled
    assert stream.timer is not None
    await stream.close()
    await stream.text("One two three")
    await asyncio.sleep(DELTA_INTERVAL * 2)
    assert sent == [("transcription_delta", "One")]


# --- logs ------------------------------------------------------------------------------


def timing(caplog):
    lines = [record.getMessage() for record in caplog.records
             if record.getMessage().startswith("AI provider request: ")]
    (line,) = lines
    match = TIMING.fullmatch(line)
    assert match, line
    return match


@pytest.mark.asyncio
async def test_timing_log_has_first_text_ms_and_no_reply_text(desk, caplog):
    caplog.set_level(logging.DEBUG)
    client = ClaudeClient(
        ([0.03, f"Answer {REPLY_MARKER}"],
         claude_message([{"type": "text", "text": f"Answer {REPLY_MARKER}"}])),
    )
    await send(desk, claude_service(client), text=USER_MARKER)
    match = timing(caplog)
    assert match.group(5) == "ok"
    assert match.group(4) != "-" and 25 <= int(match.group(4)) <= int(match.group(3))
    assert REPLY_MARKER not in caplog.text and USER_MARKER not in caplog.text


@pytest.mark.asyncio
async def test_failed_stream_logs_no_reply_text(desk, caplog, monkeypatch):
    monkeypatch.setattr(gemini, "RETRY_DELAY", 0)
    caplog.set_level(logging.DEBUG)
    client = GeminiClient([chunk(words(f"Partial {REPLY_MARKER}")), overloaded()])
    await send(desk, gemini_service(client), text=USER_MARKER)
    match = timing(caplog)
    assert match.group(5) == "provider_unavailable" and match.group(4) != "-"
    assert REPLY_MARKER not in caplog.text and USER_MARKER not in caplog.text


@pytest.mark.asyncio
async def test_unstreamed_callers_are_unchanged(tmp_path, caplog):
    """Voice (ask_brain) and phone call reply() without a stream: no on_text, '-' timing."""
    caplog.set_level(logging.INFO)
    seen = []

    class Provider:
        name = "gemini"
        _model = "gemini-3.8-flash"

        async def generate(self, messages, **kwargs):
            seen.append(sorted(kwargs))
            from llm.base import LLMResponse

            return LLMResponse(text="Done.")

        async def close(self):
            pass

    service = ConversationService(dispatcher(), Provider)
    result = await service.reply("owner", ConversationRequest(text="Hi"), tmp_path)
    assert result.text == "Done." and "on_text" not in seen[0]
    assert timing(caplog).group(4) == "-"
