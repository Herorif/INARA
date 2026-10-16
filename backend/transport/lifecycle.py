"""Typed native/resource lifecycle controls; no model-callable admin tools."""

import asyncio
from typing import Annotated, Literal
from pydantic import Field, RootModel, StrictBool, ValidationError
from services.resources import ResourceRequest
from services.settings import EmptyRequest
from services.tools import ServiceError


class ControlAction(EmptyRequest):
    action: Literal["register", "state", "close", "quit"]


class GamingAction(EmptyRequest):
    action: Literal["gaming"]
    gaming: StrictBool


class DesktopControl(
    RootModel[Annotated[ControlAction | GamingAction, Field(discriminator="action")]]
):
    pass


class LifecycleTransport:
    events = ("set_resource_state", "desktop_control", "shutdown")

    def __init__(self, sio, sessions, resources, restrict, close_app, request_exit):
        self.sio, self.sessions, self.resources = sio, sessions, resources
        self.restrict, self.close_app, self.request_exit = restrict, close_app, request_exit
        self.lock = asyncio.Lock()
        self.fallback_gaming = False
        for name in self.events:
            sio.on(name, handler=getattr(self, name))

    async def error(self, sid, exc):
        code = getattr(exc, "code", "invalid_arguments")
        message = str(exc) if isinstance(exc, ServiceError) else "Invalid lifecycle request."
        await self.sio.emit("error", {"msg": message, "code": code}, room=sid)
        return {"ok": False, "code": code, "error": message}

    async def set_resource_state(self, sid, data):
        try:
            request = ResourceRequest.model_validate(data)
            async with self.lock:
                role = self.sessions.roles.get(sid)
                principal = self.sessions.require_owner(
                    sid, {"renderer", "resident"}, allow_locked=(role == "resident")
                )
                native = self.sessions.native_desktop
                if sid == "native-resident" and native is None:
                    raise ServiceError("permission_denied", "Native control is unavailable.")
                if native and role == "resident" and sid != "native-resident":
                    raise ServiceError(
                        "permission_denied", "Use the native host to control resident state."
                    )
                if not native and role == "resident":
                    self.fallback_gaming = request.state == "gaming"
                state = (
                    "gaming"
                    if (
                        (native and native.state.identity.gaming)
                        or (not native and role == "renderer" and self.fallback_gaming)
                    )
                    else request.state
                )
                self.resources.select(state)
                if state in ("resident", "gaming"):
                    await self.restrict()
                for room in self.sessions.rooms(principal):
                    if room != "native-resident":
                        await self.sio.emit("resource_state", self.resources.snapshot(), room=room)
                return {"ok": True}
        except (ServiceError, ValidationError) as exc:
            return await self.error(sid, exc)
        except Exception:
            return await self.error(
                sid,
                ServiceError(
                    "lifecycle_failed",
                    "Resource cleanup could not finish; restart INARA before heavy work.",
                ),
            )

    async def desktop_control(self, sid, data):
        try:
            request = DesktopControl.model_validate(data).model_dump()
            native = self.sessions.native_desktop
            if native is None:
                raise ServiceError("permission_denied", "Desktop control is unavailable.")
            principal = self.sessions.require_owner(
                sid,
                {"workspace"},
                allow_locked=True,
                allow_registration=request["action"] == "register",
            )
            state = await native.control(principal, request)
            if request["action"] == "close":
                for room in self.sessions.rooms(principal, "renderer"):
                    await self.sio.disconnect(room)
            return {"ok": True, "state": state}
        except (ServiceError, ValidationError) as exc:
            return await self.error(sid, exc)
        except (ValueError, TimeoutError):
            return await self.error(
                sid, ServiceError("desktop_rejected", "Desktop action rejected.")
            )
        except Exception:
            return await self.error(
                sid, ServiceError("desktop_failed", "Desktop control could not complete.")
            )

    async def shutdown(self, sid, data=None):
        try:
            EmptyRequest.model_validate({} if data is None else data)
            self.sessions.require_owner(sid, {"resident"}, allow_locked=True)
            if self.sessions.native_desktop is not None:
                raise ServiceError("permission_denied", "Use native desktop control to quit.")
            await self.close_app()
            self.request_exit()
            return {"ok": True}
        except (ServiceError, ValidationError) as exc:
            return await self.error(sid, exc)
        except Exception:
            return await self.error(
                sid,
                ServiceError("shutdown_failed", "Shutdown could not finish. Retry from the tray."),
            )
