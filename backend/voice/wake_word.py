"""
Voice Activity Detection  - RMS-based speech detection with pluggable wake word support.

Currently uses a simple RMS threshold to detect speech onset/offset.
Designed to be extended with a real wake word engine (Porcupine, Snowboy, etc.)
when INARA graduates to always-on listening.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from voice.audio_io import calculate_rms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VAD_THRESHOLD = 800        # RMS threshold for speech (conservative for 16-bit PCM)
SILENCE_DURATION = 0.5     # Seconds of silence to consider speech ended


# ---------------------------------------------------------------------------
# VAD State
# ---------------------------------------------------------------------------

@dataclass
class VADState:
    """Tracks voice activity detection state across audio chunks."""
    is_speaking: bool = False
    silence_start: Optional[float] = None
    threshold: int = VAD_THRESHOLD
    silence_duration: float = SILENCE_DURATION


class VoiceActivityDetector:
    """
    RMS-based voice activity detector.

    Detects speech onset (silence → speech) and speech offset (speech → silence).
    Fires callbacks on transitions, not on every frame.

    Usage:
        vad = VoiceActivityDetector()
        vad.on_speech_start = lambda: print("speaking")
        vad.on_speech_end = lambda: print("silence")

        for chunk in audio_stream:
            vad.process(chunk)
    """

    def __init__(
        self,
        threshold: int = VAD_THRESHOLD,
        silence_duration: float = SILENCE_DURATION,
    ):
        self._state = VADState(threshold=threshold, silence_duration=silence_duration)
        self.on_speech_start: Optional[Callable[[], None]] = None
        self.on_speech_end: Optional[Callable[[], None]] = None

    @property
    def is_speaking(self) -> bool:
        return self._state.is_speaking

    def process(self, audio_chunk: bytes) -> bool:
        """
        Process one audio chunk. Returns True if speech is currently detected.

        Fires on_speech_start on silence→speech transition.
        Fires on_speech_end after silence_duration of quiet following speech.
        """
        rms = calculate_rms(audio_chunk)
        state = self._state

        if rms > state.threshold:
            # Speech detected
            state.silence_start = None

            if not state.is_speaking:
                # Transition: silence → speech
                state.is_speaking = True
                if self.on_speech_start:
                    self.on_speech_start()

        else:
            # Silence
            if state.is_speaking:
                if state.silence_start is None:
                    state.silence_start = time.time()
                elif time.time() - state.silence_start > state.silence_duration:
                    # Transition: speech → silence (confirmed)
                    state.is_speaking = False
                    state.silence_start = None
                    if self.on_speech_end:
                        self.on_speech_end()

        return state.is_speaking

    def reset(self):
        """Reset VAD state."""
        self._state.is_speaking = False
        self._state.silence_start = None


# ---------------------------------------------------------------------------
# Wake Word Detector (placeholder for future implementation)
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """
    Placeholder for wake word detection.

    When implemented, this will listen for "INARA" and only activate
    the voice pipeline on detection. For now, the pipeline is always
    active when started (push-to-talk or continuous mode).

    Future implementation options:
    - Picovoice Porcupine (custom wake word, runs locally)
    - OpenWakeWord (open-source, runs locally)
    - Whisper-based keyword spotting
    """

    def __init__(self, wake_word: str = "inara"):
        self.wake_word = wake_word
        self._active = False

    @property
    def is_active(self) -> bool:
        """Whether the wake word has been detected and pipeline should be listening."""
        return self._active

    def process(self, audio_chunk: bytes) -> bool:
        """
        Process audio chunk for wake word detection.
        Returns True if wake word was detected in this chunk.

        Currently a no-op  - always returns False.
        The pipeline runs in always-on mode until this is implemented.
        """
        # TODO: Integrate wake word engine
        return False

    def activate(self):
        """Manually activate (for push-to-talk or testing)."""
        self._active = True

    def deactivate(self):
        """Return to listening-for-wake-word state."""
        self._active = False

    def reset(self):
        """Reset detector state."""
        self._active = False
