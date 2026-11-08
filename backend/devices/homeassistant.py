"""
Home Assistant REST API bridge (docs/HOME_ASSISTANT.md).

A thin async client on httpx for one Home Assistant server: ``ping`` (``GET /api/``),
``states``, ``state``, ``areas`` (rendered through ``POST /api/template``), ``config``,
``call_service`` and ``list_devices``. Each call is one bounded request (10 s) with
redirects off; https verifies against the OS certificate store through
``services.tls.provider_ssl_context()`` (antivirus HTTPS scanning still verifies).

The address comes from the ``home_assistant.url`` setting and the long-lived access token
from the encrypted secret ``home_assistant_token`` (services/home_assistant.py); the bridge
never reads settings.json itself. The token and exception text (which can carry the
address) are never logged.
"""

import json
import ssl

from services.log import get_logger

logger = get_logger(__name__)

TIMEOUT = 10.0
BODY_LIMIT = 8 * 1024 * 1024
API_RUNNING = "API running."

# The device domains JARVIS shows and controls, in display order.
INCLUDED_DOMAINS = (
    "light",
    "switch",
    "input_boolean",
    "fan",
    "cover",
    "climate",
    "media_player",
    "lock",
    "alarm_control_panel",
    "scene",
    "script",
)

# Rooms are Home Assistant areas. The template reads the area registry order and each
# included entity's area name; no caller data is placed in it.
AREAS_TEMPLATE = (
    "{% set ns = namespace(rows=[]) %}"
    "{% for s in states if s.domain in " + json.dumps(list(INCLUDED_DOMAINS)) + " %}"
    "{% set ns.rows = ns.rows + [[s.entity_id, area_name(s.entity_id)]] %}"
    "{% endfor %}"
    '{{ {"areas": areas() | map("area_name") | list, "entities": ns.rows} | to_json }}'
)


class HomeAssistantError(Exception):
    """A failed request. ``code``: invalid_token, unreachable, timeout, tls,
    not_home_assistant, not_found, refused or unexpected."""

    def __init__(self, code, status=None):
        super().__init__(code)
        self.code = code
        self.status = status


def classify_exception(exc):
    """invalid_token / timeout / tls / unreachable / unexpected for a transport failure."""
    import httpx

    seen, current = set(), exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(current):
            return "tls"
        current = current.__cause__ or current.__context__
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, (httpx.TransportError, OSError)):
        return "unreachable"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "unexpected"


class HomeAssistantBridge:
    """Async REST client for one Home Assistant server.

    ``transport`` is an httpx transport for tests (httpx.MockTransport)."""

    def __init__(self, url: str, token: str, *, transport=None, timeout: float = TIMEOUT):
        self._base = url.rstrip("/")
        self._token = token
        self._transport = transport
        self._timeout = timeout

    def __repr__(self):  # never shows the token
        return "HomeAssistantBridge()"

    @property
    def secure(self):
        return self._base.lower().startswith("https://")

    async def close(self):
        """Nothing to release: each request uses its own short-lived client."""

    # ------------------------------------------------------------------
    # Core REST helper
    # ------------------------------------------------------------------

    async def _request(self, method, path, *, json_body=None):
        import httpx

        options = {"timeout": self._timeout, "follow_redirects": False}
        if self._transport is not None:
            options["transport"] = self._transport
        elif self.secure:
            from services.tls import provider_ssl_context

            options["verify"] = provider_ssl_context()
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(
                    method, f"{self._base}/api{path}", json=json_body, headers=headers
                )
        except Exception as exc:  # the text can carry the address: only the class is logged
            code = classify_exception(exc)
            logger.warning("Home Assistant request failed (%s, %s)", code, type(exc).__name__)
            raise HomeAssistantError(code) from None
        if response.status_code in (401, 403):
            raise HomeAssistantError("invalid_token", response.status_code)
        if len(response.content) > BODY_LIMIT:
            raise HomeAssistantError("unexpected", response.status_code)
        return response

    async def _json(self, method, path, *, json_body=None):
        response = await self._request(method, path, json_body=json_body)
        if response.status_code == 404:
            raise HomeAssistantError("not_found", 404)
        if response.status_code == 400:
            raise HomeAssistantError("refused", 400)
        if not 200 <= response.status_code < 300:
            raise HomeAssistantError("unexpected", response.status_code)
        try:
            return response.json() if response.content else None
        except ValueError:
            raise HomeAssistantError("unexpected", response.status_code) from None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """``GET /api/`` must answer {"message": "API running."}; raises otherwise."""
        try:
            body = await self._json("GET", "/")
        except HomeAssistantError as exc:
            if exc.code in ("not_found", "refused", "unexpected"):
                raise HomeAssistantError("not_home_assistant", exc.status) from None
            raise
        if not isinstance(body, dict) or body.get("message") != API_RUNNING:
            raise HomeAssistantError("not_home_assistant")
        return True

    async def states(self) -> list[dict]:
        """Every entity state (``GET /api/states``); malformed rows are dropped."""
        body = await self._json("GET", "/states")
        if not isinstance(body, list):
            raise HomeAssistantError("unexpected")
        return [row for row in body if isinstance(row, dict) and isinstance(row.get("entity_id"), str)]

    async def get_states(self, domain=None) -> list[dict]:
        states = await self.states()
        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return states

    async def state(self, entity_id: str) -> dict:
        """One entity (``GET /api/states/<entity_id>``); not_found when it doesn't exist.
        Callers pass a validated entity_id."""
        body = await self._json("GET", f"/states/{entity_id}")
        if not isinstance(body, dict) or body.get("entity_id") != entity_id:
            raise HomeAssistantError("unexpected")
        return body

    get_state = state

    async def config(self) -> dict:
        body = await self._json("GET", "/config")
        return body if isinstance(body, dict) else {}

    async def areas(self):
        """(area names in registry order, {entity_id: area name or None}) for the included
        entities, rendered through ``POST /api/template``. Raises HomeAssistantError when
        the template can't be rendered (callers then group by domain)."""
        response = await self._request("POST", "/template", json_body={"template": AREAS_TEMPLATE})
        if not 200 <= response.status_code < 300:
            raise HomeAssistantError("unexpected", response.status_code)
        try:
            body = json.loads(response.text)
        except ValueError:
            raise HomeAssistantError("unexpected") from None
        if isinstance(body, str):  # a server that JSON-encodes the rendered string
            try:
                body = json.loads(body)
            except ValueError:
                raise HomeAssistantError("unexpected") from None
        if not isinstance(body, dict):
            raise HomeAssistantError("unexpected")
        order = [name for name in body.get("areas") or [] if isinstance(name, str) and name]
        rows = body.get("entities")
        pairs = rows.items() if isinstance(rows, dict) else rows if isinstance(rows, list) else None
        if pairs is None:
            raise HomeAssistantError("unexpected")
        mapping = {}
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str):
                area = pair[1] if isinstance(pair[1], str) and pair[1] else None
                mapping[pair[0]] = area
        return order, mapping

    async def call_service(self, domain: str, service: str, data: dict | None = None):
        """``POST /api/services/<domain>/<service>``; refused (400) when Home Assistant
        rejects the data. Callers pass a domain and service from their own table."""
        return await self._json("POST", f"/services/{domain}/{service}", json_body=data or {})

    async def turn_on(self, entity_id: str, **kwargs) -> bool:
        domain = entity_id.split(".", 1)[0]
        await self.call_service(domain, "turn_on", {"entity_id": entity_id, **kwargs})
        return True

    async def turn_off(self, entity_id: str) -> bool:
        domain = entity_id.split(".", 1)[0]
        await self.call_service(domain, "turn_off", {"entity_id": entity_id})
        return True

    async def toggle(self, entity_id: str) -> bool:
        domain = entity_id.split(".", 1)[0]
        await self.call_service(domain, "toggle", {"entity_id": entity_id})
        return True

    # ------------------------------------------------------------------
    # Convenience device list
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[dict]:
        """A simplified list of the included domains (for the legacy DeviceAgent)."""
        devices = []
        for s in await self.states():
            eid = s["entity_id"]
            domain = eid.split(".")[0] if "." in eid else ""
            if domain not in INCLUDED_DOMAINS:
                continue
            attrs = s.get("attributes") if isinstance(s.get("attributes"), dict) else {}
            devices.append({
                "id": eid,
                "name": attrs.get("friendly_name", eid),
                "domain": domain,
                "state": s.get("state", "unknown"),
                "source": "home_assistant",
            })
        return devices
