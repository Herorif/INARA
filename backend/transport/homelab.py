"""Owner-only homelab routes (S12.3, docs/HOMELAB.md); never model tools.

Every route needs the authenticated, unlocked desktop owner renderer.

- ``homelab_status {}``: ``{ok, hosts, paused}``; each host ``{id, name, adapter, state,
  checked_at, address, interval_s, actions, can_wake, entities, trusted?}``.
- ``homelab_hosts_get {}``: ``{ok, hosts}``, the validated ``homelab.hosts``.
- ``homelab_hosts_save {hosts}``: validates every entry (``HostConfig``), saves the list whole
  and returns ``{ok, hosts}``. A problem comes back as ``invalid_arguments`` with the field and
  a plain message, never the submitted value.
- ``homelab_probe_now {host}``: probes one system now (even in gaming mode, because the owner
  asked) and returns ``{ok, host, entities}``.
"""

import asyncio

from pydantic import ValidationError

from services.homelab.base import HomelabHosts, Strict
from services.homelab.registry import host_configs
from services.homelab.tools import HostId
from services.log import get_logger
from services.settings import EmptyRequest, SettingsPatch
from services.tools import ServiceError

logger = get_logger(__name__)

RENDERER = {"renderer"}


class ProbeRequest(Strict):
    host: HostId


def _problem(error):
    """'hosts.0.options: Use the full address…' without the submitted value."""
    location = ".".join(str(part) for part in error.get("loc", ()) if part != "__root__")
    message = str(error.get("msg", "Invalid value.")).removeprefix("Value error, ")
    text = f"{location}: {message}" if location else message
    return text[:300]


class HomelabTransport:
    def __init__(self, app):
        self.app = app
        for name, method, schema in (
            ("homelab_status", self._status, EmptyRequest),
            ("homelab_hosts_get", self._hosts_get, EmptyRequest),
            ("homelab_hosts_save", self._hosts_save, HomelabHosts),
            ("homelab_probe_now", self._probe_now, ProbeRequest),
        ):
            handler = self.route(name, method, schema)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

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
            except ValidationError as exc:
                errors = exc.errors(include_input=False, include_url=False)
                message = _problem(errors[0]) if errors else "Invalid request."
                return {"ok": False, "code": "invalid_arguments", "message": message}
            except Exception as exc:
                logger.warning("Homelab request %s failed (%s)", name, type(exc).__name__)
                return {"ok": False, "code": "homelab_unavailable",
                        "message": "That couldn't be done just now. Try again."}

        return handle

    @property
    def registry(self):
        return self.app.homelab

    async def _status(self, _request):
        return {"ok": True, **self.registry.status_for_owner()}

    async def _hosts_get(self, _request):
        hosts = host_configs(self.app.settings).values()
        return {"ok": True, "hosts": [host.model_dump() for host in hosts]}

    async def _hosts_save(self, request):
        patch = SettingsPatch(homelab=HomelabHosts(
            hosts=[host.model_dump() for host in request.hosts]))
        self.app.settings_service.apply(patch)
        self.registry.hosts()  # pick the new list up now (drops removed systems' alerts)
        return {"ok": True, "hosts": [host.model_dump() for host in request.hosts]}

    async def _probe_now(self, request):
        entities = await self.registry.probe_now(request.host)
        return {"ok": True, "host": request.host,
                "entities": [entity.as_dict() for entity in entities]}
