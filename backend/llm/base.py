"""
Base LLM provider interface.

All LLM providers (Gemini, Claude, local) implement this ABC.
The rest of the system never imports provider-specific SDKs directly.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


_SAFE_FIELD = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
GENERIC_FAILURE = "The AI provider could not complete this request."


def _field(value):
    """A short identifier-shaped value, or ``-``; never free text from a provider."""
    if value is None:
        return "-"
    text = str(value)
    return text if _SAFE_FIELD.fullmatch(text) else "-"


def log_provider_failure(provider, exc, status=None, kind=None, reason=None):
    """One WARNING per failed provider request with safe diagnostic fields only.

    Never pass request text, response bodies, keys or the provider's error message.
    """
    from services.log import get_logger

    get_logger("llm.provider").warning(
        "AI provider request failed: provider=%s error=%s status=%s kind=%s reason=%s",
        _field(provider), _field(type(exc).__name__), _field(status), _field(kind),
        _field(reason),
    )


class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class Message:
    role: MessageRole
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    # For multimodal messages (images, audio)
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a tool, sent back to the LLM."""
    tool_call_id: str
    name: str
    result: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: Optional[str] = None
    # Raw provider-specific response for edge cases
    raw: Any = None
    # Whether this is a partial streaming chunk
    is_partial: bool = False
    # Audio data (for voice-capable providers)
    audio_data: Optional[bytes] = None
    # Claude: the assistant turn's content blocks exactly as returned (thinking
    # blocks and signatures included), to be replayed unchanged.
    content_blocks: Optional[list[dict[str, Any]]] = None
    stop_reason: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'gemini', 'claude')."""
        ...

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        """Single-shot generation. Returns when complete."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[LLMResponse]:
        """Streaming generation. Yields partial responses."""
        ...

    async def close(self):  # noqa: B027  optional hook; the default is a no-op
        """Clean up provider resources. Override if needed."""
        pass


class BaseVoiceProvider(ABC):
    """Extended interface for providers that support real-time voice (e.g. Gemini Native Audio)."""

    @abstractmethod
    async def connect_voice(
        self,
        system_instruction: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        voice_name: Optional[str] = None,
        **kwargs,
    ):
        """Establish a real-time voice session."""
        ...

    @abstractmethod
    async def send_audio(self, audio_data: bytes, mime_type: str = "audio/pcm"):
        """Send audio chunk to the live session."""
        ...

    @abstractmethod
    async def send_text(self, text: str):
        """Send text input to the live session."""
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[LLMResponse]:
        """Receive responses (audio, text, tool calls) from the live session."""
        ...

    @abstractmethod
    async def send_tool_result(self, result: ToolResult):
        """Send a tool execution result back to the live session."""
        ...

    @abstractmethod
    async def disconnect_voice(self):
        """Close the voice session."""
        ...
