"""The world tool group gate (S1.3, docs/WORLD_VIEW.md "When the brain is offered the globe")
and World view's fast failure with no window.

Fake providers, tools and sidecar only: no network, audio, camera or real globe.
"""

import time

import pytest
from pydantic import BaseModel, ConfigDict

from llm.base import LLMResponse, ToolCall
from services.conversation import TOOL_NOT_OFFERED, ConversationRequest, ConversationService
from services.tool_groups import (
    WORLD_WORDS,
    in_world_group,
    mentions_world,
    offer_world,
    select_tools,
    used_world_last,
)
from services.tools import ServiceError, ToolDispatcher, ToolSpec
from services.world_tools import SHOW_DESCRIPTION, TOUR_DESCRIPTION

WEATHER = [
    "What's the weather in KL?",
    "what's the weather in KL",
    "Will it rain tomorrow?",
    "Is it going to be hot in Penang this afternoon?",
    "Forecast for Ipoh this weekend",
    "Show me the weather in Kuala Lumpur",
    "Cuaca hari ini",
    "Adakah hujan esok di Johor Bahru?",
    "Berapa suhu sekarang?",
]
GLOBE = [
    "Show me Penang",
    "show me penang island",
    "Show me the Strait of Malacca",
    "show me where the ISS is",
    "What flights are over KL right now?",
    "Any earthquakes in Indonesia today?",
    "How many ships are in the Strait of Malacca?",
    "Open the GLOBE",
    "Give me a tour of the wildfires in Australia",
    "track satellites above us",
    "Put it on the map",
    "Show me the planes near KLIA",
    "Any quakes near Japan?",
    "what's happening in the world",
]
NOT_GLOBE = [
    "Show me my calendar",
    "show me how to bake bread",
    "Show me this file",
    "Remind me to call Aisyah at five",
    "",
]
WORLD_NAMES = ("world_show", "world_tour", "mcp__gev__get_earthquakes", "mcp__gev__flights")


# --- the pure gate ----------------------------------------------------------------------------
@pytest.mark.parametrize("text", WEATHER)
def test_weather_questions_do_not_bring_in_the_world_group(text):
    assert mentions_world(text) is False
    assert offer_world(text) is False


@pytest.mark.parametrize("text", GLOBE)
def test_globe_requests_bring_it_in(text):
    assert mentions_world(text) is True
    assert offer_world(text) is True


@pytest.mark.parametrize("text", NOT_GLOBE)
def test_other_requests_do_not(text):
    assert offer_world(text) is False


def test_the_word_list_is_a_module_constant_matched_as_whole_words():
    assert {"globe", "map", "flights", "satellite", "earthquake", "wildfire", "tour"} <= set(
        WORLD_WORDS
    )
    # Whole words only: "detour", "remapped" and "worldly" are not the globe.
    assert mentions_world("Take the detour") is False
    assert mentions_world("The keys were remapped") is False
    assert mentions_world("A worldly man") is False


def test_an_open_world_page_brings_it_in():
    assert offer_world("What's the weather in KL?", page_open=True) is True


def test_a_follow_up_after_a_world_tool_brings_it_in():
    # A marked entry (both providers) and a Claude entry with a stored tool_use block.
    marked = [
        {"role": "user", "content": "Show me Penang"},
        {"role": "assistant", "content": "On screen, sir.", "tool_groups": ["world"]},
    ]
    claude = [
        {"role": "user", "content": "Show me Penang"},
        {
            "role": "assistant", "content": "On screen, sir.",
            "claude": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "world_show", "input": {}}
                ]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "On screen, sir."}]},
            ],
        },
    ]
    for history in (marked, claude):
        assert used_world_last(history) is True
        assert offer_world("now zoom closer", history=history) is True
    # Only the last assistant entry counts.
    later = [*marked, {"role": "user", "content": "Thanks"},
             {"role": "assistant", "content": "Of course."}]
    assert used_world_last(later) is False
    assert offer_world("now zoom closer", history=later) is False
    assert used_world_last([]) is False


def test_select_tools_leaves_out_only_the_world_group():
    schemas = [{"name": name} for name in ("weather", *WORLD_NAMES, "calendar_read")]
    kept, hidden = select_tools(schemas, world=False)
    assert [item["name"] for item in kept] == ["weather", "calendar_read"]
    assert hidden == set(WORLD_NAMES)
    kept, hidden = select_tools(schemas, world=True)
    assert kept == schemas and hidden == set()
    assert all(in_world_group(name) for name in WORLD_NAMES)
    assert not in_world_group("weather") and not in_world_group(None)


def test_the_world_descriptions_send_weather_to_the_weather_tool():
    assert "satellites, weather" not in SHOW_DESCRIPTION
    assert "For a plain weather question use the weather tool." in SHOW_DESCRIPTION
    assert "Use the globe only when the owner asks to see something." in SHOW_DESCRIPTION
    assert "weather" not in TOUR_DESCRIPTION.replace("weather-", "")


# --- the gate in ConversationService ----------------------------------------------------------
class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tools:
    def __init__(self):
        self.ran = []
        self.dispatcher = ToolDispatcher(lambda: {name: False for name in ("weather", *WORLD_NAMES)})
        for name in ("weather", *WORLD_NAMES):
            self.dispatcher.register(ToolSpec(name, f"The {name} tool.", NoArgs, self.runner(name)))

    def runner(self, name):
        async def run(args, context):
            self.ran.append(name)
            return {"ok": True}

        return run


class Script:
    """Plays one scripted response per call and keeps the declared tool names."""

    def __init__(self, steps, name=None):
        self.name, self._model = name, "fake-model" if name else None
        self.steps = list(steps)
        self.declared = []

    async def generate(self, messages, **kwargs):
        tools = kwargs.get("tools") or []
        if self.name == "claude":
            names = [item["name"] for item in tools]
        else:
            names = [item["name"] for item in tools[0]["function_declarations"]] if tools else []
        self.declared.append(names)
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


def service_for(provider, tools):
    return ConversationService(
        tools.dispatcher, lambda: provider, fast_provider_factory=lambda: provider
    )


def world_names(names):
    return [name for name in names if name.startswith(("world_", "mcp__gev__"))]


@pytest.mark.parametrize("brain", ["claude", None])
async def test_a_weather_turn_declares_no_world_tools(tmp_path, brain):
    tools = Tools()
    provider = Script([call("weather"), text("Clear, sir.")], name=brain)
    service = service_for(provider, tools)
    await service.reply("owner", ConversationRequest(text="What's the weather in KL?"), tmp_path)
    assert len(provider.declared) == 2
    for names in provider.declared:
        assert "weather" in names and world_names(names) == []
    assert tools.ran == ["weather"]


@pytest.mark.parametrize("brain", ["claude", None])
async def test_a_globe_turn_declares_them_and_its_follow_up_too(tmp_path, brain):
    tools = Tools()
    provider = Script(
        [call("world_show"), text("Penang, sir."), text("Closer, sir.")], name=brain
    )
    service = service_for(provider, tools)
    first = ConversationRequest(text="Show me Penang")
    await service.reply("owner", first, tmp_path)
    follow = ConversationRequest(text="now zoom closer", conversation_id=first.conversation_id)
    await service.reply("owner", follow, tmp_path)
    assert all(set(WORLD_NAMES) <= set(names) for names in provider.declared)
    assert tools.ran == ["world_show"]
    history = service.conversations[str(first.conversation_id)].history
    assert history[1]["tool_groups"] == ["world"] and "tool_groups" not in history[3]


@pytest.mark.parametrize("brain", ["claude", None])
async def test_an_open_world_page_declares_them_on_a_weather_turn(tmp_path, brain):
    tools = Tools()
    provider = Script([text("Clear, sir.")], name=brain)
    service = service_for(provider, tools)
    owners = []
    service.world_page_open = lambda owner: owners.append(owner) or True
    await service.reply("owner", ConversationRequest(text="Will it rain tomorrow?"), tmp_path)
    assert set(WORLD_NAMES) <= set(provider.declared[0]) and owners == ["owner"]


async def test_a_failing_page_check_counts_as_closed(tmp_path):
    tools = Tools()
    provider = Script([text("Clear, sir.")], name="claude")
    service = service_for(provider, tools)

    def broken(owner):
        raise RuntimeError("no world")

    service.world_page_open = broken
    await service.reply("owner", ConversationRequest(text="Will it rain tomorrow?"), tmp_path)
    assert world_names(provider.declared[0]) == []


@pytest.mark.parametrize("brain", ["claude", None])
async def test_a_call_to_an_undeclared_world_tool_is_refused(tmp_path, brain):
    tools = Tools()
    provider = Script([call("world_show"), text("Clear, sir.")], name=brain)
    service = service_for(provider, tools)
    await service.reply("owner", ConversationRequest(text="Cuaca hari ini"), tmp_path)
    assert tools.ran == []
    assert TOOL_NOT_OFFERED["error"] == "tool_unavailable"


# --- World view fails fast with no window -----------------------------------------------------
@pytest.fixture
def windowless(application_factory, tmp_path):
    """World view installed and on (empty stand-in files), the owner unlocked, and only a
    tray socket: no JARVIS window. ensure_ready is a recording fake, never the sidecar."""
    app = application_factory()
    app.sessions.principals.update({"tray": "owner"})
    app.sessions.roles.update({"tray": "resident"})
    app.sessions.local_owner = "owner"
    root = tmp_path / "gev"
    for part in ("dist/index.html", "node_modules/vite/bin/vite.js", "server/mcp/stdio.js"):
        (root / part).parent.mkdir(parents=True, exist_ok=True)
        (root / part).write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")
    app.settings["world"] = {
        "root": str(root), "node": str(node), "port": 4999, "idle_minutes": 10, "enabled": True,
    }
    app.settings["tool_permissions"].update({"world_show": False, "world_tour": False})
    started = []

    async def ensure_ready():
        started.append(True)

    async def spawner(*args):
        raise AssertionError("the globe sidecar must not start")

    app.world.ensure_ready = ensure_ready
    app.world.spawner = spawner
    app.world.started = started
    return app


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("world_show", {"area": {"place": "Penang"}}),
        ("world_tour", {"title": "Penang", "steps": [
            {"area": {"place": "Penang"}, "caption": "Penang, sir.", "seconds": 3}
        ]}),
    ],
)
async def test_world_tools_with_no_window_fail_fast_without_starting_the_globe(
    windowless, tmp_path, name, arguments
):
    began = time.monotonic()
    with pytest.raises(ServiceError) as raised:
        await windowless.dispatcher.dispatch(
            "owner", name, arguments, {"principal": "owner", "project_path": tmp_path}
        )
    assert time.monotonic() - began < 1.0
    assert raised.value.code == "world_no_window"
    assert str(raised.value) == "Open JARVIS on the World page to see the globe."
    assert windowless.world.started == [] and windowless.world.process is None


async def test_show_view_with_no_window_fails_fast_without_starting_the_globe(windowless):
    view = {"camera": {"lat": 5.4, "lon": 100.3, "altitude_m": 60000}}
    began = time.monotonic()
    with pytest.raises(ServiceError) as raised:
        await windowless.world.show_view(view)
    assert time.monotonic() - began < 1.0
    assert raised.value.code == "world_no_window" and windowless.world.started == []
    assert windowless.world.pending == {}


async def test_the_page_check_reads_the_open_world_page(windowless):
    assert windowless.world_tools.page_open("owner") is False
    assert windowless.conversation.world_page_open("owner") is False
    windowless.sessions.principals["client"] = "owner"
    windowless.sessions.roles["client"] = "renderer"
    windowless.world.page("client", True)
    assert windowless.conversation.world_page_open("owner") is True
    windowless.world.page("client", False)
    assert windowless.conversation.world_page_open("owner") is False
