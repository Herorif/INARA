"""S7.1 signals (docs/SIGNALS.md): the Signal shape, the hub and the first producers.

A fake clock, a manual sleep and fake calendar / weather / call / job / battery sources; no
network, no real battery reads and no real waits beyond a few milliseconds.
"""

import asyncio
import dataclasses
import datetime as dt
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from core.event_bus import Event, EventBus
from services.signals import (
    KINDS,
    PENDING_LIMIT,
    BatteryProducer,
    CalendarProducer,
    CallsProducer,
    JobsProducer,
    PollingProducer,
    Signal,
    SignalHub,
    SignalProducers,
    WeatherProducer,
    signal,
)

KL = ZoneInfo("Asia/Kuala_Lumpur")
START = dt.datetime(2026, 11, 15, 9, 0, tzinfo=KL)
MARKER = "SIGNAL-MARKER-4kz Aisyah's secret"


class Clock:
    def __init__(self, now=START):
        self.value = now

    def __call__(self):
        return self.value

    def set(self, hour, minute, second=0):
        self.value = self.value.replace(hour=hour, minute=minute, second=second)

    def advance(self, **delta):
        self.value += dt.timedelta(**delta)


class Ticker:
    """A manual sleep: each call waits until the test releases one tick."""

    def __init__(self):
        self.waits = []
        self.gate = asyncio.Event()

    async def __call__(self, seconds):
        self.waits.append(seconds)
        self.gate.clear()
        await self.gate.wait()

    def tick(self):
        self.gate.set()


async def until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(0.005)


def fake_app(**extra):
    return SimpleNamespace(bus=EventBus(), resources=SimpleNamespace(state="chat"), **extra)


def hub_for(app=None, clock=None):
    app = app or fake_app()
    clock = clock or Clock()
    return app, SignalHub(app, now=clock), clock


def accepted(hub):
    """Every signal the hub accepted, kept even after it expires from the pending list."""
    kept, publish = [], hub.publish

    def spy(item):
        ok = publish(item)
        if ok:
            kept.append(item)
        return ok

    hub.publish = spy
    return kept


def make(key="k", clock=None, minutes=10, **fields):
    at = clock() if clock else START
    return signal(fields.pop("kind", "calendar.soon"), fields.pop("source", "test"),
                  fields.pop("title", "Title"), at=at, dedupe_key=key,
                  ttl=dt.timedelta(minutes=minutes), **fields)


# --- the Signal shape --------------------------------------------------------------------------


def test_signal_validates_kind_urgency_times_and_freezes_data():
    item = make(data={"event_id": "e1"}, urgency=2)
    assert item.kind in KINDS and item.urgency == 2 and item.person_id is None
    assert item.expires_at == START + dt.timedelta(minutes=10)
    with pytest.raises(TypeError):
        item.data["event_id"] = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.title = "changed"
    assert item.as_dict()["data"] == {"event_id": "e1"}
    with pytest.raises(ValueError):
        make(kind="calendar.later")
    for bad in (-1, 4, True, 1.5):
        with pytest.raises(ValueError):
            make(urgency=bad)
    with pytest.raises(ValueError):
        signal("call.missed", "calls", "x", at=START.replace(tzinfo=None), dedupe_key="k")
    with pytest.raises(ValueError):
        make(key="")
    assert set(KINDS) == {
        "calendar.soon", "weather.rain_soon", "call.missed", "call.vip", "message.received",
        "job.finished", "home.state", "home.alert", "homelab.alert", "system.battery",
        "routine.due",
    }


# --- the hub -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedupe_holds_for_the_signals_lifetime_then_frees_the_key():
    _app, hub, clock = hub_for()
    assert hub.publish(make("calendar:e1:30", clock)) is True
    assert hub.publish(make("calendar:e1:30", clock, title="Again")) is False
    assert [item.title for item in hub.pending()] == ["Title"]
    clock.advance(minutes=11)  # the first one expired: the key is free again
    assert hub.pending() == []
    assert hub.publish(make("calendar:e1:30", clock)) is True


@pytest.mark.asyncio
async def test_expired_signals_are_dropped():
    _app, hub, clock = hub_for()
    stale = signal("call.missed", "calls", "Old", at=clock() - dt.timedelta(hours=2),
                   dedupe_key="old", ttl=dt.timedelta(hours=1))
    assert hub.publish(stale) is False and hub.pending() == []
    with pytest.raises(TypeError):
        hub.publish({"kind": "call.missed"})


@pytest.mark.asyncio
async def test_pending_keeps_the_newest_hundred_and_ack_removes_one():
    _app, hub, clock = hub_for()
    for index in range(PENDING_LIMIT + 5):
        assert hub.publish(make(f"k{index}", clock, title=f"T{index}"))
    pending = hub.pending()
    assert len(pending) == PENDING_LIMIT == 100
    assert pending[0].dedupe_key == "k5" and pending[-1].dedupe_key == "k104"
    assert hub.ack("k50") is True and hub.ack("k50") is False and hub.ack("nope") is False
    assert "k50" not in [item.dedupe_key for item in hub.pending()]
    assert hub.publish(make("k50", clock)) is False  # acknowledged is not forgotten


@pytest.mark.asyncio
async def test_publishes_on_the_bus_under_signal_and_signal_kind():
    app, hub, clock = hub_for()
    seen = []

    async def record(event):
        seen.append((event.type, event.data["signal"], event.source))

    app.bus.on("signal", record)
    app.bus.on("signal.call.vip", record)
    app.bus.on("signal.calendar.soon", record)
    item = make("vip:1", clock, kind="call.vip", urgency=2)
    hub.publish(item)
    hub.publish(make("vip:1", clock, kind="call.vip"))  # a repeat goes nowhere
    await app.bus.drain()
    assert sorted(seen, key=lambda entry: entry[0]) == [
        ("signal", item, "signals"), ("signal.call.vip", item, "signals"),
    ]


# --- calendar ----------------------------------------------------------------------------------


def calendar_producer(events, clock):
    app, hub, _ = hub_for(clock=clock)
    calls = []

    async def today():
        calls.append(clock())
        return "connected", events

    return CalendarProducer(app, hub, events=today), hub, calls


@pytest.mark.asyncio
async def test_calendar_soon_fires_at_t30_and_t10_exactly_once_per_event():
    clock = Clock(START.replace(hour=9, minute=20))
    events = [
        {"title": "Design review", "date": "2026-11-15", "all_day": False, "start": "10:00",
         "end": "11:00", "location": "Room 4"},
        {"title": "Holiday", "date": "2026-11-15", "all_day": True, "start": None, "end": None},
        {"title": "Broken", "date": "nope", "all_day": False, "start": "10:00"},
    ]
    producer, hub, calls = calendar_producer(events, clock)
    signals = accepted(hub)
    for minute in range(20, 66):  # 09:20 to 10:05, once a minute, 10 s past
        clock.value = START.replace(hour=9, minute=0, second=10) + dt.timedelta(minutes=minute)
        await producer.tick()
    assert hub.pending() == []  # both expired when the event started
    assert [(item.urgency, item.title) for item in signals] == [
        (1, "Design review in 30 minutes"), (2, "Design review in 10 minutes"),
    ]
    first, second = signals
    assert first.kind == "calendar.soon" and first.source == "calendar"
    assert first.data["start"] == "2026-11-15T10:00:00+08:00"
    assert first.data["location"] == "Room 4" and first.data["event_id"] == second.data["event_id"]
    assert first.dedupe_key.endswith(":30") and second.dedupe_key.endswith(":10")
    assert first.expires_at == START.replace(hour=10)
    assert len(calls) < 15  # events are re-read every 5 minutes, not every tick


@pytest.mark.asyncio
async def test_calendar_event_first_seen_inside_ten_minutes_gets_only_t10():
    clock = Clock(START.replace(hour=9, minute=55))
    events = [{"title": "Standup", "date": "2026-11-15", "all_day": False, "start": "10:00"}]
    producer, hub, _ = calendar_producer(events, clock)
    await producer.tick()
    clock.advance(minutes=1)
    await producer.tick()
    assert [(item.urgency, item.title) for item in hub.pending()] == [(2, "Standup in 5 minutes")]


@pytest.mark.asyncio
async def test_calendar_not_connected_reads_nothing():
    clock = Clock(START.replace(hour=9, minute=40))
    app, hub, _ = hub_for(clock=clock)

    async def today():
        return "not_connected", None

    producer = CalendarProducer(app, hub, events=today)
    assert await producer.tick() == 0 and hub.pending() == []


# --- weather -----------------------------------------------------------------------------------


class FakeWeather:
    def __init__(self, home=True):
        self.home, self.answers, self.calls = home, [], []

    def home_place(self):
        return {"name": MARKER, "lat": 3.1, "lon": 101.7} if self.home else None

    async def rain_soon(self, now=None):
        self.calls.append(now)
        return self.answers.pop(0)


def rain(start_hour, end_hour, chance=80):
    return {"rain": True, "start": START.replace(hour=start_hour),
            "end": START.replace(hour=end_hour), "probability": chance, "precipitation": 1.2}


@pytest.mark.asyncio
async def test_weather_rain_soon_once_per_spell():
    clock = Clock(START.replace(hour=14, minute=10))
    weather = FakeWeather()
    app, hub, _ = hub_for(fake_app(weather=weather), clock)
    producer = WeatherProducer(app, hub)
    signals = accepted(hub)
    weather.answers = [
        rain(15, 16),                 # 14:10: rain from 15:00
        rain(15, 17),                 # 14:25: the same spell, longer
        rain(16, 17),                 # 15:40 (ongoing; the window now starts at 16:00)
        {"rain": False},              # 17:10: dry, spell over
        rain(19, 20, chance=None),    # 17:40: a new spell
        {"error": "unavailable"},     # failures say nothing
    ]
    for hour, minute in ((14, 10), (14, 25), (15, 40), (17, 10), (17, 40), (18, 0)):
        clock.set(hour, minute)
        await producer.tick()
    assert [(item.kind, item.urgency, item.title) for item in signals] == [
        ("weather.rain_soon", 1, "Rain expected at home around 15:00"),
        ("weather.rain_soon", 1, "Rain expected at home around 19:00"),
    ]
    assert signals[0].body == "80% chance of rain" and signals[1].body == ""
    assert signals[0].dedupe_key == "weather.rain_soon:2026-11-15:15"
    assert len(weather.calls) == 6


@pytest.mark.asyncio
async def test_weather_without_home_place_asks_nothing():
    weather = FakeWeather(home=False)
    app, hub, _ = hub_for(fake_app(weather=weather))
    assert await WeatherProducer(app, hub).tick() == 0
    assert weather.calls == [] and hub.pending() == []


HOURLY = {
    "latitude": 3.125, "longitude": 101.6875, "timezone": "Asia/Kuala_Lumpur",
    "utc_offset_seconds": 28800,
    "hourly_units": {"time": "iso8601", "precipitation_probability": "%", "precipitation": "mm"},
    "hourly": {
        "time": ["2026-11-15T14:00", "2026-11-15T15:00", "2026-11-15T16:00"],
        "precipitation_probability": [10, 75, 90],
        "precipitation": [0.0, 0.3, 2.4],
    },
}


def weather_service(settings, handler):
    from services.weather import WeatherService

    app = SimpleNamespace(settings=settings, dispatcher=SimpleNamespace(register=lambda spec: None))
    return WeatherService(app, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_weather_service_rain_soon_reads_two_hours_of_hourly_data():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=HOURLY)

    settings = {"assistant": {"home_place": {"name": "Kuala Lumpur", "lat": 3.14, "lon": 101.69}}}
    service = weather_service(settings, handler)
    result = await service.rain_soon(START.replace(hour=14, minute=20))
    assert result == {
        "rain": True, "start": START.replace(hour=15), "end": START.replace(hour=17),
        "probability": 90, "precipitation": 2.7,
    }
    params = requests[0].url.params
    assert params["hourly"] == "precipitation_probability,precipitation"
    assert params["forecast_hours"] == "3" and "daily" not in params and "current" not in params
    assert "Kuala" not in str(requests[0].url)  # coordinates only
    # Cached: a second look inside 10 minutes makes no request; 13:00 sees no rain yet.
    assert (await service.rain_soon(START.replace(hour=13)))["rain"] is False
    assert len(requests) == 1
    assert (await weather_service({}, handler).rain_soon())["need_place"] is True

    def broken(request):
        raise httpx.ConnectError("no route to " + MARKER)

    failing = weather_service(settings, broken)
    assert await failing.rain_soon(START) == {"error": "unavailable"}


# --- calls -------------------------------------------------------------------------------------


class FakeRecords:
    def __init__(self):
        self.items = {}

    def get(self, record_id):
        return self.items.get(record_id)


def call_record(record_id, *, state="completed", group=None, contact=None, direction="inbound",
                triage=None, mode="screening"):
    return {
        "id": record_id, "source": "twilio", "direction": direction, "mode": mode,
        "state": state, "caller_group": group, "contact_id": contact,
        "triage": triage, "triage_state": "done" if triage else "pending",
    }


def calls_setup():
    records = FakeRecords()
    people = {"p-vip": {"id": "p-vip", "name": "Aisyah"}, "p-known": {"id": "p-known", "name": "Ravi"}}
    app = fake_app(call_agent=SimpleNamespace(records=records),
                   contacts=SimpleNamespace(by_id=people.get))
    app, hub, clock = hub_for(app)
    return app, hub, records, CallsProducer(app, hub)


@pytest.mark.asyncio
async def test_call_missed_and_vip_mapping_with_person_ids():
    app, hub, records, producer = calls_setup()
    records.items = {
        "missed-unknown": call_record("missed-unknown", state="missed"),
        "missed-known": call_record("missed-known", state="failed", group="known", contact="p-known"),
        "vip": call_record("vip", group="vip", contact="p-vip",
                           triage={"summary": "Wants to move dinner to 8."}),
        "vip-missed": call_record("vip-missed", state="missed", group="vip", contact="p-vip"),
        "screened": call_record("screened", group="known", contact="p-known"),
        "outbound": call_record("outbound", state="missed", direction="outbound"),
        "blocked": call_record("blocked", state="missed", group="blocked"),
        "spam": call_record("spam", triage={"spam": True}),
        "task": call_record("task", state="missed", mode="task"),
    }
    producer.start()
    for record_id in records.items:
        await app.bus.emit(Event(type="call_record_ready", data={"record_id": record_id}))
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": "vip", "vip": True}))
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": "absent"}))
    await app.bus.emit(Event(type="call_record_ready", data={}))
    got = [(item.kind, item.urgency, item.title, item.person_id, item.body) for item in hub.pending()]
    assert got == [
        ("call.missed", 1, "Missed call", None, ""),
        ("call.missed", 1, "Missed call from Ravi", "p-known", ""),
        ("call.vip", 2, "Aisyah called", "p-vip", "Wants to move dinner to 8."),
        ("call.vip", 2, "Missed call from Aisyah", "p-vip", ""),
    ]
    assert hub.pending()[2].data == {"record_id": "vip", "missed": False, "group": "vip"}
    await producer.stop()
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": "missed-unknown"}))
    assert app.bus._handlers["call_record_ready"] == []


# --- jobs --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_finished_for_cad_images_and_web_failures_are_urgent():
    cad_previous, image_previous = AsyncMock(), AsyncMock()
    report = {"text": "page"}

    async def runner(args):
        if args == "fail":
            raise RuntimeError("bad page " + MARKER)
        if args == "cancel":
            raise asyncio.CancelledError()
        return report

    design = SimpleNamespace(job={"request_id": "cad-live"})
    app = fake_app(cad=SimpleNamespace(on_update=cad_previous),
                   images=SimpleNamespace(on_update=image_previous),
                   browser=SimpleNamespace(runner=runner),
                   live_design=SimpleNamespace(designs={"owner": design}))
    app, hub, _ = hub_for(app)
    producer = JobsProducer(app, hub)
    await app.cad.on_update("owner", {"request_id": "early", "state": "succeeded"})
    assert hub.pending() == []  # not started yet
    producer.start()
    await app.cad.on_update("owner", {"request_id": "c1", "state": "running"})
    await app.cad.on_update("owner", {"request_id": "c1", "state": "succeeded", "project": "Desk"})
    await app.cad.on_update("owner", {"request_id": "c1", "state": "succeeded"})  # repeat
    await app.cad.on_update("owner", {"request_id": "cad-live", "state": "succeeded"})
    await app.images.on_update("owner", {"request_id": "i1", "state": "failed", "error": MARKER})
    await app.images.on_update("owner", {"request_id": "i2", "state": "cancelled"})
    await app.images.on_update("owner", {"request_id": "i3", "state": "interrupted"})
    assert await app.browser.runner("ok") is report
    with pytest.raises(RuntimeError):
        await app.browser.runner("fail")
    with pytest.raises(asyncio.CancelledError):
        await app.browser.runner("cancel")
    got = [(item.source, item.urgency, item.title) for item in hub.pending()]
    assert got == [
        ("cad", 1, "CAD build finished"),
        ("cad", 1, "CAD build finished"),
        ("image", 2, "Image generation failed"),
        ("web", 1, "Web inspection finished"),
        ("web", 2, "Web inspection failed"),
    ]
    pending = hub.pending()
    assert all(item.kind == "job.finished" for item in pending)
    assert pending[0].data == {"job": "cad", "request_id": "c1", "state": "succeeded",
                               "project": "Desk", "live": False}
    assert pending[1].data["live"] is True
    assert cad_previous.await_count == 5 and image_previous.await_count == 3
    await producer.stop()
    await app.cad.on_update("owner", {"request_id": "c9", "state": "failed"})
    assert len(hub.pending()) == 5


# --- battery -----------------------------------------------------------------------------------


class FakePsutil:
    def __init__(self):
        self.battery = None

    def set(self, percent, plugged=False):
        self.battery = SimpleNamespace(percent=percent, power_plugged=plugged, secsleft=-1)

    def sensors_battery(self):
        return self.battery


@pytest.mark.asyncio
async def test_battery_warns_at_20_and_10_percent_once_per_discharge():
    ps = FakePsutil()
    app, hub, clock = hub_for()
    producer = BatteryProducer(app, hub, psutil=ps)
    readings = [None, (30, True), (15, True), (25, False), (20, False), (18, False),
                (10, False), (7, False), (50, True), (19, False), (4, False)]
    for reading in readings:
        if reading is None:
            ps.battery = None
        else:
            ps.set(*reading)
        await producer.tick()
        clock.advance(minutes=2)
    got = [(item.urgency, item.title, item.data["threshold"]) for item in hub.pending()]
    assert got == [
        (1, "Battery at 20%", 20), (2, "Battery at 10%", 10),
        (1, "Battery at 19%", 20), (2, "Battery at 4%", 10),
    ]
    assert all(item.kind == "system.battery" for item in hub.pending())


@pytest.mark.asyncio
async def test_battery_dropping_past_both_thresholds_gives_only_the_urgent_one():
    ps = FakePsutil()
    app, hub, _ = hub_for()
    producer = BatteryProducer(app, hub, psutil=ps)
    ps.set(9)
    await producer.tick()
    ps.set(8)
    await producer.tick()
    assert [(item.urgency, item.data["threshold"]) for item in hub.pending()] == [(2, 10)]


# --- lifecycle ---------------------------------------------------------------------------------


class Counting(PollingProducer):
    name = "counting"
    interval = 5.0
    first_delay = 1.0

    def __init__(self, *args, fail=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.ticks, self.fail = 0, fail

    async def tick(self):
        self.ticks += 1
        if self.fail:
            raise RuntimeError(MARKER)


@pytest.mark.asyncio
async def test_gaming_mode_pauses_polling_producers():
    app, hub, _ = hub_for()
    ticker = Ticker()
    producer = Counting(app, hub, sleep=ticker)
    producer.start()
    await until(lambda: len(ticker.waits) == 1)
    assert ticker.waits == [1.0]
    ticker.tick()
    await until(lambda: len(ticker.waits) == 2)
    assert producer.ticks == 1
    app.resources.state = "gaming"
    for count in (3, 4):
        ticker.tick()
        await until(lambda count=count: len(ticker.waits) == count)
    assert producer.ticks == 1  # no polling while gaming
    app.resources.state = "resident"  # resident (tray) mode keeps watching
    ticker.tick()
    await until(lambda: len(ticker.waits) == 5)
    assert producer.ticks == 2 and ticker.waits[1:] == [5.0] * 4
    await producer.stop()
    assert producer.task is None and not producer.running


@pytest.mark.asyncio
async def test_producers_start_once_and_stop_cleanly_even_after_failures(caplog):
    caplog.set_level(logging.DEBUG)
    records = FakeRecords()
    app = fake_app(call_agent=SimpleNamespace(records=records), contacts=None)
    app, hub, _ = hub_for(app)
    ticker = Ticker()
    failing = Counting(app, hub, sleep=ticker, fail=True)
    calls = CallsProducer(app, hub)
    jobs = JobsProducer(app, hub)
    producers = SignalProducers(app, hub, [failing, calls, jobs])
    producers.start()
    task = failing.task
    producers.start()  # idempotent
    assert failing.task is task
    assert len(app.bus._handlers["call_record_ready"]) == 1 and jobs.active
    await until(lambda: len(ticker.waits) == 1)
    ticker.tick()
    await until(lambda: len(ticker.waits) == 2)
    assert failing.ticks == 1 and failing.running  # a failing tick keeps the loop alive
    await producers.stop()
    assert task.done() and app.bus._handlers["call_record_ready"] == [] and not jobs.active
    await producers.stop()  # twice is fine
    assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_application_starts_and_stops_its_producers(application_factory):
    runtime = application_factory()
    producers = runtime.signal_producers
    assert [item.name for item in producers.producers] == [
        "calendar", "weather", "battery", "calls", "jobs"]
    await runtime.start()
    polling = [item for item in producers.producers if isinstance(item, PollingProducer)]
    assert all(item.running for item in polling) and producers.get("jobs").active
    assert runtime.bus._handlers.get("call_record_ready")
    await runtime.close()
    assert not any(item.running for item in polling) and not producers.get("jobs").active
    assert not producers.get("calls").subscribed


# --- privacy -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_titles_bodies_names_or_places_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    clock = Clock(START.replace(hour=9, minute=52))
    events = [{"title": MARKER, "date": "2026-11-15", "all_day": False, "start": "10:00",
               "location": MARKER}]
    producer, hub, _ = calendar_producer(events, clock)
    await producer.tick()
    app, calls_hub, records, calls = calls_setup()
    records.items["r"] = call_record("r", group="vip", contact="p-vip",
                                     triage={"summary": MARKER})
    calls.consider({"record_id": "r"})
    hub.publish(make("private", clock, title=MARKER, body=MARKER, data={"note": MARKER}))
    stale = signal("call.missed", "calls", MARKER, at=clock() - dt.timedelta(days=1),
                   dedupe_key="stale", body=MARKER)
    hub.publish(stale)
    assert len(hub.pending()) == 2 and len(calls_hub.pending()) == 1
    assert "Signal calendar.soon from calendar (urgency 2)" in caplog.text
    assert MARKER not in caplog.text and "Aisyah" not in caplog.text


# --- the owner-only route ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signals_pending_route_is_owner_only_and_lists_newest_first(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "second": "other", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "second": "renderer", "tray": "resident"})
    now = dt.datetime.now(dt.timezone.utc)
    app.signals.publish(signal("call.missed", "calls", "Missed call", at=now, dedupe_key="a"))
    app.signals.publish(signal("job.finished", "cad", "CAD build finished", at=now,
                               dedupe_key="b", urgency=2))
    handler = app.sio.handlers["/"]["signals_pending"]
    result = await handler("client", {})
    assert result == {"ok": True, "signals": [
        {"title": "CAD build finished", "kind": "job.finished", "urgency": 2, "at": now.isoformat()},
        {"title": "Missed call", "kind": "call.missed", "urgency": 1, "at": now.isoformat()},
    ]}
    assert (await handler("client", None))["ok"] is True
    assert (await handler("client", {"extra": 1}))["code"] == "invalid_arguments"
    assert (await handler("second", {}))["code"] == "permission_denied"
    assert (await handler("tray", {}))["code"] == "authentication_required"
    assert (await handler("unknown", {}))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = True
    assert (await handler("client", {}))["code"] == "authentication_required"


def test_signals_pending_is_in_the_route_policy_matrix():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text(
            encoding="utf-8")
    )
    entry = matrix["socket_routes"]["signals_pending"]
    assert entry["status"] == "implemented" and entry["schema"] == "EmptyRequest"


def test_signal_is_a_frozen_dataclass():
    assert dataclasses.is_dataclass(Signal)
    assert Signal.__dataclass_params__.frozen
