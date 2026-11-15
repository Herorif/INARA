"""No stall, as a whole (S1 layer 7, docs/AI_PROVIDERS.md "Why JARVIS never hangs").

A simple question used to hang for minutes. S1 found five causes, numbered as in
docs/handover/9NovWork-specs.md S1 "Why it stalls today":

1. there was no weather tool (and no web search tool);
2. weather questions were sent to the God's Eye View globe tools;
3. a brain turn had no overall time limit (5 steps x 45 s of model time alone);
4. tools could wait a long time (globe data 135 s, globe start 60 s, world_show 150 s,
   world_tour 240 s);
5. voice waited for the brain with no deadline, and the voice model filled the silence with
   invented status.

Each test below names the cause it guards against. The deeper cases live beside the code
(test_tool_groups, test_turn_budget, test_ask_brain_phases, test_voice_quick_tools,
test_weather, test_turn_timing); this file reuses their fakes and is the one place that
proves "no stall" end to end. Fake providers, fake HTTP and tiny patched budgets only: no
network, audio, camera, globe or provider.
"""

import asyncio
import json
import time
import uuid

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from llm.base import LLMResponse, ToolCall
from services import voice as voice_module
from services.conversation import (
    FIRST_TOKEN_S,
    TURN_BUDGET_S,
    VOICE_TURN_BUDGET_S,
    ConversationRequest,
    claude_messages,
)
from services.tools import ServiceError, ToolSpec
import tests.test_ask_brain_phases as phase_tests
import tests.test_tool_groups as tool_group_tests
import tests.test_voice_quick_tools as quick_tests
import tests.test_weather as weather_tests
from tests.test_ask_brain_phases import BlockingProvider
from tests.test_tool_groups import Script as DeclaringScript
from tests.test_tool_groups import world_names
from tests.test_turn_budget import Script, assert_no_orphans, assert_valid_claude_history
from tests.test_turn_budget import ask as budget_ask
from tests.test_turn_budget import hang, service_for, text, tools
from tests.test_voice_quick_tools import FakeConnector as QuickConnector
from tests.test_voice_quick_tools import ask as quick_ask
from tests.test_voice_quick_tools import start as quick_start
from tests.test_weather import FakeMeteo

# Read at import, before any fixture patches them.
SHIPPED_INTERIM_S = voice_module.INTERIM_SECONDS
HOME = {"name": "Kuala Lumpur, Malaysia", "lat": 3.1412, "lon": 101.68653}
GEV = ("mcp__gev__get_earthquakes", "mcp__gev__flights", "mcp__gev__show_in_gods_eye_view")
SLACK = 0.5  # scheduling slack on a loaded Windows runner


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@pytest.fixture
def meteo():
    return FakeMeteo()


@pytest.fixture
def weather_app(application_factory, meteo):
    """The real application with Open-Meteo faked (test_weather's ``app``)."""
    return weather_tests.app.__wrapped__(application_factory, meteo)


@pytest.fixture
def windowless(application_factory, tmp_path):
    """World view on, the owner unlocked, no JARVIS window (test_tool_groups)."""
    return tool_group_tests.windowless.__wrapped__(application_factory, tmp_path)


@pytest.fixture
def phases_voice(application_factory, monkeypatch):
    """A fake Live session, the ask_brain thresholds patched to ms (test_ask_brain_phases)."""
    return phase_tests.voice.__wrapped__(application_factory, monkeypatch)


@pytest.fixture
def quick_voice(application_factory, monkeypatch):
    """A fake Live session; any brain turn or history entry fails (test_voice_quick_tools)."""
    return quick_tests.voice.__wrapped__(application_factory, monkeypatch)


class RecordingScript(DeclaringScript):
    """test_tool_groups' Script (it keeps the declared tool names per step) that also keeps
    the messages each step was sent."""

    def __init__(self, steps, name=None):
        super().__init__(steps, name=name)
        self.messages = []

    async def generate(self, messages, **kwargs):
        self.messages.append(list(messages))
        return await super().generate(messages, **kwargs)


def tool_result_text(message):
    """The one tool result the model was sent, for either provider's message shape."""
    if isinstance(message, dict):
        (block,) = message["content"]
        return block["content"]
    return message.content


def weather_call(**arguments):
    call = ToolCall("call-weather", "weather", arguments)
    return LLMResponse(
        tool_calls=[call],
        content_blocks=[{"type": "tool_use", "id": call.id, "name": call.name,
                         "input": arguments}],
    )


# --- 1 ----------------------------------------------------------------------------------------
async def test_a_weather_turn_is_never_offered_the_world_tool_group(weather_app, meteo):
    """Causes 1 and 2: weather questions went to the globe tools because there was no
    weather tool. Through the real ConversationService and the real dispatcher, with
    world_show, world_tour and mcp__gev__* registered, "what's the weather today?" declares
    the weather tool and none of the world group, and the real weather tool answers from the
    home town."""
    app = weather_app
    app.settings.setdefault("assistant", {})["home_place"] = dict(HOME)
    ran = []

    def runner(name):
        async def run(args, context):
            ran.append(name)
            return {"ok": True}

        return run

    for name in GEV:
        app.dispatcher.register(ToolSpec(name, f"The {name} tool.", NoArgs, runner(name)))
        app.settings["tool_permissions"][name] = False
    assert {"world_show", "world_tour", "weather", *GEV} <= set(app.dispatcher.tools)
    # The real World page check: no page is open.
    assert app.conversation.world_page_open("owner") is False
    project = app.projects.get_current_project_path().resolve()

    for brain in ("claude", None):  # Claude, and the Gemini fallback's declarations
        provider = RecordingScript(
            [weather_call(when="today"), LLMResponse(text="31 degrees and light rain, sir.")],
            name=brain,
        )
        app.conversation.provider_factory = lambda provider=provider: provider
        request = ConversationRequest(text="what's the weather today?")
        result = await app.conversation.reply("owner", request, project)
        assert result.text == "31 degrees and light rain, sir."
        assert len(provider.declared) == 2
        for names in provider.declared:
            assert "weather" in names
            assert world_names(names) == []
        # The real weather tool answered from the home town.
        assert "Kuala Lumpur" in tool_result_text(provider.messages[1][-1])
        history = app.conversation.restore("owner", request.conversation_id, project)
        assert history[-1] == {"role": "assistant", "content": result.text}
    assert ran == []
    # The home town's forecast, read once (the second turn hit the 10 minute cache).
    assert meteo.hosts() == ["api.open-meteo.com"]


# --- 2 ----------------------------------------------------------------------------------------
async def test_a_model_that_never_answers_falls_back_at_the_first_token_deadline(tmp_path):
    """Cause 3: a model step could take 45 s, five times over, with nothing to show. A step
    with no first token by the deadline (20 s shipped, 50 ms here) is cancelled and retried
    once on the fast route; when the retry is silent too, the turn ends with a truthful
    answer inside its budget instead of hanging."""
    assert FIRST_TOKEN_S == 20.0
    deadline = 0.05
    asked = []

    async def fast_answer(kwargs):
        asked.append(time.monotonic())
        return text("Clear skies in Ipoh, sir.")

    brain = Script([hang], name="claude", model="claude-sonnet-5-5")
    fast = Script([fast_answer], name="claude", model="claude-haiku-5-5")
    service, _ = service_for(brain, fast=fast, first_token_timeout=deadline)
    began = time.monotonic()
    result, elapsed, conversation = await budget_ask(service, tmp_path, 2.0)
    assert result.text == "Clear skies in Ipoh, sir."
    assert brain.cancelled == 1 and len(fast.calls) == 1
    # The fallback started at the deadline (timer resolution allowed for), not later.
    assert deadline - 0.02 <= asked[0] - began < deadline + SLACK
    assert elapsed < 2.0
    assert service.last_turn_timing["outcome"] == "ok"
    assert_valid_claude_history(conversation.history)
    assert_no_orphans()

    # The retry never answers either: a truthful failure, inside the budget.
    budget = 0.3
    brain = Script([hang], name="claude", model="claude-sonnet-5-5")
    fast = Script([hang], name="claude", model="claude-haiku-5-5")
    service, _ = service_for(brain, fast=fast, first_token_timeout=deadline)
    result, elapsed, conversation = await budget_ask(service, tmp_path, budget)
    assert result.text == "I couldn't finish that in time, sir."
    assert brain.cancelled == 1 and fast.cancelled == 1
    assert budget - 0.02 <= elapsed < budget + SLACK
    assert service.last_turn_timing["outcome"] == "budget"
    assert_valid_claude_history(conversation.history)
    assert_no_orphans()


# --- 3 ----------------------------------------------------------------------------------------
async def test_a_tool_that_hangs_is_cut_at_the_budget_and_the_turn_still_answers(tmp_path):
    """Cause 4 (and 3): a tool could wait minutes (world_show 150 s, a globe data call
    135 s). A tool that never returns, with a 240 s timeout of its own, is cut where the
    turn's budget says, and the turn still returns text with a valid history: every
    tool_use has its tool_result, so the next turn's request is accepted."""
    budget = 0.3
    brain = Script(
        [tools("weather", "hang"), text("The forecast is clear; the other lookup timed out.")],
        name="claude", model="claude-sonnet-5-5",
    )
    service, tools_ = service_for(brain)
    assert tools_.dispatcher.tools["hang"].execution_timeout == 240
    result, elapsed, conversation = await budget_ask(service, tmp_path, budget)
    assert result.text == "The forecast is clear; the other lookup timed out."
    assert tools_.cancelled == ["hang"]
    assert elapsed < budget + SLACK
    results = {block["tool_use_id"]: block for block in brain.calls[1][0][-1]["content"]}
    assert "high_c" in results["call-0"]["content"]
    assert results["call-1"]["is_error"] is True
    assert "action_timeout" in results["call-1"]["content"]
    assert_valid_claude_history(conversation.history)
    assert service.last_turn_timing["outcome"] == "ok"
    assert_no_orphans()

    # The model hangs too after the cut: the budget answer says what finished.
    brain = Script([tools("weather", "hang"), hang], name="claude", model="claude-sonnet-5-5")
    service, tools_ = service_for(brain)
    result, elapsed, conversation = await budget_ask(service, tmp_path, budget)
    assert result.text == (
        "I couldn't finish that in time, sir. I got as far as checking the forecast."
    )
    assert tools_.cancelled == ["hang"] and brain.cancelled == 1
    assert elapsed < budget + SLACK
    assert_valid_claude_history(conversation.history)
    stored = claude_messages(conversation.history)
    assert stored[-1] == {"role": "assistant", "content": [{"type": "text", "text": result.text}]}
    assert_no_orphans()


# --- 4 ----------------------------------------------------------------------------------------
async def test_a_long_running_tool_pauses_the_budget(tmp_path, application_factory):
    """Cause 3's fix must not break real long work: a budget that cut everything would turn
    a CAD build or a world tour into a failure. While a ``long_running`` tool runs the
    budget clock is paused (its own timeout still bounds it); the same wait in an ordinary
    tool is cut."""
    assert (VOICE_TURN_BUDGET_S, TURN_BUDGET_S) == (60.0, 120.0)
    budget = 0.1
    brain = Script([tools("slow_build"), text("Built it.")])
    service, tools_ = service_for(brain)
    assert tools_.dispatcher.tools["slow_build"].long_running is True
    result, elapsed, _ = await budget_ask(service, tmp_path, budget)
    assert result.text == "Built it."
    assert elapsed > budget  # more wall time than the whole budget, spent in the tool
    assert "done" in brain.calls[1][0][-1].content
    timing = service.last_turn_timing
    assert timing["outcome"] == "ok"
    (tool_step,) = [step for step in timing["steps"] if step["name"] == "slow_build"]
    assert tool_step["ms"] >= 100

    # The same kind of wait in an ordinary tool is cut, and the model still answers.
    brain = Script([tools("slow_lookup"), text("That took too long, sir.")])
    service, _ = service_for(brain)
    result, elapsed, _ = await budget_ask(service, tmp_path, 0.3)
    assert result.text == "That took too long, sir."
    assert "action_timeout" in brain.calls[1][0][-1].content
    assert elapsed < 0.5

    # The shipped tools: a tour holds the budget, a single view does not.
    app = application_factory()
    assert app.dispatcher.tools["world_tour"].long_running is True
    assert app.dispatcher.tools["world_show"].long_running is False
    assert app.dispatcher.tools["weather"].long_running is False


# --- 5 ----------------------------------------------------------------------------------------
async def open_live(app, connector, conversation_id):
    """Start a voice session and wait for its new fake Live connection."""
    count = len(connector.connections)
    ack = await app.sio.handlers["/"]["voice_start"](
        "client", {"mode": "push_to_talk", "conversation_id": str(conversation_id)}
    )
    assert ack["ok"], ack
    await until(lambda: len(connector.connections) > count)
    live = connector.connections[-1]
    await until(lambda: app.voice.sessions.get("owner") is not None
                and app.voice.sessions["owner"].live is live)
    return live


async def until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(0.005)


async def test_ask_brain_answers_in_two_phases_and_a_closed_session_still_stores_it(
    phases_voice,
):
    """Cause 5: voice waited for the brain with no deadline and the voice model filled the
    silence with invented status ("One moment"). A brain turn still running at the
    threshold (4 s shipped, 30 ms here) gets a real interim reply; the answer comes as one
    final text turn. If the Live session closes mid-task, the answer still lands in the
    conversation and nothing is sent to the closed session."""
    assert SHIPPED_INTERIM_S == 4.0
    interim_s = voice_module.INTERIM_SECONDS
    app, connector = phases_voice
    project = app.projects.get_current_project_path().resolve()
    loop = asyncio.get_running_loop()

    # Live session open: interim at the threshold, then the final injection.
    answer = "Thirty one degrees and light rain in Kuala Lumpur, sir."
    provider = BlockingProvider(answer)
    app.conversation.provider_factory = lambda: provider
    conversation_id = uuid.uuid4()
    live = await open_live(app, connector, conversation_id)
    asked = loop.time()
    live.call("slow", request="What's the weather in Kuala Lumpur and the latest news?")
    await provider.started.wait()
    await until(lambda: live.tool_responses)
    waited = loop.time() - asked
    assert interim_s - 0.02 <= waited < interim_s + SLACK
    (interim,) = live.tool_responses[0]
    assert (interim.id, interim.name) == ("slow", "ask_brain")
    assert interim.response == {
        "status": "working", "say": "Working on it, sir.", "then": "wait silently",
    }
    assert live.texts() == []  # no invented status while the brain works
    provider.release.set()
    await until(lambda: live.texts())
    (final,) = live.texts()
    assert final.startswith("Answer for the owner's request: " + json.dumps(answer) + ".")
    assert len(live.tool_responses) == 1  # the call was answered once
    history = app.conversation.restore("owner", conversation_id, project)
    assert history[-1] == {"role": "assistant", "content": answer}
    assert app.conversation.last_turn_timing["origin"] == "voice"
    await app.voice.stop_sid()
    await until(lambda: not app.voice.sessions)

    # The session closes mid-task: the answer is stored, never injected.
    answer = "Here is what I found."
    provider = BlockingProvider(answer)
    app.conversation.provider_factory = lambda: provider
    conversation_id = uuid.uuid4()
    live = await open_live(app, connector, conversation_id)
    live.call("drop", request="Look this up")
    await provider.started.wait()
    await until(lambda: live.tool_responses)  # phase 1 went out
    live.inbox.put_nowait(ConnectionError("link lost"))
    await until(lambda: not app.voice.sessions)
    (task,) = app.voice.released  # released to finish, not cancelled
    sent = (list(live.sent), list(live.tool_responses))
    provider.release.set()
    await asyncio.wait_for(task, 2)
    assert task.exception() is None
    history = app.conversation.restore("owner", conversation_id, project)
    assert history == [
        {"role": "user", "content": "Look this up"},
        {"role": "assistant", "content": answer},
    ]
    # Nothing more went to the closed session (its FakeLive raises if anything had).
    assert (live.sent, live.tool_responses) == sent and live.texts() == []


# --- 6 ----------------------------------------------------------------------------------------
async def test_quick_weather_answers_without_creating_a_brain_turn(quick_voice, meteo):
    """Causes 1 and 5: a plain weather question by voice went through a full brain turn
    (and from there to the globe). quick_weather answers in the voice layer from the real
    WeatherService (Open-Meteo faked): no brain turn, no conversation, no history entry
    (the fixture's reply and append_turns fail the test if called)."""
    app, connector = quick_voice
    assert isinstance(connector, QuickConnector)
    app.weather.transport = httpx.MockTransport(meteo)
    app.weather.cache.clear()
    live = await quick_start(app, connector)
    began = time.monotonic()
    response = await quick_ask(live, "quick_weather", {"place": "Kuala Lumpur", "when": "today"})
    assert time.monotonic() - began < 1.0
    assert response["answer"] == (
        "Kuala Lumpur: 31°C, feels like 36, light rain; today 25 to 33 with a 70% chance of rain."
    )
    assert response["data"]["place"] == "Kuala Lumpur, Malaysia"
    assert meteo.hosts() == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    app.conversation.reply.assert_not_called()
    app.conversation.append_turns.assert_not_called()
    assert len(app.conversation.conversations) == 0
    assert app.conversation.last_turn_timing is None
    session = app.voice.sessions["owner"]
    assert not session.brain and not session.brain_turn
    await app.voice.stop_sid()


# --- 7 ----------------------------------------------------------------------------------------
async def test_world_show_with_no_window_fails_fast_and_never_starts_the_globe(
    windowless, tmp_path
):
    """Cause 4: world_show started the globe (up to 60 s) before finding there was nowhere
    to show it, inside a tool that could take 150 s. With no JARVIS window it fails in
    under a second, both as a tool call and inside a brain turn, and the globe sidecar is
    never started."""
    app = windowless
    began = time.monotonic()
    with pytest.raises(ServiceError) as raised:
        await app.dispatcher.dispatch(
            "owner", "world_show", {"area": {"place": "Penang"}},
            {"principal": "owner", "project_path": tmp_path},
        )
    assert time.monotonic() - began < 1.0
    assert raised.value.code == "world_no_window"

    # The same call from the brain: the error goes back as data and the turn answers.
    call = ToolCall("call-show", "world_show", {"area": {"place": "Penang"}})
    provider = RecordingScript(
        [
            LLMResponse(tool_calls=[call], content_blocks=[
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
            ]),
            text("Open JARVIS on the World page to see the globe, sir."),
        ],
        name="claude",
    )
    app.conversation.provider_factory = lambda: provider
    project = app.projects.get_current_project_path().resolve()
    request = ConversationRequest(text="Show me Penang")
    began = time.monotonic()
    result = await app.conversation.reply("owner", request, project)
    assert time.monotonic() - began < 1.0
    assert result.text == "Open JARVIS on the World page to see the globe, sir."
    assert "world_show" in provider.declared[0]
    (block,) = provider.messages[1][-1]["content"]
    assert block["tool_use_id"] == "call-show" and block["is_error"] is True
    assert "world_no_window" in block["content"]
    assert app.world.started == [] and app.world.process is None
    assert app.world.pending == {}
