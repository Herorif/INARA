"""Explicit desktop resource policy; heavy adapters remain on-demand."""

import asyncio
import time

from services.capability_profiles import RAM_HEADROOM_MB, WORKER_PROFILES
from typing import Literal
from pydantic import BaseModel, ConfigDict
from services.tools import ServiceError


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["resident", "chat", "studio", "gaming"]


class ResourceGovernor:
    def __init__(self, capacity=None, probe=None):
        self.capacity = dict(capacity or {"cpu": 2, "ram_mb": 8192, "vram_mb": 0})
        self.probe = probe or probe_hardware
        self.hardware = None
        self.probed_at = None
        self.reservations = {}
        self.runner = None
        self.max_jobs = 4
        self.queue_timeout = 120
        self.fault = None
        self.state = "chat"
        self.creative_lock = asyncio.Lock()

    @property
    def creative_active(self):
        return self.reservations

    def select(self, state):
        self.state = state
        return self.snapshot()

    def require_heavy(self):
        if self.fault:
            raise ServiceError("resource_fault", self.fault)
        if self.state in ("resident", "gaming"):
            raise ServiceError(
                "resource_policy", "Open Studio and leave gaming mode to use this capability."
            )
        self.state = "studio"

    def inspect_hardware(self):
        if self.probed_at is None or time.monotonic() - self.probed_at > 10:
            try:
                self.hardware = self.probe()
            except Exception:
                self.hardware = {
                    "cpu_count": None,
                    "ram_available_mb": None,
                    "ram_total_mb": None,
                    "vram_mb": None,
                }
            self.probed_at = time.monotonic()
        return self.hardware

    def check_capacity(self, profile):
        estimate = WORKER_PROFILES[profile]
        hardware = self.inspect_hardware()
        limits = dict(self.capacity)
        if hardware.get("cpu_count") is not None:
            limits["cpu"] = min(limits["cpu"], hardware["cpu_count"])
        if hardware.get("ram_available_mb") is not None:
            limits["ram_mb"] = min(
                limits["ram_mb"], max(0, hardware["ram_available_mb"] - RAM_HEADROOM_MB)
            )
        if any(estimate[key] > limits[key] for key in ("cpu", "ram_mb", "vram_mb")):
            raise ServiceError(
                "resource_capacity",
                "This fixed worker profile exceeds the resource budget or available memory. Close other work and refresh diagnostics.",
            )
        return dict(estimate)

    def check(self, profile):
        self.require_heavy()
        return self.check_capacity(profile)

    def reserve(self, key, profile):
        estimate = self.check(profile)
        if len(self.reservations) >= self.max_jobs:
            raise ServiceError(
                "worker_busy",
                "The creative queue is full (one worker and three waiting). Cancel a job or wait.",
            )
        self.reservations[key] = {"profile": profile, "estimate": estimate}
        return self.reservations[key]

    def poll(self, previous):
        now = time.monotonic()
        if now - previous > 15:
            raise ServiceError(
                "job_interrupted",
                "Work was interrupted by suspension or a long core stall. Inspect saved revisions and start a new request.",
            )
        return now

    async def acquire(self, key, cancel):
        previous = time.monotonic()
        deadline = previous + self.queue_timeout
        while True:
            previous = self.poll(previous)
            if cancel.is_set() or self.state in ("resident", "gaming"):
                raise ServiceError("job_cancelled", "Queued build cancelled.")
            if time.monotonic() > deadline:
                raise ServiceError(
                    "queue_timeout",
                    "Queue wait expired. Start a new build when resources are free.",
                )
            if self.runner is None and next(iter(self.reservations), None) == key:
                self.check(self.reservations[key]["profile"])
                self.runner = key
                return
            await asyncio.sleep(0.05)

    def release(self, key):
        self.reservations.pop(key, None)
        if self.runner == key:
            self.runner = None

    def snapshot(self):
        return {
            "state": self.state,
            "fault": self.fault,
            "budget": dict(self.capacity),
            "reservation_kind": "admission_estimates_not_hard_limits",
            "running": int(self.runner is not None),
            "waiting": max(0, len(self.reservations) - int(self.runner is not None)),
            "queue_limit": self.max_jobs,
            "reserved": {
                key: sum(
                    item["estimate"][key]
                    for reservation_key, item in self.reservations.items()
                    if reservation_key == self.runner
                )
                for key in ("cpu", "ram_mb", "vram_mb")
            },
            "heavy_allowed": self.state in ("chat", "studio") and not self.fault,
            "camera_frame_interval_ms": 500,
            "automatic_game_detection": False,
        }


def probe_hardware():
    """Cheap OS counters on demand; unsupported GPU information stays unknown."""
    import os

    result = {
        "cpu_count": os.cpu_count(),
        "ram_available_mb": None,
        "ram_total_mb": None,
        "vram_mb": None,
    }
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong)
                    for name in (
                        "total_physical",
                        "available_physical",
                        "total_page",
                        "available_page",
                        "total_virtual",
                        "available_virtual",
                        "extended",
                    )
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            probe = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
            probe.argtypes = [ctypes.POINTER(MemoryStatus)]
            probe.restype = wintypes.BOOL
            if not probe(ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            result.update(
                ram_available_mb=status.available_physical // 1048576,
                ram_total_mb=status.total_physical // 1048576,
            )
        else:
            import psutil

            memory = psutil.virtual_memory()
            result.update(
                ram_available_mb=memory.available // 1048576, ram_total_mb=memory.total // 1048576
            )
    except (ImportError, OSError):
        pass
    return result
