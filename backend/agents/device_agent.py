"""
Device Agent — unified smart home control.

Combines TP-Link Kasa devices (via KasaSmartHomeAgent) with
Home Assistant entities (via HomeAssistantBridge) behind a single
set of tools.  The LLM calls list_all_devices / control_device and
never has to know which protocol a device uses.
"""

import logging
from typing import Any, Optional

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.tools import Tool, ToolParameter, ToolParameterType

logger = logging.getLogger(__name__)


class DeviceAgent(BaseAgent):
    """Unified smart-home control across Kasa and Home Assistant."""

    def __init__(
        self,
        event_bus: EventBus,
        kasa_agent=None,           # KasaSmartHomeAgent instance (optional)
        ha_bridge=None,            # HomeAssistantBridge instance (optional)
    ):
        self._bus = event_bus
        self._kasa = kasa_agent
        self._ha = ha_bridge

    @property
    def name(self) -> str:
        return "device"

    @property
    def description(self) -> str:
        return "Unified smart home device control (Kasa + Home Assistant)"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="list_all_devices",
                description=(
                    "Lists all smart home devices across all connected protocols "
                    "(TP-Link Kasa and Home Assistant). Use this before controlling a device "
                    "to get the correct device ID."
                ),
                parameters=[],
            ),
            Tool(
                name="control_device",
                description=(
                    "Controls a smart home device by ID. "
                    "Actions: 'turn_on', 'turn_off', 'toggle', 'set'. "
                    "For 'set', pass brightness (0-100) and/or color (name or 'warm')."
                ),
                parameters=[
                    ToolParameter("device_id", ToolParameterType.STRING, "Device ID or IP from list_all_devices."),
                    ToolParameter("action", ToolParameterType.STRING, "Action: 'turn_on', 'turn_off', 'toggle', or 'set'."),
                    ToolParameter("brightness", ToolParameterType.INTEGER, "Brightness 0-100 (optional, for lights).", required=False),
                    ToolParameter("color", ToolParameterType.STRING, "Color name or 'warm' (optional, for lights).", required=False),
                    ToolParameter("temperature", ToolParameterType.NUMBER, "Target temperature for climate devices.", required=False),
                ],
            ),
            Tool(
                name="get_device_state",
                description="Returns the current state and attributes of a specific device.",
                parameters=[
                    ToolParameter("device_id", ToolParameterType.STRING, "Device ID or IP."),
                ],
            ),
        ]

    async def initialize(self):
        # Kasa is initialized by server.py — don't double-init here.
        if self._ha:
            reachable = await self._ha.ping()
            if reachable:
                logger.info("[DeviceAgent] Home Assistant connected.")
            else:
                logger.warning("[DeviceAgent] Home Assistant unreachable — HA tools will be unavailable.")

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "list_all_devices":
            return await self._list_all_devices()
        elif tool_name == "control_device":
            return await self._control_device(args)
        elif tool_name == "get_device_state":
            return await self._get_device_state(args.get("device_id", ""))
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _list_all_devices(self) -> AgentResult:
        all_devices: list[dict] = []

        # Kasa devices — read from live KasaAgent's .devices dict
        if self._kasa and hasattr(self._kasa, "devices"):
            for ip, dev in self._kasa.devices.items():
                dev_type = "unknown"
                if   getattr(dev, "is_bulb",   False): dev_type = "bulb"
                elif getattr(dev, "is_plug",   False): dev_type = "plug"
                elif getattr(dev, "is_strip",  False): dev_type = "strip"
                elif getattr(dev, "is_dimmer", False): dev_type = "dimmer"
                all_devices.append({
                    "id":     ip,
                    "name":   getattr(dev, "alias", ip),
                    "state":  "on" if getattr(dev, "is_on", False) else "off",
                    "source": "kasa",
                    "type":   dev_type,
                })

        # Home Assistant devices
        if self._ha:
            try:
                ha_devices = await self._ha.list_devices()
                all_devices.extend(ha_devices)
            except Exception as e:
                logger.warning(f"[DeviceAgent] HA list failed: {e}")

        # Always emit (even empty) so the frontend can clear stale state.
        self._bus.emit_nowait(Event(
            type=Events.DEVICE_LIST,
            data={"devices": all_devices},
            source=self.name,
        ))

        if not all_devices:
            return AgentResult(
                success=True,
                data={"devices": []},
                message="No devices found. Make sure Kasa or Home Assistant is configured.",
            )

        lines = [f"  - [{d['source']}] {d['name']} ({d['id']}) — {d['state']}" for d in all_devices]
        return AgentResult(
            success=True,
            data={"devices": all_devices},
            message=f"Found {len(all_devices)} devices:\n" + "\n".join(lines),
        )

    async def _control_device(self, args: dict[str, Any]) -> AgentResult:
        device_id = args.get("device_id", "").strip()
        action = args.get("action", "").strip()
        brightness = args.get("brightness")
        color = args.get("color")
        temperature = args.get("temperature")

        if not device_id:
            return AgentResult(success=False, message="device_id is required.")
        if not action:
            return AgentResult(success=False, message="action is required.")

        # HA entity IDs contain a dot (e.g. "light.office"); IPs do not
        if self._ha and "." in device_id and not self._is_ip(device_id):
            return await self._control_ha(device_id, action, brightness, color, temperature)
        elif self._kasa:
            return await self._control_kasa(device_id, action, brightness, color)

        return AgentResult(success=False, message="No device protocol available for this device.")

    async def _control_ha(
        self,
        entity_id: str,
        action: str,
        brightness: Optional[int],
        color: Optional[str],
        temperature: Optional[float],
    ) -> AgentResult:
        try:
            kwargs: dict[str, Any] = {}
            if brightness is not None:
                # HA uses 0-255 for brightness
                kwargs["brightness"] = max(0, min(255, int(brightness * 2.55)))
            if temperature is not None:
                kwargs["temperature"] = temperature

            if action == "turn_on":
                ok = await self._ha.turn_on(entity_id, **kwargs)
            elif action == "turn_off":
                ok = await self._ha.turn_off(entity_id)
            elif action == "toggle":
                ok = await self._ha.toggle(entity_id)
            elif action == "set":
                ok = await self._ha.turn_on(entity_id, **kwargs)
            else:
                return AgentResult(success=False, message=f"Unknown action: {action}")

            msg = f"{action} {entity_id}: {'OK' if ok else 'FAILED'}"
            self._bus.emit_nowait(Event(
                type=Events.DEVICE_CONTROL,
                data={"device_id": entity_id, "action": action, "success": ok},
                source=self.name,
            ))
            return AgentResult(success=ok, message=msg)
        except Exception as e:
            return AgentResult(success=False, message=f"HA control error: {e}")

    async def _control_kasa(
        self,
        device_id: str,
        action: str,
        brightness: Optional[int],
        color: Optional[str],
    ) -> AgentResult:
        ok = False
        msg = f"Action '{action}' on '{device_id}' failed."

        if action == "turn_on":
            ok = await self._kasa.turn_on(device_id)
            if ok: msg = f"Turned ON '{device_id}'."
        elif action == "turn_off":
            ok = await self._kasa.turn_off(device_id)
            if ok: msg = f"Turned OFF '{device_id}'."
        elif action == "toggle":
            dev = self._kasa.devices.get(device_id)
            if dev:
                ok = await (self._kasa.turn_off if dev.is_on else self._kasa.turn_on)(device_id)
                if ok: msg = f"Toggled '{device_id}'."
        elif action == "set":
            ok = True
            msg = f"Updated '{device_id}'."

        if ok and brightness is not None:
            await self._kasa.set_brightness(device_id, brightness)
        if ok and color is not None:
            await self._kasa.set_color(device_id, color)

        self._bus.emit_nowait(Event(
            type=Events.DEVICE_CONTROL,
            data={"device_id": device_id, "action": action, "success": ok,
                  "state": "on" if action == "turn_on" else "off" if action == "turn_off" else None},
            source=self.name,
        ))
        return AgentResult(success=ok, message=msg)

    async def _get_device_state(self, device_id: str) -> AgentResult:
        if not device_id:
            return AgentResult(success=False, message="device_id is required.")

        if self._ha and "." in device_id and not self._is_ip(device_id):
            try:
                state = await self._ha.get_state(device_id)
                attrs = state.get("attributes", {})
                return AgentResult(
                    success=True,
                    data=state,
                    message=(
                        f"{device_id}: {state.get('state', 'unknown')} "
                        f"(name: {attrs.get('friendly_name', device_id)})"
                    ),
                )
            except Exception as e:
                return AgentResult(success=False, message=f"HA state error: {e}")

        # Kasa: look up directly in cached devices
        if self._kasa and hasattr(self._kasa, "devices"):
            dev = self._kasa.devices.get(device_id)
            if dev:
                return AgentResult(
                    success=True,
                    data={"ip": device_id, "alias": dev.alias, "is_on": dev.is_on},
                    message=f"{dev.alias} ({device_id}): {'ON' if dev.is_on else 'OFF'}",
                )

        return AgentResult(success=False, message=f"Device '{device_id}' not found.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ip(s: str) -> bool:
        parts = s.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
