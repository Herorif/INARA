"""
App registry for INARA's desktop control.

Maps friendly names to launch commands. Supports built-in apps,
user-defined overrides from config, exact (case-insensitive) name or
alias matching, and optional window focusing via pywin32 (graceful
degradation). Commands never run through a shell: "start X" entries are
opened with the OS shell-execute API, everything else as an argument list.
"""

from dataclasses import dataclass
import difflib
import os
import shlex
import shutil
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


class AppResolutionError(ValueError):
    """The requested app name is unknown; ``suggestions`` lists close matches."""

    def __init__(self, message: str, suggestions: tuple[str, ...] = ()):
        super().__init__(message)
        self.suggestions = suggestions


@dataclass(frozen=True)
class LaunchTarget:
    """A resolved launch: ``open`` uses shell-execute on argv[0]; ``exec`` runs argv."""

    key: str
    kind: str
    argv: tuple[str, ...]

    def describe(self) -> str:
        if self.kind == "open":
            return f"open {self.argv[0]}"
        return subprocess.list2cmdline(list(self.argv))


def _split_command(command) -> list[str]:
    if isinstance(command, (list, tuple)):
        return [str(part) for part in command]
    parts = shlex.split(str(command), posix=sys.platform != "win32")
    # Non-POSIX shlex keeps quotes around quoted paths; strip them.
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part for part in parts]


class AppRegistry:
    """Resolves friendly app names to commands and launches them."""

    def __init__(self, custom_apps: Optional[dict] = None):
        self._apps = {**BUILTIN_APPS}
        if custom_apps:
            self._apps.update({k.lower().strip(): v for k, v in custom_apps.items()})

    # -----------------------------------------------------------------------
    # Resolution
    # -----------------------------------------------------------------------

    def resolve(self, name: str) -> Optional[str]:
        """Return the registered command for an exact (case-insensitive) name or alias."""
        return self._apps.get(name.lower().strip())

    def close_matches(self, name: str, limit: int = 5) -> list[str]:
        lower = name.lower().strip()
        found = difflib.get_close_matches(lower, self._apps, n=limit, cutoff=0.6)
        if lower:
            for key in sorted(self._apps):
                if len(found) >= limit:
                    break
                if key not in found and (key.startswith(lower) or lower in key):
                    found.append(key)
        return found

    def resolve_target(self, name: str) -> LaunchTarget:
        """Resolve a name to exactly what will run, or raise AppResolutionError."""
        key = name.lower().strip()
        command = self._apps.get(key)
        if command is None:
            suggestions = tuple(self.close_matches(name))
            hint = (
                f" Did you mean: {', '.join(suggestions)}?"
                if suggestions
                else f" Available: {', '.join(self.list_available()[:12])}..."
            )
            raise AppResolutionError(
                f"Unknown app '{name.strip()}'. Use an exact app name or alias.{hint}",
                suggestions,
            )
        argv = _split_command(command)
        if not argv:
            raise AppResolutionError(f"App '{key}' has an empty launch command.")
        if argv[0].lower() == "start":
            target = argv[1:]
            if len(target) != 1:
                raise AppResolutionError(f"App '{key}' has an unsupported start command.")
            if sys.platform == "win32":
                return LaunchTarget(key, "open", (target[0],))
            argv = target
        executable = shutil.which(argv[0]) or argv[0]
        return LaunchTarget(key, "exec", (executable, *argv[1:]))

    def list_available(self) -> list[str]:
        return sorted(self._apps.keys())

    # -----------------------------------------------------------------------
    # Launch
    # -----------------------------------------------------------------------

    def launch(self, name: str) -> dict:
        """Launch an app by exact friendly name. Returns { success, message, command }."""
        try:
            target = self.resolve_target(name)
        except AppResolutionError as e:
            return {"success": False, "message": str(e), "suggestions": list(e.suggestions)}

        try:
            if target.kind == "open":
                os.startfile(target.argv[0])  # ShellExecute; no command interpreter.
            else:
                subprocess.Popen(list(target.argv), shell=False)
            return {
                "success": True,
                "message": f"Launched '{target.key}' ({target.describe()}).",
                "command": target.describe(),
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to launch '{target.key}': {e}"}

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
