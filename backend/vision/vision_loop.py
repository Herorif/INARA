"""
Continuous vision monitoring loop.

Holds the latest camera frame in memory and evaluates any active
watch conditions against it on a configurable interval. When a watch
condition is met, fires a VISION_ALERT event on the event bus.
"""

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from core.event_bus import Event, Events

logger = logging.getLogger(__name__)


@dataclass
class WatchCondition:
    """A single active watch condition."""
    id: str
    description: str          # e.g. "person at the door"
    added_at: float = field(default_factory=time.time)
    last_checked: float = 0.0
    last_result: str = ""


class VisionLoop:
    """
    Runs in the background, watching camera frames for user-specified events.

    Usage
    -----
    loop = VisionLoop(event_bus=bus, interval=5)
    loop.set_frame(jpeg_bytes)          # called from video_frame socket handler
    loop.add_watch("person at door")
    await loop.run()                    # runs until stop() called
    """

    def __init__(self, event_bus, interval: float = 5.0):
        self._bus = event_bus
        self._interval = interval          # seconds between checks
        self._frame: Optional[bytes] = None
        self._watches: dict[str, WatchCondition] = {}
        self._stop_event = asyncio.Event()
        self._api_key: Optional[str] = None
        self._client = None          # initialized once in run()
        self._model = "gemini-2.0-flash"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_frame(self, jpeg_bytes: bytes):
        """Update the latest camera frame. Called externally on every video_frame event."""
        self._frame = jpeg_bytes

    def add_watch(self, watch_id: str, description: str) -> WatchCondition:
        """Register a new watch condition. Replaces any existing one with the same ID."""
        w = WatchCondition(id=watch_id, description=description)
        self._watches[watch_id] = w
        logger.info(f"[VisionLoop] Watch added: '{description}' (id={watch_id})")
        return w

    def remove_watch(self, watch_id: str) -> bool:
        """Remove a watch condition. Returns True if it existed."""
        if watch_id in self._watches:
            del self._watches[watch_id]
            logger.info(f"[VisionLoop] Watch removed: {watch_id}")
            return True
        return False

    def list_watches(self) -> list[dict]:
        return [
            {"id": w.id, "description": w.description, "added_at": w.added_at}
            for w in self._watches.values()
        ]

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def run(self):
        """Main loop — polls active watches every self._interval seconds."""
        logger.info("[VisionLoop] Started")
        self._api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        # Create the Gemini client once for all watch evaluations
        if self._api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except Exception as e:
                logger.warning(f"[VisionLoop] Failed to create Gemini client: {e}")
                self._client = None
        else:
            self._client = None

        while not self._stop_event.is_set():
            await asyncio.sleep(self._interval)
            if not self._watches:
                continue
            if self._frame is None:
                continue
            await self._check_all_watches()

        logger.info("[VisionLoop] Stopped")

    async def _check_all_watches(self):
        frame_snapshot = self._frame
        if frame_snapshot is None:
            return

        for watch in list(self._watches.values()):
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda w=watch, f=frame_snapshot: self._evaluate_watch(w, f),
                )
                watch.last_result = result
                watch.last_checked = time.time()

                if result.startswith("DETECTED"):
                    self._bus.emit_nowait(Event(
                        type=Events.VISION_ALERT,
                        data={
                            "watch_id": watch.id,
                            "watch_description": watch.description,
                            "result": result,
                        },
                        source="vision_loop",
                    ))
                    logger.info(f"[VisionLoop] Alert: {result}")
            except Exception as e:
                logger.warning(f"[VisionLoop] Watch check failed ({watch.id}): {e}")

    def _evaluate_watch(self, watch: WatchCondition, frame_bytes: bytes) -> str:
        """Synchronous Gemini call — runs in executor to avoid blocking the event loop."""
        if not self._api_key or not self._client:
            return "CLEAR (no API key)"
        try:
            from google.genai import types

            prompt = (
                f"You are monitoring a camera feed. "
                f"Watch for: {watch.description}. "
                f"If you see it, respond with exactly: DETECTED: <brief description>. "
                f"If you do not see it, respond with exactly: CLEAR."
            )
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"),
                    types.Part(text=prompt),
                ],
            )
            return (response.text or "CLEAR").strip()
        except Exception as e:
            logger.warning(f"[VisionLoop] Gemini error: {e}")
            return f"ERROR: {e}"
