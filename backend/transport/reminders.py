"""Reminder actions and receipts preserve the shared dispatcher contract."""

from pydantic import ValidationError
from services.tools import ServiceError


class ReminderTransport:
    events = (
        "create_reminder",
        "snooze_reminder",
        "cancel_reminder",
        "acknowledge_reminder",
        "dismiss_reminder",
        "get_reminders",
    )

    def __init__(self, sio, dispatcher, store, sessions):
        self.sio, self.dispatcher, self.store, self.sessions = sio, dispatcher, store, sessions
        for name in self.events:
            sio.on(name, handler=getattr(self, name))

    async def run_reminder_action(self, sid, name, data):
        if not await self.reminder_action_allowed(sid):
            return

        async def approve(payload):
            await self.sio.emit("tool_confirmation_request", payload, room=sid)

        try:
            result = await self.dispatcher.dispatch(
                self.sessions.principals[sid],
                name,
                data or {},
                {"principal": self.sessions.principals[sid]},
                approve,
            )
            await self.sio.emit("reminder_updated", result, room=sid)
            await self.refresh_reminders(sid)
        except (ServiceError, ValidationError) as exc:
            await self.sio.emit(
                "error",
                {
                    "msg": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Invalid reminder arguments.",
                    "code": getattr(exc, "code", "invalid_arguments"),
                },
                room=sid,
            )

    async def create_reminder(self, sid, data):
        await self.run_reminder_action(sid, "create_reminder", data)

    async def snooze_reminder(self, sid, data):
        await self.run_reminder_action(sid, "snooze_reminder", data)

    async def cancel_reminder(self, sid, data):
        await self.run_reminder_action(sid, "cancel_reminder", data)

    async def reminder_action_allowed(self, sid):
        principal = self.sessions.principals.get(sid)
        if principal is None or not self.dispatcher.authenticated(principal):
            await self.sio.emit("error", {"msg": "Authentication is required."}, room=sid)
            return False
        return True

    async def refresh_reminders(self, sid):
        principal = self.sessions.principals[sid]
        for room, owner in tuple(self.sessions.principals.items()):
            if owner == principal:
                await self.sio.emit(
                    "reminder_list", [r.to_dict() for r in self.store.list_reminders()], room=room
                )
                await self.sio.emit(
                    "reminder_deliveries", self.store.open_deliveries(owner), room=room
                )

    async def acknowledge_reminder(self, sid, data):
        if await self.reminder_action_allowed(sid) and isinstance(data, dict):
            self.store.acknowledge(str(data.get("delivery_id", "")), self.sessions.principals[sid])

    async def dismiss_reminder(self, sid, data):
        if await self.reminder_action_allowed(sid) and isinstance(data, dict):
            if not self.store.acknowledge(
                str(data.get("delivery_id", "")), self.sessions.principals[sid], complete=True
            ):
                await self.sio.emit(
                    "error", {"msg": "This reminder alert is no longer actionable."}, room=sid
                )
            await self.refresh_reminders(sid)

    async def get_reminders(self, sid):
        if await self.reminder_action_allowed(sid):
            await self.refresh_reminders(sid)
