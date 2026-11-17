"""S7.3 heartbeat (services/heartbeat.py, docs/PROACTIVE.md "Heartbeat"). Offline: a fake
clock, a fake provider (or ClaudeProvider over a fake Anthropic client), the real proactive
engine with the S7.2 test fakes, and HEARTBEAT.md in a temporary data folder."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm.base import LLMResponse
from llm.claude import ClaudeProvider
from services.heartbeat import (
    DEFAULT_TEXT,
    FEATURE,
    MAX_ACTIONS,
    OUTPUT_SCHEMA,
    SYSTEM,
    TEXT_MAX,
    Heartbeat,
    parse_actions,
)
from services.signals import SignalHub
from services.tools import ServiceError
from services.usage import UsageService

from tests.test_memory_extractor import FakeClient, message
from tests.test_proactive import NIGHT, OWNER, SECRET, emitted, focus, item, make, settle

INSTRUCTIONS = "Never tell me about the dentist."


class FakeProvider:
    """A structured-output provider: ``respond(payload) -> JSON text``."""

    def __init__(self, respond=None, name="claude"):
        self.name = name
        self.respond = respond or (lambda payload: actions())
        self.calls = []

    def __call__(self):
        return self

    async def generate(self, messages, **kwargs):
        payload = json.loads(messages[0].content)
        self.calls.append({"kwargs": kwargs, "payload": payload})
        result = self.respond(payload)
        if isinstance(result, BaseException):
            raise result
        return LLMResponse(text=result)

    async def close(self):
        pass


def actions(*items):
    return json.dumps({"actions": list(items)})


def setup(tmp_path, provider=None, **options):
    app, engine, clock, state = make(tmp_path, **options)
    app.signals = SignalHub(app, now=clock)
    app.project = tmp_path
    app.usage = UsageService(app)
    provider = provider or FakeProvider()
    beat = Heartbeat(app, provider_factory=provider, now=clock)
    app.heartbeat = beat
    return app, engine, clock, beat, provider


def publish(app, clock, **fields):
    sig = item(clock, **fields)
    assert app.signals.publish(sig)
    return sig


# --- when it calls -----------------------------------------------------------------------------


async def test_no_pending_signal_means_no_model_call(tmp_path):
    app, _engine, clock, beat, provider = setup(tmp_path)
    assert await beat.check() == "nothing"
    assert provider.calls == []
    assert beat.last_run == clock() and beat.last_actions == []


async def test_signals_the_engine_delivered_held_or_muted_need_no_judgment(tmp_path):
    app, engine, clock, beat, provider = setup(tmp_path)
    focus(engine)
    told = publish(app, clock, urgency=2, key="told")
    assert await engine.consider(told) == "card"
    held = publish(app, clock, urgency=2, key="held")
    app.resources.state = "gaming"
    assert await engine.consider(held) == "held"
    app.resources.state = "chat"
    engine.mute("call.missed", "calls")
    publish(app, clock, kind="call.missed", source="calls", key="muted")
    assert engine.delivered("told") and engine.delivered("held")
    assert await beat.check() == "nothing"
    assert provider.calls == []


async def test_each_signal_is_judged_once(tmp_path):
    app, _engine, clock, beat, provider = setup(tmp_path, FakeProvider(lambda p: actions()))
    publish(app, clock, urgency=0, key="fyi")
    assert await beat.check() == "done"
    assert await beat.check() == "nothing"
    assert len(provider.calls) == 1


async def test_the_exact_structured_output_request_and_its_metering(tmp_path):
    client = FakeClient([message(actions({"action": "none", "signal": "fyi"}))])
    provider = lambda: ClaudeProvider(api_key="sk-ant-offline",  # noqa: E731
                                      model="claude-haiku-5-5", effort="low", client=client)
    app, _engine, clock, beat, _ = setup(tmp_path, provider)
    beat.save_text(INSTRUCTIONS)
    clock.advance(minutes=1)
    publish(app, clock, urgency=0, key="fyi", body="x" * 400)
    clock.advance(minutes=7)
    assert await beat.check() == "done"
    [request] = client.requests
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"] == {
        "effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    assert request["system"] == SYSTEM
    assert SYSTEM[0]["cache_control"] == {"type": "ephemeral"}
    assert request["max_tokens"] == 1024
    assert "tools" not in request
    [user] = request["messages"]
    payload = json.loads(user["content"])
    assert set(payload) == {"now", "standing_instructions", "routines", "signals"}
    assert payload["standing_instructions"] == INSTRUCTIONS
    assert payload["now"] == "Sunday 2026-11-15 14:08"
    assert payload["routines"] == []
    assert payload["signals"] == [{"signal": "fyi", "kind": "calendar.soon", "title": SECRET,
                                   "body": "x" * 200, "urgency": 0, "age_minutes": 7}]
    text = json.dumps(OUTPUT_SCHEMA)
    for keyword in ("maxLength", "minLength", "maximum", "minimum", "maxItems"):
        assert keyword not in text
    database = app.database
    with database.connection() as db:
        [receipt] = database.all(db, app.usage.call_kind(OWNER, app.usage.periods()[1]))
    assert receipt["feature"] == FEATURE == "heartbeat"
    assert receipt["model"] == "claude-haiku-5-5"


async def test_gaming_mode_and_quiet_hours_skip(tmp_path):
    app, _engine, clock, beat, provider = setup(tmp_path)
    publish(app, clock, urgency=1, key="a")
    app.resources.state = "gaming"
    assert await beat.check() == "gaming"
    app.resources.state = "chat"
    clock.value = NIGHT
    publish(app, clock, urgency=1, key="b")
    assert await beat.check() == "quiet_hours"
    assert provider.calls == [] and beat.last_run is None
    publish(app, clock, urgency=3, key="urgent")  # urgency 3 breaks through quiet hours
    assert await beat.check() == "done"
    assert len(provider.calls) == 1


async def test_without_structured_output_nothing_is_asked(tmp_path):
    app, _engine, clock, beat, provider = setup(tmp_path, FakeProvider(name="gemini"))
    publish(app, clock, urgency=0, key="fyi")
    assert await beat.check() == "no_structured_output"
    assert provider.calls == []


async def test_a_failure_is_tried_once_more_then_left(tmp_path):
    provider = FakeProvider(lambda p: RuntimeError("boom"))
    app, _engine, clock, beat, _ = setup(tmp_path, provider)
    publish(app, clock, urgency=0, key="fyi")
    assert await beat.check() == "failed"
    assert await beat.check() == "failed"
    assert await beat.check() == "nothing"
    assert len(provider.calls) == 2


# --- applying ------------------------------------------------------------------------------------


async def test_notify_goes_through_the_engine_past_the_score_but_not_the_rules(tmp_path):
    provider = FakeProvider(lambda p: actions({"action": "notify", "signal": "fyi", "text": "Hi"}))
    app, engine, clock, beat, _ = setup(tmp_path, provider)
    focus(engine)
    publish(app, clock, urgency=0, key="fyi")  # urgency 0: the engine alone never tells it
    await beat.check()
    await settle()
    [card] = emitted(app, "proactive_card")
    assert card["card"]["title"] == SECRET  # notify keeps the signal's own card
    assert beat.last_actions == [{"action": "notify", "signal": "fyi", "kind": "calendar.soon",
                                  "outcome": "card"}]
    assert engine.recent()[0]["channel"] == "card" and engine.delivered("fyi")


async def test_notify_respects_mutes_and_holds_while_away(tmp_path):
    provider = FakeProvider(lambda p: actions(*({"action": "notify", "signal": s["signal"]}
                                                 for s in p["signals"])))
    app, engine, clock, beat, _ = setup(tmp_path, provider, idle=9999.0)
    publish(app, clock, urgency=0, key="fyi")
    await beat.check()
    assert beat.last_actions[0]["outcome"] == "held"  # away: the digest, as the engine rules


async def test_speak_uses_the_sentence_and_the_spoken_rate_limit(tmp_path):
    provider = FakeProvider(lambda p: actions(*({"action": "speak", "signal": s["signal"],
                                                 "text": "Your parcel  arrived."}
                                                for s in p["signals"])))
    app, engine, clock, beat, _ = setup(tmp_path, provider)
    focus(engine)
    app.voice.sessions = {"v": SimpleNamespace(closed=False, owner=OWNER)}
    publish(app, clock, urgency=0, key="one")
    await beat.check()
    [(_session, turn)] = app.voice.injected
    assert "Your parcel arrived." in turn and SECRET not in turn
    clock.advance(minutes=2)
    publish(app, clock, urgency=0, key="two")
    await beat.check()
    assert len(app.voice.injected) == 1  # one spoken interruption per 10 min on Balanced
    assert beat.last_actions[0]["outcome"] == "card"


async def test_none_acknowledges_the_signal(tmp_path):
    provider = FakeProvider(lambda p: actions({"action": "none", "signal": "fyi"}))
    app, _engine, clock, beat, _ = setup(tmp_path, provider)
    publish(app, clock, urgency=0, key="fyi")
    await beat.check()
    assert app.signals.pending() == []
    assert beat.last_actions[0]["outcome"] == "acknowledged"


async def test_run_routine_without_the_routines_service_becomes_notify(tmp_path):
    provider = FakeProvider(lambda p: actions(
        {"action": "run_routine", "signal": "fyi", "routine": "Leave home"}))
    app, engine, clock, beat, _ = setup(tmp_path, provider)
    focus(engine)
    publish(app, clock, urgency=0, key="fyi")
    await beat.check()
    [entry] = beat.last_actions
    assert entry["action"] == "notify" and entry["outcome"] == "card"
    assert entry["note"]


class Routines:
    def __init__(self, routines):
        self.fired = []
        self.store = SimpleNamespace(
            list=lambda: routines,
            find=lambda name: next((r for r in routines if r["name"].lower() == name.lower()),
                                   None),
        )

    def fire(self, routine_id, origin, item=None):
        self.fired.append((routine_id, origin, item.dedupe_key))
        return object()


async def test_run_routine_fires_through_the_routines_service(tmp_path):
    provider = FakeProvider(lambda p: actions(
        {"action": "run_routine", "signal": "fyi", "routine": "leave home"}))
    app, _engine, clock, beat, _ = setup(tmp_path, provider)
    app.routines = Routines([{"id": "r1", "name": "Leave home", "enabled": True},
                             {"id": "r2", "name": "Off", "enabled": False}])
    publish(app, clock, urgency=0, key="fyi")
    await beat.check()
    assert provider.calls[0]["payload"]["routines"] == ["Leave home"]
    assert app.routines.fired == [("r1", "heartbeat", "fyi")]
    assert beat.last_actions[0]["outcome"] == "started"


def test_parse_actions_bounds_and_validates():
    keys = {f"k{n}" for n in range(9)}
    raw = actions(
        {"action": "shout", "signal": "k0"},
        {"action": "none", "signal": "unknown"},
        {"action": "run_routine", "signal": "k1"},
        {"action": "none", "signal": "k2", "extra": 1},
        *({"action": "none", "signal": f"k{n}"} for n in range(3, 9)),
        {"action": "none", "signal": "k3"},
    )
    valid, invalid = parse_actions(raw, keys)
    assert len(valid) == MAX_ACTIONS and [a.signal for a in valid] == ["k3", "k4", "k5", "k6", "k7"]
    assert invalid == 6
    with pytest.raises(ValueError):
        parse_actions("[]", keys)


async def test_logs_never_carry_signal_text_or_instructions(tmp_path, caplog):
    provider = FakeProvider(lambda p: actions({"action": "notify", "signal": "fyi"}))
    app, engine, clock, beat, _ = setup(tmp_path, provider)
    focus(engine)
    beat.save_text(INSTRUCTIONS)
    publish(app, clock, urgency=0, key="fyi")
    with caplog.at_level(logging.DEBUG):
        await beat.check()
    assert SECRET not in caplog.text and INSTRUCTIONS not in caplog.text


# --- HEARTBEAT.md ---------------------------------------------------------------------------------


def test_heartbeat_md_default_save_and_length(tmp_path):
    app, _engine, _clock, beat, _ = setup(tmp_path)
    path = Path(app.database.directory) / "HEARTBEAT.md"
    assert not path.exists()
    assert beat.status()["text"] == DEFAULT_TEXT
    assert path.read_text(encoding="utf-8") == DEFAULT_TEXT
    assert DEFAULT_TEXT.startswith("# Standing instructions\n- Tell me about VIP calls")
    assert beat.save_text("a\r\nb") == "a\nb"
    assert path.read_text(encoding="utf-8") == "a\nb"
    assert beat.save_text("x" * TEXT_MAX) == "x" * TEXT_MAX
    for bad in ("x" * (TEXT_MAX + 1), "bell\x07", 3):
        with pytest.raises(ServiceError) as caught:
            beat.save_text(bad)
        assert caught.value.code == "invalid_arguments"
    beat.save_text("   ")
    assert beat.instructions() == DEFAULT_TEXT  # empty uses the defaults
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


# --- routes ---------------------------------------------------------------------------------------


async def test_routes_are_owner_only(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "second": "other", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "second": "renderer", "tray": "resident"})
    handlers = app.sio.handlers["/"]
    got = await handlers["heartbeat_get"]("client", {})
    assert got == {"ok": True, "text": DEFAULT_TEXT, "last_run": None, "last_actions": []}
    saved = await handlers["heartbeat_save"]("client", {"text": INSTRUCTIONS})
    assert saved == {"ok": True, "text": INSTRUCTIONS}
    assert (await handlers["heartbeat_get"]("client", None))["text"] == INSTRUCTIONS
    too_long = await handlers["heartbeat_save"]("client", {"text": "x" * (TEXT_MAX + 1)})
    assert too_long["code"] == "invalid_arguments"
    assert (await handlers["heartbeat_save"]("client", {"text": 3}))["code"] == "invalid_arguments"
    assert (await handlers["heartbeat_get"]("client", {"x": 1}))["code"] == "invalid_arguments"
    assert (await handlers["heartbeat_get"]("second", {}))["code"] == "permission_denied"
    assert (await handlers["heartbeat_save"]("tray", {"text": "x"}))["code"] == \
        "authentication_required"
    app.settings["face_auth_enabled"] = True
    assert (await handlers["heartbeat_get"]("client", {}))["code"] == "authentication_required"


def test_routes_are_in_the_route_policy_matrix():
    matrix = json.loads((Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json")
                        .read_text(encoding="utf-8"))
    for name in ("heartbeat_get", "heartbeat_save"):
        assert matrix["socket_routes"][name]["status"] == "implemented"


async def test_the_loop_checks_every_interval_and_closes(tmp_path):
    app, _engine, clock, beat, _ = setup(tmp_path)
    slept = []

    class Stop(Exception):
        pass

    async def sleep(seconds):
        slept.append(seconds)
        if len(slept) > 2:
            raise Stop

    beat.sleep = sleep
    with pytest.raises(Stop):
        await beat.run()
    assert slept[:2] == [1800.0, 1800.0] and beat.last_run == clock()
