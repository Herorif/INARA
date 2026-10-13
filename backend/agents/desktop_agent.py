"""
Desktop Agent — gives INARA awareness of and control over the host machine.

Follows the BaseAgent pattern. Provides 8 LLM-callable tools:
  get_system_info, launch_app, list_running_apps, focus_window,
  take_screenshot, search_files, read_clipboard, write_clipboard
"""

import os
import sys
from pathlib import Path
from typing import Any

from agents.base import AgentResult, BaseAgent
from core.event_bus import EventBus, Event, Events
from desktop.system_monitor import SystemMonitor
from desktop.app_registry import AppRegistry
from desktop.screen_capture import ScreenCapture
from llm.tools import Tool, ToolParameter, ToolParameterType


class DesktopAgent(BaseAgent):

    def __init__(
        self,
        event_bus: EventBus,
        custom_apps: dict | None = None,
        screenshot_max_width: int = 1280,
        file_search_root: str = "~",
    ):
        self._bus = event_bus
        self._monitor = SystemMonitor()
        self._registry = AppRegistry(custom_apps=custom_apps)
        self._capture = ScreenCapture(max_width=screenshot_max_width)
        self._search_root = Path(file_search_root).expanduser()

    # -----------------------------------------------------------------------
    # BaseAgent interface
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "desktop"

    @property
    def description(self) -> str:
        return "Controls the host machine: system info, app launching, screen vision, file search, clipboard"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="get_system_info",
                description=(
                    "Returns current CPU usage, memory, disk space, battery level, "
                    "and top running processes."
                ),
                parameters=[],
            ),
            Tool(
                name="launch_app",
                description=(
                    "Opens an application by its friendly name "
                    "(e.g. 'chrome', 'vscode', 'spotify', 'discord', 'terminal')."
                ),
                parameters=[
                    ToolParameter("name", ToolParameterType.STRING, "The app to open."),
                ],
            ),
            Tool(
                name="list_running_apps",
                description="Lists the top running processes on the machine sorted by memory usage.",
                parameters=[],
            ),
            Tool(
                name="focus_window",
                description="Brings an open window to the foreground by its title or app name.",
                parameters=[
                    ToolParameter("name", ToolParameterType.STRING, "Window title or app name to focus."),
                ],
            ),
            Tool(
                name="take_screenshot",
                description=(
                    "Takes a screenshot of the current screen and uses vision AI to describe "
                    "what is visible. Use this when the user asks what's on screen, "
                    "to help debug a visual problem, or to provide context about the UI."
                ),
                parameters=[
                    ToolParameter(
                        "prompt",
                        ToolParameterType.STRING,
                        "Optional specific question about the screen (e.g. 'Is there an error message?').",
                        required=False,
                    ),
                ],
                non_blocking=False,
            ),
            Tool(
                name="search_files",
                description=(
                    "Searches for files matching a name pattern on the user's machine. "
                    "Returns up to 20 matching file paths."
                ),
                parameters=[
                    ToolParameter("query", ToolParameterType.STRING, "Filename or glob pattern (e.g. 'resume*.docx', '*.pdf')."),
                    ToolParameter(
                        "directory",
                        ToolParameterType.STRING,
                        "Directory to search in. Defaults to user home folder.",
                        required=False,
                    ),
                ],
            ),
            Tool(
                name="read_clipboard",
                description="Reads and returns the current text content of the system clipboard.",
                parameters=[],
            ),
            Tool(
                name="write_clipboard",
                description="Writes text to the system clipboard.",
                parameters=[
                    ToolParameter("text", ToolParameterType.STRING, "The text to place in the clipboard."),
                ],
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "get_system_info":
            return self._get_system_info()
        if tool_name == "launch_app":
            return self._launch_app(args)
        if tool_name == "list_running_apps":
            return self._list_running_apps()
        if tool_name == "focus_window":
            return self._focus_window(args)
        if tool_name == "take_screenshot":
            return await self._take_screenshot(args)
        if tool_name == "search_files":
            return self._search_files(args)
        if tool_name == "read_clipboard":
            return self._read_clipboard()
        if tool_name == "write_clipboard":
            return self._write_clipboard(args)
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    # -----------------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------------

    def _get_system_info(self) -> AgentResult:
        summary = self._monitor.get_summary()
        data = self._monitor.to_dict()

        self._bus.emit_nowait(Event(
            type=Events.DESKTOP_SYSTEM_INFO,
            data=data,
            source=self.name,
        ))

        return AgentResult(success=True, data=data, message=summary)

    def _launch_app(self, args: dict) -> AgentResult:
        name = args.get("name", "").strip()
        if not name:
            return AgentResult(success=False, message="No app name provided.")

        result = self._registry.launch(name)
        return AgentResult(
            success=result["success"],
            message=result["message"],
        )

    def _list_running_apps(self) -> AgentResult:
        procs = self._registry.list_running(limit=15)
        if not procs:
            return AgentResult(success=True, data={"processes": []}, message="No process data available.")

        lines = [f"  {p['name']} (PID {p['pid']}) — {p['memory_mb']} MB" for p in procs]
        msg = f"Top {len(procs)} processes by memory:\n" + "\n".join(lines)
        return AgentResult(success=True, data={"processes": procs}, message=msg)

    def _focus_window(self, args: dict) -> AgentResult:
        name = args.get("name", "").strip()
        if not name:
            return AgentResult(success=False, message="No window name provided.")

        ok = self._registry.focus_window(name)
        if ok:
            return AgentResult(success=True, message=f"Focused window matching '{name}'.")
        return AgentResult(
            success=False,
            message=f"Could not focus '{name}'. Window may not be open or pywin32 is not installed.",
        )

    async def _take_screenshot(self, args: dict) -> AgentResult:
        prompt = args.get("prompt") or None
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # Run the blocking Gemini call off the event loop
            description = await loop.run_in_executor(
                None,
                lambda: self._capture.capture_and_describe(prompt=prompt),
            )
            b64 = await loop.run_in_executor(None, self._capture.capture_to_base64)

            self._bus.emit_nowait(Event(
                type=Events.DESKTOP_SCREENSHOT,
                data={"image": b64},
                source=self.name,
            ))

            return AgentResult(
                success=True,
                data={"description": description, "image": b64},
                message=description,
            )
        except Exception as e:
            return AgentResult(success=False, message=f"Screenshot failed: {e}")

    def _search_files(self, args: dict) -> AgentResult:
        query = args.get("query", "").strip()
        directory = args.get("directory")

        if not query:
            return AgentResult(success=False, message="No search query provided.")

        search_dir = Path(directory).expanduser() if directory else self._search_root

        if not search_dir.exists():
            return AgentResult(success=False, message=f"Directory not found: {search_dir}")

        # Add glob wildcard if not already present
        pattern = query if any(c in query for c in "*?[") else f"*{query}*"

        try:
            matches = []
            # Limit depth to avoid scanning the entire filesystem
            for depth in range(5):
                glob_pattern = "/".join(["*"] * depth) + ("/" if depth > 0 else "") + pattern
                for p in search_dir.glob(glob_pattern):
                    if p.is_file():
                        matches.append(str(p))
                    if len(matches) >= 20:
                        break
                if len(matches) >= 20:
                    break

            if not matches:
                return AgentResult(
                    success=True,
                    data={"files": []},
                    message=f"No files matching '{query}' found in {search_dir}.",
                )

            msg = f"Found {len(matches)} file(s) matching '{query}':\n" + "\n".join(f"  {f}" for f in matches)
            return AgentResult(success=True, data={"files": matches}, message=msg)

        except Exception as e:
            return AgentResult(success=False, message=f"Search failed: {e}")

    def _read_clipboard(self) -> AgentResult:
        try:
            import pyperclip
            text = pyperclip.paste()
            if not text:
                return AgentResult(success=True, data={"text": ""}, message="Clipboard is empty.")
            preview = text[:500] + ("..." if len(text) > 500 else "")
            return AgentResult(
                success=True,
                data={"text": text},
                message=f"Clipboard contents ({len(text)} chars):\n{preview}",
            )
        except ImportError:
            return AgentResult(success=False, message="pyperclip is not installed. Run: pip install pyperclip")
        except Exception as e:
            return AgentResult(success=False, message=f"Could not read clipboard: {e}")

    def _write_clipboard(self, args: dict) -> AgentResult:
        text = args.get("text", "")
        try:
            import pyperclip
            pyperclip.copy(text)
            preview = text[:100] + ("..." if len(text) > 100 else "")
            return AgentResult(
                success=True,
                data={"text": text},
                message=f"Copied to clipboard: {preview}",
            )
        except ImportError:
            return AgentResult(success=False, message="pyperclip is not installed. Run: pip install pyperclip")
        except Exception as e:
            return AgentResult(success=False, message=f"Could not write clipboard: {e}")
