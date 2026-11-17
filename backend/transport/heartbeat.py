"""Owner-only routes for the heartbeat (S7.3, docs/PROACTIVE.md "Heartbeat"); never model tools.

Both need the authenticated, unlocked desktop owner renderer.

- ``heartbeat_get {}``: ``{ok, text, last_run, last_actions}``; ``text`` is HEARTBEAT.md (created
  with the default on first read), ``last_run`` ISO 8601 or null, ``last_actions``
  ``[{action, signal, kind, outcome, note?}]`` from the last model call.
- ``heartbeat_save {text}``: ``{ok, text}``; plain text, at most 4,000 characters (empty means
  the defaults are used).

The standing instructions are the owner's private text: nothing here logs them.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from services.heartbeat import TEXT_MAX
from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)

RENDERER = {"renderer"}


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # \r\n counts twice here; the service checks the saved length exactly.
    text: StrictStr = Field(max_length=TEXT_MAX * 2)


class HeartbeatTransport:
    def __init__(self, app):
        self.app = app
        for name, method, schema in (
            ("heartbeat_get", self._get, EmptyRequest),
            ("heartbeat_save", self._save, SaveRequest),
        ):
            app.sio.on(name, handler=self.route(name, method, schema))

    def route(self, name, method, schema):
        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, RENDERER)
                request = schema.model_validate({} if data is None else data)
                return await method(request)
            except asyncio.CancelledError:
                raise
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
            except Exception as exc:
                logger.warning("Heartbeat request %s failed (%s)", name, type(exc).__name__)
                return {"ok": False, "code": "heartbeat_unavailable",
                        "message": "That couldn't be done just now. Try again."}

        return handle

    async def _get(self, _request):
        return {"ok": True, **await asyncio.to_thread(self.app.heartbeat.status)}

    async def _save(self, request):
        text = await asyncio.to_thread(self.app.heartbeat.save_text, request.text)
        return {"ok": True, "text": text}
