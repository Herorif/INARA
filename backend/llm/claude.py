"""
Claude (Anthropic) LLM provider.

Wraps the Anthropic SDK behind the BaseLLMProvider interface.
"""

import os
from typing import AsyncIterator, Optional

from dotenv import load_dotenv

from .base import (
    BaseLLMProvider,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
)

load_dotenv()


def _messages_to_claude_format(messages: list[Message]) -> tuple[Optional[str], list[dict]]:
    """Convert our Message objects to Claude's format.

    Returns (system_text, messages_list).
    Claude handles system instructions separately from messages.
    """
    system_text = None
    claude_messages = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_text = msg.content
            continue

        role = "user" if msg.role in (MessageRole.USER, MessageRole.TOOL) else "assistant"

        if msg.role == MessageRole.TOOL:
            claude_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })
            continue

        content = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})

        for att in msg.attachments:
            if att.get("type") == "image":
                import base64
                data_b64 = base64.b64encode(att["data"]).decode("utf-8") if isinstance(att["data"], bytes) else att["data"]
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att.get("mime_type", "image/jpeg"),
                        "data": data_b64,
                    },
                })

        claude_messages.append({"role": role, "content": content})

    return system_text, claude_messages


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider for text generation and tool calling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._model = model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "claude"

    async def generate(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        self._ensure_client()

        inline_system, claude_messages = _messages_to_claude_format(messages)
        system = system_instruction or inline_system

        api_kwargs = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": claude_messages,
            "temperature": temperature,
        }
        if system:
            api_kwargs["system"] = system
        if tools:
            api_kwargs["tools"] = tools

        response = await self._client.messages.create(**api_kwargs)

        text_parts = []
        tool_calls = []
        thinking_parts = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        args=block.input,
                    )
                )
            elif block.type == "thinking":
                thinking_parts.append(block.thinking)

        return LLMResponse(
            text="".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            thinking="".join(thinking_parts) if thinking_parts else None,
            raw=response,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[LLMResponse]:
        self._ensure_client()

        inline_system, claude_messages = _messages_to_claude_format(messages)
        system = system_instruction or inline_system

        api_kwargs = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": claude_messages,
            "temperature": temperature,
        }
        if system:
            api_kwargs["system"] = system
        if tools:
            api_kwargs["tools"] = tools

        async with self._client.messages.stream(**api_kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield LLMResponse(text=event.delta.text, is_partial=True)
                    elif event.delta.type == "input_json_delta":
                        # Tool input streaming  - accumulate externally if needed
                        pass
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        yield LLMResponse(
                            tool_calls=[
                                ToolCall(
                                    id=event.content_block.id,
                                    name=event.content_block.name,
                                    args={},
                                )
                            ],
                            is_partial=True,
                        )

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
