"""Owner-only routes for the proactive engine (S7.2, docs/PROACTIVE.md); never model tools.

All need the authenticated, unlocked desktop owner renderer, except ``proactive_focus``
(allowed while locked, like ``voice_stage``: a locked workspace reports itself unfocused).

- ``proactive_recent {}``: ``{ok, deliveries: [{id, at, channel, kind, source, person_id,
  title, body, urgency, score}]}``, newest first (at most 100, in memory).
- ``proactive_mute {kind, source, person_id?}``: ``{ok, mute: {id, kind, source, person_id,
  created_at}}``; signals with that kind, source and person are dropped silently from now on.
- ``proactive_unmute {id}``: ``{ok}``; ``not_found`` when the rule is gone.
- ``proactive_mutes {}``: ``{ok, mutes: [...]}``, oldest first.
- ``proactive_focus {focused}``: whether this renderer shows the workspace focused and visible.
- ``proactive_digest_dismiss {}``: clears the "While you were away" digest.

Titles and bodies are the owner's private data: nothing here logs them.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.signals import KINDS
from services.tools import ServiceError

logger = get_logger(__name__)

RENDERER = {"renderer"}
ID = r"^[0-9a-f]{32}$"
NAME = r"^[A-Za-z0-9._:-]{1,64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MuteRequest(Strict):
    kind: StrictStr = Field(max_length=40)
    source: StrictStr = Field(pattern=NAME)
    person_id: StrictStr | None = Field(default=None, pattern=NAME)


class UnmuteRequest(Strict):
    id: StrictStr = Field(pattern=ID)


class FocusRequest(Strict):
    focused: StrictBool


class ProactiveTransport:
    def __init__(self, app):
        self.app = app
        for name, method, schema, locked in (
            ("proactive_recent", self._recent, EmptyRequest, False),
            ("proactive_mute", self._mute, MuteRequest, False),
            ("proactive_unmute", self._unmute, UnmuteRequest, False),
            ("proactive_mutes", self._mutes, EmptyRequest, False),
            ("proactive_focus", self._focus, FocusRequest, True),
            ("proactive_digest_dismiss", self._dismiss, EmptyRequest, False),
        ):
            app.sio.on(name, handler=self.route(name, method, schema, locked))

    def route(self, name, method, schema, allow_locked):
        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, RENDERER, allow_locked=allow_locked)
                request = schema.model_validate({} if data is None else data)
                return await method(sid, request)
            except asyncio.CancelledError:
                raise
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid request."}
            except Exception as exc:
                logger.warning("Proactive request %s failed (%s)", name, type(exc).__name__)
                return {"ok": False, "code": "proactive_unavailable",
                        "message": "That couldn't be done just now. Try again."}

        return handle

    @property
    def engine(self):
        return self.app.proactive

    async def _recent(self, _sid, _request):
        return {"ok": True, "deliveries": self.engine.recent()}

    async def _mute(self, _sid, request):
        if request.kind not in KINDS:
            raise ServiceError("invalid_arguments", "Unknown signal kind.")
        rule = self.engine.mute(request.kind, request.source, request.person_id)
        return {"ok": True, "mute": dict(rule)}

    async def _unmute(self, _sid, request):
        self.engine.unmute(request.id)
        return {"ok": True}

    async def _mutes(self, _sid, _request):
        return {"ok": True, "mutes": self.engine.mutes()}

    async def _focus(self, sid, request):
        self.engine.set_focus(sid, request.focused)
        return {"ok": True}

    async def _dismiss(self, _sid, _request):
        await self.engine.dismiss_digest()
        return {"ok": True}
