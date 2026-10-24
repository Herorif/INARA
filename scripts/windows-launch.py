"""Windows file leases and a suspended-start, kill-on-close resident process tree."""

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys


class BasicLimits(c.Structure):
    _fields_ = [
        ("process_time", c.c_longlong),
        ("job_time", c.c_longlong),
        ("flags", w.DWORD),
        ("min_working", c.c_size_t),
        ("max_working", c.c_size_t),
        ("active", w.DWORD),
        ("affinity", c.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class ExtendedLimits(c.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", c.c_ulonglong * 6),
        ("process_memory", c.c_size_t),
        ("job_memory", c.c_size_t),
        ("peak_process", c.c_size_t),
        ("peak_job", c.c_size_t),
    ]


class Startup(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("width", w.DWORD),
        ("height", w.DWORD),
        ("columns", w.DWORD),
        ("rows", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_bytes", w.WORD),
        ("reserved_data", c.c_void_p),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class Process(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


def api():
    if sys.platform != "win32":
        raise ValueError("Guarded resident launch currently requires Windows")
    dll = c.WinDLL("kernel32.dll", winmode=0x800, use_last_error=True)
    definitions = {
        "CreateFileW": (
            [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE],
            w.HANDLE,
        ),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
        "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
        "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
        "ResumeThread": ([w.HANDLE], w.DWORD),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "GetExitCodeProcess": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        "CreateProcessW": (
            [
                w.LPCWSTR,
                w.LPWSTR,
                c.c_void_p,
                c.c_void_p,
                w.BOOL,
                w.DWORD,
                c.c_void_p,
                w.LPCWSTR,
                c.POINTER(Startup),
                c.POINTER(Process),
            ],
            w.BOOL,
        ),
    }
    for name, (arguments, result) in definitions.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = arguments, result
    return dll


def required(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


@contextmanager
def file_leases(paths):
    """Deny writes/deletion before verification; close every handle on failure."""
    dll, handles = api(), []
    try:
        for path in dict.fromkeys(paths):
            path = Path(path).absolute()
            if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError("Missing, linked or shared launch input")
            handle = dll.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
            if handle == w.HANDLE(-1).value:
                raise c.WinError(c.get_last_error())
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            dll.CloseHandle(handle)


def run(executable, arguments, directory, environment, expires):
    """No shell; suspended process cannot execute before job assignment succeeds."""
    dll, process = api(), Process()
    job = required(dll.CreateJobObjectW(None, None))
    expired = False
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway permission.
        required(dll.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)))
        if datetime.now(timezone.utc) >= expires:
            raise ValueError("Launch authorization expired before process creation")
        command = c.create_unicode_buffer(subprocess.list2cmdline([str(executable), *arguments]))
        # An explicit, sorted environment; handles are never inherited by the child.
        block = c.create_unicode_buffer(
            "\0".join(
                f"{key}={value}"
                for key, value in sorted(environment.items(), key=lambda item: item[0].upper())
            )
            + "\0\0"
        )
        startup = Startup()
        startup.size = c.sizeof(startup)
        required(
            dll.CreateProcessW(
                str(executable),
                command,
                None,
                None,
                False,
                0x4 | 0x400 | 0x08000000,
                block,
                str(directory),
                c.byref(startup),
                c.byref(process),
            )
        )
        required(dll.AssignProcessToJobObject(job, process.process))
        if datetime.now(timezone.utc) >= expires:
            raise ValueError("Launch authorization expired before process resume")
        if dll.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise c.WinError(c.get_last_error())
        while True:
            status = dll.WaitForSingleObject(process.process, 250)
            if status == 0:
                break
            if status != 258:
                raise c.WinError(c.get_last_error())
            if datetime.now(timezone.utc) >= expires:
                expired = True
                required(dll.TerminateJobObject(job, 1))
                break
        required(dll.WaitForSingleObject(process.process, 5000) == 0)
        code = w.DWORD()
        required(dll.GetExitCodeProcess(process.process, c.byref(code)))
        return {
            "exit_code": code.value,
            "authorization_expired": expired,
            "process_tree_contained": True,
        }
    finally:
        # Also kills remaining descendants after a natural resident exit, on errors,
        # or when Python unwinds after interruption. OS handle closure covers death.
        dll.TerminateJobObject(job, 1)
        if process.process:
            dll.TerminateProcess(process.process, 1)
            dll.WaitForSingleObject(process.process, 5000)
        for handle in (process.thread, process.process, job):
            if handle:
                dll.CloseHandle(handle)


def environment(data):
    values = dict(os.environ)
    for key in list(values):
        if key.upper() in {"PYTHONPATH", "PYTHONHOME", "ELECTRON_RUN_AS_NODE", "INARA_DEV_SERVER"}:
            del values[key]
    for key, name in {
        "INARA_DATA_DIR": "database",
        "INARA_SETTINGS_FILE": "settings.json",
        "INARA_PROJECT_ROOT": "projects",
        "INARA_LEGACY_DATA_DIR": "legacy",
        "INARA_DESKTOP_DATA_DIR": "desktop-profile",
    }.items():
        for old in list(values):
            if old.upper() == key:
                del values[old]
        values[key] = str(data / name)
    return values
