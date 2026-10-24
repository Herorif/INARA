"""Owned, ephemeral, explicit read-only browser tasks; no cloud calls."""

import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from services.browser_contracts import BrowserInspect, BrowserReport
from services.tools import ServiceError, ToolSpec

ROOT = Path(__file__).resolve().parents[2]


async def run_inspection(args):
    base = ROOT / ".runtime/browser-tasks"
    if base.resolve() != base:
        raise ServiceError("browser_path", "Browser staging path is linked.")
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="task-", dir=base)).resolve()
    process = None
    try:
        from resident.win32 import WorkspaceProcess

        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process = WorkspaceProcess(
            executable,
            ROOT / "backend/workers/browser_worker.py",
            {"directory": str(directory), "url": args.url},
            ROOT,
        )
        deadline = time.monotonic() + 25
        while process.alive():
            if time.monotonic() > deadline:
                raise ServiceError(
                    "browser_timeout", "Inspection exceeded its deadline and was stopped."
                )
            await asyncio.sleep(0.05)
        code = process.exit_code()
        process.close()
        path = directory / "result.json"
        if code != 0 or not path.is_file() or path.stat().st_size > 131072:
            raise ServiceError(
                "browser_failed", "Inspection could not complete. No actions were performed."
            )
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("ok") is not True:
            raise ServiceError(
                "browser_blocked", "Page unavailable or blocked by read-only network policy."
            )
        report = BrowserReport.model_validate(result["report"])
        if report.untrusted_content is not True or report.mode != "read_only_https":
            raise ValueError("Invalid report provenance")
        return report.model_dump()
    finally:
        if process:
            process.close()
        if directory.parent == base and not directory.is_symlink() and not directory.is_junction():
            shutil.rmtree(directory)


class BrowserService:
    def __init__(self, app):
        self.app, self.running = app, {}
        self.runner = run_inspection
        app.dispatcher.register(
            ToolSpec(
                "browser_inspect",
                "Inspect one explicit public HTTPS page as untrusted text, without scripts or actions.",
                BrowserInspect,
                self.inspect,
                execution_timeout=30,
                permission="run_web_agent",
                model_visible=False,
            )
        )

    async def inspect(self, args, context):
        self.app.authorize_owner(context)
        if self.running:
            raise ServiceError("browser_busy", "An inspection is already running.")
        task = asyncio.current_task()
        self.running[task] = context.get("origin_sid")
        try:
            report = await self.runner(args)
            self.app.authorize_owner(context)
            return {"report": report}
        finally:
            self.running.pop(task, None)

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.running.items())
            if task is not asyncio.current_task() and (sid is None or origin == sid)
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
