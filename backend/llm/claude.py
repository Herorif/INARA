"""Claude (Anthropic) provider: INARA's brain for chat, planning and tool use.

Request rules for Claude Sonnet 5.5 / Haiku 5.5 (see docs/AI_PROVIDERS.md):
- no temperature, top_p or top_k; adaptive thinking only, depth set by
  ``output_config.effort``; ``tool_choice`` stays at its "auto" default;
- every assistant turn is kept verbatim (thinking blocks and signatures included)
  and replayed unchanged. ``block_binding.prefix_mismatch_behavior: drop_block``
  is the safety net for the rare unavoidable edit (trimmed history, a changed
  tool list), so such a request loses old reasoning instead of failing;
- top-level automatic prompt caching; server-side refusal fallback on Sonnet.

No SDK import, client or key access happens until the first request.
"""

import json
from typing import Any, Optional

from services.tools import ServiceError

from .base import BaseLLMProvider, LLMResponse, MessageRole, ToolCall

MAX_TOKENS = 32_000
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
THINKING_TYPES = ("thinking", "redacted_thinking")
REFUSAL_MESSAGE = (
    "I can't help with that request. Try rephrasing it, or ask for something else."
)


def supports_fallback(model):
    # Claude Haiku 5.5 has no server-side fallback; sending one is pointless or a 400.
    return "haiku" not in str(model)


def anthropic_tools(schemas):
    """Dispatcher ToolSpec schemas -> Anthropic tool definitions, sorted by name."""
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": item["parameters"],
            "eager_input_streaming": True,
        }
        for item in sorted(schemas, key=lambda item: item["name"])
    ]


def message_to_api(message):
    """A plain ``Message`` -> Anthropic message dict (dicts pass through unchanged)."""
    if isinstance(message, dict):
        return message
    if message.role == MessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": message.tool_call_id,
                 "content": message.content}
            ],
        }
    role = {MessageRole.USER: "user", MessageRole.ASSISTANT: "assistant",
            MessageRole.SYSTEM: "system"}[message.role]
    return {"role": role, "content": message.content}


def replayable_blocks(blocks):
    """Apply the fallback echo rule: before the last ``fallback`` block, drop the
    declined attempt's thinking and tool_use blocks; everything else is kept as is."""
    last = max((i for i, block in enumerate(blocks) if block.get("type") == "fallback"),
               default=None)
    if last is None:
        return list(blocks)
    return [
        block
        for index, block in enumerate(blocks)
        if index > last or block.get("type") not in (*THINKING_TYPES, "tool_use")
    ]


def strip_thinking(messages):
    """Copy of ``messages`` without thinking blocks (used once when history is trimmed)."""
    result = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, list):
            message = {**message,
                       "content": [b for b in content if b.get("type") not in THINKING_TYPES]}
            if not message["content"]:
                continue
        result.append(message)
    return result


def usage_counts(message):
    """Token counters summed across attempts (``usage.iterations`` when present)."""
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
              "cache_read_input_tokens")
    iterations = [
        item for item in (getattr(usage, "iterations", None) or [])
        if getattr(item, "type", None) in ("message", "fallback_message")
    ]
    sources = iterations or [usage]
    counts = {}
    for name in fields:
        values = [getattr(item, name, None) for item in sources]
        values = [value for value in values if type(value) is int and value >= 0]
        if values:
            counts[name] = sum(values)
    if counts:
        counts["total_tokens"] = sum(counts.values())
    if iterations and any(getattr(item, "type", None) == "fallback_message"
                          for item in iterations):
        counts["fallback_attempts"] = sum(
            1 for item in iterations if item.type == "fallback_message")
    return counts or None


def map_error(exc):
    """SDK exception -> ServiceError with a plain message; never echoes SDK text."""
    import anthropic

    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ServiceError(
            "provider_key_invalid",
            "Claude rejected the Anthropic API key. Update it in Setup (AI providers) "
            "or Preferences.",
        )
    if isinstance(exc, anthropic.RateLimitError):
        wait = None
        try:
            wait = int(float(exc.response.headers.get("retry-after", "")))
        except (AttributeError, TypeError, ValueError):
            pass
        return ServiceError(
            "provider_rate_limited",
            "Claude is limiting requests right now. Try again "
            + (f"in {wait} seconds." if wait and 0 < wait <= 3600 else "in a minute."),
        )
    if isinstance(exc, anthropic.APITimeoutError):
        return ServiceError("provider_timeout", "The AI request timed out. Try again.")
    if isinstance(exc, anthropic.APIConnectionError):
        from services.secrets import classify_exception

        if classify_exception(exc) == "tls_error":
            return ServiceError(
                "provider_network",
                "Couldn't make a secure connection to Claude. A proxy or antivirus may be "
                "intercepting HTTPS.",
            )
        return ServiceError(
            "provider_network", "Couldn't reach Claude. Check your internet connection."
        )
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return ServiceError(
            "provider_unavailable", "Claude is temporarily unavailable. Try again shortly."
        )
    return ServiceError("provider_failed", "The AI provider could not complete this request.")


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider. ``generate`` streams and returns the final turn."""

    def __init__(self, api_key=None, model="claude-sonnet-5-5", effort="medium", client=None):
        if not api_key:
            from services.capability_profiles import anthropic_key

            api_key = anthropic_key()
        self._api_key = api_key
        self._model = model
        self.effort = effort
        self._client = client

    @property
    def name(self) -> str:
        return "claude"

    def _ensure_client(self):
        if self._client is None:
            import anthropic

            from services.tls import provider_ssl_context

            # SDK 1.x+/2.x run on httpx2: use the SDK's own client wrapper, never httpx.
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                http_client=anthropic.DefaultAsyncHttpxClient(verify=provider_ssl_context()),
            )
        return self._client

    def request(self, messages, tools=None, system_instruction=None, effort=None,
                max_output_tokens=None):
        """The exact keyword arguments sent to ``client.beta.messages.stream``."""
        effort = effort or self.effort
        if effort not in EFFORTS:
            raise ValueError(f"Unknown effort: {effort}")
        if tools and isinstance(tools[0], dict) and "function_declarations" in tools[0]:
            tools = anthropic_tools(tools[0]["function_declarations"])
        params = {
            "model": self._model,
            "max_tokens": min(MAX_TOKENS, max_output_tokens) if max_output_tokens else MAX_TOKENS,
            "messages": [message_to_api(message) for message in messages],
            "thinking": THINKING,
            "output_config": {"effort": effort},
            "cache_control": {"type": "ephemeral"},
            "betas": [THINKING_BINDING_BETA],
        }
        if system_instruction:
            params["system"] = system_instruction
        if tools:
            params["tools"] = tools
        if supports_fallback(self._model):
            params["betas"] = [THINKING_BINDING_BETA, SERVER_FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def generate(self, messages: list, tools: Optional[list[dict]] = None,
                       system_instruction: Optional[str] = None, temperature: float = 1.0,
                       **kwargs) -> LLMResponse:
        # ``temperature`` exists only for the shared interface; it is never sent.
        final = None
        async for response in self.stream(messages, tools, system_instruction, **kwargs):
            if not response.is_partial:
                final = response
        return final

    async def stream(self, messages, tools=None, system_instruction=None,
                     temperature: float = 1.0, **kwargs):
        """Yield text deltas as they arrive, then the final turn (``is_partial`` False).

        ``on_text`` (an async callable) receives the same deltas, for callers that
        go through ``generate``.
        """
        params = self.request(
            messages, tools, system_instruction, kwargs.get("effort"),
            kwargs.get("max_output_tokens"),
        )
        on_text = kwargs.get("on_text")
        client = self._ensure_client()
        try:
            async with client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "text" and event.text:
                        if on_text is not None:
                            await on_text(event.text)
                        yield LLMResponse(text=event.text, is_partial=True)
                message = await stream.get_final_message()
        except ServiceError:
            raise
        except ValueError as exc:
            # Tool input JSON the SDK could not parse at all (eager input streaming).
            raise ServiceError(
                "provider_failed", "Claude sent an unreadable tool request. Try again."
            ) from exc
        except Exception as exc:
            import anthropic

            if isinstance(exc, anthropic.AnthropicError):
                raise map_error(exc) from exc
            raise
        yield self.parse(message)

    def parse(self, message: Any) -> LLMResponse:
        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            # Branch on stop_reason before reading content; the category stays private.
            raise ServiceError("provider_refused", REFUSAL_MESSAGE)
        blocks = replayable_blocks([block.to_dict() for block in message.content])
        text = "".join(block["text"] for block in blocks if block.get("type") == "text")
        calls = [
            ToolCall(block["id"], block["name"], block.get("input") or {})
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        if stop == "max_tokens" and calls:
            # A truncated tool input parses as a valid partial object; never run it.
            raise ServiceError(
                "provider_truncated",
                "The answer was cut off before an action was complete. Try a smaller request.",
            )
        return LLMResponse(
            text=text or None, tool_calls=calls, raw=message, content_blocks=blocks,
            stop_reason=stop,
        )

    async def close(self):
        if self._client is not None:
            await self._client.close()
            self._client = None


def tool_result_content(output):
    return json.dumps(output, default=str, sort_keys=True)

