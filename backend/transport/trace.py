"""Owner-only flight recorder routes (S4.1, docs/DIAGNOSTICS.md); never model tools.

``trace_recent {limit?}`` answers ``{ok: True, traces}``: up to ``limit`` (1-200, default 50)
of the owner's turn traces, newest first (services/trace.py has the shape).
``trace_clear {}`` empties the recorder and answers ``{ok: True}``.
"""

from pydantic import Field, StrictInt, ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError
from services.trace import TRACE_LIMIT

logger = get_logger(__name__)


class TraceRecent(EmptyRequest):
    limit: StrictInt = Field(default=50, ge=1, le=TRACE_LIMIT)


class TraceTransport:
    models = {"trace_recent": TraceRecent, "trace_clear": EmptyRequest}

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def handle(sid, data=None):
            try:
                owner = self.app.sessions.require_owner(sid, {"renderer"})
                args = model.model_validate({} if data is None else data)
                if name == "trace_clear":
                    self.app.trace.clear(owner)
                    return {"ok": True}
                return {"ok": True, "traces": self.app.trace.recent(args.limit, owner=owner)}
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
            except Exception as exc:
                logger.warning("Trace request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "trace_unavailable",
                    "message": "The activity list couldn't be loaded. Try again.",
                }

        return handle
