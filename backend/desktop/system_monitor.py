"""
System resource monitor for INARA.

Provides real-time CPU, memory, disk, battery, and process telemetry
via psutil. All methods are synchronous and stateless — safe to call
from any async context via run_in_executor if needed.
"""

from typing import Optional


def _psutil():
    import psutil
    return psutil


class SystemMonitor:

    def get_cpu(self) -> dict:
        ps = _psutil()
        freq = ps.cpu_freq()
        return {
            "percent":  ps.cpu_percent(interval=0.2),
            "cores":    ps.cpu_count(logical=False),
            "threads":  ps.cpu_count(logical=True),
            "freq_mhz": round(freq.current) if freq else None,
        }

    def get_memory(self) -> dict:
        ps = _psutil()
        vm = ps.virtual_memory()
        return {
            "total_gb": round(vm.total / 1e9, 1),
            "used_gb":  round(vm.used  / 1e9, 1),
            "free_gb":  round(vm.available / 1e9, 1),
            "percent":  vm.percent,
        }

    def get_disk(self) -> list[dict]:
        ps = _psutil()
        results = []
        for part in ps.disk_partitions(all=False):
            try:
                usage = ps.disk_usage(part.mountpoint)
            except PermissionError:
                continue
            results.append({
                "mount":    part.mountpoint,
                "total_gb": round(usage.total / 1e9, 1),
                "used_gb":  round(usage.used  / 1e9, 1),
                "free_gb":  round(usage.free  / 1e9, 1),
                "percent":  usage.percent,
            })
        return results

    def get_battery(self) -> Optional[dict]:
        ps = _psutil()
        bat = ps.sensors_battery()
        if bat is None:
            return None
        time_left = None
        if bat.secsleft not in (ps.POWER_TIME_UNKNOWN, ps.POWER_TIME_UNLIMITED):
            time_left = round(bat.secsleft / 60)
        return {
            "percent":      round(bat.percent),
            "plugged_in":   bat.power_plugged,
            "time_left_min": time_left,
        }

    def get_processes(self, limit: int = 10) -> list[dict]:
        ps = _psutil()
        procs = []
        for proc in ps.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
            try:
                info = proc.info
                procs.append({
                    "pid":        info["pid"],
                    "name":       info["name"],
                    "memory_mb":  round((info["memory_info"].rss if info["memory_info"] else 0) / 1e6, 1),
                    "cpu_percent": info["cpu_percent"] or 0.0,
                })
            except (ps.NoSuchProcess, ps.AccessDenied):
                continue
        # Sort by memory descending
        procs.sort(key=lambda p: p["memory_mb"], reverse=True)
        return procs[:limit]

    def get_summary(self) -> str:
        """Return a single human-readable summary string for the LLM."""
        lines = []

        try:
            cpu = self.get_cpu()
            lines.append(
                f"CPU: {cpu['percent']}% ({cpu['cores']} cores"
                + (f" @ {cpu['freq_mhz']} MHz" if cpu['freq_mhz'] else "")
                + ")"
            )
        except Exception as e:
            lines.append(f"CPU: unavailable ({e})")

        try:
            mem = self.get_memory()
            lines.append(
                f"Memory: {mem['used_gb']} / {mem['total_gb']} GB ({mem['percent']}%)"
            )
        except Exception as e:
            lines.append(f"Memory: unavailable ({e})")

        try:
            for disk in self.get_disk():
                lines.append(
                    f"Disk {disk['mount']}: {disk['used_gb']} / {disk['total_gb']} GB ({disk['percent']}%)"
                )
        except Exception as e:
            lines.append(f"Disk: unavailable ({e})")

        try:
            bat = self.get_battery()
            if bat:
                status = "plugged in" if bat["plugged_in"] else "on battery"
                time_str = f", ~{bat['time_left_min']}m remaining" if bat["time_left_min"] else ""
                lines.append(f"Battery: {bat['percent']}% ({status}{time_str})")
        except Exception:
            pass

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return all stats as a serialisable dict for the frontend."""
        return {
            "cpu":       self._safe(self.get_cpu),
            "memory":    self._safe(self.get_memory),
            "disk":      self._safe(self.get_disk, default=[]),
            "battery":   self._safe(self.get_battery),
            "processes": self._safe(lambda: self.get_processes(10), default=[]),
        }

    @staticmethod
    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default
