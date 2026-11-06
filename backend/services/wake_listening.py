"""Listening for "Hey Jarvis" from the native tray: when the microphone is held, and what a
detection does.

The listener (services/wake_word.py) holds this PC's microphone only while ALL of these
hold: ``voice.wake_word`` is on, the detector's extras and models are available, a desktop
owner is registered, Live voice is ready (Gemini key and SDK), microphone permission is
not denied, the PC is not in gaming mode, and a microphone exists. Conditions are checked
again on settings changes (``voice``, ``tool_permissions``), resource-state changes, owner
registration, the end of a tray voice session, and every 30 s while not listening. A lost
microphone is retried after 10 s, 30 s, then every 60 s, resolving the device again each
time. It runs only in the native resident (``activate`` is called by resident/host.py), in
the resident, chat and studio states; a bare server or test app never listens.

One capture stream: while listening, ``audio_devices.Microphone`` stays open across tray
voice sessions (they attach to it) and closes or reopens only when no session uses it.
Turning the setting off drops the listener and its models; a gaming pause keeps the models.

A detection is marshalled to the core loop and decided there:

a. no voice session: ``start_local``'s synchronous checks first; if they pass, the wake
   cue, then ``start_local(wake=True)``, which sends the 1.5 s pre-roll first. A refusal
   plays only the denied cue (after the wake cue has finished, for a late refusal) and
   shows the reason on the tray; a face-locked refusal also shows the fixed "unlock"
   balloon (rate-limited by the host);
b. a workspace (renderer) voice session: ignored;
c. a tray session while JARVIS is audible: barge-in (``VoiceService.barge_in``), no cue;
d. a tray session while JARVIS is not audible: ignored (the audio already reaches Live).

Audio is never logged or stored; the log carries state changes and reasons only.
"""

import asyncio
import time

from services import wake_word
from services.audio_contracts import wake_word_settings
from services.audio_devices import OPEN_FAILED, Cue, Microphone, local_choices
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)

RECHECK_SECONDS = 30.0  # while not listening: keys or models added later
RETRY_SECONDS = (10.0, 30.0, 60.0)  # after the microphone was lost
CUE_MARGIN_SECONDS = 0.15  # the cue stream stays open this long after its last sample
LOCKED_NOTICE = "voice_locked"  # resident/host.py NOTICES entry
OWNER_MESSAGE = "Register the desktop owner first."
KEY_MESSAGE = 'Add a Gemini API key in Setup to use "Hey Jarvis".'
LOST_MESSAGE = "The microphone was disconnected. JARVIS will listen again when it is back."
TRAY_ONLY_MESSAGE = 'Start JARVIS from the tray to use "Hey Jarvis".'
LISTENER_FAILED = "The wake-word detector could not start."


class WakeWordService:
    def __init__(self, app, *, status_reader=None, listener_factory=None,
                 microphone_factory=None, clock=time.monotonic):
        self.app = app
        self.status_reader = status_reader or wake_word.status
        self.listener_factory = listener_factory or self.make_listener
        self.microphone_factory = microphone_factory or self.make_microphone
        self.clock = clock
        self.recheck = RECHECK_SECONDS
        self.retry_delays = RETRY_SECONDS
        self.active = False  # set by the native resident host only
        self.observer = None  # tray: callable({"setting", "state", "message"})
        self.notice_observer = None  # tray balloon: callable(kind)
        self.listener = None
        self.microphone = None
        self.mic_choice = None  # the saved choice the open microphone was resolved from
        self.mic_problem = None  # why the microphone could not open (no device, ...)
        self.lost = 0  # retries since the microphone was lost (0: not lost)
        self.retry_at = None
        self.listener_failed = None  # sticky until a settings change or registration
        self.fresh = False
        self.opening = None  # future while the microphone opens
        self.published = None
        self.loop = None
        self.lock = asyncio.Lock()
        self.poked = asyncio.Event()
        self.task = None
        self.tasks = set()

    # --- construction hooks (tests replace these) -----------------------------------------

    def make_listener(self, on_detect, on_state, sensitivity):
        return wake_word.WakeWordListener(on_detect, sensitivity=sensitivity, on_state=on_state)

    def make_microphone(self, on_lost):
        return Microphone(self.app.audio_devices, on_lost=on_lost)

    # --- lifetime -------------------------------------------------------------------------

    def activate(self, observer=None, notice=None):
        """The native resident host: listening may run here (before the core loop starts)."""
        self.active = True
        self.observer, self.notice_observer = observer, notice

    async def begin(self):
        """Application start: the first check, then re-checks while active."""
        if not self.active or self.task is not None:
            return
        self.loop = asyncio.get_running_loop()
        # "Retry backend" runs the core on a new loop: no primitive from the old one.
        self.lock, self.poked = asyncio.Lock(), asyncio.Event()
        self.task = asyncio.create_task(self._maintain(), name="wake-word")

    async def close(self):
        """Quit / close_services: stop listening and release the microphone."""
        self.active = False
        task, self.task = self.task, None
        pending = [item for item in (task, *self.tasks) if item is not None]
        for item in pending:
            item.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        async with self.lock:
            await self._drop_listener()
            await self._close_microphone()
        self.published = None

    def poke(self, fresh=False):
        """Re-evaluate soon (any thread before the loop runs; the loop afterwards)."""
        if fresh:
            self.fresh = True
        self.poked.set()

    def session_ended(self):
        self.poke()

    def set_audible(self, value):
        listener = self.listener
        if listener is not None:
            listener.audible = bool(value)

    async def _maintain(self):
        while True:
            self.poked.clear()
            await self.reconcile()
            timeout = self._timeout()
            try:
                await asyncio.wait_for(self.poked.wait(), timeout)
            except TimeoutError:
                pass

    def _timeout(self):
        if self.retry_at is not None:
            return max(0.0, self.retry_at - self.clock())
        if self.listening() or not wake_word_settings(self.app.settings)["wake_word"]:
            return None  # nothing to re-check: changes poke
        return self.recheck

    def listening(self):
        listener, mic = self.listener, self.microphone
        return (
            mic is not None
            and listener is not None
            and listener.running
            and not self.listener_failed
        )

    # --- conditions and status -------------------------------------------------------------

    def conditions(self, settings=None):
        """("off" | "unavailable" | "paused" | "listening", message) without any device."""
        settings = settings or wake_word_settings(self.app.settings)
        if not settings["wake_word"]:
            return "off", None
        status = self.status_reader()
        if not status["available"]:
            return "unavailable", status["reason"]
        voice = self.app.voice
        owner = voice.local_owner()
        if owner is None or not self.app.sessions.is_owner(owner):
            return "unavailable", OWNER_MESSAGE
        try:
            voice.preflight()
            voice.require_permission()
        except ServiceError as exc:
            return "unavailable", KEY_MESSAGE if exc.code == "provider_not_configured" else str(exc)
        if self.app.resources.state == "gaming":
            return "paused", None
        return "listening", None

    def status(self):
        """``WakeWordStatus``: what is true now; never opens a device. Loading counts as
        listening; while a tray session uses its own microphone this says listening too."""
        state, message = self.conditions()
        if state != "listening":
            return {"state": state, "message": message}
        if not self.active:
            return {"state": "unavailable", "message": TRAY_ONLY_MESSAGE}
        listener = self.listener
        failed = self.listener_failed or (
            (listener.error or LISTENER_FAILED)
            if listener is not None and listener.state == "error"
            else None
        )
        if failed:
            return {"state": "unavailable", "message": failed}
        if self.lost:
            return {"state": "unavailable", "message": LOST_MESSAGE}
        if self.mic_problem:
            return {"state": "unavailable", "message": self.mic_problem}
        return {"state": "listening", "message": None}

    def report(self):
        """The ``wake_word_status`` answer; a stale view asks for a re-check."""
        view = self.status()
        published = self.published or {}
        if self.active and (published.get("state"), published.get("message")) != (
            view["state"], view["message"]
        ):
            self.poke()
        return view

    def publish(self):
        payload = {
            "setting": wake_word_settings(self.app.settings)["wake_word"],
            **self.status(),
        }
        if payload == self.published:
            return
        self.published = payload
        if self.observer is None:
            return
        try:
            self.observer(dict(payload))
        except Exception:
            logger.warning('"Hey Jarvis" status could not be delivered', exc_info=True)

    # --- reconcile ---------------------------------------------------------------------------

    def local_session(self):
        return next(
            (
                item
                for item in self.app.voice.sessions.values()
                if item.endpoint == "local" and not item.closed
            ),
            None,
        )

    async def reconcile(self, fresh=False):
        """Bring the listener and microphone in line with the conditions; never raises."""
        if fresh:
            self.fresh = True
        if not self.active:
            return
        async with self.lock:
            try:
                await self._reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('"Hey Jarvis" could not update its listening state')
        self.publish()

    async def _reconcile(self):
        if self.fresh:
            self.fresh = False
            self.listener_failed = self.mic_problem = self.retry_at = None
        settings = wake_word_settings(self.app.settings)
        state, _ = self.conditions(settings)
        session = self.local_session()
        if state != "listening":
            self.lost, self.retry_at, self.mic_problem = 0, None, None
            if state == "off":
                self.listener_failed = None
                await self._drop_listener()  # back to the tray-voice-only footprint
            else:
                await self._stop_listener()  # a gaming pause keeps the models
            if session is None:
                await self._close_microphone()
            return
        listener = self.listener
        if listener is None:
            listener = self.listener = self.listener_factory(
                self._detected, self._listener_state, settings["wake_sensitivity"]
            )
        listener.sensitivity = settings["wake_sensitivity"]
        if listener.state == "error" and not self.listener_failed:
            self.listener_failed = listener.error or LISTENER_FAILED
        if self.listener_failed:
            if session is None:
                await self._close_microphone()
            return
        choice = local_choices(self.app.settings)[0]
        mic = self.microphone
        if mic is not None and session is None and mic.attached() is None and (
            self.mic_choice != choice
        ):
            await self._close_microphone()  # the saved microphone changed: reopen below
        if self.microphone is None:
            if session is not None:
                return  # a tray session uses its own stream; listen once it ends
            if self.retry_at is not None and self.clock() < self.retry_at:
                return
            await self._open_microphone(choice)
        if self.microphone is not None and not listener.running:
            listener.start()

    async def _open_microphone(self, choice):
        self.opening = asyncio.get_running_loop().create_future()
        mic = self.microphone_factory(self._microphone_lost)
        listener = self.listener
        mic.submit = listener.submit if listener is not None else None
        try:
            try:
                await mic.open(choice)
            except Exception as exc:
                try:
                    await mic.close()
                except Exception:
                    logger.debug("Wake-word microphone close failed", exc_info=True)
                message = str(exc) if isinstance(exc, ServiceError) else OPEN_FAILED
                if self.lost:
                    self.lost += 1
                    delay = self.retry_delays[min(self.lost - 1, len(self.retry_delays) - 1)]
                    self.retry_at = self.clock() + delay
                else:
                    self.mic_problem = message
                    self.retry_at = self.clock() + self.recheck
                logger.info(
                    '"Hey Jarvis" microphone unavailable (%s)',
                    getattr(exc, "code", type(exc).__name__),
                )
                return
            self.microphone, self.mic_choice = mic, choice
            self.lost, self.retry_at, self.mic_problem = 0, None, None
        finally:
            self.opening.set_result(None)

    async def _close_microphone(self):
        mic, self.microphone = self.microphone, None
        self.mic_choice = None
        if mic is None:
            return
        try:
            await mic.close()
        except Exception:
            logger.warning("Wake-word microphone did not close cleanly", exc_info=True)

    async def _stop_listener(self):
        listener = self.listener
        if listener is not None and listener.running:
            await asyncio.to_thread(listener.stop)

    async def _drop_listener(self):
        listener, self.listener = self.listener, None
        if listener is not None:
            await asyncio.to_thread(listener.stop)

    async def session_microphone(self):
        """The open shared microphone for a tray session starting now, else None."""
        if not self.active:
            return None
        opening = self.opening
        if opening is not None and not opening.done():
            await asyncio.shield(opening)
        mic = self.microphone
        if mic is None or not mic.ready or mic.lost or mic.closing:
            return None
        return mic

    async def report_devices(self):
        """The Preferences device list. PortAudio re-reads devices only with no stream open,
        so with no session the listener's stream is released for the refresh and reopened."""
        devices = self.app.audio_devices
        if not self.active or self.microphone is None or self.local_session() is not None:
            return await devices.report()
        async with self.lock:
            if self.microphone is None or self.local_session() is not None:
                return await devices.report()
            choice = self.mic_choice or local_choices(self.app.settings)[0]
            await self._close_microphone()
            try:
                return await devices.report()
            finally:
                await self._open_microphone(choice)
                listener = self.listener
                if self.microphone is not None and listener is not None:
                    listener.reset()

    # --- listener and microphone callbacks -----------------------------------------------

    def _threadsafe(self, callback, *args):
        loop = self.loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            pass  # the loop closed during shutdown

    def _detected(self, score, when):
        """Listener thread: hold the audio from here on, then decide on the core loop."""
        mic = self.microphone
        if mic is not None:
            mic.arm()
        self._threadsafe(self._spawn_detection, mic)

    def _listener_state(self, state, error):
        if state == "error":
            self._threadsafe(self.poke)

    def _microphone_lost(self):
        """Core loop: the shared stream stopped or went silent."""
        mic = self.microphone
        if mic is None or not mic.lost:
            return
        self.microphone, self.mic_choice = None, None
        sink = mic.attached()
        if sink is not None:
            sink._report_lost("microphone")  # the tray session ends, as in J2
        self.lost = 1
        self.retry_at = self.clock() + self.retry_delays[0]
        self._spawn(mic.close())
        self.publish()
        self.poke()

    def _spawn(self, coroutine):
        task = asyncio.ensure_future(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def _spawn_detection(self, mic):
        self._spawn(self.handle_detection(mic))

    # --- detections ----------------------------------------------------------------------

    async def handle_detection(self, mic):
        if mic is None:
            return
        if not self.active or mic is not self.microphone:
            mic.discard()
            return
        voice = self.app.voice
        owner = voice.local_owner()
        current = voice.sessions.get(owner) if owner is not None else None
        if current is not None and not current.closed:
            if current.endpoint != "local":
                mic.discard()  # (b) the workspace has the conversation
                return
            audio = current.audio
            if audio is not None and getattr(audio, "ready", False) and audio.speaking():
                await voice.barge_in(current)  # (c) flush and end the tail first
            mic.release()  # (c, d) audio from the detection onward goes to Live
            return
        # (a) start tray voice with the pre-roll. The synchronous refusals (face lock,
        # gaming, permission, no key or SDK) come first, so they play only the denied cue.
        try:
            voice.check_local_start()
        except ServiceError as exc:
            mic.discard()
            voice.refused_local(exc)
            self.refused(exc.code)
            return
        cue = self.play_cue("wake")
        try:
            result = await voice.start_local(wake=True)
        except asyncio.CancelledError:
            mic.discard()
            raise
        except Exception:
            logger.exception('"Hey Jarvis" could not start tray voice')
            result = {"ok": False, "code": "voice_failed"}
        if result.get("ok"):
            mic.release()  # normally already taken by the session
            return
        mic.discard()
        if cue is not None:
            await asyncio.wait({cue})  # a late refusal: the denied cue never overlaps it
        self.refused(result.get("code"))

    def refused(self, code):
        """The denied cue, plus the fixed unlock balloon when face lock refused."""
        self.play_cue("denied")
        if code == "authentication_required" and self.notice_observer:
            try:
                self.notice_observer(LOCKED_NOTICE)
            except Exception:
                logger.warning("The unlock notice could not be shown", exc_info=True)

    # --- cues -----------------------------------------------------------------------------

    def play_cue(self, kind):
        """Queue the cue's stream on the audio control thread now (before anything else the
        caller opens) and close it when it has played; never blocks the loop."""
        devices = self.app.audio_devices
        cue = Cue(devices, kind)
        try:
            future = devices.submit(cue.open, local_choices(self.app.settings)[1])
        except Exception as exc:
            logger.info("Skipped the %s cue (%s)", kind, type(exc).__name__)
            return None
        return self._spawn(self._finish_cue(cue, future))

    async def _finish_cue(self, cue, future):
        devices = self.app.audio_devices
        try:
            duration = await asyncio.wait_for(future, devices.timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Skipped the %s cue (%s)", cue.kind, type(exc).__name__)
            try:
                devices.submit(cue.close)  # in case the open finishes late
            except Exception:
                pass
            return
        try:
            await asyncio.sleep(duration + CUE_MARGIN_SECONDS)
        finally:
            try:
                await devices.call(cue.close)
            except Exception:
                logger.debug("Cue stream close failed", exc_info=True)

    # --- the tray switch -------------------------------------------------------------------

    async def toggle(self):
        return await self.set_enabled(not wake_word_settings(self.app.settings)["wake_word"])

    async def set_enabled(self, value):
        """The tray's Listen for "Hey Jarvis": saved like a Preferences change."""
        from services.settings import SettingsPatch

        request = SettingsPatch.model_validate({"voice": {"wake_word": bool(value)}})
        try:
            snapshot = self.app.settings_service.apply(request)
        except ServiceError as exc:
            logger.warning('"Hey Jarvis" setting could not be saved (%s)', exc.code)
            voice = self.app.voice
            if not any(item.endpoint == "local" for item in voice.sessions.values()):
                voice.publish_local(voice.local_status(notice=str(exc)))
            return {"ok": False, "code": exc.code, "message": str(exc)}
        await self.app.settings_changed(request.model_dump(exclude_unset=True))
        owner = self.app.voice.local_owner()
        if owner is not None:
            for room in self.app.sessions.rooms(owner, "renderer"):
                await self.app.sio.emit("settings", snapshot, room=room)
        return {"ok": True}
