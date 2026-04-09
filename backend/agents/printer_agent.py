"""
Printer Agent  - wraps the existing PrinterAgent with the BaseAgent interface.

The underlying printer_agent.py is well-structured and LLM-independent.
This wrapper registers its tools and routes tool calls.
"""

import sys
import os
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.tools import Tool, ToolParameter, ToolParameterType

from printer_agent import PrinterAgent as _PrinterAgent


class PrinterControlAgent(BaseAgent):
    """INARA agent wrapper around the 3D printer controller."""

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus
        self._printer = _PrinterAgent()

    @property
    def name(self) -> str:
        return "printer"

    @property
    def description(self) -> str:
        return "Discovers, slices, and prints to 3D printers (OctoPrint, Moonraker, PrusaLink)"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="discover_printers",
                description="Discovers 3D printers available on the local network.",
                parameters=[],
            ),
            Tool(
                name="print_stl",
                description="Prints an STL file to a 3D printer. Handles slicing and uploading.",
                parameters=[
                    ToolParameter("stl_path", ToolParameterType.STRING, "Path to STL file, or 'current' for most recent."),
                    ToolParameter("printer", ToolParameterType.STRING, "Printer name or IP."),
                    ToolParameter("profile", ToolParameterType.STRING, "Optional slicer profile.", required=False),
                ],
            ),
            Tool(
                name="get_print_status",
                description="Gets the current status of a 3D printer.",
                parameters=[
                    ToolParameter("printer", ToolParameterType.STRING, "Printer name or IP."),
                ],
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "discover_printers":
            return await self._discover()
        elif tool_name == "print_stl":
            return await self._print_stl(args, context)
        elif tool_name == "get_print_status":
            return await self._get_status(args)
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    async def _discover(self) -> AgentResult:
        printers = await self._printer.discover_printers()
        printer_list = []
        for p in printers:
            printer_list.append({
                "name": p.get("name", "unknown"),
                "ip": p.get("ip", p.get("host", "")),
                "type": p.get("type", "unknown"),
                "has_camera": p.get("camera_url") is not None,
            })
        self._bus.emit_nowait(Event(
            type=Events.PRINTER_LIST,
            data={"printers": printer_list},
            source=self.name,
        ))
        summaries = [f"  - {p['name']} ({p['ip']}) [{p['type']}]" for p in printer_list]
        return AgentResult(
            success=True,
            data={"printers": printer_list},
            message=f"Found {len(printer_list)} printers:\n" + "\n".join(summaries),
        )

    async def _print_stl(self, args: dict[str, Any], context: dict) -> AgentResult:
        stl_path = args.get("stl_path", "")
        printer_name = args.get("printer", "")
        profile = args.get("profile")

        # Resolve 'current' to the latest CAD output
        if stl_path == "current":
            stl_path = context.get("latest_stl_path", "")
            if not stl_path:
                return AgentResult(success=False, message="No current CAD model available.")

        try:
            result = await self._printer.print_stl(
                stl_path=stl_path,
                printer_name=printer_name,
                profile_name=profile,
            )
            return AgentResult(success=True, message=str(result))
        except Exception as e:
            return AgentResult(success=False, message=f"Print failed: {e}")

    async def _get_status(self, args: dict[str, Any]) -> AgentResult:
        printer_name = args.get("printer", "")
        try:
            status = await self._printer.get_print_status(printer_name)
            if status:
                status_data = {
                    "state": status.state,
                    "progress": status.progress,
                    "time_remaining": status.time_remaining,
                }
                self._bus.emit_nowait(Event(
                    type=Events.PRINTER_STATUS,
                    data=status_data,
                    source=self.name,
                ))
                return AgentResult(
                    success=True,
                    data=status_data,
                    message=f"Printer '{printer_name}': {status.state}, {status.progress}% done",
                )
            return AgentResult(success=False, message=f"Could not get status for '{printer_name}'")
        except Exception as e:
            return AgentResult(success=False, message=f"Status check failed: {e}")

    @property
    def inner(self) -> _PrinterAgent:
        """Direct access to the underlying PrinterAgent."""
        return self._printer
