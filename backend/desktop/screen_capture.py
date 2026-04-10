"""
Screen capture and vision analysis for INARA.

Grabs the desktop screenshot, downscales it, and optionally sends it
to Gemini for a natural-language description. This gives INARA "eyes"
on whatever the user is looking at.
"""

import base64
import io
import os
from typing import Optional


_VISION_PROMPT = (
    "You are INARA, an AI assistant. The user has asked you to look at their screen. "
    "Describe what you see clearly and specifically: any application windows, text content, "
    "error messages, UI elements, or anything noteworthy. "
    "Be concise but accurate. If you see an error or problem, highlight it."
)


class ScreenCapture:

    def __init__(self, max_width: int = 1280):
        self._max_width = max_width

    # -----------------------------------------------------------------------
    # Capture
    # -----------------------------------------------------------------------

    def capture(self, region: Optional[tuple] = None):
        """
        Take a screenshot. Returns a PIL.Image.

        Args:
            region: Optional (x, y, width, height) tuple to capture a sub-region.
        """
        try:
            from PIL import ImageGrab
        except ImportError:
            raise RuntimeError("Pillow is required for screenshots: pip install Pillow")

        if region:
            x, y, w, h = region
            bbox = (x, y, x + w, y + h)
        else:
            bbox = None

        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return img

    def capture_to_bytes(self, region: Optional[tuple] = None) -> bytes:
        """Capture and return as JPEG bytes, downscaled to max_width."""
        img = self.capture(region)
        img = self._downscale(img)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def capture_to_base64(self, region: Optional[tuple] = None) -> str:
        """Capture and return as base64-encoded JPEG string."""
        return base64.b64encode(self.capture_to_bytes(region)).decode("utf-8")

    # -----------------------------------------------------------------------
    # Vision analysis via Gemini
    # -----------------------------------------------------------------------

    def capture_and_describe(
        self,
        region: Optional[tuple] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """
        Capture the screen and ask Gemini to describe it.

        Returns the description string. Falls back to a plain error message
        if the Gemini call fails.
        """
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return "GEMINI_API_KEY not set — cannot analyse screen."

        img_bytes = self.capture_to_bytes(region)
        describe_prompt = prompt or _VISION_PROMPT

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    types.Part(text=describe_prompt),
                ],
            )
            return response.text or "No description returned."
        except Exception as e:
            return f"Screenshot taken but vision analysis failed: {e}"

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _downscale(self, img):
        """Downscale image if wider than max_width, preserving aspect ratio."""
        w, h = img.size
        if w <= self._max_width:
            return img
        ratio = self._max_width / w
        new_h = int(h * ratio)
        from PIL import Image
        return img.resize((self._max_width, new_h), Image.LANCZOS)
