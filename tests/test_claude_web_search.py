"""Claude web search and web fetch (server tools). Offline: the Anthropic client is faked,
so no request reaches the network and no credit is spent."""

import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from llm.claude import (
    MAX_CONTINUATIONS,
    PROGRESS_EVENTS,
    WEB_FETCH_TOOL,
    WEB_SEARCH_TOOL,
    ClaudeProvider,
    anthropic_tools,
    answer_text,
    usage_counts,
)
from llm.pricing import CLAUDE_SERVER_TOOL_PRICES, estimate_microusd
from llm.router import TaskRouter, web_search_setting
from services.conversation import ConversationRequest
from services.settings import (
    ASSISTANT_DEFAULTS,
    SettingsPatch,
    SettingsService,
    SettingsStore,
)
from services.tools import ServiceError, ToolDispatcher, register_project_tools
from tests.test_claude_brain import claude_service, message, text, thinking, tool_use

SEARCH = {"type": "server_tool_use", "id": "srvtoolu_01", "name": "web_search",
          "input": {"query": "kuala lumpur weather today"}}
SEARCH_RESULT = {
    "type": "web_search_tool_result", "tool_use_id": "srvtoolu_01",
    "content": [{"type": "web_search_result", "url": "https://example.com/kl",
                 "title": "KL forecast", "encrypted_content": "EqOPAQUE1",
                 "page_age": "November 13, 2026"}],
}
FETCH = {"type": "server_tool_use", "id": "srvtoolu_02", "name": "web_fetch",
         "input": {"url": "https://example.com/kl"}}
FETCH_RESULT = {
    "type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_02",
    "content": {"type": "web_fetch_result", "url": "https://example.com/kl",
                "retrieved_at": "2026-11-14T01:00:00Z",
                "content": {"type": "document", "title": "KL forecast",
                            "source": {"type": "text", "media_type": "text/plain",
                                       "data": "Rain after 3 pm."},
                            "citations": {"enabled": True}}},
}
CITED = {
    "type": "text", "text": "Expect rain after 3 pm",
    "citations": [{"type": "web_search_result_location", "url": "https://example.com/kl",
                   "title": "KL forecast", "encrypted_index": "EoOPAQUE2",
                   "cited_text": "Rain after 3 pm."}],
}


def client_tools():
    dispatcher = ToolDispatcher(lambda: {})
    register_project_tools(dispatcher)
    return anthropic_tools(dispatcher.schemas())


class EventStream:
    """A streamed turn: a content_block_start per block, a text event per text block."""

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for block in self.response.content:
            yield SimpleNamespace(type="content_block_start", content_block=block)
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    async def get_final_message(self):
        return self.response


class EventClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        return EventStream(self.responses.pop(0))

    async def close(self):
        pass


def provider(responses, **options):
    client = EventClient(responses)
    return ClaudeProvider(api_key="sk-ant-offline", client=client, **options), client


# --- request shape ------------------------------------------------------------------


def test_web_tools_join_client_tools_when_on_and_are_absent_when_off():
    tools = client_tools()
    on = ClaudeProvider(api_key="sk-ant-offline").request(
        [{"role": "user", "content": "Weather?"}], tools)
    assert on["tools"] == [*tools, WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
    assert WEB_SEARCH_TOOL == {"type": "web_search_20260209", "name": "web_search",
                               "max_uses": 3}
    assert WEB_FETCH_TOOL == {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}
    # No code execution: the _20260209 tools run their own filtering sandbox.
    assert not any("code_execution" in str(tool.get("type", "")) for tool in on["tools"])
    # eager_input_streaming is for client tools only, never on server tools.
    assert not any("eager_input_streaming" in tool for tool in on["tools"][-2:])
    # Gemini-style declarations convert first, then the web tools follow.
    dispatcher = ToolDispatcher(lambda: {})
    register_project_tools(dispatcher)
    declared = ClaudeProvider(api_key="sk-ant-offline").request(
        [{"role": "user", "content": "Hi"}], [{"function_declarations": dispatcher.schemas()}])
    assert declared["tools"] == on["tools"]

    off = ClaudeProvider(api_key="sk-ant-offline", web_search=False).request(
        [{"role": "user", "content": "Weather?"}], tools)
    assert off["tools"] == tools
    # A tool-free request (phone chat, a camera look) stays tool-free.
    bare = ClaudeProvider(api_key="sk-ant-offline").request([{"role": "user", "content": "Hi"}])
    assert "tools" not in bare


def test_history_with_server_blocks_keeps_the_web_tools_declared():
    history = [
        {"role": "user", "content": "Weather?"},
        {"role": "assistant", "content": [SEARCH, SEARCH_RESULT, CITED]},
        {"role": "user", "content": "And tomorrow?"},
    ]
    off = ClaudeProvider(api_key="sk-ant-offline", web_search=False).request(history)
    assert off["tools"] == [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
    assert off["messages"] == history  # replayed unchanged
    # Haiku (the stalled-step retry) calls them directly, never through code execution.
    fast = ClaudeProvider(api_key="sk-ant-offline", model="claude-haiku-5-5",
                          web_search=False).request(history)
    assert fast["tools"] == [{**WEB_SEARCH_TOOL, "allowed_callers": ["direct"]},
                             {**WEB_FETCH_TOOL, "allowed_callers": ["direct"]}]


def test_router_sets_web_search_from_settings_for_chat_only():
    def router(assistant):
        settings = {"assistant": assistant} if assistant is not None else {}
        return TaskRouter(lambda: settings, anthropic=lambda: "sk-ant-offline",
                          gemini=lambda: "AIza-offline")

    assert router(None).provider("chat").web_search is True
    assert router({"web_search": True}).provider("chat").web_search is True
    assert router({"web_search": False}).provider("chat").web_search is False
    assert router({"web_search": "no"}).provider("chat").web_search is True  # stale value
    assert router(None).provider("fast").web_search is False
    assert router(None).provider("summary").web_search is False
    assert web_search_setting({}) is True and web_search_setting(None) is True
    # The Gemini brain never searches (no change there).
    gemini = router({"brain": "gemini", "web_search": True}).provider("chat")
    assert gemini.name == "gemini" and not hasattr(gemini, "web_search")


# --- settings -----------------------------------------------------------------------


def test_web_search_setting_defaults_on_and_validates():
    assert ASSISTANT_DEFAULTS["web_search"] is True
    store = {"tool_permissions": {}, "assistant": {"brain": "claude"}}
    service = SettingsService(store, SettingsStore(None), [])
    service.apply(SettingsPatch(assistant={"address": "sir"}))
    assert store["assistant"]["web_search"] is True
    service.apply(SettingsPatch.model_validate({"assistant": {"web_search": False}}))
    assert store["assistant"]["web_search"] is False and store["assistant"]["brain"] == "claude"
    for bad in (None, "true", 1, 0, "off", [], {}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"assistant": {"web_search": bad}})


# --- pause_turn, blocks, text -------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_turn_is_resumed_into_one_finished_turn():
    paused = message([thinking("sig-1"), text("Let me check."), SEARCH, SEARCH_RESULT, FETCH],
                     stop="pause_turn",
                     usage={"input_tokens": 100, "output_tokens": 20,
                            "server_tool_use": {"web_search_requests": 1,
                                                "web_fetch_requests": 0}})
    done = message([FETCH_RESULT, CITED, text(" this afternoon.")],
                   usage={"input_tokens": 300, "output_tokens": 30,
                          "server_tool_use": {"web_search_requests": 0,
                                              "web_fetch_requests": 1}})
    claude, client = provider([paused, done])
    deltas, progress = [], []

    async def on_text(chunk):
        deltas.append(chunk)

    tools = client_tools()
    final = await claude.generate([{"role": "user", "content": "Weather in KL?"}], tools,
                                  on_text=on_text, on_progress=lambda: progress.append(1))

    assert len(client.requests) == 2
    first, second = client.requests
    paused_blocks = [block.to_dict() for block in paused.content]
    # The resumed request is the first one plus the paused content, verbatim; no
    # "continue" user message, and every other field unchanged.
    assert second["messages"] == [*first["messages"],
                                  {"role": "assistant", "content": paused_blocks}]
    assert {k: v for k, v in second.items() if k != "messages"} == {
        k: v for k, v in first.items() if k != "messages"}
    assert final.stop_reason == "end_turn" and not final.is_partial
    assert final.content_blocks == [*paused_blocks, *[b.to_dict() for b in done.content]]
    # Readable text: no citation objects, a space where a search split the runs.
    assert final.text == "Let me check. Expect rain after 3 pm this afternoon."
    assert "".join(deltas) == final.text
    assert final.tool_calls == []
    # Server tool block starts count as progress for the first-token deadline.
    assert "content_block_start" in PROGRESS_EVENTS and len(progress) >= 8
    counts = usage_counts(final.raw)
    assert counts["input_tokens"] == 400 and counts["output_tokens"] == 50
    assert counts["web_search_requests"] == 1 and counts["web_fetch_requests"] == 1
    assert counts["total_tokens"] == 450  # request counts are not tokens


@pytest.mark.asyncio
async def test_second_pause_resumes_with_one_merged_assistant_message():
    one = message([SEARCH, SEARCH_RESULT], stop="pause_turn")
    two = message([FETCH], stop="pause_turn")
    three = message([FETCH_RESULT, CITED])
    claude, client = provider([one, two, three])
    final = await claude.generate([{"role": "user", "content": "Weather?"}], client_tools())
    base = client.requests[0]["messages"]
    merged = [*[b.to_dict() for b in one.content], *[b.to_dict() for b in two.content]]
    assert client.requests[2]["messages"] == [*base, {"role": "assistant", "content": merged}]
    assert final.content_blocks == [*merged, *[b.to_dict() for b in three.content]]
    assert final.text == "Expect rain after 3 pm"


@pytest.mark.asyncio
async def test_pause_turn_stops_after_the_continuation_limit():
    responses = [message([SEARCH], stop="pause_turn") for _ in range(MAX_CONTINUATIONS + 1)]
    claude, client = provider(responses)
    with pytest.raises(ServiceError) as exc:
        await claude.generate([{"role": "user", "content": "Weather?"}], client_tools())
    assert exc.value.code == "provider_incomplete"
    assert len(client.requests) == MAX_CONTINUATIONS + 1


@pytest.mark.asyncio
async def test_server_tool_blocks_are_never_client_calls():
    turn = message([text("Checking."), SEARCH, SEARCH_RESULT,
                    tool_use("toolu_1", "read_file", {"path": "notes.md"})], stop="tool_use")
    claude, _ = provider([turn])
    response = await claude.generate([{"role": "user", "content": "Hi"}], client_tools())
    assert [(call.id, call.name) for call in response.tool_calls] == [("toolu_1", "read_file")]
    assert response.content_blocks == [block.to_dict() for block in turn.content]


def test_answer_text_joins_cited_runs_and_skips_non_text_blocks():
    assert answer_text([CITED, text(" this afternoon.")]) == (
        "Expect rain after 3 pm this afternoon.")
    assert answer_text([SEARCH, SEARCH_RESULT, CITED]) == "Expect rain after 3 pm"
    assert answer_text([text("A."), SEARCH, text(" B.")]) == "A. B."
    assert answer_text([text("A.\n"), SEARCH, text("B.")]) == "A.\nB."
    assert answer_text([thinking("s")]) == ""


@pytest.mark.asyncio
async def test_conversation_stores_and_replays_server_blocks_verbatim(tmp_path):
    answer = message([thinking("sig-w"), SEARCH, SEARCH_RESULT, CITED, text(".")],
                     usage={"input_tokens": 10, "output_tokens": 5,
                            "server_tool_use": {"web_search_requests": 1,
                                                "web_fetch_requests": 0}})
    later = message([text("Tomorrow looks dry.")])
    service, client = claude_service([answer, later])
    request = ConversationRequest(text="Will it rain in KL?")
    result = await service.reply("owner", request, tmp_path)
    assert result.text == "Expect rain after 3 pm."
    opening = client.requests[0]
    assert opening["tools"][-2:] == [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]

    await service.reply(
        "owner",
        ConversationRequest(text="And tomorrow?", conversation_id=request.conversation_id),
        tmp_path,
    )
    replay = client.requests[1]["messages"]
    stored = {"role": "assistant", "content": [block.to_dict() for block in answer.content]}
    assert replay[: len(opening["messages"]) + 1] == [*opening["messages"], stored]
    for key in ("system", "tools", "thinking", "output_config"):
        assert client.requests[1][key] == opening[key]
    restored = service.restore("owner", request.conversation_id, tmp_path)
    assert restored[1] == {"role": "assistant", "content": "Expect rain after 3 pm."}


# --- pricing ------------------------------------------------------------------------


def test_search_requests_are_priced_per_thousand():
    assert CLAUDE_SERVER_TOOL_PRICES == {"web_search_requests": 10.00,
                                         "web_fetch_requests": 0.00}
    counts = usage_counts(message([CITED], usage={
        "input_tokens": 1000, "output_tokens": 500,
        "server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 2},
    }))
    assert counts == {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500,
                      "web_search_requests": 3, "web_fetch_requests": 2}
    # $2 / $10 per million tokens, $10 per 1,000 searches ($0.01 each), fetches free.
    assert estimate_microusd("claude-sonnet-5-5", counts) == 2000 + 5000 + 3 * 10_000
    no_search = usage_counts(message([text("x")], usage={"input_tokens": 1, "output_tokens": 1}))
    assert "web_search_requests" not in no_search


@pytest.mark.asyncio
async def test_usage_receipt_counts_search_requests(application_factory):
    from tests.test_claude_brain import owner_app

    app = owner_app(application_factory)
    project = app.projects.get_current_project_path()
    client = EventClient([message([SEARCH, SEARCH_RESULT, CITED], usage={
        "input_tokens": 1000, "output_tokens": 500,
        "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0},
    })])
    app.conversation.provider_factory = lambda: ClaudeProvider(api_key="k", client=client)
    await app.conversation.reply("owner", ConversationRequest(text="Weather?"), project)
    record = app.usage.snapshot("owner", project)["records"][0]
    assert record["tokens"]["web_search_requests"] == 2
    assert "web_fetch_requests" not in record["tokens"]
    assert record["estimated_cost_microusd"] == 2000 + 5000 + 20_000
