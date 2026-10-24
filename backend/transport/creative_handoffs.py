"""Owner-only, read-only creative handoff route. No provider or worker dispatch."""

from pydantic import ValidationError
from services.handoff_contracts import HandoffRequest
from services.tools import ServiceError


class HandoffTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("creative_handoff", handler=self.prepare)

    async def prepare(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            args = HandoffRequest.model_validate(data)
            return {"ok": True, "draft": self.app.handoffs.prepare(sid, args)}
        except (ServiceError, ValidationError) as exc:
            return {
                "ok": False,
                "code": getattr(exc, "code", "invalid_arguments"),
                "message": str(exc)
                if isinstance(exc, ServiceError)
                else "Select a saved source and destination studio.",
            }
        except Exception:
            return {
                "ok": False,
                "code": "handoff_unavailable",
                "message": "The saved reference could not be read. Refresh project history.",
            }
