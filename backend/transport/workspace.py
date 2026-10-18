"""Preserved desktop wire events over owned workspace services."""

import asyncio
import hashlib
from pydantic import ValidationError
from services.settings import EmptyRequest
from services.tools import ServiceError
from services.workspace import WORKSPACE_TOOLS
from transport.local_actions import LocalActionTransport


class WorkspaceTransport(LocalActionTransport):
    events = tuple(
        "generate_cad" if name == "legacy_generate_cad" else name for name in WORKSPACE_TOOLS
    )

    def __init__(self, sio, dispatcher, sessions, service):
        self.service = service
        self.media_requests = set()
        super().__init__(sio, dispatcher, sessions)
        for name in ("pause_audio", "stop_audio"):
            handler = self.safety_handler(name)
            setattr(self, name, handler)
            sio.on(name, handler=handler)

    def handler(self, name):
        tool = "legacy_generate_cad" if name == "generate_cad" else name
        execute = super().handler(tool)

        async def handle(sid, data=None):
            task = asyncio.current_task()
            media = name in ("start_audio", "resume_audio", "upload_memory", "video_frame")
            if media:
                self.media_requests.add(task)
            try:
                await execute(sid, data)
            finally:
                self.media_requests.discard(task)

        return handle

    def context(self, sid):
        self.sessions.require_owner(sid, {"renderer"})
        return super().context(sid)

    def tool_context(self, sid, context):
        return {**context.tools(), "origin_sid": sid}

    def approval_payload(self, payload):
        return approval_summary(payload)

    async def emit_result(self, name, result, sid):
        if name != "video_frame":
            await self.sio.emit("status", {"msg": result["message"]}, room=sid)
        if name in ("legacy_generate_cad", "iterate_cad"):
            await self.sio.emit("cad_status", {"status": "idle"}, room=sid)

    async def emit_error(self, name, sid, payload):
        if name in ("legacy_generate_cad", "iterate_cad"):
            await self.sio.emit("cad_status", {"status": "error"}, room=sid)
        if name == "start_audio":
            await self.sio.emit("status", {"msg": "AI Unavailable"}, room=sid)
        await super().emit_error(name, sid, payload)

    def safety_handler(self, name):
        async def handle(sid, data=None):
            try:
                self.sessions.require_owner(sid, {"renderer"}, allow_locked=True)
                EmptyRequest.model_validate({} if data is None else data)
                if name == "stop_audio":
                    # Stopping the shared voice session also cancels pending
                    # media approvals from sibling renderer channels.
                    tasks = tuple(t for t in self.media_requests if t is not asyncio.current_task())
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await self.service.stop_audio()
                    await self.service.stop_vision()
                elif self.service.audio:
                    self.service.audio.set_paused(True)
                await self.sio.emit(
                    "status",
                    {"msg": "INARA Stopped" if name == "stop_audio" else "Audio Paused"},
                    room=sid,
                )
            except (ServiceError, ValidationError) as exc:
                await self.emit_error(
                    name,
                    sid,
                    {
                        "msg": "Invalid or unauthorized media control.",
                        "code": getattr(exc, "code", "invalid_arguments"),
                    },
                )

        return handle


def approval_summary(payload):
    """Review metadata without duplicating private transcript/image bodies in UI."""
    args = payload["args"]
    if payload["tool"] in ("save_memory", "upload_memory", "video_frame"):
        import json

        raw = json.dumps(
            args, sort_keys=True, default=lambda v: hashlib.sha256(v).hexdigest()
        ).encode()
        summary = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if payload["tool"] == "save_memory":
            summary.update(filename=args.get("filename"), messages=len(args["messages"]))
        return {**payload, "args": summary}
    return payload
