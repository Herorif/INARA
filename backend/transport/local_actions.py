"""Renderer-only deterministic local actions using the common tool dispatcher."""

import asyncio
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError
from services.local_actions import ACTION_MODELS
from services.tools import ServiceError


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = Field(min_length=1, max_length=128)
    confirmed: StrictBool


class LocalActionTransport:
    events = tuple(ACTION_MODELS)

    def __init__(self, sio, dispatcher, sessions):
        self.sio, self.dispatcher, self.sessions = sio, dispatcher, sessions
        self.running = {}
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            sio.on(name, handler=handler)

    async def validate_confirmation(self, sid, data):
        try:
            context = self.sessions.context(sid, renderer=True)
            if not self.dispatcher.authenticated(context.principal):
                raise ServiceError("authentication_required", "Authentication is required.")
            return Confirmation.model_validate(data).model_dump()
        except (ServiceError, ValidationError) as exc:
            await self.sio.emit(
                "error",
                {
                    "msg": "Invalid or unauthorized confirmation.",
                    "code": getattr(exc, "code", "invalid_arguments"),
                },
                room=sid,
            )
            return None

    def handler(self, name):
        async def handle(sid, data=None):
            task = asyncio.current_task()
            try:
                context = self.context(sid)
                if not self.dispatcher.authenticated(context.principal):
                    raise ServiceError("authentication_required", "Authentication is required.")
                self.running[task] = sid

                async def approve(payload):
                    await self.sio.emit("tool_confirmation_request", payload, room=sid)

                result = await self.dispatcher.dispatch(
                    context.principal, name, {} if data is None else data, context.tools(), approve
                )
                await self.emit_result(name, result, sid)
            except (ServiceError, ValidationError) as exc:
                await self.sio.emit(
                    "error",
                    {
                        "msg": str(exc)
                        if isinstance(exc, ServiceError)
                        else "Invalid local action arguments.",
                        "code": getattr(exc, "code", "invalid_arguments"),
                    },
                    room=sid,
                )
            except Exception:
                await self.sio.emit(
                    "error",
                    {"msg": "The local action could not complete.", "code": "action_failed"},
                    room=sid,
                )
            finally:
                self.running.pop(task, None)

        return handle

    def context(self, sid):
        return self.sessions.context(sid, renderer=True)

    async def emit_result(self, name, result, sid):
        if name == "launch_app":
            await self.sio.emit("status", {"msg": result["message"]}, room=sid)
        elif name == "take_screenshot":
            await self.sio.emit(
                "desktop_screenshot",
                {"description": result["message"], "data": result["data"]},
                room=sid,
            )
        elif name == "read_clipboard":
            await self.sio.emit("clipboard_content", {"text": result["message"]}, room=sid)
        elif name == "control_device":
            await self.sio.emit(
                "device_control", {"success": True, "message": result["message"]}, room=sid
            )
        elif name == "stop_watching":
            await self.sio.emit("vision_watches", {"watches": result["watches"]}, room=sid)
            await self.sio.emit("status", {"msg": result["message"]}, room=sid)
        # System/device list data keeps its existing agent event contract.

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.running.items())
            if (sid is None or origin == sid) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
