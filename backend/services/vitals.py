"""PC vitals for the Systems rail (S13a.5, docs/SYSTEMS_RAIL.md).

A renderer that shows the rail sends ``vitals_watch {on: true}``; while at least one owner
renderer watches, this service samples the PC with ``psutil`` every 2 s (every 5 s on low
battery) and emits ``vitals`` to each watching renderer::

    {t, cpu, mem: {used, total}, disk: {used, total}, net: {up, down},
     battery?: {percent, plugged}, gpu?: {percent}}

``t`` is epoch seconds, ``cpu`` and ``battery.percent`` are percentages, ``mem`` and
``disk`` are bytes (the system drive), ``net`` is bytes per second since the previous
sample. ``battery`` is left out on a PC without one; ``gpu`` only appears when
``nvidia-ml-py`` (module ``pynvml``) is importable, and it is never installed for this.

Nobody watching: no loop, no sampling. Gaming mode: the loop keeps its watchers but takes
no samples until gaming ends. Low battery: a watcher's ``low_battery`` hint (the renderer's
Battery API) or this PC discharging at 20% or less slows sampling to every 5 s; the core
decides. Everything stays on this PC; nothing here logs a value.
"""

import asyncio
import importlib
import os
import sys
import time

from services.log import get_logger

logger = get_logger(__name__)

INTERVAL = 2.0
LOW_BATTERY_INTERVAL = 5.0
LOW_BATTERY_PERCENT = 20


def system_drive():
    """The drive Windows runs from (``C:\\``), or ``/`` elsewhere."""
    if sys.platform == "win32":
        return (os.environ.get("SystemDrive") or "C:").rstrip("\\") + "\\"
    return "/"


def load_gpu():
    """A () -> percent reader from NVML, or None when ``pynvml`` is missing or fails."""
    try:
        nvml = importlib.import_module("pynvml")
    except ImportError:
        return None
    try:
        nvml.nvmlInit()
        handle = nvml.nvmlDeviceGetHandleByIndex(0)
    except Exception as exc:
        logger.info("GPU vitals unavailable (%s)", type(exc).__name__)
        return None
    return lambda: float(nvml.nvmlDeviceGetUtilizationRates(handle).gpu)


def _load_psutil():
    import psutil

    return psutil


class VitalsService:
    """Owned by the composition root (application.py)."""

    def __init__(self, app, *, psutil=None, gpu=..., clock=time.time, monotonic=time.monotonic,
                 sleep=asyncio.sleep, drive=None):
        self.app = app
        self._psutil = psutil
        self._gpu = gpu  # ... = load on first sample; None = no GPU
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.drive = drive or system_drive()
        self.watchers = {}  # sid -> {"low_battery": bool}
        self.task = None
        self._net = None  # (monotonic, sent, received) of the previous sample
        self._battery_low = False

    # --- state ---------------------------------------------------------------------------
    @property
    def psutil(self):
        if self._psutil is None:
            self._psutil = _load_psutil()
        return self._psutil

    def gaming(self):
        return getattr(getattr(self.app, "resources", None), "state", None) == "gaming"

    def interval(self):
        low = self._battery_low or any(item["low_battery"] for item in self.watchers.values())
        return LOW_BATTERY_INTERVAL if low else INTERVAL

    def status(self, sid):
        return {
            "ok": True,
            "watching": sid in self.watchers,
            "paused": self.gaming(),
            "interval": self.interval(),
        }

    # --- watchers ------------------------------------------------------------------------
    def watch(self, sid, on, low_battery=False):
        """Start or stop one renderer's watch; the loop runs while anyone watches."""
        if on:
            self.watchers[sid] = {"low_battery": bool(low_battery)}
            if self.task is None or self.task.done():
                self._net = None
                self.task = asyncio.create_task(self._run(), name="vitals")
        else:
            self.watchers.pop(sid, None)
            self._stop_if_idle()
        return self.status(sid)

    def stop_sid(self, sid=None):
        """Disconnect cleanup (one socket), or every watcher when ``sid`` is None."""
        if sid is None:
            self.watchers.clear()
        else:
            self.watchers.pop(sid, None)
        self._stop_if_idle()

    def _stop_if_idle(self):
        if self.watchers:
            return
        task = self.task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            self.task = None  # a new watch starts a fresh loop
        self._net = None

    async def close(self):
        self.watchers.clear()
        task, self.task = self.task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # --- sampling ------------------------------------------------------------------------
    def prime(self):
        """Start the CPU and network counters so the first sample has real rates."""
        ps = self.psutil
        ps.cpu_percent(interval=None)
        counters = ps.net_io_counters()
        self._net = (self.monotonic(), counters.bytes_sent, counters.bytes_recv)

    def sample(self):
        """One ``vitals`` payload (blocking psutil calls; run off the event loop)."""
        ps = self.psutil
        memory = ps.virtual_memory()
        disk = ps.disk_usage(self.drive)
        counters = ps.net_io_counters()
        now = self.monotonic()
        up = down = 0.0
        if self._net is not None:
            elapsed = now - self._net[0]
            if elapsed > 0:
                up = max(0.0, (counters.bytes_sent - self._net[1]) / elapsed)
                down = max(0.0, (counters.bytes_recv - self._net[2]) / elapsed)
        self._net = (now, counters.bytes_sent, counters.bytes_recv)
        payload = {
            "t": round(self.clock(), 3),
            "cpu": round(float(ps.cpu_percent(interval=None)), 1),
            "mem": {"used": int(memory.used), "total": int(memory.total)},
            "disk": {"used": int(disk.used), "total": int(disk.total)},
            "net": {"up": round(up), "down": round(down)},
        }
        battery = self._battery()
        if battery is not None:
            payload["battery"] = battery
        gpu = self._gpu_percent()
        if gpu is not None:
            payload["gpu"] = {"percent": gpu}
        return payload

    def _battery(self):
        reader = getattr(self.psutil, "sensors_battery", None)
        try:
            battery = reader() if reader is not None else None
        except Exception:
            battery = None
        if battery is None or battery.percent is None:
            self._battery_low = False
            return None
        percent = round(float(battery.percent), 1)
        plugged = battery.power_plugged
        plugged = None if plugged is None else bool(plugged)
        self._battery_low = plugged is False and percent <= LOW_BATTERY_PERCENT
        return {"percent": percent, "plugged": plugged}

    def _gpu_percent(self):
        if self._gpu is ...:
            self._gpu = load_gpu()
        if self._gpu is None:
            return None
        try:
            return round(float(self._gpu()), 1)
        except Exception:
            self._gpu = None  # stop asking a GPU that failed once
            return None

    # --- the loop ------------------------------------------------------------------------
    def _rooms(self):
        """Watching sids still connected as the unlocked owner; gone sockets are dropped."""
        sessions = self.app.sessions
        rooms = []
        for sid in tuple(self.watchers):
            principal = sessions.principals.get(sid)
            if principal is None or sessions.roles.get(sid) != "renderer" \
                    or not sessions.is_owner(principal):
                self.watchers.pop(sid, None)
                continue
            if sessions.authenticated(principal):
                rooms.append(sid)
        return rooms

    async def _run(self):
        primed = False
        try:
            while self.watchers:
                if self.gaming():
                    primed = False  # no sampling; rates restart after gaming
                    self._net = None
                    await self.sleep(self.interval())
                    continue
                if not primed:
                    try:
                        await asyncio.to_thread(self.prime)
                    except Exception as exc:
                        logger.warning("Vitals counters could not start (%s)", type(exc).__name__)
                    primed = True
                await self.sleep(self.interval())
                if not self.watchers or self.gaming():
                    continue
                rooms = self._rooms()
                if not rooms:
                    continue
                try:
                    payload = await asyncio.to_thread(self.sample)
                except Exception as exc:
                    logger.warning("A vitals sample failed (%s)", type(exc).__name__)
                    continue
                for room in rooms:
                    try:
                        await self.app.sio.emit("vitals", payload, room=room)
                    except Exception:
                        logger.warning("Vitals could not be delivered")
        finally:
            if self.task is asyncio.current_task():
                self.task = None
