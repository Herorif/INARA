"""Strict compatibility contracts for local devices and printer workflows."""

import ipaddress
import re
import uuid
from typing import Annotated, Literal
from pydantic import Field, RootModel, StrictInt, StrictStr, field_validator, model_validator
from services.settings import EmptyRequest


class EndpointRequest(EmptyRequest):
    host: StrictStr = Field(min_length=1, max_length=253)
    port: StrictInt | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def endpoint(self):
        raw = self.host.strip()
        if raw.count(":") == 1:
            host, port = raw.split(":")
            if self.port is not None or not port.isdecimal():
                raise ValueError("Use one numeric port.")
            raw, self.port = host, int(port)
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", raw):
            raise ValueError("Use an IPv4 address or hostname without a URL/path.")
        if any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in raw.split(".")
        ):
            raise ValueError("Use a valid hostname.")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("Use a valid port.")
        self.host, self.port = raw.lower(), self.port or 80
        return self


class AddPrinter(EndpointRequest):
    name: StrictStr | None = Field(default=None, min_length=1, max_length=120)
    type: Literal["moonraker", "octoprint", "unknown"] = "moonraker"
    camera_url: StrictStr | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def camera(self):
        from urllib.parse import urlsplit

        if self.name is not None and not self.name.strip():
            raise ValueError("Use a readable printer name.")
        if self.camera_url:
            parsed = urlsplit(self.camera_url)
            if (
                parsed.scheme not in ("http", "https")
                or parsed.hostname != self.host
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "Camera URL must use the configured printer host without credentials."
                )
        return self


class HSV(EmptyRequest):
    h: StrictInt = Field(ge=0, le=360)
    s: StrictInt = Field(ge=0, le=100)
    v: StrictInt = Field(ge=0, le=100)


class KasaTarget(EmptyRequest):
    ip: StrictStr

    @field_validator("ip")
    @classmethod
    def address(cls, value):
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_multicast or address.is_unspecified:
            raise ValueError("Use a discovered IPv4 device.")
        return str(address)


class KasaSwitch(KasaTarget):
    action: Literal["on", "off"]


class KasaBrightness(KasaTarget):
    action: Literal["brightness"]
    value: StrictInt = Field(ge=0, le=100)


class KasaColor(KasaTarget):
    action: Literal["color"]
    value: HSV


class KasaControl(
    RootModel[Annotated[KasaSwitch | KasaBrightness | KasaColor, Field(discriminator="action")]]
):
    pass


class PrintRequest(EmptyRequest):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    stl_path: StrictStr = Field(default="current", min_length=1, max_length=1024)
    printer: StrictStr = Field(min_length=1, max_length=253)
    profile: StrictStr | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("stl_path", "profile")
    @classmethod
    def relative_file(cls, value):
        from pathlib import PureWindowsPath

        if value is None:
            return value
        path = PureWindowsPath(value)
        if (
            path.drive
            or path.root
            or ":" in value
            or ".." in path.parts
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Use a project-relative path.")
        return value

    @field_validator("printer")
    @classmethod
    def readable_target(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Choose a configured printer.")
        return value.strip()


class PrintStage(EmptyRequest):
    request_id: uuid.UUID
    printer: StrictStr
    path: StrictStr
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source: StrictStr = Field(default="", max_length=1024)
    target: StrictStr = Field(default="", max_length=300)
    profile_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
