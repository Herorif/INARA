"""Strict reminder actions and delivery receipts for desktop owner channels."""

import asyncio
import uuid
from pydantic import ValidationError
from services.settings import EmptyRequest
from services.tools import ServiceError


class DeliveryReceipt(EmptyRequest):
    delivery_id: uuid.UUID


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
        self.running = {}
        for name in self.events:
            sio.on(name, handler=getattr(self, name))

    def owner(self, sid, receipt=False):
        roles = {"renderer", "resident"} if receipt else {"renderer"}
        return self.sessions.require_owner(
            sid, roles, allow_locked=receipt and self.sessions.roles.get(sid) == "resident"
        )

    def can_read(self, sid):
        try:
            self.sessions.require_owner(sid, {"renderer", "resident"})
            return True
        except ServiceError:
            return False

    async def error(self, sid, exc):
        await self.sio.emit(
            "error",
            {
                "msg": str(exc) if isinstance(exc, ServiceError) else "Invalid reminder request.",
                "code": getattr(exc, "code", "invalid_arguments"),
            },
            room=sid,
        )

    async def run_reminder_action(self, sid, name, data):
        task = asyncio.current_task()
        try:
            principal = self.owner(sid)
            self.running[task] = sid

            async def approve(payload):
                await self.sio.emit("tool_confirmation_request", payload, room=sid)

            result = await self.dispatcher.dispatch(
                principal, name, {} if data is None else data, {"principal": principal}, approve
            )
            await self.sio.emit("reminder_updated", result, room=sid)
            await self.refresh_reminders(sid)
        except (ServiceError, ValidationError) as exc:
            await self.error(sid, exc)
        finally:
            self.running.pop(task, None)

    async def create_reminder(self, sid, data):
        await self.run_reminder_action(sid, "create_reminder", data)

    async def snooze_reminder(self, sid, data):
        await self.run_reminder_action(sid, "snooze_reminder", data)

    async def cancel_reminder(self, sid, data):
        await self.run_reminder_action(sid, "cancel_reminder", data)

    async def refresh_reminders(self, sid):
        principal = self.sessions.principals[sid]
        for room in self.sessions.rooms(principal):
            if room != "native-resident" and self.sessions.roles.get(room) in (
                "renderer",
                "resident",
            ):
                await self.sio.emit(
                    "reminder_list", [r.to_dict() for r in self.store.list_reminders()], room=room
                )
                await self.sio.emit(
                    "reminder_deliveries", self.store.open_deliveries(principal), room=room
                )

    async def acknowledge_reminder(self, sid, data):
        try:
            principal = self.owner(sid, receipt=True)
            receipt = DeliveryReceipt.model_validate(data)
            if not self.store.acknowledge(str(receipt.delivery_id), principal):
                raise ServiceError(
                    "stale_delivery", "This reminder delivery is no longer available."
                )
        except (ServiceError, ValidationError) as exc:
            await self.error(sid, exc)

    async def dismiss_reminder(self, sid, data):
        try:
            principal = self.owner(sid)
            receipt = DeliveryReceipt.model_validate(data)
            if not self.store.acknowledge(str(receipt.delivery_id), principal, complete=True):
                raise ServiceError(
                    "stale_delivery", "This reminder delivery is no longer available."
                )
            await self.refresh_reminders(sid)
        except (ServiceError, ValidationError) as exc:
            await self.error(sid, exc)

    async def get_reminders(self, sid, data=None):
        try:
            self.owner(sid)
            EmptyRequest.model_validate({} if data is None else data)
            await self.refresh_reminders(sid)
        except (ServiceError, ValidationError) as exc:
            await self.error(sid, exc)

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.running.items())
            if (sid is None or origin == sid) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
