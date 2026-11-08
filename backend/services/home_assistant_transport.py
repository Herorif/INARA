"""Owner-only Home Assistant routes for the Connections card and the Home view
(docs/HOME_ASSISTANT.md).

``home_status``, ``home_connect`` {url, token}, ``home_disconnect``, ``home_devices``,
``home_set_access`` {entity_id, access} and ``home_control_direct`` {entity_id, action,
value?} (the owner's own tile controls: they act at once, without an approval card). Every
route needs the authenticated, unlocked desktop owner renderer. The token goes in through
home_connect and never comes back out.
"""

import sqlite3

from pydantic import ValidationError

from services.home_assistant import HomeAccessRequest, HomeConnect, HomeControl
from services.log import get_logger
from services.settings import EmptyRequest
from services.storage import StorageError
from services.tools import ServiceError

logger = get_logger(__name__)


class HomeAssistantTransport:
    events = (
        "home_status",
        "home_connect",
        "home_disconnect",
        "home_devices",
        "home_set_access",
        "home_control_direct",
    )

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    @property
    def home(self):
        return self.app.home

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                principal = self.app.sessions.require_owner(sid, {"renderer"})
                return await method(principal, {} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                # Never echo pydantic details: they can include the submitted token.
                return {
                    "ok": False,
                    "code": "invalid_arguments",
                    "message": "Invalid Home Assistant request.",
                }
            except (StorageError, sqlite3.Error):
                return {
                    "ok": False,
                    "code": "storage_error",
                    "message": "Protected storage could not be opened.",
                }
            except Exception as exc:
                logger.warning("Home Assistant request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "home_unavailable",
                    "message": "Home Assistant couldn't be reached from JARVIS. Try again.",
                }

        return handle

    async def _home_status(self, _principal, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "home": self.home.status()}

    async def _home_connect(self, _principal, data):
        request = HomeConnect.model_validate(data)
        return {"ok": True, "home": await self.home.connect(request.url, request.token)}

    async def _home_disconnect(self, _principal, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "home": await self.home.disconnect()}

    async def _home_devices(self, _principal, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, **await self.home.devices()}

    async def _home_set_access(self, _principal, data):
        request = HomeAccessRequest.model_validate(data)
        result = await self.home.set_access(request.entity_id, request.access)
        return {"ok": True, **result}

    async def _home_control_direct(self, _principal, data):
        request = HomeControl.model_validate(data)
        device = await self.home.control(
            request.entity_id, request.action, request.value, owner=True
        )
        return {"ok": True, "device": device}
