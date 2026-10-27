"""Short spoken samples of INARA's prebuilt voices for Preferences.

One fixed line per voice through Gemini text-to-speech, cached in memory for the process.
Importing this module opens no provider and imports no SDK.

Request shape: ``generate_content`` with ``response_modalities=["AUDIO"]`` and
``speech_config.voice_config.prebuilt_voice_config.voice_name``; the model id is
``model_id("tts")`` (default ``gemini-3.8-flash-tts``). Source:
https://ai.google.dev/gemini-api/docs/speech-generation ("Supported models", "Voice options"
and the migration guide; page last updated 2026-10-12 UTC, checked 27 Oct 2026). Gemini 3.8
TTS reads the input as a verbatim transcript and returns WAV (RIFF, 24 kHz mono PCM16) for
unary requests; earlier models return headerless PCM16 (``audio/L16;rate=24000``). Both are
accepted and reduced to raw PCM16 for the renderer.
"""

import asyncio
import base64
import io
import re
import time
import uuid
import wave

from pydantic import BaseModel, ConfigDict
from typing import Literal

from services.capability_profiles import model_id, provider_key
from services.live_config import PREBUILT_VOICES
from services.log import get_logger
from services.tools import ServiceError
from services.usage import usage_counts

logger = get_logger(__name__)

PREVIEW_LINE = "Hello, I'm INARA. How can I help?"
DEFAULT_RATE = 24000
TIMEOUT_SECONDS = 30
# The line is about three seconds; anything over 20 s of 48 kHz PCM16 is not a preview.
MAX_PCM_BYTES = 20 * 48000 * 2


class VoicePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal[PREBUILT_VOICES]


def ready():
    if not provider_key():
        raise ServiceError(
            "provider_not_configured", "Add a Gemini key to preview voices."
        )


async def synthesize(model, name, max_output_tokens=None):
    """One TTS request with the profile key and the OS certificate store; returns the response."""
    from google import genai
    from google.genai import types

    from services.tls import genai_http_options

    client = genai.Client(
        api_key=provider_key(), http_options=genai_http_options(retry_options={"attempts": 1})
    )
    try:
        return await client.aio.models.generate_content(
            model=model,
            contents=PREVIEW_LINE,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name)
                    )
                ),
                **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}),
            ),
        )
    finally:
        try:
            await asyncio.wait_for(client.aio.aclose(), 5)
        except Exception:
            logger.warning("TTS client did not close cleanly", exc_info=True)


def map_error(exc):
    """SDK/transport failure -> ServiceError with a plain message; never echoes SDK text."""
    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ServiceError("provider_timeout", "The voice preview timed out. Try again.")
    try:
        from google.genai import errors

        if isinstance(exc, errors.APIError):
            status = exc.code if isinstance(exc.code, int) else 0
            detail = f"{getattr(exc, 'status', '')} {getattr(exc, 'message', '')}"
            if status in (401, 403) or (
                status == 400 and ("API_KEY_INVALID" in detail or "API key not valid" in detail)
            ):
                return ServiceError(
                    "provider_key_invalid",
                    "Gemini rejected the API key. Update it under AI providers.",
                )
            if status == 429:
                return ServiceError(
                    "provider_rate_limited",
                    "Gemini is limiting requests right now. Try the preview again in a minute.",
                )
            if status >= 500:
                return ServiceError(
                    "provider_unavailable", "Gemini is temporarily unavailable. Try again shortly."
                )
            return ServiceError("provider_failed", "Gemini could not make this voice preview.")
    except ImportError:
        pass
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return ServiceError("provider_timeout", "The voice preview timed out. Try again.")
        network = isinstance(exc, (httpx.TransportError, OSError))
    except ImportError:
        network = isinstance(exc, OSError)
    if network:
        from services.secrets import classify_exception

        if classify_exception(exc) == "tls_error":
            return ServiceError(
                "provider_network",
                "Couldn't make a secure connection to Gemini. A proxy or antivirus may be "
                "intercepting HTTPS.",
            )
        return ServiceError("provider_network", "Couldn't reach Gemini. Check your internet connection.")
    return ServiceError("provider_failed", "Gemini could not make this voice preview.")


def extract_audio(response):
    """(sample_rate, PCM16 mono bytes) from a TTS response, or a provider_failed error."""
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            blob = getattr(part, "inline_data", None)
            data = getattr(blob, "data", None)
            if isinstance(data, str):
                data = base64.b64decode(data)
            if not isinstance(data, (bytes, bytearray)) or not data:
                continue
            data = bytes(data)
            if data[:4] == b"RIFF":
                try:
                    with wave.open(io.BytesIO(data), "rb") as audio:
                        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                            raise ValueError("Unexpected WAV layout")
                        rate, pcm = audio.getframerate(), audio.readframes(audio.getnframes())
                except (wave.Error, EOFError, ValueError) as exc:
                    raise ServiceError(
                        "provider_failed", "Gemini returned audio INARA can't play."
                    ) from exc
            else:
                mime = str(getattr(blob, "mime_type", "") or "")
                match = re.search(r"rate=(\d+)", mime)
                rate, pcm = (int(match.group(1)) if match else DEFAULT_RATE), data
            pcm = pcm[: len(pcm) - len(pcm) % 2]
            if not 8000 <= rate <= 48000 or not pcm or len(pcm) > MAX_PCM_BYTES:
                raise ServiceError("provider_failed", "Gemini returned audio INARA can't play.")
            return rate, pcm
    raise ServiceError("provider_failed", "Gemini returned no audio for this voice.")


class VoicePreviewService:
    def __init__(self, app, synthesizer=None, preflight=None):
        self.app = app
        self.synthesizer = synthesizer or synthesize
        self.preflight = preflight or ready
        self.cache = {}  # (model, voice) -> {"sample_rate", "pcm_base64"}; process lifetime
        self.locks = {}  # (model, voice) -> Lock; one provider request per voice at a time

    async def preview(self, sid, request):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        model = model_id("tts")
        key = (model, request.name)
        if key in self.cache:
            return {"name": request.name, "cached": True, **self.cache[key]}
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self.cache:
                return {"name": request.name, "cached": True, **self.cache[key]}
            self.preflight()
            project = self.app.projects.get_current_project_path().resolve()
            operation = self.app.usage.operation(owner, project, "voice_preview", uuid.uuid4())
            ticket = operation.begin(model)
            started = time.monotonic()
            counts = None
            try:
                response = await asyncio.wait_for(
                    self.synthesizer(
                        model,
                        request.name,
                        ticket["max_output_tokens"] if ticket["capped"] else None,
                    ),
                    TIMEOUT_SECONDS,
                )
                counts = usage_counts(response)
            except asyncio.CancelledError:
                self.app.usage.finish(ticket, "uncertain", None, time.monotonic() - started)
                raise
            except Exception as exc:
                self.app.usage.finish(ticket, "uncertain", None, time.monotonic() - started)
                error = map_error(exc)
                if error.code == "provider_failed":
                    logger.warning("Voice preview failed (%s)", type(exc).__name__)
                raise error from exc
            self.app.usage.finish(
                ticket, "completed" if counts else "uncertain", counts, time.monotonic() - started
            )
            rate, pcm = extract_audio(response)
            entry = {"sample_rate": rate, "pcm_base64": base64.b64encode(pcm).decode("ascii")}
            self.cache[key] = entry
            return {"name": request.name, "cached": False, **entry}
