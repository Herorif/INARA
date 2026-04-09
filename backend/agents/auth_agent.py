"""
Face Authentication Agent  - wraps the existing FaceAuthenticator.

Fixes the macOS-only CAP_AVFOUNDATION bug by using platform-appropriate backend.
"""

import platform
import sys
import os
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.tools import Tool


class AuthAgent(BaseAgent):
    """INARA agent for face-based authentication."""

    def __init__(self, event_bus: EventBus, reference_image_path: str = "reference.jpg"):
        self._bus = event_bus
        self._reference_path = reference_image_path
        self._authenticator = None

    @property
    def name(self) -> str:
        return "auth"

    @property
    def description(self) -> str:
        return "Face authentication using MediaPipe face landmarks"

    def get_tools(self) -> list[Tool]:
        # Auth is not tool-callable by the LLM  - it's a system service
        return []

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        return AgentResult(success=False, message="Auth agent has no LLM-callable tools")

    async def initialize(self):
        """Initialize the authenticator with platform-appropriate settings."""
        from authenticator import FaceAuthenticator

        # Patch the _run_cv_loop to use the right camera backend
        original_class = FaceAuthenticator

        async def on_status(authenticated: bool):
            self._bus.emit_nowait(Event(
                type=Events.AUTH_STATUS,
                data={"authenticated": authenticated},
                source=self.name,
            ))

        async def on_frame(frame_b64: str):
            self._bus.emit_nowait(Event(
                type=Events.AUTH_FRAME,
                data={"frame": frame_b64},
                source=self.name,
            ))

        self._authenticator = original_class(
            reference_image_path=self._reference_path,
            on_status_change=on_status,
            on_frame=on_frame,
        )

        # Fix platform bug: patch cv2 backend selection
        self._patch_camera_backend()

    def _patch_camera_backend(self):
        """Fix the macOS-only CAP_AVFOUNDATION bug."""
        if self._authenticator is None:
            return

        import cv2
        original_run = self._authenticator._run_cv_loop

        def patched_run(loop):
            def try_open_camera(index):
                # Use platform-appropriate backend
                system = platform.system()
                if system == "Darwin":
                    backend = cv2.CAP_AVFOUNDATION
                elif system == "Windows":
                    backend = cv2.CAP_DSHOW
                else:
                    backend = cv2.CAP_V4L2

                cap = cv2.VideoCapture(index, backend)
                if not cap.isOpened():
                    # Fallback: let OpenCV pick
                    cap = cv2.VideoCapture(index)
                if not cap.isOpened():
                    return None
                ret, frame = cap.read()
                if not ret:
                    cap.release()
                    return None
                return cap

            # Replace the nested function in the original
            import types
            self._authenticator._try_open_camera = try_open_camera
            return original_run(loop)

        self._authenticator._run_cv_loop = patched_run

    async def start_auth(self):
        """Start the authentication loop."""
        if self._authenticator:
            await self._authenticator.start_authentication_loop()

    def stop_auth(self):
        """Stop the authentication loop."""
        if self._authenticator:
            self._authenticator.stop()

    @property
    def is_authenticated(self) -> bool:
        if self._authenticator:
            return self._authenticator.authenticated
        return False

    @property
    def inner(self):
        return self._authenticator
