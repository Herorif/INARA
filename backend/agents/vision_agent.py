"""
Vision Agent — gives INARA the ability to see through the camera
and describe, analyze, or watch for things in the scene.

Tools
-----
describe_camera     Describe what the current camera sees
detect_presence     Check if any person is visible
watch_for           Register a persistent watch condition
stop_watching       Remove a watch condition
list_watches        List active watch conditions
"""

import asyncio
import base64
import logging
import os
from typing import Any, Optional

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.tools import Tool, ToolParameter, ToolParameterType
from vision.vision_loop import VisionLoop

logger = logging.getLogger(__name__)


class VisionAgent(BaseAgent):
    """Provides camera-based scene understanding tools."""

    def __init__(self, event_bus: EventBus, vision_loop: VisionLoop):
        self._bus = event_bus
        self._loop = vision_loop
        self._api_key: Optional[str] = None
        self._model = "gemini-2.0-flash"

    @property
    def name(self) -> str:
        return "vision"

    @property
    def description(self) -> str:
        return "Camera vision: scene description, presence detection, and continuous monitoring"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="describe_camera",
                description=(
                    "Takes the current camera frame and describes what INARA sees. "
                    "Use when the user asks 'What do you see?' or 'Look at this'. "
                    "Optionally pass a focused question."
                ),
                parameters=[
                    ToolParameter(
                        "question",
                        ToolParameterType.STRING,
                        "Optional specific question about the scene (e.g. 'How many people are there?').",
                        required=False,
                    ),
                ],
            ),
            Tool(
                name="detect_presence",
                description=(
                    "Checks whether any person is visible in the current camera view. "
                    "Returns True/False and an approximate count if multiple people are present."
                ),
                parameters=[],
            ),
            Tool(
                name="watch_for",
                description=(
                    "Starts continuously monitoring the camera for a specific event or object. "
                    "INARA will alert the user when the condition is detected. "
                    "Examples: 'package delivery', 'person at the door', 'cat on desk'."
                ),
                parameters=[
                    ToolParameter("description", ToolParameterType.STRING, "What to watch for."),
                    ToolParameter(
                        "watch_id",
                        ToolParameterType.STRING,
                        "A short identifier for this watch (e.g. 'door', 'desk'). Used to cancel it later.",
                        required=False,
                    ),
                ],
                non_blocking=True,
            ),
            Tool(
                name="stop_watching",
                description="Stops a previously registered camera watch condition.",
                parameters=[
                    ToolParameter("watch_id", ToolParameterType.STRING, "The watch ID to remove."),
                ],
            ),
            Tool(
                name="list_watches",
                description="Lists all active camera watch conditions.",
                parameters=[],
            ),
        ]

    async def initialize(self):
        self._api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "describe_camera":
            return await self._describe_camera(args.get("question"))
        elif tool_name == "detect_presence":
            return await self._detect_presence()
        elif tool_name == "watch_for":
            return self._watch_for(args)
        elif tool_name == "stop_watching":
            return self._stop_watching(args.get("watch_id", ""))
        elif tool_name == "list_watches":
            return self._list_watches()
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _describe_camera(self, question: Optional[str]) -> AgentResult:
        frame = self._loop._frame
        if frame is None:
            return AgentResult(
                success=False,
                message="No camera frame available. Make sure the camera is enabled.",
            )

        prompt = question or "Describe what you see in this camera frame. Be concise and specific."
        try:
            description = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._call_gemini_vision(frame, prompt),
            )
            self._bus.emit_nowait(Event(
                type=Events.VISION_DESCRIPTION,
                data={"description": description},
                source=self.name,
            ))
            return AgentResult(success=True, message=description)
        except Exception as e:
            return AgentResult(success=False, message=f"Vision error: {e}")

    async def _detect_presence(self) -> AgentResult:
        frame = self._loop._frame
        if frame is None:
            return AgentResult(success=False, message="No camera frame available.")

        prompt = (
            "Is any person visible in this image? "
            "Respond with one of: "
            "'PRESENT: 1 person', 'PRESENT: N people', or 'ABSENT: no person visible'. "
            "Be brief."
        )
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._call_gemini_vision(frame, prompt),
            )
            present = result.upper().startswith("PRESENT")
            self._bus.emit_nowait(Event(
                type=Events.VISION_PRESENCE,
                data={"present": present, "result": result},
                source=self.name,
            ))
            return AgentResult(
                success=True,
                data={"present": present},
                message=result,
            )
        except Exception as e:
            return AgentResult(success=False, message=f"Presence detection error: {e}")

    def _watch_for(self, args: dict[str, Any]) -> AgentResult:
        description = args.get("description", "").strip()
        if not description:
            return AgentResult(success=False, message="Please provide a description of what to watch for.")

        watch_id = args.get("watch_id") or description.lower().replace(" ", "_")[:20]
        self._loop.add_watch(watch_id, description)
        return AgentResult(
            success=True,
            data={"watch_id": watch_id},
            message=f"Now watching for '{description}' (id: {watch_id}). I'll alert you when detected.",
        )

    def _stop_watching(self, watch_id: str) -> AgentResult:
        removed = self._loop.remove_watch(watch_id)
        if removed:
            return AgentResult(success=True, message=f"Watch '{watch_id}' removed.")
        return AgentResult(success=False, message=f"No watch found with id '{watch_id}'.")

    def _list_watches(self) -> AgentResult:
        watches = self._loop.list_watches()
        if not watches:
            return AgentResult(success=True, message="No active watch conditions.")
        lines = [f"  - [{w['id']}] {w['description']}" for w in watches]
        return AgentResult(
            success=True,
            data={"watches": watches},
            message="Active watches:\n" + "\n".join(lines),
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_gemini_vision(self, frame_bytes: bytes, prompt: str) -> str:
        from google import genai
        from google.genai import types

        api_key = self._api_key
        if not api_key:
            raise RuntimeError("No GOOGLE_API_KEY / GEMINI_API_KEY set")

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"),
                types.Part(text=prompt),
            ],
        )
        return (response.text or "").strip()
