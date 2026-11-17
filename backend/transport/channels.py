"""Owner-only routes for remote channels (S8.1, docs/CHANNELS.md); never model tools.

Both need the authenticated, unlocked desktop owner renderer.

- ``channels_status {}``: ``{ok, channels: [{name, paired, state}]}`` in registration order.
- ``channel_messages_list {limit?}``: ``{ok, messages: [{id, channel, sender, sender_name,
  person_id, person_name, text, media, at, received_at}]}``, newest first; ``limit`` 1-200
  (default 50). Chat ids are never listed.

Message text and senders are the owner's private data: nothing here logs them.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)

RENDERER = {"renderer"}


class MessagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: StrictInt = Field(default=50, ge=1, le=200)


class ChannelsTransport:
    def __init__(self, app):
        self.app = app
        for name, method, schema in (
            ("channels_status", self._status, EmptyRequest),
            ("channel_messages_list", self._messages, MessagesRequest),
        ):
            app.sio.on(name, handler=self.route(name, method, schema))

    def route(self, name, method, schema):
        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, RENDERER)
                request = schema.model_validate({} if data is None else data)
                return method(request)
            except asyncio.CancelledError:
                raise
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
            except Exception as exc:
                logger.warning("Channels request %s failed (%s)", name, type(exc).__name__)
                return {"ok": False, "code": "channels_unavailable",
                        "message": "That couldn't be done just now. Try again."}

        return handle

    def _status(self, _request):
        return {"ok": True, "channels": self.app.channels.status()}

    def _messages(self, request):
        return {"ok": True, "messages": self.app.channels.store.list(request.limit)}
