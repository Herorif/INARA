"""The talking overlay (J4): what the small always-on-top window shows during tray voice.

While a tray voice session runs (tray "Talk to JARVIS" or "Hey Jarvis"), the native host
runs a separate Electron process (electron/overlay-main.cjs, docs/VOICE_OVERLAY.md) that
connects with the socket role ``overlay`` and shows the live core and captions. This
module keeps the model of what it shows and publishes it to the owner's overlay sockets
only; with none connected nothing is sent.

``voice_overlay`` is a full snapshot (``snapshot()``), sent on connect and on every
change, coalesced to at most 20 per second (the latest state wins); the end snapshot goes
out at once. ``voice_level`` (``{"level": 0..1}``) follows the speaker's output while
JARVIS speaks, at most 20 per second, then one final 0.0.

The voice service feeds it through small hooks (``VoiceService.overlay_event``) and the
text the core already accumulates; it never changes what the conversation records.
Caption text is never logged.
"""

import asyncio
import time

from services.audio_contracts import overlay_settings
from services.log import get_logger
from services.voice import QUIET_ENDS

logger = get_logger(__name__)

USER_LIMIT = 300  # the owner's words: the last 300 characters
JARVIS_LIMIT = 600  # JARVIS's words: the last 600 characters
INTERVAL = 0.05  # at most 20 snapshots (and 20 levels) per second
# Ends after which nothing may stay on screen: the overlay closes at once.
NOW_ENDS = frozenset({"gaming_mode", "authentication_required", "permission_denied"})


def plain(text, limit):
    """The caption as shown: trimmed, the last ``limit`` characters."""
    return text.strip()[-limit:].lstrip()


def end_kind(state, code):
    """``"quiet"`` | ``"now"`` | ``"error"`` for a session's final voice_state."""
    if code in NOW_ENDS:
        return "now"
    if code in QUIET_ENDS or (code is None and state != "error"):
        return "quiet"
    return "error"


class VoiceOverlay:
    def __init__(self, app, clock=time.monotonic, interval=INTERVAL):
        self.app, self.clock, self.interval = app, clock, interval
        # The native host: callable(event, data) on the core loop, for the overlay process:
        # ("started", None), ("ended", {"now": bool}), ("disabled", None).
        self.observer = None
        self.session = None  # the tray VoiceSession shown (the current or the last one)
        self.state = "ended"
        self.user = self.jarvis = ""
        self.user_final = self.jarvis_final = False
        self.approval = False
        self.end = None
        self.turn_done = True  # the next owner words start a new exchange
        self.frozen = False  # barged in: JARVIS's words stay as they were until the turn ends
        # Publishing.
        self.dirty = self.urgent = False
        self.last_sent = float("-inf")
        self.kick = None
        self.sender = None
        self.levels = None

    # --- the model -------------------------------------------------------------------------

    def snapshot(self):
        return {
            "session": self.session.id if self.session is not None else None,
            "state": self.state,
            "user": self.user,
            "user_final": self.user_final,
            "jarvis": self.jarvis,
            "jarvis_final": self.jarvis_final,
            "approval": self.approval,
            "end": dict(self.end) if self.end is not None else None,
        }

    def enabled(self):
        return overlay_settings(self.app.settings)["overlay"]

    def current(self, session):
        return session is self.session and not session.closed

    def live_state(self, session):
        """The tray's mapping (idle -> listening, "speaking" while audible)."""
        return self.app.voice.local_status(session)["state"]

    # --- hooks from VoiceService (core loop, tray sessions only) ----------------------------

    def started(self, session):
        """A tray session holds its slot (check_local_start passed): a fresh snapshot."""
        self.session = session
        self.state = "connecting"
        self.user = self.jarvis = ""
        self.user_final = self.jarvis_final = self.approval = False
        self.end = None
        self.turn_done, self.frozen = True, False
        self.publish()
        if self.enabled():
            self.notify("started")

    def delivered(self, session, event, payload):
        if session is not self.session:
            return
        if event == "voice_caption":
            self.caption(payload.get("role"), payload.get("text"), payload.get("final") is True)
        elif event == "voice_interrupted":
            self.interrupted()
        elif event == "voice_state":
            if session.closed:
                self.ended(
                    session, payload.get("state"), payload.get("code"), payload.get("message")
                )
            else:
                self.changed(session)

    def caption(self, role, text, final):
        if self.session is None or self.end is not None or not isinstance(text, str):
            return
        if role == "user":
            if not final and self.turn_done:
                # The owner started speaking after the last turn completed: a new exchange.
                self.jarvis, self.jarvis_final, self.approval = "", False, False
                self.turn_done = self.frozen = False
            self.user, self.user_final = plain(text, USER_LIMIT), final
        elif role == "jarvis":
            if self.frozen:
                self.jarvis_final = self.jarvis_final or final
            else:
                if not final and self.turn_done:
                    self.turn_done = False  # an answer after the turn (e.g. a brain hand-off)
                self.jarvis, self.jarvis_final = plain(text, JARVIS_LIMIT), final
        else:
            return
        self.publish()

    def interrupted(self):
        """Live's barge-in: JARVIS's words are final as they stand."""
        self.jarvis_final = True
        self.frozen = not self.turn_done
        self.publish()

    def barged(self, session):
        """"Hey Jarvis" while JARVIS speaks: as interrupted (the rest is dropped)."""
        if session is self.session:
            self.interrupted()

    def turn_completed(self, session):
        if session is not self.session:
            return
        self.user_final = self.jarvis_final = True
        self.turn_done, self.frozen = True, False
        self.publish()

    def approval_needed(self, session):
        """approval_unavailable: the overlay offers "Open JARVIS"."""
        if self.current(session):
            self.approval = True
            self.publish()

    def changed(self, session):
        if not self.current(session):
            return
        state = self.live_state(session)
        if state != self.state:
            self.state = state
            self.publish()
        else:
            self.sync_level()

    def ended(self, session, state, code, message):
        if session is not self.session or self.end is not None:
            return
        kind = end_kind(state, code)
        self.state = "ended"
        self.user_final = self.jarvis_final = True
        self.turn_done, self.frozen = True, False
        if kind == "now":
            self.user = self.jarvis = ""  # nothing may stay on screen
        self.end = {
            "kind": kind,
            "message": message if kind == "error" and isinstance(message, str) else None,
        }
        self.publish(urgent=True)
        self.notify("ended", {"now": kind == "now"})

    # --- settings and lifetime ------------------------------------------------------------

    def settings_changed(self):
        """voice.overlay turned off: an open overlay closes at once (on: next session)."""
        if not self.enabled():
            self.notify("disabled")

    def notify(self, event, data=None):
        observer = self.observer
        if observer is None:
            return
        try:
            observer(event, data)
        except Exception:
            logger.warning("The voice overlay process could not be told (%s)", event, exc_info=True)

    async def close(self):
        tasks = [task for task in (self.sender, self.levels) if task is not None]
        self.sender = self.levels = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.dirty = self.urgent = False
        self.kick = None  # "Retry backend" runs the core on a new loop

    # --- sockets ----------------------------------------------------------------------------

    def rooms(self, exclude=None):
        sessions = self.app.sessions
        owner = self.app.voice.local_owner()
        if owner is None or not sessions.is_owner(owner):
            return ()
        return tuple(sid for sid in sessions.rooms(owner, "overlay") if sid != exclude)

    async def attached(self, sid):
        """An overlay socket connected: the current snapshot, to that socket only."""
        await self.send("voice_overlay", self.snapshot(), (sid,))
        self.sync_level()

    def detached(self, sid):
        """An overlay socket is disconnecting (still registered while this runs)."""
        self.sync_level(exclude=sid)

    async def send(self, event, payload, rooms):
        for sid in rooms:
            try:
                await self.app.sio.emit(event, payload, room=sid)
            except Exception:
                logger.warning("The voice overlay could not be updated (%s)", event, exc_info=True)

    def publish(self, urgent=False):
        """Coalesce to at most one snapshot per ``interval``; ``urgent`` goes out at once."""
        if not self.rooms():
            self.sync_level()
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self.dirty = True
        if urgent:
            self.urgent = True
        if self.kick is None:
            self.kick = asyncio.Event()
        self.kick.set()
        if self.sender is None or self.sender.done():
            self.sender = asyncio.create_task(self._send_snapshots(), name="voice-overlay")
        self.sync_level()

    async def _send_snapshots(self):
        while self.dirty:
            wait = self.last_sent + self.interval - self.clock()
            if not self.urgent and wait > 0:
                self.kick.clear()
                try:
                    await asyncio.wait_for(self.kick.wait(), wait)
                except TimeoutError:
                    pass
                continue
            self.dirty = self.urgent = False
            self.last_sent = self.clock()
            await self.send("voice_overlay", self.snapshot(), self.rooms())

    # --- the output level -----------------------------------------------------------------

    def sync_level(self, exclude=None):
        """Measure the speaker while an overlay is connected during the session, and send
        levels while JARVIS speaks."""
        session = self.session
        connected = bool(self.rooms(exclude))
        audio = getattr(session, "audio", None)
        active = session is not None and not session.closed
        if audio is not None:
            audio.measure_level = connected and active
        if not (connected and active and self.state == "speaking"):
            return
        if self.levels is not None and not self.levels.done():
            return
        try:
            self.levels = asyncio.get_running_loop().create_task(
                self._send_levels(session), name="voice-overlay-level"
            )
        except RuntimeError:
            pass

    async def _send_levels(self, session):
        sent = False
        while self.current(session) and self.state == "speaking":
            rooms = self.rooms()
            if not rooms:
                break
            audio = session.audio
            level = audio.output_level() if audio is not None else 0.0
            await self.send("voice_level", {"level": float(level)}, rooms)
            sent = True
            await asyncio.sleep(self.interval)
        if sent:
            rooms = self.rooms()
            if rooms:
                await self.send("voice_level", {"level": 0.0}, rooms)
