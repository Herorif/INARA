"""
Voice Activity Detection and Wake Word Detection.

- VoiceActivityDetector: RMS-based speech onset/offset detection.
- WakeWordDetector: OpenWakeWord-based wake word detection for "Hey INARA".
  Uses "hey_jarvis" as a built-in proxy model until a custom "hey_inara"
  model is trained via OpenWakeWord's training pipeline.
"""

import time
import numpy as np
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
# Wake Word Detector (OpenWakeWord)
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """
    Wake word detection using OpenWakeWord.

    Listens for "Hey INARA" using the built-in "hey_jarvis" model as a
    proxy (closest phonetic match). A custom "hey_inara" model can be
    trained later via OpenWakeWord's training pipeline and passed in
    via the `wake_words` parameter.

    Audio format: 16-bit PCM, 16kHz mono (OpenWakeWord's expected input).
    """

    def __init__(
        self,
        wake_words: Optional[list[str]] = None,
        threshold: float = 0.5,
    ):
        self._threshold = threshold
        self._active = False
        self._model = None
        self._wake_words = wake_words

        # Callback fired on wake word detection with the detected model name
        self.on_wake: Optional[Callable[[str], None]] = None

        self._init_model()

    def _init_model(self):
        """Lazy-load OpenWakeWord model."""
        try:
            from openwakeword.model import Model
            self._model = Model(
                wakeword_models=self._wake_words or ["hey_jarvis"],
                inference_framework="onnx",
            )
            print(f"[INARA] [WAKE] OpenWakeWord loaded. Models: {self._wake_words or ['hey_jarvis']}")
        except ImportError:
            print("[INARA] [WAKE] openwakeword not installed. Wake word detection disabled.")
            self._model = None
        except Exception as e:
            print(f"[INARA] [WAKE] Failed to load OpenWakeWord: {e}")
            self._model = None

    @property
    def is_active(self) -> bool:
        """Whether the wake word has been detected and pipeline should be listening."""
        return self._active

    @property
    def available(self) -> bool:
        """Whether the wake word engine is loaded and ready."""
        return self._model is not None

    def process(self, audio_chunk: bytes) -> bool:
        """
        Process audio chunk for wake word detection.
        Returns True if wake word was detected in this chunk.

        Expects 16-bit PCM audio at 16kHz mono.
        """
        if self._model is None:
            return False

        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
        prediction = self._model.predict(audio_array)

        for name, score in prediction.items():
            if score > self._threshold:
                self._active = True
                print(f"[INARA] [WAKE] Detected '{name}' (score: {score:.3f})")
                if self.on_wake:
                    self.on_wake(name)
                return True

        return False

    def activate(self):
        """Manually activate (for push-to-talk or testing)."""
        self._active = True

    def deactivate(self):
        """Return to listening-for-wake-word state."""
        self._active = False
        if self._model:
            self._model.reset()

    def reset(self):
        """Reset detector state."""
        self._active = False
        if self._model:
            self._model.reset()
