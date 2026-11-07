"""Typed conversation Socket.IO adapter with injected service and session context."""

import asyncio
import contextlib
import time
import uuid
from pydantic import BaseModel, ConfigDict, ValidationError
from services.conversation import ConversationRequest
from services.storage import StorageError
from services.tools import ServiceError


class ResumeConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: uuid.UUID


class CancelConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")


DELTA_INTERVAL = 0.05  # at most one transcription_delta per 50 ms per request
# The final transcription has no cap of its own; deltas stop growing here (about 4x
# Claude's 32k-token answer ceiling) so a runaway stream cannot flood the socket.
DELTA_TEXT_LIMIT = 128_000


class ReplyDeltas:
    """Coalesced ``transcription_delta`` events for one typed request.

    Each event carries the tool-loop ``step`` and that step's text so far (cumulative
    within the step). The latest text wins: at most one event per ``DELTA_INTERVAL``,
    with a trailing send for text that arrived inside the window. ``close()`` ends the stream for good, waiting out an event already being
    sent, so nothing is emitted after it: the caller closes before the final
    ``transcription``, before an error, and when the request is cancelled.
    """

    def __init__(self, emit, scope, interval=DELTA_INTERVAL, clock=time.monotonic):
        self.emit, self.scope, self.interval, self.clock = emit, scope, interval, clock
        self.latest = self.sent = None
        self.last = None
        self.timer = None
        self.closed = False
        self.lock = asyncio.Lock()

    async def text(self, text, step=0):
        if self.closed or not isinstance(text, str):
            return
        self.latest = (step, text[:DELTA_TEXT_LIMIT])
        if self.timer is not None:
            return  # the scheduled send picks up the latest text
        wait = 0 if self.last is None else self.last + self.interval - self.clock()
        if wait <= 0:
            await self._send()
        else:
            self.timer = asyncio.create_task(self._later(wait))

    async def working(self):
        """A tool step starts: deliver the step's text first, then say JARVIS is working."""
        await self.flush()
        if not self.closed:
            await self.emit("text_status", {"state": "processing", "phase": "tool", **self.scope})

    async def flush(self):
        timer, self.timer = self.timer, None
        if timer is not None:
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer
        if self.closed or self.latest == self.sent:
            async with self.lock:  # an event already being sent goes out first
                return
        wait = 0 if self.last is None else self.last + self.interval - self.clock()
        if wait > 0:
            await asyncio.sleep(wait)
        await self._send()

    async def _later(self, wait):
        await asyncio.sleep(wait)
        self.timer = None
        await self._send()

    async def _send(self):
        async with self.lock:
            if self.closed or self.latest is None or self.latest == self.sent:
                return
            self.sent, self.last = self.latest, self.clock()
            step, text = self.sent
            await self.emit(
                "transcription_delta",
                {
                    "request_id": self.scope["request_id"],
                    "conversation_id": self.scope["conversation_id"],
                    "step": step,
                    "text": text,
                },
            )

    async def close(self):
        self.closed = True
        timer, self.timer = self.timer, None
        if timer is not None and not timer.done():
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer
        async with self.lock:  # an event already being sent finishes first
            pass


class ConversationTransport:
    events = ("user_input", "resume_conversation", "cancel_conversation")

    def __init__(self, sio, service, dispatcher, sessions):
        self.sio, self.service, self.dispatcher, self.sessions = sio, service, dispatcher, sessions
        self.running = {}
        for name in self.events:
            sio.on(name, handler=getattr(self, name))

    async def cancel_conversation(self, sid, data=None):
        try:
            self.sessions.require_owner(sid, {"renderer"}, allow_locked=True)
            CancelConversation.model_validate(data)
            await self.stop_sid(sid)
            return {"ok": True}
        except (ServiceError, ValidationError):
            return {"ok": False, "code": "invalid_request"}

    async def resume_conversation(self, sid, data):
        try:
            request = ResumeConversation.model_validate(data)
            principal = self.sessions.principals.get(sid)
            if principal is None or not self.dispatcher.authenticated(principal):
                raise ServiceError(
                    "authentication_required", "Unlock JARVIS before restoring conversation."
                )
            context = self.sessions.context(sid)
            messages = self.service.restore(
                context.principal, request.conversation_id, context.project_path
            )
            # Tray voice may have started a conversation while the workspace was closed.
            latest = self.service.shown(
                context.principal, context.project_path, request.conversation_id
            )
            await self.sio.emit(
                "conversation_restored",
                {
                    "conversation_id": str(request.conversation_id),
                    "project": context.project,
                    "messages": messages,
                    **({"latest_conversation_id": latest} if latest else {}),
                },
                room=sid,
            )
        except (ServiceError, ValidationError, StorageError) as exc:
            await self.sio.emit(
                "conversation_restore_failed",
                {
                    "msg": str(exc)
                    if not isinstance(exc, ValidationError)
                    else "Invalid conversation ID.",
                    "conversation_id": data.get("conversation_id")
                    if isinstance(data, dict)
                    else None,
                },
                room=sid,
            )

    async def user_input(self, sid, data):
        request = None
        scope = {}
        deltas = None
        task = asyncio.current_task()
        self.running[task] = sid
        try:
            request = ConversationRequest.model_validate(data)
            if not request.text.strip():
                raise ServiceError("invalid_request", "Enter a message first.")
            principal = self.sessions.principals.get(sid)
            if principal is None or not self.dispatcher.authenticated(principal):
                raise ServiceError("authentication_required", "Authentication is required.")
            context = self.sessions.context(sid)
            scope = {
                "request_id": str(request.request_id),
                "conversation_id": str(request.conversation_id),
                "project": context.project_path.name,
            }

            async def approve(payload):
                await self.sio.emit("tool_confirmation_request", payload, room=sid)

            async def emit(event, payload):
                await self.sio.emit(event, payload, room=sid)

            deltas = ReplyDeltas(emit, scope)
            await self.sio.emit(
                "text_status",
                {"state": "processing", **scope},
                room=sid,
            )
            result = await self.service.reply(
                principal, request, context.project_path, approve, origin_sid=sid, stream=deltas
            )
            await deltas.close()  # no delta may follow the final transcription
            await self.sio.emit("conversation_result", result.model_dump(mode="json"), room=sid)
            # Preserve the existing desktop transcript event contract.
            await self.sio.emit(
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
                        if result.memory_sources
                        else {}
                    ),
                    **scope,
                },
                room=sid,
            )
        except (ServiceError, ValidationError) as exc:
            if deltas is not None:
                await deltas.close()
            await self.sio.emit(
                "error",
                {
                    "msg": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Invalid message payload.",
                    "code": getattr(exc, "code", "invalid_request"),
                    "request_id": str(request.request_id) if request else None,
                    **scope,
                },
                room=sid,
            )
        except StorageError as exc:
            if deltas is not None:
                await deltas.close()
            await self.sio.emit(
                "error",
                {
                    "msg": str(exc),
                    "code": "storage_unavailable",
                    "request_id": str(request.request_id) if request else None,
                    **scope,
                },
                room=sid,
            )
        finally:
            self.running.pop(task, None)
            if deltas is not None:
                # Cancelled mid-stream: stop the pending delta before anything else runs.
                await deltas.close()
            await self.sio.emit("text_status", {"state": "idle", **scope}, room=sid)

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.running.items())
            if (sid is None or origin == sid) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
