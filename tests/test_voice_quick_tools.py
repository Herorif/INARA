"""Quick answers by voice (S1.2): fakes only; no network, microphone, speaker or provider."""

import asyncio
from contextlib import asynccontextmanager
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
from zoneinfo import ZoneInfo

import pytest
from google.genai import types

import services.calendar as calendar_module
import services.voice_quick as voice_quick
from services.live_config import (
    QUICK_AGENDA,
    QUICK_HOME,
    QUICK_RULE,
    QUICK_WEATHER,
    clock_line,
    declarations,
    make_live_config,
)

KL = ZoneInfo("Asia/Kuala_Lumpur")
NOW = dt.datetime(2026, 11, 14, 9, 12, tzinfo=KL)  # a Saturday
WEATHER = {
    "place": {"name": "Kuala Lumpur", "country": "Malaysia", "lat": 3.1, "lon": 101.7},
    "when": "today",
    "now": {"temp": 31.2, "feels_like": 36.1, "humidity": 70, "precipitation": 0.0,
            "condition": "light rain", "wind_kmh": 9.0},
    "days": [{"date": "2026-11-14", "condition": "light rain", "min": 25, "max": 33,
              "rain_chance": 70}],
    "units": {"temperature": "°C", "wind": "km/h", "precipitation": "mm", "rain_chance": "%"},
    "source": "Open-Meteo",
}


class FakeLive:
    def __init__(self, model, config):
        self.model, self.config = model, config
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

    def call(self, name, args=None, identifier="q-1"):
        self.inbox.put_nowait(
            types.LiveServerMessage(
                tool_call=types.LiveServerToolCall(
                    function_calls=[types.FunctionCall(id=identifier, name=name, args=args or {})]
                )
            )
        )


class FakeConnector:
    def __init__(self):
        self.connections = []

    @asynccontextmanager
    async def __call__(self, model, config):
        live = FakeLive(model, config)
        self.connections.append(live)
        yield live


class FakeWeather:
    def __init__(self, result=None, hang=False):
        self.result, self.hang, self.calls = result, hang, []

    async def lookup(self, place=None, when="today"):
        self.calls.append((place, when))
        if self.hang:
            await asyncio.Event().wait()
        return dict(self.result)


class FakeCalendar:
    connected = True

    def __init__(self, events):
        self.events = events

    def switches(self):
        return {"read_events": True, "share_free_busy": False, "add_events": False}

    async def today_events(self):
        return {"time_zone": "Asia/Kuala_Lumpur", "events": self.events, "truncated": False}


async def until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(0.005)


@pytest.fixture
def voice(application_factory, monkeypatch):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner"})
    app.sessions.roles.update({"client": "renderer"})
    # The shipped defaults (server.py): these reads never ask.
    app.settings["tool_permissions"].update(
        {"weather": False, "calendar_read": False, "home_devices": False}
    )
    connector = FakeConnector()
    app.voice.connector = connector
    app.voice.preflight = lambda: None
    app.voice.retry_delay = 0
    app.voice.tick = 0.01
    app.conversation.reply = AsyncMock(side_effect=AssertionError("no brain turn"))
    app.conversation.append_turns = AsyncMock(side_effect=AssertionError("no history entry"))
    monkeypatch.setattr(calendar_module, "local_now", lambda: NOW)
    return app, connector


async def start(app, connector, mode="push_to_talk"):
    count = len(connector.connections)
    ack = await app.sio.handlers["/"]["voice_start"](
        "client", {"mode": mode, "conversation_id": str(uuid.uuid4())}
    )
    assert ack["ok"], ack
    await until(lambda: len(connector.connections) > count)
    live = connector.connections[-1]
    await until(lambda: app.voice.sessions["owner"].live is live)
    return live


async def ask(live, name, args=None):
    live.call(name, args)
    await until(lambda: live.tool_responses)
    (response,) = live.tool_responses[-1]
    assert response.name == name
    return response.response


# --- declarations and the system text ---------------------------------------------------------


def test_quick_declarations_sit_beside_ask_brain_and_home_needs_home_assistant():
    for item in (QUICK_WEATHER, QUICK_AGENDA, QUICK_HOME):
        assert item["description"].endswith(QUICK_RULE)
        assert "Do not call ask_brain for this." in item["description"]
    assert QUICK_WEATHER["parameters"]["properties"]["when"]["enum"] == [
        "now", "today", "tomorrow", "week",
    ]
    assert "required" not in QUICK_WEATHER["parameters"]
    assert [item["name"] for item in declarations("push_to_talk")] == [
        "ask_brain", "quick_weather", "quick_agenda",
    ]
    assert [item["name"] for item in declarations("conversation", home=True)] == [
        "ask_brain", "quick_weather", "quick_agenda", "quick_home", "end_conversation",
    ]
    names = {item.name for item in make_live_config({}, home=True).tools[0].function_declarations}
    assert "quick_home" in names
    names = {item.name for item in make_live_config({}).tools[0].function_declarations}
    assert "quick_home" not in names
    ask_brain = declarations("push_to_talk")[0]["description"]
    assert "quick_weather, quick_agenda and quick_home" in ask_brain


def test_live_system_text_carries_the_local_date_time_and_zone(monkeypatch):
    import services.live_config as live_config

    line = "Saturday 14 November 2026, 09:12, Asia/Kuala_Lumpur (UTC+08:00)"
    assert line in clock_line(NOW)
    assert line in make_live_config({}, now=NOW).system_instruction
    # Without ``now`` the session start reads this PC's clock.
    monkeypatch.setattr(live_config, "local_now", lambda: NOW)
    text = make_live_config({}, mode="conversation").system_instruction
    assert line in text and text.index("JARVIS") < text.index(line)
    fixed = dt.datetime(2026, 11, 14, 9, 12, tzinfo=dt.timezone(dt.timedelta(hours=-3, minutes=-30)))
    assert "Saturday 14 November 2026, 09:12, UTC-03:30." in clock_line(fixed)


@pytest.mark.asyncio
async def test_voice_declares_quick_home_only_while_home_assistant_is_connected(voice):
    app, connector = voice
    live = await start(app, connector)
    assert "quick_home" not in {item.name for item in live.config.tools[0].function_declarations}
    assert "At the start of this voice session it is " in live.config.system_instruction
    await app.voice.stop_sid()
    app.home = SimpleNamespace(connected=True)
    live = await start(app, connector)
    assert "quick_home" in {item.name for item in live.config.tools[0].function_declarations}
    await app.voice.stop_sid()


# --- quick_weather ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_weather_answers_without_a_brain_turn(voice):
    app, connector = voice
    app.weather = FakeWeather(WEATHER)
    live = await start(app, connector)
    response = await ask(live, "quick_weather", {"place": "  Kuala   Lumpur ", "when": "today"})
    assert response["answer"] == (
        "Kuala Lumpur: 31°C, feels like 36, light rain; today 25 to 33 with a 70% chance of rain."
    )
    assert response["data"]["place"] == "Kuala Lumpur, Malaysia"
    assert response["data"]["now"]["temp"] == 31.2 and response["data"]["days"][0]["max"] == 33
    assert app.weather.calls == [("Kuala Lumpur", "today")]
    app.conversation.reply.assert_not_called()
    app.conversation.append_turns.assert_not_called()
    session = app.voice.sessions["owner"]
    assert not session.brain and not session.brain_turn and not session.quick
    # A bad ``when`` falls back to today; no place means the home town.
    live.tool_responses.clear()
    await ask(live, "quick_weather", {"when": "next century"})
    assert app.weather.calls[-1] == (None, "today")
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_quick_weather_without_a_home_town_asks_for_one_and_saves_nothing(voice):
    app, connector = voice
    app.weather = FakeWeather({"need_place": True, "message": "Ask the owner..."})
    live = await start(app, connector)
    response = await ask(live, "quick_weather")
    assert response["need_place"] is True
    assert response["answer"] == (
        "I don't know your home town yet. Which town should I use for the weather?"
    )
    assert "quick_weather again with that place" in response["message"]
    assert app.settings.get("assistant", {}).get("home_place") is None
    app.conversation.reply.assert_not_called()
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_a_hanging_service_is_cut_off_and_answers_unavailable(voice, monkeypatch):
    app, connector = voice
    monkeypatch.setattr(voice_quick, "QUICK_SECONDS", 0.05)
    app.weather = FakeWeather(hang=True)
    live = await start(app, connector)
    response = await ask(live, "quick_weather")
    assert response == {"error": "unavailable", "message": "That took too long to answer."}
    await until(lambda: not app.voice.sessions["owner"].quick)
    app.conversation.reply.assert_not_called()
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_failures_and_gates_answer_plainly(voice):
    app, connector = voice
    app.weather = FakeWeather({"error": "unavailable", "message": "The weather service couldn't be reached."})
    live = await start(app, connector)
    assert await ask(live, "quick_weather") == {
        "error": "unavailable", "message": "The weather service couldn't be reached.",
    }
    live.tool_responses.clear()
    app.settings["tool_permissions"]["weather"] = "deny"
    assert (await ask(live, "quick_weather"))["error"] == "permission_denied"
    live.tool_responses.clear()
    app.settings["tool_permissions"]["weather"] = True  # asks the owner: the brain's job
    response = await ask(live, "quick_weather")
    assert response["error"] == "approval_required" and "ask_brain" in response["message"]
    live.tool_responses.clear()
    assert (await ask(live, "quick_home")) == {
        "error": "unavailable", "message": "Home Assistant isn't connected.",
    }
    app.conversation.reply.assert_not_called()
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_quick_tools_respect_the_face_lock(voice):
    app, connector = voice
    app.weather = FakeWeather(WEATHER)
    app.voice.tick = 60  # the watchdog would end the locked session first
    live = await start(app, connector)
    session = app.voice.sessions["owner"]
    app.voice.authorize = lambda _session: (_ for _ in ()).throw(
        voice_quick.ServiceError("authentication_required", "Authentication is required.")
    )
    response = await ask(live, "quick_weather")
    assert response["error"] == "authentication_required"
    assert app.weather.calls == []
    await app.voice.end(session)


# --- quick_agenda -----------------------------------------------------------------------------


def add_reminder(app, task, at):
    app.reminders.add_reminder(task, at.timestamp())


@pytest.mark.asyncio
async def test_quick_agenda_without_a_calendar_still_answers_reminders(voice):
    app, connector = voice
    add_reminder(app, "Call the bank", NOW.replace(hour=15, minute=0))
    add_reminder(app, "Next week", NOW + dt.timedelta(days=7))
    assert not app.calendar.connected
    live = await start(app, connector)
    response = await ask(live, "quick_agenda")
    assert response["answer"] == "Google Calendar isn't connected. One reminder: Call the bank."
    assert response["data"]["calendar"] == "not_connected"
    assert response["data"]["reminders"] == [{"time": "15:00", "text": "Call the bank"}]
    assert response["data"]["events"] == []
    app.conversation.reply.assert_not_called()
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_quick_agenda_reads_today_from_the_calendar(voice):
    app, connector = voice
    app.calendar = FakeCalendar([
        {"title": "Standup", "date": "2026-11-14", "all_day": False, "start": "08:00", "end": "08:30"},
        {"title": "Dentist", "date": "2026-11-14", "all_day": False, "start": "10:00", "end": "11:00"},
    ])
    live = await start(app, connector)
    response = await ask(live, "quick_agenda")
    # The standup is over; the spoken line names what's left.
    assert response["answer"].startswith("On the calendar today: Dentist at ten")
    assert response["answer"].endswith("No reminders due today.")
    assert response["data"]["calendar"] == "connected"
    assert [event["title"] for event in response["data"]["events"]] == ["Standup", "Dentist"]
    # An empty day, then a calendar read that's turned off by permission.
    app.calendar.events = []
    live.tool_responses.clear()
    assert (await ask(live, "quick_agenda"))["answer"].startswith("Your calendar's clear today.")
    app.settings["tool_permissions"]["calendar_read"] = "deny"
    live.tool_responses.clear()
    response = await ask(live, "quick_agenda")
    assert response["data"]["calendar"] == "off"
    assert response["answer"].startswith("Reading the calendar is turned off.")
    await app.voice.stop_sid()


@pytest.mark.asyncio
async def test_a_slow_calendar_still_leaves_time_for_the_reminders(voice, monkeypatch):
    app, connector = voice
    monkeypatch.setattr(voice_quick, "QUICK_SECONDS", 0.1)
    calendar = FakeCalendar([])

    async def hang():
        await asyncio.Event().wait()

    calendar.today_events = hang
    app.calendar = calendar
    add_reminder(app, "Water the plants", NOW.replace(hour=18))
    live = await start(app, connector)
    response = await ask(live, "quick_agenda")
    assert response["data"]["calendar"] == "unavailable"
    assert response["answer"] == (
        "I couldn't read the calendar just now. One reminder: Water the plants."
    )
    await app.voice.stop_sid()


# --- quick_home -------------------------------------------------------------------------------


def test_home_summary_counts_and_never_describes_off_limits_devices():
    line, data = voice_quick.home_summary([
        {"domain": "light", "name": "Desk", "state": "On · 40%"},
        {"domain": "light", "name": "Hall", "state": "Off"},
        {"domain": "light", "name": "Porch", "state": "Off"},
        {"domain": "fan", "name": "Ceiling", "state": "On"},
        {"domain": "lock", "name": "Front door", "state": "Unlocked"},
        {"domain": "alarm_control_panel", "name": "Alarm", "state": "Armed (away)"},
        {"domain": "climate", "name": "Bedroom AC", "state": "Cooling"},
        {"domain": "switch", "name": "Kettle", "state": "Unavailable"},
        {"name": "Safe", "room": "Study", "access": "off limits"},
    ])
    assert line == (
        "At home: 1 of 3 lights on, 1 fan on, Front door unlocked, the alarm armed (away), "
        "1 climate device running, 1 unavailable."
    )
    assert data["off_limits"] == 1 and "Safe" not in str(data)
    assert voice_quick.home_summary([])[0] == "Nothing to report at home."


@pytest.mark.asyncio
async def test_quick_home_answers_from_home_assistant(voice):
    app, connector = voice

    async def list_for_brain(room=None, domain=None):
        return {"devices": [
            {"domain": "light", "name": "Desk", "state": "On"},
            {"domain": "lock", "name": "Front door", "state": "Locked"},
        ]}

    app.home = SimpleNamespace(connected=True, list_for_brain=list_for_brain)
    live = await start(app, connector)
    response = await ask(live, "quick_home")
    assert response["answer"] == "At home: 1 of 1 light on, the lock is locked."
    assert response["data"]["lights_on"] == 1
    app.settings["tool_permissions"]["home_devices"] = "deny"
    live.tool_responses.clear()
    assert (await ask(live, "quick_home"))["error"] == "permission_denied"
    app.conversation.reply.assert_not_called()
    await app.voice.stop_sid()
