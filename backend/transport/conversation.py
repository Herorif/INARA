"""Typed conversation Socket.IO adapter with injected service and session context."""

import uuid
from pydantic import BaseModel, ConfigDict, ValidationError
from services.conversation import ConversationRequest
from services.storage import StorageError
from services.tools import ServiceError


class ResumeConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: uuid.UUID


class ConversationTransport:
    events = ("user_input", "resume_conversation")

    def __init__(self, sio, service, dispatcher, sessions):
        self.sio, self.service, self.dispatcher, self.sessions = sio, service, dispatcher, sessions
        for name in self.events:
            sio.on(name, handler=getattr(self, name))

    async def resume_conversation(self, sid, data):
        try:
            request = ResumeConversation.model_validate(data)
            principal = self.sessions.principals.get(sid)
            if principal is None or not self.dispatcher.authenticated(principal):
                raise ServiceError(
                    "authentication_required", "Unlock INARA before restoring conversation."
                )
            context = self.sessions.context(sid)
            messages = self.service.restore(
                context.principal, request.conversation_id, context.project_path
            )
            await self.sio.emit(
                "conversation_restored",
                {
                    "conversation_id": str(request.conversation_id),
                    "project": context.project,
                    "messages": messages,
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
        try:
            request = ConversationRequest.model_validate(data)
            if not request.text.strip():
                raise ServiceError("invalid_request", "Enter a message first.")
            principal = self.sessions.principals.get(sid)
            if principal is None or not self.dispatcher.authenticated(principal):
                raise ServiceError("authentication_required", "Authentication is required.")
            context = self.sessions.context(sid)

            async def approve(payload):
                await self.sio.emit("tool_confirmation_request", payload, room=sid)

            await self.sio.emit(
                "text_status",
                {"state": "processing", "request_id": str(request.request_id)},
                room=sid,
            )
            result = await self.service.reply(principal, request, context.project_path, approve)
            await self.sio.emit("conversation_result", result.model_dump(mode="json"), room=sid)
            # Preserve the existing desktop transcript event contract.
            await self.sio.emit(
                "transcription",
                {"sender": "INARA", "text": result.text, "request_id": str(request.request_id)},
                room=sid,
            )
        except (ServiceError, ValidationError) as exc:
            await self.sio.emit(
                "error",
                {
                    "msg": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Invalid message payload.",
                    "code": getattr(exc, "code", "invalid_request"),
                    "request_id": str(request.request_id) if request else None,
                },
                room=sid,
            )
        except StorageError as exc:
            await self.sio.emit(
                "error",
                {
                    "msg": str(exc),
                    "code": "storage_unavailable",
                    "request_id": str(request.request_id) if request else None,
                },
                room=sid,
            )
        finally:
            await self.sio.emit("text_status", {"state": "idle"}, room=sid)
