"""Fixed offline contract suite in a disposable workspace-owned profile."""

import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


async def main():
    request = json.loads(sys.stdin.buffer.read(8193))
    directory = Path(request["directory"]).resolve()
    base = ROOT / ".runtime/quality-checks"
    if directory.parent != base.resolve() or directory.is_symlink() or directory.is_junction():
        raise ValueError("Invalid evaluation directory")
    for key in tuple(os.environ):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            os.environ.pop(key, None)
    os.environ.update(
        INARA_DATA_DIR=str(directory / "private"),
        INARA_PROJECT_ROOT=str(directory / "projects"),
        INARA_LEGACY_DATA_DIR=str(directory / "legacy"),
        INARA_SETTINGS_FILE=str(directory / "settings.json"),
        GEMINI_API_KEY="changeme",
    )

    def offline(event, args):
        if event in (
            "socket.connect",
            "socket.connect_ex",
            "socket.getaddrinfo",
            "socket.bind",
            "socket.sendto",
            "socket.sendmsg",
        ):
            raise RuntimeError("Network is disabled in quality fixtures")

    sys.addaudithook(offline)
    from services.quality_suite import run_fixture_suite

    report = await run_fixture_suite(directory)
    (directory / "result.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
