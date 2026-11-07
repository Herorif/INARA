"""C3 call orchestration: owner briefings, callbacks, call progress and the Calls view data.

Calls stay off by default; nothing here places a call unless ``calls.enabled`` is true.

- **Owner briefing policy.** When ``call_record_ready`` fires for an inbound screening
  record, the owner is phoned (``CallAgent.call(owner_briefing_brief(...))``, no grant)
  only if ``calls.brief_by_phone`` allows it for the triage result ("urgent": triage
  urgency urgent; "needs_owner": urgent or needs_owner; "off": never), the owner is away
  from the PC (no owner renderer, the native window hidden, or no ``presence_ping`` for
  five minutes) and it is not quiet hours, unless the call is urgent. Otherwise the
  desktop notice C2 already sent is all that happens.
- **Voice-confirmed callbacks.** A briefing that ends with a confirmed callback carries
  C2's one-use grant (10 minutes); the callback is placed at once. Quiet hours, the daily
  cap or the per-number cooldown never drop it silently: the original record is marked
  ``callback_blocked`` with the reason and the owner is notified.
- **Desktop-approved callbacks.** "Approve call" in the Calls view is the approval: a grant
  bound to that number and that brief's hash is issued and the call placed immediately.
- **Task calls (C4).** The owner approved ``place_task_call`` on screen (task_calls.py);
  a grant bound to the business's number and the task brief's hash is issued and the call
  placed. When it ends, the outcome is appended to the conversation the request came from
  (and sent live as ``transcription``), and a confirmed booking gets a reminder.
- **Progress.** Twilio status callbacks and Media Stream open/close become
  ``call_progress`` events for the owner's renderers.

Records are linked both ways through ``related_ids``; the original screening record also
keeps ``briefing`` / ``callback`` state and the owner's ``done`` mark (calls.records).
"""

import asyncio
from datetime import datetime, timezone
import time
import uuid

from services.log import get_logger
from services.tools import ServiceError
from telephony import briefs, task_calls
from telephony.agent import BRIEFING_PIN
from telephony.grants import in_quiet_hours
from telephony.numbers import mask_display, normalize, withheld

logger = get_logger("telephony.orchestrator")

EVENT_RECORD_READY = "call_record_ready"
EVENT_PROGRESS = "call_progress"
EVENT_CALL_STATUS = "telephony.call_status"
EVENT_SESSION = "telephony.session"
EVENT_OPEN = "calls_open"  # P1: open the Calls view on one record (a VIP balloon click)
OPEN_SECONDS = 120.0  # a workspace started by that click has this long to pick it up
AWAY_SECONDS = 300
RESULT_TIMEOUT = 2700.0  # a placed call has resolved long before this (30 min cap + ringing)
PROGRESS_TTL = 7200.0
DRAFT_LIMIT = 300
# place_call refusals that block a callback (the owner can retry from the Calls view).
BLOCKED = {
    "call_quiet_hours": "quiet_hours",
    "call_daily_cap": "daily_cap",
    "call_number_cooldown": "cooldown",
}
BLOCKED_TEXT = {
    "quiet_hours": "Callback not placed: it is quiet hours.",
    "daily_cap": "Callback not placed: today's limit for calls to other people is reached.",
    "cooldown": "Callback not placed: JARVIS called this number recently.",
}
TWILIO_STATES = {
    "queued": "dialing",
    "initiated": "dialing",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "answered": "in_progress",
    "completed": "completed",
    "busy": "no_answer",
    "no-answer": "no_answer",
    "canceled": "no_answer",
    "failed": "failed",
}
TERMINAL = frozenset({"completed", "no_answer", "failed"})
RANK = {"dialing": 0, "ringing": 1, "in_progress": 2}  # a late "ringing" never goes back
# call_progress ``message`` for failed / no_answer (plain owner-facing text, at most 200
# characters, never provider internals), by Twilio CallStatus.
PROGRESS_MESSAGES = {
    "busy": "The line was busy.",
    "no-answer": "No one answered.",
    "canceled": "The call was cancelled before anyone answered.",
    "failed": "The call could not be connected.",
}
DEFAULT_MESSAGES = {"no_answer": "No one answered.", "failed": "The call could not be connected."}
REPORTED_LIMIT = 256


def should_brief(setting, triage, *, away, quiet, group=None, untriaged=False):
    """The owner-briefing policy for one triaged screening record.

    P1, by the caller's group in the owner's people list: a VIP is briefed whenever
    ``calls.brief_by_phone`` is not "off" and the owner is away, even when the call is not
    urgent (quiet hours still hold unless it is urgent); a blocked caller never is; an
    unknown caller's spam never is. Known and unknown callers follow the setting.
    ``untriaged``: the triage failed, timed out or never ran. A VIP is still briefed then;
    the urgency is unknown, so quiet hours always hold. Anyone else is not."""
    if setting not in ("urgent", "needs_owner") or not away:
        return False
    if not isinstance(triage, dict):
        return bool(group == "vip" and untriaged and not quiet)
    if group == "blocked" or (group not in ("vip", "known") and triage.get("spam") is True):
        return False
    urgent = triage.get("urgency") == "urgent"
    if group == "vip":
        return bool(urgent or not quiet)
    wanted = urgent if setting == "urgent" else urgent or triage.get("needs_owner") is True
    return bool(wanted and (urgent or not quiet))


class Presence:
    """Whether the owner is at the PC: an open, visible owner renderer with user input
    (``presence_ping``, sent at most once a minute) in the last five minutes."""

    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.last = clock()  # a fresh start counts as recent activity

    def ping(self):
        self.last = self.clock()

    def away(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        owner = native.state.identity.owner if native else sessions.local_owner
        if owner is None or not sessions.rooms(owner, "renderer"):
            return True
        if native is not None and getattr(native.state, "visible", True) is False:
            return True
        return self.clock() - self.last >= AWAY_SECONDS


# --- record views (masked numbers only) ---------------------------------------------------


def _message(record):
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    message = fields.get("message")
    return message if isinstance(message, dict) else {}


def _triage(record):
    triage = record.get("triage")
    return triage if record.get("triage_state") == "done" and isinstance(triage, dict) else None


def _part(record, name):
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def callback_number(record):
    number = _message(record).get("callback_number")
    number = normalize(number) if isinstance(number, str) else None
    return None if number is None or withheld(number) else number


def resolved(record):
    """The owner's matter is settled: marked done, ignored on a briefing, or called back."""
    return (
        record.get("done") is True
        or _part(record, "briefing").get("decision") == "ignore"
        or _part(record, "callback").get("state") == "completed"
    )


def missed(record):
    """An incoming call JARVIS did not screen (voicemail because the budget ran out, or the
    agent failed): the owner must see it until it is marked done."""
    return record.get("direction") != "outbound" and record.get("state") in (
        "missed", "failed", "uncertain"
    )


def task_unconfirmed(record):
    """A task call JARVIS made that did not end with a confirmation (declined, needs the
    owner, no answer or no outcome). A failed call shows as failed instead."""
    outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else {}
    return (record.get("mode") == "task" and record.get("direction") == "outbound"
            and record.get("state") not in ("failed", "uncertain")
            and outcome.get("status") != "confirmed")


def caller_group(record):
    group = record.get("caller_group")
    return group if group in briefs.CALLER_GROUPS else None


def spam(record):
    """P1: a blocked caller's call, or an unknown caller's call that triage marked spam
    (a sales pitch, recorded message, robocall or scam). Listed under Spam, never under
    Needs you."""
    if record.get("direction") == "outbound":
        return False
    group = caller_group(record)
    if group == "blocked":
        return True
    return group is None and (_triage(record) or {}).get("spam") is True


def needs_you(record):
    if record.get("done") is True or record.get("mode") == "owner_briefing" or spam(record):
        return False
    if _part(record, "callback").get("state") in ("blocked", "failed", "no_answer"):
        return True
    if resolved(record):
        return False
    if missed(record):
        return True
    if record.get("mode") == "task":
        return task_unconfirmed(record)
    triage = _triage(record) or {}
    return triage.get("needs_owner") is True or triage.get("urgency") == "urgent"


def call_status(record):
    if spam(record):
        return "blocked" if caller_group(record) == "blocked" else "spam"
    if record.get("done") is True:
        return "done"
    callback = _part(record, "callback").get("state")
    if callback == "calling" or _part(record, "briefing").get("state") == "calling":
        return "in_progress"
    if callback == "blocked":
        return "callback_blocked"
    if callback in ("failed", "no_answer"):
        return "failed"
    if resolved(record):
        return "done"
    if missed(record):
        return "needs_you"
    if record.get("triage_state") == "pending":
        return "in_progress"
    if record.get("state") in ("failed", "uncertain"):
        return "failed"  # a call JARVIS placed that failed
    return "needs_you" if needs_you(record) else "done"


def _iso(stamp):
    if not isinstance(stamp, (int, float)):
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def person_for(record, people):
    """The owner's saved person for this record (by the person matched at call time, else
    by the caller ID), from ``people`` = (by id, by number); None for outbound calls."""
    if not people or record.get("direction") == "outbound":
        return None
    by_id, by_number = people
    person = by_id.get(record.get("contact_id"))
    number = record.get("caller_number")
    return person or (by_number.get(number) if isinstance(number, str) else None)


def summary_item(record, people=None):
    triage = _triage(record)
    message = _message(record)
    urgency = (triage or {}).get("urgency") or message.get("urgency")
    person = person_for(record, people)
    # A saved caller shows by the owner's name for them (P1), else the name they gave.
    name = (person or {}).get("name") or message.get("name") or record.get("name")
    outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else {}
    counterpart = record.get("counterpart") if isinstance(record.get("counterpart"), dict) else {}
    duration = record.get("duration_seconds")
    return {
        "id": record["id"],
        "direction": "outbound" if record.get("direction") == "outbound" else "inbound",
        "mode": record.get("mode"),
        "counterpart_masked": counterpart.get("masked") or "withheld",
        "name": name if isinstance(name, str) and name else None,
        "started_at": _iso(record.get("started_at")),
        "duration_seconds": duration if isinstance(duration, (int, float)) else 0,
        "urgency": urgency if urgency in briefs.URGENCY else None,
        "needs_owner": bool(triage and triage.get("needs_owner") is True),
        "summary": (triage or {}).get("summary") or None,
        "status": call_status(record),
        "outcome_status": outcome.get("status") if isinstance(outcome.get("status"), str) else None,
        # P1: the saved person's current group (null for an unsaved caller).
        "caller_group": person["group"] if person else None,
    }


def _details(record):
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    outcome = fields.get("outcome")
    if isinstance(outcome, dict) and outcome.get("details"):
        return str(outcome["details"])
    decision = fields.get("decision")
    if isinstance(decision, dict) and decision.get("message_for_caller"):
        return str(decision["message_for_caller"])
    callback = _part(record, "callback")
    if callback.get("state") in ("blocked", "failed", "no_answer"):
        return BLOCKED_TEXT.get(callback.get("reason"), "The callback did not go through.")
    return None


def detail_item(record, known_ids, people=None, can_add_person=False):
    item = summary_item(record, people)
    person = person_for(record, people)
    message = _message(record)
    number = callback_number(record)
    triage = _triage(record)
    roles = {"assistant": "jarvis", "caller": "owner" if record.get("mode") == "owner_briefing" else "caller"}
    outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else None
    return {
        **item,
        "fields": {
            "name": message.get("name"),
            "reason": message.get("reason"),
            "urgency": message.get("urgency"),
            "callback_number_masked": mask_display(number) if number else None,
            "message": message.get("message"),
        } if message else None,
        "triage": {
            "summary": triage.get("summary"),
            "urgency": triage.get("urgency"),
            "needs_owner": triage.get("needs_owner") is True,
            "suggested_actions": [str(value) for value in triage.get("suggested_actions") or []],
        } if triage else None,
        "triage_state": record.get("triage_state"),
        "transcript": [
            {"role": roles[segment["role"]], "text": str(segment.get("text", ""))}
            for segment in record.get("transcript") or []
            if isinstance(segment, dict) and segment.get("role") in roles
        ],
        "outcome": {
            "status": outcome.get("status"),
            "details": _details(record),
        } if outcome and isinstance(outcome.get("status"), str) else None,
        "related_ids": [value for value in record.get("related_ids") or [] if value in known_ids],
        # P1: the saved person (id, name, group) and whether the call has a number the
        # owner can add to people, mark VIP or block.
        "contact": {key: person[key] for key in ("id", "name", "group")} if person else None,
        "can_add_person": bool(can_add_person),
    }


def callback_draft(record):
    """A short message for the caller: a blocked or failed callback's owner-approved words,
    else the triage's ``suggested_reply`` (addressed to the caller), else "". The triage's
    ``suggested_actions`` are instructions to the owner and are never used here."""
    callback = _part(record, "callback")
    if callback.get("state") in ("blocked", "failed", "no_answer") and callback.get("message"):
        return str(callback["message"])[:DRAFT_LIMIT]
    reply = (_triage(record) or {}).get("suggested_reply")
    return briefs.clean_line(reply, DRAFT_LIMIT) if isinstance(reply, str) else ""


# --- the orchestrator ---------------------------------------------------------------------


class CallOrchestrator:
    def __init__(self, app, *, clock=time.monotonic, wall=time.time):
        self.app, self.clock, self.wall = app, clock, wall
        self.presence = Presence(app, clock)
        self.inflight = {}  # source record id -> "briefing" | "callback"
        self.progress = {}  # progress call id -> entry
        self.inbound_ids = {}  # CallSid -> progress call id (inbound streams)
        self.ended = {}  # progress call id -> time, so late Twilio statuses are ignored
        self.task_calls = {}  # C4: C1 call id -> the task call waiting for its outcome
        self.reported = {}  # C1 call id -> time its outcome was posted (once per call)
        self.tasks = set()
        self.closing = False
        self.open_target = None  # P1: (record id, time) from a VIP balloon click
        bus = getattr(app, "bus", None)
        if bus is not None:
            bus.on(EVENT_RECORD_READY, self._record_ready)
            bus.on(EVENT_CALL_STATUS, self._call_status)
            bus.on(EVENT_SESSION, self._session)

    @property
    def agent(self):
        return self.app.call_agent

    @property
    def records(self):
        return self.app.call_agent.records

    @property
    def telephony(self):
        return self.app.telephony

    def owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def _spawn(self, coroutine):
        if self.closing:
            coroutine.close()
            return None
        task = asyncio.create_task(coroutine, name="call-orchestrator")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def _update(self, record_id, changes):
        try:
            return self.records.update_call(record_id, changes)
        except Exception:
            logger.exception("Call record could not be updated")
            return False

    def _link(self, source_id, record_id, name):
        if not record_id:
            return

        def add(other, extra=None):
            def changes(current):
                ids = [value for value in current.get("related_ids") or [] if isinstance(value, str)]
                return {"related_ids": [*ids, other] if other not in ids else ids, **(extra or {})}
            return changes

        self._update(source_id, add(record_id))
        self._update(record_id, add(source_id, {"name": name} if name else None))

    # --- owner briefings -----------------------------------------------------------------

    async def _record_ready(self, event):
        record_id = (event.data or {}).get("record_id")
        if isinstance(record_id, str):
            await self.consider_briefing(record_id)

    async def consider_briefing(self, record_id):
        """Apply the briefing policy to one stored record; returns True when placed."""
        if self.closing or record_id in self.inflight:
            return False
        try:
            record = self.records.get(record_id)
        except Exception:
            logger.exception("Call record could not be read for the briefing policy")
            return False
        if (record is None or record.get("source") != "twilio" or record.get("mode") != "screening"
                or record.get("direction") != "inbound" or record.get("briefing")
                or record.get("done") is True):
            return False
        settings = self.telephony.calls_settings()
        if not settings["enabled"]:
            return False
        moment = self.telephony.limits.local_now().time().replace(tzinfo=None)
        # P1: a VIP call whose triage failed, timed out or never ran (not a missed call
        # with nothing recorded) is still briefed, from the message as stored.
        untriaged = record.get("triage_state") in ("failed", "skipped") and not missed(record)
        if not should_brief(settings["brief_by_phone"], _triage(record), away=self.presence.away(),
                            quiet=in_quiet_hours(moment, settings["quiet_hours"]),
                            group=caller_group(record), untriaged=untriaged):
            return False
        credentials = self.telephony.credentials()
        owner_number = credentials["owner_number"] if credentials else None
        if not owner_number:
            logger.info("Owner briefing skipped: no owner number configured")
            return False
        brief = briefs.owner_briefing_brief(
            record, owner_number=owner_number, owner_name=briefs.owner_name(self.app.settings)
        )
        self.inflight[record_id] = "briefing"
        try:
            handle = await self.agent.call(brief)  # calls to the owner need no grant
        except ServiceError as exc:
            self.inflight.pop(record_id, None)
            logger.warning("Owner briefing could not be placed: %s", exc.code)
            self._update(record_id, {"briefing": {"state": "failed", "reason": exc.code,
                                                  "at": self.wall()}})
            return False
        except BaseException:
            self.inflight.pop(record_id, None)
            raise
        self._update(record_id, {"briefing": {"state": "calling", "call_id": handle.call_id,
                                              "at": self.wall()}})
        await self._placed(handle.call_id, "owner_briefing", record_id)
        self._spawn(self._after_briefing(record_id, handle))
        return True

    async def _result(self, handle):
        try:
            return await asyncio.wait_for(asyncio.shield(handle.result), RESULT_TIMEOUT)
        except TimeoutError:
            return None

    async def _after_briefing(self, record_id, handle):
        try:
            result = await self._result(handle)
        finally:
            self.inflight.pop(record_id, None)
        if result is None:
            self._update(record_id, {"briefing": {"state": "failed", "reason": "timeout",
                                                  "call_id": handle.call_id, "at": self.wall()}})
            return
        decision = result.fields.get("decision") if isinstance(result.fields, dict) else None
        action = decision.get("action") if isinstance(decision, dict) else None
        state = {"completed": "completed", "no_answer": "no_answer"}.get(result.state, "failed")
        self._link(record_id, result.record_id, None)
        self._update(record_id, {"briefing": {
            "state": state, "decision": action, "call_id": handle.call_id,
            "record_id": result.record_id, "at": self.wall(),
        }})
        if result.callback:
            approved, grant = result.callback
            await self._place_callback(record_id, approved, grant, origin="voice")

    # --- callbacks -------------------------------------------------------------------------

    async def _place_callback(self, record_id, brief, grant, *, origin):
        """Place one approved callback; returns (handle, None, None) or (None, code, message)."""
        self.inflight[record_id] = "callback"
        try:
            handle = await self.agent.call(brief, grant)
        except ServiceError as exc:
            self.inflight.pop(record_id, None)
            self.telephony.grants.revoke(grant.id)
            code = BLOCKED.get(exc.code)
            logger.warning("Approved callback not placed (%s): %s", origin, exc.code)
            if origin == "voice":
                self._update(record_id, {"callback": {
                    "state": "blocked" if code else "failed", "reason": code or exc.code,
                    "message": brief.message, "at": self.wall(),
                }})
                await self._notify(record_id)
            return None, code or exc.code, str(exc)
        except BaseException:
            self.inflight.pop(record_id, None)
            self.telephony.grants.revoke(grant.id)
            raise
        self._update(record_id, {"callback": {
            "state": "calling", "call_id": handle.call_id, "message": brief.message,
            "origin": origin, "at": self.wall(),
        }})
        await self._placed(handle.call_id, "approved_callback", record_id)
        self._spawn(self._after_callback(record_id, brief, handle, origin))
        return handle, None, None

    async def _after_callback(self, record_id, brief, handle, origin):
        try:
            result = await self._result(handle)
        finally:
            self.inflight.pop(record_id, None)
        state = "failed"
        if result is not None:
            state = {"completed": "completed", "no_answer": "no_answer"}.get(result.state, "failed")
            self._link(record_id, result.record_id, brief.caller_name or None)
        self._update(record_id, {"callback": {
            "state": state, "reason": None if state == "completed" else (
                (result.code if result else None) or state),
            "message": brief.message, "call_id": handle.call_id, "origin": origin,
            "record_id": result.record_id if result else None, "at": self.wall(),
        }})
        if state != "completed":
            await self._notify(record_id)

    async def approve_callback(self, record_id, message):
        """The owner approved a callback in the Calls view (that click is the approval)."""
        settings = self.telephony.calls_settings()
        if not settings["enabled"]:
            return _refused("calls_disabled", "Calls are turned off.")
        record = self.records.get(record_id)
        if record is None or record.get("source") != "twilio":
            raise ServiceError("not_found", "That call record no longer exists.")
        if record.get("mode") != "screening" or record.get("direction") != "inbound":
            return _refused("not_ready", "Only screened incoming calls can be called back.")
        number = callback_number(record)
        if number is None:
            return _refused("no_callback_number", "There is no callback number for this call.")
        if record_id in self.inflight or self.telephony.sessions:
            return _refused("busy", "JARVIS is on another call. Try again when it ends.")
        telephony = self.telephony
        if (telephony.credentials() is None or telephony.public_base_url() is None
                or not telephony.agent_ready()):
            return _refused("not_ready", "Calls are not ready yet. Check the Calls status.")
        try:
            telephony.limits.check(number, settings)
        except ServiceError as exc:
            return _refused(BLOCKED.get(exc.code, "not_ready"), str(exc))
        brief = briefs.CallBrief(
            mode="approved_callback",
            direction="outbound",
            counterpart=number,
            owner_name=briefs.owner_name(self.app.settings),
            message=message,
            caller_name=briefs.clean_line(str(_message(record).get("name") or ""), 80),
            source_record_id=record_id,
        )
        # Bound to exactly this number and this brief's hash; consumed by place_call.
        grant = telephony.grants.issue(number, brief.purpose())
        handle, code, text = await self._place_callback(record_id, brief, grant, origin="desktop")
        if handle is None:
            return _refused(code if code in BLOCKED.values() else "not_ready", text)
        return {"ok": True, "call_id": handle.call_id}

    # --- task calls (C4) ----------------------------------------------------------------------

    async def place_task_call(self, brief, request, *, owner, project, conversation_id):
        """The owner approved this task call on screen (that card is the authorization).
        Returns the tool result at once: placed with its id, or why nothing was dialled."""
        business = request.business_name

        def refused(code, reason):
            reason = reason.rstrip(".")
            return {
                "placed": False, "code": code,
                "message": f"I didn't call {business}: {reason[:1].lower() + reason[1:]}.",
            }

        telephony = self.telephony
        settings = telephony.calls_settings()
        if not settings["enabled"]:
            return refused("calls_disabled", "Calls are turned off. Turn them on in the Calls view first")
        if (telephony.credentials() is None or telephony.public_base_url() is None
                or not telephony.agent_ready()):
            return refused("not_ready", "Call setup isn't complete. Check the Calls view")
        if telephony.sessions or self.task_calls:
            return refused("busy", "JARVIS is on another call. Ask again when it ends")
        number = brief.counterpart
        try:
            telephony.limits.check(number, settings)
        except ServiceError as exc:
            return refused(BLOCKED.get(exc.code, "not_ready"), str(exc))
        # Bound to exactly this number and this brief's hash; consumed by place_call.
        grant = telephony.grants.issue(number, brief.purpose())
        try:
            handle = await self.agent.call(brief, grant)
        except ServiceError as exc:
            telephony.grants.revoke(grant.id)
            logger.warning("Task call not placed: %s", exc.code)
            return refused(BLOCKED.get(exc.code, exc.code), str(exc))
        except BaseException:
            telephony.grants.revoke(grant.id)
            raise
        task = {
            "call_id": handle.call_id, "request": request, "brief": brief, "owner": owner,
            "project": project, "conversation_id": conversation_id,
        }
        self.task_calls[handle.call_id] = task
        await self._placed(handle.call_id, "task", None)
        self._spawn(self._after_task(task, handle))
        return {
            "placed": True, "task_call_id": handle.call_id,
            "message": f"Calling {business} now — I'll report back.",
        }

    async def _after_task(self, task, handle):
        try:
            result = await self._result(handle)
        finally:
            self.task_calls.pop(handle.call_id, None)
        request = task["request"]
        if result is not None and result.record_id:
            self._update(result.record_id, {"name": request.business_name})
        reminder_at = None
        if task_calls.outcome_status(result) == "confirmed":
            reminder_at = await self._task_reminder(task, result)
        await self._report(task, task_calls.outcome_message(request, result, reminder_at))

    async def _task_reminder(self, task, result):
        """A reminder at the confirmed local time; None when it is past or not created."""
        request = task["request"]
        moment = task_calls.reminder_moment(request, result)
        if moment.timestamp() <= self.wall():
            return None
        from core.event_bus import event_owner

        token = event_owner.set(task["owner"])
        try:
            created = await self.app.scheduler.handle_tool_call("create_reminder", {
                "task": task_calls.reminder_task(request, task["brief"].constraints.booking_name),
                "when": moment.replace(tzinfo=None).isoformat(timespec="minutes"),
                "timezone": task_calls.ZONE_NAME,
            })
        except Exception:
            logger.exception("Task call reminder could not be created")
            return None
        finally:
            event_owner.reset(token)
        if not created.success:
            logger.warning("Task call reminder was refused")
            return None
        return moment

    async def _report(self, task, text):
        """Post the outcome once into the conversation the request came from, and live to
        the owner's renderers (``transcription``, a separate message)."""
        call_id = task["call_id"]
        if call_id in self.reported:
            return
        self.reported[call_id] = self.wall()
        while len(self.reported) > REPORTED_LIMIT:
            self.reported.pop(next(iter(self.reported)))
        owner, project, conversation_id = task["owner"], task["project"], task["conversation_id"]
        if conversation_id and project is not None:
            try:
                await self.app.conversation.append_turns(
                    owner, conversation_id, project, [{"role": "assistant", "content": text}]
                )
            except Exception:
                logger.warning("Task call outcome could not be added to the conversation",
                               exc_info=True)
        sessions = self.app.sessions
        if not sessions.authenticated(owner):
            return  # restored from the conversation history after unlocking
        payload = {
            "sender": "JARVIS", "text": text, "kind": "task_call_outcome",
            "request_id": f"task-call-{call_id}",
            **({"conversation_id": conversation_id} if conversation_id else {}),
            **({"project": project.name} if project is not None else {}),
        }
        try:
            for sid in sessions.rooms(owner, "renderer"):
                await self.app.sio.emit("transcription", payload, room=sid)
        except Exception:
            logger.warning("Task call outcome could not be delivered", exc_info=True)

    # --- Calls view --------------------------------------------------------------------------

    def people(self):
        """(by id, by number) from the owner's people list; None when it can't be read."""
        contacts = getattr(self.app, "contacts", None)
        if contacts is None:
            return None
        try:
            stored = contacts.people()
        except Exception as exc:
            logger.warning("People list could not be read for the Calls view: %s", type(exc).__name__)
            return None
        return ({item["id"]: item for item in stored},
                {number: item for item in stored for number in item["numbers"]})

    def list_calls(self, filter_name, limit):
        records = self.records.phone_calls()
        if filter_name == "needs_you":
            records = [item for item in records if needs_you(item)]
        elif filter_name == "done":
            records = [item for item in records if call_status(item) == "done"]
        elif filter_name == "spam":
            records = [item for item in records if spam(item)]
        people = self.people()
        return [summary_item(item, people) for item in records[:limit]]

    def get_call(self, record_id):
        records = self.records.phone_calls()
        record = next((item for item in records if item["id"] == record_id), None)
        if record is None:
            raise ServiceError("not_found", "That call record no longer exists.")
        contacts = getattr(self.app, "contacts", None)
        can_add = contacts is not None and contacts.call_number(record) is not None
        return detail_item(record, {item["id"] for item in records}, self.people(), can_add)

    def mark_done(self, record_id):
        if not self.records.update_call(record_id, {"done": True, "done_at": self.wall()}):
            raise ServiceError("not_found", "That call record no longer exists.")

    def delete(self, record_id):
        if not self.records.delete_call(record_id):
            raise ServiceError("not_found", "That call record no longer exists.")

    def draft(self, record_id):
        record = self.records.get(record_id)
        if record is None or record.get("source") != "twilio":
            raise ServiceError("not_found", "That call record no longer exists.")
        return callback_draft(record)

    def briefing_pin_set(self):
        try:
            return bool(BRIEFING_PIN.fullmatch(self.agent.briefing_pin()))
        except Exception:
            return False

    def status(self):
        """The calls_status extension (C3)."""
        try:
            count = sum(1 for item in self.records.phone_calls() if needs_you(item))
        except Exception:
            logger.warning("Call records could not be counted", exc_info=True)
            count = None
        self._prune_progress()
        active = max(self.progress.values(), key=lambda item: item["at"], default=None)
        return {
            "answering": self.telephony.calls_settings()["enabled"],
            "needs_you_count": count,
            "active_call": {key: active[key] for key in ("id", "mode", "direction", "state")}
            if active else None,
            "briefing_pin_set": self.briefing_pin_set(),
            # JARVIS's own Twilio number in E.164, for the carrier forwarding codes (owner-only).
            "jarvis_number": normalize(self.telephony.secret("twilio_phone_number")),
        }

    # --- opening a record from the tray (P1) ----------------------------------------------

    async def open_record(self, record_id):
        """A VIP balloon was clicked: the owner's renderers open Calls on that record. A
        workspace that is still starting picks it up when it connects (``hydrate``)."""
        if not isinstance(record_id, str):
            return
        self.open_target = (record_id, self.clock())
        owner = self.owner()
        if owner is None or not self.app.sessions.authenticated(owner):
            return
        sids = self.app.sessions.rooms(owner, "renderer")
        if sids:
            self.open_target = None
        try:
            for sid in sids:
                await self.app.sio.emit(EVENT_OPEN, {"record_id": record_id}, room=sid)
        except Exception:
            logger.warning("Calls open request could not be delivered", exc_info=True)

    async def hydrate(self, sid):
        """An owner renderer connected (and is unlocked): deliver a pending open request."""
        target, self.open_target = self.open_target, None
        if target is None or self.clock() - target[1] > OPEN_SECONDS:
            return
        await self.app.sio.emit(EVENT_OPEN, {"record_id": target[0]}, room=sid)

    # --- progress ------------------------------------------------------------------------------

    def _prune_progress(self):
        now = self.clock()
        for key in [key for key, item in self.progress.items() if now - item["at"] > PROGRESS_TTL]:
            del self.progress[key]
        for key in [key for key, stamp in self.ended.items() if now - stamp > PROGRESS_TTL]:
            del self.ended[key]

    async def _set_progress(self, call_id, state, *, mode=None, direction="outbound", record_id=None,
                            message=None):
        if call_id in self.ended:
            return
        self._prune_progress()
        entry = self.progress.get(call_id)
        if entry is None:
            entry = self.progress[call_id] = {
                "id": call_id, "mode": mode, "direction": direction, "record_id": record_id,
                "state": None, "at": self.clock(),
            }
        if record_id and not entry["record_id"]:
            entry["record_id"] = record_id
        if mode and not entry["mode"]:
            entry["mode"] = mode
        if entry["state"] == state or (
            state in RANK and RANK.get(entry["state"], -1) > RANK[state]
        ):
            return
        entry["state"], entry["at"] = state, self.clock()
        if state in DEFAULT_MESSAGES:
            entry["message"] = (message or DEFAULT_MESSAGES[state])[:200]
        if state in TERMINAL:
            self.progress.pop(call_id, None)
            self.ended[call_id] = self.clock()
        await self._emit_progress(entry)

    async def _placed(self, call_id, mode, record_id):
        await self._set_progress(call_id, "dialing", mode=mode, record_id=record_id)

    async def _call_status(self, event):
        data = event.data or {}
        call_id, state = data.get("call_id"), TWILIO_STATES.get(data.get("status"))
        if not isinstance(call_id, str) or state is None:
            return
        await self._set_progress(call_id, state, mode=self._mode(call_id),
                                 message=PROGRESS_MESSAGES.get(data.get("status")))

    def _mode(self, call_id, purpose=None):
        if purpose is None:
            record = self.telephony.outbound.get(call_id) or {}
            purpose = record.get("purpose")
        parts = purpose.split(":") if isinstance(purpose, str) else []
        if len(parts) == 3 and parts[0] == briefs.PURPOSE_PREFIX and parts[1] in briefs.MODES:
            return parts[1]
        return None

    async def _session(self, event):
        data = event.data or {}
        state = data.get("state")
        if data.get("direction") == "inbound":
            call_sid = data.get("call_sid")
            if state == "opened":
                call_id = self.inbound_ids[call_sid] = uuid.uuid4().hex
                await self._set_progress(call_id, "in_progress", mode="screening", direction="inbound")
            elif state == "closed" and call_sid in self.inbound_ids:
                await self._set_progress(self.inbound_ids.pop(call_sid), "completed")
            return
        call_id = data.get("call_id")
        if not isinstance(call_id, str):
            return
        mode = self._mode(call_id, data.get("purpose"))
        await self._set_progress(call_id, "in_progress" if state == "opened" else "completed", mode=mode)

    async def _emit_progress(self, entry):
        owner = self.owner()
        if owner is None or not self.app.sessions.authenticated(owner):
            return
        payload = {
            "call_id": entry["id"],
            "record_id": entry["record_id"],
            "mode": entry["mode"],
            "direction": entry["direction"],
            "state": entry["state"],
        }
        if entry["state"] in DEFAULT_MESSAGES:  # only failed / no_answer carry a message
            payload["message"] = entry.get("message") or DEFAULT_MESSAGES[entry["state"]]
        try:
            for sid in self.app.sessions.rooms(owner, "renderer"):
                await self.app.sio.emit(EVENT_PROGRESS, payload, room=sid)
        except Exception:
            logger.warning("Call progress could not be delivered", exc_info=True)

    async def _notify(self, record_id):
        """A record changed in a way the owner must see (a blocked or failed callback):
        ``call_record_ready`` to the owner's renderers, else a generic tray notice."""
        owner = self.owner()
        if owner is None:
            return
        sessions = self.app.sessions
        try:
            renderers = sessions.rooms(owner, "renderer")
            for sid in renderers:
                await self.app.sio.emit(EVENT_RECORD_READY, {"record_id": record_id}, room=sid)
            native = getattr(sessions, "native_desktop", None)
            if not renderers and native is not None:
                await native.notify({
                    "delivery_id": f"call-update:{record_id}:{int(self.wall())}", "notice": "call",
                })
        except Exception:
            logger.warning("Callback notice could not be delivered", exc_info=True)

    async def close(self):
        self.closing = True
        tasks = [task for task in self.tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _refused(code, message):
    return {"ok": False, "code": code, "message": message}


def migrate_briefing_pin(app):
    """Move a legacy ``calls.briefing_pin`` from settings.json into the encrypted secret
    store (``call_briefing_pin``), then drop it from settings. Never logs the value."""
    calls = app.settings.get("calls") if isinstance(app.settings, dict) else None
    if not isinstance(calls, dict) or "briefing_pin" not in calls:
        return False
    pin = calls.get("briefing_pin")
    try:
        if isinstance(pin, str) and BRIEFING_PIN.fullmatch(pin) and not app.secrets.get(
            "call_briefing_pin"
        ):
            app.secrets.set("call_briefing_pin", pin)
    except Exception as exc:
        # Left in settings: the call agent still honours it until a later start migrates it.
        logger.warning("Briefing PIN could not be moved to the secret store: %s", type(exc).__name__)
        return False
    calls.pop("briefing_pin", None)
    try:
        app.settings_service.store.save(app.settings_service.snapshot())
    except Exception as exc:
        logger.warning("Settings could not be saved after moving the briefing PIN: %s",
                       type(exc).__name__)
    logger.info("Moved the call briefing PIN into the encrypted secret store")
    return True
