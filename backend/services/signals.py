"""Signals (S7.1, docs/SIGNALS.md): one normalised shape for everything worth telling the owner.

Producers turn their sources (the calendar, the weather at the home town, call records,
finished jobs, the battery) into a ``Signal`` and hand it to ``SignalHub.publish``. The hub
drops expired signals, drops a repeat of a ``dedupe_key`` while the first one is still
live, keeps a small pending list (at most ``PENDING_LIMIT``, newest kept) and publishes on
``app.bus`` under ``signal`` and ``signal.<kind>`` with ``data={"signal": Signal}``.

Nothing here tells the owner anything: delivery (scoring, presence, quiet hours) is the
proactive engine's job (S7.2). Logs carry the kind, the source and the urgency only, never
a title, a body, a place, a name or any ``data`` value.

Polling producers (calendar, weather, battery) sleep through gaming mode; the event
producers (calls, jobs) only react to events that already happened.
"""

import asyncio
import datetime as dt
import hashlib
import math
from dataclasses import dataclass, field
from types import MappingProxyType

from core.event_bus import Event
from services.log import get_logger

logger = get_logger(__name__)

KINDS = (
    "calendar.soon",
    "weather.rain_soon",
    "call.missed",
    "call.vip",
    "message.received",
    "job.finished",
    "home.state",
    "home.alert",
    "homelab.alert",
    "system.battery",
    "routine.due",
)
TOPIC = "signal"
PENDING_LIMIT = 100
SEEN_LIMIT = 2048
TITLE_LIMIT = 160
BODY_LIMIT = 500

UTC = dt.timezone.utc


def utc_now():
    return dt.datetime.now(UTC)


def _aware(value, name):
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Signal {name} must be an aware datetime")
    return value


def _line(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Signal:
    """One thing that happened. ``urgency``: 0 FYI, 1 worth a mention, 2 soon, 3 now."""

    kind: str
    source: str
    at: dt.datetime
    title: str
    body: str
    data: MappingProxyType
    urgency: int
    dedupe_key: str
    expires_at: dt.datetime
    person_id: str | None = field(default=None)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError("Unknown signal kind")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("Signal source is required")
        if isinstance(self.urgency, bool) or self.urgency not in (0, 1, 2, 3):
            raise ValueError("Signal urgency must be 0-3")
        if not isinstance(self.dedupe_key, str) or not self.dedupe_key:
            raise ValueError("Signal dedupe_key is required")
        _aware(self.at, "at")
        _aware(self.expires_at, "expires_at")
        if self.person_id is not None and not isinstance(self.person_id, str):
            raise ValueError("Signal person_id must be a string")
        object.__setattr__(self, "title", _line(self.title, TITLE_LIMIT))
        object.__setattr__(self, "body", _line(self.body, BODY_LIMIT))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data or {})))

    def expired(self, now):
        return self.expires_at <= now

    def as_dict(self):
        return {
            "kind": self.kind,
            "source": self.source,
            "at": self.at.isoformat(),
            "title": self.title,
            "body": self.body,
            "data": dict(self.data),
            "urgency": self.urgency,
            "dedupe_key": self.dedupe_key,
            "expires_at": self.expires_at.isoformat(),
            "person_id": self.person_id,
        }


def signal(kind, source, title, *, at, dedupe_key, expires_at=None, ttl=None, urgency=1,
           body="", data=None, person_id=None):
    """A ``Signal`` with ``expires_at`` given directly or as ``at + ttl``."""
    if expires_at is None:
        expires_at = at + (ttl if ttl is not None else dt.timedelta(hours=1))
    return Signal(kind=kind, source=source, at=at, title=title, body=body, data=data or {},
                  urgency=urgency, dedupe_key=dedupe_key, expires_at=expires_at,
                  person_id=person_id)


class SignalHub:
    """Owned by the composition root (application.py)."""

    def __init__(self, app, *, now=utc_now):
        self.app = app
        self.now = now
        self._pending = []  # Signals, oldest first
        self._seen = {}  # dedupe_key -> expires_at of the signal that claimed it

    def _prune(self, now):
        self._pending = [item for item in self._pending if not item.expired(now)]
        for key in [key for key, expires in self._seen.items() if expires <= now]:
            del self._seen[key]

    def publish(self, item):
        """Accept one signal; True when it was new and live (and went out on the bus)."""
        if not isinstance(item, Signal):
            raise TypeError("SignalHub.publish takes a Signal")
        now = self.now()
        self._prune(now)
        if item.expired(now):
            logger.debug("Signal %s from %s dropped: expired", item.kind, item.source)
            return False
        if item.dedupe_key in self._seen:
            return False
        if len(self._seen) >= SEEN_LIMIT:
            del self._seen[min(self._seen, key=self._seen.get)]
        self._seen[item.dedupe_key] = item.expires_at
        self._pending.append(item)
        del self._pending[:-PENDING_LIMIT]
        logger.info("Signal %s from %s (urgency %d)", item.kind, item.source, item.urgency)
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            for topic in (TOPIC, f"{TOPIC}.{item.kind}"):
                bus.emit_nowait(Event(type=topic, data={"signal": item}, source="signals"))
        return True

    def pending(self):
        """The live, unacknowledged signals, oldest first."""
        self._prune(self.now())
        return list(self._pending)

    def ack(self, dedupe_key):
        """Take one signal off the pending list (it still will not repeat). True if found."""
        before = len(self._pending)
        self._pending = [item for item in self._pending if item.dedupe_key != dedupe_key]
        return len(self._pending) != before


# --- producers ------------------------------------------------------------------------------


class PollingProducer:
    """A producer that checks its source every ``interval`` seconds, never in gaming mode."""

    name = "poll"
    interval = 60.0
    first_delay = 30.0

    def __init__(self, app, hub, *, now=None, sleep=asyncio.sleep):
        self.app, self.hub = app, hub
        self.now = now or hub.now
        self.sleep = sleep
        self.task = None

    def gaming(self):
        return getattr(getattr(self.app, "resources", None), "state", None) == "gaming"

    @property
    def running(self):
        return self.task is not None and not self.task.done()

    def start(self):
        if not self.running:
            self.task = asyncio.create_task(self._run(), name=f"signals-{self.name}")
        return self.task

    async def stop(self):
        task, self.task = self.task, None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self):
        delay = self.first_delay
        while True:
            await self.sleep(delay)
            delay = self.interval
            if self.gaming():
                continue
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Signal producer %s failed (%s)", self.name, type(exc).__name__)

    async def tick(self):
        raise NotImplementedError


def _event_id(event):
    """A stable id for a calendar entry (the date, start and title; never logged)."""
    raw = "\n".join(str(event.get(key) or "") for key in ("date", "start", "title"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _minutes(delta):
    count = max(1, math.ceil(delta.total_seconds() / 60))
    return f"{count} minute" if count == 1 else f"{count} minutes"


class CalendarProducer(PollingProducer):
    """``calendar.soon`` at T-30 (urgency 1) and T-10 (urgency 2) for today's timed events.

    Reads today's events through ``voice_quick.today_events`` (the calendar's read switch
    and the calendar_read permission apply) at most every ``REFRESH`` seconds and checks the
    offsets every minute. An event first seen inside 10 minutes gets only the T-10 signal.
    Travel time to the event's place is not built yet (docs/SIGNALS.md)."""

    name = "calendar"
    interval = 60.0
    OFFSETS = ((30, 1), (10, 2))  # minutes before the start, urgency
    REFRESH = 300.0

    def __init__(self, app, hub, *, events=None, **options):
        super().__init__(app, hub, **options)
        self.events = events or self._today
        self._cache = None  # (fetched at, events)

    async def _today(self):
        from services import voice_quick

        return await voice_quick.today_events(self.app)

    async def _events(self, now):
        cached = self._cache
        if cached is not None and cached[0].date() == now.date() \
                and (now - cached[0]).total_seconds() < self.REFRESH:
            return cached[1]
        state, events = await self.events()
        events = list(events or ()) if state == "connected" else []
        self._cache = (now, events)
        return events

    async def tick(self):
        from services.calendar import TIMEZONE, local

        now = local(self.now())
        published = 0
        for event in await self._events(now):
            if not isinstance(event, dict) or event.get("all_day"):
                continue
            start = event.get("start")
            try:
                day = dt.date.fromisoformat(str(event.get("date")))
                clock = dt.time.fromisoformat(start) if isinstance(start, str) else None
            except ValueError:
                continue
            if clock is None:
                continue
            begin = dt.datetime.combine(day, clock, TIMEZONE)
            left = begin - now
            if left <= dt.timedelta(0):
                continue
            offset = next(
                ((minutes, urgency) for minutes, urgency in reversed(self.OFFSETS)
                 if left <= dt.timedelta(minutes=minutes)),
                None,
            )
            if offset is None:
                continue
            minutes, urgency = offset
            event_id = _event_id(event)
            data = {"event_id": event_id, "start": begin.isoformat()}
            if event.get("location"):
                data["location"] = event["location"]
            title = event.get("title") or "(No title)"
            item = signal(
                "calendar.soon", "calendar", f"{title} in {_minutes(left)}",
                at=now, expires_at=begin, urgency=urgency,
                dedupe_key=f"calendar.soon:{event_id}:{minutes}",
                body=f"Starts at {start}" + (f", {event['location']}" if data.get("location") else ""),
                data=data,
            )
            published += self.hub.publish(item)
        return published


class WeatherProducer(PollingProducer):
    """``weather.rain_soon`` (urgency 1) once per rain spell at the home town, every 15 min.

    Nothing (and no request) without ``assistant.home_place``. A spell is a run of rainy
    hours; a later poll that still sees rain continuing the same spell stays quiet."""

    name = "weather"
    interval = 900.0

    def __init__(self, app, hub, **options):
        super().__init__(app, hub, **options)
        self.spell_end = None  # end of the last rainy hour of the current spell

    async def tick(self):
        weather = getattr(self.app, "weather", None)
        if weather is None or weather.home_place() is None:
            return 0
        now = self.now()
        result = await weather.rain_soon(now)
        if not isinstance(result, dict) or result.get("error") or result.get("need_place"):
            return 0
        if not result.get("rain"):
            if self.spell_end is not None and now >= self.spell_end:
                self.spell_end = None
            return 0
        start, end = result["start"], result["end"]
        if self.spell_end is not None and start <= self.spell_end:
            self.spell_end = max(self.spell_end, end)  # the same spell continues
            return 0
        self.spell_end = end
        # Open-Meteo's hours carry the home town's own UTC offset: the time reads locally.
        if start <= now:
            title = "Rain likely at home now"
        else:
            title = f"Rain expected at home around {start:%H:%M}"
        chance = result.get("probability")
        item = signal(
            "weather.rain_soon", "weather", title,
            at=now, expires_at=max(end, now + dt.timedelta(minutes=30)), urgency=1,
            dedupe_key=f"weather.rain_soon:{start:%Y-%m-%d}:{start:%H}",
            body=f"{round(chance)}% chance of rain" if chance is not None else "",
            data={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "probability": chance,
                "precipitation": result.get("precipitation"),
            },
        )
        return int(self.hub.publish(item))


class BatteryProducer(PollingProducer):
    """``system.battery`` at 20% (urgency 1) and 10% (urgency 2) while discharging.

    Checks every 2 minutes with ``psutil``; plugging in re-arms both thresholds. A drop
    straight past both gives only the 10% signal."""

    name = "battery"
    interval = 120.0
    THRESHOLDS = ((10, 2), (20, 1))  # percent, urgency (lowest first)

    def __init__(self, app, hub, *, psutil=None, **options):
        super().__init__(app, hub, **options)
        self._psutil = psutil
        self.sent = set()
        self.run = 0  # one per discharge, so a new discharge can warn again

    @property
    def psutil(self):
        if self._psutil is None:
            import psutil

            self._psutil = psutil
        return self._psutil

    def _read(self):
        reader = getattr(self.psutil, "sensors_battery", None)
        return reader() if reader else None

    async def tick(self):
        battery = await asyncio.to_thread(self._read)
        percent = getattr(battery, "percent", None)
        if battery is None or getattr(battery, "power_plugged", None) is not False \
                or isinstance(percent, bool) or not isinstance(percent, (int, float)):
            if self.sent:
                self.sent.clear()
                self.run += 1
            return 0
        crossed = next(
            ((level, urgency) for level, urgency in self.THRESHOLDS if percent <= level), None
        )
        if crossed is None:
            return 0
        level, urgency = crossed
        if any(sent <= level for sent in self.sent):
            return 0
        self.sent.update(threshold for threshold, _u in self.THRESHOLDS if threshold >= level)
        now = self.now()
        item = signal(
            "system.battery", "battery", f"Battery at {round(percent)}%",
            at=now, ttl=dt.timedelta(minutes=30), urgency=urgency,
            dedupe_key=f"system.battery:{self.run}:{level}",
            body="Plug in the charger soon." if urgency == 1 else "Plug in the charger now.",
            data={"percent": round(percent), "threshold": level},
        )
        return int(self.hub.publish(item))


CALL_RECORD_READY = "call_record_ready"  # telephony/agent.py EVENT_RECORD_READY
CALL_TTL = dt.timedelta(hours=12)


class CallsProducer:
    """``call.missed`` (urgency 1) and ``call.vip`` (urgency 2) from ``call_record_ready``.

    Inbound screening records only; outbound calls, blocked callers and spam are skipped.
    A VIP's call (missed or not) is ``call.vip``; anyone else's missed call is
    ``call.missed``. ``person_id`` is the matched person from the people list (P1). One
    signal per record: the VIP's second announcement (after triage) is a repeat."""

    name = "calls"

    def __init__(self, app, hub, *, now=None):
        self.app, self.hub = app, hub
        self.now = now or hub.now
        self.subscribed = False

    def start(self):
        bus = getattr(self.app, "bus", None)
        if bus is not None and not self.subscribed:
            bus.on(CALL_RECORD_READY, self._record_ready)
            self.subscribed = True

    async def stop(self):
        bus = getattr(self.app, "bus", None)
        if bus is not None and self.subscribed:
            bus.off(CALL_RECORD_READY, self._record_ready)
        self.subscribed = False

    def _person(self, person_id):
        contacts = getattr(self.app, "contacts", None)
        if person_id is None or contacts is None:
            return None
        try:
            return contacts.by_id(person_id)
        except Exception as exc:
            logger.warning("Call signal could not read the people list (%s)", type(exc).__name__)
            return None

    async def _record_ready(self, event):
        try:
            self.consider(event.data or {})
        except Exception as exc:
            logger.warning("Call signal failed (%s)", type(exc).__name__)

    def consider(self, data):
        from telephony.orchestrator import caller_group, missed, spam

        record_id = data.get("record_id")
        if not isinstance(record_id, str):
            return False
        record = self.app.call_agent.records.get(record_id)
        if not isinstance(record, dict) or record.get("direction") != "inbound" \
                or record.get("mode") != "screening" or spam(record):
            return False
        group = caller_group(record)
        vip = group == "vip" or data.get("vip") is True
        was_missed = missed(record)
        if not vip and not was_missed:
            return False
        person_id = record.get("contact_id") if isinstance(record.get("contact_id"), str) else None
        person = self._person(person_id)
        name = person.get("name") if isinstance(person, dict) else None
        triage = record.get("triage") if record.get("triage_state") == "done" else None
        summary = triage.get("summary") if isinstance(triage, dict) else None
        now = self.now()
        if vip:
            kind, urgency = "call.vip", 2
            title = f"{name} called" if name else "A VIP called"
            if was_missed:
                title = f"Missed call from {name}" if name else "Missed call from a VIP"
        else:
            kind, urgency = "call.missed", 1
            title = f"Missed call from {name}" if name else "Missed call"
        item = signal(
            kind, "calls", title, at=now, ttl=CALL_TTL, urgency=urgency,
            dedupe_key=f"call:{record_id}", body=summary if isinstance(summary, str) else "",
            data={"record_id": record_id, "missed": was_missed, "group": group},
            person_id=person_id,
        )
        return self.hub.publish(item)


JOB_TTL = dt.timedelta(hours=2)
JOB_TITLES = {
    "cad": ("CAD build finished", "CAD build failed"),
    "image": ("Image ready", "Image generation failed"),
    "web": ("Web inspection finished", "Web inspection failed"),
}


class JobsProducer:
    """``job.finished`` (urgency 1; failures urgency 2) for CAD builds, image generation and
    web inspections.

    The creative services publish job updates through ``on_update``; this producer chains
    onto it once (like the live design does) and acts only while started. Only the
    ``succeeded`` and ``failed`` states count: a cancelled or interrupted job says nothing.
    Web inspections are observed around ``BrowserService.runner``."""

    name = "jobs"

    def __init__(self, app, hub, *, now=None):
        self.app, self.hub = app, hub
        self.now = now or hub.now
        self.active = False
        for job, attribute in (("cad", "cad"), ("image", "images")):
            service = getattr(app, attribute, None)
            if service is not None:
                self._chain(service, job)
        browser = getattr(app, "browser", None)
        if browser is not None and getattr(browser, "runner", None) is not None:
            browser.runner = self._observed(browser.runner)

    def start(self):
        self.active = True

    async def stop(self):
        self.active = False

    def _chain(self, service, job):
        previous = service.on_update

        async def on_update(owner, value):
            if previous:
                await previous(owner, value)
            if self.active and isinstance(value, dict):
                try:
                    self.creative(job, value)
                except Exception as exc:
                    logger.warning("Job signal failed (%s)", type(exc).__name__)

        service.on_update = on_update

    def _live(self, request_id):
        live = getattr(self.app, "live_design", None)
        for design in tuple(getattr(live, "designs", {}).values()):
            current = getattr(design, "job", None)
            if isinstance(current, dict) and current.get("request_id") == request_id:
                return True
        return False

    def creative(self, job, value):
        state = value.get("state")
        request_id = value.get("request_id")
        if state not in ("succeeded", "failed") or not isinstance(request_id, str):
            return False
        data = {"job": job, "request_id": request_id, "state": state}
        if isinstance(value.get("project"), str):
            data["project"] = value["project"]
        if job == "cad":
            data["live"] = self._live(request_id)
        return self.finished(job, state == "succeeded", f"job.finished:{job}:{request_id}", data)

    def finished(self, job, ok, dedupe_key, data):
        done, failed = JOB_TITLES[job]
        now = self.now()
        item = signal(
            "job.finished", job, done if ok else failed, at=now, ttl=JOB_TTL,
            urgency=1 if ok else 2, dedupe_key=dedupe_key, data=data,
        )
        return self.hub.publish(item)

    def _observed(self, runner):
        counter = iter(range(1, 1 << 62))

        async def observed(args):
            run = next(counter)
            try:
                report = await runner(args)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._web(run, False)
                raise
            self._web(run, True)
            return report

        return observed

    def _web(self, run, ok):
        if not self.active:
            return
        try:
            stamp = self.now().strftime("%Y%m%dT%H%M%S%f")
            self.finished("web", ok, f"job.finished:web:{stamp}:{run}",
                          {"job": "web", "state": "succeeded" if ok else "failed"})
        except Exception as exc:
            logger.warning("Job signal failed (%s)", type(exc).__name__)


class SignalProducers:
    """Every producer, started with the app and stopped on close."""

    def __init__(self, app, hub, producers=None):
        self.app, self.hub = app, hub
        self.producers = list(producers) if producers is not None else [
            CalendarProducer(app, hub),
            WeatherProducer(app, hub),
            BatteryProducer(app, hub),
            CallsProducer(app, hub),
            JobsProducer(app, hub),
        ]

    def get(self, name):
        return next((item for item in self.producers if item.name == name), None)

    def start(self):
        for producer in self.producers:
            try:
                producer.start()
            except Exception as exc:
                logger.warning("Signal producer %s did not start (%s)", producer.name,
                               type(exc).__name__)

    async def stop(self):
        results = await asyncio.gather(
            *(producer.stop() for producer in self.producers), return_exceptions=True
        )
        for producer, result in zip(self.producers, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Signal producer %s did not stop cleanly (%s)", producer.name,
                               type(result).__name__)
