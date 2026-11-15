"""The flight recorder (S4.1, docs/DIAGNOSTICS.md): what JARVIS did in each of the last
200 turns, in memory only.

One trace per brain turn (desktop chat, tray or renderer voice, phone chat, Show JARVIS)
and one per voice exchange Live answered without the brain (a quick answer, or a reply
Live gave itself). A trace holds identifiers, timings, token counts, a list-price cost
estimate, tool names and approval answers. It never holds message text, tool arguments,
places or names, unless the owner turned on ``diagnostics.include_text``: then the turn's
request and answer are kept too, cut to 500 characters.

Shape (``recent`` / ``get``)::

    {id, origin, started_at, provider, model, effort, outcome, total_ms, first_token_ms,
     spans: [{kind, name?, start_ms, ms, outcome}], tokens: {input, output},
     cost_usd, approvals: [{tool, asked_ms, answer}], request_text?, answer_text?}

``kind`` is wake, speech_in, model, tool, approval or speech_out. ``start_ms`` is relative
to the trace's start (the brain turn's start for a brain turn), so the voice spans before
a brain turn (wake, speech_in) are negative. Hooks here never raise into a turn.

Every new or updated trace is announced to the owner's renderers as ``trace_added``
``{id, origin, outcome, total_ms}``; a voice brain turn is announced again when its speech
spans arrive (same id: the list replaces the row).
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import time
import uuid

from services.log import get_logger
from services.settings import diagnostics_settings

logger = get_logger(__name__)

TRACE_LIMIT = 200
TEXT_LIMIT = 500
PENDING_LIMIT = 32  # voice spans waiting for their brain turn's trace
ORIGINS = {
    "desktop_chat": "chat",
    "voice_brain": "voice",
    "phone_chat": "phone",
    "vision_ask": "vision",
}
ANSWERS = ("approved", "denied", "timeout")


def _ms(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(value):
    return value[:TEXT_LIMIT] if isinstance(value, str) else None


# Equal start times (a coarse clock) keep the order things happen in.
KIND_ORDER = {"wake": 0, "speech_in": 1, "speech_out": 3}


def span_order(span):
    start = span["start_ms"]
    return (start if start is not None else 1 << 62, KIND_ORDER.get(span["kind"], 2))


def brain_spans(budget):
    """Model, tool and approval spans plus the approvals list from ``TurnBudget.steps``."""
    from services.conversation import step_name

    spans, approvals = [], []
    for item in getattr(budget, "steps", None) or []:
        kind = "model" if item.get("kind") == "model" else "tool"
        span = {
            "kind": kind,
            "start_ms": _ms(item.get("start_ms")),
            "ms": _ms(item.get("ms")),
            "outcome": item.get("outcome") if isinstance(item.get("outcome"), str) else None,
        }
        if kind == "model":
            provider = item.get("provider")
            if isinstance(provider, str):
                span["name"] = provider
            if item.get("retry") is True:
                span["retry"] = True
        else:
            span["name"] = step_name(item)
        spans.append(span)
        asked = item.get("approval")
        if kind == "tool" and isinstance(asked, dict):
            answer = asked.get("answer") if asked.get("answer") in ANSWERS else "timeout"
            asked_ms, answered_ms = _ms(asked.get("asked_ms")), _ms(asked.get("answered_ms"))
            approvals.append({"tool": span["name"], "asked_ms": asked_ms, "answer": answer})
            spans.append({
                "kind": "approval",
                "name": span["name"],
                "start_ms": asked_ms,
                "ms": answered_ms - asked_ms
                if asked_ms is not None and answered_ms is not None else None,
                "outcome": answer,
            })
    spans.sort(key=span_order)
    return spans, approvals


class TraceService:
    def __init__(self, app=None, *, settings=None, clock=time.monotonic, wall=None,
                 limit=TRACE_LIMIT):
        self.app = app
        self._settings = settings
        self.clock = clock
        self.wall = wall or (lambda: datetime.now(timezone.utc))
        self.limit = limit
        self.traces = OrderedDict()  # id -> trace, oldest first
        self._meta = {}  # id -> (owner, monotonic start); never public
        self._pending = OrderedDict()  # brain request id -> voice spans that came first
        self._voice = {}  # voice session id -> exchange state
        self._tasks = set()

    # --- settings ------------------------------------------------------------------------
    def include_text(self):
        try:
            settings = self._settings() if self._settings else getattr(self.app, "settings", {})
            return diagnostics_settings(settings)["include_text"] is True
        except Exception:
            return False

    # --- public API ----------------------------------------------------------------------
    def recent(self, limit=50, owner=None):
        """Up to ``limit`` traces, newest first (only ``owner``'s when given)."""
        limit = max(0, min(int(limit), self.limit))
        found = []
        for key in reversed(self.traces):
            if owner is not None and self._meta.get(key, (None,))[0] not in (owner, None):
                continue
            found.append(self._public(self.traces[key]))
            if len(found) >= limit:
                break
        return found

    def get(self, trace_id):
        trace = self.traces.get(str(trace_id))
        return self._public(trace) if trace is not None else None

    def clear(self, owner=None):
        if owner is None:
            self.traces.clear()
            self._meta.clear()
        else:
            for key in [k for k, (who, _) in self._meta.items() if who in (owner, None)]:
                self.traces.pop(key, None)
                self._meta.pop(key, None)
        self._pending.clear()

    @staticmethod
    def _public(trace):
        return {
            **trace,
            "spans": [dict(span) for span in trace["spans"]],
            "tokens": dict(trace["tokens"]),
            "approvals": [dict(item) for item in trace["approvals"]],
        }

    # --- recording -----------------------------------------------------------------------
    def record_turn(self, timing, budget, *, usage_feature=None, owner=None,
                    request_text=None, answer_text=None):
        """One brain turn, from ConversationService._record_turn_timing's timing dict."""
        trace_id = str(timing.get("request_id") or uuid.uuid4())
        total_ms = _ms(timing.get("total_ms")) or 0
        spans, approvals = brain_spans(budget)
        cost = getattr(budget, "cost_microusd", None)
        trace = {
            "id": trace_id,
            "origin": ORIGINS.get(usage_feature, timing.get("origin") or "chat"),
            "started_at": (self.wall() - timedelta(milliseconds=total_ms)).isoformat(),
            "provider": timing.get("provider"),
            "model": timing.get("model"),
            "effort": timing.get("effort"),
            "outcome": timing.get("outcome"),
            "total_ms": total_ms,
            "first_token_ms": _ms(timing.get("first_token_ms")),
            "spans": spans,
            "tokens": {
                "input": _ms(timing.get("input_tokens")) or 0,
                "output": _ms(timing.get("output_tokens")) or 0,
            },
            "cost_usd": round(cost / 1_000_000, 6) if isinstance(cost, int) else None,
            "approvals": approvals,
        }
        if self.include_text():
            trace["request_text"] = _text(request_text)
            trace["answer_text"] = _text(answer_text)
        started = self.clock() - total_ms / 1000
        pending = self._pending.pop(trace_id, None)
        if pending is not None:
            self._merge(trace, started, pending)
        self._add(trace, owner, started)

    def _add(self, trace, owner, started):
        key = trace["id"]
        self.traces.pop(key, None)
        self.traces[key] = trace
        self._meta[key] = (owner, started)
        while len(self.traces) > self.limit:
            old, _ = self.traces.popitem(last=False)
            self._meta.pop(old, None)
        self._announce(trace, owner)

    def _merge(self, trace, started, voice_spans):
        for span in voice_spans:
            at, end = span.pop("_at"), span.pop("_end")
            trace["spans"].append({
                **span, "start_ms": int((at - started) * 1000), "ms": max(0, int((end - at) * 1000)),
            })
        trace["spans"].sort(key=span_order)

    def _announce(self, trace, owner):
        app = self.app
        sio, sessions = getattr(app, "sio", None), getattr(app, "sessions", None)
        if sio is None or sessions is None or owner is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        payload = {key: trace[key] for key in ("id", "origin", "outcome", "total_ms")}

        async def send():
            try:
                if not sessions.authenticated(owner):
                    return
                for room in sessions.rooms(owner, "renderer"):
                    await sio.emit("trace_added", payload, room=room)
            except Exception as exc:
                logger.warning("trace_added could not be delivered (%s)", type(exc).__name__)

        task = loop.create_task(send())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- voice ---------------------------------------------------------------------------
    def voice_event(self, session, kind, **data):
        """A voice session event (services/voice.py). Never raises."""
        try:
            getattr(self, "_voice_" + kind)(session, **data)
        except Exception as exc:
            logger.warning("Voice trace hook failed (%s, %s)", kind, type(exc).__name__)

    def _state(self, session):
        state = self._voice.get(session.id)
        if state is None:
            state = self._voice[session.id] = {
                "began": self.clock(), "wake": getattr(session, "source", None) == "wake",
                "wake_ms": None, "model": None, "ex": None,
            }
            if len(self._voice) > 16:  # sessions that never ended cleanly
                self._voice.pop(next(iter(self._voice)))
        return state

    def _exchange(self, session):
        state = self._state(session)
        if state["ex"] is None:
            state["ex"] = {
                "start": self.clock(), "spans": [], "speech_in": None, "out": None,
                "first_out": None, "brain": None, "tools": {}, "interrupted": False,
                "user": [], "jarvis": [],
            }
        return state["ex"]

    def _voice_started(self, session, model=None):
        state = self._state(session)
        state["began"], state["model"] = self.clock(), model

    def _voice_connected(self, session):
        state = self._state(session)
        if state["wake"] and state["wake_ms"] is None:
            state["wake_ms"] = (self.clock() - state["began"]) * 1000

    def _voice_speech_in(self, session):
        ex, now = self._exchange(session), self.clock()
        if ex["speech_in"] is None:
            ex["speech_in"] = [now, now]
        else:
            ex["speech_in"][1] = now

    def _voice_audio_out(self, session):
        ex = self._exchange(session)
        if ex["out"] is None:
            ex["out"] = self.clock()
            if ex["first_out"] is None:
                ex["first_out"] = ex["out"]

    def _voice_interrupted(self, session):
        self._exchange(session)["interrupted"] = True

    def _voice_tool(self, session, call_id, name):
        self._exchange(session)["tools"][str(call_id)] = (str(name)[:64], self.clock())

    def _voice_tool_done(self, session, call_id, outcome):
        ex = self._exchange(session)
        found = ex["tools"].pop(str(call_id), None)
        if found is not None:
            ex["spans"].append(self._span("tool", found[1], self.clock(), outcome, found[0]))

    def _voice_brain(self, session, call_id, request_id):
        ex = self._exchange(session)
        ex["tools"].pop(str(call_id), None)  # the brain turn's own spans cover it
        ex["brain"] = str(request_id)

    def _voice_turn_complete(self, session, pending=False, final=False, user="", jarvis=""):
        state = self._voice.get(session.id)
        ex = state["ex"] if state else None
        if ex is not None:
            now = self.clock()
            if ex["out"] is not None:
                ex["spans"].append(self._span(
                    "speech_out", ex["out"], now,
                    "interrupted" if ex["interrupted"] else "ok",
                    "progress" if pending and not final else None,
                ))
                ex["out"] = None
            if self.include_text():
                ex["user"].append(user or "")
                ex["jarvis"].append(jarvis or "")
            if final or not pending:
                state["ex"] = None
                self._finish_exchange(session, state, ex, now)
        if final:
            self._voice.pop(session.id, None)

    @staticmethod
    def _span(kind, at, end, outcome, name=None):
        span = {"kind": kind, "_at": at, "_end": end, "outcome": outcome}
        if name:
            span["name"] = name
        return span

    def _finish_exchange(self, session, state, ex, now):
        # In time order, so equal clock readings keep it (the sort is stable).
        spans = []
        if state["wake"] and state["wake_ms"] is not None:
            # The first exchange of a "Hey Jarvis" session: detection to Live ready.
            state["wake"] = False
            spans.append(
                self._span("wake", state["began"], state["began"] + state["wake_ms"] / 1000, "ok")
            )
        if ex["speech_in"] is not None:
            at, end = ex["speech_in"]
            spans.append(self._span("speech_in", at, end, "ok"))
        spans.extend(ex["spans"])
        for name, at in ex["tools"].values():
            spans.append(self._span("tool", at, now, "cancelled", name))
        if not spans:
            return
        owner = getattr(session, "owner", None)
        brain = ex["brain"]
        if brain is not None:
            trace = self.traces.get(brain)
            if trace is None:
                self._pending[brain] = spans
                while len(self._pending) > PENDING_LIMIT:
                    self._pending.popitem(last=False)
                return
            _, started = self._meta.get(brain, (owner, now))
            self._merge(trace, started, spans)
            self._announce(trace, self._meta.get(brain, (owner,))[0])
            return
        start = min([ex["start"], *(span["_at"] for span in spans)])
        trace = {
            "id": str(uuid.uuid4()),
            "origin": "voice",
            "started_at": (self.wall() - timedelta(seconds=now - start)).isoformat(),
            "provider": "gemini_live",
            "model": state["model"],
            "effort": None,
            "outcome": "interrupted" if ex["interrupted"] else "ok",
            "total_ms": int((now - start) * 1000),
            "first_token_ms": int((ex["first_out"] - start) * 1000)
            if ex["first_out"] is not None else None,
            "spans": [],
            "tokens": {"input": None, "output": None},  # Live counts are per session
            "cost_usd": None,
            "approvals": [],
        }
        if self.include_text():
            trace["request_text"] = _text(" ".join(t for t in ex["user"] if t).strip())
            trace["answer_text"] = _text(" ".join(t for t in ex["jarvis"] if t).strip())
        self._merge(trace, start, spans)
        self._add(trace, owner, start)
