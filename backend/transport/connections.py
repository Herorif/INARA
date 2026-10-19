"""Owner-only metadata inspection, without network or optional adapter initialization."""

from pydantic import ValidationError
from services.settings import EmptyRequest
from services.tools import ServiceError


class ConnectionsTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("connections_state", handler=self.state)

    async def state(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            EmptyRequest.model_validate(data)
            return {"ok": True, **self.app.connections.snapshot()}
        except (ServiceError, ValidationError) as exc:
            return {
                "ok": False,
                "code": getattr(exc, "code", "invalid_arguments"),
                "message": "Use the authenticated owner workspace to inspect connection readiness.",
            }
        except Exception:
            return {
                "ok": False,
                "code": "connections_unavailable",
                "message": "Local readiness could not be inspected. No network discovery was started.",
            }
