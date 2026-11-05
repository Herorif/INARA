"""Real-time spoken voice: one Gemini Live session per owner, from one of two endpoints.

``renderer``: the owner's renderer owns the microphone and playback; the core relays PCM
between the renderer socket and Live. Gaming/resident mode, lock, project change,
disconnect and quit stop the session.

``local`` (J2, tray voice): the resident core itself captures this PC's microphone and
plays through its speaker (services/audio_devices.py), hands-free with Gemini server VAD
and half-duplex echo control: microphone frames are not sent while JARVIS is audible and
for a short tail after. It runs with the workspace closed (resident state) for the local
owner; gaming mode, lock, project change, a lost device, the tray Stop action, silence and
quit stop it. Turns join the conversation the workspace shows for the current project.

Either way the core never stores audio. Captions become text turns of the desktop
conversation. Anything that needs tools is handed to the brain through the ``ask_brain``
function, which runs a normal ConversationService turn, so ToolDispatcher approvals apply
unchanged. One live session per owner across both endpoints.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import importlib.metadata
from pathlib import Path
import time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBytes, StrictInt, ValidationError, field_validator

from services.capability_profiles import model_id, provider_key
from services.conversation import ConversationRequest
from services.live_config import INPUT_RATE, OUTPUT_RATE, make_live_config
from services.log import get_logger
from services.tools import ServiceError
from services.usage import live_usage_counts

logger = get_logger(__name__)

SILENCE_SECONDS = 60  # no speech either way (and no brain work) ends the session
END_GRACE_SECONDS = 10  # end_conversation: let the goodbye finish speaking
THINKING_SECONDS = 20  # no answer after the owner spoke: return to standing by
QUEUED_AUDIO_LIMIT = 100  # frames buffered while connecting or resuming (2-10 s)
RECONNECT_ATTEMPTS = 3
CAPTION_LIMIT = 12_000
PCM_MIME = f"audio/pcm;rate={INPUT_RATE}"
# Ends the owner asked for (or expected); anything else stays visible on the tray.
QUIET_ENDS = frozenset({"stopped", "conversation_ended", "silence_timeout"})


class VoiceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["push_to_talk", "conversation"]
    # The desktop conversation that voice turns are appended to.
    conversation_id: uuid.UUID


class VoiceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID


class VoiceActivity(VoiceReference):
    state: Literal["start", "end"]


class VoiceAudio(VoiceReference):
    seq: StrictInt = Field(ge=0, lt=2**31)
    # PCM16 16 kHz mono little-endian, 20-100 ms.
    pcm: StrictBytes = Field(min_length=640, max_length=3200)

    @field_validator("pcm")
    @classmethod
    def whole_samples(cls, value):
        if len(value) % 2:
            raise ValueError("PCM16 needs whole samples")
        return value


def ready():
    if not provider_key():
        raise ServiceError(
            "provider_not_configured",
            "Voice needs a Gemini API key. Add one in Setup, or type a message.",
        )
    try:
        importlib.metadata.version("google-genai")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ServiceError(
            "voice_adapter_missing", "The voice SDK is not installed. Type a message instead."
        ) from exc


@asynccontextmanager
async def connect_live(model, config):
    """One Live API connection with the profile key and the OS certificate store."""
    from google import genai
    from services.tls import genai_http_options

    client = genai.Client(api_key=provider_key(), http_options=genai_http_options())
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            yield session
    finally:
        try:
            await asyncio.wait_for(client.aio.aclose(), 5)
        except Exception:
            logger.warning("Live client did not close cleanly", exc_info=True)


def failure_code(exc):
    """Map a connection failure to a renderer code without exposing SDK text."""
    status = getattr(exc, "code", None)
    if isinstance(exc, (OSError, ConnectionError, TimeoutError)) or status in (1006, 1011, 503):
        return "offline", "Voice lost its connection. Check the network and try again."
    if isinstance(status, int) and (400 <= status < 500 or status in (1007, 1008)):
        return "provider_rejected", "The voice provider rejected the session. Check the Gemini key."
    return "voice_failed", "Voice stopped unexpectedly. Type a message or try again."


@dataclass(eq=False)
class VoiceSession:
    id: str
    sid: str
    owner: str
    project: Path
    conversation_id: str
    mode: str
    started: float
    state: str = "connecting"
    outbound: asyncio.Queue = field(default_factory=asyncio.Queue)
    queued_audio: int = 0
    live: object = None
    handle: str | None = None
    go_away: bool = False
    connected: bool = False
    closed: bool = False
    holding: bool = False
    in_seq: int = -1
    out_seq: int = 0
    user_text: str = ""
    jarvis_text: str = ""
    brain_turn: bool = False
    brain: dict = field(default_factory=dict)
    ending: float | None = None
    stop_after_turn: ServiceError | None = None
    last_activity: float = 0.0
    usage: object = None
    ticket: dict | None = None
    ticket_started: float = 0.0
    tasks: set = field(default_factory=set)
    history_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    runner: object = None
    watchdog: object = None
    # "renderer" (sid is the owner's renderer) or "local" (sid is None; audio is this PC's).
    endpoint: str = "renderer"
    audio: object = None
    notice: str | None = None


class VoiceService:
    def __init__(
        self, app, connector=None, preflight=None, clock=time.monotonic, audio_factory=None
    ):
        self.app = app
        self.connector = connector or connect_live
        self.preflight = preflight or ready
        self.clock = clock
        self.sessions = {}  # owner -> VoiceSession; one live voice session per owner
        self.silence = SILENCE_SECONDS
        self.ending = set()  # end() calls spawned from inside a session's own handlers
        self.tick = 1.0
        self.retry_delay = 0.5
        # Local endpoint: the PC's devices, and the tray's view of the session.
        self.audio_factory = audio_factory or self.local_audio
        self.local_observer = None  # set by the native host: callable(status dict)
        self.local_published = None

    # --- authority -------------------------------------------------------------------

    def require_resources(self, endpoint="renderer"):
        state = self.app.resources.state
        if state == "gaming":
            raise ServiceError("gaming_mode", "Voice pauses in gaming mode. Typed input is available.")
        # Tray voice exists for the resident state; renderer voice needs the workspace.
        if state == "resident" and endpoint != "local":
            raise ServiceError("resource_policy", "Open the workspace to use voice.")

    def local_owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def require_local_owner(self, owner):
        """The renderer check's equivalent for tray voice: the registered, unlocked owner."""
        sessions = self.app.sessions
        if owner is None or owner != self.local_owner() or not sessions.is_owner(owner):
            raise ServiceError("permission_denied", "Register the desktop owner first.")
        if not sessions.authenticated(owner):
            raise ServiceError(
                "authentication_required", "Unlock JARVIS in the workspace to use voice."
            )

    def require_permission(self):
        if any(
            self.app.settings["tool_permissions"].get(name) == "deny"
            for name in ("start_audio", "speech_capture")
        ):
            raise ServiceError("permission_denied", "Microphone permission is turned off.")

    def authorize(self, session):
        if session.closed or self.sessions.get(session.owner) is not session:
            raise ServiceError("voice_stopped", "This voice session has stopped.")
        if session.endpoint == "local":
            self.require_local_owner(session.owner)
        else:
            owner = self.app.sessions.require_owner(session.sid, {"renderer"})
            if owner != session.owner:
                raise ServiceError("voice_stopped", "The voice connection changed.")
        if self.app.projects.get_current_project_path().resolve() != session.project:
            raise ServiceError("voice_scope", "The project changed. Start voice again.")
        self.require_resources(session.endpoint)
        self.require_permission()

    @staticmethod
    def busy(current):
        if current.endpoint == "local":
            return ServiceError(
                "voice_busy", "Voice is already on from the tray. Stop it there first."
            )
        return ServiceError("voice_busy", "Voice is already on. Stop it before starting again.")

    def find(self, sid, session_id):
        session = next(
            (item for item in self.sessions.values() if item.id == str(session_id)), None
        )
        return session if session and session.sid == sid and not session.closed else None

    # --- renderer requests -------------------------------------------------------------

    async def start(self, sid, args):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        self.require_resources()
        self.require_permission()
        current = self.sessions.get(owner)
        if current and not current.closed:
            raise self.busy(current)
        self.preflight()
        now = self.clock()
        session = VoiceSession(
            id=str(uuid.uuid4()),
            sid=sid,
            owner=owner,
            project=self.app.projects.get_current_project_path().resolve(),
            conversation_id=str(args.conversation_id),
            mode=args.mode,
            started=now,
            last_activity=now,
        )
        session.usage = self.app.usage.operation(owner, session.project, "voice_live", session.id)
        # Admission before any provider connection: budget caps apply per Live turn.
        session.ticket, session.ticket_started = session.usage.begin(model_id("voice")), now
        self.sessions[owner] = session
        session.runner = asyncio.create_task(self.run(session), name="voice-live")
        session.watchdog = asyncio.create_task(self.watch(session), name="voice-watchdog")
        return {"session_id": session.id, "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE}

    def audio(self, sid, data):
        """Relay one frame; unknown sessions, bad frames and stale sequences are dropped."""
        try:
            args = VoiceAudio.model_validate(data)
        except ValidationError:
            return
        session = self.find(sid, args.session_id)
        if session is None or args.seq <= session.in_seq:
            return
        session.in_seq = args.seq
        if session.mode == "push_to_talk" and not session.holding:
            return  # the microphone belongs to the hold; nothing outside it is relayed
        if session.queued_audio >= QUEUED_AUDIO_LIMIT:
            return
        session.queued_audio += 1
        session.outbound.put_nowait(("audio", args.pcm))

    async def activity(self, sid, args):
        session = self.find(sid, args.session_id)
        if session is None:
            raise ServiceError("voice_missing", "Start voice again.")
        if session.mode != "push_to_talk":
            raise ServiceError("voice_mode", "Hands-free voice detects speech by itself.")
        try:
            self.authorize(session)
        except ServiceError as exc:
            await self.end(session, "error", exc.code, str(exc))
            raise
        session.last_activity = self.clock()
        if args.state == "start" and not session.holding:
            session.holding = True
            session.outbound.put_nowait(("activity_start", None))
            await self.set_state(session, "listening")
        elif args.state == "end" and session.holding:
            session.holding = False
            session.outbound.put_nowait(("activity_end", None))
            await self.set_state(session, "thinking")

    async def stop(self, sid, args):
        session = next(
            (item for item in self.sessions.values() if item.id == str(args.session_id)), None
        )
        if session and session.sid == sid:
            await self.end(session, "ended", "stopped", "Voice is off.")

    async def stop_sid(self, sid=None, code="stopped", message="Voice is off."):
        sessions = [
            item for item in tuple(self.sessions.values()) if sid is None or item.sid == sid
        ]
        for session in sessions:
            await self.end(session, "ended", code, message)

    async def restrict(self):
        gaming = self.app.resources.state == "gaming"
        code = "gaming_mode" if gaming else "resource_policy"
        message = "Voice stopped for gaming mode." if gaming else "Voice stopped."
        # Resident state is where tray voice lives; gaming mode stops every session.
        for session in tuple(self.sessions.values()):
            if gaming or session.endpoint != "local":
                await self.end(session, "ended", code, message)

    # --- tray requests (local endpoint) -------------------------------------------------

    def local_audio(self, **callbacks):
        from services.audio_devices import LocalAudio

        return LocalAudio(self.app.audio_devices, **callbacks)

    async def start_local(self):
        """Tray "Talk to JARVIS": hands-free voice through this PC's microphone and speaker.

        Returns an ACK-shaped result and never raises a refusal: the tray shows the message.
        """
        try:
            return {"ok": True, **await self._start_local()}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            if exc.code != "voice_stopped":  # else whatever stopped it already said why
                self.publish_local(self.local_status(notice=str(exc)))
            return {"ok": False, "code": exc.code, "message": str(exc)}

    async def _start_local(self):
        owner = self.local_owner()
        self.require_local_owner(owner)
        self.require_resources("local")
        self.require_permission()
        current = self.sessions.get(owner)
        if current and not current.closed:
            if current.endpoint == "local":
                raise ServiceError("voice_busy", "Voice is already on.")
            raise ServiceError(
                "voice_busy", "Voice is already on in the workspace. Stop it there first."
            )
        self.preflight()
        project = self.app.projects.get_current_project_path().resolve()
        conversation_id = self.app.conversation.current_conversation(owner, project)
        now = self.clock()
        session = VoiceSession(
            id=str(uuid.uuid4()),
            sid=None,
            owner=owner,
            project=project,
            conversation_id=str(conversation_id),
            mode="conversation",
            started=now,
            last_activity=now,
            endpoint="local",
        )
        # Hold the one-per-owner slot while the devices open.
        self.sessions[owner] = session
        self.publish_local(self.local_status(session))
        try:
            from services.audio_devices import local_choices

            session.audio = self.audio_factory(
                on_frame=lambda pcm: self.local_frame(session, pcm),
                on_lost=lambda kind: self.local_lost(session, kind),
                on_change=lambda: self.publish_local(self.local_status(session)),
            )
            notices = await session.audio.open(*local_choices(self.app.settings))
            session.notice = " ".join(notices) or None
            self.authorize(session)  # opening took a moment: still the owner's, same project
            session.usage = self.app.usage.operation(owner, project, "voice_live", session.id)
            # Admission before any provider connection: budget caps apply per Live turn.
            session.ticket, session.ticket_started = (
                session.usage.begin(model_id("voice")),
                self.clock(),
            )
        except ServiceError as exc:
            await self.end(session, "error", exc.code, str(exc))
            raise
        except BaseException:
            await self.end(session, "error", "voice_failed", "Voice could not start.")
            raise
        session.runner = asyncio.create_task(self.run(session), name="voice-live")
        session.watchdog = asyncio.create_task(self.watch(session), name="voice-watchdog")
        self.publish_local(self.local_status(session))
        logger.info("Tray voice started")
        return {
            "session_id": session.id,
            "conversation_id": session.conversation_id,
            "notices": notices,
        }

    async def stop_local(self, code="stopped", message="Voice is off."):
        """Tray "Stop talking": a safety stop, always allowed."""
        for session in tuple(self.sessions.values()):
            if session.endpoint == "local":
                await self.end(session, "ended", code, message)
        if not any(item.endpoint == "local" for item in self.sessions.values()):
            self.publish_local(self.local_status())
        return {"ok": True}

    def local_frame(self, session, pcm):
        """One 40 ms 16 kHz microphone frame; half-duplex: dropped while JARVIS is audible."""
        if session.closed or session.audio is None:
            return
        if session.audio.speaking():
            session.audio.gated += 1
            return
        if session.queued_audio >= QUEUED_AUDIO_LIMIT:
            session.audio.backlog_dropped += 1
            return
        session.queued_audio += 1
        session.outbound.put_nowait(("audio", pcm))

    def local_lost(self, session, kind):
        if not session.closed:
            self.spawn_end(
                session, "error", "audio_device_lost", f"The {kind} was disconnected. Voice is off."
            )

    def local_status(self, session=None, notice=None):
        """What the tray shows: state, microphone (on / paused while JARVIS speaks / off)."""
        if session is None or session.closed:
            return {"active": False, "state": "off", "microphone": "off", "notice": notice}
        opened = session.audio is not None and getattr(session.audio, "ready", False)
        audible = opened and session.audio.speaking()
        state = "speaking" if audible and session.state != "connecting" else session.state
        if state == "idle":
            state = "listening"
        return {
            "active": True,
            "state": state,
            "microphone": "paused" if audible else "on" if opened else "off",
            "notice": session.notice,
        }

    def publish_local(self, status):
        if status == self.local_published:
            return
        self.local_published = status
        observer = self.local_observer
        if observer is None:
            return
        try:
            observer(dict(status))
        except Exception:
            logger.warning("Tray voice status could not be delivered", exc_info=True)

    def renderer_rooms(self, session):
        return self.app.sessions.rooms(session.owner, "renderer")

    async def show_in_workspace(self, session):
        """Refresh an open workspace showing this conversation (tray voice only)."""
        rooms = self.renderer_rooms(session)
        transport = getattr(self.app, "conversation_transport", None)
        typing = set(getattr(transport, "running", {}).values())
        # A typed turn in flight shows its own result; the next refresh catches up.
        if not rooms or typing & set(rooms):
            return
        try:
            messages = self.app.conversation.restore(
                session.owner, session.conversation_id, session.project
            )
        except Exception:
            logger.warning("Voice turns could not be shown in the workspace", exc_info=True)
            return
        payload = {
            "conversation_id": session.conversation_id,
            "project": self.app.projects.current_project,
            "messages": messages,
        }
        for room in rooms:
            await self.app.sio.emit("conversation_restored", payload, room=room)

    # --- core -> renderer ------------------------------------------------------------

    async def emit(self, session, event, payload):
        if session.endpoint == "local":
            self.deliver_local(session, event, payload)
            return
        await self.app.sio.emit(event, {"session_id": session.id, **payload}, room=session.sid)

    def deliver_local(self, session, event, payload):
        """The local endpoint's renderer: the PC's speaker and the tray."""
        audio = session.audio
        if event == "voice_audio_out":
            if audio is not None and not session.closed:
                audio.play(payload["pcm"])
        elif event == "voice_interrupted":
            if audio is not None:
                audio.flush()
        elif event == "voice_state":
            if session.closed:
                code = payload.get("code")
                quiet = payload.get("state") == "ended" and code in QUIET_ENDS
                self.publish_local(
                    self.local_status(notice=None if quiet else payload.get("message"))
                )
            else:
                self.publish_local(self.local_status(session))
        # Captions are recorded as conversation turns when each turn completes.

    async def set_state(self, session, state, code=None, message=None):
        if session.state == state and code is None:
            return
        session.state = state
        payload = {"state": state}
        if code:
            payload["code"] = code
        if message:
            payload["message"] = message
        await self.emit(session, "voice_state", payload)

    def rest_state(self, session):
        if session.mode == "conversation" or session.holding:
            return "listening"
        return "idle"

    # --- session lifetime --------------------------------------------------------------

    def config(self, session):
        ticket = session.ticket
        return make_live_config(
            self.app.settings,
            mode=session.mode,
            handle=session.handle,
            max_output_tokens=ticket["max_output_tokens"] if ticket and ticket["capped"] else None,
        )

    async def run(self, session):
        attempts = 0
        try:
            while not session.closed:
                session.go_away = False
                try:
                    async with self.connector(model_id("voice"), self.config(session)) as live:
                        session.live, session.connected, attempts = live, True, 0
                        await self.set_state(session, self.rest_state(session))
                        sender = asyncio.create_task(self.send_loop(session, live))
                        receiver = asyncio.create_task(self.receive_loop(session, live))
                        try:
                            # Either direction failing ends this connection.
                            done, _ = await asyncio.wait(
                                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                            )
                            for task in done:
                                task.result()
                        finally:
                            for task in (sender, receiver):
                                task.cancel()
                            await asyncio.gather(sender, receiver, return_exceptions=True)
                            session.live = None
                    if session.closed:
                        return
                    if not session.go_away:
                        raise ConnectionError("Live connection ended")
                    # GoAway: reconnect at once with the latest resumption handle.
                    await self.set_state(session, "connecting")
                except asyncio.CancelledError:
                    raise
                except ServiceError as exc:
                    await self.end(session, "error", exc.code, str(exc))
                    return
                except Exception as exc:
                    attempts += 1
                    if session.closed:
                        return
                    if session.connected and session.handle and attempts <= RECONNECT_ATTEMPTS:
                        logger.info("Live voice dropped; resuming (%s)", type(exc).__name__)
                        await self.set_state(session, "connecting")
                        await asyncio.sleep(self.retry_delay * attempts)
                        continue
                    code, message = failure_code(exc)
                    logger.warning("Live voice failed: %s", type(exc).__name__)
                    await self.end(session, "error", code, message)
                    return
        finally:
            session.live = None

    async def send_loop(self, session, live):
        from google.genai import types

        while True:
            kind, value = await session.outbound.get()
            if kind == "audio":
                session.queued_audio = max(0, session.queued_audio - 1)
                await live.send_realtime_input(audio=types.Blob(data=value, mime_type=PCM_MIME))
            elif kind == "activity_start":
                await live.send_realtime_input(activity_start=types.ActivityStart())
            elif kind == "activity_end":
                await live.send_realtime_input(activity_end=types.ActivityEnd())
            elif kind == "tool":
                await live.send_tool_response(function_responses=value)

    async def receive_loop(self, session, live):
        while not session.closed:
            received = False
            async for message in live.receive():
                received = True
                await self.handle(session, message)
                if session.go_away or session.closed:
                    return
            if not received:
                raise ConnectionError("Live stream closed")

    async def watch(self, session):
        try:
            while not session.closed:
                await asyncio.sleep(self.tick)
                if session.closed:
                    return
                try:
                    self.authorize(session)
                except ServiceError as exc:
                    await self.end(session, "ended", exc.code, str(exc))
                    return
                now = self.clock()
                if session.ending is not None and now - session.ending > END_GRACE_SECONDS:
                    await self.end(session, "ended", "conversation_ended", "Voice is off.")
                    return
                if (
                    session.state == "thinking"
                    and not session.brain
                    and now - session.last_activity > THINKING_SECONDS
                ):
                    await self.set_state(session, self.rest_state(session))
                if (
                    not session.brain
                    and not session.holding
                    and now - session.last_activity > self.silence
                ):
                    await self.end(
                        session, "ended", "silence_timeout", "Voice ended after a minute of quiet."
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice watchdog failed")
            await self.end(session, "error", "voice_failed", "Voice stopped unexpectedly.")

    async def end(self, session, state="ended", code=None, message=None):
        if session.closed:
            return
        session.closed = True
        session.holding = False
        if self.sessions.get(session.owner) is session:
            del self.sessions[session.owner]
        current = asyncio.current_task()
        tasks = [
            task
            for task in (session.runner, session.watchdog, *session.brain.values())
            if task and task is not current and not task.done()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        session.brain.clear()
        while not session.outbound.empty():
            session.outbound.get_nowait()
        session.queued_audio = 0
        if session.audio is not None:
            # The microphone closes with the session, before anything else can wait.
            try:
                await session.audio.close()
            except Exception:
                logger.warning("Local audio did not close cleanly", exc_info=True)
            if code:
                logger.info("Tray voice ended (%s)", code)
        try:
            await self.complete_turn(session, final=True)
            pending = [task for task in session.tasks if task is not current]
            if pending:
                await asyncio.wait(pending, timeout=5)
        finally:
            self.finish_ticket(session, None, final=True)
            session.state = state
            payload = {"state": state, **({"code": code} if code else {})}
            if message:
                payload["message"] = message
            try:
                await self.emit(session, "voice_state", payload)
            except Exception:
                logger.warning("Voice end state could not be delivered", exc_info=True)

    # --- Live server messages ----------------------------------------------------------

    async def handle(self, session, message):
        update = getattr(message, "session_resumption_update", None)
        if update and update.resumable and update.new_handle:
            session.handle = update.new_handle
        if getattr(message, "go_away", None) is not None:
            session.go_away = True
        if getattr(message, "usage_metadata", None) is not None:
            self.record_usage(session, message.usage_metadata)
        call = getattr(message, "tool_call", None)
        if call:
            for function in call.function_calls or []:
                await self.tool_call(session, function)
        cancellation = getattr(message, "tool_call_cancellation", None)
        if cancellation:
            for identifier in cancellation.ids or []:
                task = session.brain.get(identifier)
                if task:
                    task.cancel()
        content = getattr(message, "server_content", None)
        if content is None:
            return
        if content.input_transcription and content.input_transcription.text:
            session.user_text = (session.user_text + content.input_transcription.text)[
                -CAPTION_LIMIT:
            ]
            session.last_activity = self.clock()
            await self.emit(
                session, "voice_caption", {"role": "user", "text": session.user_text, "final": False}
            )
        if content.interrupted:
            await self.emit(session, "voice_interrupted", {})
            await self.complete_turn(session)
        if content.model_turn and content.model_turn.parts:
            for part in content.model_turn.parts:
                data = getattr(part, "inline_data", None)
                if data and data.data and str(data.mime_type or "").startswith("audio/pcm"):
                    session.last_activity = self.clock()
                    if session.state != "speaking":
                        await self.set_state(session, "speaking")
                    session.out_seq += 1
                    await self.emit(
                        session, "voice_audio_out", {"seq": session.out_seq, "pcm": data.data}
                    )
        if content.output_transcription and content.output_transcription.text:
            session.jarvis_text = (session.jarvis_text + content.output_transcription.text)[
                -CAPTION_LIMIT:
            ]
            await self.emit(
                session, "voice_caption", {"role": "jarvis", "text": session.jarvis_text, "final": False}
            )
        if content.turn_complete:
            await self.complete_turn(session)

    async def complete_turn(self, session, final=False):
        user, jarvis = session.user_text.strip(), session.jarvis_text.strip()
        session.user_text = session.jarvis_text = ""
        brain = session.brain_turn
        if not session.brain:  # the answer after a hand-off belongs to the same exchange
            session.brain_turn = False
        if user:
            await self.emit(session, "voice_caption", {"role": "user", "text": user, "final": True})
        if jarvis:
            await self.emit(session, "voice_caption", {"role": "jarvis", "text": jarvis, "final": True})
        # A brain hand-off already recorded its own request and answer.
        if (user or jarvis) and not brain:
            task = asyncio.create_task(self.record(session, user, jarvis))
            session.tasks.add(task)
            task.add_done_callback(session.tasks.discard)
        if final:
            return
        session.last_activity = self.clock()
        if session.stop_after_turn is not None:
            error = session.stop_after_turn
            self.spawn_end(session, "error", error.code, str(error))
        elif session.ending is not None and not session.brain:
            self.spawn_end(session, "ended", "conversation_ended", "Voice is off.")
        elif not session.brain:
            await self.set_state(session, self.rest_state(session))

    def spawn_end(self, session, state, code, message):
        # Ending cancels the receive loop that is running this handler, so it runs apart.
        task = asyncio.create_task(self.end(session, state, code, message))
        self.ending.add(task)
        task.add_done_callback(self.ending.discard)

    async def record(self, session, user, jarvis):
        async with session.history_lock:
            try:
                await self.app.conversation.append_turns(
                    session.owner,
                    session.conversation_id,
                    session.project,
                    [{"role": "user", "content": user}, {"role": "assistant", "content": jarvis}],
                )
            except Exception:
                logger.warning("Voice turn could not be added to the conversation", exc_info=True)
                return
        if session.endpoint == "local":
            await self.show_in_workspace(session)

    # --- tools -------------------------------------------------------------------------

    def respond(self, session, call, response):
        from google.genai import types

        if not session.closed:
            session.outbound.put_nowait(
                (
                    "tool",
                    [types.FunctionResponse(id=call.id, name=call.name, response=response)],
                )
            )

    async def tool_call(self, session, call):
        session.last_activity = self.clock()
        if call.name == "ask_brain":
            session.brain_turn = True
            task = asyncio.create_task(self.ask_brain(session, call), name="voice-brain")
            session.brain[call.id] = task
            task.add_done_callback(lambda _: session.brain.pop(call.id, None))
            await self.set_state(session, "working")
        elif call.name == "end_conversation" and session.mode == "conversation":
            session.ending = self.clock()
            self.respond(session, call, {"result": "Ending the conversation."})
        else:
            self.respond(
                session,
                call,
                {"error": "tool_unavailable", "message": "Use ask_brain for this request."},
            )

    async def ask_brain(self, session, call):
        args = call.args if isinstance(call.args, dict) else {}
        request = args.get("request")
        try:
            if not isinstance(request, str) or not request.strip() or len(request) > CAPTION_LIMIT:
                raise ServiceError("invalid_arguments", "Pass the owner's request as text.")
            self.authorize(session)

            async def approve(payload):
                self.authorize(session)
                request = {
                    **payload,
                    "voice_session_id": session.id,
                    "project": session.project.name,
                }
                if session.endpoint != "local":
                    await self.app.sio.emit("tool_confirmation_request", request, room=session.sid)
                    return
                # Tray voice: approvals still happen on screen, in an open workspace.
                rooms = self.renderer_rooms(session)
                if not rooms:
                    raise ServiceError(
                        "approval_unavailable",
                        "This needs your approval on screen. Open the JARVIS workspace, "
                        "then ask again.",
                    )
                for room in rooms:
                    await self.app.sio.emit("tool_confirmation_request", request, room=room)

            turn = ConversationRequest(text=request.strip(), conversation_id=session.conversation_id)
            result = await self.app.conversation.reply(
                session.owner,
                turn,
                session.project,
                approve,
                origin_sid=session.sid,
                authorize=lambda: self.authorize(session),
                usage_feature="voice_brain",
            )
            self.authorize(session)
            if session.endpoint == "local":
                # The brain recorded the exchange; an open workspace shows it.
                await self.show_in_workspace(session)
                return await self.answered(session, call, {"result": result.text})
            # The full answer goes on screen through the existing transcript event.
            await self.app.sio.emit(
                "transcription",
                {
                    "sender": "JARVIS",
                    "text": result.text,
                    **(
                        {
                            "memory_sources": [
                                item.model_dump(mode="json") for item in result.memory_sources
                            ]
                        }
                        if getattr(result, "memory_sources", None)
                        else {}
                    ),
                    "request_id": str(turn.request_id),
                    "conversation_id": session.conversation_id,
                    "project": session.project.name,
                },
                room=session.sid,
            )
            response = {"result": result.text}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            response = {"error": exc.code, "message": str(exc)}
        except Exception:
            logger.exception("Voice brain hand-off failed")
            response = {"error": "brain_failed", "message": "The brain could not finish this."}
        await self.answered(session, call, response)

    async def answered(self, session, call, response):
        self.respond(session, call, response)
        if not session.closed:
            session.last_activity = self.clock()
            await self.set_state(session, "thinking")

    # --- usage -------------------------------------------------------------------------

    def finish_ticket(self, session, counts, final=False):
        ticket, session.ticket = session.ticket, None
        if ticket:
            state = "completed" if counts else "uncertain"
            self.app.usage.finish(ticket, state, counts, self.clock() - session.ticket_started)

    def record_usage(self, session, metadata):
        counts = live_usage_counts(metadata)
        if not counts:
            return
        self.finish_ticket(session, counts)
        try:
            session.ticket, session.ticket_started = (
                session.usage.begin(model_id("voice")),
                self.clock(),
            )
        except ServiceError as exc:
            # Budget reached: finish speaking this turn, then stop.
            session.stop_after_turn = exc


class VoiceTransport:
    def __init__(self, app):
        self.app = app
        for name in ("start", "audio", "activity", "stop"):
            app.sio.on("voice_" + name, handler=getattr(self, name))

    @staticmethod
    def failure(exc):
        if isinstance(exc, ServiceError):
            return {"ok": False, "code": exc.code, "message": str(exc)}
        if isinstance(exc, ValidationError):
            return {"ok": False, "code": "invalid_arguments", "message": "Invalid voice request."}
        return {"ok": False, "code": "voice_failed", "message": "Voice could not start. Type a message instead."}

    async def start(self, sid, data=None):
        try:
            return {"ok": True, **await self.app.voice.start(sid, VoiceStart.model_validate(data))}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not isinstance(exc, (ServiceError, ValidationError)):
                logger.exception("Voice start failed")
            return self.failure(exc)

    async def audio(self, sid, data=None):
        # Hot path: no ACK and no await before the frame is queued, so frames keep their order.
        self.app.voice.audio(sid, data)

    async def activity(self, sid, data=None):
        try:
            await self.app.voice.activity(sid, VoiceActivity.model_validate(data))
            return {"ok": True}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self.failure(exc)

    async def stop(self, sid, data=None):
        try:
            # A safety stop: allowed while locked, never needs the session to be valid.
            self.app.sessions.require_owner(sid, {"renderer"}, allow_locked=True)
            await self.app.voice.stop(sid, VoiceReference.model_validate(data))
            return {"ok": True}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self.failure(exc)

    async def stop_sid(self, sid=None):
        await self.app.voice.stop_sid(sid)
