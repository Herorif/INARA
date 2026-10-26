"""Owner-only telephony readiness (``calls_status``). Never returns secret values."""

import sqlite3

from pydantic import ValidationError

from services.settings import EmptyRequest
from services.storage import StorageError
from services.tools import ServiceError


class CallsTransport:
    events = ("calls_status",)

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = getattr(self, name)
            app.sio.on(name, handler=handler)

    async def calls_status(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            EmptyRequest.model_validate({} if data is None else data)
            return {"ok": True, "calls": self.app.telephony.status()}
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {"ok": False, "code": "invalid_arguments", "message": "Invalid calls request."}
        except (StorageError, sqlite3.Error):
            return {
                "ok": False,
                "code": "storage_error",
                "message": "Protected storage could not be opened.",
            }
