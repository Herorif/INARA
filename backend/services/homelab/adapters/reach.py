"""Reachability: ``ping`` (one echo through Windows' ping.exe) and ``tcp`` (open ports).

ping runs ``PING.EXE -n 1 -w <ms> <address>`` with no shell, the minimal environment and a
kill-on-close job; up means a reply line with a round-trip time ("time=3ms", "time<1ms", or
the same in another Windows language). tcp opens and closes one TCP connection per port.
"""

import asyncio
import re
from typing import Annotated

from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.homelab.adapters.common import BaseAdapter, WakeOptions
from services.homelab.process import program

# "time=3ms", "time<1ms", "Zeit=12ms", "durée=3 ms": a number right after = or < and before ms.
_LATENCY = re.compile(rb"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms\b", re.IGNORECASE)


def parse_ping(code, stdout):
    """(up, latency_ms or None) from ping.exe's exit code and output (bytes)."""
    if code != 0:
        return False, None
    match = _LATENCY.search(stdout or b"")
    if match is None:
        return False, None  # e.g. "Destination host unreachable" exits 0 without a time
    return True, float(match.group(1).replace(b",", b"."))


class PingOptions(WakeOptions):
    timeout_ms: StrictInt = Field(default=1000, ge=100, le=5000)
    warn_ms: StrictInt | None = Field(default=None, ge=1, le=5000)


class PingAdapter(BaseAdapter):
    Options = PingOptions

    def argv(self):
        path = self.context.programs.get("ping") or program("ping")
        return [path, "-n", "1", "-w", str(self.options.timeout_ms), self.config.address]

    async def probe(self):
        result = await self.context.run(
            self.argv(), timeout=self.options.timeout_ms / 1000 + 5, label="A homelab ping"
        )
        up, latency = parse_ping(result.code, result.stdout)
        if not up:
            return [self.entity(None, "host", self.config.name, "down", {},
                                "No answer to ping.")]
        state = "ok"
        if self.options.warn_ms is not None and latency > self.options.warn_ms:
            state = "warn"
        return [self.entity(None, "host", self.config.name, state, {"latency_ms": latency},
                            f"Answered in {latency:g} ms.")]


Label = Annotated[StrictStr, StringConstraints(min_length=1, max_length=40,
                                               pattern=r"^[^\x00-\x1f\x7f<>{}]+$")]


class TcpOptions(WakeOptions):
    ports: list[Annotated[StrictInt, Field(ge=1, le=65535)]] = Field(min_length=1, max_length=32)
    labels: dict[Annotated[StrictStr, StringConstraints(pattern=r"^[0-9]{1,5}$")], Label] = Field(
        default_factory=dict, max_length=32)
    timeout_s: StrictInt | StrictFloat = Field(default=2, ge=0.2, le=10)

    @field_validator("ports")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("List each port once.")
        return value

    @model_validator(mode="after")
    def labelled_ports(self):
        if any(int(port) not in self.ports for port in self.labels):
            raise ValueError("Label only the listed ports.")
        return self


class TcpAdapter(BaseAdapter):
    Options = TcpOptions

    async def _open(self, port):
        try:
            await self.context.connect(self.config.address, port, float(self.options.timeout_s))
            return True
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError):
            return False

    async def probe(self):
        ports = self.options.ports
        results = await asyncio.gather(*(self._open(port) for port in ports))
        entities = []
        for port, open_ in zip(ports, results, strict=True):
            name = self.options.labels.get(str(port)) or f"Port {port}"
            entities.append(self.entity(
                f"port:{port}", "service", name, "ok" if open_ else "down", {"port": port},
                "Open." if open_ else "Not answering.",
            ))
        return entities
