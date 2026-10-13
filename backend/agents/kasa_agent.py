"""
Kasa Smart Home Agent  - wraps the existing KasaAgent with the BaseAgent interface.

The underlying kasa_agent.py is clean and LLM-independent.
This wrapper registers its tools and routes tool calls.
"""

import sys
import os
from typing import Any

# Allow imports from parent backend/ dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.tools import Tool, ToolParameter, ToolParameterType

# Import the original (unchanged) KasaAgent
from kasa_agent import KasaAgent as _KasaAgent


class KasaSmartHomeAgent(BaseAgent):
    """INARA agent wrapper around the Kasa smart home controller."""

    def __init__(self, event_bus: EventBus, known_devices: list | None = None):
        self._bus = event_bus
        self._kasa = _KasaAgent(known_devices=known_devices)

    @property
    def name(self) -> str:
        return "kasa"

    @property
    def description(self) -> str:
        return "Controls TP-Link Kasa smart home devices (lights, plugs, switches)"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="list_smart_devices",
                description="Lists all available smart home devices on the network.",
                parameters=[],
            ),
            Tool(
                name="control_light",
                description="Controls a smart light device.",
                parameters=[
                    ToolParameter("target", ToolParameterType.STRING, "Device IP or alias."),
                    ToolParameter("action", ToolParameterType.STRING, "Action: 'turn_on', 'turn_off', or 'set'."),
                    ToolParameter("brightness", ToolParameterType.INTEGER, "Brightness 0-100.", required=False),
                    ToolParameter("color", ToolParameterType.STRING, "Color name or 'warm'.", required=False),
                ],
            ),
        ]

    async def initialize(self):
        await self._kasa.initialize()

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "list_smart_devices":
            return await self._list_devices()
        elif tool_name == "control_light":
            return await self._control_light(args)
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    async def _list_devices(self) -> AgentResult:
        device_list = await self._kasa.discover_devices()
        self._bus.emit_nowait(Event(
            type=Events.KASA_DEVICES,
            data={"devices": device_list},
            source=self.name,
        ))

        # Build summary for LLM
        summaries = []
        for d in device_list:
            state = "ON" if d["is_on"] else "OFF"
            summaries.append(f"  - {d['alias']} ({d['ip']}) [{d['type']}] {state}")

        return AgentResult(
            success=True,
            data={"devices": device_list},
            message=f"Found {len(device_list)} devices:\n" + "\n".join(summaries),
        )

    async def _control_light(self, args: dict[str, Any]) -> AgentResult:
        target = args.get("target", "")
        action = args.get("action", "")
        brightness = args.get("brightness")
        color = args.get("color")

        result_parts = []

        if action == "turn_on":
            ok = await self._kasa.turn_on(target)
            result_parts.append(f"Turn on: {'OK' if ok else 'FAILED'}")
        elif action == "turn_off":
            ok = await self._kasa.turn_off(target)
            result_parts.append(f"Turn off: {'OK' if ok else 'FAILED'}")
        elif action == "set":
            if brightness is not None:
                ok = await self._kasa.set_brightness(target, brightness)
                result_parts.append(f"Brightness {brightness}%: {'OK' if ok else 'FAILED'}")
            if color is not None:
                ok = await self._kasa.set_color(target, color)
                result_parts.append(f"Color '{color}': {'OK' if ok else 'FAILED'}")
        else:
            return AgentResult(success=False, message=f"Unknown action: {action}")

        msg = f"Control {target}: " + ", ".join(result_parts)
        self._bus.emit_nowait(Event(
            type=Events.KASA_CONTROL_RESULT,
            data={"target": target, "action": action, "results": result_parts},
            source=self.name,
        ))
        return AgentResult(success=True, message=msg)

    @property
    def inner(self) -> _KasaAgent:
        """Direct access to the underlying KasaAgent for advanced usage."""
        return self._kasa
