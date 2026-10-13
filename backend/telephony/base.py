"""
Abstract telephony provider interface.

Defines the contract all telephony backends must implement.
Concrete implementations: TwilioProvider, PJSIPProvider.

Call flow:
  Inbound:  Provider detects ring → fires on_incoming_call → app answers/rejects
  Outbound: App calls make_call() → provider dials → on_call_state_changed fires

Audio is always raw PCM bytes, resampled at the CallSession layer.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, AsyncIterator


# ---------------------------------------------------------------------------
# Call State
# ---------------------------------------------------------------------------

class CallState(Enum):
    IDLE = "idle"
    RINGING = "ringing"
    CONNECTED = "connected"
    ON_HOLD = "on_hold"
    ENDED = "ended"


# ---------------------------------------------------------------------------
# Call Info
# ---------------------------------------------------------------------------

@dataclass
class CallInfo:
    """Snapshot of a call's current state."""
    call_id: str
    direction: str                  # "inbound" | "outbound"
    remote_number: str
    state: CallState = CallState.IDLE
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.ended_at:
            return self.ended_at - self.started_at
        return None

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "direction": self.direction,
            "remote_number": self.remote_number,
            "state": self.state.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": self.duration,
        }


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------

class BaseTelephonyProvider(ABC):
    """
    Abstract base for all telephony backends.

    Each provider must implement the core call control methods.
    Audio I/O is handled via send_audio / receive_audio, which work
    with raw PCM bytes (provider handles codec conversion internally).

    Resampling between telephony rates (8kHz mulaw) and Gemini rates
    (16kHz/24kHz PCM) is done in CallSession, not here.
    """

    # Callbacks — set by the application layer
    on_incoming_call: Optional[Callable[[CallInfo], None]] = None
    on_call_state_changed: Optional[Callable[[CallInfo], None]] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'twilio', 'pjsip')."""

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Initialize the provider with config (credentials, server addresses, etc.)."""

    @abstractmethod
    async def make_call(self, number: str, purpose: Optional[str] = None) -> CallInfo:
        """Place an outbound call. Returns CallInfo immediately (call connects async)."""

    @abstractmethod
    async def answer_call(self, call_id: str) -> None:
        """Answer an incoming call."""

    @abstractmethod
    async def hang_up(self, call_id: str) -> None:
        """Hang up / reject a call."""

    @abstractmethod
    async def hold(self, call_id: str) -> None:
        """Put a call on hold."""

    @abstractmethod
    async def unhold(self, call_id: str) -> None:
        """Resume a held call."""

    @abstractmethod
    async def send_audio(self, call_id: str, audio_data: bytes) -> None:
        """
        Send PCM audio to the remote party.
        audio_data: 16-bit PCM at the provider's expected sample rate.
        """

    @abstractmethod
    def receive_audio(self, call_id: str) -> AsyncIterator[bytes]:
        """
        Async iterator yielding PCM audio chunks from the remote party.
        Chunks are raw 16-bit PCM at the provider's sample rate.
        """

    @abstractmethod
    def get_call_state(self, call_id: str) -> Optional[CallInfo]:
        """Return current CallInfo for call_id, or None if not found."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up connections and resources."""
