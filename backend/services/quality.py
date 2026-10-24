"""Owned bounded subprocess runner; no real profiles, providers or model setup."""

import asyncio
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import time
from services.quality_suite import CASE_IDS, SUITE_VERSION
from services.storage import scope_hash
from services.tools import ServiceError

ROOT = Path(__file__).resolve().parents[2]


async def run_offline_suite():
    base = ROOT / ".runtime/quality-checks"
    if base.resolve() != base:
        raise ServiceError(
            "quality_path", "Evaluation staging path is linked. No suite was started."
        )
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="fixture-", dir=base)).resolve()
    if directory.parent != base:
        raise ServiceError("quality_path", "Evaluation directory escaped its staging root.")
    process = None
    try:
        from resident.win32 import WorkspaceProcess

        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process = WorkspaceProcess(
            executable,
            ROOT / "backend/workers/quality_worker.py",
            {"directory": str(directory)},
            ROOT,
        )
        deadline = time.monotonic() + 20
        while process.alive():
            if time.monotonic() > deadline:
                raise TimeoutError
            await asyncio.sleep(0.05)
        code = process.exit_code()
        process.close()
        path = directory / "result.json"
        if code != 0 or not path.is_file() or path.stat().st_size > 65536:
            raise ServiceError(
                "quality_failed",
                "Offline fixtures could not complete. No real provider or profile was used.",
            )
        report = json.loads(path.read_text(encoding="utf-8"))
        if (
            type(report.get("passed")) is not bool
            or type(report.get("passed_count")) is not int
            or type(report.get("total")) is not int
            or not isinstance(report.get("duration_seconds"), (float, int))
            or not math.isfinite(report["duration_seconds"])
            or report["duration_seconds"] < 0
            or report.get("suite_version") != SUITE_VERSION
            or report.get("fixture_only") is not True
            or report.get("provider_used") is not False
            or report.get("model_quality_verified") is not False
            or [item["id"] for item in report.get("cases", [])] != list(CASE_IDS)
            or any(type(item.get("passed")) is not bool for item in report["cases"])
            or any(
                not isinstance(item.get("duration_seconds"), (float, int))
                or not math.isfinite(item["duration_seconds"])
                or item["duration_seconds"] < 0
                for item in report["cases"]
            )
            or report.get("total") != len(CASE_IDS)
            or report.get("passed_count") != sum(item["passed"] for item in report["cases"])
            or report.get("passed") != all(item["passed"] for item in report["cases"])
        ):
            raise ServiceError("quality_invalid", "Offline evaluation report failed validation.")
        return report
    except TimeoutError as exc:
        raise ServiceError(
            "quality_timeout", "Offline checks exceeded their deadline and were stopped."
        ) from exc
    finally:
        if process:
            process.close()
        # Exact resolved task-owned directory only, never a user profile or computed shell command.
        if directory.parent == base and not directory.is_symlink() and not directory.is_junction():
            shutil.rmtree(directory)


class QualityService:
    def __init__(self, app):
        self.app = app
        self.running = {}

    def key(self, owner, project):
        return scope_hash(owner + "\n" + str(project.resolve()))

    def snapshot(self, owner, project):
        with self.app.database.connection() as db:
            report = self.app.database.get(db, "quality_report_v1", self.key(owner, project))
        return {"report": report, "running": bool(self.running)}

    async def run(self, sid, owner, project):
        if self.running:
            raise ServiceError("quality_busy", "An offline evaluation is already running.")
        task = asyncio.current_task()
        self.running[task] = sid
        try:
            report = await run_offline_suite()
            self.app.sessions.require_owner(sid, {"renderer"})
            report["completed_at"] = time.time()
            with self.app.database.transaction() as db:
                self.app.database.put(db, "quality_report_v1", self.key(owner, project), report)
            return {"report": report, "running": False}
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
