"""Isolated real Win32 host/workspace lifecycle and idle measurement (no keys/camera)."""

import argparse
import asyncio
import ctypes as C
from ctypes import wintypes as W
import json
import os
import socket
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--idle-seconds", type=int, default=600)
parser.add_argument("--failure-recovery", action="store_true")
args = parser.parse_args()
output = ROOT / ".runtime/native-qa" / f"run-{uuid.uuid4()}"
output.mkdir(parents=True)
for key, directory in [
    ("INARA_DATA_DIR", "database"),
    ("INARA_SETTINGS_FILE", "settings.json"),
    ("INARA_PROJECT_ROOT", "workspace"),
    ("INARA_LEGACY_DATA_DIR", "legacy"),
]:
    os.environ[key] = str(output / directory)
os.environ.pop("ELECTRON_RUN_AS_NODE", None)
from resident.host import NativeHost  # noqa: E402 - isolate before importing the runtime
from resident.state import Identity  # noqa: E402
from resident.win32 import api, kernel, user, Tray, WPARAM, LPARAM  # noqa: E402

owner = str(uuid.uuid4())
Identity(output / "profile").register(owner)
host = NativeHost(
    ROOT, output / "profile", resident_only=True, suppress_notifications=True, hide_workspace=True
)
result = {"pid": os.getpid(), "output": str(output), "real_game_benchmark": "deferred by user"}
busy = None
if args.failure_recovery:
    busy = socket.socket()
    busy.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    busy.bind(("127.0.0.1", 8000))
    busy.listen(1)
resident_handles = [("core_and_tray", api(kernel, "GetCurrentProcess", [], W.HANDLE)())]
launcher = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
    0x410, False, os.getppid()
)
if launcher:
    image = C.create_unicode_buffer(32768)
    size = W.DWORD(len(image))
    ok = api(
        kernel,
        "QueryFullProcessImageNameW",
        [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)],
        W.BOOL,
    )(launcher, 0, image, C.byref(size))
    if ok and Path(image.value).parent.resolve() == (ROOT / ".venv/Scripts").resolve():
        resident_handles.append(("venv_launcher", launcher))
    else:
        kernel.CloseHandle(launcher)
        launcher = None
result["resident_process_count"] = len(resident_handles)


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


def process_sample(process):
    memory = Memory()
    memory.cb = C.sizeof(memory)
    if not api(C.WinDLL("psapi"), "GetProcessMemoryInfo", [W.HANDLE, W.LPVOID, W.DWORD], W.BOOL)(
        process, C.byref(memory), memory.cb
    ):
        raise C.WinError()
    times = [W.FILETIME() for _ in range(4)]
    if not api(kernel, "GetProcessTimes", [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL)(
        process, *(C.byref(t) for t in times)
    ):
        raise C.WinError()
    cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10000000
    return {
        "working_set_mb": memory.ws / 1048576,
        "private_mb": memory.private / 1048576,
        "cpu_seconds": cpu,
    }


def sample():
    processes = {role: process_sample(handle) for role, handle in resident_handles}
    return {
        "elapsed": time.monotonic(),
        "processes": processes,
        **{
            metric: sum(values[metric] for values in processes.values())
            for metric in ("working_set_mb", "private_mb", "cpu_seconds")
        },
    }


def until(condition, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        if host.state.phase == "failed":
            raise AssertionError(host.state.error)
        time.sleep(0.1)
    raise AssertionError("Native integration condition timed out")


def core(coroutine):
    return asyncio.run_coroutine_threadsafe(coroutine, host.loop).result(15)


def role_count(role):
    return sum(
        value == role
        for key, value in tuple(host.runtime.client_roles.items())
        if key != "native-resident"
    )


def close_workspace():
    async def close():
        for sid, role in tuple(host.runtime.client_roles.items()):
            if role == "workspace":
                await host.runtime.sio.emit("workspace_close", {}, room=sid)

    core(close())
    until(
        lambda: (
            host.workspace is None and role_count("renderer") == 0 and role_count("workspace") == 0
        )
    )


def verify():
    try:
        if busy:
            deadline = time.monotonic() + 25
            while (
                not (host.state.phase == "failed" and not host.thread.is_alive())
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            assert host.state.phase == "failed" and not host.thread.is_alive()
            assert (
                busy.getsockname()[1] == 8000
            )  # The host did not kill or claim the busy listener.
            busy.close()
            host.tray.post(host.start_core)
            time.sleep(0.1)
            result["busy_port_failure_recovery"] = True
        until(lambda: host.state.phase == "ready")
        for attempt in range(2):
            started = time.monotonic()
            if attempt == 0:
                api(user, "PostMessageW", [W.HWND, W.UINT, WPARAM, LPARAM], W.BOOL)(
                    host.tray.window, 0x312, 1, 0
                )
            else:
                secondary = Tray(
                    host.tray.name.rsplit(".", 1)[-1],
                    ROOT / "assets/icons/inara.ico",
                    lambda _: None,
                    lambda: None,
                )
                assert secondary.secondary
                secondary.close()
            until(lambda: role_count("workspace") == 1 and role_count("renderer") == 1)
            result[f"open_{attempt + 1}_seconds"] = round(time.monotonic() - started, 3)
            assert host.state.identity.owner == owner
            assert host.runtime.client_principals["native-resident"] == owner
            pid = host.workspace.pid
            close_workspace()
            process = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                0x100000, False, pid
            )
            if process:
                try:
                    assert (
                        api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)(
                            process, 5000
                        )
                        == 0
                    )
                finally:
                    kernel.CloseHandle(process)
        result["close_reopen_same_core_identity"] = True
        result["hotkey_message_and_single_instance_reopen"] = True
        result["hotkey_registered"] = host.state.hotkey
        host.tray.post(host.open_workspace)
        until(lambda: role_count("workspace") == 1 and role_count("renderer") == 1)
        host.tray.post(lambda: host.workspace.close())  # Simulate exit of this owned workspace job.
        until(
            lambda: (
                host.workspace is None
                and role_count("renderer") == 0
                and role_count("workspace") == 0
            )
        )
        assert host.state.phase == "ready"
        result["workspace_crash_transport_cleanup"] = True

        async def reminder():
            host.runtime.reminder_store.add_reminder("isolated native reminder", time.time() - 1)
            await host.runtime.deliver_reminders_once()
            return host.runtime.reminder_store.open_deliveries(owner)

        deliveries = core(reminder())
        assert host.tray.notification_count == 1 and len(deliveries) == 1
        result["resident_reminder_receipt"] = True
        core(host.control(owner, {"action": "gaming", "gaming": True}))
        until(lambda: host.runtime.resource_governor.state == "gaming")

        async def override():
            host.runtime.client_principals["qa-renderer"] = owner
            await host.runtime.set_resource_state("qa-renderer", {"state": "studio"})
            assert host.runtime.resource_governor.state == "gaming"
            host.runtime.client_principals.pop("qa-renderer")

        core(override())
        assert not core(host.notify({"delivery_id": "gaming-suppressed"}))
        core(host.control(owner, {"action": "gaming", "gaming": False}))
        until(lambda: host.runtime.resource_governor.state == "resident")
        result["manual_gaming_guard"] = True
        # Warm up complete; measure the entire resident host/core process, no Electron.
        assert host.workspace is None
        samples = [sample()]
        deadline = time.monotonic() + args.idle_seconds
        print(f"IDLE START {output}", flush=True)
        while time.monotonic() < deadline:
            time.sleep(min(5, max(0.01, deadline - time.monotonic())))
            assert host.workspace is None and host.state.phase == "ready"
            samples.append(sample())
        duration = samples[-1]["elapsed"] - samples[0]["elapsed"]
        result["idle"] = {
            "seconds": round(duration, 2),
            "working_set_mean_mb": round(
                sum(s["working_set_mb"] for s in samples) / len(samples), 2
            ),
            "working_set_peak_mb": round(max(s["working_set_mb"] for s in samples), 2),
            "private_peak_mb": round(max(s["private_mb"] for s in samples), 2),
            "cpu_percent_one_core": round(
                100 * (samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]) / duration, 4
            ),
            "electron_processes": 0,
            "samples": samples,
        }
        result["passed"] = True
    except BaseException as exc:
        result["passed"], result["error"] = False, repr(exc)
    finally:
        (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(
            json.dumps({key: value for key, value in result.items() if key != "idle"}), flush=True
        )
        if "idle" in result:
            print(
                json.dumps(
                    {key: value for key, value in result["idle"].items() if key != "samples"}
                ),
                flush=True,
            )
        host.tray.post(lambda: host.action("quit"))


host.start_core()
worker = threading.Thread(target=verify, name="Native QA")
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
    if launcher:
        kernel.CloseHandle(launcher)
    result["graceful_core_stop"] = not host.thread.is_alive() and host.loop.is_closed()
    if not result["graceful_core_stop"]:
        result["passed"] = False
    (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
sys.exit(0 if result.get("passed") else 1)
