"""S1 layer 7: one content-free turn_timing line per brain turn, the owner's brain check,
and CAD planning without web search. Fake providers, fake weather; no network."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from llm.base import LLMResponse, ToolCall
from llm.router import TaskRouter
from services.brain_check import CHECK_PROMPT, BrainCheck
from services.conversation import (
    ConversationRequest,
    ConversationService,
    TurnBudget,
    create_text_provider,
    timing_steps,
)
from services.tools import ServiceError, ToolDispatcher, ToolSpec
from pydantic import BaseModel, ConfigDict

SECRET = "secret-marker-7f3a in Ipoh"


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Script:
    def __init__(self, steps, name="claude", model="claude-sonnet-5-5", progress=True):
        self.name, self._model, self.reports_progress = name, model, progress
        self.effort = "high"
        self.steps = list(steps)
        self.calls = []
        self.closed = False

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return await step(kwargs) if callable(step) else step

    async def close(self):
        self.closed = True


def claude_usage(input_tokens, output_tokens, cache_read=0):
    return SimpleNamespace(content=[], usage=SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
    ))


def text(value, raw=None):
    return LLMResponse(text=value, content_blocks=[{"type": "text", "text": value}], raw=raw)


def tools(*names, raw=None):
    calls = [ToolCall(f"call-{index}", name, {"place": SECRET}) for index, name in enumerate(names)]
    blocks = [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
              for call in calls]
    return LLMResponse(tool_calls=calls, content_blocks=blocks, raw=raw)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: str


def dispatcher():
    made = ToolDispatcher(lambda: {"weather": False, "hang": False})

    async def weather(args, context):
        await asyncio.sleep(0.02)
        return {"forecast": "clear"}

    async def hang(args, context):
        await asyncio.Event().wait()

    made.register(ToolSpec("weather", "Forecast.", Args, weather))
    made.register(ToolSpec("hang", "Never returns.", Args, hang, execution_timeout=240))
    return made


def service_for(provider):
    return ConversationService(dispatcher(), lambda: provider,
                               fast_provider_factory=lambda: provider)


def timing_lines(caplog):
    return [record.getMessage() for record in caplog.records
            if record.getMessage().startswith("turn_timing ")]


def fields(line):
    parts = line.split(" ")[1:]
    return dict(part.split("=", 1) for part in parts)


async def test_ok_turn_logs_every_field_and_no_content(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    async def first(kwargs):
        await asyncio.sleep(0.03)
        kwargs["on_progress"]()
        return tools("weather", raw=claude_usage(100, 20, cache_read=900))

    provider = Script([first, text("Clear skies in Ipoh, sir.", raw=claude_usage(50, 10))])
    service = service_for(provider)
    request = ConversationRequest(text=f"What's the weather? {SECRET}")
    result = await service.reply("owner", request, tmp_path, usage_feature="voice_brain")
    assert result.text.startswith("Clear")
    lines = timing_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert "secret-marker-7f3a" not in line and "Ipoh" not in line
    got = fields(line)
    assert got["request_id"] == str(request.request_id)
    assert got["origin"] == "voice" and got["provider"] == "claude"
    # The provider's own effort (the router sets the owner's assistant.effort) is sent.
    assert got["model"] == "claude-sonnet-5-5" and got["effort"] == "high"
    assert got["outcome"] == "ok"
    assert int(got["first_token_ms"]) >= 25
    assert int(got["total_ms"]) >= int(got["first_token_ms"])
    assert got["input_tokens"] == "1050" and got["output_tokens"] == "30"
    steps = got["steps"].strip("[]").split(",")
    assert [item.split(":")[0] for item in steps] == ["model", "weather", "model"]
    assert all(item.split(":")[1].isdigit() for item in steps)
    timing = service.last_turn_timing
    assert timing["outcome"] == "ok" and timing["origin"] == "voice"
    assert [item["name"] for item in timing["steps"]] == ["model", "weather", "model"]
    assert SECRET not in repr(timing)
    # No other line from the turn carries the message text either.
    for record in caplog.records:
        assert "secret-marker-7f3a" not in record.getMessage()


async def test_first_token_without_progress_is_the_first_step_answer(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    async def slow(kwargs):
        await asyncio.sleep(0.03)
        return text("Hello.")

    service = service_for(Script([slow], name="gemini", model="gemini-3.8-flash", progress=False))
    await service.reply("owner", ConversationRequest(text=SECRET), tmp_path)
    got = fields(timing_lines(caplog)[-1])
    assert got["origin"] == "chat" and got["provider"] == "gemini"
    assert got["effort"] == "-"  # Gemini manages its own thinking
    assert int(got["first_token_ms"]) >= 25
    assert got["input_tokens"] == "0" and got["output_tokens"] == "0"


async def test_budget_turn_logs_outcome_budget(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    async def hang(kwargs):
        await asyncio.Event().wait()

    service = service_for(Script([tools("weather", "hang"), hang]))
    await service.reply("owner", ConversationRequest(text=SECRET), tmp_path, turn_budget=0.2)
    line = timing_lines(caplog)[-1]
    got = fields(line)
    assert got["outcome"] == "budget"
    names = [item.split(":")[0] for item in got["steps"].strip("[]").split(",")]
    assert names[:3] == ["model", "weather", "hang"]
    assert "secret-marker-7f3a" not in line
    # The older budget line stays: it carries the budget and the unheld time used.
    assert any(record.getMessage().startswith("Brain turn stopped:") for record in caplog.records)


async def test_error_turn_logs_outcome_error(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service = service_for(Script([RuntimeError(f"sdk said {SECRET}")]))
    with pytest.raises(ServiceError):
        await service.reply("owner", ConversationRequest(text=SECRET), tmp_path)
    got = fields(timing_lines(caplog)[-1])
    assert got["outcome"] == "error" and got["steps"].startswith("[model:")
    assert service.last_turn_timing["outcome"] == "error"
    for record in caplog.records:
        assert "secret-marker-7f3a" not in record.getMessage()


async def test_unconfigured_provider_still_logs_one_line(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    def missing():
        raise ServiceError("provider_not_configured", "Add a key.")

    service = ConversationService(dispatcher(), missing)
    with pytest.raises(ServiceError):
        await service.reply("owner", ConversationRequest(text=SECRET), tmp_path)
    got = fields(timing_lines(caplog)[-1])
    assert got["outcome"] == "error" and got["provider"] == "-" and got["steps"] == "[]"


async def test_cancelled_turn_logs_outcome_cancelled(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    started = asyncio.Event()

    async def hang(kwargs):
        started.set()
        await asyncio.Event().wait()

    service = service_for(Script([hang]))
    task = asyncio.ensure_future(
        service.reply("owner", ConversationRequest(text=SECRET), tmp_path)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fields(timing_lines(caplog)[-1])["outcome"] == "cancelled"


def test_steps_formatting():
    assert timing_steps([]) == "[]"
    assert timing_steps([
        {"kind": "model", "ms": 1200},
        {"kind": "tool", "tool": "mcp__gev__flights", "ms": 340},
        {"kind": "tool", "tool": "weird name {x}", "ms": 5},
        {"kind": "model"},
    ]) == "[model:1200,mcp__gev__flights:340,tool:5,model:?]"


def test_first_progress_is_recorded_once_for_step_zero():
    now = [10.0]
    budget = TurnBudget(60, clock=lambda: now[0])
    now[0] = 10.5
    budget.first_progress(1)
    assert budget.first_token_ms is None
    budget.first_progress(0)
    now[0] = 11.0
    budget.first_progress(0)
    assert budget.first_token_ms == 500


# --- CAD planning never searches the web ----------------------------------------------


def test_cad_planning_provider_has_web_search_off(monkeypatch):
    seen = []

    def provider(self, task, web_search=None):
        seen.append((task, web_search))
        return "provider"

    monkeypatch.setattr(TaskRouter, "provider", provider)
    assert create_text_provider() == "provider"
    assert seen == [("chat", False)]


def test_router_web_search_false_overrides_the_setting():
    router = TaskRouter(lambda: {"assistant": {"brain": "claude", "web_search": True}},
                        anthropic=lambda: "test-key", gemini=lambda: None)
    assert router.provider("chat").web_search is True
    assert router.provider("chat", web_search=False).web_search is False


# --- brain_check ---------------------------------------------------------------------


class FakeRouter:
    def __init__(self, provider, route_provider="claude", model="claude-sonnet-5-5"):
        self._provider = provider
        self.route_value = SimpleNamespace(provider=route_provider, model=model,
                                           label="Claude Sonnet 5.5")
        self.calls = []

    def route(self, task):
        return self.route_value

    def provider(self, task, web_search=None):
        self.calls.append((task, web_search))
        if isinstance(self._provider, Exception):
            raise self._provider
        return self._provider


class FakeWeather:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def lookup(self, place=None, when="today"):
        self.calls.append((place, when))
        return self.result


KL = {"place": {"name": "Kuala Lumpur", "country": "Malaysia", "lat": 3.1, "lon": 101.7},
      "now": {}, "days": [], "units": {}, "source": "Open-Meteo"}


async def test_brain_check_ok(caplog):
    caplog.set_level(logging.INFO)
    provider = Script([text("ready")], model="claude-sonnet-5-5")
    provider.effort = "medium"
    router, weather = FakeRouter(provider), FakeWeather(KL)
    result = await BrainCheck(router, weather).run("owner")
    assert result["ok"] is True
    brain = result["brain"]
    assert brain["ok"] is True and brain["provider"] == "claude"
    assert brain["model"] == "claude-sonnet-5-5" and brain["label"] == "Claude Sonnet 5.5"
    assert brain["effort"] == "medium" and isinstance(brain["ms"], int)
    assert result["weather"] == {"ok": True, "place": "Kuala Lumpur, Malaysia",
                                 "ms": result["weather"]["ms"]}
    assert router.calls == [("chat", False)] and weather.calls == [(None, "now")]
    messages, kwargs = provider.calls[0]
    assert messages[0].content == CHECK_PROMPT and kwargs.get("tools") is None
    assert provider.closed
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("brain_check ")]
    assert len(lines) == 1
    assert "provider=claude model=claude-sonnet-5-5" in lines[0] and "outcome=ok" in lines[0]
    assert "Kuala" not in lines[0] and "ready" not in lines[0]


async def test_brain_check_provider_error_keeps_the_weather_half(caplog):
    caplog.set_level(logging.INFO)
    provider = Script([RuntimeError(f"sdk {SECRET}")], name="gemini", model="gemini-3.8-flash")
    result = await BrainCheck(FakeRouter(provider, "gemini", "gemini-3.8-flash"),
                              FakeWeather(KL)).run("owner")
    assert result["ok"] is True
    assert result["brain"]["ok"] is False and result["brain"]["code"]
    assert SECRET not in result["brain"]["message"]
    assert result["brain"]["effort"] is None
    assert result["weather"]["ok"] is True
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("brain_check"))
    assert "outcome=brain_" in line
    for record in caplog.records:
        assert "secret-marker-7f3a" not in record.getMessage()


async def test_brain_check_not_configured_and_timeout(monkeypatch):
    missing = ServiceError("provider_not_configured", "Add an Anthropic key.")
    result = await BrainCheck(FakeRouter(missing), FakeWeather(KL)).run("owner")
    assert result["brain"]["code"] == "provider_not_configured"
    assert result["brain"]["message"] == "Add an Anthropic key."

    import services.brain_check as module

    monkeypatch.setattr(module, "BRAIN_TIMEOUT_S", 0.05)

    async def hang(kwargs):
        await asyncio.Event().wait()

    result = await BrainCheck(FakeRouter(Script([hang])), FakeWeather(KL)).run("owner")
    assert result["brain"]["code"] == "brain_timeout"


async def test_brain_check_need_place_and_weather_error(caplog):
    caplog.set_level(logging.INFO)
    need = FakeWeather({"need_place": True, "message": "Ask the owner."})
    result = await BrainCheck(FakeRouter(Script([text("ready")])), need).run("owner")
    assert result["weather"]["ok"] is False and result["weather"]["skipped"] is True
    assert result["weather"]["code"] == "need_place"
    assert any("outcome=ok" in r.getMessage() for r in caplog.records)
    down = FakeWeather({"error": "unavailable", "message": "The weather service couldn't be reached."})
    result = await BrainCheck(FakeRouter(Script([text("ready")])), down).run("owner")
    assert result["weather"] == {"ok": False, "code": "unavailable",
                                 "message": "The weather service couldn't be reached.",
                                 "ms": result["weather"]["ms"]}


async def test_brain_check_route_is_owner_only(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "tray": "owner", "second": "other"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "second": "renderer"})
    app.sessions.local_owner = "owner"
    provider = Script([text("ready")])
    weather = FakeWeather(KL)
    app.settings_transport.checker = BrainCheck(FakeRouter(provider), weather)
    handler = app.sio.handlers["/"]["brain_check"]
    for sid, code in (("unknown", "authentication_required"), ("tray", "authentication_required"),
                      ("second", "permission_denied")):
        result = await handler(sid, {})
        assert result["ok"] is False and result["code"] == code
    assert provider.calls == [] and weather.calls == []
    assert (await handler("client", {"x": 1}))["code"] == "invalid_arguments"
    result = await handler("client", {})
    assert result["ok"] is True and result["brain"]["ok"] and result["weather"]["ok"]
    app.settings["face_auth_enabled"] = True
    assert (await handler("client"))["code"] == "authentication_required"


def test_application_wires_a_brain_check(application_factory):
    app = application_factory()
    assert isinstance(app.settings_transport.checker, BrainCheck)
