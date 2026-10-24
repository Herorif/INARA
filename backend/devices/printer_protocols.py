"""Explicit printer HTTP clients. No retries, redirects, fallback or upload-to-start."""

import asyncio
import json
import math
from pathlib import Path
import re
from services.device_contracts import EndpointRequest
from devices.printer_models import PrintStatus

MAX_JSON = 262144
MAX_GCODE = 134217728


class ProtocolError(RuntimeError):
    pass


def session_factory(timeout):
    import aiohttp

    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 3)),
        trust_env=False,
        auto_decompress=False,
    )


def endpoint(printer):
    value = EndpointRequest(host=printer.host, port=printer.port)
    kind = getattr(printer.printer_type, "value", printer.printer_type)
    if kind not in {"moonraker", "octoprint"}:
        raise ProtocolError("Unsupported configured protocol.")
    return (
        f"http://{value.host}:{value.port}",
        kind,
        {"X-Api-Key": printer.api_key} if printer.api_key else {},
    )


def number(value, low=0, high=1e10):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ProtocolError("Invalid numeric status.")
    return value


def duration(value):
    if value is None:
        return None
    seconds = int(number(value))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def text(value, limit=1024):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ProtocolError("Invalid text status.")
    return value


def state_name(value):
    result = text(value, 80)
    if not result:
        raise ProtocolError("Missing printer state.")
    return result.lower()


def temperature(value):
    return number(value, -100, 2000)


async def json_response(response):
    if response.status != 200:
        raise ProtocolError("Status request was rejected.")
    raw = bytearray()
    while len(raw) <= MAX_JSON:
        chunk = await response.content.read(min(65536, MAX_JSON + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) > MAX_JSON:
        raise ProtocolError("Status response exceeds its limit.")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ProtocolError("Expected a status object.")
    return data


class PrinterProtocolClient:
    def __init__(self, sessions=session_factory, forms=None):
        self.sessions, self.forms = sessions, forms

    async def status(self, printer):
        base, kind, headers = endpoint(printer)
        async with asyncio.timeout(8):
            async with self.sessions(3) as session:
                if kind == "octoprint":
                    async with session.get(
                        base + "/api/job", headers=headers, allow_redirects=False
                    ) as response:
                        data = await json_response(response)
                    async with session.get(
                        base + "/api/printer", headers=headers, allow_redirects=False
                    ) as response:
                        sensors = (await json_response(response)).get("temperature", {})
                    state = state_name(data["state"])
                    progress, job = data.get("progress", {}), data.get("job", {})
                    temps = {}
                    for source, name in (("tool0", "hotend"), ("bed", "bed")):
                        if source in sensors:
                            temps[name] = {
                                "current": temperature(sensors[source].get("actual", 0)),
                                "target": temperature(sensors[source].get("target", 0)),
                            }
                    return PrintStatus(
                        printer.name,
                        state.lower(),
                        number(progress.get("completion") or 0, 0, 100),
                        duration(progress.get("printTimeLeft")),
                        duration(progress.get("printTime")),
                        text(job.get("file", {}).get("name")),
                        temps,
                    )
                async with session.get(
                    base + "/printer/objects/query?print_stats&display_status&heater_bed&extruder",
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    data = (await json_response(response))["result"]["status"]
                stats, display = data["print_stats"], data.get("display_status", {})
                temps = {}
                for source, name in (("extruder", "hotend"), ("heater_bed", "bed")):
                    sensor = data.get(source, {})
                    temps[name] = {
                        "current": temperature(sensor.get("temperature", 0)),
                        "target": temperature(sensor.get("target", 0)),
                    }
                return PrintStatus(
                    printer.name,
                    state_name(stats["state"]),
                    number(display.get("progress") or 0, 0, 1) * 100,
                    None,
                    duration(stats.get("print_duration")),
                    text(stats.get("filename")),
                    temps,
                )

    async def upload(self, printer, path):
        # Physical start has a separate method; never include a print/select/start form field.
        try:
            base, kind, headers = endpoint(printer)
            path = Path(path)
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_GCODE:
                return False
            if not re.fullmatch(r"[0-9a-f]{32}\.gcode", path.name):
                return False
            forms = self.forms
            if forms is None:
                from aiohttp import FormData

                forms = FormData
            async with asyncio.timeout(30):
                async with self.sessions(30) as session:
                    with path.open("rb") as stream:
                        form = forms()
                        form.add_field("file", stream, filename=path.name)
                        if kind == "moonraker":
                            form.add_field("root", "gcodes")
                        route = (
                            "/server/files/upload" if kind == "moonraker" else "/api/files/local"
                        )
                        async with session.post(
                            base + route, data=form, headers=headers, allow_redirects=False
                        ) as response:
                            return response.status in (200, 201, 202, 204)
        except Exception:
            return False

    async def start(self, printer, filename):
        if not re.fullmatch(r"[0-9a-f]{32}\.gcode", filename):
            return False
        try:
            base, kind, headers = endpoint(printer)
            route, payload = (
                ("/printer/print/start", {"filename": filename})
                if kind == "moonraker"
                else ("/api/files/local/" + filename, {"command": "select", "print": True})
            )
            async with asyncio.timeout(10):
                async with self.sessions(10) as session:
                    async with session.post(
                        base + route, json=payload, headers=headers, allow_redirects=False
                    ) as response:
                        return response.status in (200, 201, 202, 204)
        except Exception:
            return False
