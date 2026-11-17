"""Tool search (S5.1, docs/AI_PROVIDERS.md "Tool search"): Claude defers the non-core tools
behind the BM25 tool search tool past 25 tools; Gemini gets the core set plus local BM25
matches (services/tool_index.py).

Offline: fake providers and fake tools only; no request reaches the network.
"""

import copy
import logging

from pydantic import BaseModel, ConfigDict

from llm.base import LLMResponse, ToolCall
from llm.claude import (
    TOOL_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    WEB_SEARCH_TOOL,
    ClaudeProvider,
    anthropic_tools,
    defer_tools,
    has_server_blocks,
    has_tool_search_blocks,
    web_tools,
    with_tool_search,
)
from services import tool_index
from services.conversation import ConversationRequest, ConversationService, reads_web
from services.tool_groups import CORE_TOOLS, TOOL_SEARCH_THRESHOLD, core_names, uses_tool_search
from services.tool_index import MAX_TOOLS, TOP_MATCHES, ToolIndex, index_for, select_for_request
from services.tools import ToolDispatcher, ToolSpec

WORLD = ("world_show", "world_tour", "mcp__gev__flights", "mcp__gev__get_earthquakes")
CORE = ("weather", "memory_search", "list_reminders", "create_reminder", "home_control")
PRINTERS = {
    "print_stl": "Slice an STL model and send it to a 3D printer.",
    "get_print_status": "Read the progress of the current 3D print job.",
    "add_printer": "Add a 3D printer to JARVIS by its address.",
    "discover_printers": "Find 3D printers on the local network.",
}
OTHERS = {
    "launch_app": "Open an application on this PC.",
    "focus_window": "Bring an open window to the front.",
    "read_clipboard": "Read the text on the clipboard.",
    "write_clipboard": "Put text on the clipboard.",
    "take_screenshot": "Save a screenshot of the screen to the project.",
    "get_system_info": "Report CPU, memory and disk use of this PC.",
    "list_running_apps": "List the applications that are running.",
    "search_files": "Find files in the current project by name.",
    "read_file": "Read a UTF-8 file in the current project.",
    "write_file": "Save a UTF-8 file in the current project.",
    "generate_image": "Draw a picture from a text prompt.",
    "place_task_call": "Phone a business for the owner and report back.",
    "discover_kasa": "Find Kasa smart plugs and bulbs on the network.",
    "control_device": "Turn a Kasa smart plug or bulb on or off.",
    "get_device_state": "Read whether a Kasa device is on.",
    "switch_project": "Switch to another JARVIS project.",
    "create_project": "Create a new JARVIS project.",
    "list_projects": "List the owner's JARVIS projects.",
}


def schema(name, description=None):
    return {"name": name, "description": description or f"The {name} tool.",
            "parameters": {"type": "object", "properties": {}}}


def many(count=40):
    """``count`` dispatcher schemas: the core names, the world group, printers and fillers."""
    names = {**{name: None for name in (*CORE, *WORLD)}, **PRINTERS, **OTHERS}
    items = [schema(name, description) for name, description in names.items()]
    index = 0
    while len(items) < count:
        items.append(schema(f"extra_tool_{index:02d}"))
        index += 1
    return items[:count]


def provider(web_search=True, model="claude-sonnet-5-5"):
    return ClaudeProvider(api_key="test-key", model=model, client=object(),
                          web_search=web_search)


def send(tools, web_search=True, model="claude-sonnet-5-5", messages=None):
    return provider(web_search, model).request(
        messages or [{"role": "user", "content": "hello"}],
        tools=tools, system_instruction="You are JARVIS.",
    )["tools"]


def by_name(tools):
    return {tool["name"]: tool for tool in tools}


# --- Claude: the request ----------------------------------------------------------------------
def test_past_25_tools_the_core_loads_and_the_rest_is_deferred():
    schemas = many(40)
    tools = send(anthropic_tools(schemas))
    named = by_name(tools)
    # Every client tool is still declared, plus the search tool and the two web tools.
    assert set(named) == {item["name"] for item in schemas} | {
        "tool_search_tool_bm25", "web_search", "web_fetch"}
    assert named["tool_search_tool_bm25"] == TOOL_SEARCH_TOOL
    for name in CORE:
        assert "defer_loading" not in named[name], name
    deferred = {name for name, tool in named.items() if tool.get("defer_loading") is True}
    assert deferred == {item["name"] for item in schemas} - set(CORE)
    # World tools are not core by name: deferred unless the world gate loads them.
    assert set(WORLD) <= deferred
    # Deferred definitions are full definitions, never with a cache breakpoint.
    assert all("input_schema" in named[name] and "cache_control" not in named[name]
               for name in deferred)


def test_the_list_is_sorted_by_name_and_stable_across_calls():
    schemas = many(40)
    first = send(anthropic_tools(schemas))
    shuffled = list(reversed(schemas))
    second = send(anthropic_tools(shuffled))
    assert [tool["name"] for tool in first] == sorted(tool["name"] for tool in first)
    assert first == second
    # A third call with the same input is byte-identical (prompt cache prefix).
    assert send(anthropic_tools(schemas)) == first


def test_at_or_below_25_tools_nothing_changes():
    schemas = many(TOOL_SEARCH_THRESHOLD)
    client = anthropic_tools(schemas)
    tools = send(copy.deepcopy(client))
    assert tools == [*client, *web_tools("claude-sonnet-5-5")]
    assert not any("defer_loading" in tool for tool in tools)
    assert "tool_search_tool_bm25" not in by_name(tools)
    assert uses_tool_search(25) is False and uses_tool_search(26) is True


def test_never_everything_deferred():
    # No core tool registered at all and web search off: the search tool still loads.
    schemas = [schema(f"plain_{index:02d}") for index in range(30)]
    tools = send(anthropic_tools(schemas), web_search=False)
    loaded = [tool for tool in tools if not tool.get("defer_loading")]
    assert [tool["name"] for tool in loaded] == ["tool_search_tool_bm25"]
    assert "defer_loading" not in by_name(tools)["tool_search_tool_bm25"]
    # With the core set present, real tools load too.
    tools = send(anthropic_tools(many(30)), web_search=False)
    loaded = {tool["name"] for tool in tools if not tool.get("defer_loading")}
    assert set(CORE) | {"tool_search_tool_bm25"} == loaded


def test_web_tools_are_never_deferred_or_changed():
    for model in ("claude-sonnet-5-5", "claude-haiku-5-5"):
        tools = send(anthropic_tools(many(40)), model=model)
        named = by_name(tools)
        expected = by_name(web_tools(model))
        assert named["web_search"] == expected["web_search"]
        assert named["web_fetch"] == expected["web_fetch"]
        assert "defer_loading" not in named["web_search"]
    assert WEB_SEARCH_TOOL["name"] == "web_search" and WEB_FETCH_TOOL["name"] == "web_fetch"
    # Haiku 5.5 supports tool search too: the same search tool, no special shape.
    assert by_name(send(anthropic_tools(many(40)), model="claude-haiku-5-5"))[
        "tool_search_tool_bm25"] == TOOL_SEARCH_TOOL


def test_marks_made_by_the_caller_are_kept():
    # The conversation marks the world group loaded on a globe turn; the request keeps that.
    client = anthropic_tools(many(40))
    loaded = core_names([tool["name"] for tool in client], world=True)
    tools = send(defer_tools(client, loaded))
    named = by_name(tools)
    for name in (*CORE, *WORLD):
        assert "defer_loading" not in named[name], name
    assert named["print_stl"]["defer_loading"] is True


def test_a_history_that_used_tool_search_replays_with_it():
    history = [
        {"role": "user", "content": "print the bracket"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "tool_search_tool_bm25",
             "input": {"query": "3d printer"}},
            {"type": "tool_search_tool_result", "tool_use_id": "srvtoolu_1",
             "content": {"type": "tool_search_tool_search_result",
                         "tool_references": [{"type": "tool_reference",
                                              "tool_name": "print_stl"}]}},
            {"type": "text", "text": "Sending it."},
        ]},
        {"role": "user", "content": "thanks"},
    ]
    assert has_tool_search_blocks(history) is True
    # Tool search blocks are not web blocks: they don't bring the web tools in...
    assert has_server_blocks(history) is False
    # ...and a search result is JARVIS's own catalog, not untrusted web content.
    assert reads_web(history[1]["content"]) is False
    assert reads_web([{"type": "web_search_tool_result"}]) is True
    # Fewer than 25 tools now, but the history needs the search tool: it stays on.
    tools = send(anthropic_tools(many(10)), web_search=False, messages=history)
    assert "tool_search_tool_bm25" in by_name(tools)
    assert by_name(tools)["print_stl"]["defer_loading"] is True


def test_with_tool_search_on_an_empty_list_is_a_no_op():
    assert with_tool_search([]) == []
    assert with_tool_search(None) == []


# --- the conversation: Claude and Gemini ------------------------------------------------------
class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tools:
    def __init__(self, schemas):
        self.ran = []
        names = [item["name"] for item in schemas]
        self.dispatcher = ToolDispatcher(lambda: {name: False for name in names})
        for item in schemas:
            self.dispatcher.register(
                ToolSpec(item["name"], item["description"], NoArgs, self.runner(item["name"]))
            )

    def runner(self, name):
        async def run(args, context):
            self.ran.append(name)
            return {"ok": True}

        return run


class Script:
    """Plays one scripted response per call; keeps each call's ``tools`` as sent."""

    def __init__(self, steps, name=None):
        self.name, self._model = name, "claude-sonnet-5-5" if name else None
        self.steps = list(steps)
        self.sent = []

    async def generate(self, messages, **kwargs):
        self.sent.append(kwargs.get("tools"))
        return self.steps.pop(0)

    async def close(self):
        pass


def text(value):
    return LLMResponse(text=value, content_blocks=[{"type": "text", "text": value}])


def call(name):
    tool = ToolCall("call-1", name, {})
    return LLMResponse(
        tool_calls=[tool],
        content_blocks=[{"type": "tool_use", "id": tool.id, "name": name, "input": {}}],
    )


def service_for(brain, tools):
    return ConversationService(tools.dispatcher, lambda: brain, fast_provider_factory=lambda: brain)


def loaded_names(tools):
    return {tool["name"] for tool in tools if not tool.get("defer_loading")}


async def test_a_claude_weather_turn_defers_the_world_group(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    tools = Tools(many(40))
    brain = Script([call("weather"), text("Clear, sir.")], name="claude")
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="What's the weather in KL?"), tmp_path)
    assert len(brain.sent) == 2
    for sent in brain.sent:
        named = by_name(sent)
        assert set(WORLD) <= set(named)  # declared...
        assert all(named[name]["defer_loading"] is True for name in WORLD)  # ...not loaded
        assert "weather" in loaded_names(sent)
        # What the real provider would send from it: the gate's marks survive.
        final = by_name(provider().request([{"role": "user", "content": "x"}], sent)["tools"])
        assert all(final[name]["defer_loading"] is True for name in WORLD)
        assert "defer_loading" not in final["weather"]
    assert tools.ran == ["weather"]
    timing = service.last_turn_timing
    assert timing["tools_declared"] == 40
    assert timing["deferred"] == 40 - len(CORE)
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_timing ")]
    assert f" tools_declared=40 deferred={40 - len(CORE)} " in line
    assert "KL" not in line


async def test_a_claude_globe_turn_loads_the_world_group(tmp_path):
    tools = Tools(many(40))
    brain = Script([call("world_show"), text("Penang, sir.")], name="claude")
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Show me Penang"), tmp_path)
    for sent in brain.sent:
        assert set(WORLD) | set(CORE) == loaded_names(sent)
    assert tools.ran == ["world_show"]
    assert service.last_turn_timing["deferred"] == 40 - len(CORE) - len(WORLD)


async def test_a_claude_turn_may_call_a_deferred_tool_it_found(tmp_path):
    # Under tool search a deferred tool is declared, so a call to it (after a search) runs.
    tools = Tools(many(40))
    brain = Script([call("print_stl"), text("Printing, sir.")], name="claude")
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Print the bracket"), tmp_path)
    assert tools.ran == ["print_stl"]


async def test_gemini_gets_the_core_set_plus_the_best_matches(tmp_path):
    tools = Tools(many(60))
    brain = Script([call("print_stl"), text("Printing, sir.")])
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Print the bracket on my 3D printer"),
                        tmp_path)
    for sent in brain.sent:
        names = [item["name"] for item in sent[0]["function_declarations"]]
        assert set(CORE) <= set(names)
        assert set(PRINTERS) <= set(names)
        assert not set(WORLD) & set(names)
        assert len(names) <= len(CORE) + TOP_MATCHES <= MAX_TOOLS
    assert tools.ran == ["print_stl"]
    assert service.last_turn_timing["deferred"] == 0
    assert service.last_turn_timing["tools_declared"] <= MAX_TOOLS


async def test_gemini_weather_turn_never_declares_the_world_group(tmp_path):
    tools = Tools(many(60))
    brain = Script([call("weather"), text("Clear, sir.")])
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Show me the weather in Kuala Lumpur"),
                        tmp_path)
    for sent in brain.sent:
        names = {item["name"] for item in sent[0]["function_declarations"]}
        assert "weather" in names and not set(WORLD) & names
    # A call to a tool that wasn't declared is refused, not run.
    brain = Script([call("world_show"), text("Clear, sir.")])
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Cuaca hari ini"), tmp_path)
    assert tools.ran == ["weather"]


async def test_gemini_globe_turn_declares_the_world_group(tmp_path):
    tools = Tools(many(60))
    brain = Script([text("Penang, sir.")])
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Show me Penang"), tmp_path)
    names = {item["name"] for item in brain.sent[0][0]["function_declarations"]}
    assert set(WORLD) <= names and set(CORE) <= names


async def test_gemini_at_or_below_25_tools_gets_them_all(tmp_path):
    schemas = many(25)
    tools = Tools(schemas)
    brain = Script([text("Done, sir.")])
    service = service_for(brain, tools)
    await service.reply("owner", ConversationRequest(text="Print it"), tmp_path)
    names = {item["name"] for item in brain.sent[0][0]["function_declarations"]}
    assert names == {item["name"] for item in schemas} - set(WORLD)


# --- the local BM25 index ---------------------------------------------------------------------
def test_a_print_request_ranks_the_printer_tools_first():
    index = ToolIndex(many(60))
    top = index.search("print this bracket", limit=4)
    assert set(top) == set(PRINTERS)
    assert index.search("is the printer done yet?", limit=1) in (
        ["get_print_status"], ["add_printer"], ["discover_printers"], ["print_stl"])
    assert index.search("copy this to the clipboard", limit=2) == ["read_clipboard",
                                                                    "write_clipboard"]
    assert index.search("", limit=5) == []
    assert index.search("zzz qqq", limit=5) == []


def test_the_index_is_cached_and_rebuilt_when_the_tools_change():
    schemas = many(40)
    first = index_for(schemas)
    assert index_for(copy.deepcopy(schemas)) is first
    changed = [*schemas, schema("brand_new_tool")]
    assert index_for(changed) is not first
    described = [{**schemas[0], "description": "Something else entirely."}, *schemas[1:]]
    assert index_for(described) is not index_for(changed)


def test_selection_respects_the_cap_and_the_world_gate():
    schemas = many(80)
    declared, hidden = select_for_request(schemas, "print the bracket", world=False)
    names = [item["name"] for item in declared]
    assert len(names) <= MAX_TOOLS and not set(WORLD) & set(names)
    assert set(names) | hidden == {item["name"] for item in schemas}
    # A large core set still never goes past the cap.
    big_core = frozenset(item["name"] for item in schemas[:50])
    declared, _ = select_for_request(schemas, "print the bracket", world=True, core=big_core)
    assert len(declared) == MAX_TOOLS
    # Declared tools keep the dispatcher's order.
    order = [item["name"] for item in schemas]
    assert [item["name"] for item in declared] == sorted(
        (item["name"] for item in declared), key=order.index)


def test_the_tokenizer_splits_names_and_strips_suffixes():
    assert tool_index.tokens("print_stl") == ["print", "stl"]
    assert tool_index.tokens("Printers printing PRINTS") == ["print", "print", "print"]
    assert tool_index.tokens("the of and") == []


# --- the shipped tools ------------------------------------------------------------------------
def test_the_core_names_are_real_tools(application_factory):
    app = application_factory()
    registered = set(app.dispatcher.tools)
    # load_skill arrives with skills (S5); every other core name is registered today.
    assert CORE_TOOLS - {"load_skill"} <= registered
    assert uses_tool_search(len(app.dispatcher.schemas()))
