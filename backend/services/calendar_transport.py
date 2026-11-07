"""Owner-only Google Calendar routes for the Connections card (docs/CALENDAR.md).

``calendar_status``, ``calendar_connect`` (returns the Google sign-in URL, which the
renderer opens in the system browser through the https-only ``electronAPI.openExternal``),
``calendar_cancel`` (stops a pending sign-in), ``calendar_disconnect`` and
``calendar_settings``. Every route needs the authenticated, unlocked desktop owner
renderer. Tokens, codes and the client secret never leave the core.
"""

import sqlite3

from pydantic import ValidationError

from services.calendar_oauth import AUTH_URL
from services.log import get_logger
from services.settings import CalendarSettings, EmptyRequest, SettingsPatch
from services.storage import StorageError
from services.tools import ServiceError

logger = get_logger(__name__)


class CalendarTransport:
    events = (
        "calendar_status",
        "calendar_connect",
        "calendar_cancel",
        "calendar_disconnect",
        "calendar_settings",
    )

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    @property
    def calendar(self):
        return self.app.calendar

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                principal = self.app.sessions.require_owner(sid, {"renderer"})
                return await method(principal, {} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                # Never echo pydantic details: they can include the submitted values.
                return {
                    "ok": False, "code": "invalid_arguments", "message": "Invalid calendar request."
                }
            except (StorageError, sqlite3.Error):
                return {
                    "ok": False,
                    "code": "storage_error",
                    "message": "Protected storage could not be opened.",
                }
            except Exception as exc:
                logger.warning("Calendar request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "calendar_unavailable",
                    "message": "Google Calendar couldn't be reached from JARVIS. Try again.",
                }

        return handle

    async def _calendar_status(self, _principal, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "calendar": self.calendar.status()}

    async def _calendar_connect(self, _principal, data):
        EmptyRequest.model_validate(data)
        url = await self.calendar.connect()
        if not url.startswith(AUTH_URL + "?"):
            raise ServiceError("calendar_unavailable", "The sign-in link could not be made.")
        return {"ok": True, "auth_url": url, "calendar": self.calendar.status()}

    async def _calendar_cancel(self, _principal, data):
        EmptyRequest.model_validate(data)
        await self.calendar.cancel()
        return {"ok": True, "calendar": self.calendar.status()}

    async def _calendar_disconnect(self, _principal, data):
        EmptyRequest.model_validate(data)
        revoked = await self.calendar.disconnect()
        return {"ok": True, "revoked": revoked, "calendar": self.calendar.status()}

    async def _calendar_settings(self, principal, data):
        request = SettingsPatch(calendar=CalendarSettings.model_validate(data))
        snapshot = self.app.settings_service.apply(request)
        # settings_changed publishes calendar_status (application.settings_changed).
        await self.app.settings_changed(request.model_dump(exclude_unset=True))
        for room in self.app.sessions.rooms(principal, "renderer"):
            await self.app.sio.emit("settings", snapshot, room=room)
        return {"ok": True, "calendar": self.calendar.status()}
