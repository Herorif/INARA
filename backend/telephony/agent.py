"""The call agent (C2): a Twilio CallAudioSession bridged to one Gemini Live session.

``CallAgent`` is installed with ``TelephonyService.set_agent`` and awaited once per
connected call. Inbound calls are screened. Outbound calls run only for a brief this
process placed with ``CallAgent.call``: owner briefings go to the owner's number, and
approved callbacks and task calls need a C1 one-use grant for the exact number and brief
hash (``CallBrief.purpose``), which ``place_call`` consumes. The stream picks up its brief
by a single-use token in the call context, so a brief runs at most once.

Audio: caller mu-law 8 kHz -> PCM16 16 kHz (C1 media/audio) -> Live; Live PCM16 24 kHz ->
``session.send`` (resampled to 8 kHz mu-law). Live ``interrupted`` -> ``session.clear()``.
Automatic voice activity detection is on (phone calls are hands-free); context-window
compression and session resumption work as for desktop voice (services/live_config.py).
Caller audio is held until the opening disclosure has played, so it is always heard first.

Limits: ``calls.max_call_minutes`` (default 10, a warning one minute before), 20 s of
silence -> a polite check, then goodbye; ``end_call`` hangs up once Twilio has played
everything sent before a final mark. When the stream ends (caller hangs up, gateway
teardown, kill switch) the Live session closes at once.

Gaming and resident mode do NOT stop phone calls: the owner treats them as a priority.
Desktop voice checks ``ResourceGovernor.state`` and stops in those modes
(``VoiceService.require_resources``/``restrict``); the call agent deliberately never does,
and ``Application.restrict_resources`` does not include telephony.

After every call the structured record is stored in CallRecords (DPAPI, 7 days) before
anything else, then a triage step runs in the background and the owner is told
(``call_record_ready`` with the record id only, plus a generic tray notice). Usage: Live
turns are metered like desktop voice (feature ``call_live``) and Twilio minutes are
recorded as estimates (``call_twilio``, llm/pricing.py).
"""

import asyncio
from dataclasses import dataclass, field
import hmac
import math
import re
import secrets
import time
import uuid

from pydantic import ValidationError

from calls.records import CallRecords
from core.event_bus import Event
from llm.base import Message, MessageRole
from services.capability_profiles import model_id
from services.live_config import INPUT_RATE, OUTPUT_RATE, live_connect_config, voice_settings
from services.log import get_logger
from services.tools import ServiceError
from services.usage import live_usage_counts
from telephony import briefs, triage
from telephony.media import SEND_RATES, StreamClosed
from telephony.numbers import mask_sid, normalize, same_number, withheld

logger = get_logger("telephony.agent")

EVENT_RECORD_READY = "call_record_ready"
EVENT_VIP_ALERT = "call_vip_alert"  # P1: {record_id, name, summary} to the owner's renderers
VIP_LEFT_MESSAGE = "Left a message."  # a VIP alert's text before (or without) a summary
EVENT_CALL_STATUS = "telephony.call_status"  # telephony.service
TERMINAL_STATUSES = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})
BRIEFING_PIN = re.compile(r"[0-9]{4,8}")
WARN_BEFORE_END = 60
SILENCE_SECONDS = 20
SILENCE_END_SECONDS = 10
END_GRACE_SECONDS = 10  # an ending call's goodbye turn has this long to finish
PLAYBACK_TIMEOUT = 15  # waiting for Twilio to play the last audio before hanging up
OPENING_TIMEOUT = 12  # caller audio is held until the disclosure has played, at most this
QUEUED_FRAMES = 150  # about three seconds of caller audio while Live connects or resumes
RECONNECT_ATTEMPTS = 3
PENDING_SECONDS = 300.0
PIN_ATTEMPTS = 3
CAPTION_LIMIT = 4000
TRANSCRIPT_SEGMENTS = 400
TRANSCRIPT_CHARS = 40_000
PCM_MIME = f"audio/pcm;rate={INPUT_RATE}"
MODE_TOOLS = {
    "screening": {"record_message", "end_call"},
    "owner_briefing": {"verify_pin", "record_owner_decision", "end_call"},
    "approved_callback": {"record_outcome", "end_call"},
    "task": {"record_outcome", "end_call"},
}


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class CallResult:
    record_id: str | None  # None when the call never ran (refused or expired)
    mode: str
    direction: str
    state: str  # completed | failed | refused | no_answer
    outcome: dict
    fields: dict
    duration_seconds: float
    code: str | None = None
    # A confirmed owner decision to call back: (approved CallBrief, one-use CallGrant).
    # C3 places it with CallAgent.call before the grant expires (10 minutes).
    callback: tuple | None = None


@dataclass(eq=False)
class PendingCall:
    brief: briefs.CallBrief
    future: asyncio.Future
    created: float
    call_id: str | None = None
    call_sid: str | None = None


@dataclass
class CallHandle:
    call_id: str
    call_sid: str
    result: asyncio.Future  # resolves to a CallResult


@dataclass(eq=False)
class CallRun:
    brief: briefs.CallBrief
    session: object
    record_id: str
    started: float
    started_wall: float
    max_seconds: float
    instruction: str
    declarations: list
    pin: str = field(default="", repr=False)  # never logged
    contact_id: str | None = None  # P1: the matched person (telephony/contacts.py)
    outbound: asyncio.Queue = field(default_factory=asyncio.Queue)
    opening_done: asyncio.Event = field(default_factory=asyncio.Event)
    opening_started: float | None = None
    kicked_off: bool = False
    queued_audio: int = 0
    dropped_audio: int = 0
    live: object = None
    handle: str | None = None
    go_away: bool = False
    connected: bool = False
    closed: bool = False
    last_caller: float = 0.0
    last_jarvis: float = 0.0
    silence_checked: float | None = None
    warned: bool = False
    ending: str | None = None
    ending_at: float | None = None
    hanging_up: bool = False
    hung_up_after_mark: bool = False
    caller_text: str = ""
    jarvis_text: str = ""
    turn_audio: bool = False
    transcript: list = field(default_factory=list)
    transcript_chars: int = 0
    truncated: bool = False
    fields: dict = field(default_factory=dict)
    pending_decision: dict | None = None
    heard_since_readback: str = ""
    pin_verified: bool = False
    pin_attempts: int = 0
    callback: tuple | None = None
    failure: str | None = None
    usage: object = None
    ticket: dict | None = None
    ticket_started: float = 0.0
    tasks: set = field(default_factory=set)


def _live_defaults():
    from services.voice import connect_live, ready

    return connect_live, ready


def _failure_code(exc):
    from services.voice import failure_code

    return failure_code(exc)[0]


class CallAgent:
    def __init__(self, app, *, connector=None, preflight=None, clock=time.monotonic,
                 wall=time.time, triage_provider=None):
        self.app = app
        self._connector, self._preflight = connector, preflight
        self.clock, self.wall = clock, wall
        self.records = CallRecords(app.database, clock=wall)
        self.triage_provider = triage_provider or self._fast_provider
        self.pending = {}  # brief token -> PendingCall (single use)
        self.placed = {}  # C1 call_id -> brief token, until the call ends
        self.runs = {}  # CallSid -> CallRun
        self.tasks = set()  # triage and notices, outliving their call
        self.closing = False
        self.tick = 1.0
        self.retry_delay = 0.5
        self.silence_seconds = SILENCE_SECONDS
        self.silence_end_seconds = SILENCE_END_SECONDS
        bus = getattr(app, "bus", None)
        if bus is not None:
            bus.on(EVENT_CALL_STATUS, self._call_status)

    # --- configuration ----------------------------------------------------------------------

    @property
    def connector(self):
        return self._connector or _live_defaults()[0]

    def preflight(self):
        (self._preflight or _live_defaults()[1])()

    def available(self):
        """True when Live voice can run (Gemini key and SDK); else calls go to voicemail."""
        try:
            self.preflight()
            return True
        except ServiceError:
            return False

    def settings(self):
        return self.app.telephony.calls_settings()

    def owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def usage_scope(self):
        return self.owner() or "telephony", self.app.projects.get_current_project_path()

    def _fast_provider(self):
        from llm.router import TaskRouter

        return TaskRouter(lambda: self.app.settings).provider("fast")

    def config(self, run):
        ticket = run.ticket
        return live_connect_config(
            system_instruction=run.instruction,
            voice_name=voice_settings(self.app.settings)["name"],
            function_declarations=run.declarations,
            automatic_activity_detection=True,  # hands-free: server VAD and barge-in
            handle=run.handle,
            max_output_tokens=ticket["max_output_tokens"] if ticket and ticket["capped"] else None,
        )

    # --- entry points ---------------------------------------------------------------------

    async def __call__(self, session):
        """TelephonyService agent: one connected Media Stream."""
        info = session.info or {}
        if info.get("direction", session.direction) == "inbound":
            # P1: the owner's saved person for this caller ID, if any (VIP, known, blocked).
            person = self.match_caller(info.get("from"))
            # Validated calls.* values (a malformed facts pack falls back to none).
            brief = briefs.screening_brief(
                info, {**self.app.settings, "calls": self.settings()}, person=person
            )
            return await self._run(session, brief, None,
                                   contact_id=person["id"] if person and brief.caller_group else None)
        context = info.get("context") if isinstance(info.get("context"), dict) else {}
        token = context.get("brief")
        pending = self.pending.pop(token, None) if isinstance(token, str) else None
        if pending is None or not self._matches(pending, info):
            logger.warning(
                "Outbound call %s has no approved brief; hanging up", mask_sid(session.call_sid)
            )
            if pending is not None and not pending.future.done():
                pending.future.set_result(_unconnected(pending.brief, "refused", "call_brief_mismatch"))
            await session.hangup()
            return None
        return await self._run(session, pending.brief, pending)

    def match_caller(self, number):
        """The owner's saved person for a caller ID, or None (never raises; never logs the
        number, name or note)."""
        contacts = getattr(self.app, "contacts", None)
        if contacts is None:
            return None
        try:
            return contacts.match(number)
        except Exception as exc:
            logger.warning("People list could not be read for a call: %s", type(exc).__name__)
            return None

    def _matches(self, pending, info):
        brief = pending.brief
        if self.clock() - pending.created > PENDING_SECONDS:
            return False
        if not same_number(info.get("to"), brief.counterpart):
            return False
        return bool(info.get("owner")) == (brief.mode == "owner_briefing")

    async def call(self, brief, grant=None):
        """Place one outbound call for ``brief``; returns a CallHandle (``await handle.result``).

        Owner briefings need the owner's number. Approved callbacks and task calls need a
        valid one-use grant for ``brief.counterpart`` and ``brief.purpose()``; it is checked
        and consumed by ``TelephonyService.place_call`` before Twilio is asked to ring.
        """
        if not isinstance(brief, briefs.CallBrief):
            brief = briefs.CallBrief.model_validate(brief)
        if brief.direction != "outbound":
            raise ServiceError("invalid_arguments", "Only outbound briefs can be placed.")
        telephony = self.app.telephony
        credentials = telephony.credentials()
        if credentials is None:
            raise ServiceError("calls_not_configured", "Add the Twilio details first.")
        owner = same_number(brief.counterpart, credentials["owner_number"])
        if brief.mode == "owner_briefing" and not owner:
            raise ServiceError("call_brief_mismatch", "Owner briefings go only to the owner's number.")
        if brief.mode in briefs.GRANTED_MODES:
            if owner:
                raise ServiceError("call_brief_mismatch", "Callbacks and task calls are for other people.")
            if grant is None:
                raise ServiceError(
                    "call_grant_required", "Calls to anyone but the owner need the owner's approval."
                )
        self.preflight()
        self._prune_pending()
        token = secrets.token_urlsafe(16)
        pending = PendingCall(brief, asyncio.get_running_loop().create_future(), self.clock())
        self.pending[token] = pending
        try:
            placed = await telephony.place_call(
                brief.counterpart, brief.purpose(), {"brief": token, "mode": brief.mode},
                grant=grant,
            )
        except BaseException:
            self.pending.pop(token, None)
            raise
        pending.call_id, pending.call_sid = placed["call_id"], placed["call_sid"]
        self.placed[placed["call_id"]] = token
        return CallHandle(placed["call_id"], placed["call_sid"], pending.future)

    def _prune_pending(self):
        now = self.clock()
        for token, pending in list(self.pending.items()):
            if now - pending.created > PENDING_SECONDS:
                del self.pending[token]
                if pending.call_id:
                    self.placed.pop(pending.call_id, None)
                if not pending.future.done():
                    pending.future.set_result(_unconnected(pending.brief, "refused", "call_expired"))

    async def _call_status(self, event):
        """A placed call that ended without a stream: record it as not answered."""
        data = event.data or {}
        status, call_id = data.get("status"), data.get("call_id")
        if status not in TERMINAL_STATUSES or call_id not in self.placed:
            return
        token = self.placed.pop(call_id)
        pending = self.pending.pop(token, None)
        if pending is None:
            return  # the stream ran; its own result is already resolved
        state = "failed" if status == "failed" else "no_answer"
        now = self.wall()
        record = {
            "id": str(uuid.uuid4()),
            "source": "twilio",
            "state": state,
            "direction": "outbound",
            "mode": pending.brief.mode,
            "counterpart": self.records.counterpart(pending.brief.counterpart),
            "started_at": now,
            "finished_at": now,
            "duration_seconds": 0.0,
            "fields": {},
            "transcript": [],
            "outcome": {"status": "no_answer", "twilio_status": status},
            "end_reason": status,
            "brief_hash": pending.brief.hash(),
            "triage_state": "skipped",
            "identity_verified": False,
            "message_confirmed": False,
        }
        try:
            self.records.save_call(record)
        except Exception:
            logger.exception("Unanswered call record could not be saved")
        if not pending.future.done():
            pending.future.set_result(CallResult(
                record["id"], pending.brief.mode, "outbound", state, record["outcome"], {}, 0.0,
            ))
        self._spawn(self._announce(record["id"]))

    # --- one call ---------------------------------------------------------------------------

    def briefing_pin(self):
        """The owner-briefing PIN from the encrypted secret store (``call_briefing_pin``), or
        "" for none. A legacy ``calls.briefing_pin`` still in settings (its startup migration
        failed) is honoured rather than silently dropping the PIN. Never logged."""
        pin = self.app.telephony.secret("call_briefing_pin") or ""
        if not BRIEFING_PIN.fullmatch(pin):
            calls = self.app.settings.get("calls") if isinstance(self.app.settings, dict) else None
            legacy = calls.get("briefing_pin") if isinstance(calls, dict) else None
            pin = legacy if isinstance(legacy, str) and BRIEFING_PIN.fullmatch(legacy) else ""
        return pin

    def inbound_refusal(self, params):
        """C3: the usage budget is exhausted, so an inbound call cannot be screened. Stores a
        minimal record ("missed", reason "budget"), tells the owner, and returns the code so
        the gateway answers with voicemail; None when the call can go ahead."""
        owner, _project = self.usage_scope()
        try:
            code = self.app.usage.admission_blocked(owner)
        except Exception:
            logger.warning("Usage budget could not be checked", exc_info=True)
            return None
        if code is None:
            return None
        caller = (params or {}).get("From")
        now = self.wall()
        try:
            counterpart = self.records.counterpart(caller)
        except Exception:
            counterpart = {"masked": "withheld", "key": None}
        person = self.match_caller(caller)
        group = person.get("group") if person else None
        record = {
            "id": str(uuid.uuid4()),
            "source": "twilio",
            "state": "missed",
            "caller_number": caller_number(caller),
            "caller_group": group,
            "contact_id": person["id"] if person else None,
            "code": code,
            "direction": "inbound",
            "mode": "screening",
            "counterpart": counterpart,
            "caller_hash": counterpart["key"],
            "started_at": now,
            "finished_at": now,
            "duration_seconds": 0.0,
            "fields": {},
            "transcript": [],
            "outcome": {"status": "missed", "reason": "budget"},
            "end_reason": "voicemail",
            "brief_hash": None,
            "triage": None,
            "triage_state": "skipped",
            "identity_verified": False,
            "message_confirmed": False,
        }
        try:
            self.records.save_call(record)
        except Exception:
            logger.exception("Missed call record could not be saved")
            return code
        if group != "blocked":  # P1: a blocked caller's call is a quiet Spam record
            vip = {"name": person["name"]} if group == "vip" else None
            self._spawn(self._announce(record["id"], vip=vip))
        return code

    def _new_run(self, session, brief, contact_id=None):
        settings = self.settings()
        pin = self.briefing_pin() if brief.mode == "owner_briefing" else ""
        now = self.clock()
        return CallRun(
            brief=brief,
            session=session,
            record_id=str(uuid.uuid4()),
            started=now,
            started_wall=self.wall(),
            max_seconds=float(settings.get("max_call_minutes", 10)) * 60,
            instruction=briefs.system_instruction(brief, now=self.wall(), pin_required=bool(pin)),
            declarations=briefs.declarations(brief.mode, pin_required=bool(pin),
                                             caller_group=brief.caller_group),
            pin=pin,
            contact_id=contact_id,
            last_caller=now,
            last_jarvis=now,
        )

    async def _run(self, session, brief, pending, *, contact_id=None):
        run = self._new_run(session, brief, contact_id)
        self.runs[session.call_sid] = run
        tasks = []
        result = None
        try:
            owner, project = self.usage_scope()
            try:
                run.usage = self.app.usage.operation(owner, project, "call_live", run.record_id)
                # Admission before any provider connection, per Live turn like desktop voice.
                run.ticket, run.ticket_started = run.usage.begin(model_id("voice")), self.clock()
            except ServiceError as exc:
                run.failure = exc.code
                logger.warning("Call %s refused: %s", mask_sid(session.call_sid), exc.code)
            if run.failure:
                await self._hangup(run)
            else:
                tasks = self._start(run)
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if not session.closed.is_set():
                    await self._hangup(run)  # a part of the bridge stopped: never leave a silent line
        finally:
            # Bookkeeping first and synchronously: the gateway cancels a slow agent.
            run.closed = True
            result = self._finish(run)
            self.runs.pop(session.call_sid, None)
            if pending is not None and not pending.future.done():
                pending.future.set_result(result)
            for task in [*tasks, *run.tasks]:
                task.cancel()
            if tasks or run.tasks:
                await asyncio.wait([*tasks, *run.tasks], timeout=2)
        return result

    def _start(self, run):
        return [
            asyncio.create_task(self._pump(run), name="call-agent-audio"),
            asyncio.create_task(self._live(run), name="call-agent-live"),
            asyncio.create_task(self._watch(run), name="call-agent-watchdog"),
            asyncio.create_task(run.session.closed.wait(), name="call-agent-closed"),
        ]

    # --- audio -----------------------------------------------------------------------------

    async def _pump(self, run):
        """Caller audio (PCM16 16 kHz from C1) -> Live, after the disclosure has played."""
        async for frame in run.session:
            if run.closed:
                return
            if not run.opening_done.is_set():
                continue
            if run.queued_audio >= QUEUED_FRAMES:
                run.dropped_audio += 1
                continue
            run.queued_audio += 1
            run.outbound.put_nowait(("audio", frame))

    async def _live(self, run):
        attempts = 0
        try:
            while not run.closed:
                run.go_away = False
                try:
                    async with self.connector(model_id("voice"), self.config(run)) as live:
                        run.live, run.connected, attempts = live, True, 0
                        if not run.kicked_off:
                            run.kicked_off = True
                            run.opening_started = self.clock()
                            run.outbound.put_nowait(("text", briefs.kickoff(run.brief)))
                        sender = asyncio.create_task(self._send(run, live))
                        receiver = asyncio.create_task(self._receive(run, live))
                        try:
                            done, _ = await asyncio.wait(
                                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                            )
                            for task in done:
                                task.result()
                        finally:
                            for task in (sender, receiver):
                                task.cancel()
                            await asyncio.gather(sender, receiver, return_exceptions=True)
                            run.live = None
                    if run.closed:
                        return
                    if not run.go_away:
                        raise ConnectionError("Live connection ended")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    attempts += 1
                    if run.closed:
                        return
                    if run.connected and run.handle and attempts <= RECONNECT_ATTEMPTS:
                        logger.info("Call Live session dropped; resuming (%s)", type(exc).__name__)
                        await asyncio.sleep(self.retry_delay * attempts)
                        continue
                    run.failure = _failure_code(exc)
                    logger.warning("Call Live session failed: %s", type(exc).__name__)
                    await self._hangup(run)
                    return
        finally:
            run.live = None

    async def _send(self, run, live):
        from google.genai import types

        while True:
            kind, value = await run.outbound.get()
            if kind == "audio":
                run.queued_audio = max(0, run.queued_audio - 1)
                await live.send_realtime_input(audio=types.Blob(data=value, mime_type=PCM_MIME))
            elif kind == "text":
                await live.send_realtime_input(text=value)
            elif kind == "tool":
                await live.send_tool_response(function_responses=value)

    async def _receive(self, run, live):
        while not run.closed:
            received = False
            async for message in live.receive():
                received = True
                await self._handle(run, message)
                if run.go_away or run.closed:
                    return
            if not received:
                raise ConnectionError("Live stream closed")

    async def _handle(self, run, message):
        update = getattr(message, "session_resumption_update", None)
        if update and update.resumable and update.new_handle:
            run.handle = update.new_handle
        if getattr(message, "go_away", None) is not None:
            run.go_away = True
        if getattr(message, "usage_metadata", None) is not None:
            self._usage(run, message.usage_metadata)
        call = getattr(message, "tool_call", None)
        if call:
            for function in call.function_calls or []:
                self._tool(run, function)
        content = getattr(message, "server_content", None)
        if content is None:
            return
        now = self.clock()
        if content.input_transcription and content.input_transcription.text:
            text = content.input_transcription.text
            run.caller_text = (run.caller_text + text)[-CAPTION_LIMIT:]
            run.heard_since_readback = (run.heard_since_readback + text)[-CAPTION_LIMIT:]
            run.last_caller = now
        if content.interrupted:
            # Barge-in: Twilio drops what it has not played yet.
            await run.session.clear()
            self._flush(run)
        if content.model_turn and content.model_turn.parts:
            for part in content.model_turn.parts:
                data = getattr(part, "inline_data", None)
                mime = str(getattr(data, "mime_type", "") or "") if data else ""
                if data and data.data and mime.startswith("audio/pcm"):
                    run.last_jarvis, run.turn_audio = now, True
                    try:
                        await run.session.send(data.data, _rate(mime))
                    except StreamClosed:
                        return
        if content.output_transcription and content.output_transcription.text:
            run.jarvis_text = (run.jarvis_text + content.output_transcription.text)[-CAPTION_LIMIT:]
        if content.turn_complete:
            await self._turn_complete(run)

    async def _turn_complete(self, run):
        self._flush(run)
        audio, run.turn_audio = run.turn_audio, False
        if run.ending is not None:
            self._spawn_run(run, self._end_after_playback(run))
        elif not run.opening_done.is_set():
            self._spawn_run(run, self._finish_opening(run))
        elif audio:
            try:
                await run.session.mark()  # keeps ``session.playing`` true until played
            except StreamClosed:
                pass

    async def _finish_opening(self, run):
        try:
            mark = await run.session.mark("jarvis-opening")
            await asyncio.wait_for(mark, OPENING_TIMEOUT)
        except (StreamClosed, TimeoutError):
            pass
        run.opening_done.set()
        if run.brief.caller_group == "blocked" and run.ending is None:
            # P1: the opening line already said goodbye to a blocked caller; end the call
            # even if the model never calls end_call.
            self._begin_ending(run, "blocked")
            self._spawn_run(run, self._end_after_playback(run))

    async def _end_after_playback(self, run):
        """Hang up once Twilio has played everything sent before the final mark."""
        if run.hanging_up:
            return
        run.hanging_up = True
        try:
            mark = await run.session.mark("jarvis-end")
            played = await asyncio.wait_for(mark, PLAYBACK_TIMEOUT)
        except StreamClosed:
            return
        except TimeoutError:
            played = True
        if not played and not run.session.closed.is_set():
            # The goodbye was interrupted: let the next turn finish, within a fresh grace.
            run.hanging_up, run.ending_at = False, self.clock()
            return
        run.hung_up_after_mark = True
        await self._hangup(run)

    async def _hangup(self, run):
        try:
            # Shielded: the run cancels its helpers as soon as the stream reports closed,
            # and the WebSocket close that follows must still complete.
            await asyncio.shield(run.session.hangup())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Ending a call failed", exc_info=True)

    def _spawn_run(self, run, coroutine):
        task = asyncio.create_task(coroutine)
        run.tasks.add(task)
        task.add_done_callback(run.tasks.discard)

    def _nudge(self, run, text):
        if not run.closed:
            run.outbound.put_nowait(("text", text))

    def _begin_ending(self, run, reason):
        if run.ending is None:
            run.ending, run.ending_at = reason, self.clock()

    # --- watchdog: limits and silence ---------------------------------------------------

    async def _watch(self, run):
        try:
            while not run.closed:
                await asyncio.sleep(self.tick)
                if run.closed:
                    return
                now = self.clock()
                if run.session.playing:
                    run.last_jarvis = now  # JARVIS is still being heard
                if (not run.opening_done.is_set() and run.opening_started is not None
                        and now - run.opening_started > OPENING_TIMEOUT):
                    run.opening_done.set()
                elapsed = now - run.started
                if not run.warned and elapsed >= run.max_seconds - WARN_BEFORE_END:
                    run.warned = True
                    self._nudge(run, briefs.NUDGE_ONE_MINUTE)
                if elapsed >= run.max_seconds and run.ending is None:
                    self._nudge(run, briefs.NUDGE_TIME_UP)
                    self._begin_ending(run, "time_limit")
                if elapsed >= run.max_seconds + END_GRACE_SECONDS + PLAYBACK_TIMEOUT:
                    run.ending = run.ending or "time_limit"
                    await self._hangup(run)  # hard stop
                    return
                if run.ending is not None:
                    if not run.hanging_up and now - run.ending_at > END_GRACE_SECONDS:
                        self._spawn_run(run, self._end_after_playback(run))
                    continue
                quiet = now - max(run.last_caller, run.last_jarvis)
                if run.silence_checked is None:
                    if quiet >= self.silence_seconds:
                        run.silence_checked = now
                        self._nudge(run, briefs.NUDGE_SILENCE_CHECK)
                elif run.last_caller > run.silence_checked:
                    run.silence_checked = None  # the caller answered
                elif now - max(run.silence_checked, run.last_jarvis) >= self.silence_end_seconds:
                    self._nudge(run, briefs.NUDGE_SILENCE_END)
                    self._begin_ending(run, "silence")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Call watchdog failed")
            await self._hangup(run)

    # --- captions -------------------------------------------------------------------------------

    def _flush(self, run):
        for role, attribute in (("caller", "caller_text"), ("assistant", "jarvis_text")):
            text = getattr(run, attribute).strip()
            setattr(run, attribute, "")
            if not text:
                continue
            if run.pin:  # a spoken (or repeated) briefing PIN never reaches the record
                text = briefs.redact_pin(text, run.pin)
            if (len(run.transcript) >= TRANSCRIPT_SEGMENTS
                    or run.transcript_chars + len(text) > TRANSCRIPT_CHARS):
                run.truncated = True
                continue
            run.transcript_chars += len(text)
            run.transcript.append({"role": role, "text": text})

    # --- tools ------------------------------------------------------------------------------

    def _respond(self, run, call, response):
        from google.genai import types

        if not run.closed:
            run.outbound.put_nowait(
                ("tool", [types.FunctionResponse(id=call.id, name=call.name, response=response)])
            )

    def _tool(self, run, call):
        run.last_jarvis = self.clock()
        args = call.args if isinstance(call.args, dict) else {}
        try:
            if call.name not in MODE_TOOLS[run.brief.mode] or (
                call.name == "verify_pin" and not run.pin
            ) or (run.brief.caller_group == "blocked" and call.name != "end_call"):
                raise ToolError("tool_unavailable", "That tool is not available on this call.")
            response = getattr(self, "_tool_" + call.name)(run, args)
        except ValidationError as exc:
            errors = exc.errors()
            message = str(errors[0].get("msg", "Invalid arguments.")) if errors else "Invalid arguments."
            response = {"is_error": True, "error": "invalid_arguments", "message": message[:200]}
        except ToolError as exc:
            response = {"is_error": True, "error": exc.code, "message": exc.message}
        except Exception:
            logger.exception("Call tool %s failed", call.name)
            response = {"is_error": True, "error": "tool_failed", "message": "That did not work."}
        self._respond(run, call, response)

    def _tool_end_call(self, run, args):
        value = briefs.EndCall.model_validate(args)
        self._begin_ending(run, value.reason)
        return {"result": "Say a short goodbye now if you have not; the line closes when you finish."}

    def _tool_record_message(self, run, args):
        value = briefs.RecordMessage.model_validate(args)
        run.fields["message"] = value.model_dump()
        owner = run.brief.owner_name or "the owner"
        return {
            "result": f"Message saved. Tell the caller it will be passed on to {owner}, without "
            "saying when they will hear back. Then say goodbye and call end_call."
        }

    def _tool_verify_pin(self, run, args):
        if run.pin_verified:
            return {"result": "The PIN is already verified."}
        value = briefs.VerifyPin.model_validate(args)
        digits = re.sub(r"\D", "", value.pin)
        if hmac.compare_digest(digits.encode(), run.pin.encode()):
            run.pin_verified = True
            return {"result": "PIN verified. Brief the owner now.",
                    "call_details": briefs.briefing_details(run.brief)}
        run.pin_attempts += 1
        if run.pin_attempts >= PIN_ATTEMPTS:
            self._begin_ending(run, "pin_failed")
            raise ToolError("pin_locked", "Too many wrong PINs. Say you can't continue and goodbye.")
        raise ToolError("pin_incorrect", "That PIN is not correct. Ask the owner to say it again.")

    def _tool_record_owner_decision(self, run, args):
        if run.pin and not run.pin_verified:
            raise ToolError("pin_required", "Verify the owner's briefing PIN first.")
        if run.fields.get("decision"):
            raise ToolError("decision_recorded", "A decision is already recorded for this briefing.")
        value = briefs.OwnerDecision.model_validate(args)
        proposal = {"action": value.action, "message_for_caller": value.message_for_caller}
        if not value.confirmed:
            run.pending_decision, run.heard_since_readback = proposal, ""
            readback = briefs.decision_readback(value, run.brief)
            return {
                "result": "Read this back to the owner and ask for an explicit yes.",
                "readback": readback,
            }
        if run.pending_decision != proposal:
            raise ToolError(
                "readback_required",
                "Read the decision back first: call record_owner_decision with confirmed=false.",
            )
        if not briefs.explicit_yes(run.heard_since_readback):
            raise ToolError(
                "confirmation_required",
                "The owner's explicit yes was not heard after the read-back. Ask again.",
            )
        decision = {**proposal, "confirmed": True, "confirmed_at": self.wall()}
        if value.action == "callback":
            approved = briefs.callback_brief(run.brief, value.message_for_caller)
            if approved is None:
                raise ToolError(
                    "no_callback_number",
                    "There is no callback number on record, so JARVIS can't call back. "
                    "Tell the owner they will need to handle it.",
                )
            grant = self.app.telephony.grants.issue(approved.counterpart, approved.purpose())
            run.callback = (approved, grant)
            decision.update(callback_brief_hash=approved.hash(), grant_expires_at=grant.expires_at)
        run.fields["decision"] = decision
        run.pending_decision = None
        return {"result": "Decision recorded. Tell the owner it is done, then say goodbye and call end_call."}

    def _tool_record_outcome(self, run, args):
        value = briefs.RecordOutcome.model_validate(args)
        run.fields["outcome"] = value.model_dump()
        return {"result": "Outcome recorded. Say goodbye and call end_call."}

    # --- usage -------------------------------------------------------------------------------

    def _finish_ticket(self, run, counts):
        ticket, run.ticket = run.ticket, None
        if ticket:
            self.app.usage.finish(
                ticket, "completed" if counts else "uncertain", counts, self.clock() - run.ticket_started
            )

    def _usage(self, run, metadata):
        counts = live_usage_counts(metadata)
        if not counts:
            return
        self._finish_ticket(run, counts)
        try:
            run.ticket, run.ticket_started = run.usage.begin(model_id("voice")), self.clock()
        except ServiceError as exc:
            # Budget reached mid-call: wrap up politely instead of cutting the caller off.
            logger.warning("Call usage admission stopped: %s", exc.code)
            self._nudge(run, briefs.NUDGE_WRAP_UP)
            self._begin_ending(run, "usage_limit")

    def _twilio_estimate(self, run, duration):
        if duration <= 0:
            return
        brief = run.brief
        mobile = brief.direction == "outbound" and (brief.counterpart or "").startswith("+601")
        model = "twilio-voice-my-mobile" if mobile else "twilio-voice-my-local"
        owner, project = self.usage_scope()
        try:
            self.app.usage.record_estimate(
                owner, project, "call_twilio", run.record_id, model,
                {"call_minutes": max(1, math.ceil(duration / 60))}, duration,
            )
        except Exception:
            logger.warning("Twilio minute estimate could not be recorded", exc_info=True)

    # --- after the call ------------------------------------------------------------------------

    def _outcome(self, run):
        mode, fields = run.brief.mode, run.fields
        if run.failure:
            status = "failed"
        elif mode == "screening" and run.brief.caller_group == "blocked":
            status = "blocked"
        elif mode == "screening":
            status = "message_taken" if fields.get("message") else "no_message"
        elif mode == "owner_briefing":
            decision = fields.get("decision")
            status = decision["action"] if decision else "no_decision"
        else:
            status = fields["outcome"]["status"] if fields.get("outcome") else "no_outcome"
        ended_by = (
            "jarvis" if run.hung_up_after_mark or run.session.end_reason == "agent_hangup"
            else "caller" if run.session.end_reason in ("stopped", "disconnected")
            else "gateway"
        )
        return {"status": status, "ended_by": ended_by, "reason": run.ending}

    def _finish(self, run):
        """Store the structured record (synchronously), meter, schedule triage."""
        self._flush(run)
        duration = round(max(0.0, self.clock() - run.started), 3)
        try:
            self._finish_ticket(run, None)
        except Exception:
            logger.warning("Call usage receipt could not be finished", exc_info=True)
        brief, session = run.brief, run.session
        state = "failed" if run.failure else "completed"
        outcome = self._outcome(run)
        group = brief.caller_group if brief.mode == "screening" else None
        blocked = group == "blocked"
        try:
            counterpart = self.records.counterpart(brief.counterpart)
        except Exception:
            counterpart = {"masked": "withheld", "key": None}
        record = {
            "id": run.record_id,
            "source": "twilio",
            "state": state,
            "code": run.failure,
            "direction": brief.direction,
            "mode": brief.mode,
            "counterpart": counterpart,
            "caller_hash": counterpart["key"],
            "started_at": run.started_wall,
            "finished_at": self.wall(),
            "duration_seconds": duration,
            # P1: a blocked caller's record is minimal: no message and no transcript.
            "fields": {} if blocked else {key: value for key, value in run.fields.items()},
            "transcript": [] if blocked else list(run.transcript),
            "transcript_truncated": False if blocked else run.truncated,
            "outcome": outcome,
            "end_reason": session.end_reason,
            "brief_hash": brief.hash() if brief.direction == "outbound" else None,
            "source_record_id": _source_record(brief),
            "identity_verified": run.pin_verified,
            "message_confirmed": bool(run.fields.get("message")) and not blocked,
            "triage": None,
            "triage_state": "skipped" if blocked else "pending",
        }
        if brief.direction == "inbound":
            # P1: the caller's group at call time, the matched person and the caller ID
            # (E.164, protected with the record; it never leaves the core unmasked except
            # into the owner's own people list).
            record.update(caller_group=group, contact_id=run.contact_id,
                          caller_number=brief.counterpart)
        saved = False
        try:
            self.records.save_call(record)
            saved = True
        except Exception:
            logger.exception("Call record could not be saved")
        self._twilio_estimate(run, duration)
        logger.info(
            "Call %s ended: mode=%s state=%s outcome=%s duration=%ss",
            mask_sid(session.call_sid), brief.mode, state, outcome["status"], duration,
        )
        if saved and not blocked:  # P1: no triage and no notice for a blocked caller
            self._spawn(self._triage_and_announce(run.record_id, group, brief.contact_name))
        return CallResult(
            record_id=run.record_id,
            mode=brief.mode,
            direction=brief.direction,
            state=state,
            outcome=outcome,
            fields=record["fields"],
            duration_seconds=duration,
            code=run.failure,
            callback=run.callback,
        )

    def _spawn(self, coroutine):
        if self.closing:
            coroutine.close()
            return None
        task = asyncio.create_task(coroutine, name="call-agent-after")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _triage_and_announce(self, record_id, group=None, name=""):
        """Triage, then tell the owner. P1: a VIP's call is announced at once, before
        triage (marked VIP, "Left a message."), and again once triaged (with the summary);
        an unknown caller's spam is only a quiet record (no tray notice)."""
        vip = {"name": name} if group == "vip" and name else None
        if vip:
            await self._announce(record_id, vip=vip)
        value = None
        try:
            value = await self.triage(record_id)
        finally:
            spam = group not in ("vip", "known") and isinstance(value, dict) and value.get("spam") is True
            summary = value.get("summary") if isinstance(value, dict) else None
            await self._announce(
                record_id, vip={**vip, "summary": summary} if vip and summary else vip, quiet=spam
            )

    async def triage(self, record_id):
        """Triage one stored record; never raises, never alters the record's call data."""
        provider = None
        try:
            record = self.records.get(record_id)
            if record is None:
                return None
            try:
                provider = self.triage_provider()
            except ServiceError as exc:
                self.records.set_triage(record_id, {"code": exc.code}, "skipped")
                return None
            owner, project = self.usage_scope()
            # A fresh admission per attempt (a retry is not a replay of the same step);
            # the receipt's request id stays the record id.
            operation = self.app.usage.operation(
                owner, project, "call_triage", f"{uuid.uuid4()}:{record_id}"
            )
            response = await asyncio.wait_for(
                operation.generate(
                    provider,
                    [Message(MessageRole.USER, triage.prompt(record))],
                    system_instruction=triage.SYSTEM,
                    effort="low",
                    max_output_tokens=triage.MAX_OUTPUT_TOKENS,
                ),
                triage.TIMEOUT_SECONDS,
            )
            result = triage.parse(response.text)
            value = {
                **result.model_dump(),
                "model": getattr(provider, "_model", None),
                "at": self.wall(),
            }
            self.records.set_triage(record_id, value, "done")
            return value
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, ServiceError) else (
                "triage_timeout" if isinstance(exc, TimeoutError) else
                "triage_invalid" if isinstance(exc, (ValueError, ValidationError)) else
                "triage_failed"
            )
            logger.warning("Call triage failed: %s", code)
            try:
                self.records.set_triage(record_id, {"code": code}, "failed")
            except Exception:
                logger.exception("Call triage state could not be saved")
            return None
        finally:
            if provider is not None:
                try:
                    await asyncio.wait_for(provider.close(), 5)
                except Exception:
                    logger.warning("Triage provider did not close cleanly", exc_info=True)

    async def _announce(self, record_id, *, vip=None, quiet=False):
        """Owner-facing: ``call_record_ready`` (record id only, plus ``vip: true`` for a VIP
        caller) and a generic tray notice. ``quiet`` (spam): the renderers refresh, but no
        tray or resident notice goes out.

        P1, ``vip`` = {name, summary?}: the renderers also get ``call_vip_alert`` (the in-app
        card), and the native tray gets the VIP balloon even with a renderer connected (the
        host shows it only while the workspace is not visible). The name and summary are the
        owner's and JARVIS's text for the owner only; they are never logged."""
        payload = {"record_id": record_id, **({"vip": True} if vip else {})}
        alert = vip_alert(record_id, vip) if vip else None
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            bus.emit_nowait(Event(type=EVENT_RECORD_READY, data=payload, source="telephony"))
        owner = self.owner()
        if owner is None:
            return
        sessions = self.app.sessions
        renderers = sessions.rooms(owner, "renderer")
        try:
            for sid in renderers:
                await self.app.sio.emit(EVENT_RECORD_READY, payload, room=sid)
                if alert:
                    await self.app.sio.emit(EVENT_VIP_ALERT, alert, room=sid)
            native = getattr(sessions, "native_desktop", None)
            if quiet or (renderers and not (alert and native is not None)):
                return
            if native is not None:
                # Suppressed in gaming mode by the native host. The delivery id is per record,
                # so a VIP's second announce is not shown twice. Other calls get the fixed,
                # content-free notice; a VIP call names the caller (the owner's own label).
                await native.notify({
                    "delivery_id": "call:" + record_id, "notice": "call",
                } if not alert else {
                    "delivery_id": "call:" + record_id, "notice": "call_vip",
                    "title": f"{alert['name']} called · VIP", "text": alert["summary"],
                    "record_id": record_id,
                })
            else:
                for sid in sessions.rooms(owner, "resident"):
                    await self.app.sio.emit(EVENT_RECORD_READY, payload, room=sid)
        except Exception:
            logger.warning("Call record notice could not be delivered", exc_info=True)

    async def close(self):
        """Core shutdown: unfinished triage is cancelled (the record stays, state pending)."""
        self.closing = True
        tasks = [task for task in self.tasks if not task.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=2)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def vip_alert(record_id, vip):
    """``call_vip_alert``: the record, the saved person's name and a one-line summary."""
    summary = briefs.clean_line(str(vip.get("summary") or ""), 200) or VIP_LEFT_MESSAGE
    return {"record_id": record_id, "name": briefs.clean_line(str(vip.get("name") or ""), 60),
            "summary": summary}


def caller_number(value):
    """E.164 caller ID, or None when withheld or not a number."""
    return None if withheld(value) else normalize(value)


def _unconnected(brief, state, code):
    """The result of a placed call that never ran (no record)."""
    return CallResult(
        record_id=None, mode=brief.mode, direction=brief.direction, state=state,
        outcome={"status": state}, fields={}, duration_seconds=0.0, code=code,
    )


def _source_record(brief):
    source = brief.source_record_id or (brief.briefing.source_record_id if brief.briefing else None)
    return str(source) if source else None


def _rate(mime):
    match = re.search(r"rate=(\d+)", mime)
    rate = int(match.group(1)) if match else OUTPUT_RATE
    return rate if rate in SEND_RATES else OUTPUT_RATE
