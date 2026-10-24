"""Real bundled private setup worker: fresh synthetic install, launch, removal and erasure."""

import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--control", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
control = args.control.absolute()
assert Path(sys.executable).resolve() == control / "runtime/python/python.exe"
output = args.output.absolute()
assert output.parent == ROOT / ".runtime"
if not args.resume:
    assert not output.exists()
    output.mkdir()
else:
    assert output.is_dir() and output.name.startswith("setup-package-qa-")
installation = output / "installation"
assert installation.resolve().is_relative_to((ROOT / ".runtime").resolve())


def start():
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-X", "utf8", str(control / "scripts/desktop-control.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    reply = json.loads(process.stdout.readline())
    assert reply["ready"]
    return process


worker = start()


def send(request, success=True):
    worker.stdin.write(json.dumps(request) + "\n")
    worker.stdin.flush()
    line = worker.stdout.readline()
    assert line, "Setup worker stopped"
    result = json.loads(line)
    assert result["ok"] is success, result
    return result.get("result", result)


def action(name, **values):
    reviewed = send(
        {"op": "review", "request": {"action": name, "root": str(installation), **values}}
    )
    result = send({"op": "apply", "token": reviewed["token"]})
    return reviewed, result


if not args.resume:
    reviewed = send(
        {
            "op": "review",
            "request": {"action": "install", "root": str(installation), "package": str(control)},
        }
    )
    assert not installation.exists()
    installed = send({"op": "apply", "token": reviewed["token"]})
    slot = installed["slot"]
    assert not installed["activated"]
    action("select", slot=slot)
    data = installation / "data" / slot
    (data / "settings.json").write_text(json.dumps({"face_auth_enabled": False}))
    (data / "fixture-private.txt").write_text("SYNTHETIC_PRIVATE_SETUP_DATA")
else:
    state = json.loads((installation / "installation.json").read_text())
    slot = state["current"]
    assert slot in state["slots"] and len(state["slots"]) == 1
    data = installation / "data" / slot
    assert (data / "fixture-private.txt").read_text() == "SYNTHETIC_PRIVATE_SETUP_DATA"
_, launched = action("launch", resident_only=True)
pid = launched["pid"]
assert launched["launch_requested"]
user = C.WinDLL("user32", use_last_error=True)
kernel = C.WinDLL("kernel32", use_last_error=True)
callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user.EnumWindows.argtypes = [callback, W.LPARAM]
user.EnumWindows.restype = W.BOOL
user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user.GetWindowThreadProcessId.restype = W.DWORD
user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user.GetClassNameW.restype = C.c_int
user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user.PostMessageW.restype = W.BOOL
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel.WaitForSingleObject.restype = W.DWORD
kernel.CloseHandle.argtypes = [W.HANDLE]
kernel.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
kernel.GetExitCodeProcess.restype = W.BOOL
handle = kernel.OpenProcess(0x101000, False, pid)
assert handle
window = None
try:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        found = []

        @callback
        def enumerate_window(hwnd, value):
            owner = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(owner))
            if owner.value == pid:
                name = C.create_unicode_buffer(256)
                user.GetClassNameW(hwnd, name, 256)
                if name.value.startswith("INARA.Native."):
                    found.append(hwnd)
            return True

        user.EnumWindows(enumerate_window, 0)
        if found and (data / "database/assistant.sqlite3").exists():
            window = found[0]
            break
        assert kernel.WaitForSingleObject(handle, 0) == 0x102
        time.sleep(0.2)
    assert window, "Owned resident window/storage did not start"
    # Closing setup must not terminate the explicitly launched resident.
    worker.stdin.close()
    assert worker.wait(timeout=30) == 0
    assert kernel.WaitForSingleObject(handle, 0) == 0x102
    worker = start()
    busy = send({"op": "status", "root": str(installation)}, success=False)
    assert "busy" in busy["error"].lower()
    assert user.PostMessageW(window, 0x8002, 0, 0)  # Only the observed owned test PID/window.
    assert kernel.WaitForSingleObject(handle, 30000) == 0
    code = W.DWORD()
    assert kernel.GetExitCodeProcess(handle, C.byref(code)) and code.value == 0
finally:
    if window and kernel.WaitForSingleObject(handle, 0) == 0x102:
        user.PostMessageW(window, 0x8002, 0, 0)
    kernel.CloseHandle(handle)
# Wait for the child process to release all filesystem mappings before removal.
status = send({"op": "status", "root": str(installation)})
assert status["selected"] == slot
_, removed = action("uninstall")
assert removed["data_preserved"]
assert (data / "fixture-private.txt").read_text() == "SYNTHETIC_PRIVATE_SETUP_DATA"
assert (data / "database/assistant.sqlite3").is_file()
assert not (installation / "versions" / slot).exists()
status = send({"op": "status", "root": str(installation)})
assert status["versions"] == []
reviewed = send({"op": "review", "request": {"action": "erase_data", "root": str(installation)}})
send({"op": "apply", "token": reviewed["token"], "confirmation": "yes"}, success=False)
assert data.exists()
reviewed = send({"op": "review", "request": {"action": "erase_data", "root": str(installation)}})
send({"op": "apply", "token": reviewed["token"], "confirmation": "ERASE INARA DATA"})
assert not data.exists()
worker.stdin.close()
assert worker.wait(timeout=30) == 0
# Full inventory check proves uninstall/erasure did not escape to the control candidate.

spec = importlib.util.spec_from_file_location("package", control / "scripts/desktop-package.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.verify(control)
report = {
    "passed": True,
    "bundled_private_worker_used": True,
    "fresh_install_and_explicit_selection": True,
    "owned_native_resident_started": True,
    "resident_survived_setup_close": True,
    "resident_lease_blocked_management": True,
    "owned_resident_graceful_quit": True,
    "software_removed_profiles_retained": True,
    "separate_exact_data_erasure_confirmation": True,
    "synthetic_data_erased_after_confirmation": True,
    "control_candidate_unchanged": True,
    "real_profile_used": False,
    "registry_or_startup_changed": False,
    "signed": False,
    "clean_machine_acceptance": False,
}
(output / "verification.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
