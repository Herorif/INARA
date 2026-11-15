"""Show JARVIS (docs/VISION_STUDIO.md#show-jarvis): one still photo answers one question.

- ``vision_ask`` (owner's unlocked workspace renderer): a typed chat turn with one JPEG,
  streamed exactly like typed chat (``text_status``, ``transcription_delta``,
  ``conversation_result``, ``transcription``) and acknowledged with the answer.
- ``look_through_camera`` (model-visible, always asks): the core asks the owner's workspace
  renderer for one frame (``vision_capture_request``), takes the one ``vision_capture_result``
  that answers it within 20 s, then makes one vision request with the current brain provider
  and returns the answer text.

The photo lives in memory for one request only. History and request receipts keep the text
line "📷 photo · <question>" and the answer; no image reaches the database, a file or a log.
This module logs no image, question or answer.
"""

import asyncio
import base64
import binascii
import re
import time
import unicodedata
import uuid
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from llm.base import Message, MessageRole
from services.conversation import (
    IMAGE_PROVIDERS,
    ConversationRequest,
    provider_failure,
)
from services.log import get_logger
from services.storage import StorageError
from services.tools import ServiceError, ToolSpec
from services.usage import metered_generate

logger = get_logger(__name__)

TOOL = "look_through_camera"
PHOTO_LINE = "📷 photo · "
QUESTION_LIMIT = 500
MAX_IMAGE_BYTES = 1_500_000  # decoded JPEG
MAX_IMAGE_TEXT = 4 * ((MAX_IMAGE_BYTES + 2) // 3)  # its base64 length
JPEG_MAGIC = b"\xff\xd8\xff"
CAPTURE_TIMEOUT = 20.0
CAPTURE_POLL = 0.25  # how often a waiting capture rechecks the window, lock and gaming
LOOK_TIMEOUT = 45.0  # the one vision request
CAPTURE_ERRORS = ("hidden", "denied", "unavailable", "busy", "gaming", "locked", "failed")

DESCRIPTION = (
    "Take one still photo with the owner's camera and answer a question about it. Use it when "
    "the owner asks you to look at something they are showing or holding, such as 'what's "
    "this?', 'can you read this label?' or 'what colour is this?'. The owner approves on "
    "screen first; the camera turns on for one photo, then turns off. One call takes one "
    "photo: never use it to watch or monitor. Returns the answer, or a plain message when no "
    "photo could be taken."
)
LOOK_NOTE = (
    "The owner approved one still photo from their camera so you can answer the question "
    "below. Answer it from the photo, briefly; say plainly if the photo doesn't show enough."
)

MESSAGES = {
    "gaming_mode": "The camera is off in gaming mode. Turn gaming mode off, then ask me again.",
    "locked": "JARVIS is locked. Unlock JARVIS on screen, then ask me again.",
    "workspace_unavailable": "I need the JARVIS window open to use the camera. Open JARVIS and "
    "ask me again.",
    "workspace_closed": "The JARVIS window closed before I could take the photo. Open JARVIS "
    "and ask me again.",
    "capture_timeout": "The camera didn't answer in time, so I couldn't take the photo. Ask me "
    "again.",
    "capture_hidden": "I couldn't take the photo because JARVIS's window was hidden. Open "
    "JARVIS and ask me again.",
    "capture_denied": "I couldn't take the photo because camera access was denied. Allow camera "
    "access for JARVIS in Windows settings, then ask me again.",
    "capture_unavailable": "I couldn't find a camera to take the photo. Connect a camera, then "
    "ask me again.",
    "capture_busy": "The camera is busy, so I couldn't take the photo. Close the other camera "
    "app or finish the photo in the Vision studio, then ask me again.",
    "capture_gaming": "The camera is off in gaming mode. Turn gaming mode off, then ask me "
    "again.",
    "capture_locked": "JARVIS is locked. Unlock JARVIS on screen, then ask me again.",
    "capture_failed": "I couldn't take the photo. Check the camera in the Vision studio, then "
    "ask me again.",
    "capture_invalid": "The photo from the camera couldn't be read. Ask me again.",
    "image_unsupported": "Your AI provider can't look at photos. Choose Claude or Gemini in "
    "Preferences > AI.",
    "empty_answer": "I took the photo but couldn't work out an answer. Ask me again.",
}
_CONTROL = re.compile(r"\s+")


def clean_question(value):
    """Control characters become spaces, whitespace collapses; 1-500 characters."""
    if not isinstance(value, str):
        return value
    value = "".join(" " if unicodedata.category(char) in ("Cc", "Cf") else char for char in value)
    value = _CONTROL.sub(" ", value).strip()
    if not value:
        raise ValueError("Ask a question first.")
    return value


def photo_line(question):
    """The owner's line in history and on screen; the photo itself is never stored."""
    return PHOTO_LINE + question


def decode_jpeg(value):
    """Base64 text -> JPEG bytes (at most 1.5 MB decoded, JPEG magic bytes), else ServiceError."""
    if not isinstance(value, str) or not value:
        raise ServiceError("image_invalid", "The photo couldn't be read. Take another.")
    if len(value) > MAX_IMAGE_TEXT:
        raise ServiceError("image_too_large", "The photo is too large. Take another.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ServiceError("image_invalid", "The photo couldn't be read. Take another.") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise ServiceError("image_too_large", "The photo is too large. Take another.")
    if len(data) < 4 or not data.startswith(JPEG_MAGIC):
        raise ServiceError("image_invalid", "The photo must be a JPEG. Take another.")
    return data


class VisionAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: uuid.UUID
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    question: StrictStr = Field(min_length=1, max_length=QUESTION_LIMIT)
    image: StrictStr = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def cleaned(cls, value):
        return clean_question(value)


class CaptureResult(BaseModel):
    """The renderer's answer to one ``vision_capture_request``: a JPEG or an error code."""

    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    image: StrictStr | None = Field(default=None, min_length=1)
    error: Literal["hidden", "denied", "unavailable", "busy", "gaming", "locked", "failed"] | None = (
        None
    )

    @model_validator(mode="after")
    def one_outcome(self):
        if (self.image is None) == (self.error is None):
            raise ValueError("Send either an image or an error.")
        return self


class LookArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: StrictStr = Field(
        min_length=1,
        max_length=QUESTION_LIMIT,
        description="The owner's question about what the camera will show, in their words.",
    )

    @field_validator("question")
    @classmethod
    def cleaned(cls, value):
        return clean_question(value)


def failure(code, message=None):
    return {"ok": False, "code": code, "message": message or MESSAGES.get(code, "Try again.")}


class ShowJarvis:
    """Owns the two Show JARVIS routes and the brain's ``look_through_camera`` tool."""

    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.pending = {}  # capture request_id -> (principal, sid, future); one use each
        app.sio.on("vision_ask", handler=self.vision_ask)
        app.sio.on("vision_capture_result", handler=self.capture_result)
        app.dispatcher.register(
            ToolSpec(
                TOOL,
                DESCRIPTION,
                LookArguments,
                self.look,
                always_ask=True,
                execution_timeout=CAPTURE_TIMEOUT + LOOK_TIMEOUT + 10,
                # What the camera sees can carry text from anyone (a note, a screen).
                untrusted_output=True,
                untrusted_source="the camera",
            )
        )

    # --- refusals ----------------------------------------------------------------------

    def gaming(self):
        return getattr(self.app.resources, "state", None) == "gaming"

    def refuse(self, principal):
        if self.gaming():
            raise ServiceError("gaming_mode", MESSAGES["gaming_mode"])
        if not self.app.sessions.authenticated(principal):
            raise ServiceError("authentication_required", MESSAGES["locked"])

    # --- vision_ask ----------------------------------------------------------------------

    async def vision_ask(self, sid, data=None):
        """One chat turn with one photo, streamed like typed chat; ACK carries the answer."""
        scope, deltas = {}, None
        transport = self.app.conversation_transport
        task = asyncio.current_task()
        transport.running[task] = sid  # cancel_conversation and disconnect stop it too
        try:
            principal = self.app.sessions.require_owner(sid, {"renderer"})
            if self.gaming():
                raise ServiceError("gaming_mode", "Photos can't be sent in gaming mode.")
            try:
                request = VisionAskRequest.model_validate(data)
            except ValidationError:
                # Never echo pydantic's text: it can quote the payload.
                raise ServiceError(
                    "invalid_request", "Ask a question of 1 to 500 characters with one photo."
                ) from None
            image = decode_jpeg(request.image)
            context = self.app.sessions.context(sid, renderer=True)
            scope = {
                "request_id": str(request.request_id),
                "conversation_id": str(request.conversation_id),
                "project": context.project_path.name,
            }

            async def approve(payload):
                await self.app.sio.emit("tool_confirmation_request", payload, room=sid)

            async def emit(event, payload):
                await self.app.sio.emit(event, payload, room=sid)

            from transport.conversation import ReplyDeltas

            deltas = ReplyDeltas(emit, scope)
            await emit("text_status", {"state": "processing", **scope})
            turn = ConversationRequest(
                text=photo_line(request.question),
                conversation_id=request.conversation_id,
                request_id=request.request_id,
            )
            try:
                result = await self.app.conversation.reply(
                    principal,
                    turn,
                    context.project_path,
                    approve,
                    origin_sid=sid,
                    authorize=lambda: self.app.sessions.require_owner(sid, {"renderer"}),
                    usage_feature="vision_ask",
                    stream=deltas,
                    image=image,
                )
            finally:
                image = None  # the photo is not kept past the request
            await deltas.close()
            await emit("conversation_result", result.model_dump(mode="json"))
            sources = [item.model_dump(mode="json") for item in result.memory_sources]
            await emit(
                "transcription",
                {
                    "sender": "JARVIS",
                    "text": result.text,
                    **({"memory_sources": sources} if sources else {}),
                    **scope,
                },
            )
            return {"ok": True, **scope, "text": result.text}
        except ServiceError as exc:
            if deltas is not None:
                await deltas.close()
            if scope:  # the owner's line is in the chat: show why there is no answer
                await self.app.sio.emit(
                    "error", {"msg": str(exc), "code": exc.code, **scope}, room=sid
                )
            return failure(exc.code, str(exc))
        except StorageError as exc:
            if deltas is not None:
                await deltas.close()
            if scope:
                await self.app.sio.emit(
                    "error", {"msg": str(exc), "code": "storage_unavailable", **scope}, room=sid
                )
            return failure("storage_unavailable", str(exc))
        except Exception as exc:
            # Only the exception's type: its text or traceback locals could hold the request.
            logger.error("Show JARVIS request failed: %s", type(exc).__name__)
            if deltas is not None:
                await deltas.close()
            message = "JARVIS couldn't answer about this photo. Try again."
            if scope:
                await self.app.sio.emit(
                    "error", {"msg": message, "code": "vision_failed", **scope}, room=sid
                )
            return failure("vision_failed", message)
        finally:
            transport.running.pop(task, None)
            if deltas is not None:
                await deltas.close()
            if scope:
                await self.app.sio.emit("text_status", {"state": "idle", **scope}, room=sid)

    # --- look_through_camera ---------------------------------------------------------------

    async def look(self, args, context):
        """After approval: one frame from the owner's workspace, one vision request."""
        principal = context["principal"]
        self.refuse(principal)
        provider = self.app.conversation.provider_factory()
        try:
            if getattr(provider, "name", None) not in IMAGE_PROVIDERS:
                raise ServiceError("image_unsupported", MESSAGES["image_unsupported"])
            image = await self.capture(principal, args.question, context.get("origin_sid"))
            try:
                self.refuse(principal)
                usage = getattr(self.app, "usage", None)
                operation = (
                    usage.operation(
                        principal,
                        context["project_path"],
                        "vision_look",
                        context.get("usage_operation") or str(uuid.uuid4()),
                    )
                    if usage
                    else None
                )
                messages = [
                    Message(
                        MessageRole.USER,
                        args.question,
                        attachments=[{"type": "image", "data": image, "mime_type": "image/jpeg"}],
                    )
                ]
                response = await asyncio.wait_for(
                    (operation.generate if operation else metered_generate)(
                        provider,
                        messages,
                        system_instruction=self.app.conversation.system_prompt() + " " + LOOK_NOTE,
                        effort="low",
                        budget=LOOK_TIMEOUT,
                    ),
                    LOOK_TIMEOUT,
                )
            finally:
                image = messages = None  # nothing keeps the photo
            text = (getattr(response, "text", None) or "").strip()
            if not text:
                raise ServiceError("empty_answer", MESSAGES["empty_answer"])
            return {"answer": text}
        except ServiceError:
            raise
        except TimeoutError as exc:
            from llm.base import log_provider_failure

            log_provider_failure(getattr(provider, "name", None) or "unknown", exc, reason="timeout")
            raise ServiceError("provider_timeout", "The AI request timed out. Try again.") from exc
        except Exception as exc:
            raise provider_failure(provider, exc) from exc
        finally:
            try:
                await asyncio.wait_for(provider.close(), 5)
            except Exception:
                logger.warning("AI provider client did not close cleanly", exc_info=True)

    async def capture(self, principal, question, origin_sid=None):
        """Ask one owner workspace renderer for one frame; JPEG bytes or a plain ServiceError."""
        rooms = self.app.sessions.rooms(principal, "renderer")
        if not rooms:
            raise ServiceError("workspace_unavailable", MESSAGES["workspace_unavailable"])
        sid = origin_sid if origin_sid in rooms else rooms[-1]
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (principal, sid, future)
        try:
            await self.app.sio.emit(
                "vision_capture_request", {"request_id": request_id, "question": question}, room=sid
            )
            deadline = self.clock() + CAPTURE_TIMEOUT
            while not future.done():
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise ServiceError("capture_timeout", MESSAGES["capture_timeout"])
                await asyncio.wait({future}, timeout=min(CAPTURE_POLL, remaining))
                if future.done():
                    break
                if self.app.sessions.principals.get(sid) != principal:
                    raise ServiceError("workspace_closed", MESSAGES["workspace_closed"])
                self.refuse(principal)
            outcome = future.result()
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()
        if isinstance(outcome, str):
            code = f"capture_{outcome}"
            raise ServiceError(code, MESSAGES.get(code, MESSAGES["capture_failed"]))
        return outcome

    async def capture_result(self, sid, data=None):
        """The one answer to a ``vision_capture_request``; any later answer is refused."""
        try:
            principal = self.app.sessions.require_owner(sid, {"renderer"}, allow_locked=True)
        except ServiceError as exc:
            return failure(exc.code, str(exc))
        try:
            result = CaptureResult.model_validate(data)
        except ValidationError:
            return failure("invalid_request", "Send the photo or an error for this request.")
        key = str(result.request_id)
        entry = self.pending.get(key)
        if entry is None or entry[0] != principal or entry[1] != sid or entry[2].done():
            return failure("unknown_request", "This photo request has ended.")
        future = self.pending.pop(key)[2]  # one use: the request is gone from here on
        if result.error is not None:
            future.set_result(result.error)
            return {"ok": True}
        if not self.app.sessions.authenticated(principal):
            future.set_result("locked")
            return failure("authentication_required", MESSAGES["locked"])
        try:
            image = decode_jpeg(result.image)
        except ServiceError as exc:
            future.set_result("invalid")
            return failure(exc.code, str(exc))
        future.set_result(image)
        return {"ok": True}
