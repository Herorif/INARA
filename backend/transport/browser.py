"""Renderer-only ACK transport; approval and cancellation belong to the origin."""

import asyncio
from pydantic import ValidationError
from services.settings import EmptyRequest
from services.tools import ServiceError


class BrowserTransport:
    def __init__(self, app):
        self.app, self.running = app, {}
        for name in ("browser_inspect", "browser_cancel"):
            app.sio.on(name, handler=self.handler(name))

    def handler(self, name):
        async def handle(sid, data=None):
            task = asyncio.current_task()
            try:
                owner = self.app.sessions.require_owner(
                    sid, {"renderer"}, allow_locked=name == "browser_cancel"
                )
                if name == "browser_cancel":
                    EmptyRequest.model_validate(data)
                    await self.stop_sid(sid)
                    return {"ok": True}
                self.running[task] = sid
                context = self.app.sessions.context(sid)

                async def approve(payload):
                    await self.app.sio.emit("tool_confirmation_request", payload, room=sid)

                result = await self.app.dispatcher.dispatch(
                    owner, name, data, {**context.tools(), "origin_sid": sid}, approve
                )
                return {"ok": True, **result}
            except asyncio.CancelledError:
                return {
                    "ok": False,
                    "code": "browser_cancelled",
                    "message": "Inspection stopped. No task will be replayed.",
                }
            except (ServiceError, ValidationError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "invalid_arguments"),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Use one public HTTPS URL.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "browser_failed",
                    "message": "Inspection could not complete.",
                }
            finally:
                self.running.pop(task, None)

        return handle

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.running.items())
            if task is not asyncio.current_task() and (sid is None or sid == origin)
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.app.browser.stop_sid(sid)
