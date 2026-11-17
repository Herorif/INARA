"""What the generic adapters share: the context they run in, common options and HTTP.

``AdapterContext`` carries everything with an outside effect (secrets by name, the child
process runner, the httpx transport, TCP connect, the UDP sender, the known_hosts file), so
tests swap fakes in and nothing here reaches the network on its own.
"""

import asyncio
import contextlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Annotated, Callable, Literal

import httpx
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, StringConstraints, field_validator

from services.homelab.base import AdapterError, Entity, Strict
from services.log import get_logger

logger = get_logger(__name__)

BODY_LIMIT = 2_000_000
MAC = re.compile(r"^[0-9a-f]{2}([:-]?)[0-9a-f]{2}(?:\1[0-9a-f]{2}){4}$")


async def tcp_connect(host, port, timeout):
    """Open and close one TCP connection (raises OSError or TimeoutError)."""
    _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


@dataclass
class AdapterContext:
    secret: Callable  # name -> value | None (never logged)
    run: Callable  # async (argv, *, timeout, label, stdin=None) -> ProcessResult
    known_hosts: object  # ssh.KnownHosts
    transport: object = None  # an httpx transport (tests); None uses the real network
    connect: Callable = tcp_connect
    send_udp: Callable = None  # (packet, (address, port)) -> None
    programs: dict = field(default_factory=dict)  # name -> path override (tests)


# --- options -------------------------------------------------------------------------------


def mac_address(value):
    text = value.strip().lower() if isinstance(value, str) else ""
    if not MAC.fullmatch(text):
        raise ValueError("Use the MAC address, for example aa:bb:cc:dd:ee:ff.")
    raw = re.sub(r"[:-]", "", text)
    if raw in ("000000000000", "ffffffffffff"):
        raise ValueError("Use the machine's own MAC address.")
    return ":".join(raw[index:index + 2] for index in range(0, 12, 2))


def broadcast_address(value):
    try:
        address = ipaddress.IPv4Address(value.strip() if isinstance(value, str) else value)
    except (ValueError, TypeError):
        raise ValueError("Use an IPv4 broadcast address, for example 192.168.1.255.") from None
    if str(address) != "255.255.255.255" and not (address.is_private or address.is_link_local):
        raise ValueError("Wake-on-LAN packets stay on the home network.")
    if address.is_loopback:
        raise ValueError("Use the home network's broadcast address.")
    return str(address)


class CommonOptions(Strict):
    """Options every adapter takes. ``temp_max_c``: the high-temperature alert threshold."""

    temp_max_c: StrictInt | StrictFloat = Field(default=80, ge=30, le=120)


class WakeOptions(CommonOptions):
    """``wake_mac``: lets ``homelab_wake`` wake this system (its broadcast and UDP port)."""

    wake_mac: StrictStr | None = None
    wake_broadcast: StrictStr = "255.255.255.255"
    wake_port: Literal[7, 9] = 9

    @field_validator("wake_mac")
    @classmethod
    def check_mac(cls, value):
        return None if value is None else mac_address(value)

    @field_validator("wake_broadcast")
    @classmethod
    def check_broadcast(cls, value):
        return broadcast_address(value)


HeaderName = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,64}$")]
UrlPath = Annotated[StrictStr, StringConstraints(max_length=300, pattern=r"^(/[A-Za-z0-9._~/%-]*)?$")]


class HttpOptions(WakeOptions):
    """``path`` is added to the address; the secret (by name) goes in ``auth_header`` as
    ``auth_prefix`` + value, e.g. Authorization: "Bearer " or "PVEAPIToken=" + the token."""

    path: UrlPath = ""
    auth_header: HeaderName = "Authorization"
    auth_prefix: Annotated[StrictStr, StringConstraints(max_length=32, pattern=r"^[A-Za-z0-9 =_.-]*$")] = ""
    verify_tls: StrictBool = True
    timeout_s: StrictInt | StrictFloat = Field(default=10, ge=1, le=30)


# --- adapters --------------------------------------------------------------------------------


class BaseAdapter:
    url_address = False  # the address is a URL (http_json, prometheus) or a bare host
    uses_secret = False
    Options = WakeOptions

    def __init__(self, config, context):
        self.config = config
        self.context = context
        self.options = self.Options.model_validate(config.options)

    @property
    def actions(self):
        names = [action.name for action in self.config.named_actions]
        if getattr(self.options, "wake_mac", None) or self.config.adapter == "wol":
            names.append("wake")
        return names

    def entity(self, suffix, kind, name, state, metrics=None, detail=""):
        entity_id = self.config.id if suffix is None else f"{self.config.id}:{suffix}"
        return Entity(entity_id, self.config.id, kind, name, state, metrics or {}, detail)

    async def probe(self):
        raise NotImplementedError

    async def act(self, action, args):
        raise AdapterError("homelab_no_action", "This system has no actions.")


class HttpAdapter(BaseAdapter):
    url_address = True
    uses_secret = True
    Options = HttpOptions

    def headers(self):
        """The auth header, with the secret from the store by name (never logged)."""
        headers = {"Accept": "application/json"}
        if self.config.secret is None:
            return headers
        value = self.context.secret(self.config.secret)
        if not value:
            raise AdapterError(
                "homelab_secret_missing",
                f"The secret {self.config.secret} isn't saved yet.",
            )
        headers[self.options.auth_header] = f"{self.options.auth_prefix}{value}"
        return headers

    async def request(self, method, path, *, params=None, json_body=None):
        """One bounded request to ``address + path``; AdapterError on transport failure."""
        options = {"timeout": float(self.options.timeout_s), "follow_redirects": False,
                   "trust_env": False}
        if self.context.transport is not None:
            options["transport"] = self.context.transport
        elif self.options.verify_tls:
            from services.tls import provider_ssl_context

            options["verify"] = provider_ssl_context()
        else:
            options["verify"] = False
        headers = self.headers()
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(
                    method, self.config.address + path, params=params, json=json_body,
                    headers=headers,
                )
        except httpx.TimeoutException:
            raise AdapterError("timeout", "The system didn't answer in time.") from None
        except Exception as exc:  # the text can carry the address: never logged or returned
            logger.info("Homelab request to a %s system failed (%s)",
                        self.config.adapter, type(exc).__name__)
            raise AdapterError("unreachable", "The system couldn't be reached.") from None
        if len(response.content) > BODY_LIMIT:
            raise AdapterError("too_large", "The system's answer was too large.")
        return response

    @staticmethod
    def refused(status):
        return status in (401, 403)

    @staticmethod
    def json_of(response):
        try:
            return json.loads(response.content)
        except (ValueError, UnicodeDecodeError):
            raise AdapterError("not_json", "The system's answer wasn't JSON.") from None

    async def act(self, action, args):
        named = self.config.action(action)
        if named is None or named.request is None:
            raise AdapterError("homelab_unknown_action", "That action isn't set up for this system.")
        request = named.request
        response = await self.request(request.method, request.path, json_body=request.body)
        if self.refused(response.status_code):
            raise AdapterError("homelab_refused", "The system refused the saved secret.")
        return {"done": 200 <= response.status_code < 300, "status": response.status_code}
