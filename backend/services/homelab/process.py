"""Child processes for homelab probes (ping.exe, ssh.exe, ssh-keyscan.exe).

Every child starts from ``child_env.minimal_env()`` (no inherited secrets) inside a
kill-on-close job (``job_object.spawn``), never through a shell, with a hard timeout. Output
stays in memory for parsing: it is never logged (only the program kind and an error class).
"""

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from services import job_object
from services.child_env import minimal_env
from services.homelab.base import AdapterError
from services.log import get_logger

logger = get_logger(__name__)

OUTPUT_LIMIT = 1_000_000


@dataclass(frozen=True)
class ProcessResult:
    code: int
    stdout: bytes
    stderr: bytes


def _system_root(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get("SystemRoot") or environ.get("SYSTEMROOT") or r"C:\Windows"


def program(name, *, environ=None, exists=os.path.isfile, which=shutil.which):
    """The full path of ``ping``, ``ssh`` or ``ssh-keyscan``: the Windows copy first
    (``System32\\PING.EXE``, ``System32\\OpenSSH\\<name>.exe``), else the one on PATH."""
    root = Path(_system_root(environ)) / "System32"
    candidates = {
        "ping": [root / "PING.EXE"],
        "ssh": [root / "OpenSSH" / "ssh.exe"],
        "ssh-keyscan": [root / "OpenSSH" / "ssh-keyscan.exe"],
    }[name]
    for candidate in candidates:
        if exists(str(candidate)):
            return str(candidate)
    found = which(name)
    if not found:
        raise AdapterError("program_missing", f"{name} isn't installed on this PC.")
    return found


async def run_process(argv, *, timeout, label="A homelab probe", stdin=None):
    """Run ``argv`` (a list, no shell) and return its exit code and output.

    Raises AdapterError("timeout") when it runs past ``timeout`` seconds (the job is
    terminated) and AdapterError("program_failed") when it can't start."""
    argv = [str(item) for item in argv]
    pipe = asyncio.subprocess.PIPE
    try:
        process, job = await job_object.spawn(
            argv, cwd=None, env=minimal_env(), label=label,
            stdin=pipe if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=pipe, stderr=pipe,
        )
    except OSError as exc:
        logger.info("%s could not start (%s)", label, type(exc).__name__)
        raise AdapterError("program_failed", "The check couldn't be started on this PC.") from None
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
    except BaseException as exc:
        if job is not None:
            job.terminate()
        try:
            process.kill()
        except ProcessLookupError:
            pass
        if isinstance(exc, TimeoutError):
            raise AdapterError("timeout", "The system didn't answer in time.") from None
        raise
    finally:
        if job is not None:
            job.close()
    return ProcessResult(
        process.returncode if process.returncode is not None else -1,
        (stdout or b"")[:OUTPUT_LIMIT],
        (stderr or b"")[:OUTPUT_LIMIT],
    )
