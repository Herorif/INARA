"""
Speech-to-Text — Transcription processing and chat buffering.

Handles the delta calculation for streaming transcription (Gemini sends
cumulative text, we extract the new portion) and manages the chat buffer
for logging conversations to the project manager.

Provider-agnostic — works with any transcription source that delivers
cumulative or chunked text.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable


# ---------------------------------------------------------------------------
# Transcription Processor
# ---------------------------------------------------------------------------

class TranscriptionProcessor:
    """
    Processes streaming transcription text and extracts deltas.

    Gemini's Live API sends cumulative transcription — each update contains
    the full text so far, not just the new part. This class tracks the last
    seen text and extracts only the new portion (the delta).

    It also deduplicates exact repeats.

    Usage:
        proc = TranscriptionProcessor()
        delta = proc.process("Hello")        # → "Hello"
        delta = proc.process("Hello world")  # → " world"
        delta = proc.process("Hello world")  # → None (duplicate)
    """

    def __init__(self):
        self._last_text = ""

    def process(self, transcript: str) -> Optional[str]:
        """
        Process a transcription update. Returns the new text (delta),
        or None if it's a duplicate.
        """
        if not transcript:
            return None

        # Skip exact duplicates
        if transcript == self._last_text:
            return None

        # Calculate delta
        delta = transcript
        if transcript.startswith(self._last_text):
            delta = transcript[len(self._last_text):]

        self._last_text = transcript

        return delta if delta else None

    def reset(self):
        """Reset tracking state (e.g., on reconnect or turn boundary)."""
        self._last_text = ""


# ---------------------------------------------------------------------------
# Chat Buffer
# ---------------------------------------------------------------------------

class ChatBuffer:
    """
    Aggregates streaming transcription chunks into complete messages.

    The voice pipeline receives transcription in small deltas — this buffer
    collects them by sender and flushes complete messages when the sender
    changes or when explicitly requested.

    Usage:
        buf = ChatBuffer(on_flush=lambda sender, text: log(sender, text))
        buf.append("User", "Hello ")
        buf.append("User", "world")    # still buffering
        buf.append("INARA", "Hi")      # flushes "User: Hello world", starts "INARA: Hi"
        buf.flush()                     # flushes "INARA: Hi"
    """

    def __init__(self, on_flush: Optional[Callable[[str, str], None]] = None):
        self._sender: Optional[str] = None
        self._text: str = ""
        self.on_flush = on_flush

    @property
    def current_sender(self) -> Optional[str]:
        return self._sender

    def append(self, sender: str, text: str):
        """
        Append text from a sender. If the sender changes, the previous
        buffer is flushed first.
        """
        if self._sender != sender:
            # Sender changed — flush previous
            self.flush()
            self._sender = sender
            self._text = text
        else:
            self._text += text

    def flush(self):
        """Flush the current buffer. Fires on_flush if there's content."""
        if self._sender and self._text.strip():
            if self.on_flush:
                self.on_flush(self._sender, self._text)
        self._sender = None
        self._text = ""

    def reset(self):
        """Reset without flushing (discard current buffer)."""
        self._sender = None
        self._text = ""


# ---------------------------------------------------------------------------
# Transcription Manager
# ---------------------------------------------------------------------------

class TranscriptionManager:
    """
    High-level transcription manager that combines input/output processors
    and a chat buffer.

    Wired into the voice pipeline to handle all transcription concerns:
    - Delta extraction for both user (input) and INARA (output) transcription
    - Chat buffer management for logging
    - Callback dispatch to the frontend

    Usage:
        mgr = TranscriptionManager(
            on_transcription=lambda data: emit("transcription", data),
            on_log=lambda sender, text: project_manager.log_chat(sender, text),
        )
        mgr.process_input("Hello world")
        mgr.process_output("Hi there")
        mgr.flush()
    """

    def __init__(
        self,
        on_transcription: Optional[Callable[[dict], None]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_user_speech: Optional[Callable[[], None]] = None,
    ):
        self._input_proc = TranscriptionProcessor()
        self._output_proc = TranscriptionProcessor()
        self._buffer = ChatBuffer(on_flush=on_log)
        self._on_transcription = on_transcription
        self._on_user_speech = on_user_speech

    def process_input(self, transcript: str) -> Optional[str]:
        """
        Process user speech transcription. Returns delta text or None.

        Fires on_transcription callback and on_user_speech (for interrupt handling).
        """
        delta = self._input_proc.process(transcript)
        if delta is None:
            return None

        # User is speaking — notify for interrupt handling
        if self._on_user_speech:
            self._on_user_speech()

        # Send to frontend
        if self._on_transcription:
            self._on_transcription({"sender": "User", "text": delta})

        # Buffer for logging
        self._buffer.append("User", delta)

        return delta

    def process_output(self, transcript: str) -> Optional[str]:
        """
        Process INARA speech transcription. Returns delta text or None.

        Fires on_transcription callback.
        """
        delta = self._output_proc.process(transcript)
        if delta is None:
            return None

        # Send to frontend
        if self._on_transcription:
            self._on_transcription({"sender": "INARA", "text": delta})

        # Buffer for logging
        self._buffer.append("INARA", delta)

        return delta

    def flush(self):
        """Flush the chat buffer and reset transcription tracking."""
        self._buffer.flush()
        self._input_proc.reset()
        self._output_proc.reset()

    def reset(self):
        """Full reset — discard everything."""
        self._buffer.reset()
        self._input_proc.reset()
        self._output_proc.reset()
