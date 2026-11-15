"""Kill-on-close Windows Job Objects for every JARVIS child process (docs/SECURITY.md).

One job holds a child and everything it starts. Closing the job's last handle (the core
exiting, crashing or calling ``close()``) kills the whole tree; ``terminate()`` kills it
at once.

Two ways a child joins a job:
- ``resident.win32.WorkspaceProcess`` (workers, Electron windows, cloudflared) names the
  job in CreateProcessW's attribute list, so the child is born inside it. It creates the
  job with ``create_job()`` here.
- ``spawn()`` (MCP servers, the CAD kernel, the World view globe) starts the child
  suspended through asyncio, assigns it with ``contain()`` and only then lets it run, so
  no grandchild can start outside the job.

If assignment fails (an old or restricted Windows), ``contain()`` logs one warning per
kind of child, lets the process run without a job and returns None: the owner's
``close()`` still stops it, only the kill-on-crash guarantee is lost. The native calls
sit behind ``native()`` so tests can swap in a fake layer.
"""

import asyncio
import os

from services.log import get_logger

logger = get_logger(__name__)

KILL_ON_JOB_CLOSE = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
EXTENDED_LIMIT_INFORMATION = 9  # JobObjectExtendedLimitInformation
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
# PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME
ASSIGN_ACCESS = 0x0001 | 0x0100 | 0x0800

_native = None
_warned = set()


class Win32Jobs:
    """The real ctypes layer (resident.win32's typed boundary). Each call raises OSError."""

    def __init__(self):
        import ctypes as C
        from ctypes import wintypes as W

        from resident.win32 import ExtendedLimit, api, checked, close_handle, kernel

        self.C, self.W, self.api, self.checked, self.kernel = C, W, api, checked, kernel
        self.ExtendedLimit, self.close_handle = ExtendedLimit, close_handle

    def create(self):
        C, W, api, checked, kernel = self.C, self.W, self.api, self.checked, self.kernel
        job = checked(api(kernel, "CreateJobObjectW", [W.LPVOID, W.LPCWSTR], W.HANDLE)(None, None))
        try:
            limits = self.ExtendedLimit()
            limits.basic.flags = KILL_ON_JOB_CLOSE
            checked(
                api(kernel, "SetInformationJobObject",
                    [W.HANDLE, C.c_int, W.LPVOID, W.DWORD], W.BOOL)(
                    job, EXTENDED_LIMIT_INFORMATION, C.byref(limits), C.sizeof(limits)
                )
            )
        except BaseException:
            self.close_handle(job)
            raise
        return job

    def _open(self, pid):
        W = self.W
        return self.checked(
            self.api(self.kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                ASSIGN_ACCESS, False, pid
            )
        )

    def assign(self, job, pid):
        W = self.W
        process = self._open(pid)
        try:
            self.checked(
                self.api(self.kernel, "AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL)(
                    job, process
                )
            )
        finally:
            self.close_handle(process)

    def resume(self, pid):
        C, W = self.C, self.W
        process = self._open(pid)
        try:
            function = C.WinDLL("ntdll").NtResumeProcess
            function.argtypes, function.restype = [W.HANDLE], C.c_long
            if function(process) != 0:
                raise OSError("The child process could not be resumed")
        finally:
            self.close_handle(process)

    def terminate(self, job):
        W = self.W
        self.api(self.kernel, "TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL)(job, 1)

    def close(self, job):
        self.close_handle(job)


def native():
    """The native layer (created on first use; tests replace ``_native``)."""
    global _native
    if _native is None:
        _native = Win32Jobs()
    return _native


def create_job():
    """A new kill-on-close job handle (raises OSError). The caller owns and closes it."""
    return native().create()


class KillOnCloseJob:
    """A kill-on-close job holding one child's process tree."""

    def __init__(self, layer=None):
        self.layer = layer or native()
        self.job = self.layer.create()

    def assign(self, pid):
        self.layer.assign(self.job, pid)

    def terminate(self):
        if self.job:
            self.layer.terminate(self.job)

    def close(self):
        if self.job:
            job, self.job = self.job, None
            self.layer.close(job)


def warn_once(label, exc):
    if label in _warned:
        return
    _warned.add(label)
    logger.warning(
        "%s runs without a kill-on-close job (%s); it stops with JARVIS's close only",
        label, type(exc).__name__,
    )


def contain(pid, label="A child process"):
    """Put the suspended process ``pid`` in a new kill-on-close job, then resume it.

    Returns the job, or None (logged once per ``label``) when the job couldn't be made or
    joined; the process is resumed either way. Raises OSError only when it can't be
    resumed, and the caller must then kill it.
    """
    layer = native()
    job = None
    try:
        job = KillOnCloseJob(layer)
        job.assign(pid)
    except OSError as exc:
        if job is not None:
            job.close()
            job = None
        warn_once(label, exc)
    try:
        layer.resume(pid)
    except BaseException:
        if job is not None:
            job.close()
        raise
    return job


async def spawn(argv, *, cwd, env, label="A child process", **stdio):
    """Start ``argv`` (no shell) with exactly ``env``; on Windows, suspended, then contained.

    ``stdio`` are asyncio's stdin/stdout/stderr choices. Returns ``(process, job)``; the
    job is None off Windows (the child gets its own session instead) or when ``contain``
    fell back.
    """
    if os.name != "nt":
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env, start_new_session=True, **stdio
        )
        return process, None
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW, **stdio
    )
    try:
        job = contain(process.pid, label)
    except BaseException:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise
    return process, job
