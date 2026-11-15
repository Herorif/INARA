"""Owner-only routes for "What JARVIS knows" (S6, docs/MEMORY.md).

- ``facts_list`` {kind?}: current facts (newest first) and the pause switch.
- ``facts_update`` {id, text?, subject?, kind?, pinned?}: edits one fact in place.
- ``facts_delete`` {id}: forgets one fact (hard delete).
- ``facts_pause`` {paused}: turns memory writes by the assistant and extraction off or on.
- ``facts_export``: every fact (current and superseded) as JSON text.

Every route needs the authenticated, unlocked desktop owner renderer. Answers are
``{ok: true, ...}`` or ``{ok: false, code, message}``. Fact text is never logged.
"""

import json

from pydantic import ValidationError

from services.log import get_logger
from services.memory_facts import (
    FactsDeleteRequest,
    FactsListRequest,
    FactsPauseRequest,
    FactsUpdateRequest,
)
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)


class FactsTransport:
    models = {
        "facts_list": FactsListRequest,
        "facts_update": FactsUpdateRequest,
        "facts_delete": FactsDeleteRequest,
        "facts_pause": FactsPauseRequest,
        "facts_export": EmptyRequest,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                request = model.model_validate({} if data is None else data)
                return method(self.app.facts.require(), request)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {
                    "ok": False,
                    "code": "invalid_arguments",
                    "message": "That memory change isn't valid.",
                }
            except Exception as exc:
                logger.warning("Memory request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "memory_unavailable",
                    "message": "Memory couldn't be read or saved. Try again.",
                }

        return handle

    @staticmethod
    def _facts_list(store, request):
        return {"ok": True, "paused": store.is_paused(), "facts": store.list(request.kind)}

    @staticmethod
    def _facts_update(store, request):
        fact = store.update(
            request.id, text=request.text, subject=request.subject, kind=request.kind,
            pinned=request.pinned, origin="owner",
        )
        return {"ok": True, "fact": fact}

    @staticmethod
    def _facts_delete(store, request):
        if not store.forget(request.id):
            raise ServiceError("memory_not_found", "That fact is already gone.")
        return {"ok": True, "deleted": request.id}

    @staticmethod
    def _facts_pause(store, request):
        return {"ok": True, "paused": store.set_paused(request.paused)}

    @staticmethod
    def _facts_export(store, request):
        text = store.export()
        return {"ok": True, "count": len(json.loads(text)["facts"]), "json": text}
