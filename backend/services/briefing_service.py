"""The morning briefing at runtime (P2): when it plays, where it goes, and its routes.

The composer (services/briefing.py) builds the card and the spoken text; this module
gathers the inputs, decides when, and delivers.

When:

- Once a local day (Asia/Kuala_Lumpur), the first time the owner is at the PC inside
  ``briefing.window_start``-``briefing.window_end``. Presence is a renderer
  ``presence_ping``, an authenticated owner renderer connecting or unlocking (``hydrate``),
  or a tray or "Hey Jarvis" voice session starting.
- While a voice session runs, or JARVIS is locked, the briefing waits; it plays when that
  ends (the same day, before 12:00).
- The day's state lives in the protected profile database (kind ``briefing``): the date,
  when the owner was first present, when it was shown, the card, dismissal and the phone
  outcome.

Where:

- The card always: ``briefing`` (``{"briefing": {date, card, expires_at} | null}``) to the
  owner's authenticated renderers, and ``briefing_get`` / ``briefing_dismiss`` /
  ``briefing_play`` for them. The card stays until dismissed or 12:00 local (a card first
  shown after noon, from ``briefing_play``, until midnight).
- Speech when ``briefing.speak`` is on and voice is available (no voice session, not
  gaming, not locked, a Gemini key): a tray voice session with source ``"briefing"``
  (VoiceService.start_briefing), shown by the voice stage or the talking overlay as any tray
  session. If Live fails, the card is all there is.
- Gaming mode: the card only (no speech, no phone call).
- Phone when ``briefing.phone`` is on: from ``briefing.phone_time`` for 30 minutes, if the
  owner has not been at the PC yet today, is away, and calls are enabled and set up, an
  owner call (mode ``morning_briefing``, the owner-briefing PIN rules) reads it. A call the
  owner heard marks the day as briefed by phone: the PC shows the card later without
  speaking it.

Never logged: event titles, reminder text, call summaries, names or the spoken text.
"""

import asyncio
import datetime as dt
import time

from services import briefing as composer
from services.log import get_logger
from services.settings import EmptyRequest, briefing_settings
from services.tools import ServiceError

logger = get_logger(__name__)

KIND, KEY = "briefing", "state"
NOON = dt.time(12, 0)
PHONE_GRACE = dt.timedelta(minutes=30)
PHONE_RESULT_TIMEOUT = 2700.0
CALENDAR_TIMEOUT = 10.0
TICK_SECONDS = 30.0
ZONE = composer.ZONE


class MorningBriefing:
    events = ("briefing_get", "briefing_dismiss", "briefing_play")

    def __init__(self, app, *, wall=time.time, tick=TICK_SECONDS):
        self.app, self.wall, self.tick = app, wall, tick
        self.waiting = None  # the local date of a presence held back by voice or the lock
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.runner = None
        self.expired = None  # the date whose card expiry was already published
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    # --- clock, settings and state ---------------------------------------------------------

    def now(self):
        return dt.datetime.fromtimestamp(self.wall(), ZONE)

    def settings(self):
        return briefing_settings(self.app.settings)

    def load(self, now=None):
        """Today's state; a new day starts fresh and remembers the last briefing before it."""
        today = (now or self.now()).date().isoformat()
        database = self.app.database
        with database.connection() as db:
            saved = database.get(db, KIND, KEY)
        saved = saved if isinstance(saved, dict) else {}
        if saved.get("date") == today:
            return saved
        previous = saved.get("last_at") or saved.get("previous_at")
        return {"date": today, "previous_at": previous if isinstance(previous, (int, float)) else None}

    def save(self, state):
        database = self.app.database
        with database.transaction() as db:
            database.put(db, KIND, KEY, state)

    def owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def locked(self):
        owner = self.owner()
        return owner is None or not self.app.sessions.authenticated(owner)

    def gaming(self):
        return self.app.resources.state == "gaming"

    def voice_active(self):
        return any(not session.closed for session in self.app.voice.sessions.values())

    @staticmethod
    def in_window(now, settings):
        clock = f"{now:%H:%M}"
        return settings["window_start"] <= clock < settings["window_end"]

    @staticmethod
    def expires_at(state):
        """12:00 for a card shown before noon; midnight for one shown after."""
        shown = state.get("shown_at")
        if not isinstance(shown, (int, float)):
            return None
        moment = dt.datetime.fromtimestamp(shown, ZONE)
        if moment.time() < NOON:
            return dt.datetime.combine(moment.date(), NOON, ZONE)
        return dt.datetime.combine(moment.date() + dt.timedelta(days=1), dt.time(), ZONE)

    def payload(self, state, now=None):
        """Today's card for the renderers, or None (none yet, dismissed or expired)."""
        now = now or self.now()
        if state.get("date") != now.date().isoformat() or state.get("dismissed"):
            return None
        card, expires = state.get("card"), self.expires_at(state)
        if not isinstance(card, dict) or expires is None or now >= expires:
            return None
        return {
            "date": state["date"],
            "card": card,
            "expires_at": expires.isoformat(timespec="seconds"),
        }

    # --- presence (the trigger) -----------------------------------------------------------

    def _spawn(self, coroutine):
        try:
            task = asyncio.get_running_loop().create_task(coroutine, name="morning-briefing")
        except RuntimeError:
            coroutine.close()
            return None
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def presence(self, source):
        """The owner is at the PC (``source``: ping, unlock or voice)."""
        self._spawn(self._presence(source))

    def voice_ended(self):
        """A voice session ended: a briefing held back for it may play now."""
        if self.waiting is not None:
            self._spawn(self._resume())

    async def _presence(self, source):
        try:
            async with self.lock:
                now = self.now()
                state = self.load(now)
                if not state.get("present_at"):
                    state["present_at"] = self.wall()
                    self.save(state)
                await self._consider(now, state, held=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Morning briefing presence (%s) failed", source)

    async def _resume(self):
        try:
            async with self.lock:
                now = self.now()
                state = self.load(now)
                if self.waiting == state["date"]:
                    await self._consider(now, state, held=True)
                else:
                    self.waiting = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Morning briefing resume failed")

    async def _consider(self, now, state, *, held):
        """Play today's briefing if it is due (the lock is held)."""
        settings = self.settings()
        if not settings["enabled"] or state.get("shown_at"):
            self.waiting = None
            return
        if held:
            if now.time() >= NOON:  # held past the card's lifetime: today's is skipped
                self.waiting = None
                return
        elif not self.in_window(now, settings):
            return
        if self.voice_active() or self.locked():
            self.waiting = state["date"]
            return
        self.waiting = None
        speak = settings["speak"] and state.get("phone") != "done"
        await self._deliver(now, state, speak=speak)

    # --- delivery -------------------------------------------------------------------------

    async def _deliver(self, now, state, *, speak):
        composed = await self.compose(now, state)
        stamp = self.wall()
        state.update(card=composed["card"], dismissed=False, shown_at=stamp, last_at=stamp)
        self.save(state)
        self.expired = None
        await self.publish(state)
        spoken, reason = (False, "speech_off")
        if speak:
            spoken, reason = await self.speak(composed["spoken"])
        logger.info("Morning briefing shown (spoken=%s, reason=%s)", spoken, reason)
        return spoken, reason

    def speech_block(self):
        """Why the briefing can't be spoken now, or None."""
        if self.gaming():
            return "gaming_mode"
        if self.locked():
            return "authentication_required"
        if self.voice_active():
            return "voice_busy"
        try:
            self.app.voice.preflight()
        except ServiceError as exc:
            return exc.code
        return None

    async def speak(self, text):
        """(spoken, reason): start the briefing's voice session, or why not."""
        reason = self.speech_block()
        if reason is not None:
            return False, reason
        started = await self.app.voice.start_briefing(text)
        return (True, None) if started else (False, "voice_unavailable")

    async def publish(self, state=None, rooms=None):
        """``briefing`` to the owner's authenticated renderers (or ``rooms``)."""
        owner = self.owner()
        if owner is None or not self.app.sessions.authenticated(owner):
            return
        payload = {"briefing": self.payload(state if state is not None else self.load())}
        for sid in rooms if rooms is not None else self.app.sessions.rooms(owner, "renderer"):
            try:
                await self.app.sio.emit("briefing", payload, room=sid)
            except Exception:
                logger.warning("Morning briefing could not be delivered", exc_info=True)

    async def hydrate(self, sid):
        """An authenticated owner renderer connected or unlocked: today's card, then presence."""
        await self.publish(rooms=(sid,))
        self.presence("unlock")

    # --- gathering the inputs -------------------------------------------------------------

    async def compose(self, now, state):
        since = composer.overnight_since(now, state.get("previous_at"))
        return composer.compose(
            now,
            self.app.settings,
            calendar=await self.calendar_events(now),
            reminders=self.reminders(),
            calls=self.calls(),
            jobs=self.jobs(),
            since=since,
        )

    async def calendar_events(self, now):
        """Today's events, or None when not connected, reading is off, or the read failed."""
        calendar = getattr(self.app, "calendar", None)
        if calendar is None or not calendar.connected or not calendar.switches()["read_events"]:
            return None
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            body = await asyncio.wait_for(
                calendar.events(midnight, midnight + dt.timedelta(days=1)), CALENDAR_TIMEOUT
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Morning briefing calendar unavailable (%s)", getattr(exc, "code", type(exc).__name__))
            return None
        return body.get("events") or []

    def reminders(self):
        try:
            return [item.to_dict() for item in self.app.reminders.list_reminders("all")]
        except Exception as exc:
            logger.warning("Morning briefing reminders unavailable (%s)", type(exc).__name__)
            return []

    def calls(self):
        """Incoming phone calls as the composer reads them (the Calls view's summaries)."""
        from telephony.orchestrator import summary_item

        orchestrator = getattr(self.app, "call_orchestrator", None)
        if orchestrator is None:
            return []
        try:
            records = orchestrator.records.phone_calls()
            people = orchestrator.people()
            calls = []
            for record in records:
                if record.get("direction") == "outbound" or record.get("mode") not in (
                    "screening", None
                ):
                    continue
                item = summary_item(record, people)
                group = item["caller_group"]
                if group is None and record.get("caller_group") == "vip":
                    group = "vip"  # a VIP at call time whose person was removed since
                calls.append({
                    "id": item["id"],
                    "started_at": record.get("started_at"),
                    "name": item["name"],
                    "group": group,
                    "summary": item["summary"],
                    "status": item["status"],
                    "counterpart_masked": item["counterpart_masked"],
                })
            return calls
        except Exception as exc:
            logger.warning("Morning briefing calls unavailable (%s)", type(exc).__name__)
            return []

    def jobs(self):
        """CAD and image jobs of the current project (print jobs keep no finish time)."""
        owner = self.owner()
        if owner is None:
            return []
        project = self.app.projects.get_current_project_path().resolve()
        jobs = []
        for kind, service in (("cad", getattr(self.app, "cad", None)),
                              ("image", getattr(self.app, "images", None))):
            if service is None:
                continue
            try:
                values = service.list(owner, project)
            except Exception as exc:
                logger.warning("Morning briefing %s jobs unavailable (%s)", kind, type(exc).__name__)
                continue
            for value in values:
                created, duration = value.get("created_at"), value.get("duration_seconds")
                if not isinstance(created, (int, float)):
                    continue
                recipe = value.get("recipe") if isinstance(value.get("recipe"), dict) else {}
                jobs.append({
                    "kind": kind,
                    "request_id": value.get("request_id"),
                    "name": recipe.get("name"),
                    "state": value.get("state"),
                    "finished_at": created + (duration if isinstance(duration, (int, float)) else 0),
                })
        return jobs

    # --- the phone ---------------------------------------------------------------------------

    def phone_due(self, now, state, settings):
        if not (settings["enabled"] and settings["phone"]):
            return False
        at = dt.datetime.combine(now.date(), dt.time.fromisoformat(settings["phone_time"]), ZONE)
        if not at <= now < at + PHONE_GRACE:
            return False
        # Only when the owner hasn't been at the PC yet today, and only once a day.
        return not (state.get("present_at") or state.get("shown_at") or state.get("phone"))

    def phone_ready(self):
        """The owner number, or None while calls can't reach the owner now."""
        if self.gaming():
            return None
        orchestrator = getattr(self.app, "call_orchestrator", None)
        telephony = getattr(self.app, "telephony", None)
        if orchestrator is None or telephony is None or not orchestrator.presence.away():
            return None
        if not telephony.calls_settings()["enabled"] or telephony.sessions:
            return None
        credentials = telephony.credentials()
        owner_number = credentials.get("owner_number") if credentials else None
        if not owner_number or telephony.public_base_url() is None or not telephony.agent_ready():
            return None
        return owner_number

    async def check_phone(self):
        from telephony import briefs

        async with self.lock:
            now = self.now()
            state = self.load(now)
            if not self.phone_due(now, state, self.settings()):
                return False
            owner_number = self.phone_ready()
            if owner_number is None:
                return False
            composed = await self.compose(now, state)
            brief = briefs.morning_briefing_brief(
                composed["spoken"], owner_number=owner_number,
                owner_name=briefs.owner_name(self.app.settings),
            )
            state["phone"] = "calling"
            self.save(state)
            try:
                handle = await self.app.call_agent.call(brief)  # calls to the owner need no grant
            except ServiceError as exc:
                state["phone"] = "failed"
                self.save(state)
                logger.warning("Morning briefing call could not be placed: %s", exc.code)
                return False
        orchestrator = self.app.call_orchestrator
        try:
            await orchestrator._placed(handle.call_id, "morning_briefing", None)
        except Exception:
            logger.warning("Morning briefing call progress could not be shown", exc_info=True)
        logger.info("Morning briefing call placed")
        self._spawn(self._after_phone(state["date"], handle))
        return True

    async def _after_phone(self, date, handle):
        try:
            result = await asyncio.wait_for(asyncio.shield(handle.result), PHONE_RESULT_TIMEOUT)
        except TimeoutError:
            result = None
        heard = (
            result is not None
            and result.state == "completed"
            and (result.outcome or {}).get("status") == "delivered"
        )
        async with self.lock:
            state = self.load()
            if state.get("date") != date:
                return
            state["phone"] = "done" if heard else "missed"
            if heard:
                state["last_at"] = self.wall()
            self.save(state)
        logger.info("Morning briefing call ended (heard=%s)", heard)

    # --- the schedule -----------------------------------------------------------------------

    def start(self):
        if self.runner is None or self.runner.done():
            self.runner = asyncio.get_running_loop().create_task(self.run(), name="morning-briefing")
        return self.runner

    async def run(self):
        while True:
            await asyncio.sleep(self.tick)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Morning briefing check failed")

    async def check(self):
        """Every tick: clear an expired card, play a held-back briefing, phone when due."""
        now = self.now()
        state = self.load(now)
        if (state.get("shown_at") and self.payload(state, now) is None
                and self.expired != state["date"]):
            self.expired = state["date"]
            await self.publish(state)
        if self.waiting is not None and not (self.voice_active() or self.locked()):
            await self._resume()
        await self.check_phone()

    async def close(self):
        tasks = [task for task in (self.runner, *self.tasks) if task is not None and not task.done()]
        self.runner = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- routes ---------------------------------------------------------------------------

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                EmptyRequest.model_validate({} if data is None else data)
                return await method(sid)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValueError:  # pydantic's ValidationError; never echo its details
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid briefing request."}
            except Exception as exc:
                logger.warning("Morning briefing request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "briefing_unavailable",
                    "message": "The morning briefing couldn't be prepared. Try again.",
                }

        return handle

    async def _briefing_get(self, _sid):
        return {"ok": True, "briefing": self.payload(self.load())}

    async def _briefing_dismiss(self, _sid):
        async with self.lock:
            state = self.load()
            state["dismissed"] = True
            self.save(state)
        await self.publish(state)
        return {"ok": True}

    async def _briefing_play(self, _sid):
        """Today's briefing, freshly composed, shown and spoken now (also outside the window)."""
        async with self.lock:
            now = self.now()
            state = self.load(now)
            if not state.get("present_at"):
                state["present_at"] = self.wall()
            self.waiting = None
            spoken, reason = await self._deliver(now, state, speak=True)
        return {"ok": True, "briefing": self.payload(state), "spoken": spoken, "reason": reason}
