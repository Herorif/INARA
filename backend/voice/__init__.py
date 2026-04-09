"""
INARA Voice Module  - real-time voice conversation pipeline.

Components:
    audio_io     - Hardware I/O (mic, speaker, camera)
    wake_word    - Voice activity detection & wake word
    stt          - Speech-to-text / transcription processing
    tts          - Text-to-speech / audio output management
    pipeline     - Main orchestrator (Gemini Live API integration)
"""

from voice.pipeline import VoicePipeline
from voice.audio_io import AudioInput, AudioOutput, VideoCapture, get_input_devices, get_output_devices
from voice.wake_word import VoiceActivityDetector, WakeWordDetector
from voice.stt import TranscriptionManager, TranscriptionProcessor, ChatBuffer
from voice.tts import SpeechOutputManager, INARA_SYSTEM_INSTRUCTION, INARA_VOICE_NAME

__all__ = [
    "VoicePipeline",
    "AudioInput",
    "AudioOutput",
    "VideoCapture",
    "get_input_devices",
    "get_output_devices",
    "VoiceActivityDetector",
    "WakeWordDetector",
    "TranscriptionManager",
    "TranscriptionProcessor",
    "ChatBuffer",
    "SpeechOutputManager",
    "INARA_SYSTEM_INSTRUCTION",
    "INARA_VOICE_NAME",
]
