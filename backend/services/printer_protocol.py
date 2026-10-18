"""Start an already uploaded file, without upload, fallback or automatic retry."""

import re
from urllib.parse import quote


async def start_uploaded(printer, filename, client_factory=None):
    if not re.fullmatch(r"[0-9a-f]{32}\.gcode", filename):
        return False
    kind = getattr(printer.printer_type, "value", printer.printer_type)
    if kind == "moonraker":
        path, payload = "/printer/print/start", {"filename": filename}
    elif kind == "octoprint":
        path, payload = (
            "/api/files/local/" + quote(filename, safe=""),
            {"command": "select", "print": True},
        )
    else:
        return False
    headers = {"X-Api-Key": printer.api_key} if printer.api_key else {}
    if client_factory is None:
        import aiohttp

        def client_factory():
            return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))

    try:
        async with client_factory() as session:
            async with session.post(
                f"http://{printer.host}:{printer.port}{path}", json=payload, headers=headers
            ) as response:
                return response.status in (200, 201, 202, 204)
    except Exception:
        return False
