"""Owner-only diagnostics export route (S4.2, docs/DIAGNOSTICS.md); never a model tool.

``diagnostics_export {}`` writes ``diagnostics-<timestamp>.zip`` (services/diagnostics.py)
and answers ``{ok: True, path}``, or ``{ok: False, code, message}``.
"""

from pydantic import ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)


class DiagnosticsTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("diagnostics_export", handler=self.export)

    async def export(self, sid, data=None):
        try:
            owner = self.app.sessions.require_owner(sid, {"renderer"})
            EmptyRequest.model_validate({} if data is None else data)
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
        return await self.app.diagnostics.export(owner)
