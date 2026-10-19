"""Read-only web inspection contracts; no scripts, credentials or action payloads."""

from urllib.parse import urlsplit, urlunsplit
import ipaddress
from typing import Literal
from pydantic import Field, StrictStr, field_validator
from services.settings import EmptyRequest


def public_url(value):
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError("Use a public HTTPS URL without whitespace.")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise ValueError("Use HTTPS on port 443 without credentials or a fragment.")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if (
        host.endswith(".")
        or "." not in host
        or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid"))
    ):
        raise ValueError("Use a public Internet hostname.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP literals are not supported.")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


class BrowserInspect(EmptyRequest):
    url: StrictStr = Field(min_length=10, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value)


class BrowserReport(EmptyRequest):
    url: StrictStr = Field(max_length=2048)
    title: StrictStr = Field(max_length=240)
    text: StrictStr = Field(max_length=12000)
    links: list[StrictStr] = Field(max_length=30)
    untrusted_content: Literal[True] = True
    mode: Literal["read_only_https"] = "read_only_https"
