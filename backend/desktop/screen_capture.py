"""
Screen capture and vision analysis for JARVIS.

Grabs the desktop screenshot, downscales it, and optionally sends it
to Gemini for a natural-language description. This gives JARVIS "eyes"
on whatever the user is looking at.
"""

import base64
from dataclasses import dataclass
import io
from typing import Optional


_VISION_PROMPT = (
    "You are JARVIS, an AI assistant. The user has asked you to look at their screen. "
    "Describe what you see clearly and specifically: any application windows, text content, "
    "error messages, UI elements, or anything noteworthy. "
    "Be concise but accurate. If you see an error or problem, highlight it."
)


@dataclass(frozen=True)
class ScreenDescription:
    """One capture plus its vision result; ``image`` is the JPEG that was described."""

    success: bool
    description: str
    image: bytes
    error: Optional[str] = None

    @property
    def image_base64(self) -> str:
        return base64.b64encode(self.image).decode("utf-8")


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
        except ImportError as exc:
            raise RuntimeError("Pillow is required for screenshots: pip install Pillow") from exc

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
    ) -> ScreenDescription:
        """
        Capture the screen once and ask the vision model to describe it.

        Returns a ScreenDescription holding the captured JPEG. ``success`` is
        False (with ``error`` set) when the key is missing or the model call
        fails; capture errors propagate to the caller.
        """
        img_bytes = self.capture_to_bytes(region)
        return self.describe_bytes(img_bytes, prompt)

    def describe_bytes(self, img_bytes: bytes, prompt: Optional[str] = None) -> ScreenDescription:
        """Describe an already-captured JPEG with the configured vision model."""
        from services.capability_profiles import model_id, provider_key

        api_key = provider_key()
        if not api_key:
            error = (
                "No Gemini API key is saved (Setup > AI providers, or GEMINI_API_KEY); "
                "cannot analyse screen."
            )
            return ScreenDescription(False, error, img_bytes, error)

        describe_prompt = prompt or _VISION_PROMPT

        try:
            from google import genai
            from google.genai import types

            from services.tls import genai_http_options

            client = genai.Client(api_key=api_key, http_options=genai_http_options())
            response = client.models.generate_content(
                model=model_id("vision"),
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    types.Part(text=describe_prompt),
                ],
            )
        except Exception as e:
            error = f"Screenshot taken but vision analysis failed: {e}"
            return ScreenDescription(False, error, img_bytes, error)
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            error = "Screenshot taken but the vision model returned no description."
            return ScreenDescription(False, error, img_bytes, error)
        return ScreenDescription(True, text, img_bytes)

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
