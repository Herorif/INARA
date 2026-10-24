"""Hidden native Command OS acceptance using isolated files and inert local fixtures."""

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
output = ROOT / ".runtime/command-qa" / f"run-{uuid.uuid4()}"
output.mkdir(parents=True)
for key, name in [
    ("INARA_DATA_DIR", "database"),
    ("INARA_SETTINGS_FILE", "settings.json"),
    ("INARA_PROJECT_ROOT", "workspace"),
    ("INARA_LEGACY_DATA_DIR", "legacy"),
]:
    os.environ[key] = str(output / name)
os.environ["GEMINI_API_KEY"] = "changeme"
os.environ["INARA_IMAGE_MODEL_DIR"] = ""
os.environ.pop("ELECTRON_RUN_AS_NODE", None)
(output / "settings.json").write_text(
    json.dumps({"tool_permissions": {"write_file": False, "read_file": False, "launch_app": False}})
)
from resident.host import NativeHost  # noqa: E402
from resident.state import Identity  # noqa: E402
from resident.win32 import WorkspaceProcess, api, kernel  # noqa: E402

Identity(output / "profile").register(str(uuid.uuid4()))


def workspace(executable, entrypoint, bootstrap, cwd):
    bootstrap["qaOutput"] = str(output)
    return WorkspaceProcess(
        executable, ROOT / "scripts/verify-command-workspace.cjs", bootstrap, cwd
    )


host = NativeHost(
    ROOT,
    output / "profile",
    process_factory=workspace,
    resident_only=True,
    hide_workspace=True,
    suppress_notifications=True,
)
result = {}


class Memory(C.Structure):
    _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [
        (name, C.c_size_t)
        for name in (
            "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged", "nonpaged",
            "pagefile", "peak_pagefile", "private",
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
            kernel, "QueryFullProcessImageNameW",
            [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL,
        )(parent, 0, image, C.byref(length))
        if ok and Path(image.value).parent.resolve() == (ROOT / ".venv/Scripts").resolve():
            handles.append(parent)
    try:
        values = [memory(handle) for handle in handles]
        return {key: round(sum(value[key] for value in values), 2) for key in values[0]}
    finally:
        if parent:
            kernel.CloseHandle(parent)


def until(condition, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = output / "ui-verification.json"
        if report.exists() and not json.loads(report.read_text()).get("passed", False):
            raise AssertionError(report.read_text())
        if condition():
            return
        if host.state.phase == "failed":
            raise AssertionError(host.state.error)
        time.sleep(0.1)
    raise AssertionError("Command workspace integration condition timed out")


def verify():
    try:
        until(lambda: host.state.phase == "ready")
        result["before_workspace"] = sample()
        app = host.runtime.runtime
        app.settings["kasa_devices"] = [{"ip": "10.0.0.2", "alias": "Private fixture"}]
        app.settings["printers"] = [{"host": "printer.test", "port": 7125, "type": "moonraker"}]
        app.connections.package_probe = lambda name: True
        # Deterministic admission fixture; this run does not benchmark host capacity.
        app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
        activations = []
        checks = []
        supervisor_factory = app.call_lab.supervisor_factory

        def supervised_check():
            checks.append(True)
            return supervisor_factory()

        app.call_lab.supervisor_factory = supervised_check

        def forbidden(*args, **kwargs):
            activations.append(True)
            raise AssertionError("Shell navigation must not activate devices, providers or workers")

        for name in ("kasa", "printer", "inara", "desktop", "vision", "devices"):
            getattr(app, name).get = forbidden
        app.conversation.provider_factory = forbidden
        app.cad.process_factory = app.images.process_factory = forbidden
        app.browser.runner = forbidden
        app.speech.transcriber = forbidden

        # Fail one local snapshot after the renderer explicitly asks for the fixture.
        snapshot = app.connections.snapshot
        error_seen = False

        def readiness():
            nonlocal error_seen
            if (output / "readiness-error-requested.json").exists() and not error_seen:
                error_seen = True
                raise RuntimeError("Synthetic local readiness failure")
            return snapshot()

        app.connections.snapshot = readiness
        host.tray.post(host.open_workspace)
        until(lambda: (output / "ui-verification.json").exists())
        result["ui"] = json.loads((output / "ui-verification.json").read_text())
        assert result["ui"]["passed"], result["ui"]
        until(lambda: host.workspace is None)
        assert error_seen, "Recovery fixture must actually exercise the error path"
        assert not activations
        assert all(getattr(app, name).instance is None for name in (
            "kasa", "printer", "inara", "desktop", "vision", "devices"
        ))
        assert not app.cad.active and not app.images.active and not app.browser.running
        assert app.speech.turn is None and not app.compat_service.observation.task
        assert not app.mobile.listener.running
        assert app.call_lab.active is None
        assert len(checks) == 3
        assert not {
            "kasa", "zeroconf", "printer_agent", "kasa_agent", "google.genai",
            "torch", "diffusers", "cv2", "mediapipe", "creative.image_backend",
        } & set(sys.modules)
        result["device_provider_creative_activations"] = 0
        result["supervised_call_check_requests"] = len(checks)
        result["resident_after_workspace_exit"] = sample()
        result["real_hardware_or_notifications_used"] = False
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
