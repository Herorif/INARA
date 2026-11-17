"""The shapes every homelab adapter shares (S12.3, docs/HOMELAB.md).

- ``Entity``: one observed thing (a host, a port, a disk, a container, a unit, a UPS) with a
  state of ok, warn, down or unknown, a few metrics and a short plain detail.
- ``Adapter``: ``async probe() -> list[Entity]``, ``actions`` and ``async act(action, args)``.
- ``HostConfig``: one ``homelab.hosts`` entry. ``secret`` is a secret NAME in the encrypted
  store, never a value; ``options`` are checked by the adapter's own options model; named
  actions are fixed by the owner (the brain can only pick one by name).
- ``Comparison`` and ``dotted``: the small, eval-free rule language of ``ok_when``.

No I/O here. Nothing in this module logs.
"""

import ipaddress
import math
import re
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

STATES = ("ok", "warn", "down", "unknown")
STATE_RANK = {"ok": 0, "unknown": 1, "warn": 2, "down": 3}
ADAPTER_NAMES = ("ping", "tcp", "http_json", "prometheus", "ssh", "wol")
HOST_LIMIT = 64
NAMED_ACTION_LIMIT = 16
INTERVAL_MIN, INTERVAL_MAX, INTERVAL_DEFAULT = 15, 3600, 60
DETAIL_LIMIT = 200
TEXT_METRIC_LIMIT = 120

HOST_ID = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
SECRET_NAME = r"^[a-z][a-z0-9_]{0,63}$"
METRIC_NAME = r"^[a-z][a-z0-9_]{0,47}$"
ACTION_NAME = r"^[a-z0-9](?:[a-z0-9 _-]{0,38}[a-z0-9])?$"
# Dotted paths: object keys and list indexes joined by dots ("data.0.status"). Never code.
PATH_SEGMENT = r"[A-Za-z0-9_\-]{1,64}"
DOTTED_PATH = rf"^{PATH_SEGMENT}(?:\.{PATH_SEGMENT}){{0,15}}$"
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_URL_PATH = re.compile(r"^[A-Za-z0-9._~/%-]*$")
_PRINTABLE = r"^[^\x00-\x1f\x7f]+$"

HostId = Annotated[StrictStr, StringConstraints(pattern=HOST_ID)]
SecretName = Annotated[StrictStr, StringConstraints(pattern=SECRET_NAME)]
MetricName = Annotated[StrictStr, StringConstraints(pattern=METRIC_NAME)]
DottedPath = Annotated[StrictStr, StringConstraints(pattern=DOTTED_PATH, max_length=400)]
ActionName = Annotated[StrictStr, StringConstraints(pattern=ACTION_NAME)]
Scalar = StrictBool | StrictInt | StrictFloat | Annotated[StrictStr, StringConstraints(max_length=200)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- entities and adapters ------------------------------------------------------------------


def _clean(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def metric_value(value):
    """A metric as a finite float or a short string; None for anything else."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        return _clean(value, TEXT_METRIC_LIMIT)
    return None


@dataclass(frozen=True)
class Entity:
    """One observed thing. ``id`` is unique across the homelab ("nas:disk:/mnt/data")."""

    id: str
    host: str
    kind: str
    name: str
    state: str
    metrics: dict = field(default_factory=dict)
    detail: str = ""

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError("Unknown entity state")
        clean = {}
        for key, value in dict(self.metrics or {}).items():
            value = metric_value(value)
            if isinstance(key, str) and value is not None:
                clean[key] = value
        object.__setattr__(self, "metrics", clean)
        object.__setattr__(self, "name", _clean(self.name, 120))
        object.__setattr__(self, "detail", _clean(self.detail, DETAIL_LIMIT))

    def as_dict(self):
        return {
            "id": self.id, "host": self.host, "kind": self.kind, "name": self.name,
            "state": self.state, "metrics": dict(self.metrics), "detail": self.detail,
        }


def worst(states):
    """The worst of several states (down > warn > unknown > ok); "unknown" for none."""
    states = [state for state in states if state in STATE_RANK]
    return max(states, key=STATE_RANK.get) if states else "unknown"


@runtime_checkable
class Adapter(Protocol):
    actions: list

    async def probe(self) -> list:  # list[Entity]
        ...

    async def act(self, action: str, args: dict) -> dict:
        ...


class AdapterError(Exception):
    """A plain, owner-safe failure: never an address with credentials, a secret or output."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# --- the ok_when rule language (no eval) ----------------------------------------------------

Op = Literal["==", "!=", "<", "<=", ">", ">=", "in", "contains"]
_ORDERING = frozenset({"<", "<=", ">", ">="})
_MISSING = object()


class Comparison(Strict):
    """``{"path": "status", "op": "==", "value": "ok"}``: a fixed operator on a dotted path."""

    path: DottedPath
    op: Op
    value: Scalar | list[Scalar] = Field()

    @field_validator("path")
    @classmethod
    def no_private_segments(cls, value):
        if any(segment.startswith("__") for segment in value.split(".")):
            raise ValueError("A path segment can't start with two underscores.")
        return value

    @model_validator(mode="after")
    def operand(self):
        if self.op == "in":
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 32:
                raise ValueError("'in' needs a list of 1 to 32 values.")
        elif isinstance(self.value, list):
            raise ValueError("Only 'in' takes a list of values.")
        if self.op in _ORDERING and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("Ordering comparisons need a number.")
        return self


def dotted(data, path):
    """The value at ``path`` in nested dicts and lists, or ``_MISSING``. Item access only."""
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return _MISSING
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def lookup(data, path):
    """``dotted`` with None for a missing value."""
    value = dotted(data, path)
    return None if value is _MISSING else value


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _equal(actual, expected):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(expected, (int, float)):
        number = _number(actual)
        return number is not None and number == float(expected)
    if isinstance(expected, str):
        return isinstance(actual, (str, int, float)) and str(actual) == expected
    return False


def compare(actual, op, expected):
    """One comparison; a missing or wrongly typed value is simply False."""
    if actual is _MISSING:
        return False
    if op == "==":
        return _equal(actual, expected)
    if op == "!=":
        return not _equal(actual, expected)
    if op in _ORDERING:
        left, right = _number(actual), _number(expected)
        if left is None or right is None:
            return False
        return {"<": left < right, "<=": left <= right,
                ">": left > right, ">=": left >= right}[op]
    if op == "in":
        return any(_equal(actual, item) for item in expected)
    if op == "contains":
        if isinstance(actual, str):
            return isinstance(expected, str) and expected in actual
        if isinstance(actual, list):
            return any(_equal(item, expected) for item in actual)
        return False
    return False


def evaluate(data, comparisons):
    """True when every comparison holds (an empty list holds)."""
    return all(compare(dotted(data, item.path), item.op, item.value) for item in comparisons)


# --- addresses --------------------------------------------------------------------------------


def host_address(value):
    """A bare host name or IP address (never an option, a user@ or a URL)."""
    if not isinstance(value, str):
        raise ValueError("Give the host name or IP address.")
    text = value.strip().lower()
    try:
        return str(ipaddress.ip_address(text.strip("[]")))
    except ValueError:
        pass
    if not _HOSTNAME.fullmatch(text):
        raise ValueError("Use a host name or IP address, for example 192.168.1.10 or nas.local.")
    return text


def base_url(value):
    """``scheme://host[:port][/path]`` with no sign-in, query or fragment. http is accepted
    only for an address on the home network (the rule Home Assistant uses)."""
    message = "Use the full address, for example http://192.168.1.10:9100."
    if not isinstance(value, str):
        raise ValueError(message)
    text = value.strip()
    if not text or len(text) > 300 or any(ord(char) < 33 or ord(char) == 127 for char in text):
        raise ValueError(message)
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise ValueError(message) from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Start the address with http:// or https://.")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("Use only the address, without a sign-in name or anything after ?.")
    host = host_address(parts.hostname)
    if not _URL_PATH.fullmatch(parts.path):
        raise ValueError(message)
    from services.settings import home_address_is_local

    if scheme == "http" and not home_address_is_local(host):
        raise ValueError("Use https for an address outside your home network.")
    shown = f"[{host}]" if ":" in host else host
    return f"{scheme}://{shown}{'' if port is None else ':' + str(port)}{parts.path.rstrip('/')}"


def url_host(url):
    """The host name of a ``base_url``."""
    return (urlsplit(url).hostname or "").lower()


# --- host configuration -----------------------------------------------------------------------


class HttpRequestAction(Strict):
    """A fixed HTTP request against the host's address (``http_json`` hosts)."""

    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    path: Annotated[StrictStr, StringConstraints(max_length=300, pattern=r"^/[A-Za-z0-9._~/%-]*$")]
    body: dict | None = None

    @field_validator("body")
    @classmethod
    def small_body(cls, value):
        if value is not None and len(repr(value)) > 4000:
            raise ValueError("The request body is too large.")
        return value


class NamedAction(Strict):
    """An owner-defined action: exactly one fixed ``command`` (ssh) or ``request`` (http)."""

    name: ActionName
    command: Annotated[StrictStr, StringConstraints(min_length=1, max_length=500,
                                                    pattern=_PRINTABLE)] | None = None
    request: HttpRequestAction | None = None

    @model_validator(mode="after")
    def one_kind(self):
        if (self.command is None) == (self.request is None):
            raise ValueError("Give each action either a command or a request.")
        return self

    def describe(self, address):
        """The exact command or request, as the approval card shows it."""
        if self.command is not None:
            return self.command
        request = self.request
        text = f"{request.method} {address}{request.path}"
        return text if request.body is None else f"{text} with body {request.body}"


class HostConfig(Strict):
    """One ``homelab.hosts`` entry; ``options`` are normalised by the adapter's model."""

    id: HostId
    name: StrictStr = Field(min_length=1, max_length=60, pattern=r"^[^\x00-\x1f\x7f<>{}]+$")
    adapter: Literal["ping", "tcp", "http_json", "prometheus", "ssh", "wol"]
    address: StrictStr = Field(min_length=1, max_length=300)
    options: dict = Field(default_factory=dict)
    secret: SecretName | None = None
    named_actions: list[NamedAction] = Field(default_factory=list, max_length=NAMED_ACTION_LIMIT)
    interval_s: StrictInt = Field(default=INTERVAL_DEFAULT, ge=INTERVAL_MIN, le=INTERVAL_MAX)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the system a name.")
        return value

    @model_validator(mode="after")
    def adapter_rules(self):
        from services.homelab.adapters import ADAPTERS

        adapter = ADAPTERS[self.adapter]
        self.address = (
            base_url(self.address) if adapter.url_address else host_address(self.address)
        )
        self.options = adapter.Options.model_validate(self.options).model_dump()
        if self.secret is not None and not adapter.uses_secret:
            raise ValueError("Only http_json and prometheus systems use a secret.")
        names = [action.name for action in self.named_actions]
        if len(set(names)) != len(names):
            raise ValueError("Each action needs its own name.")
        for action in self.named_actions:
            if action.command is not None and self.adapter != "ssh":
                raise ValueError("Command actions need an ssh system.")
            if action.request is not None and self.adapter != "http_json":
                raise ValueError("Request actions need an http_json system.")
        return self

    def action(self, name):
        return next((item for item in self.named_actions if item.name == name), None)


class HomelabHosts(Strict):
    """``homelab.*``: the owner's systems, replaced whole on each save."""

    hosts: list[HostConfig] = Field(default_factory=list, max_length=HOST_LIMIT)

    @field_validator("hosts")
    @classmethod
    def unique_ids(cls, value):
        if len({host.id for host in value}) != len(value):
            raise ValueError("Each system needs its own id.")
        return value
