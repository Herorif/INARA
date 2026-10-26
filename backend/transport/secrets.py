"""Owner-only API key routes. Values go in; only status (never a value) comes out."""

import asyncio
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError

from services.secrets import REGISTRY, check_message
from services.settings import EmptyRequest
from services.storage import StorageError
from services.tools import ServiceError

SecretName = Literal[tuple(REGISTRY)]


class SecretReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: SecretName


class SecretValue(SecretReference):
    # The value is validated by the registry; pydantic only bounds its size/type.
    value: StrictStr = Field(max_length=512)
    # Check with the provider before storing; a rejected key never replaces the saved one.
    verify: StrictBool = False


class SecretsTransport:
    events = ("secrets_status", "secrets_set", "secrets_test", "secrets_clear")

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    def handler(self, name):
        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                store = self.app.secrets
                if name == "secrets_status":
                    EmptyRequest.model_validate({} if data is None else data)
                    return {"ok": True, "secrets": store.statuses()}
                if name == "secrets_set":
                    request = SecretValue.model_validate(data)
                    if not request.verify:
                        return {"ok": True, "secret": store.set(request.name, request.value)}
                    value = store.validate(request.name, request.value)
                    check = await asyncio.to_thread(store.check_value, request.name, value)
                    if check["code"] == "invalid_key":
                        return {
                            "ok": False,
                            "code": "key_rejected",
                            "message": check_message(request.name, check["code"]),
                            "check": check,
                        }
                    secret = store.set(request.name, value, check=check)
                    return {"ok": True, "secret": secret, "check": check}
                request = SecretReference.model_validate(data)
                if name == "secrets_clear":
                    return {"ok": True, "secret": store.clear(request.name)}
                return {"ok": True, "secret": await asyncio.to_thread(store.test, request.name)}
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                # Never echo pydantic details: they can include the submitted value.
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid key request."}
            except (StorageError, sqlite3.Error):
                return {
                    "ok": False,
                    "code": "storage_error",
                    "message": "Protected storage could not be opened. Your keys were not changed.",
                }

        return handle
