"""Owner-only debug route for signals (S7.1, docs/SIGNALS.md); never a model tool.

``signals_pending {}``: the hub's live, unacknowledged signals, newest first, as
``{ok: true, signals: [{title, kind, urgency, at}]}`` (``at`` is ISO 8601). Needs the
authenticated, unlocked desktop owner renderer. Titles are the owner's private data:
nothing here logs them.
"""

from pydantic import ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)


class SignalsTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("signals_pending", handler=self._signals_pending)

    async def _signals_pending(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            EmptyRequest.model_validate({} if data is None else data)
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
        items = self.app.signals.pending()
        return {
            "ok": True,
            "signals": [
                {"title": item.title, "kind": item.kind, "urgency": item.urgency,
                 "at": item.at.isoformat()}
                for item in reversed(items)
            ],
        }
