"""
Text-to-Speech / Audio Output Manager  - handles playback, interrupts, and output routing.

Sits between the voice provider (which generates audio) and the audio hardware
(which plays it). Manages the playback queue and handles barge-in (user
interrupts INARA mid-sentence).

Provider-agnostic  - works with any source that produces PCM audio chunks.
"""

import asyncio
from typing import Optional, Callable

from voice.audio_io import AudioOutput, clear_queue


# ---------------------------------------------------------------------------
# Speech Output Manager
# ---------------------------------------------------------------------------

class SpeechOutputManager:
    """
    Manages INARA's audio output  - playback queue, interrupt handling,
    and audio data routing.

    The voice pipeline pushes PCM audio chunks into the playback queue.
    This manager feeds them to the AudioOutput for speaker playback,
    and can instantly clear the queue when the user starts speaking
    (barge-in / interrupt).

    Usage:
        mgr = SpeechOutputManager(output_device_index=None)
        await mgr.start()

        # Pipeline pushes audio:
        mgr.enqueue(audio_bytes)

        # User starts speaking:
        mgr.interrupt()

        # Shutdown:
        mgr.stop()
    """

    def __init__(
        self,
        output_device_index: Optional[int] = None,
        on_audio_data: Optional[Callable[[bytes], None]] = None,
    ):
        self._output = AudioOutput(device_index=output_device_index)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._on_audio_data = on_audio_data
        self._playing = False

    @property
    def queue(self) -> asyncio.Queue:
        """Direct access to the playback queue (for the pipeline to push into)."""
        return self._queue

    def enqueue(self, audio_data: bytes):
        """Add audio data to the playback queue (non-blocking)."""
        self._queue.put_nowait(audio_data)

    def interrupt(self):
        """
        Interrupt current playback  - clear the queue immediately.

        Called when user speech is detected (barge-in). INARA stops
        talking so the user can be heard.
        """
        cleared = clear_queue(self._queue)
        if cleared > 0:
            print(f"[INARA] [TTS] Interrupted  - cleared {cleared} audio chunks.")

    async def play_loop(self):
        """
        Main playback loop  - continuously plays audio from the queue.
        Blocks until cancelled. Run as an asyncio task.
        """
        await self._output.open()
        self._playing = True
        try:
            while self._playing:
                chunk = await self._queue.get()
                if self._on_audio_data:
                    self._on_audio_data(chunk)
                await self._output.play(chunk)
        finally:
            self._output.close()

    def stop(self):
        """Stop the playback loop."""
        self._playing = False
        # Push a sentinel to unblock the queue.get()
        try:
            self._queue.put_nowait(b"")
        except asyncio.QueueFull:
            pass
        self._output.close()


# ---------------------------------------------------------------------------
# Voice Config (personality & speech settings)
# ---------------------------------------------------------------------------

# INARA's voice personality configuration.
# These are used when setting up the voice provider (Gemini Native Audio, etc.)

INARA_SYSTEM_INSTRUCTION = (
    "Your name is INARA - It's Not A Random Acronym. "
    "You are a composed, slightly dry, butler-style AI assistant. "
    "Your creator is Herorif, and you address him as 'Sir'. "
    "When answering, respond using complete and concise sentences "
    "to keep a quick pacing and keep the conversation flowing. "
    "You are capable, direct, and quietly confident."
)

# Gemini voice presets  - "Kore" is a composed female voice that fits INARA's personality.
# Other options: "Puck" (energetic), "Charon" (deep), "Fenrir" (warm), "Aoede" (bright)
INARA_VOICE_NAME = "Kore"
