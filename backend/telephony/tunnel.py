"""Cloudflare named-tunnel supervisor: ``cloudflared tunnel --no-autoupdate run``.

The tunnel token is passed in the child's environment as ``TUNNEL_TOKEN``
(cloudflared reads it there), never on the command line. The child runs in a
kill-on-close Windows job (``resident.win32.WorkspaceProcess``) so it cannot
outlive the core. cloudflared is never downloaded: it is found through
``JARVIS_CLOUDFLARED`` (an explicit path), ``PATH`` or the installer's default
folders. Ingress (public hostname -> ``http://127.0.0.1:8790``, path
``^/telephony/``) is configured on the Cloudflare side for the named tunnel.
"""

import asyncio
import os
from pathlib import Path
import shutil
import sys
import time

from services import env
from services.log import get_logger

logger = get_logger("telephony.tunnel")

ARGUMENTS = ("tunnel", "--no-autoupdate", "run")
RESTART_DELAYS = (2.0, 10.0, 30.0)
HEALTHY_SECONDS = 300.0
POLL_SECONDS = 0.5
STATES = ("stopped", "not_configured", "missing_binary", "starting", "running", "restarting", "failed")


def default_locations(environ=None):
    environ = os.environ if environ is None else environ
    folders = [environ.get("ProgramFiles(x86)"), environ.get("ProgramFiles")]
    return [Path(folder) / "cloudflared" / "cloudflared.exe" for folder in folders if folder]


def locate_cloudflared(environ=None, which=shutil.which):
    """Path to an existing cloudflared executable, or None."""
    environ = os.environ if environ is None else environ
    explicit = (env.getenv("CLOUDFLARED", environ=environ) or "").strip()
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    found = which("cloudflared", path=environ.get("PATH"))
    if found:
        return Path(found)
    for path in default_locations(environ):
        if path.is_file():
            return path
    return None


def _workspace_process(executable, arguments, environment, cwd):
    from resident.win32 import WorkspaceProcess

    return WorkspaceProcess(
        executable, None, None, cwd, arguments=arguments, environment=environment
    )


class TunnelSupervisor:
    def __init__(self, token, *, locate=locate_cloudflared, process_factory=None, launcher=None,
                 restart_delays=RESTART_DELAYS, healthy_seconds=HEALTHY_SECONDS,
                 poll_seconds=POLL_SECONDS, clock=time.monotonic):
        """``token()`` returns the tunnel token or None.

        ``launcher`` (tests only) replaces the located binary with a command
        prefix such as ``[python, fake_cloudflared.py]``.
        """
        self.token, self.locate = token, locate
        self.process_factory = process_factory
        self.launcher = list(launcher) if launcher else None
        self.restart_delays, self.healthy_seconds = tuple(restart_delays), healthy_seconds
        self.poll_seconds, self.clock = poll_seconds, clock
        self.state = "stopped"
        self.process = self.task = None
        self.exit_code = None
        self.restarts = 0
        self.lock = asyncio.Lock()

    def binary(self):
        if self.launcher:
            return Path(self.launcher[0])
        return self.locate()

    def status(self):
        binary = self.binary()
        return {
            "state": self.state,
            "binary_found": binary is not None,
            "exit_code": self.exit_code,
            "restarts": self.restarts,
        }

    async def start(self):
        async with self.lock:
            if self.task is not None and not self.task.done():
                return self.status()
            token = self.token()
            if not token:
                self.state = "not_configured"
                return self.status()
            binary = self.binary()
            if binary is None:
                self.state = "missing_binary"
                return self.status()
            self.exit_code, self.restarts = None, 0
            self.state = "starting"
            self.task = asyncio.create_task(self._supervise(binary), name="cloudflare-tunnel")
            await asyncio.sleep(0)
            return self.status()

    def _spawn(self, binary):
        token = self.token()
        if not token:
            raise LookupError("tunnel token missing")
        arguments = [*(self.launcher or [str(binary)]), *ARGUMENTS]
        factory = self.process_factory
        if factory is None:
            if os.name != "nt":
                raise OSError("The tunnel supervisor requires Windows job objects.")
            factory = _workspace_process
        executable = self.launcher[0] if self.launcher else str(binary)
        return factory(executable, arguments, {"TUNNEL_TOKEN": token}, str(Path(sys.prefix)))

    async def _supervise(self, binary):
        # Cancellation (stop) leaves the live child to stop(), which kills its job.
        attempt = 0
        while True:
            started = self.clock()
            try:
                self.process = await asyncio.to_thread(self._spawn, binary)
            except Exception as exc:
                logger.error("cloudflared could not start: %s", type(exc).__name__)
                self.state = "failed"
                return
            self.state = "running"
            while self.process.alive():  # noqa: ASYNC110  polls the cloudflared child; no in-process event exists
                await asyncio.sleep(self.poll_seconds)
            try:
                self.exit_code = self.process.exit_code()
            except OSError:
                self.exit_code = None
            await asyncio.to_thread(self._release)
            if self.clock() - started >= self.healthy_seconds:
                attempt = 0
            if attempt >= len(self.restart_delays):
                logger.error("cloudflared exited (code %s); giving up", self.exit_code)
                self.state = "failed"
                return
            logger.warning("cloudflared exited (code %s); restarting", self.exit_code)
            self.state = "restarting"
            await asyncio.sleep(self.restart_delays[attempt])
            attempt += 1
            self.restarts += 1

    def _release(self):
        process, self.process = self.process, None
        if process is not None:
            terminate = getattr(process, "terminate", None)
            if terminate is not None:
                terminate(timeout=5.0)
            else:
                process.close()

    async def stop(self):
        async with self.lock:
            task, self.task = self.task, None
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(self._release)
            self.state = "stopped"
            return self.status()
