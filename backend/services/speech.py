"""One bounded push-to-talk session; reviewed text uses the normal conversation service."""

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from services.conversation import ConversationRequest
from services.tools import ServiceError, ToolSpec


class SpeechTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: uuid.UUID


class SpeechBegin(SpeechTurn):
    conversation_id: uuid.UUID


class SpeechFrame(SpeechTurn):
    codec: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate: Literal[16000] = 16000
    channels: Literal[1] = 1
    sequence: StrictInt = Field(ge=0, lt=1000)
    timestamp_ms: StrictInt = Field(ge=0, lt=20000)
    duration_ms: Literal[20] = 20
    data: StrictStr = Field(min_length=856, max_length=856)

    @field_validator("sample_rate", "channels", "duration_ms", mode="before")
    @classmethod
    def exact_integers(cls, value):
        if type(value) is not int:
            raise ValueError("Use integer audio metadata")
        return value


class SpeechSend(SpeechTurn):
    text: StrictStr = Field(min_length=1, max_length=12000)

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip():
            raise ValueError("Enter a message first")
        return value


@dataclass
class Turn:
    sid: str
    owner: str
    project: Path
    turn_id: str
    conversation_id: str
    state: str = "armed"
    pcm: bytearray = field(default_factory=bytearray)
    sequence: int = 0
    capture_started: float | None = None
    task: object = None
    watchdog: object = None
    touched: float = field(default_factory=time.monotonic)


class SpeechService:
    def __init__(self, app, transcriber=None, preflight=None):
        from services.speech_provider import transcribe, ready

        self.app = app
        self.transcriber, self.preflight = transcriber or transcribe, preflight or ready
        self.turn = None
        app.dispatcher.register(
            ToolSpec(
                "speech_capture",
                "Begin an explicitly requested bounded push-to-talk turn, with no microphone opened by the core.",
                SpeechBegin,
                self.execute_begin,
                permission="start_audio",
                model_visible=False,
            )
        )

    async def execute_begin(self, args, context):
        return await self.begin(context["origin_sid"], args)

    def authorize(self, turn):
        if self.turn is not turn:
            raise ServiceError("speech_stopped", "This speech turn has stopped.")
        owner = self.app.sessions.require_owner(turn.sid, {"renderer"})
        if (
            owner != turn.owner
            or self.app.projects.get_current_project_path().resolve() != turn.project
        ):
            raise ServiceError(
                "speech_scope", "The voice project or connection changed. Start a new turn."
            )
        self.app.resources.require_heavy()
        if any(
            self.app.settings["tool_permissions"].get(name) == "deny"
            for name in ("start_audio", "speech_capture")
        ):
            raise ServiceError("permission_denied", "Microphone permission was revoked.")

    def require(self, sid, identifier):
        turn = self.turn
        if not turn or turn.sid != sid or turn.turn_id != str(identifier):
            raise ServiceError("speech_missing", "Start a new push-to-talk turn.")
        self.authorize(turn)
        if turn.state == "listening" and time.monotonic() - turn.touched > 15:
            raise ServiceError(
                "speech_interrupted", "Speech was suspended or stalled. Start a new turn."
            )
        turn.touched = time.monotonic()
        return turn

    async def status(self, turn, state, **extra):
        if self.turn is turn:
            turn.state = state
            await self.app.sio.emit(
                "speech_state",
                {
                    "turn_id": turn.turn_id,
                    "conversation_id": turn.conversation_id,
                    "project": turn.project.name,
                    "state": state,
                    **extra,
                },
                room=turn.sid,
            )

    async def begin(self, sid, args):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        self.app.resources.require_heavy()
        if self.turn:
            raise ServiceError(
                "speech_busy", "Another speech turn owns the microphone session. Stop it first."
            )
        self.preflight()
        turn = Turn(
            sid,
            owner,
            self.app.projects.get_current_project_path().resolve(),
            str(args.turn_id),
            str(args.conversation_id),
        )
        self.turn = turn
        turn.watchdog = asyncio.create_task(self.watch(turn))
        await self.status(turn, "armed")
        return {"turn_id": turn.turn_id, "state": "armed", "max_seconds": 20}

    async def watch(self, turn):
        started = time.monotonic()
        try:
            while self.turn is turn:
                await asyncio.sleep(1)
                self.authorize(turn)
                age = time.monotonic() - started
                if age > 120 or (
                    turn.capture_started is not None
                    and turn.state == "listening"
                    and time.monotonic() - turn.capture_started > 22
                ):
                    raise ServiceError(
                        "speech_expired", "Speech turn expired. Press to talk again."
                    )
        except ServiceError as exc:
            await self.status(turn, "error", message=str(exc))
            await self.stop(turn.sid)

    async def frame(self, sid, args):
        turn = self.require(sid, args.turn_id)
        if turn.state == "armed":
            turn.state = "listening"
            turn.capture_started = time.monotonic()
        if (
            turn.state != "listening"
            or args.sequence != turn.sequence
            or args.timestamp_ms != turn.sequence * 20
        ):
            raise ServiceError(
                "speech_sequence", "An audio frame was missing or duplicated. Record a new turn."
            )
        try:
            raw = base64.b64decode(args.data, validate=True)
        except ValueError as exc:
            raise ServiceError("speech_frame", "Invalid audio frame.") from exc
        if len(raw) != 640 or len(turn.pcm) + len(raw) > 640000:
            raise ServiceError("speech_limit", "Audio reached its bounded turn limit.")
        turn.pcm.extend(raw)
        turn.sequence += 1
        return {"sequence": args.sequence}

    async def finish(self, sid, args):
        turn = self.require(sid, args.turn_id)
        if turn.state != "listening" or turn.sequence < 5:
            raise ServiceError("speech_empty", "Hold to talk for at least a moment, then release.")
        turn.task = asyncio.current_task()
        raw = bytes(turn.pcm)
        turn.pcm.clear()
        await self.status(turn, "transcribing")
        try:

            async def partial(text):
                self.authorize(turn)
                if not isinstance(text, str) or len(text) > 12000:
                    raise ServiceError("speech_transcript", "Transcript exceeded its limit.")
                await self.status(turn, "transcribing", transcript=text)

            text = await asyncio.wait_for(self.transcriber(raw, partial), 40)
            self.authorize(turn)
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ServiceError(
                    "speech_transcript", "No usable transcript was returned. Try again or type."
                )
            turn.touched = time.monotonic()
            await self.status(turn, "review", transcript=text.strip())
            return {"turn_id": turn.turn_id, "state": "review", "text": text.strip()}
        finally:
            turn.task = None

    async def send(self, sid, args):
        turn = self.require(sid, args.turn_id)
        if turn.state != "review":
            raise ServiceError("speech_state", "Review a completed transcript before sending it.")
        turn.task = asyncio.current_task()
        await self.status(turn, "thinking")

        async def approve(payload):
            self.authorize(turn)
            await self.app.sio.emit(
                "tool_confirmation_request",
                {**payload, "speech_turn_id": turn.turn_id, "project": turn.project.name},
                room=sid,
            )

        try:
            result = await self.app.conversation.reply(
                turn.owner,
                ConversationRequest(
                    text=args.text, conversation_id=turn.conversation_id, request_id=turn.turn_id
                ),
                turn.project,
                approve,
                origin_sid=sid,
                authorize=lambda: self.authorize(turn),
            )
            self.authorize(turn)
            await self.status(turn, "answered")
            return {"turn_id": turn.turn_id, "state": "answered", "text": result.text}
        finally:
            await self.stop(sid)

    async def stop(self, sid=None):
        turn = self.turn
        if not turn or (sid is not None and turn.sid != sid):
            return
        self.turn = None
        turn.pcm.clear()
        tasks = [
            task
            for task in (turn.task, turn.watchdog)
            if task and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class SpeechTransport:
    models = {
        "begin": SpeechBegin,
        "frame": SpeechFrame,
        "finish": SpeechTurn,
        "send": SpeechSend,
        "cancel": SpeechTurn,
    }

    def __init__(self, app):
        self.app = app
        self.pending = {}
        for name, model in self.models.items():
            app.sio.on("speech_" + name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def call(sid, data=None):
            pending_key = None
            try:
                self.app.sessions.require_owner(sid, {"renderer"}, allow_locked=name == "cancel")
                args = model.model_validate(data)
                if name == "begin":
                    pending_key = (sid, str(args.turn_id))
                    if any(origin == sid for origin, _ in self.pending):
                        raise ServiceError("speech_busy", "A speech request is already pending.")
                    self.pending[pending_key] = asyncio.current_task()
                    self.app.speech.preflight()
                    context = self.app.sessions.context(sid, renderer=True)

                    async def approve(payload):
                        await self.app.sio.emit(
                            "tool_confirmation_request",
                            {
                                **payload,
                                "speech_turn_id": str(args.turn_id),
                                "project": context.project,
                            },
                            room=sid,
                        )

                    def authorize():
                        self.app.sessions.require_owner(sid, {"renderer"})
                        if (
                            self.app.projects.get_current_project_path().resolve()
                            != context.project_path
                        ):
                            raise ServiceError(
                                "speech_scope", "Project changed before audio capture."
                            )

                    return {
                        "ok": True,
                        **await self.app.dispatcher.dispatch(
                            context.principal,
                            "speech_capture",
                            args.model_dump(mode="json"),
                            {**context.tools(), "origin_sid": sid},
                            approve,
                            authorize=authorize,
                        ),
                    }
                if name == "cancel":
                    task = self.pending.get((sid, str(args.turn_id)))
                    if task and task is not asyncio.current_task():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    if self.app.speech.turn and self.app.speech.turn.turn_id == str(args.turn_id):
                        await self.app.speech.stop(sid)
                    return {"ok": True}
                return {"ok": True, **await getattr(self.app.speech, name)(sid, args)}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                from pydantic import ValidationError

                if name != "begin":
                    await self.app.speech.stop(sid)
                return {
                    "ok": False,
                    "code": getattr(
                        exc,
                        "code",
                        "invalid_arguments"
                        if isinstance(exc, ValidationError)
                        else "speech_failed",
                    ),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Speech could not complete. Type a message or start a new turn.",
                }

            finally:
                if pending_key and self.pending.get(pending_key) is asyncio.current_task():
                    self.pending.pop(pending_key, None)

        return call

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for (origin, _), task in tuple(self.pending.items())
            if (sid is None or origin == sid) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.app.speech.stop(sid)
