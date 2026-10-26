"""Owned, hard-deadline execution for retained AI-written legacy CAD scripts.

Generated code runs only in a WorkspaceProcess child (Windows Job Object with
kill-on-close), never in the core. The awaiting coroutine owns the child:
every exit path — success, failure, hard timeout, cancellation (including the
dispatcher deadline and workspace shutdown) and gaming/resident mode — kills
the whole tree and waits for it to be gone before returning, so a caller that
holds the creative lock around ``run`` releases it only after the exit.
"""

import asyncio
import os
from pathlib import Path
import sys
import time

from services.tools import ServiceError
from services.log import get_logger

logger = get_logger(__name__)

# Hard wall-clock limit for one generated script run (per attempt).
LEGACY_CAD_SCRIPT_TIMEOUT_SECONDS = 120
# Bound on waiting for the killed tree to disappear before declaring a fault.
LEGACY_CAD_STOP_TIMEOUT_SECONDS = 5
LEGACY_CAD_WORKER = Path(__file__).resolve().parents[1] / "workers" / "legacy_cad_worker.py"
ERROR_FILENAME = ".legacy_cad_error.txt"
ERROR_LIMIT = 8000


def default_process_factory():
    if os.name != "nt":
        raise ServiceError(
            "legacy_cad_platform", "Owned legacy CAD workers require Windows."
        )
    from resident.win32 import WorkspaceProcess

    return WorkspaceProcess


class LegacyScriptRunner:
    def __init__(
        self,
        governor=None,
        process_factory=None,
        timeout=LEGACY_CAD_SCRIPT_TIMEOUT_SECONDS,
        worker=LEGACY_CAD_WORKER,
        poll_interval=0.05,
    ):
        self.governor, self.process_factory = governor, process_factory
        self.timeout, self.worker, self.poll_interval = timeout, Path(worker), poll_interval

    def stop(self, process):
        """Kill the owned tree and confirm it exited; returns False on a stalled cleanup."""
        terminate = getattr(process, "terminate", None)
        if terminate is None:
            process.close()
            return True
        try:
            return bool(terminate(LEGACY_CAD_STOP_TIMEOUT_SECONDS))
        except Exception:
            try:
                process.close()
            except Exception:
                logger.warning("Legacy CAD process tree could not be closed", exc_info=True)
            return False

    def stopped_state(self):
        return self.governor is not None and self.governor.state in ("gaming", "resident")

    async def run(self, script, work_dir):
        """Run ``script`` with cwd ``work_dir``; returns ``(exit_code, error_text)``."""
        work_dir = Path(work_dir).resolve()
        script = Path(script).resolve()
        if not work_dir.is_dir() or not script.is_file() or script.parent != work_dir:
            raise ServiceError(
                "artifact_invalid", "Legacy CAD scripts must stay in the project CAD folder."
            )
        error_path = work_dir / ERROR_FILENAME
        error_path.unlink(missing_ok=True)
        factory = self.process_factory or default_process_factory()
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        process = None
        clean = True
        try:
            if self.stopped_state():
                raise ServiceError(
                    "job_cancelled", "Legacy CAD is unavailable in gaming or resident mode."
                )
            process = factory(
                executable,
                self.worker,
                {"script": str(script), "work_dir": str(work_dir), "error": str(error_path)},
                work_dir,
            )
            previous = time.monotonic()
            deadline = previous + self.timeout
            while process.alive():
                if self.governor is not None:
                    previous = self.governor.poll(previous)
                if self.stopped_state():
                    raise ServiceError(
                        "job_cancelled",
                        "Legacy CAD stopped for gaming or resident mode; its process tree was terminated.",
                    )
                if time.monotonic() > deadline:
                    raise ServiceError(
                        "legacy_cad_timeout",
                        f"Generated CAD code exceeded its {self.timeout:g}s limit; its process tree was terminated.",
                    )
                await asyncio.sleep(self.poll_interval)
            exit_code = process.exit_code()
        finally:
            # Synchronous on purpose: a second cancellation cannot interrupt the
            # wait, so callers never observe a return while the tree survives.
            if process is not None and not self.stop(process):
                clean = False
                if self.governor is not None:
                    self.governor.fault = (
                        "Legacy CAD cleanup failed. Restart the core before more heavy work."
                    )
                    self.governor.select("resident")
        if not clean:
            raise ServiceError(
                "legacy_cad_cleanup",
                "Legacy CAD cleanup could not confirm the process tree exited; restart the core.",
            )
        text = ""
        try:
            if error_path.is_file():
                with error_path.open("rb") as stream:
                    text = stream.read(ERROR_LIMIT).decode("utf-8", "replace")
        except OSError:
            logger.debug("Legacy CAD error output could not be read", exc_info=True)
        finally:
            try:
                error_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Legacy CAD error output could not be removed", exc_info=True)
        return exit_code, text
