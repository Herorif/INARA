"""
Phone Call Session — bridges a phone call to INARA's Gemini Live API.

Each active phone call gets its own Gemini Live API session, independent
of the main voice pipeline. This means:
  - INARA can hold a phone conversation while the local voice pipeline is idle
  - Multiple simultaneous calls are possible (each has its own session)
  - Call audio never leaks into the room speakers (no feedback loops)

Audio flow:
  Phone (mulaw 8kHz) → resample to PCM 16kHz → Gemini
  Gemini (PCM 24kHz) → resample to mulaw 8kHz → Phone

Resampling uses soxr (high-quality, minimal aliasing on thin telephony audio).
numpy.interp is NOT used — it causes audible aliasing at 8kHz.

Audio ducking: When a call is active, the local voice pipeline is paused
to prevent room speakers from feeding back into the phone microphone.
"""

import asyncio
import os
import traceback
from typing import Optional, TYPE_CHECKING

from dotenv import load_dotenv
from google import genai
from google.genai import types

from core.event_bus import EventBus, Event, Events
from telephony.base import CallInfo, CallState
from voice.tts import INARA_SYSTEM_INSTRUCTION, INARA_VOICE_NAME

if TYPE_CHECKING:
    from telephony.base import BaseTelephonyProvider
    from voice.pipeline import VoicePipeline


# ---------------------------------------------------------------------------
# Audio resampling helpers
# ---------------------------------------------------------------------------

def _resample(audio: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    Resample 16-bit PCM audio using soxr (high-quality resampler).

    Falls back to numpy linear interpolation if soxr is not installed,
    but logs a warning — linear interpolation causes aliasing artifacts
    on low-rate telephony audio (especially 8kHz mulaw decoded to PCM).
    """
    if from_rate == to_rate:
        return audio

    import numpy as np

    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)

    try:
        import soxr
        resampled = soxr.resample(samples, from_rate, to_rate, quality="HQ")
    except ImportError:
        print("[INARA] [CALL] WARNING: soxr not installed. Using numpy resampling (lower quality).")
        n_out = int(len(samples) * to_rate / from_rate)
        x_old = np.linspace(0, 1, len(samples))
        x_new = np.linspace(0, 1, n_out)
        resampled = np.interp(x_new, x_old, samples)

    return resampled.astype(np.int16).tobytes()


def _mulaw_decode(mulaw_bytes: bytes) -> bytes:
    """Decode G.711 mu-law bytes to 16-bit PCM."""
    import numpy as np
    MULAW_MAX = 0x1FFF
    mulaw = np.frombuffer(mulaw_bytes, dtype=np.uint8).astype(np.int16)
    mulaw = ~mulaw
    sign = (mulaw & 0x80)
    exponent = (mulaw >> 4) & 0x07
    mantissa = mulaw & 0x0F
    sample = ((mantissa << 1) + 33) << exponent
    sample -= 33
    sample = np.where(sign != 0, -sample, sample)
    return (sample * (32767 // MULAW_MAX)).astype(np.int16).tobytes()


def _mulaw_encode(pcm_bytes: bytes) -> bytes:
    """Encode 16-bit PCM to G.711 mu-law bytes."""
    import numpy as np
    MULAW_MAX = 0x1FFF
    BIAS = 33
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.int32)
    sign = np.where(samples < 0, 0x80, 0x00).astype(np.uint8)
    samples = np.abs(samples)
    samples = np.clip(samples // (32767 // MULAW_MAX), 0, MULAW_MAX)
    samples = samples + BIAS
    exponent = np.zeros(len(samples), dtype=np.uint8)
    for exp in range(7, -1, -1):
        mask = samples >= (1 << (exp + 1))
        exponent[mask] = exp
    mantissa = ((samples >> (exponent)) & 0x0F).astype(np.uint8)
    encoded = (~(sign | (exponent << 4) | mantissa)).astype(np.uint8)
    return encoded.tobytes()


# ---------------------------------------------------------------------------
# Call Session
# ---------------------------------------------------------------------------

PHONE_SYSTEM_INSTRUCTION = (
    INARA_SYSTEM_INSTRUCTION
    + " You are currently on a phone call. Keep responses brief and conversational, "
    "suitable for audio-only communication. Speak clearly and naturally."
)

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

# Telephony audio spec (G.711 standard)
PHONE_SAMPLE_RATE = 8000
PHONE_CHANNELS = 1

# Gemini Live API audio spec
GEMINI_IN_RATE = 16000   # Gemini expects 16kHz PCM input
GEMINI_OUT_RATE = 24000  # Gemini outputs 24kHz PCM


class CallSession:
    """
    Manages a single phone call's Gemini Live API session.

    Created by PhoneAgent when a call connects. Runs two async loops:
      - _phone_to_gemini: reads audio from provider → resample → Gemini
      - _gemini_to_phone: reads Gemini audio → resample → provider

    Stops when the call ends or the provider disconnects.
    """

    def __init__(
        self,
        call_info: CallInfo,
        provider: "BaseTelephonyProvider",
        event_bus: EventBus,
        tools: Optional[list] = None,
        local_pipeline: Optional["VoicePipeline"] = None,
    ):
        self._call = call_info
        self._provider = provider
        self._bus = event_bus
        self._tools = tools or []
        self._local_pipeline = local_pipeline  # For audio ducking

        self._session = None
        self._client = None
        self._stop_event = asyncio.Event()
        self._out_queue: asyncio.Queue = asyncio.Queue(maxsize=20)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(self):
        """
        Start the call session. Blocks until the call ends.
        Should be run as an asyncio task.
        """
        self._init_client()

        # Audio ducking: pause local pipeline while call is active
        if self._local_pipeline:
            self._local_pipeline.set_paused(True)
            print(f"[INARA] [CALL] Audio ducking — local pipeline paused.")

        try:
            config = self._build_config()
            print(f"[INARA] [CALL] Connecting session for call {self._call.call_id}...")

            async with (
                self._client.aio.live.connect(model=MODEL, config=config) as session,
                asyncio.TaskGroup() as tg,
            ):
                self._session = session

                tg.create_task(self._phone_to_gemini())
                tg.create_task(self._gemini_to_phone())
                tg.create_task(self._handle_responses())

                await self._stop_event.wait()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[INARA] [CALL] Session error for {self._call.call_id}: {e}")
            traceback.print_exc()
        finally:
            # Restore local pipeline audio
            if self._local_pipeline:
                self._local_pipeline.set_paused(False)
                print(f"[INARA] [CALL] Audio ducking released — local pipeline resumed.")
            print(f"[INARA] [CALL] Session ended for {self._call.call_id}.")

    def stop(self):
        """Signal the session to stop."""
        self._stop_event.set()

    # -----------------------------------------------------------------------
    # Internal: Setup
    # -----------------------------------------------------------------------

    def _init_client(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not found.")
        self._client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key,
        )

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=PHONE_SYSTEM_INSTRUCTION,
            tools=self._tools,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=INARA_VOICE_NAME,
                    )
                )
            ),
        )

    # -----------------------------------------------------------------------
    # Internal: Audio loops
    # -----------------------------------------------------------------------

    async def _phone_to_gemini(self):
        """Read audio from the phone provider, resample, send to Gemini."""
        try:
            async for chunk in self._provider.receive_audio(self._call.call_id):
                if self._stop_event.is_set():
                    break
                # Decode mulaw → PCM, then resample 8kHz → 16kHz for Gemini
                pcm_8k = _mulaw_decode(chunk)
                pcm_16k = _resample(pcm_8k, PHONE_SAMPLE_RATE, GEMINI_IN_RATE)
                if self._session:
                    await self._session.send(
                        input={"data": pcm_16k, "mime_type": "audio/pcm"},
                        end_of_turn=False,
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[INARA] [CALL] phone_to_gemini error: {e}")

    async def _gemini_to_phone(self):
        """Send queued Gemini audio to the phone provider."""
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = await asyncio.wait_for(self._out_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if chunk and not self._stop_event.is_set():
                    await self._provider.send_audio(self._call.call_id, chunk)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[INARA] [CALL] gemini_to_phone error: {e}")

    async def _handle_responses(self):
        """Receive Gemini responses — audio, transcription."""
        try:
            while not self._stop_event.is_set():
                turn = self._session.receive()
                async for response in turn:
                    # Audio → resample 24kHz PCM → 8kHz mulaw → phone queue
                    if response.data:
                        pcm_8k = _resample(response.data, GEMINI_OUT_RATE, PHONE_SAMPLE_RATE)
                        mulaw = _mulaw_encode(pcm_8k)
                        try:
                            self._out_queue.put_nowait(mulaw)
                        except asyncio.QueueFull:
                            pass  # Drop frame rather than block

                    # Transcription → emit to frontend via bus
                    if response.server_content:
                        self._handle_transcription(response.server_content)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[INARA] [CALL] handle_responses error: {e}")

    def _handle_transcription(self, server_content):
        if server_content.input_transcription:
            text = server_content.input_transcription.text
            if text:
                self._bus.emit_nowait(Event(
                    type=Events.VOICE_TRANSCRIPTION,
                    data={"sender": "Caller", "text": text},
                    source="telephony",
                ))

        if server_content.output_transcription:
            text = server_content.output_transcription.text
            if text:
                self._bus.emit_nowait(Event(
                    type=Events.VOICE_TRANSCRIPTION,
                    data={"sender": "INARA", "text": text},
                    source="telephony",
                ))
