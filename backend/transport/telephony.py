"""Owner-only Calls routes: readiness (``calls_status``) and the Calls view (C3).

Every route needs the authenticated, unlocked desktop owner renderer. Phone numbers only
ever leave as masked display strings; secret values never leave at all.
"""

import sqlite3
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError, field_validator

from services.settings import EmptyRequest
from services.storage import StorageError
from services.tools import ServiceError
from telephony.briefs import clean_text


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallsList(StrictRequest):
    filter: Literal["needs_you", "all", "done", "spam"]  # spam: P1
    limit: StrictInt = Field(default=50, ge=1, le=100)


class CallReference(StrictRequest):
    id: StrictStr = Field(max_length=64)

    @field_validator("id")
    @classmethod
    def record_id(cls, value):
        return str(uuid.UUID(value))


class CallbackApproval(CallReference):
    message: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def text(cls, value):
        value = clean_text(value, 500)
        if not value:
            raise ValueError("The callback message is required.")
        return value


class CallsTransport:
    events = (
        "calls_status",
        "calls_list",
        "calls_get",
        "calls_mark_done",
        "calls_delete",
        "calls_callback_draft",
        "calls_callback_approve",
        "presence_ping",
    )

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                return await method({} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                # Never echo pydantic details: they can include the submitted values.
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid calls request."}
            except (StorageError, sqlite3.Error):
                return {
                    "ok": False,
                    "code": "storage_error",
                    "message": "Protected storage could not be opened.",
                }

        return handle

    @property
    def calls(self):
        return self.app.call_orchestrator

    async def _calls_status(self, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "calls": {**self.app.telephony.status(), **self.calls.status()}}

    async def _calls_list(self, data):
        request = CallsList.model_validate(data)
        return {"ok": True, "calls": self.calls.list_calls(request.filter, request.limit)}

    async def _calls_get(self, data):
        request = CallReference.model_validate(data)
        return {"ok": True, "call": self.calls.get_call(request.id)}

    async def _calls_mark_done(self, data):
        self.calls.mark_done(CallReference.model_validate(data).id)
        return {"ok": True}

    async def _calls_delete(self, data):
        self.calls.delete(CallReference.model_validate(data).id)
        return {"ok": True}

    async def _calls_callback_draft(self, data):
        request = CallReference.model_validate(data)
        return {"ok": True, "message": self.calls.draft(request.id)}

    async def _calls_callback_approve(self, data):
        request = CallbackApproval.model_validate(data)
        return await self.calls.approve_callback(request.id, request.message)

    async def _presence_ping(self, data):
        EmptyRequest.model_validate(data)
        self.calls.presence.ping()
        return {"ok": True}
