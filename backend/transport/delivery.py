"""Socket delivery ownership; legacy unscoped bus events remain mapped for R2b."""

import asyncio
from core.event_bus import Events


LEGACY_EVENTS = {
    Events.REMINDER_TRIGGERED: "reminder_triggered",
    Events.REMINDER_CREATED: "reminder_created",
    Events.REMINDER_CANCELLED: "reminder_cancelled",
    Events.DESKTOP_SCREENSHOT: "desktop_screenshot",
    Events.DESKTOP_SYSTEM_INFO: "desktop_system_info",
    Events.VISION_ALERT: "vision_alert",
    Events.VISION_DESCRIPTION: "vision_description",
    Events.VISION_PRESENCE: "vision_presence",
    Events.DEVICE_LIST: "device_list",
    Events.DEVICE_CONTROL: "device_control",
    Events.DEVICE_STATE: "device_state",
}


class EventDelivery:
    def __init__(self, sio, sessions, reminders, dispatcher, resources):
        self.sio, self.sessions, self.reminders = sio, sessions, reminders
        self.dispatcher, self.resources = dispatcher, resources

    async def publish_job(self, event, principal, job):
        for sid in self.sessions.rooms(principal, "renderer"):
            await self.sio.emit(event, job, room=sid)

    async def bridge_legacy(self, event):
        name = LEGACY_EVENTS.get(event.type)
        if name:
            if event.principal is not None:
                if self.dispatcher.authenticated(event.principal):
                    for sid in self.sessions.rooms(event.principal, "renderer"):
                        await self.sio.emit(name, event.data, room=sid)
            else:
                # Unmigrated legacy producers remain explicitly inventoried in R2b.
                await self.sio.emit(name, event.data)

    async def deliver_reminders_once(self):
        for principal in dict.fromkeys(self.sessions.principals.values()):
            rooms = sorted(
                [
                    sid
                    for sid in self.sessions.rooms(principal)
                    if self.sessions.roles.get(sid) != "workspace"
                ],
                key=lambda sid: (
                    (self.sessions.roles.get(sid) != "resident")
                    if self.resources.state == "resident"
                    else (self.sessions.roles.get(sid) == "resident")
                ),
            )
            if (
                not rooms
                or not self.sessions.is_owner(principal)
                or not self.dispatcher.authenticated(principal)
            ):
                continue
            for delivery in self.reminders.claim_deliveries(principal):
                native = self.sessions.native_desktop
                if rooms[0] == "native-resident" and native:
                    if await native.notify(delivery):
                        self.reminders.acknowledge(delivery["delivery_id"], principal)
                else:
                    await self.sio.emit("reminder_triggered", delivery, room=rooms[0])

    async def poll_reminders(self):
        while True:
            try:
                await self.deliver_reminders_once()
            except Exception:
                print("[SERVER] Reminder delivery failed; retained for retry.")
            await asyncio.sleep(10)
