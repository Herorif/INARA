"""
App registry for INARA's desktop control.

Maps friendly names to launch commands. Supports built-in apps,
user-defined overrides from config, fuzzy name matching, and
optional window focusing via pywin32 (graceful degradation).
"""

import os
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Built-in app map — Windows-centric
# ---------------------------------------------------------------------------

BUILTIN_APPS: dict[str, str] = {
    # Browsers
    "chrome":       "start chrome",
    "firefox":      "start firefox",
    "edge":         "start msedge",

    # Dev tools
    "vscode":       "code",
    "vs code":      "code",
    "terminal":     "wt",
    "cmd":          "start cmd",
    "powershell":   "start powershell",

    # Productivity
    "notepad":      "notepad",
    "wordpad":      "wordpad",
    "excel":        "start excel",
    "word":         "start winword",
    "outlook":      "start outlook",
    "teams":        "start teams",

    # System
    "explorer":     "explorer",
    "calculator":   "calc",
    "paint":        "mspaint",
    "taskmanager":  "taskmgr",
    "settings":     "start ms-settings:",
    "control":      "control",

    # Communication & media
    "discord":      "start discord:",
    "spotify":      "start spotify:",
    "slack":        "start slack:",
    "zoom":         "start zoommtg:",
    "telegram":     "start tg:",
    "vlc":          "start vlc",
    "obs":          "start obs64",

    # Windows-specific
    "snipping tool": "snippingtool",
    "snip":          "snippingtool",
    "whiteboard":    "start whiteboard:",
}


class AppRegistry:
    """Resolves friendly app names to commands and launches them."""

    def __init__(self, custom_apps: Optional[dict] = None):
        self._apps = {**BUILTIN_APPS}
        if custom_apps:
            self._apps.update({k.lower(): v for k, v in custom_apps.items()})

    # -----------------------------------------------------------------------
    # Resolution
    # -----------------------------------------------------------------------

    def resolve(self, name: str) -> Optional[str]:
        """
        Find a command for the given app name.

        Matching order:
          1. Exact match (case-insensitive)
          2. Name is a prefix of a known key
          3. Any known key contains the name as a substring
        """
        lower = name.lower().strip()

        # Exact
        if lower in self._apps:
            return self._apps[lower]

        # Prefix match
        for key, cmd in self._apps.items():
            if key.startswith(lower):
                return cmd

        # Substring match
        for key, cmd in self._apps.items():
            if lower in key:
                return cmd

        return None

    def list_available(self) -> list[str]:
        return sorted(self._apps.keys())

    # -----------------------------------------------------------------------
    # Launch
    # -----------------------------------------------------------------------

    def launch(self, name: str) -> dict:
        """Launch an app by friendly name. Returns { success, message }."""
        cmd = self.resolve(name)
        if not cmd:
            return {
                "success": False,
                "message": f"Unknown app '{name}'. Available: {', '.join(self.list_available()[:12])}...",
            }

        try:
            if sys.platform == "win32":
                subprocess.Popen(cmd, shell=True)
            else:
                subprocess.Popen(cmd.replace("start ", "").split(), shell=False)
            return {"success": True, "message": f"Launched '{name}'."}
        except Exception as e:
            return {"success": False, "message": f"Failed to launch '{name}': {e}"}

    # -----------------------------------------------------------------------
    # Running processes
    # -----------------------------------------------------------------------

    def list_running(self, limit: int = 15) -> list[dict]:
        """Return top running processes sorted by memory."""
        try:
            import psutil
            procs = []
            for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
                try:
                    info = proc.info
                    mem = (info["memory_info"].rss if info["memory_info"] else 0) / 1e6
                    procs.append({
                        "pid":        info["pid"],
                        "name":       info["name"],
                        "memory_mb":  round(mem, 1),
                        "cpu_percent": info["cpu_percent"] or 0.0,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            procs.sort(key=lambda p: p["memory_mb"], reverse=True)
            return procs[:limit]
        except ImportError:
            return []

    # -----------------------------------------------------------------------
    # Window focus
    # -----------------------------------------------------------------------

    def focus_window(self, name: str) -> bool:
        """
        Bring the first window whose title contains 'name' to the foreground.
        Requires pywin32. Returns False silently if not available.
        """
        if sys.platform != "win32":
            return False
        try:
            import win32gui
            import win32con

            lower = name.lower()
            target_hwnd = None

            def _enum(hwnd, _):
                nonlocal target_hwnd
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if lower in title:
                        target_hwnd = hwnd

            win32gui.EnumWindows(_enum, None)

            if target_hwnd:
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(target_hwnd)
                return True
        except Exception:
            pass
        return False
