"""Owner-only settings transport. Tool permissions cannot alter its authority."""

from pydantic import ValidationError
from services.settings import EmptyRequest, SettingsPatch, PermissionPatch
from services.tools import ServiceError


class SettingsTransport:
    events = ("get_settings", "update_settings", "get_tool_permissions", "update_tool_permissions")

    def __init__(self, sio, sessions, service, after_change=None, before_change=None):
        self.sio, self.sessions, self.service = sio, sessions, service
        self.after_change = after_change
        self.before_change = before_change
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            sio.on(name, handler=handler)

    def handler(self, name):
        async def handle(sid, data=None):
            try:
                principal = self.sessions.require_owner(sid, {"renderer"})
                if name in ("get_settings", "get_tool_permissions"):
                    EmptyRequest.model_validate({} if data is None else data)
                    snapshot = self.service.snapshot()
                else:
                    request = (
                        SettingsPatch.model_validate(data)
                        if name == "update_settings"
                        else SettingsPatch(
                            tool_permissions=PermissionPatch.model_validate({"values": data}).values
                        )
                    )
                    if self.before_change:
                        self.before_change(request.model_dump(exclude_unset=True))
                    snapshot = self.service.apply(request)
                    if self.after_change:
                        await self.after_change(request.model_dump(exclude_unset=True))
                event = "tool_permissions" if name.endswith("tool_permissions") else "settings"
                payload = snapshot["tool_permissions"] if event == "tool_permissions" else snapshot
                rooms = (
                    (sid,)
                    if name.startswith("get_")
                    else self.sessions.rooms(principal, "renderer")
                )
                for room in rooms:
                    await self.sio.emit(event, payload, room=room)
                    if (
                        name == "update_settings"
                        and "face_auth_enabled" in request.model_fields_set
                    ):
                        await self.sio.emit(
                            "auth_status",
                            {"authenticated": self.sessions.authenticated(principal)},
                            room=room,
                        )
                return {"ok": True}
            except (ServiceError, ValidationError) as exc:
                code = getattr(exc, "code", "invalid_arguments")
                await self.sio.emit(
                    "error",
                    {
                        "msg": str(exc)
                        if isinstance(exc, ServiceError)
                        else "Invalid settings request.",
                        "code": code,
                    },
                    room=sid,
                )
                return {"ok": False, "code": code}

        return handle
