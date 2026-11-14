"""Turn budgets for brain turns (S1 layer 5): no turn can stall for minutes.

Fake providers and tools only, tiny budgets, no network, audio or camera.
"""

import asyncio
import logging
import time

import pytest
from pydantic import BaseModel, ConfigDict

from llm.base import LLMResponse, ToolCall
from services import conversation as conversation_module
from services.conversation import (
    TOOL_TIMED_OUT,
    ConversationRequest,
    ConversationService,
    budget_answer,
    claude_messages,
    close_tool_uses,
    progress_phrase,
    turn_budget_s,
)
from services.tools import ToolDispatcher, ToolSpec

USER_TEXT = "private-question-marker what is the weather in Ipoh"


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def hang(kwargs):
    await asyncio.Event().wait()


class Script:
    """A provider that plays one scripted step per call. A step is an LLMResponse or an
    async callable(kwargs); cancellations are counted."""

    def __init__(self, steps, name=None, model=None, progress=True):
        self.name, self._model, self.reports_progress = name, model, progress
        self.steps = list(steps)
        self.calls = []
        self.cancelled = 0
        self.closed = False

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        step = self.steps.pop(0)
        try:
            return await step(kwargs) if callable(step) else step
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def close(self):
        self.closed = True


def text(value):
    return LLMResponse(text=value, content_blocks=[{"type": "text", "text": value}])


def tools(*names):
    calls = [ToolCall(f"call-{index}", name, {}) for index, name in enumerate(names)]
    blocks = [{"type": "tool_use", "id": call.id, "name": call.name, "input": {}} for call in calls]
    return LLMResponse(tool_calls=calls, content_blocks=blocks)


class Tools:
    def __init__(self, permissions=None):
        self.cancelled = []
        self.dispatcher = ToolDispatcher(
            lambda: permissions
            or {"weather": False, "hang": False, "slow_build": False, "slow_lookup": False}
        )
        self.dispatcher.register(ToolSpec("weather", "Forecast.", NoArgs, self.weather))
        self.dispatcher.register(ToolSpec("hang", "Never returns.", NoArgs, self.hang,
                                          execution_timeout=240))
        self.dispatcher.register(ToolSpec("slow_build", "Takes a while.", NoArgs, self.slow,
                                          long_running=True))
        self.dispatcher.register(ToolSpec("slow_lookup", "Takes a while.", NoArgs, self.slower))

    async def weather(self, args, context):
        return {"forecast": "clear", "high_c": 31}

    async def hang(self, args, context):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append("hang")
            raise

    async def slow(self, args, context):
        await asyncio.sleep(0.15)
        return {"done": True}

    async def slower(self, args, context):
        await asyncio.sleep(0.5)
        return {"done": True}


def service_for(provider, tools_=None, fast=None, settings=None, **options):
    tools_ = tools_ or Tools()
    service = ConversationService(
        tools_.dispatcher,
        lambda: provider,
        settings=(lambda: settings) if settings else None,
        fast_provider_factory=(lambda: fast) if fast else (lambda: provider),
        **options,
    )
    return service, tools_


async def ask(service, tmp_path, budget, **options):
    request = ConversationRequest(text=USER_TEXT)
    started = time.monotonic()
    result = await service.reply("owner", request, tmp_path, turn_budget=budget, **options)
    return result, time.monotonic() - started, service.conversations[str(request.conversation_id)]


def assert_no_orphans():
    others = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    assert others == []


def assert_valid_claude_history(history):
    assert_valid_messages(claude_messages(history), "assistant")


def assert_valid_messages(messages, last_role):
    """Every tool_use answered by a tool_result in the next message; roles alternate."""
    messages = [item for item in messages if item["role"] != "system"]
    roles = [item["role"] for item in messages]
    assert roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False))
    for index, message in enumerate(messages):
        content = message["content"] if isinstance(message["content"], list) else []
        uses = [block["id"] for block in content if block.get("type") == "tool_use"]
        if uses:
            following = messages[index + 1]["content"]
            answered = [block["tool_use_id"] for block in following
                        if block.get("type") == "tool_result"]
            assert sorted(answered) == sorted(uses)
    assert messages[-1]["role"] == last_role


# --- first-token deadline -------------------------------------------------------------


async def test_a_silent_claude_step_retries_once_on_the_fast_route(tmp_path):
    brain = Script([hang], name="claude", model="claude-sonnet-5-5")
    fast = Script([text("Clear skies in Ipoh, sir.")], name="claude", model="claude-haiku-5-5")
    service, _ = service_for(brain, fast=fast, first_token_timeout=0.05)
    result, elapsed, conversation = await ask(service, tmp_path, 2.0)
    assert result.text == "Clear skies in Ipoh, sir."
    assert brain.cancelled == 1 and len(fast.calls) == 1
    assert fast.closed and brain.closed
    assert elapsed < 1.0
    assert conversation.history[-1]["model"] == "claude-haiku-5-5"
    assert_no_orphans()


async def test_a_silent_step_and_a_silent_retry_end_truthfully_inside_the_budget(tmp_path):
    brain = Script([hang], name="claude", model="claude-sonnet-5-5")
    fast = Script([hang], name="claude", model="claude-haiku-5-5")
    service, _ = service_for(brain, fast=fast, first_token_timeout=0.03)
    result, elapsed, conversation = await ask(service, tmp_path, 0.15)
    assert result.text == "I couldn't finish that in time, sir."
    assert brain.cancelled == 1 and fast.cancelled == 1 and fast.closed
    assert elapsed < 0.5
    assert_valid_claude_history(conversation.history)
    assert_no_orphans()


async def test_a_silent_gemini_step_retries_once_on_the_same_model(tmp_path):
    brain = Script([hang, text("Thirty one degrees.")], name="gemini", model="gemini-3.8-flash")
    picked = []
    service, _ = service_for(brain, first_token_timeout=0.05)
    service.fast_provider_factory = lambda: picked.append(1)
    result, _, _ = await ask(service, tmp_path, 2.0)
    assert result.text == "Thirty one degrees."
    assert len(brain.calls) == 2 and brain.cancelled == 1 and not picked
    # The step cap goes to Gemini as its retry budget.
    assert 0 < brain.calls[1][1]["budget"] <= 2.0


async def test_any_streamed_progress_keeps_the_step_alive(tmp_path):
    async def thinks_then_answers(kwargs):
        kwargs["on_progress"]()  # e.g. a thinking block started
        await asyncio.sleep(0.1)
        return text("Done thinking.")

    brain = Script([thinks_then_answers], name="claude", model="claude-sonnet-5-5")
    fast = Script([], name="claude", model="claude-haiku-5-5")
    service, _ = service_for(brain, fast=fast, first_token_timeout=0.05)
    result, _, _ = await ask(service, tmp_path, 2.0)
    assert result.text == "Done thinking." and not fast.calls and brain.cancelled == 0


async def test_streamed_text_counts_as_progress(tmp_path):
    async def streams(kwargs):
        await kwargs["on_text"]("Partly ")
        await asyncio.sleep(0.1)
        return LLMResponse(text="Partly cloudy.")

    class Listener:
        async def text(self, value, step):
            pass

        async def working(self):
            pass

    brain = Script([streams], progress=False)
    service, _ = service_for(brain, first_token_timeout=0.05)
    result, _, _ = await ask(service, tmp_path, 2.0, stream=Listener())
    assert result.text == "Partly cloudy." and brain.cancelled == 0


# --- tools inside the budget ----------------------------------------------------------


async def test_a_hanging_tool_is_cut_and_the_model_still_answers(tmp_path):
    brain = Script([tools("hang"), text("The lookup timed out, sir.")])
    service, tools_ = service_for(brain)
    result, elapsed, _ = await ask(service, tmp_path, 0.3)
    assert result.text == "The lookup timed out, sir."
    assert tools_.cancelled == ["hang"]
    tool_message = brain.calls[1][0][-1]
    assert tool_message.tool_call_id == "call-0" and "action_timeout" in tool_message.content
    assert elapsed < 0.6
    assert_no_orphans()


async def test_a_hanging_tool_in_a_claude_turn_gets_an_error_result(tmp_path):
    brain = Script([tools("hang"), text("It timed out, sir.")], name="claude",
                   model="claude-sonnet-5-5")
    service, _ = service_for(brain)
    result, _, conversation = await ask(service, tmp_path, 0.3)
    assert result.text == "It timed out, sir."
    (block,) = brain.calls[1][0][-1]["content"]
    assert block["is_error"] is True and "action_timeout" in block["content"]
    assert_valid_claude_history(conversation.history)


async def test_a_long_running_tool_pauses_the_budget(tmp_path):
    brain = Script([tools("slow_build"), text("Built it.")])
    service, _ = service_for(brain)
    result, elapsed, _ = await ask(service, tmp_path, 0.1)
    assert result.text == "Built it."
    assert elapsed > 0.1  # wall time beyond the budget, all of it in the long-running tool


async def test_the_same_wait_in_an_ordinary_tool_is_cut(tmp_path):
    brain = Script([tools("slow_lookup"), text("That took too long.")])
    service, _ = service_for(brain)
    result, _, _ = await ask(service, tmp_path, 0.3)
    assert result.text == "That took too long."
    assert "action_timeout" in brain.calls[1][0][-1].content


async def test_the_owner_deciding_on_an_approval_does_not_spend_the_budget(tmp_path):
    tools_ = Tools(permissions={"weather": True})
    brain = Script([tools("weather"), text("Clear, sir.")])
    service, _ = service_for(brain, tools_)

    async def approve_later(payload):
        async def click():
            await asyncio.sleep(0.15)
            tools_.dispatcher.resolve("owner", payload["id"], True)

        clicks.append(asyncio.ensure_future(click()))

    clicks = []
    result, elapsed, _ = await ask(service, tmp_path, 0.1, request_approval=approve_later)
    await asyncio.gather(*clicks)
    assert result.text == "Clear, sir." and elapsed > 0.1
    assert "high_c" in brain.calls[1][0][-1].content


# --- budget expiry --------------------------------------------------------------------


async def test_budget_expiry_answers_truthfully_logs_and_keeps_history_valid(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    brain = Script([tools("weather", "hang"), hang], name="claude", model="claude-sonnet-5-5")
    service, tools_ = service_for(brain)
    result, elapsed, conversation = await ask(service, tmp_path, 0.2)
    assert result.text == (
        "I couldn't finish that in time, sir. I got as far as checking the forecast."
    )
    assert elapsed < 0.5 and tools_.cancelled == ["hang"] and brain.cancelled == 1
    lines = [record.getMessage() for record in caplog.records if "outcome=budget" in
             record.getMessage()]
    assert any(line.startswith("Brain turn stopped:") for line in lines)
    for line in lines:
        assert "private-question-marker" not in line and "Ipoh" not in line
    timing = [record.getMessage() for record in caplog.records
              if record.getMessage().startswith("AI provider request:")]
    assert timing and timing[-1].endswith("outcome=budget")
    assert_valid_claude_history(conversation.history)
    stored = claude_messages(conversation.history)
    assert stored[-1] == {"role": "assistant", "content": [{"type": "text", "text": result.text}]}
    assert_no_orphans()

    # The next turn's request is built on that history and is accepted as is.
    brain.steps = [text("It's clear now.")]
    follow = ConversationRequest(text="And now?", conversation_id=conversation_id(service))
    again = await service.reply("owner", follow, tmp_path, turn_budget=1.0)
    assert again.text == "It's clear now."
    sent = brain.calls[-1][0]
    assert sent[-2] == {"role": "user", "content": "And now?"}
    assert_valid_messages(sent, "user")


def conversation_id(service):
    (key,) = service.conversations
    return key


async def test_budget_expiry_in_a_text_turn_stores_text_only(tmp_path):
    brain = Script([tools("weather"), hang], name="gemini", model="gemini-3.8-flash")
    service, _ = service_for(brain, settings={"assistant": {"address": "maam"}})
    result, _, conversation = await ask(service, tmp_path, 0.15)
    assert result.text == (
        "I couldn't finish that in time, ma'am. I got as far as checking the forecast."
    )
    assert conversation.history == [
        {"role": "user", "content": USER_TEXT},
        {"role": "assistant", "content": result.text},
    ]


def test_dangling_tool_uses_get_a_timed_out_result():
    turn = [{"role": "assistant", "content": [
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "a", "name": "weather", "input": {}},
        {"type": "tool_use", "id": "b", "name": "hang", "input": {}},
    ]}]
    closed = close_tool_uses(turn)
    assert len(turn) == 1  # the original is not edited
    assert [block["tool_use_id"] for block in closed[1]["content"]] == ["a", "b"]
    assert all(block["is_error"] and "action_timeout" in block["content"]
               for block in closed[1]["content"])
    assert TOOL_TIMED_OUT["error"] == "action_timeout"
    already = [*closed, {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}]
    assert close_tool_uses(already) == already


@pytest.mark.parametrize(
    ("settings", "finished", "expected"),
    [
        ({}, [], "I couldn't finish that in time, sir."),
        ({"assistant": {"address": "none"}}, ["calendar_read"],
         "I couldn't finish that in time. I got as far as checking your calendar."),
        ({"assistant": {"address": "name", "owner_name": " Hiro "}},
         ["weather", "mcp__gev__flights", "weather", "home_control"],
         "I couldn't finish that in time, Hiro. I got as far as checking the forecast, "
         "pulling the live map data and working on it."),
        ({"assistant": {"address": "name"}}, [], "I couldn't finish that in time."),
    ],
)
def test_budget_answers_use_the_form_of_address(settings, finished, expected):
    assert budget_answer(settings, finished) == expected


def test_progress_phrases():
    assert progress_phrase("weather") == "checking the forecast"
    assert progress_phrase("web_search") == "searching the web"
    assert progress_phrase("mcp__gev__layers") == "pulling the live map data"
    assert progress_phrase("read_file") == "working on it"


# --- chat and voice budgets -----------------------------------------------------------


def test_voice_turns_get_sixty_seconds_and_everything_else_two_minutes():
    assert turn_budget_s("voice_brain") == 60
    assert turn_budget_s("desktop_chat") == 120
    assert turn_budget_s("phone_chat") == 120


@pytest.mark.parametrize(("feature", "seconds"), [("voice_brain", 60), ("desktop_chat", 120)])
async def test_reply_picks_the_budget_from_the_usage_feature(monkeypatch, tmp_path, feature,
                                                             seconds):
    made = []

    class Recording(conversation_module.TurnBudget):
        def __init__(self, value, *args, **kwargs):
            made.append(value)
            super().__init__(value, *args, **kwargs)

    monkeypatch.setattr(conversation_module, "TurnBudget", Recording)
    service, _ = service_for(Script([text("Hello.")]))
    await service.reply("owner", ConversationRequest(text="Hi"), tmp_path, usage_feature=feature)
    assert made == [seconds]
