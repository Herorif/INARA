"""P2 morning briefing: the composer, the trigger, delivery (card, speech, Live failure),
the phone call, settings, the briefing call mode and free/busy for call screening.

No network, provider, Twilio, Google, audio device or port: Live is FakeConnector, PortAudio
is the tray fixture's fake, calls are recorded by a fake CallAgent.call, Google is
httpx.MockTransport, and the clock is a fake wall clock.
"""

import asyncio
import datetime as dt
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from pydantic import ValidationError

from services import briefing as composer
from services.briefing import ZONE, compose, live_turn, overnight_since, spoken_time
from services.settings import (
    BRIEFING_DEFAULTS,
    BriefingSettings,
    SettingsPatch,
    SettingsService,
    SettingsStore,
    briefing_settings,
)
from services.tools import ServiceError
from telephony import briefs
from telephony.agent import CallHandle, CallResult

from tests.test_local_voice import OWNER as TRAY_OWNER, speech
from tests.test_local_voice import tray  # noqa: F401 - the tray voice fixture
from tests.test_voice_live import until
from tests.test_voice_overlay import sent

NOW = dt.datetime(2026, 11, 8, 8, 5, tzinfo=ZONE)  # Sunday 8 November, 08:05 Malaysia time
OWNER_NUMBER = "+60123456789"
TITLE_A, TITLE_B = "Dentist, Dr Lim", "Design review"
REMINDER_A, REMINDER_B = "Send the invoice to Hafiz", "Pick up the parcel"
SUMMARY = "Call me when you're up, nothing urgent."
SENSITIVE = (TITLE_A, TITLE_B, REMINDER_A, REMINDER_B, SUMMARY, "Mum", "NAS case")
NO_TIME = composer.NO_TIME


def at(day, hour, minute=0):
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=ZONE).timestamp()


def event(title, start, end, *, day="2026-11-08", all_day=False):
    return {"title": title, "date": day, "all_day": all_day,
            "start": None if all_day else start, "end": None if all_day else end}


CALENDAR = [event(TITLE_A, "10:00", "11:00"), event(TITLE_B, "15:00", "16:00")]
REMINDERS = [
    {"task": REMINDER_A, "trigger_at": at(7, 17), "status": "pending"},  # overdue from yesterday
    {"task": REMINDER_B, "trigger_at": at(8, 18), "status": "pending"},
]
VIP = {"id": "rec-vip", "started_at": at(7, 22, 41), "name": "Mum", "group": "vip",
       "summary": SUMMARY, "status": "done", "counterpart_masked": "+60 12-*** 6789"}
SPAM = {"id": "rec-spam", "started_at": at(8, 2, 13), "name": None, "group": None,
        "summary": "A sales pitch.", "status": "spam", "counterpart_masked": "+60 3-*** 0000"}
JOB = {"kind": "cad", "request_id": "9f3c2a17-5b6d-4c1e-8f00-000000000001", "name": "NAS case",
       "state": "succeeded", "finished_at": at(7, 23, 58)}


def everything(settings=None, **overrides):
    values = {"calendar": CALENDAR, "reminders": REMINDERS, "calls": [VIP, SPAM], "jobs": [JOB]}
    values.update(overrides)
    return compose(NOW, settings or {}, **values)


def sentences(text):
    return [part for part in text.replace("? ", ". ").split(". ") if part]


# --- the composer: the card -------------------------------------------------------------------


def test_card_has_every_section_in_order_with_the_mockup_data():
    card = everything()["card"]
    assert card["date_label"] == "Sunday 8 November"
    assert [section["id"] for section in card["sections"]] == ["today", "reminders", "calls", "jobs"]
    today, reminders, calls, jobs = (section["items"] for section in card["sections"])
    assert today == [{"time": "10:00", "text": TITLE_A}, {"time": "15:00", "text": TITLE_B}]
    assert reminders == [{"time": NO_TIME, "text": REMINDER_A}, {"time": "18:00", "text": REMINDER_B}]
    assert calls == [
        {"time": "22:41", "text": "Mum · VIP", "detail": SUMMARY, "tone": "accent",
         "action": {"kind": "call", "record_id": "rec-vip"}},
        {"time": "02:13", "text": "1 call ended as spam", "tone": "muted"},
    ]
    assert jobs == [{"time": "23:58", "text": "NAS case built · revision 9f3c2a17",
                     "action": {"kind": "studio", "request_id": JOB["request_id"], "studio": "cad"}}]
    json.dumps(card)  # plain JSON for the renderer


def test_calls_put_vips_first_then_known_and_unknown_and_sum_spam():
    known = {**VIP, "id": "rec-known", "started_at": at(7, 20), "name": "Aiman", "group": "known",
             "summary": "About the parcel."}
    unknown = {**VIP, "id": "rec-new", "started_at": at(7, 19), "name": None, "group": None,
               "summary": None, "counterpart_masked": "withheld"}
    late_vip = {**VIP, "id": "rec-vip2", "started_at": at(8, 6), "name": "Dad", "summary": None}
    blocked = {**SPAM, "id": "rec-blocked", "started_at": at(8, 3), "status": "blocked"}
    calls = compose(NOW, {}, calls=[unknown, known, SPAM, late_vip, VIP, blocked])["card"]["sections"][0]
    assert calls["id"] == "calls"
    texts = [item["text"] for item in calls["items"]]
    assert texts == ["Mum · VIP", "Dad · VIP", "Withheld number", "Aiman", "2 calls ended as spam"]
    assert calls["items"][1]["detail"] == "Left a message."  # a VIP without a summary yet
    assert calls["items"][-1]["time"] == "03:00"  # the latest of the spam calls
    assert "action" not in calls["items"][2] and "action" not in calls["items"][3]
    assert calls["items"][3]["detail"] == "About the parcel."


def test_overnight_starts_at_the_later_of_the_last_briefing_and_six_pm():
    evening = at(7, 18)
    assert overnight_since(NOW) == evening
    assert overnight_since(NOW, at(7, 9)) == evening  # yesterday morning's briefing
    assert overnight_since(NOW, at(7, 22)) == at(7, 22)  # played again late last night
    early = {**VIP, "id": "rec-old", "started_at": at(7, 17, 59)}
    assert compose(NOW, {}, calls=[early])["card"]["sections"] == []
    after_play = compose(NOW, {}, calls=[VIP], since=at(7, 23))["card"]["sections"]
    assert after_play == []


def test_calendar_section_rules():
    past = event("Breakfast", "07:00", "07:30")
    ongoing = event("Standup", "08:00", "08:30")
    all_day = event("Public holiday", None, None, all_day=True)
    carried = event("Conference", "09:00", "17:00", day="2026-11-07")
    items = compose(NOW, {}, calendar=[past, ongoing, all_day, carried])["card"]["sections"][0]["items"]
    assert items == [
        {"time": NO_TIME, "text": "Public holiday"},
        {"time": NO_TIME, "text": "Conference"},
        {"time": "08:00", "text": "Standup"},
    ]
    clear = compose(NOW, {}, calendar=[])["card"]["sections"]
    assert clear == [{"id": "today", "items": [
        {"time": NO_TIME, "text": "Nothing on the calendar today", "tone": "muted"}]}]


def test_sections_without_a_source_are_left_out():
    card = compose(NOW, {}, reminders=REMINDERS)["card"]
    assert [section["id"] for section in card["sections"]] == ["reminders"]
    future = [{"task": "Tomorrow", "trigger_at": at(9, 9), "status": "pending"},
              {"task": "Done", "trigger_at": at(8, 9), "status": "done"}]
    assert compose(NOW, {}, reminders=future)["card"]["sections"] == []
    failed = {**JOB, "state": "failed"}
    image = {**JOB, "kind": "image", "name": "Poster", "request_id": "abcdef12-0000"}
    jobs = compose(NOW, {}, jobs=[failed, image])["card"]["sections"][0]["items"]
    assert jobs == [{"time": "23:58", "text": "Poster rendered · revision abcdef12",
                     "action": {"kind": "studio", "request_id": "abcdef12-0000", "studio": "image"}}]


# --- the composer: the spoken text --------------------------------------------------------------


def test_sir_with_everything_is_capped_at_four_sentences():
    spoken = everything()["spoken"]
    assert spoken == (
        "Good morning, sir. On the calendar today: Dentist, Dr Lim at ten, and Design review at three. "
        "Mum called last night: Call me when you're up, nothing urgent. The rest is on screen."
    )
    assert spoken.count(".") >= 4 and spoken.endswith(composer.REST_ON_SCREEN)
    assert "spam" not in spoken.lower()


@pytest.mark.parametrize("assistant,greeting", [
    ({}, "Good morning, sir."),
    ({"address": "sir"}, "Good morning, sir."),
    ({"address": "maam"}, "Good morning, ma'am."),
    ({"address": "name", "owner_name": "  Hiro  "}, "Good morning, Hiro."),
    ({"address": "name", "owner_name": ""}, "Good morning."),
    ({"address": "none", "owner_name": "Hiro"}, "Good morning."),
    ({"address": "boss"}, "Good morning, sir."),
])
def test_the_four_forms_of_address(assistant, greeting):
    spoken = compose(NOW, {"assistant": assistant}, calendar=[])["spoken"]
    assert spoken == f"{greeting} Nothing on the calendar and nothing new overnight."


@pytest.mark.parametrize("value,words", [
    ("10:00", "ten"), ("15:00", "three"), ("09:30", "9:30"), ("21:05", "9:05"), ("00:00", "twelve"),
    ("12:00", "twelve"), ("12:45", "12:45"), ("13:00", "one"),
])
def test_whole_hours_are_words_and_other_times_digits(value, words):
    assert spoken_time(value) == words


def test_calendar_sentences():
    one = compose(NOW, {}, calendar=[CALENDAR[0]])["spoken"]
    assert one == "Good morning, sir. On the calendar today: Dentist, Dr Lim at ten."
    three = compose(NOW, {}, calendar=[*CALENDAR, event("Gym", "18:30", "19:30")])["spoken"]
    assert three == "Good morning, sir. On the calendar today: Dentist, Dr Lim at ten, and two more."
    holiday = compose(NOW, {}, calendar=[event("Public holiday", None, None, all_day=True)])["spoken"]
    assert holiday == "Good morning, sir. On the calendar today: Public holiday, all day."
    clear_with_more = compose(NOW, {}, calendar=[], jobs=[JOB])["spoken"]
    assert clear_with_more == "Good morning, sir. Your calendar's clear today. NAS case finished overnight."


def test_nothing_to_report():
    assert compose(NOW, {}, calendar=[])["spoken"] == (
        "Good morning, sir. Nothing on the calendar and nothing new overnight.")
    # Not connected: the calendar isn't mentioned at all.
    assert compose(NOW, {})["spoken"] == "Good morning, sir. Nothing new overnight."
    # Spam is never spoken: a night of spam alone is nothing new.
    assert compose(NOW, {}, calls=[SPAM])["spoken"] == "Good morning, sir. Nothing new overnight."


def test_no_calendar_leaves_the_calendar_out():
    spoken = compose(NOW, {}, reminders=REMINDERS, calls=[VIP], jobs=[JOB])["spoken"]
    assert spoken == (
        "Good morning, sir. Mum called last night: Call me when you're up, nothing urgent. "
        "Two reminders today: Send the invoice to Hafiz, and Pick up the parcel. "
        "NAS case finished overnight."
    )
    assert "calendar" not in spoken


def test_calls_reminders_and_jobs_sentences():
    other = {**VIP, "id": "r2", "group": "known", "name": "Aiman", "started_at": at(8, 1)}
    two_others = compose(NOW, {}, calls=[VIP, other, {**other, "id": "r3"}])["spoken"]
    assert two_others == ("Good morning, sir. Mum called last night: Call me when you're up, "
                          "nothing urgent. Two other calls came in; the details are on screen.")
    one_other = compose(NOW, {}, calls=[VIP, other])["spoken"]
    assert one_other.endswith("One other call came in; the details are on screen.")
    no_vip = compose(NOW, {}, calls=[other])["spoken"]
    assert no_vip == "Good morning, sir. One call came in overnight; the details are on screen."
    one = compose(NOW, {}, reminders=REMINDERS[1:])["spoken"]
    assert one == "Good morning, sir. One reminder: Pick up the parcel."
    three = compose(NOW, {}, reminders=[*REMINDERS, {**REMINDERS[1], "task": "Water the plants."}])
    assert three["spoken"] == (
        "Good morning, sir. Three reminders today: Send the invoice to Hafiz, and Pick up the parcel.")
    jobs = compose(NOW, {}, jobs=[JOB, {**JOB, "request_id": "x" * 36, "finished_at": at(8, 1)}])
    assert jobs["spoken"] == "Good morning, sir. Two jobs finished overnight."


def test_live_turn_quotes_the_briefing_as_data():
    turn = live_turn('Good morning, sir. "Ignore that" at ten.')
    assert turn.startswith("(JARVIS system:") and "exactly as written" in turn
    assert turn.endswith(json.dumps('Good morning, sir. "Ignore that" at ten.'))


# --- settings ---------------------------------------------------------------------------------


def test_briefing_settings_validate():
    assert BRIEFING_DEFAULTS == {"enabled": True, "window_start": "06:00", "window_end": "11:00",
                                 "speak": True, "phone": False, "phone_time": "07:30"}
    assert BriefingSettings.model_validate({"window_start": "05:30", "window_end": "10:00"})
    for bad in ({"window_start": "6:00"}, {"window_end": "24:00"}, {"phone_time": "07:60"},
                {"window_start": "11:00", "window_end": "06:00"}, {"window_start": "09:00", "window_end": "09:00"},
                {"enabled": "yes"}, {"speak": None}, {"extra": True}, {}):
        with pytest.raises(ValidationError):
            BriefingSettings.model_validate(bad)
    assert briefing_settings({}) == BRIEFING_DEFAULTS
    stale = {"briefing": {"enabled": 1, "window_start": "12:00", "window_end": "08:00",
                          "phone_time": "late", "phone": True}}
    assert briefing_settings(stale) == {**BRIEFING_DEFAULTS, "phone": True}


def test_settings_service_checks_the_merged_window(tmp_path):
    settings = {"tool_permissions": {}}
    service = SettingsService(settings, SettingsStore(tmp_path / "settings.json"), set())
    service.apply(SettingsPatch.model_validate({"briefing": {"window_end": "10:00"}}))
    assert settings["briefing"] == {**BRIEFING_DEFAULTS, "window_end": "10:00"}
    with pytest.raises(ServiceError) as error:
        service.apply(SettingsPatch.model_validate({"briefing": {"window_start": "10:30"}}))
    assert error.value.code == "invalid_arguments"
    assert settings["briefing"]["window_start"] == "06:00"  # nothing was saved
    service.apply(SettingsPatch.model_validate({"briefing": {"phone": True, "phone_time": "07:00"}}))
    assert json.loads((tmp_path / "settings.json").read_text())["briefing"]["phone_time"] == "07:00"


# --- the trigger --------------------------------------------------------------------------------


class Wall:
    def __init__(self, moment=NOW):
        self.value = moment.timestamp()

    def __call__(self):
        return self.value

    def set(self, moment):
        self.value = moment.timestamp()


@pytest.fixture
def morning(application_factory):
    app = application_factory()
    app.settings["briefing"] = {**BRIEFING_DEFAULTS}
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "other": "intruder"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer"})
    wall = Wall()
    app.briefing.wall = wall
    app.voice.preflight = lambda: None
    app.voice.start_briefing = AsyncMock(return_value=True)
    return SimpleNamespace(app=app, wall=wall, briefing=app.briefing)


def cards(app):
    return [call.args[1]["briefing"] for call in app.sio.emit.await_args_list if call.args[0] == "briefing"]


async def presence(ctx, source="ping"):
    await ctx.briefing._presence(source)


@pytest.mark.asyncio
async def test_first_presence_in_the_window_shows_and_speaks_it_once_a_day(morning):
    app, briefing = morning.app, morning.briefing
    morning.wall.set(NOW.replace(hour=5, minute=55))
    await presence(morning)
    assert cards(app) == [] and briefing.load()["present_at"]
    morning.wall.set(NOW)
    await presence(morning)
    shown = cards(app)[-1]
    assert shown["date"] == "2026-11-08" and shown["card"]["date_label"] == "Sunday 8 November"
    assert shown["expires_at"] == "2026-11-08T12:00:00+08:00"
    spoken = app.voice.start_briefing.await_args.args[0]
    assert spoken == "Good morning, sir. Nothing new overnight."
    await presence(morning, "unlock")
    await presence(morning, "voice")
    assert app.voice.start_briefing.await_count == 1 and len(cards(app)) == 1
    morning.wall.set(NOW + dt.timedelta(days=1))  # Monday 08:05: a new day
    await presence(morning)
    assert app.voice.start_briefing.await_count == 2


@pytest.mark.asyncio
async def test_outside_the_window_or_switched_off_nothing_plays(morning):
    app = morning.app
    morning.wall.set(NOW.replace(hour=11, minute=0))
    await presence(morning)
    app.settings["briefing"]["enabled"] = False
    morning.wall.set(NOW)
    await presence(morning)
    assert cards(app) == [] and app.voice.start_briefing.await_count == 0


@pytest.mark.asyncio
async def test_a_presence_during_voice_waits_until_the_session_ends(morning):
    app, briefing = morning.app, morning.briefing
    app.voice.sessions["owner"] = SimpleNamespace(closed=False)
    await presence(morning, "voice")
    assert cards(app) == [] and briefing.waiting == "2026-11-08"
    del app.voice.sessions["owner"]
    briefing.voice_ended()
    await until(lambda: app.voice.start_briefing.await_count == 1)
    assert cards(app)[-1]["card"] and briefing.waiting is None


@pytest.mark.asyncio
async def test_a_held_briefing_still_plays_after_the_window_but_not_after_noon(morning):
    app, briefing = morning.app, morning.briefing
    app.voice.sessions["owner"] = SimpleNamespace(closed=False)
    morning.wall.set(NOW.replace(hour=10, minute=58))
    await presence(morning, "voice")
    del app.voice.sessions["owner"]
    morning.wall.set(NOW.replace(hour=11, minute=4))
    await briefing._resume()
    assert app.voice.start_briefing.await_count == 1
    # A different day: held until after noon is dropped.
    morning.wall.set(NOW.replace(day=9, hour=10, minute=58))
    app.voice.sessions["owner"] = SimpleNamespace(closed=False)
    await presence(morning, "voice")
    del app.voice.sessions["owner"]
    morning.wall.set(NOW.replace(day=9, hour=12, minute=1))
    await briefing._resume()
    assert app.voice.start_briefing.await_count == 1 and briefing.waiting is None


@pytest.mark.asyncio
async def test_gaming_mode_shows_the_card_only(morning):
    app = morning.app
    app.resources.select("gaming")
    await presence(morning)
    assert cards(app)[-1]["card"] and app.voice.start_briefing.await_count == 0
    assert morning.briefing.load()["shown_at"]


@pytest.mark.asyncio
async def test_face_lock_waits_until_unlocked(morning):
    app, briefing = morning.app, morning.briefing
    unlocked = {"value": False}
    app.settings["face_auth_enabled"] = True
    app.sessions.face_authenticated = lambda: unlocked["value"]
    await presence(morning)
    assert cards(app) == [] and briefing.waiting == "2026-11-08"
    unlocked["value"] = True
    await app.connection.hydrate("client")  # unlocking hydrates the renderer
    await until(lambda: app.voice.start_briefing.await_count == 1)
    assert cards(app)[-1]["card"]


@pytest.mark.asyncio
async def test_speak_off_shows_just_the_card(morning):
    app = morning.app
    app.settings["briefing"]["speak"] = False
    await presence(morning)
    assert cards(app)[-1]["card"] and app.voice.start_briefing.await_count == 0


@pytest.mark.asyncio
async def test_presence_ping_and_hydrate_reach_the_briefing(morning):
    app = morning.app
    ack = await app.sio.handlers["/"]["presence_ping"]("client", {})
    assert ack == {"ok": True}
    await until(lambda: app.voice.start_briefing.await_count == 1)
    app.sio.emit.reset_mock()
    await app.connection.hydrate("client")
    # The renderer that connects gets today's card at once.
    assert [call.kwargs["room"] for call in app.sio.emit.await_args_list
            if call.args[0] == "briefing"] == ["client"]


@pytest.mark.asyncio
async def test_a_tray_voice_start_counts_as_presence(tray):  # noqa: F811
    app = tray.app
    app.settings["briefing"] = {**BRIEFING_DEFAULTS}
    calls = []
    app.briefing.presence = calls.append
    assert (await app.voice.start_local())["ok"]
    assert calls == ["voice"]
    await app.voice.stop_local()


# --- delivery -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_card_is_kept_until_dismissed_or_noon(morning):
    app, briefing = morning.app, morning.briefing
    handlers = app.sio.handlers["/"]
    assert (await handlers["briefing_get"]("client", {})) == {"ok": True, "briefing": None}
    await presence(morning)
    got = await handlers["briefing_get"]("client", {})
    assert got["ok"] and got["briefing"]["card"]["sections"] == []
    morning.wall.set(NOW.replace(hour=12))
    assert (await handlers["briefing_get"]("client", {}))["briefing"] is None
    await briefing.check()  # the tick publishes the expiry once
    await briefing.check()
    assert [item for item in cards(app)][-1] is None and cards(app).count(None) == 1
    morning.wall.set(NOW)
    assert (await handlers["briefing_dismiss"]("client", {})) == {"ok": True}
    assert cards(app)[-1] is None
    assert (await handlers["briefing_get"]("client", {}))["briefing"] is None


@pytest.mark.asyncio
async def test_play_works_outside_the_window_and_reports_why_it_was_not_spoken(morning):
    app = morning.app
    handlers = app.sio.handlers["/"]
    morning.wall.set(NOW.replace(hour=14))
    played = await handlers["briefing_play"]("client", {})
    assert played["ok"] and played["spoken"] is True and played["reason"] is None
    # Shown after noon: kept until midnight.
    assert played["briefing"]["expires_at"] == "2026-11-09T00:00:00+08:00"
    app.resources.select("gaming")
    assert (await handlers["briefing_play"]("client", {}))["reason"] == "gaming_mode"
    app.resources.select("chat")
    app.voice.sessions["owner"] = SimpleNamespace(closed=False)
    assert (await handlers["briefing_play"]("client", {}))["reason"] == "voice_busy"
    del app.voice.sessions["owner"]

    def missing():
        raise ServiceError("provider_not_configured", "Voice needs a Gemini API key.")

    app.voice.preflight = missing
    assert (await handlers["briefing_play"]("client", {}))["reason"] == "provider_not_configured"
    assert app.voice.start_briefing.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["briefing_get", "briefing_dismiss", "briefing_play"])
async def test_routes_are_owner_only_unlocked_and_strict(morning, name):
    app = morning.app
    handler = app.sio.handlers["/"][name]
    assert (await handler("other", {}))["code"] == "permission_denied"
    assert (await handler("client", {"extra": 1}))["code"] == "invalid_arguments"
    app.settings["face_auth_enabled"] = True
    app.sessions.face_authenticated = lambda: False
    assert (await handler("client", {}))["code"] == "authentication_required"
    assert app.voice.start_briefing.await_count == 0


@pytest.mark.asyncio
async def test_briefing_gathers_calendar_reminders_calls_and_jobs(morning, monkeypatch):
    app, briefing = morning.app, morning.briefing
    app.reminders.add_reminder(REMINDER_B, at(8, 18))
    app.calendar.events = AsyncMock(return_value={"events": CALENDAR})
    monkeypatch.setattr(type(app.calendar), "connected", property(lambda self: True))
    app.call_agent.records.clock = morning.wall  # retention runs on the same fake clock
    record = {
        "id": str(uuid.uuid4()), "source": "twilio", "state": "completed",
        "direction": "inbound", "mode": "screening",
        "counterpart": app.call_agent.records.counterpart(OWNER_NUMBER),
        "started_at": at(7, 22, 41), "finished_at": at(7, 22, 43), "duration_seconds": 90.0,
        "fields": {"message": {"name": "Mum", "message": "Hi"}}, "transcript": [],
        "outcome": {"status": "message_taken"}, "caller_group": "vip", "contact_id": None,
        "triage": {"summary": SUMMARY, "urgency": "normal", "needs_owner": True,
                   "suggested_actions": [], "suggested_reply": "", "spam": False},
        "triage_state": "done",
    }
    app.call_agent.records.save_call(record)
    app.cad.list = lambda owner, project: [{
        "request_id": JOB["request_id"], "recipe": {"name": "NAS case"}, "state": "succeeded",
        "created_at": at(7, 23, 50), "duration_seconds": 480.0}]
    await presence(morning)
    sections = {section["id"]: section["items"] for section in cards(app)[-1]["card"]["sections"]}
    assert sections["today"][0] == {"time": "10:00", "text": TITLE_A}
    assert sections["reminders"] == [{"time": "18:00", "text": REMINDER_B}]
    assert sections["calls"][0]["text"] == "Mum · VIP" and sections["calls"][0]["detail"] == SUMMARY
    assert sections["calls"][0]["action"] == {"kind": "call", "record_id": record["id"]}
    assert sections["jobs"][0]["text"] == "NAS case built · revision 9f3c2a17"
    midnight = NOW.replace(hour=0, minute=5)
    start, end = app.calendar.events.await_args.args
    assert start == midnight.replace(minute=0) and end - start == dt.timedelta(days=1)
    # Reading events off: the calendar is left out, not read.
    app.calendar.events.reset_mock()
    app.settings["calendar"] = {"read_events": False}
    composed = await briefing.compose(NOW, briefing.load())
    assert app.calendar.events.await_count == 0
    assert "today" not in [section["id"] for section in composed["card"]["sections"]]


@pytest.mark.asyncio
async def test_no_sensitive_text_in_logs(morning, caplog, monkeypatch):
    app = morning.app
    app.calendar.events = AsyncMock(return_value={"events": CALENDAR})
    monkeypatch.setattr(type(app.calendar), "connected", property(lambda self: True))
    app.reminders.add_reminder(REMINDER_A, at(8, 9))
    with caplog.at_level(logging.DEBUG):
        await presence(morning)
        await app.sio.handlers["/"]["briefing_play"]("client", {})
        app.calendar.events = AsyncMock(side_effect=RuntimeError(TITLE_A))  # a failing read
        await app.sio.handlers["/"]["briefing_play"]("client", {})
    spoken = app.voice.start_briefing.await_args_list[0].args[0]
    assert TITLE_A in spoken
    for text in (*SENSITIVE, spoken):
        assert text not in caplog.text


# --- speech through tray voice (fake Live) --------------------------------------------------------


@pytest.mark.asyncio
async def test_speech_sends_one_text_turn_then_listens_like_a_conversation(tray):  # noqa: F811
    app, connector = tray.app, tray.connector
    text = "Good morning, sir. Nothing new overnight."
    assert await app.voice.start_briefing(text) is True
    await until(lambda: connector.connections and connector.connections[-1].sent)
    live = connector.connections[-1]
    assert live.sent[0] == {"text": live_turn(text)}
    session = app.voice.sessions[TRAY_OWNER]
    assert session.source == "briefing" and session.mode == "conversation"
    await until(lambda: sent(app, "local_voice", "client"))
    assert sent(app, "local_voice", "client")[-1]["source"] == "briefing"
    live.push(model_turn=speech())
    await until(lambda: session.spoke)
    live.push(output_transcription={"text": text}, turn_complete=True)
    await until(lambda: session.state == "listening")
    assert not session.closed  # it stays listening for the owner's reply
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_a_live_failure_leaves_the_card_only(tray):  # noqa: F811
    app, connector = tray.app, tray.connector
    connector.fail = ConnectionError("no network")
    assert await app.voice.start_briefing("Good morning, sir.") is True
    await until(lambda: not app.voice.sessions)
    await until(lambda: (sent(app, "local_voice", "client") or [{}])[-1].get("end") is not None)
    assert sent(app, "local_voice", "client")[-1]["end"] == {"kind": "quiet", "message": None}
    assert tray.statuses[-1]["notice"] is None  # nothing on the tray either


@pytest.mark.asyncio
async def test_a_refused_speech_start_shows_nothing_on_the_tray(tray):  # noqa: F811
    app = tray.app
    app.resources.select("gaming")
    count = len(tray.statuses)
    assert await app.voice.start_briefing("Good morning, sir.") is False
    assert len(tray.statuses) == count


@pytest.mark.asyncio
async def test_play_from_preferences_speaks_through_tray_voice(tray):  # noqa: F811
    app = tray.app
    played = await app.sio.handlers["/"]["briefing_play"]("client", {})
    assert played["ok"] and played["spoken"] is True
    await until(lambda: tray.connector.connections and tray.connector.connections[-1].sent)
    assert "text" in tray.connector.connections[-1].sent[0]
    await app.voice.stop_local()


# --- the phone ------------------------------------------------------------------------------------


class FakeCalls:
    def __init__(self):
        self.placed, self.handles = [], []

    async def __call__(self, brief, grant=None):
        self.placed.append((brief, grant))
        handle = CallHandle(uuid.uuid4().hex, "CA" + "d" * 32, asyncio.get_running_loop().create_future())
        self.handles.append(handle)
        return handle


@pytest.fixture
def phone_morning(morning):
    app = morning.app
    app.settings["briefing"].update(phone=True, phone_time="07:30")
    morning.wall.set(NOW.replace(hour=7, minute=31))
    telephony = app.telephony
    telephony.calls_settings = lambda: {"enabled": True}
    telephony.credentials = lambda: {"owner_number": OWNER_NUMBER}
    telephony.public_base_url = lambda: "https://calls.example.com"
    telephony.agent_ready = lambda: True
    app.call_orchestrator.presence.away = lambda: True
    morning.calls = FakeCalls()
    app.call_agent.call = morning.calls
    return morning


def result(handle, state="completed", status="delivered"):
    handle.result.set_result(CallResult("rec", "morning_briefing", "outbound", state,
                                        {"status": status}, {}, 30.0))


@pytest.mark.asyncio
async def test_the_phone_rings_at_the_set_time_when_away_and_marks_the_day(phone_morning):
    ctx = phone_morning
    app, briefing = ctx.app, ctx.briefing
    ctx.wall.set(NOW.replace(hour=7, minute=29))
    assert await briefing.check_phone() is False
    ctx.wall.set(NOW.replace(hour=7, minute=31))
    assert await briefing.check_phone() is True
    brief, grant = ctx.calls.placed[0]
    assert brief.mode == "morning_briefing" and brief.counterpart == OWNER_NUMBER and grant is None
    assert brief.morning == "Good morning, sir. Nothing new overnight."
    assert await briefing.check_phone() is False  # once a day
    result(ctx.calls.handles[0])
    await until(lambda: briefing.load().get("phone") == "done")
    # Later at the PC: the card, but not spoken again.
    ctx.wall.set(NOW.replace(hour=9))
    await presence(ctx)
    assert cards(app)[-1]["card"] and app.voice.start_briefing.await_count == 0


@pytest.mark.asyncio
async def test_an_unanswered_call_lets_the_pc_speak_it(phone_morning):
    ctx = phone_morning
    assert await ctx.briefing.check_phone() is True
    result(ctx.calls.handles[0], state="no_answer", status="no_answer")
    await until(lambda: ctx.briefing.load().get("phone") == "missed")
    ctx.wall.set(NOW.replace(hour=9))
    await presence(ctx)
    assert ctx.app.voice.start_briefing.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["present", "not_away", "calls_off", "no_number", "gaming",
                                    "phone_off", "too_late", "on_a_call"])
async def test_no_phone_call_unless_every_condition_holds(phone_morning, change):
    ctx = phone_morning
    app = ctx.app
    if change == "present":
        ctx.wall.set(NOW.replace(hour=5))
        await presence(ctx)  # at the PC before the window: no call today
        ctx.wall.set(NOW.replace(hour=7, minute=31))
    elif change == "not_away":
        app.call_orchestrator.presence.away = lambda: False
    elif change == "calls_off":
        app.telephony.calls_settings = lambda: {"enabled": False}
    elif change == "no_number":
        app.telephony.credentials = lambda: {"owner_number": None}
    elif change == "gaming":
        app.resources.select("gaming")
    elif change == "phone_off":
        app.settings["briefing"]["phone"] = False
    elif change == "too_late":
        ctx.wall.set(NOW.replace(hour=8, minute=1))
    elif change == "on_a_call":
        app.telephony.sessions = {"CA1": object()}
    assert await ctx.briefing.check_phone() is False
    assert ctx.calls.placed == []


@pytest.mark.asyncio
async def test_a_refused_call_is_not_retried(phone_morning):
    ctx = phone_morning

    async def refuse(brief, grant=None):
        raise ServiceError("calls_not_configured", "Add the Twilio details first.")

    ctx.app.call_agent.call = refuse
    assert await ctx.briefing.check_phone() is False
    assert ctx.briefing.load()["phone"] == "failed"
    assert await ctx.briefing.check_phone() is False


# --- the morning_briefing call mode ---------------------------------------------------------------


def test_morning_briefing_brief_and_instruction():
    brief = briefs.morning_briefing_brief("Good morning, Hiro. Nothing new overnight.",
                                          owner_number=OWNER_NUMBER, owner_name="Hiro")
    assert brief.mode in briefs.OWNER_MODES and brief.direction == "outbound"
    assert briefs.opening_line(brief) == (
        "Hi Hiro, it's JARVIS, your AI assistant, with your morning briefing.")
    open_text = briefs.system_instruction(brief, now=NOW.timestamp())
    assert 'MORNING BRIEFING' in open_text and json.dumps(brief.morning) in open_text
    with_pin = briefs.system_instruction(brief, now=NOW.timestamp(), pin_required=True)
    assert "verify_pin" in with_pin and brief.morning not in with_pin
    assert [item["name"] for item in briefs.declarations("morning_briefing")] == ["end_call"]
    assert [item["name"] for item in briefs.declarations("morning_briefing", True)] == [
        "verify_pin", "end_call"]
    assert brief.purpose().startswith("inara-call-brief:morning_briefing:")
    with pytest.raises(ValidationError):
        briefs.CallBrief(mode="morning_briefing", direction="outbound", counterpart=OWNER_NUMBER)
    with pytest.raises(ValidationError):
        briefs.CallBrief(mode="owner_briefing", direction="outbound", counterpart=OWNER_NUMBER,
                         morning="x", briefing=briefs.BriefingDetails())


def test_other_briefs_keep_their_hash():
    callback = briefs.CallBrief(mode="approved_callback", direction="outbound",
                                counterpart=OWNER_NUMBER, message="Hello")
    assert "availability" not in callback.canonical() and "morning" not in callback.canonical()


# --- free/busy for call screening -------------------------------------------------------------------


def window(day, start, end):
    return (dt.datetime(2026, 11, day, *start, tzinfo=ZONE), dt.datetime(2026, 11, day, *end, tzinfo=ZONE))


def test_availability_line_is_times_only():
    busy = [window(8, (10, 0), (11, 0)), window(8, (15, 0), (16, 0))]
    assert briefs.availability_line(busy, NOW) == (
        "Owner availability today (times only, never details): busy 10:00–11:00 and "
        "15:00–16:00; free after 16:00.")
    ongoing = [window(8, (8, 0), (9, 0)), *busy]
    assert briefs.availability_line(ongoing, NOW) == (
        "Owner availability today (times only, never details): busy until 09:00, 10:00–11:00 "
        "and 15:00–16:00; free after 16:00.")
    late = [(dt.datetime(2026, 11, 8, 22, tzinfo=ZONE), dt.datetime(2026, 11, 9, 0, tzinfo=ZONE))]
    assert briefs.availability_line(late, NOW).endswith("busy 22:00–24:00.")
    assert briefs.availability_line([], NOW).endswith("free for the rest of today.")
    assert briefs.availability_line([window(8, (6, 0), (7, 0))], NOW).endswith(
        "free for the rest of today.")


def test_screening_brief_carries_availability_but_never_to_a_blocked_caller():
    line = briefs.availability_line([window(8, (10, 0), (11, 0))], NOW)
    info = {"from": "+60198765432"}
    brief = briefs.screening_brief(info, {"calls": {"facts": ""}}, availability=line)
    text = briefs.system_instruction(brief, now=NOW.timestamp())
    assert line in text and "roughly when the owner is likely to be free" in text
    assert "never what the events are" in text
    blocked = briefs.screening_brief(info, {}, {"group": "blocked", "name": "X"}, availability=line)
    assert blocked.availability == "" and line not in briefs.system_instruction(blocked)
    assert briefs.screening_brief(info, {}).availability == ""


@pytest.mark.asyncio
async def test_call_agent_adds_the_cached_availability_and_nothing_on_failure(application_factory):
    app = application_factory()
    calls = {"count": 0}

    async def availability():
        calls["count"] += 1
        return [window(8, (10, 0), (11, 0))], NOW

    app.calendar.availability = availability
    assert (await app.call_agent.availability()).endswith("busy 10:00–11:00; free after 11:00.")

    async def broken():
        raise RuntimeError("down")

    app.calendar.availability = broken
    assert await app.call_agent.availability() == ""

    async def off():
        return None

    app.calendar.availability = off
    assert await app.call_agent.availability() == ""


@pytest.mark.asyncio
async def test_calendar_availability_is_cached_for_ten_minutes(application_factory, monkeypatch):
    from services import calendar as calendar_module

    app = application_factory()
    calendar = app.calendar
    monkeypatch.setattr(calendar_module, "local_now", lambda: NOW)
    assert await calendar.availability() is None  # not connected
    app.secrets.set("google_calendar_refresh_token", "1//0refresh-token-value-for-tests_ABCDEFGHIJ")
    clock = {"now": 1000.0}
    calendar.monotonic = lambda: clock["now"]
    busy = AsyncMock(return_value={"busy": [
        {"start": "2026-11-08T07:00:00+08:00", "end": "2026-11-08T07:30:00+08:00"},
        {"start": "2026-11-08T10:00:00+08:00", "end": "2026-11-08T11:00:00+08:00"},
    ]})
    calendar.busy = busy
    intervals, now = await calendar.availability()
    assert now == NOW and [begin.hour for begin, _end in intervals] == [10]  # the past one dropped
    start, end = busy.await_args.args
    assert start == NOW.replace(hour=0, minute=0) and end - start == dt.timedelta(days=1)
    clock["now"] += 599
    await calendar.availability()
    assert busy.await_count == 1
    clock["now"] += 2
    await calendar.availability()
    assert busy.await_count == 2
    app.settings["calendar"] = {"share_free_busy": False}
    assert await calendar.availability() is None and busy.await_count == 2


@pytest.mark.asyncio
async def test_a_morning_briefing_call_reads_it_after_the_pin_and_skips_triage(application_factory):
    from tests.test_call_agent import Line, connect, finish, opened, outbound_session
    from tests.test_call_agent import phone as phone_fixture

    app = phone_fixture.__wrapped__(application_factory)
    app.secrets.values["call_briefing_pin"] = "4321"
    brief = briefs.morning_briefing_brief("Good morning, Hiro. You've Dentist, Dr Lim at ten.",
                                          owner_number=OWNER_NUMBER, owner_name="Hiro")
    task, live = await connect(app, outbound_session(Line(), {"owner": True}), brief)
    await opened(app, live)
    assert TITLE_A not in live.config.system_instruction
    assert [item.name for item in live.config.tools[0].function_declarations] == ["verify_pin", "end_call"]
    live.tool("verify_pin", {"pin": "4321"}, "right")
    await until(lambda: live.tool_responses)
    assert TITLE_A in live.response("right")["briefing"]
    result = await finish(app, task, live)
    record = app.call_agent.records.get(result.record_id)
    assert result.mode == "morning_briefing" and result.outcome["status"] == "delivered"
    assert record["triage_state"] == "skipped" and app.call_agent.provider.calls == []
    assert app.call_orchestrator.list_calls("needs_you", 50) == []
