"""Actual native host + hidden CAD UI; inspect worker exit and warmed resident recovery."""

import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
output = ROOT / ".runtime/cad-qa" / f"run-{uuid.uuid4()}"
output.mkdir(parents=True)
for key, name in [
    ("INARA_DATA_DIR", "database"),
    ("INARA_SETTINGS_FILE", "settings.json"),
    ("INARA_PROJECT_ROOT", "workspace"),
    ("INARA_LEGACY_DATA_DIR", "legacy"),
]:
    os.environ[key] = str(output / name)
os.environ["GEMINI_API_KEY"] = "changeme"  # Never use a real key in this verification.
os.environ.pop("ELECTRON_RUN_AS_NODE", None)
(output / "settings.json").write_text(json.dumps({"tool_permissions": {"generate_cad": True}}))
from resident.host import NativeHost  # noqa: E402
from resident.state import Identity  # noqa: E402
from resident.win32 import WorkspaceProcess, api, kernel  # noqa: E402

Identity(output / "profile").register(str(uuid.uuid4()))


def workspace(executable, entrypoint, bootstrap, cwd):
    bootstrap["qaOutput"] = str(output)
    return WorkspaceProcess(executable, ROOT / "scripts/verify-cad-workspace.cjs", bootstrap, cwd)


host = NativeHost(
    ROOT,
    output / "profile",
    process_factory=workspace,
    resident_only=True,
    hide_workspace=True,
    suppress_notifications=True,
)
result, worker_pids = {}, []


class Memory(C.Structure):
    _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [
        (name, C.c_size_t)
        for name in (
            "peak_ws",
            "ws",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
            "private",
        )
    ]


def memory(handle):
    value = Memory()
    value.cb = C.sizeof(value)
    if not api(C.WinDLL("psapi"), "GetProcessMemoryInfo", [W.HANDLE, W.LPVOID, W.DWORD], W.BOOL)(
        handle, C.byref(value), value.cb
    ):
        raise C.WinError()
    return {"working_set_mb": value.ws / 1048576, "private_mb": value.private / 1048576}


def sample():
    handles = [api(kernel, "GetCurrentProcess", [], W.HANDLE)()]
    parent = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
        0x410, False, os.getppid()
    )
    if parent:
        image = C.create_unicode_buffer(32768)
        length = W.DWORD(len(image))
        ok = api(
            kernel,
            "QueryFullProcessImageNameW",
            [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)],
            W.BOOL,
        )(parent, 0, image, C.byref(length))
        if ok and Path(image.value).parent.resolve() == (ROOT / ".venv/Scripts").resolve():
            handles.append(parent)
    try:
        values = [memory(handle) for handle in handles]
        return {key: round(sum(value[key] for value in values), 2) for key in values[0]}
    finally:
        if parent:
            kernel.CloseHandle(parent)


def until(condition, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        if host.state.phase == "failed":
            raise AssertionError(host.state.error)
        time.sleep(0.1)
    raise AssertionError("CAD integration condition timed out")


def verify():
    try:
        until(lambda: host.state.phase == "ready")

        def worker(*args):
            process = WorkspaceProcess(*args)
            worker_pids.append(process.pid)
            return process

        host.runtime.cad_service.process_factory = worker
        from services.cad_changes import EditList

        original_planner = host.runtime.runtime.cad_transport.change_planner

        async def fixture_planner(prompt, base):
            if prompt == "R5 FIXTURE MOVE FIRST OBJECT":
                return EditList(edits=[{"object_index": 0, "fields": {"position": [20, 0, 0]}}])
            return await original_planner(prompt, base)

        host.runtime.runtime.cad_transport.change_planner = fixture_planner
        result["proposal_fixture_only"] = True
        result["before_workspace"] = sample()
        host.tray.post(host.open_workspace)
        until(lambda: (output / "ui-verification.json").exists())
        result["ui"] = json.loads((output / "ui-verification.json").read_text())
        assert result["ui"]["passed"], result["ui"]
        until(lambda: host.workspace is None and not host.runtime.cad_service.active)
        assert len(worker_pids) == 5
        for pid in worker_pids:
            handle = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                0x100000, False, pid
            )
            if handle:
                try:
                    assert (
                        api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)(handle, 0)
                        == 0
                    )
                finally:
                    kernel.CloseHandle(handle)
        assert "creative.geometry" not in sys.modules
        assert "creative.scene" not in sys.modules
        result["workers_started_and_exited"] = len(worker_pids)
        result["geometry_module_in_resident"] = False
        result["resident_after_worker_and_workspace_exit"] = [sample()]
        for _ in range(5):
            time.sleep(2)
            result["resident_after_worker_and_workspace_exit"].append(sample())
        result["passed"] = True
    except BaseException as exc:
        result["passed"], result["error"] = False, repr(exc)
    finally:
        print(json.dumps(result, indent=2), flush=True)
        host.tray.post(lambda: host.action("quit"))


host.start_core()
worker = threading.Thread(target=verify)
worker.start()
try:
    host.tray.run()
finally:
    host.state.quitting = True
    if host.workspace:
        host.workspace.close()
    if host.server:
        host.server.should_exit = True
    host.thread.join(5)
    worker.join(5)
    host.tray.close()
    result["graceful_core_stop"] = not host.thread.is_alive()
    result["passed"] = result.get("passed", False) and result["graceful_core_stop"]
    (output / "verification.json").write_text(json.dumps(result, indent=2))
    print(f"Evidence: {output}", flush=True)
sys.exit(0 if result["passed"] else 1)
