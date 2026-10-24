"""Owned job tree and external watchdog; a stuck driver cannot block the parent."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

from calls.lab_contracts import WorkerResult
from services.tools import ServiceError

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".runtime/call-bridge-runs"


class CallSupervisor:
    def __init__(self, process_factory=None, *, heartbeat_timeout=8, stop_timeout=6,
                 entrypoint=None):
        self.process_factory = process_factory
        self.heartbeat_timeout, self.stop_timeout = heartbeat_timeout, stop_timeout
        self.entrypoint = entrypoint or ROOT / "backend/workers/call_bridge_worker.py"
        self.running = False
        self.last_record_id = None

    async def run(self, bootstrap, stop, authorize=lambda: None, *, timeout=30):
        if self.running:
            raise ServiceError("call_worker_busy", "Another call worker is already owned here.")
        self.running = True
        self.last_record_id = None
        directory = process = None
        try:
            if BASE.resolve() != BASE:
                raise ServiceError("call_worker_path", "Call worker staging is linked.")
            BASE.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="run-", dir=BASE))
            request = {**bootstrap, "directory": str(directory)}
            if len(json.dumps(request).encode()) > 4096:
                raise ServiceError("call_worker_bootstrap", "The enrolled bridge exceeds the private pipe limit.")
            authorize()
            if stop.is_set():
                return {"ok": True, "mode": bootstrap["mode"], "id": None,
                        "state": "interrupted", "code": "owner_stopped"}
            factory = self.process_factory
            if factory is None:
                if os.name != "nt":
                    raise ServiceError("call_worker_platform", "Owned call workers require Windows.")
                from resident.win32 import WorkspaceProcess
                factory = WorkspaceProcess
            executable = Path(sys.executable)
            if executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            process = factory(executable, self.entrypoint, request, ROOT)
            started = previous = time.monotonic()
            last_heartbeat, heartbeat_value, stopping = started, None, None
            while process.alive():
                now = time.monotonic()
                if now - previous > 15:
                    raise ServiceError("call_worker_suspended", "The core was suspended; the call worker was stopped.")
                previous = now
                try:
                    authorize()
                except Exception:
                    stop.set()
                if stop.is_set() and stopping is None:
                    (directory / "stop").write_text("stop", encoding="ascii")
                    stopping = now
                if stopping is not None and now - stopping > self.stop_timeout:
                    raise ServiceError("call_worker_stop_timeout", "Call cleanup stalled; its owned process tree was terminated.")
                if now - started > timeout:
                    raise ServiceError("call_worker_timeout", "The call worker exceeded its hard deadline and was terminated.")
                heartbeat = directory / "heartbeat.json"
                if heartbeat.is_file() and heartbeat.stat().st_size <= 1024:
                    try:
                        value = json.loads(heartbeat.read_text(encoding="utf-8"))
                        sequence = value["sequence"]
                        if type(sequence) is int and sequence >= 0 and (heartbeat_value is None or sequence > heartbeat_value):
                            last_heartbeat, heartbeat_value = now, sequence
                    except (ValueError, KeyError, OSError):
                        pass
                if now - last_heartbeat > self.heartbeat_timeout:
                    raise ServiceError("call_worker_stalled", "The call worker stopped responding and its process tree was terminated.")
                await asyncio.sleep(0.05)
            path = directory / "result.json"
            if process.exit_code() != 0 or not path.is_file() or path.stat().st_size > 4096:
                raise ServiceError("call_worker_failed", "The call worker ended without a valid final receipt.")
            value = WorkerResult.model_validate_json(path.read_bytes()).model_dump(mode="json")
            if value["mode"] != bootstrap["mode"]:
                raise ServiceError("call_worker_result", "The worker returned the wrong diagnostic mode.")
            return value
        except asyncio.CancelledError:
            # First Ctrl+C/parent cancellation still gives the child a short
            # opportunity to hang up its exact call and finalize its receipt.
            if process and directory and process.alive():
                try:
                    (directory / "stop").write_text("stop", encoding="ascii")
                    deadline = time.monotonic() + self.stop_timeout
                    while process.alive() and time.monotonic() < deadline:
                        await asyncio.sleep(0.05)
                except Exception:
                    pass
            raise
        finally:
            if process:
                process.close()  # Kill-on-close job includes native helper descendants.
            if directory:
                reference = directory / "record.json"
                try:
                    if reference.is_file() and reference.stat().st_size <= 256:
                        self.last_record_id = str(uuid.UUID(json.loads(reference.read_text())["id"]))
                except (ValueError, KeyError, OSError):
                    pass
            if (directory and directory.parent == BASE and directory.resolve() == directory
                    and not directory.is_symlink() and not directory.is_junction()):
                shutil.rmtree(directory)
            self.running = False
