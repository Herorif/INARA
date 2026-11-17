"""S7.4 routines (docs/ROUTINES.md): the encrypted store and its validation, the runner (order,
stops, approvals, deny, taint, one run at a time), the phrase, schedule and signal triggers,
gaming mode, the brain's routine tools and the owner-only routines_* routes.

Offline: steps are fake tools on the real dispatcher; the schedule trigger uses a fake
SchedulerAgent (and the real one's timer with a fake clock). Nothing binds a port."""

import asyncio
import datetime as dt
import logging
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ConfigDict, StrictStr

from agents.scheduler_agent import SchedulerAgent, next_routine_run
from core.event_bus import EventBus
from services import routines as routines_module
from services.conversation import ConversationRequest
from services.routines import (
    MAX_STEPS,
    RoutineList,
    RoutineRun,
    RoutineSave,
    RoutineStore,
    clean_trigger,
    normalise_phrase,
    signal_matches,
    step_line,
    trigger_summary,
)
from services.signals import signal
from services.storage import Database
from services.tools import ServiceError, ToolSpec

ZONE = ZoneInfo("Asia/Kuala_Lumpur")
PHRASE = {"type": "phrase", "phrases": ["Movie time"]}
SECRET_PHRASE = "zebra quokka night"
SECRET_ARG = "lamp-behind-the-sofa"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: StrictStr = "x"


class FakeScheduler:
    def __init__(self):
        self.timers, self.cancelled = {}, []

    def schedule_routine(self, key, *, at, repeat, callback, day=None, timezone=None):
        self.timers[key] = {"at": at, "repeat": repeat, "day": day, "callback": callback,
                            "timezone": timezone}

    def cancel_routine(self, key):
        self.timers.pop(key, None)
        self.cancelled.append(key)

    async def close_routines(self):
        self.timers.clear()


@pytest.fixture
def app(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    import server

    for name in ("routine_run", "routine_save", "routine_list"):
        app.settings["tool_permissions"][name] = server.DEFAULT_SETTINGS["tool_permissions"][name]
    app.calls = []
    return app


def fake_tool(app, name, *, fail=None, result=None, policy=False, **options):
    async def execute(args, context):
        app.calls.append((name, args.value, context))
        if fail:
            raise ServiceError(fail, "That didn't work.")
        return result if result is not None else {"ok": True}

    app.dispatcher.register(ToolSpec(name, f"Test tool {name}.", Args, execute, **options))
    app.settings["tool_permissions"][name] = policy


def ran(app):
    return [(name, value) for name, value, _ in app.calls]


def steps(*names):
    return [{"tool": name, "args": {"value": str(index)}} for index, name in enumerate(names, 1)]


async def settle(app):
    for _ in range(5):
        await app.bus.drain()
        tasks = tuple(app.routines.tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


def emitted(app, event):
    return [(call.args[1], call.kwargs.get("room")) for call in app.sio.emit.await_args_list
            if call.args[0] == event]


def approver(app, answer=True, cards=None):
    async def approve(payload):
        if cards is not None:
            cards.append(payload)
        app.dispatcher.resolve("owner", payload["id"], answer)

    return approve


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


def tool_context(app, **extra):
    return {**app.sessions.context("client").tools(), **extra}


# --- the store ------------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    tools = {}

    def add(name, visible=True):
        async def execute(args, context):
            return {}
        tools[name] = ToolSpec(name, name, Args, execute, model_visible=visible)

    for name in ("lights", "music", "routine_run", "routine_save", "routine_list"):
        add(name)
    add("hidden_alias", visible=False)
    return RoutineStore(Database(tmp_path / "private"), tools=lambda: tools)


def test_store_crud_round_trip_and_rows_are_encrypted(store):
    routine = store.save("Movie time", PHRASE, [{"tool": "lights", "args": {"value": "dim"},
                                                 "say": "Enjoy the film."}])
    assert routine["name"] == "Movie time" and routine["enabled"] is True
    assert routine["trigger"] == {"type": "phrase", "phrases": ["Movie time"]}
    assert routine["steps"] == [{"tool": "lights", "args": {"value": "dim"},
                                 "say": "Enjoy the film."}]
    assert routine["last_run_at"] is None and routine["last_outcome"] is None
    assert store.get(routine["id"]) == routine == store.find("  movie   TIME ")
    assert [item["id"] for item in store.list()] == [routine["id"]]

    updated = store.save("Movie time", {"type": "schedule", "at": "20:00", "repeat": "daily"},
                         steps("lights", "music"), routine_id=routine["id"])
    assert updated["id"] == routine["id"] and updated["updated_at"] is not None
    assert [step["tool"] for step in updated["steps"]] == ["lights", "music"]
    assert store.set_enabled(routine["id"], False)["enabled"] is False
    assert store.record(routine["id"], {"state": "ok", "steps": 2, "done": 2})
    assert store.get(routine["id"])["last_outcome"]["state"] == "ok"

    with store.database.connection() as db:
        row = db.execute("SELECT * FROM routines").fetchone()
        columns = [item["name"] for item in db.execute("PRAGMA table_info(routines)")]
    assert columns == ["id", "name", "trigger", "steps", "enabled", "created_at", "updated_at",
                       "last_run_at", "last_outcome"]
    for column in ("name", "trigger", "steps", "last_outcome"):
        assert b"Movie" not in bytes(row[column]) and b"lights" not in bytes(row[column])

    assert store.delete(routine["id"]) is True
    assert store.delete(routine["id"]) is False and store.list() == []


def test_store_replace_by_name_and_unique_names(store):
    first = store.save("Morning", PHRASE, steps("lights"))
    with pytest.raises(ServiceError) as caught:
        store.save("MORNING", {"type": "phrase", "phrases": ["good morning"]}, steps("music"))
    assert caught.value.code == "routine_conflict"
    replaced = store.save("morning", {"type": "phrase", "phrases": ["good morning"]},
                          steps("music"), replace=True)
    assert replaced["id"] == first["id"] and replaced["name"] == "morning"
    other = store.save("Night", {"type": "phrase", "phrases": ["night"]}, steps("lights"))
    with pytest.raises(ServiceError) as caught:
        store.save("Morning", PHRASE, steps("lights"), routine_id=other["id"])
    assert caught.value.code == "routine_conflict"


@pytest.mark.parametrize("bad, message", [
    (steps("nope"), "no tool called nope"),
    (steps("hidden_alias"), "no tool called hidden_alias"),
    (steps(*["lights"] * (MAX_STEPS + 1)), "at most 12 steps"),
    ([], "at least one step"),
    (steps("lights", "routine_run"), "can't run or save routines"),
    (steps("routine_save"), "can't run or save routines"),
    ([{"tool": "lights", "args": {"colour": "red"}}], "don't fit lights"),
    ([{"tool": "lights", "args": {}, "extra": 1}], "Step 1 isn't valid"),
])
def test_store_refuses_bad_steps(store, bad, message):
    with pytest.raises(ServiceError) as caught:
        store.save("Bad", PHRASE, bad)
    assert caught.value.code == "invalid_arguments" and message in str(caught.value)
    assert store.list() == []


def test_routine_list_may_be_a_step(store):
    assert store.save("Check", PHRASE, steps("routine_list"))["steps"][0]["tool"] == "routine_list"


@pytest.mark.parametrize("trigger", [
    {"type": "phrase"},
    {"type": "phrase", "phrases": ["  "]},
    {"type": "phrase", "phrases": ["!!!"]},
    {"type": "phrase", "phrases": ["ok"], "at": "07:30"},
    {"type": "schedule", "at": "7:30", "repeat": "daily"},
    {"type": "schedule", "at": "07:30"},
    {"type": "schedule", "at": "07:30", "repeat": "weekly"},
    {"type": "schedule", "at": "07:30", "repeat": "daily", "day": "mon"},
    {"type": "schedule", "cron": "* * * * *"},
    {"type": "signal"},
    {"type": "signal", "kind": "calendar.later"},
    {"type": "signal", "kind": "calendar.soon", "filter": {"a": [1]}},
    {"type": "whenever"},
])
def test_store_refuses_bad_triggers(store, trigger):
    with pytest.raises(ServiceError) as caught:
        store.save("Bad", trigger, steps("lights"))
    assert caught.value.code == "invalid_arguments"


def test_triggers_are_stored_in_one_shape():
    assert clean_trigger({"type": "phrase", "phrases": ["Movie time", "movie-time!", "Wayang"]}) \
        == {"type": "phrase", "phrases": ["Movie time", "Wayang"]}
    assert clean_trigger({"type": "schedule", "at": "07:30", "repeat": "weekly", "day": "fri"}) \
        == {"type": "schedule", "at": "07:30", "repeat": "weekly", "day": "fri"}
    assert clean_trigger({"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}}) \
        == {"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}}
    assert clean_trigger({"type": "signal", "kind": "job.finished"}) == {
        "type": "signal", "kind": "job.finished"}


def test_an_enabled_routines_phrases_are_its_own(store):
    store.save("Movie time", PHRASE, steps("lights"))
    with pytest.raises(ServiceError) as caught:
        store.save("Film", {"type": "phrase", "phrases": ["movie TIME!"]}, steps("music"))
    assert caught.value.code == "routine_conflict"
    film = store.save("Film", {"type": "phrase", "phrases": ["movie time"]}, steps("music"),
                      enabled=False)
    with pytest.raises(ServiceError):
        store.set_enabled(film["id"], True)


def test_phrases_are_normalised_and_matched_whole(store):
    assert normalise_phrase("Hey Jarvis, Movie-time please!") == "movie time"
    assert normalise_phrase("JARVIS movie time") == "movie time"
    assert normalise_phrase("Masa  wayang, tolong") == "masa wayang"
    routine = store.save("Movie time", {"type": "phrase", "phrases": ["Movie time", "Masa wayang"]},
                         steps("lights"))
    for text in ("movie time", "Movie time.", "Jarvis, movie time please", "MASA WAYANG"):
        assert store.by_phrase(text)["id"] == routine["id"]
    for text in ("is it movie time yet", "movie", "time for a movie", "", None):
        assert store.by_phrase(text) is None
    store.set_enabled(routine["id"], False)
    assert store.by_phrase("movie time") is None


def test_plain_words_for_triggers_and_steps():
    assert trigger_summary(PHRASE) == "When you say ‘Movie time’"
    assert trigger_summary({"type": "schedule", "at": "07:30", "repeat": "weekdays"}) == \
        "Weekdays at 07:30"
    assert trigger_summary({"type": "schedule", "at": "07:30", "repeat": "daily"}) == \
        "Every day at 07:30"
    assert trigger_summary({"type": "schedule", "at": "21:00", "repeat": "weekly", "day": "fri"}) \
        == "Every Friday at 21:00"
    assert trigger_summary({"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}}) \
        == "When an event starts in 10 minutes"
    assert trigger_summary({"type": "signal", "kind": "job.finished",
                            "filter": {"state": "failed"}}) == "When a job finishes (state failed)"
    assert step_line(2, {"tool": "home_control", "args": {"entity": "light.tv", "on": False},
                         "say": "Lights down."}) == \
        "2. Home control: entity light.tv, on false. Says ‘Lights down.’."
    assert step_line(1, {"tool": "mcp__gev__fly_to", "args": {}}) == "1. gev: fly to."


# --- the runner -----------------------------------------------------------------------------
async def test_runner_runs_steps_in_order_with_the_owners_context(app):
    for name in ("first", "second", "third"):
        fake_tool(app, name)
    routine = await app.routines.save("Movie time", PHRASE, steps("first", "second", "third"))
    outcome = await app.routines.run(routine, origin="manual", principal="owner")
    assert outcome["state"] == "ok" and outcome["done"] == 3 and outcome["steps"] == 3
    assert ran(app) == [("first", "1"), ("second", "2"), ("third", "3")]
    context = app.calls[0][2]
    assert context["principal"] == "owner" and context["taint"] == frozenset()
    assert context["project_path"] == app.projects.get_current_project_path().resolve()
    stored = app.routines.store.get(routine["id"])
    assert stored["last_outcome"]["state"] == "ok" and stored["last_run_at"]
    assert emitted(app, "routines_changed")[-1] == ({"id": routine["id"]}, "client")


@pytest.mark.parametrize("how", ["raises", "reports", "error"])
async def test_runner_stops_at_the_first_failure(app, how):
    fake_tool(app, "first")
    fake_tool(app, "broken", fail="device_offline" if how == "raises" else None,
              result={"raises": None, "reports": {"success": False, "message": "Plug offline."},
                      "error": {"error": "unavailable"}}[how])
    fake_tool(app, "never")
    routine = await app.routines.save("Night", PHRASE, steps("first", "broken", "never"))
    outcome = await app.routines.run(routine, origin="manual", principal="owner")
    assert ran(app) == [("first", "1"), ("broken", "2")]
    assert outcome["state"] == "failed" and outcome["step"] == 2 and outcome["done"] == 1
    assert outcome["tool"] == "broken"
    assert outcome["code"] == {"raises": "device_offline", "reports": "step_failed",
                               "error": "unavailable"}[how]
    assert app.routines.store.get(routine["id"])["last_outcome"]["state"] == "failed"


async def test_runner_respects_deny_and_declined_approvals(app):
    fake_tool(app, "first")
    fake_tool(app, "asks", policy=True)
    fake_tool(app, "never")
    routine = await app.routines.save("Night", PHRASE, steps("first", "asks", "never"))
    cards = []
    outcome = await app.routines.run(routine, origin="manual", principal="owner",
                                     request_approval=approver(app, False, cards))
    assert outcome["state"] == "declined" and outcome["step"] == 2
    assert [card["tool"] for card in cards] == ["asks"] and cards[0]["routine"] == "Night"
    assert ran(app) == [("first", "1")]

    app.calls.clear()
    outcome = await app.routines.run(routine, origin="manual", principal="owner",
                                     request_approval=approver(app, True))
    assert outcome["state"] == "ok" and ran(app) == [("first", "1"), ("asks", "2"), ("never", "3")]

    app.calls.clear()
    app.settings["tool_permissions"]["asks"] = "deny"
    outcome = await app.routines.run(routine, origin="manual", principal="owner",
                                     request_approval=approver(app, True))
    assert outcome["state"] == "failed" and outcome["code"] == "permission_denied"
    assert ran(app) == [("first", "1")]

    app.calls.clear()
    app.settings["tool_permissions"]["asks"] = True
    outcome = await app.routines.run(routine, origin="manual", principal="owner")
    assert outcome["state"] == "failed" and outcome["code"] == "approval_required"


async def test_a_tainted_run_asks_for_outward_steps(app):
    fake_tool(app, "lights", outward=True)
    fake_tool(app, "read_page", untrusted_output=True, untrusted_source="a web page")
    fake_tool(app, "plain")
    routine = await app.routines.save("Lights", PHRASE, steps("plain", "lights"))
    cards = []
    outcome = await app.routines.run(routine, origin="brain", principal="owner",
                                     request_approval=approver(app, True, cards),
                                     taint={"an email"})
    assert outcome["state"] == "ok"
    assert [card["tool"] for card in cards] == ["lights"]
    assert cards[0]["taint"] == ["an email"]

    cards.clear()
    untainted = await app.routines.save("Lights", PHRASE, steps("lights"), replace=True)
    assert (await app.routines.run(untainted, origin="manual", principal="owner"))["state"] == "ok"

    # A step whose output is untrusted taints the steps after it.
    reader = await app.routines.save("Read", {"type": "phrase", "phrases": ["read"]},
                                     steps("lights", "read_page", "lights"))
    outcome = await app.routines.run(reader, origin="manual", principal="owner",
                                     request_approval=approver(app, False, cards))
    assert outcome["state"] == "declined" and outcome["step"] == 3
    assert cards[0]["taint"] == ["a web page"]


async def test_one_run_per_routine_at_a_time(app):
    gate = asyncio.Event()

    async def slow(args, context):
        app.calls.append(("slow", args.value, context))
        await gate.wait()
        return {}

    app.dispatcher.register(ToolSpec("slow", "Slow.", Args, slow))
    app.settings["tool_permissions"]["slow"] = False
    routine = await app.routines.save("Slow", PHRASE, steps("slow"))
    task = app.routines.start(routine, origin="manual", principal="owner")
    await asyncio.sleep(0)
    with pytest.raises(ServiceError) as caught:
        app.routines.start(routine, origin="manual", principal="owner")
    assert caught.value.code == "routine_running"
    assert app.routines.fire(routine["id"], "schedule") is None
    stored = app.routines.store.get(routine["id"])
    assert stored["last_outcome"]["state"] == "running"
    gate.set()
    assert (await task)["state"] == "ok"
    assert len(app.calls) == 1
    # Free again once it finished.
    gate.set()
    assert (await app.routines.run(routine, origin="manual", principal="owner"))["state"] == "ok"


async def test_say_lines_go_to_the_owners_voice_session(app):
    fake_tool(app, "lights")
    session = Mock(closed=False, owner="owner")
    app.voice.sessions = {"s": session}
    app.voice.inject = Mock()
    routine = await app.routines.save("Lights", PHRASE, [
        {"tool": "lights", "args": {}, "say": "Lights are down."}])
    await app.routines.run(routine, origin="manual", principal="owner")
    [(target, text)] = [call.args for call in app.voice.inject.call_args_list]
    assert target is session and '"say": "Lights are down."' in text


async def test_a_run_nobody_watches_waits_for_a_window_to_approve(app):
    fake_tool(app, "asks", policy=True)
    routine = await app.routines.save("Away", PHRASE, steps("asks"))
    app.sessions.principals.pop("client")
    app.sessions.principals["tray-only"] = "owner"
    app.sessions.roles["tray-only"] = "resident"
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 3:  # the owner comes back and opens the workspace
            app.sessions.principals["client"] = "owner"
        await asyncio.sleep(0)

    app.routines.sleep = sleep

    async def answer(event, payload, room=None):
        if event == "tool_confirmation_request":
            assert room == "client"
            app.dispatcher.resolve("owner", payload["id"], True)

    app.sio.emit.side_effect = answer
    outcome = await app.routines.run(routine, origin="schedule", principal="owner",
                                     request_approval=app.routines.owner_approval("owner"))
    assert outcome["state"] == "ok" and len(waits) == 3 and ran(app) == [("asks", "1")]


async def test_an_approval_nobody_answers_expires(app):
    fake_tool(app, "asks", policy=True)
    routine = await app.routines.save("Away", PHRASE, steps("asks"))
    app.sessions.principals.pop("client")
    app.sessions.principals["tray-only"] = "owner"
    clock = [0.0]
    app.routines.monotonic = lambda: clock[0]

    async def sleep(seconds):
        clock[0] += 600
        await asyncio.sleep(0)

    app.routines.sleep = sleep
    outcome = await app.routines.run(routine, origin="signal", principal="owner",
                                     request_approval=app.routines.owner_approval("owner"))
    assert outcome["state"] == "failed" and outcome["code"] == "approval_expired"
    assert ran(app) == []


# --- the phrase trigger ---------------------------------------------------------------------
async def test_a_phrase_runs_the_routine_and_starts_no_brain_turn(app):
    fake_tool(app, "lights")
    await app.routines.save("Movie time", PHRASE, steps("lights"))
    app.conversation.provider_factory = Mock(side_effect=AssertionError("no brain turn"))
    assert getattr(app.conversation.reply, "routines_wrapped", False) is True
    request = ConversationRequest(text="Jarvis, movie time!")
    approve = approver(app)
    result = await app.conversation.reply(
        "owner", request, app.projects.get_current_project_path(), approve, origin_sid="client"
    )
    assert result.text == "Running Movie time."
    assert result.request_id == request.request_id
    assert result.conversation_id == request.conversation_id
    await settle(app)
    assert ran(app) == [("lights", "1")]
    assert app.calls[0][2]["origin_sid"] == "client"
    app.conversation.provider_factory.assert_not_called()


async def test_other_requests_and_other_peoples_turns_go_to_the_brain(app):
    fake_tool(app, "lights")
    await app.routines.save("Movie time", PHRASE, steps("lights"))
    seen = []

    async def reply(owner, request, project, request_approval=None, **options):
        seen.append((owner, request.text, options.get("channel")))
        return "brain"

    routed = app.routines.wrap_reply(reply)
    project = app.projects.get_current_project_path()
    assert await routed("owner", ConversationRequest(text="what is movie time"), project) == "brain"
    assert await routed("owner", ConversationRequest(text="movie time"), project,
                        channel="telegram") == "brain"
    assert await routed("intruder", ConversationRequest(text="movie time"), project) == "brain"
    assert len(seen) == 3
    await settle(app)
    assert ran(app) == []
    result = await routed("owner", ConversationRequest(text="movie time"), project)
    assert result.text == "Running Movie time."


async def test_a_phrase_for_a_running_routine_says_so(app):
    gate = asyncio.Event()

    async def slow(args, context):
        await gate.wait()
        return {}

    app.dispatcher.register(ToolSpec("slow", "Slow.", Args, slow))
    app.settings["tool_permissions"]["slow"] = False
    await app.routines.save("Movie time", PHRASE, steps("slow"))
    project = app.projects.get_current_project_path()
    first = await app.conversation.reply("owner", ConversationRequest(text="movie time"), project)
    second = await app.conversation.reply("owner", ConversationRequest(text="movie time"), project)
    assert first.text == "Running Movie time."
    assert second.text == "Movie time is already running."
    gate.set()
    await settle(app)


# --- the schedule trigger -------------------------------------------------------------------
async def test_schedule_triggers_go_through_the_scheduler(app):
    fake = FakeScheduler()
    app.routines.scheduler = fake
    fake_tool(app, "lights")
    morning = await app.routines.save(
        "Morning", {"type": "schedule", "at": "07:30", "repeat": "weekdays"}, steps("lights"))
    assert fake.timers == {}  # nothing is scheduled before the triggers start
    app.routines.start_triggers()
    assert fake.timers[morning["id"]]["at"] == "07:30"
    assert fake.timers[morning["id"]]["repeat"] == "weekdays"
    assert fake.timers[morning["id"]]["timezone"] == "Asia/Kuala_Lumpur"

    fake.timers[morning["id"]]["callback"]()
    await settle(app)
    assert ran(app) == [("lights", "1")]
    assert app.routines.store.get(morning["id"])["last_outcome"]["origin"] == "schedule"

    await app.routines.set_enabled(morning["id"], False)
    assert morning["id"] not in fake.timers and fake.cancelled == [morning["id"]]
    await app.routines.set_enabled(morning["id"], True)
    assert morning["id"] in fake.timers
    await app.routines.save("Morning", PHRASE, steps("lights"), routine_id=morning["id"])
    assert morning["id"] not in fake.timers
    await app.routines.save("Morning", {"type": "schedule", "at": "08:00", "repeat": "weekly",
                                        "day": "sat"}, steps("lights"), routine_id=morning["id"])
    assert fake.timers[morning["id"]]["day"] == "sat"
    await app.routines.delete(morning["id"])
    assert morning["id"] not in fake.timers
    await app.routines.close()


def kl(*args):
    return dt.datetime(*args, tzinfo=ZONE).timestamp()


def test_next_routine_run_follows_the_reminder_calendar():
    friday_morning = kl(2026, 11, 13, 8, 0)  # Friday 13 November 2026
    assert next_routine_run("07:30", "weekdays", friday_morning) == kl(2026, 11, 16, 7, 30)
    assert next_routine_run("07:30", "daily", friday_morning) == kl(2026, 11, 14, 7, 30)
    assert next_routine_run("09:00", "daily", friday_morning) == kl(2026, 11, 13, 9, 0)
    assert next_routine_run("07:30", "weekly", friday_morning, day="wed") == kl(2026, 11, 18, 7, 30)
    assert next_routine_run("08:00", "weekly", friday_morning, day="fri") == kl(2026, 11, 20, 8, 0)
    with pytest.raises(ValueError):
        next_routine_run("07:30", "weekly", friday_morning)
    with pytest.raises(ValueError):
        next_routine_run("07:30", "hourly", friday_morning)


async def test_scheduler_agent_timer_fires_repeats_and_skips_a_late_run(caplog):
    agent = SchedulerAgent(EventBus(), None)
    clock = [kl(2026, 11, 13, 7, 29)]
    step = [30.0]
    agent.now = lambda: clock[0]

    async def sleep(seconds):
        clock[0] += step[0]
        await asyncio.sleep(0)

    agent.sleep = sleep
    fired = []
    agent.schedule_routine("r1", at="07:30", repeat="daily", callback=lambda: fired.append(clock[0]))
    for _ in range(6000):
        if len(fired) == 2:
            break
        await asyncio.sleep(0)
    assert [fired[0] >= kl(2026, 11, 13, 7, 30), fired[0] < kl(2026, 11, 13, 7, 31)] == [True, True]
    assert kl(2026, 11, 14, 7, 30) <= fired[1] < kl(2026, 11, 14, 7, 31)
    assert agent.routine_keys() == {"r1"}

    # The PC slept through 07:30 on the 15th: an hour late is skipped until the next day.
    with caplog.at_level(logging.INFO):
        for _ in range(6000):
            if clock[0] >= kl(2026, 11, 15, 7, 0):
                break
            await asyncio.sleep(0)
        clock[0] = kl(2026, 11, 15, 8, 30)
        for _ in range(50):
            await asyncio.sleep(0)
    assert len(fired) == 2
    assert "missed its time" in caplog.text
    agent.cancel_routine("r1")
    await agent.close_routines()
    assert agent.routine_keys() == frozenset()


# --- the signal trigger ---------------------------------------------------------------------
def soon(minutes, at=None, **data):
    at = at or dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)
    return signal("calendar.soon", "calendar", "Design review soon", at=at,
                  dedupe_key=f"calendar.soon:e1:{minutes}", ttl=dt.timedelta(hours=1),
                  urgency=2 if minutes == 10 else 1,
                  data={"event_id": "e1", "start": "x", "minutes": minutes, **data})


def test_signal_filters_compare_plain_values():
    trigger = {"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}}
    assert signal_matches(trigger, soon(10))
    assert not signal_matches(trigger, soon(30))
    assert signal_matches({**trigger, "filter": {"minutes": "10"}}, soon(10))
    assert signal_matches({**trigger, "filter": {"urgency": 2, "source": "Calendar"}}, soon(10))
    assert not signal_matches({**trigger, "filter": {"missing": 1}}, soon(10))
    assert not signal_matches({"type": "signal", "kind": "job.finished"}, soon(10))
    assert signal_matches({"type": "signal", "kind": "calendar.soon"}, soon(30))


async def test_signal_triggers_run_matching_routines(app):
    app.signals.now = lambda: dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)
    fake_tool(app, "lights")
    fake_tool(app, "music")
    ten = await app.routines.save(
        "Heads up", {"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}},
        steps("lights"))
    await app.routines.save("Rain", {"type": "signal", "kind": "weather.rain_soon"},
                            steps("music"))
    app.routines.start_triggers()
    app.signals.publish(soon(30))
    await settle(app)
    assert ran(app) == []
    app.signals.publish(soon(10))
    await settle(app)
    assert ran(app) == [("lights", "1")]
    assert app.routines.store.get(ten["id"])["last_outcome"]["origin"] == "signal"
    await app.routines.close()
    app.signals.publish(soon(10, dedupe=True))
    await settle(app)
    assert ran(app) == [("lights", "1")]


async def test_a_signal_from_someone_else_starts_a_tainted_run(app):
    app.signals.now = lambda: dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)
    fake_tool(app, "lights", outward=True)
    await app.routines.save("Missed", {"type": "signal", "kind": "call.missed"}, steps("lights"))
    app.routines.start_triggers()
    cards = []

    async def emit(event, payload, room=None):
        if event == "tool_confirmation_request":
            cards.append(payload)
            app.dispatcher.resolve("owner", payload["id"], True)

    app.sio.emit.side_effect = emit
    app.signals.publish(signal("call.missed", "calls", "Missed call", at=app.signals.now(),
                               dedupe_key="call:1", data={"record_id": "1"}))
    await settle(app)
    assert ran(app) == [("lights", "1")]
    assert cards and cards[0]["taint"] == ["a phone caller"]
    await app.routines.close()


async def test_gaming_mode_skips_schedule_and_signal_triggers(app, caplog):
    fake = FakeScheduler()
    app.routines.scheduler = fake
    app.signals.now = lambda: dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)
    fake_tool(app, "lights")
    timed = await app.routines.save(
        "Timed", {"type": "schedule", "at": "07:30", "repeat": "daily"}, steps("lights"))
    signalled = await app.routines.save(
        "Signalled", {"type": "signal", "kind": "calendar.soon"}, steps("lights"))
    app.routines.start_triggers()
    app.resources.state = "gaming"
    with caplog.at_level(logging.INFO):
        fake.timers[timed["id"]]["callback"]()
        app.signals.publish(soon(10))
        await settle(app)
    assert ran(app) == []
    for routine in (timed, signalled):
        outcome = app.routines.store.get(routine["id"])["last_outcome"]
        assert outcome["state"] == "skipped" and outcome["reason"] == "gaming"
    assert caplog.text.count("gaming mode") == 2
    # The owner can still run one by hand.
    assert (await app.routines.run(timed, origin="manual", principal="owner"))["state"] == "ok"
    await app.routines.close()


async def test_a_run_in_progress_at_shutdown_is_recorded_as_interrupted(app):
    gate = asyncio.Event()

    async def slow(args, context):
        await gate.wait()

    app.dispatcher.register(ToolSpec("slow", "Slow.", Args, slow))
    app.settings["tool_permissions"]["slow"] = False
    routine = await app.routines.save("Slow", PHRASE, steps("slow"))
    app.routines.start(routine, origin="manual", principal="owner")
    await asyncio.sleep(0)
    await app.routines.close()
    assert app.routines.store.get(routine["id"])["last_outcome"]["state"] == "interrupted"
    # A "running" record left by a crash becomes interrupted at the next start.
    app.routines.store.record(routine["id"], {"state": "running", "steps": 1, "done": 0})
    app.routines.start_triggers()
    assert app.routines.store.get(routine["id"])["last_outcome"]["state"] == "interrupted"
    await app.routines.close()


# --- the brain's tools ----------------------------------------------------------------------
def test_tools_are_registered_with_their_ask_rules(app):
    import server

    tools = app.dispatcher.tools
    assert tools["routine_run"].arguments is RoutineRun
    assert tools["routine_save"].arguments is RoutineSave
    assert tools["routine_list"].arguments is RoutineList
    assert tools["routine_save"].always_ask is True and tools["routine_save"].review is not None
    assert tools["routine_run"].always_ask is False and tools["routine_list"].always_ask is False
    assert tools["routine_run"].long_running is True
    defaults = server.DEFAULT_SETTINGS["tool_permissions"]
    assert defaults["routine_run"] is False and defaults["routine_list"] is False
    assert {"routine_run", "routine_save", "routine_list"} <= app.settings_service.permission_names
    schema = next(item for item in app.dispatcher.schemas() if item["name"] == "routine_save")
    assert schema["parameters"]["properties"]["steps"]["maxItems"] == MAX_STEPS


async def test_routine_run_never_asks_itself_and_list_reads(app):
    fake_tool(app, "lights")
    await app.routines.save("Movie time", PHRASE, steps("lights"))
    result = await app.dispatcher.dispatch(
        "owner", "routine_run", {"name": "movie TIME"}, tool_context(app), request_approval=None)
    assert result["state"] == "ok" and result["steps_done"] == 1
    assert result["outcome"] == "Done: the step ran."
    listed = await app.dispatcher.dispatch("owner", "routine_list", {}, tool_context(app))
    [item] = listed["routines"]
    assert item["name"] == "Movie time" and item["trigger"] == "When you say ‘Movie time’"
    assert item["steps"] == 1 and item["enabled"] is True
    assert item["last_outcome"] == "Done: the step ran."
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch("owner", "routine_run", {"name": "nope"}, tool_context(app))
    assert caught.value.code == "routine_not_found"


async def test_routine_run_passes_the_turns_taint_and_approvals_to_its_steps(app):
    fake_tool(app, "lights", outward=True)
    await app.routines.save("Lights", PHRASE, steps("lights"))
    cards = []
    result = await app.dispatcher.dispatch(
        "owner", "routine_run", {"name": "Lights"},
        tool_context(app, taint=frozenset({"an email"})), approver(app, False, cards))
    assert result["state"] == "declined" and [card["tool"] for card in cards] == ["lights"]
    assert ran(app) == []


async def test_routine_save_always_asks_and_reviews_in_plain_words(app):
    fake_tool(app, "lights")
    cards = []
    args = {"name": "Movie time", "trigger": {"type": "phrase", "phrases": ["movie time"]},
            "steps": [{"tool": "lights", "args": {"value": "dim"}, "say": "Enjoy."}]}
    app.settings["tool_permissions"]["routine_save"] = False  # always_ask wins anyway
    result = await app.dispatcher.dispatch("owner", "routine_save", args, tool_context(app),
                                           approver(app, True, cards))
    assert result == {"saved": True, "name": "Movie time",
                      "trigger": "When you say ‘movie time’", "steps": 1, "enabled": True}
    [card] = cards
    assert card["tool"] == "routine_save"
    assert card["args"]["trigger"] == "When you say ‘movie time’"
    assert card["args"]["steps"] == ["1. Lights: value dim. Says ‘Enjoy.’."]
    assert card["args"]["replaces"] is None
    assert app.routines.store.find("movie time")["steps"][0]["say"] == "Enjoy."

    cards.clear()
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch("owner", "routine_save", args, tool_context(app),
                                      approver(app, False, cards))
    assert caught.value.code == "permission_denied" and cards[0]["args"]["replaces"] == "Movie time"

    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch(
            "owner", "routine_save", {**args, "steps": [{"tool": "routine_run", "args": {}}]},
            tool_context(app), approver(app, True, cards))
    assert caught.value.code == "invalid_arguments" and len(cards) == 1  # refused before a card


async def test_routine_tools_are_owner_only(app):
    for name, args in (("routine_run", {"name": "x"}), ("routine_list", {})):
        with pytest.raises(ServiceError) as caught:
            await app.dispatcher.dispatch("intruder", name, args, {"principal": "intruder"})
        assert caught.value.code == "permission_denied"


# --- owner-only routes ----------------------------------------------------------------------
ROUTES = ("routines_list", "routines_tools", "routines_save", "routines_delete",
          "routines_toggle", "routines_run")


@pytest.mark.parametrize("name", ROUTES)
@pytest.mark.parametrize("sid", ["other", "tray", "unknown", "locked"])
async def test_routes_are_owner_renderer_only(app, name, sid):
    fake_tool(app, "lights")
    routine = await app.routines.save("Movie time", PHRASE, steps("lights"))
    payload = {
        "routines_list": {}, "routines_tools": {},
        "routines_save": {"name": "Other", "trigger": PHRASE, "steps": steps("lights")},
        "routines_delete": {"id": routine["id"]},
        "routines_toggle": {"id": routine["id"], "enabled": False},
        "routines_run": {"id": routine["id"]},
    }[name]
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    reply = await rpc(app, name, payload, sid=sid)
    assert reply["ok"] is False
    assert reply["code"] in ("authentication_required", "permission_denied")
    await settle(app)
    assert [item["id"] for item in app.routines.store.list()] == [routine["id"]]
    assert app.routines.store.get(routine["id"])["enabled"] is True and ran(app) == []


async def test_routes_list_tools_save_toggle_run_delete(app):
    fake_tool(app, "lights", policy=True)
    tools = await rpc(app, "routines_tools")
    names = [item["name"] for item in tools["tools"]]
    assert tools["ok"] and "lights" in names and "routine_list" in names
    assert "routine_run" not in names and "routine_save" not in names
    assert names == sorted(names)
    lights = next(item for item in tools["tools"] if item["name"] == "lights")
    assert lights["parameters"]["properties"]["value"]["type"] == "string"

    saved = await rpc(app, "routines_save", {"name": "Movie time", "trigger": PHRASE,
                                             "steps": steps("lights")})
    assert saved["ok"] and saved["routine"]["name"] == "Movie time"
    rid = saved["routine"]["id"]
    clash = await rpc(app, "routines_save", {"name": "movie time", "trigger": PHRASE,
                                             "steps": steps("lights")})
    assert clash == {"ok": False, "code": "routine_conflict",
                     "message": "There's already a routine called movie time."}
    bad = await rpc(app, "routines_save", {"name": "X", "trigger": PHRASE,
                                           "steps": steps("nope")})
    assert bad["ok"] is False and bad["code"] == "invalid_arguments" and "nope" in bad["message"]
    edited = await rpc(app, "routines_save", {"id": rid, "name": "Movie night",
                                              "trigger": PHRASE, "steps": steps("lights")})
    assert edited["routine"]["id"] == rid and edited["routine"]["name"] == "Movie night"

    listed = await rpc(app, "routines_list")
    assert listed["ok"] and [item["id"] for item in listed["routines"]] == [rid]
    toggled = await rpc(app, "routines_toggle", {"id": rid, "enabled": False})
    assert toggled["routine"]["enabled"] is False

    async def emit(event, payload, room=None):
        if event == "tool_confirmation_request":
            assert room == "client"
            app.dispatcher.resolve("owner", payload["id"], True)

    app.sio.emit.side_effect = emit
    started = await rpc(app, "routines_run", {"id": rid})
    assert started == {"ok": True, "started": rid}
    await settle(app)
    assert ran(app) == [("lights", "1")]
    outcome = (await rpc(app, "routines_list"))["routines"][0]["last_outcome"]
    assert outcome["state"] == "ok" and outcome["origin"] == "manual"

    assert await rpc(app, "routines_delete", {"id": rid}) == {"ok": True, "deleted": rid}
    gone = await rpc(app, "routines_delete", {"id": rid})
    assert gone["ok"] is False and gone["code"] == "routine_not_found"
    assert (await rpc(app, "routines_run", {"id": rid}))["code"] == "routine_not_found"


@pytest.mark.parametrize("name, payload", [
    ("routines_save", {"name": "X", "trigger": PHRASE, "steps": []}),
    ("routines_save", {"name": "X", "trigger": PHRASE, "steps": steps("a"), "other": 1}),
    ("routines_delete", {"id": "not-a-uuid"}),
    ("routines_toggle", {"id": "00000000-0000-4000-8000-000000000000", "enabled": "yes"}),
    ("routines_list", {"extra": True}),
])
async def test_routes_validate_their_arguments(app, name, payload):
    reply = await rpc(app, name, payload)
    assert reply == {"ok": False, "code": "invalid_arguments",
                     "message": "That routine change isn't valid."}


async def test_an_unavailable_store_answers_plainly(app):
    app.routines.store = None
    reply = await rpc(app, "routines_list")
    assert reply["ok"] is False and reply["code"] == "routines_unavailable"
    assert app.routines.phrase_match("owner", ConversationRequest(text="movie time")) is None
    assert app.routines.fire("00000000-0000-4000-8000-000000000000", "schedule") is None
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch("owner", "routine_list", {}, tool_context(app))
    assert caught.value.code == "routines_unavailable"


async def test_nothing_private_is_logged(app, caplog):
    fake_tool(app, "lights", fail="device_offline")
    with caplog.at_level(logging.DEBUG):
        routine = await app.routines.save(
            "Zebra night", {"type": "phrase", "phrases": [SECRET_PHRASE]},
            [{"tool": "lights", "args": {"value": SECRET_ARG}, "say": "Quokka line"}])
        await app.conversation.reply("owner", ConversationRequest(text=SECRET_PHRASE),
                                     app.projects.get_current_project_path())
        await settle(app)
        await rpc(app, "routines_list")
    assert app.routines.store.get(routine["id"])["last_outcome"]["state"] == "failed"
    for secret in (SECRET_PHRASE, SECRET_ARG, "Zebra night", "Quokka"):
        assert secret not in caplog.text
    assert routines_module.NOT_STEPS == {"routine_run", "routine_save"}
