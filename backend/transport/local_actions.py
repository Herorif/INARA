"""Renderer-only deterministic local actions using the common tool dispatcher."""

import asyncio
from pydantic import ValidationError
from services.local_actions import ACTION_MODELS
from services.tools import ServiceError


class LocalActionTransport:
    events = tuple(ACTION_MODELS)

    def __init__(self, sio, dispatcher, sessions):
        self.sio, self.dispatcher, self.sessions = sio, dispatcher, sessions
        self.running = {}
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            sio.on(name, handler=handler)


    def handler(self, name):
        async def handle(sid, data=None):
            task = asyncio.current_task()
            try:
                context = self.context(sid)
                if not self.dispatcher.authenticated(context.principal):
                    raise ServiceError("authentication_required", "Authentication is required.")
                self.running[task] = sid

                async def approve(payload):
                    await self.sio.emit("tool_confirmation_request", self.approval_payload(payload), room=sid)

                result = await self.dispatcher.dispatch(
                    context.principal, name, {} if data is None else data,
                    self.tool_context(sid, context), approve
                )
                await self.emit_result(name, result, sid)
            except (ServiceError, ValidationError) as exc:
                await self.emit_error(
                    name,
                    sid,
                    {
                        "msg": str(exc)
                        if isinstance(exc, ServiceError)
                        else "Invalid local action arguments.",
                        "code": getattr(exc, "code", "invalid_arguments"),
                    },
                )
            except Exception:
                await self.emit_error(
                    name,
                    sid,
                    {"msg": "The local action could not complete.", "code": "action_failed"},
                )
            finally:
                self.running.pop(task, None)

        return handle

    async def emit_error(self, name, sid, payload):
        await self.sio.emit("error", payload, room=sid)

    def context(self, sid):
        return self.sessions.context(sid, renderer=True)

    def tool_context(self, sid, context):
        return context.tools()

    def approval_payload(self, payload):
        return payload

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
