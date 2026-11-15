"""S13a.5 Systems rail (docs/SYSTEMS_RAIL.md): PC vitals and the rail's owner-only routes.

A fake psutil, a manual sleep and fake calendar / weather / Home Assistant services; no real
sampling, network or clock waits beyond a few milliseconds.
"""

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import services.calendar as calendar_module
import services.vitals as vitals_module
from services.vitals import INTERVAL, LOW_BATTERY_INTERVAL, VitalsService, load_gpu
from transport.vitals import next_event

KL = ZoneInfo("Asia/Kuala_Lumpur")
NOW = dt.datetime(2026, 11, 15, 9, 18, tzinfo=KL)
ROUTES = ("vitals_watch", "weather_now", "agenda_next", "home_summary")
MARKER = "RAIL-MARKER-7xq Seremban"


class FakePsutil:
    def __init__(self, battery=None):
        self.sent, self.received = 1_000, 5_000
        self.cpu = 12.34
        self.battery = battery
        self.calls = []

    def cpu_percent(self, interval=None):
        self.calls.append("cpu")
        return self.cpu

    def virtual_memory(self):
        self.calls.append("mem")
        return SimpleNamespace(used=8 * 2**30, total=16 * 2**30)

    def disk_usage(self, path):
        self.calls.append(("disk", path))
        return SimpleNamespace(used=200 * 2**30, total=500 * 2**30)

    def net_io_counters(self):
        self.calls.append("net")
        return SimpleNamespace(bytes_sent=self.sent, bytes_recv=self.received)

    def sensors_battery(self):
        return self.battery


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


def owner_app(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "second": "other", "tray": "owner",
                                    "client2": "owner"})
    app.sessions.roles.update({"client": "renderer", "second": "renderer", "tray": "resident",
                               "client2": "renderer"})
    # The shipped defaults (server.py): these reads never ask.
    app.settings["tool_permissions"].update({"calendar_read": False, "home_devices": False})
    return app


def vitals_events(app):
    return [call for call in app.sio.emit.await_args_list if call.args[0] == "vitals"]


def fake_service(app, psutil=None, gpu=None, clock=lambda: 1_700_000_000.0):
    ticker = Ticker()
    times = iter(range(0, 10_000, 2))
    service = VitalsService(app, psutil=psutil or FakePsutil(), gpu=gpu, clock=clock,
                            monotonic=lambda: float(next(times)), sleep=ticker, drive="C:\\")
    app.vitals = service
    return service, ticker


# --- sampling ---------------------------------------------------------------------------------


def test_sample_shape_rates_and_no_battery_or_gpu():
    app = SimpleNamespace()
    ps = FakePsutil()
    clock = iter([0.0, 2.0])
    service = VitalsService(app, psutil=ps, gpu=None, clock=lambda: 1_700_000_000.1234,
                            monotonic=lambda: next(clock), drive="C:\\")
    service.prime()
    ps.sent += 4_000
    ps.received += 10_000
    sample = service.sample()
    assert sample == {
        "t": 1_700_000_000.123,
        "cpu": 12.3,
        "mem": {"used": 8 * 2**30, "total": 16 * 2**30},
        "disk": {"used": 200 * 2**30, "total": 500 * 2**30},
        "net": {"up": 2_000, "down": 5_000},
    }
    assert ("disk", "C:\\") in ps.calls
    assert "battery" not in sample and "gpu" not in sample


def test_battery_is_optional_and_low_battery_slows_sampling():
    app = SimpleNamespace()
    ps = FakePsutil(battery=SimpleNamespace(percent=64.0, power_plugged=True))
    service = VitalsService(app, psutil=ps, gpu=None)
    assert service.sample()["battery"] == {"percent": 64.0, "plugged": True}
    assert service.interval() == INTERVAL
    ps.battery = SimpleNamespace(percent=18.0, power_plugged=False)
    assert service.sample()["battery"] == {"percent": 18.0, "plugged": False}
    assert service.interval() == LOW_BATTERY_INTERVAL  # the core decides from its own reading
    ps.battery = SimpleNamespace(percent=None, power_plugged=None)
    assert "battery" not in service.sample()
    assert service.interval() == INTERVAL

    def broken():
        raise OSError("no battery driver")

    ps.sensors_battery = broken
    assert "battery" not in service.sample()
    bare = SimpleNamespace(**{name: getattr(ps, name) for name in (
        "cpu_percent", "virtual_memory", "disk_usage", "net_io_counters")})
    assert "battery" not in VitalsService(app, psutil=bare, gpu=None).sample()  # no sensors API


def test_gpu_is_skipped_when_nvml_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)  # import raises ImportError
    assert load_gpu() is None
    service = VitalsService(SimpleNamespace(), psutil=FakePsutil())  # gpu=... loads lazily
    assert "gpu" not in service.sample()
    assert service._gpu is None


def test_gpu_reads_nvml_when_present(monkeypatch):
    fake = SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlDeviceGetHandleByIndex=lambda index: "gpu0",
        nvmlDeviceGetUtilizationRates=lambda handle: SimpleNamespace(gpu=41),
    )
    monkeypatch.setitem(sys.modules, "pynvml", fake)
    service = VitalsService(SimpleNamespace(), psutil=FakePsutil())
    assert service.sample()["gpu"] == {"percent": 41.0}

    def failing(handle):
        raise RuntimeError("driver gone")

    fake.nvmlDeviceGetUtilizationRates = failing
    assert "gpu" not in service.sample()
    assert service._gpu is None


# --- the loop ---------------------------------------------------------------------------------


async def test_watch_on_samples_and_off_stops_the_loop(application_factory):
    app = owner_app(application_factory)
    ps = FakePsutil()
    service, ticker = fake_service(app, ps)
    handlers = app.sio.handlers["/"]
    ack = await handlers["vitals_watch"]("client", {"on": True})
    assert ack == {"ok": True, "watching": True, "paused": False, "interval": INTERVAL}
    await until(lambda: ticker.waits)
    assert ticker.waits == [INTERVAL]
    ps.sent += 2_000
    ticker.tick()
    await until(lambda: vitals_events(app))
    (call,) = vitals_events(app)
    assert call.kwargs == {"room": "client"}
    assert call.args[1]["net"]["up"] == 1_000 and call.args[1]["cpu"] == 12.3
    task = service.task
    ack = await handlers["vitals_watch"]("client", {"on": False})
    assert ack["watching"] is False
    await asyncio.gather(task, return_exceptions=True)
    assert task.done() and service.task is None
    count = len(ps.calls)
    await asyncio.sleep(0.02)
    assert len(ps.calls) == count  # nobody watches: no sampling


async def test_one_loop_for_many_watchers_and_disconnect_cleanup(application_factory):
    app = owner_app(application_factory)
    service, ticker = fake_service(app)
    handlers = app.sio.handlers["/"]
    await handlers["vitals_watch"]("client", {"on": True})
    first = service.task
    await handlers["vitals_watch"]("client2", {"on": True, "low_battery": True})
    assert service.task is first
    assert service.interval() == LOW_BATTERY_INTERVAL  # the renderer's hint
    await until(lambda: ticker.waits)
    ticker.tick()
    await until(lambda: len(vitals_events(app)) == 2)
    assert {call.kwargs["room"] for call in vitals_events(app)} == {"client", "client2"}
    await app.disconnect("client2")
    assert set(service.watchers) == {"client"}
    assert service.interval() == INTERVAL
    await app.disconnect("client")
    assert service.watchers == {}
    await asyncio.gather(first, return_exceptions=True)
    assert first.done()


async def test_a_gone_socket_is_dropped_by_the_loop(application_factory):
    app = owner_app(application_factory)
    service, ticker = fake_service(app)
    await app.sio.handlers["/"]["vitals_watch"]("client", {"on": True})
    task = service.task
    await until(lambda: ticker.waits)
    app.sessions.remove("client")  # gone without the disconnect cleanup
    ticker.tick()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
    assert service.watchers == {} and vitals_events(app) == []


async def test_gaming_mode_pauses_sampling(application_factory):
    app = owner_app(application_factory)
    ps = FakePsutil()
    service, ticker = fake_service(app, ps)
    app.resources.state = "gaming"
    ack = await app.sio.handlers["/"]["vitals_watch"]("client", {"on": True})
    assert ack["paused"] is True
    for index in range(1, 4):
        await until(lambda index=index: len(ticker.waits) >= index)
        ticker.tick()
    await until(lambda: len(ticker.waits) >= 4)
    assert ps.calls == [] and vitals_events(app) == []  # no psutil call at all
    app.resources.state = "chat"
    ticker.tick()
    await until(lambda: len(ticker.waits) >= 5)  # primed, then one interval
    ticker.tick()
    await until(lambda: vitals_events(app))
    await service.close()
    assert service.task is None


async def test_locked_owner_gets_no_samples(application_factory):
    app = owner_app(application_factory)
    service, ticker = fake_service(app)
    await app.sio.handlers["/"]["vitals_watch"]("client", {"on": True})
    await until(lambda: ticker.waits)
    app.settings["face_auth_enabled"] = True
    app.sessions.face_authenticated = lambda: False
    ticker.tick()
    await until(lambda: len(ticker.waits) >= 2)
    assert vitals_events(app) == [] and "client" in service.watchers
    await service.close()


async def test_close_stops_the_loop(application_factory):
    app = owner_app(application_factory)
    service, ticker = fake_service(app)
    await app.sio.handlers["/"]["vitals_watch"]("client", {"on": True})
    task = service.task
    await app.close()
    assert task.done() and service.watchers == {}


async def test_nothing_is_logged_about_values(application_factory, caplog):
    app = owner_app(application_factory)
    ps = FakePsutil(battery=SimpleNamespace(percent=77.7, power_plugged=False))
    service, ticker = fake_service(app, ps)
    caplog.set_level(logging.DEBUG)
    await app.sio.handlers["/"]["vitals_watch"]("client", {"on": True})
    await until(lambda: ticker.waits)
    ticker.tick()
    await until(lambda: vitals_events(app))
    await service.close()
    text = caplog.text
    assert "77.7" not in text and "12.3" not in text and str(8 * 2**30) not in text


# --- routes -----------------------------------------------------------------------------------


async def test_rail_routes_are_owner_only(application_factory):
    app = owner_app(application_factory)
    service, _ticker = fake_service(app)
    handlers = app.sio.handlers["/"]
    valid = {"vitals_watch": {"on": True}}
    for name in ROUTES:
        for sid, code in (("unknown", "authentication_required"),
                          ("tray", "authentication_required"),
                          ("second", "permission_denied")):
            result = await handlers[name](sid, valid.get(name, {}))
            assert result["ok"] is False and result["code"] == code, (name, sid, result)
        assert (await handlers[name]("client", {"extra": 1}))["code"] == "invalid_arguments"
    assert service.watchers == {} and service.task is None
    for bad in ({}, {"on": "yes"}, {"on": 1}, {"on": True, "low_battery": "no"}):
        assert (await handlers["vitals_watch"]("client", bad))["code"] == "invalid_arguments"
    app.settings["face_auth_enabled"] = True
    for name in ROUTES:
        result = await handlers[name]("client", valid.get(name, {}))
        assert result["code"] == "authentication_required", name
    assert service.watchers == {}


def test_rail_routes_are_in_the_route_policy_matrix():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text(
            encoding="utf-8")
    )
    for name in ROUTES:
        assert matrix["socket_routes"][name]["status"] == "implemented"


class FakeWeather:
    def __init__(self, home=True, result=None):
        self.home, self.result, self.calls = home, result, []

    def home_place(self):
        return {"name": MARKER, "lat": 2.7, "lon": 101.9} if self.home else None

    async def lookup(self, place=None, when="today"):
        self.calls.append((place, when))
        return dict(self.result)


WEATHER = {
    "place": {"name": MARKER, "country": "", "lat": 2.7, "lon": 101.9},
    "when": "now",
    "now": {"temp": 31.2, "feels_like": 36.1, "humidity": 70, "precipitation": 0.0,
            "condition": "light rain", "wind_kmh": 9.0},
    "days": [],
    "units": {},
    "source": "Open-Meteo",
}


async def test_weather_now(application_factory, caplog):
    app = owner_app(application_factory)
    handlers = app.sio.handlers["/"]
    app.weather = FakeWeather(home=False)
    assert await handlers["weather_now"]("client", {}) == {"ok": True, "home": False}
    assert app.weather.calls == []  # no home town: no lookup
    app.weather = FakeWeather(result=WEATHER)
    caplog.set_level(logging.DEBUG)
    result = await handlers["weather_now"]("client", {})
    assert result == {"ok": True, "home": True,
                      "line": f"{MARKER}: 31°C, feels like 36, light rain.",
                      "temp": 31.2, "condition": "light rain"}
    assert app.weather.calls == [(None, "now")]
    app.weather = FakeWeather(result={"need_place": True})
    assert await handlers["weather_now"]("client") == {"ok": True, "home": False}
    app.weather = FakeWeather(result={"error": "unavailable", "message": "The weather service is busy."})
    result = await handlers["weather_now"]("client", {})
    assert result == {"ok": False, "code": "weather_unavailable",
                      "message": "The weather service is busy."}
    assert MARKER not in caplog.text


class FakeCalendar:
    connected = True

    def __init__(self, events, read=True):
        self.events, self.read = events, read

    def switches(self):
        return {"read_events": self.read}

    async def today_events(self):
        return {"time_zone": "Asia/Kuala_Lumpur", "events": self.events, "truncated": False}


EVENTS = [
    {"title": "Standup", "date": "2026-11-15", "start": "09:00", "end": "09:15", "all_day": False,
     "location": "Room 4", "attendees": ["a@example.com"], "description": "secret notes"},
    {"title": "Public holiday", "date": "2026-11-15", "all_day": True},
    {"title": f"Design review {MARKER}", "date": "2026-11-15", "start": "10:00", "end": "11:00",
     "all_day": False, "location": "Seremban office"},
    {"title": "Lunch", "date": "2026-11-15", "start": "12:30", "end": "13:30", "all_day": False},
]


async def test_agenda_next_titles_and_times_only(application_factory, monkeypatch, caplog):
    app = owner_app(application_factory)
    monkeypatch.setattr(calendar_module, "local_now", lambda: NOW)
    handlers = app.sio.handlers["/"]
    app.calendar = SimpleNamespace(connected=False)
    result = await handlers["agenda_next"]("client", {})
    assert result == {"ok": True, "calendar": "not_connected", "event": None, "reminders": None}
    app.calendar = FakeCalendar(EVENTS)
    app.reminders.add_reminder(f"Call the bank {MARKER}", NOW.replace(hour=15, minute=0).timestamp())
    app.reminders.add_reminder("Water the plants", NOW.replace(hour=18, minute=0).timestamp())
    app.reminders.add_reminder("Next week", (NOW + dt.timedelta(days=7)).timestamp())
    caplog.set_level(logging.DEBUG)
    result = await handlers["agenda_next"]("client", {})
    at = int(NOW.replace(hour=10, minute=0).timestamp())
    assert result == {
        "ok": True,
        "calendar": "connected",
        "event": {"title": f"Design review {MARKER}", "time": "10:00", "at": at},
        "reminders": {"count": 2, "first": {"title": f"Call the bank {MARKER}", "time": "15:00"}},
    }
    text = json.dumps(result)
    for private in ("Room 4", "Seremban office", "secret notes", "a@example.com"):
        assert private not in text
    assert MARKER not in caplog.text
    app.calendar = FakeCalendar(EVENTS, read=False)
    result = await handlers["agenda_next"]("client", {})
    assert result["calendar"] == "off" and result["event"] is None
    app.settings["tool_permissions"]["list_reminders"] = "deny"
    assert (await handlers["agenda_next"]("client", {}))["reminders"] is None


def test_next_event_skips_started_all_day_and_other_days():
    events = [
        {"title": "Started", "date": "2026-11-15", "start": "09:00", "all_day": False},
        {"title": "All day", "date": "2026-11-15", "all_day": True},
        {"title": "Tomorrow", "date": "2026-11-16", "start": "08:00", "all_day": False},
        {"title": "Bad time", "date": "2026-11-15", "start": "9am", "all_day": False},
        {"title": "", "date": "2026-11-15", "start": "17:45", "all_day": False},
        "not a dict",
    ]
    assert next_event(events, NOW) == {
        "title": "(No title)", "time": "17:45",
        "at": int(NOW.replace(hour=17, minute=45).timestamp()),
    }
    assert next_event(events[:4], NOW) is None
    assert next_event(None, NOW) is None


async def test_home_summary(application_factory, caplog):
    app = owner_app(application_factory)
    handlers = app.sio.handlers["/"]
    app.home = SimpleNamespace(connected=False)
    assert await handlers["home_summary"]("client", {}) == {
        "ok": True, "connected": False, "line": None}

    async def list_for_brain():
        return {"devices": [
            {"name": f"Desk lamp {MARKER}", "domain": "light", "state": "On"},
            {"name": "Front door", "domain": "lock", "state": "Locked"},
            {"name": "Safe", "room": "Study"},  # off limits
        ]}

    app.home = SimpleNamespace(connected=True, list_for_brain=list_for_brain)
    caplog.set_level(logging.DEBUG)
    result = await handlers["home_summary"]("client", {})
    assert result == {"ok": True, "connected": True,
                      "line": "At home: 1 of 1 light on, the lock is locked."}
    assert MARKER not in caplog.text
    app.settings["tool_permissions"]["home_devices"] = "deny"
    assert await handlers["home_summary"]("client", {}) == {
        "ok": True, "connected": True, "line": None}


def test_system_drive(monkeypatch):
    monkeypatch.setattr(vitals_module.sys, "platform", "win32")
    monkeypatch.setenv("SystemDrive", "D:")
    assert vitals_module.system_drive() == "D:\\"
    monkeypatch.setattr(vitals_module.sys, "platform", "linux")
    assert vitals_module.system_drive() == "/"
