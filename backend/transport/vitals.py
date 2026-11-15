"""Owner-only Systems rail routes (S13a.5, docs/SYSTEMS_RAIL.md); never model tools.

``vitals_watch {on, low_battery?}``: start or stop this renderer's PC vitals; answers
``{ok, watching, paused, interval}`` and the core then emits ``vitals`` to this socket
(services/vitals.py has the shape).
``weather_now {}``: the home town's weather now, ``{ok, home: false}`` without a home town,
else ``{ok, home: true, line, temp, condition}``.
``agenda_next {}``: ``{ok, calendar, event: {title, time, at} | null,
reminders: {count, first: {title, time}} | null}``; ``at`` is epoch seconds.
``home_summary {}``: ``{ok, connected, line}``; ``line`` is null when it couldn't be read.

All of them need the authenticated, unlocked desktop owner renderer. Titles, places and
values are the owner's private data: nothing here logs them.
"""

import datetime as dt

from pydantic import StrictBool, ValidationError

from services import briefing, voice_quick
from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)

TITLE_LIMIT = 120


class VitalsWatch(EmptyRequest):
    on: StrictBool
    low_battery: StrictBool = False


def _title(value):
    return briefing.clean(value, TITLE_LIMIT) or "(No title)"


def next_event(events, now):
    """The first timed event today that has not started yet: {title, time, at} or None."""
    from services.calendar import TIMEZONE, local

    now = local(now)
    upcoming = []
    for event in events or ():
        if not isinstance(event, dict) or event.get("all_day"):
            continue
        start = event.get("start")
        try:
            day = dt.date.fromisoformat(str(event.get("date")))
            clock = dt.time.fromisoformat(start) if isinstance(start, str) and len(start) == 5 else None
        except ValueError:
            continue
        if clock is None or day != now.date():
            continue
        begin = dt.datetime.combine(day, clock, TIMEZONE)
        if begin > now:
            upcoming.append((begin, start, event))
    if not upcoming:
        return None
    begin, start, event = min(upcoming, key=lambda item: item[0])
    return {"title": _title(event.get("title")), "time": start, "at": int(begin.timestamp())}


class VitalsTransport:
    models = {
        "vitals_watch": VitalsWatch,
        "weather_now": EmptyRequest,
        "agenda_next": EmptyRequest,
        "home_summary": EmptyRequest,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                args = model.model_validate({} if data is None else data)
                return await method(sid, args)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
            except Exception as exc:
                logger.warning("Systems rail request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "rail_unavailable",
                    "message": "This couldn't be read just now. Try again.",
                }

        return handle

    async def _vitals_watch(self, sid, args):
        return self.app.vitals.watch(sid, args.on, args.low_battery)

    async def _weather_now(self, _sid, _args):
        from services.weather import summary_line

        weather = getattr(self.app, "weather", None)
        if weather is None or weather.home_place() is None:
            return {"ok": True, "home": False}
        result = await weather.lookup(None, "now")
        if result.get("need_place"):
            return {"ok": True, "home": False}
        if result.get("error"):
            return {"ok": False, "code": "weather_unavailable", "message": summary_line(result)}
        now = result.get("now") or {}
        return {
            "ok": True,
            "home": True,
            "line": summary_line(result),
            "temp": now.get("temp"),
            "condition": now.get("condition"),
        }

    async def _agenda_next(self, _sid, _args):
        from services.calendar import local_now

        now = local_now()
        reminder_state, reminders = voice_quick.due_reminders(self.app, now)
        state, events = await voice_quick.today_events(self.app)
        due = None
        if reminder_state == "listed" and reminders:
            first = reminders[0]
            due = {
                "count": len(reminders),
                "first": {"title": _title(first.get("text")), "time": first.get("time")},
            }
        return {
            "ok": True,
            "calendar": state,
            "event": next_event(events, now) if state == "connected" else None,
            "reminders": due,
        }

    async def _home_summary(self, _sid, _args):
        service = getattr(self.app, "home", None)
        if service is None or not service.connected:
            return {"ok": True, "connected": False, "line": None}
        try:
            result = await voice_quick.home(self.app)
        except ServiceError:
            result = {}
        return {"ok": True, "connected": True, "line": result.get("answer")}
