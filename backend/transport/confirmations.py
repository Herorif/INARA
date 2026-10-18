"""Strict renderer confirmation route for the shared dispatcher."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError
from services.tools import ServiceError


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = Field(min_length=1, max_length=128)
    confirmed: StrictBool


class ConfirmationTransport:
    def __init__(self, sio, dispatcher, sessions):
        self.sio, self.dispatcher, self.sessions = sio, dispatcher, sessions
        sio.on("confirm_tool", handler=self.confirm_tool)

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

    async def confirm_tool(self, sid, data):
        payload = await self.validate_confirmation(sid, data)
        if payload is not None:
            principal = self.sessions.context(sid, renderer=True).principal
            self.dispatcher.resolve(principal, payload["id"], payload["confirmed"])
