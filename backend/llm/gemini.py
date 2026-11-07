"""
Gemini LLM provider.

Wraps the Google GenAI SDK behind the BaseLLMProvider interface.
Also implements BaseVoiceProvider for Gemini Native Audio (Live API).
"""

import asyncio
import time
from typing import AsyncIterator, Optional

from services.tools import ServiceError

from .base import (
    GENERIC_FAILURE,
    BaseLLMProvider,
    BaseVoiceProvider,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
    log_provider_failure,
    log_provider_retry,
)

KEY_STATUSES = ("UNAUTHENTICATED", "PERMISSION_DENIED", "ACCESS_TOKEN_TYPE_UNSUPPORTED")
# One retry when Google is overloaded (live run, 7 Nov 2026: 503 UNAVAILABLE on a plain "Hi").
RETRY_CODES = (500, 503)
RETRY_DELAY = 1.5
# The retry must fit in the caller's per-request timeout; skip it when less than this remains.
RETRY_MIN_REMAINING = 10.0
DEFAULT_BUDGET = 45.0


def _thinking_config(types, thinking, model=""):
    """Thoughts when asked for; otherwise LOW thinking on Gemini 3 models.

    The live run (7 Nov 2026) showed the model's default thinking pushing a plain "Hi"
    past the 45 s chat timeout, so short chat asks for LOW explicitly. ``thinking_level``
    exists for Gemini 3 models only (older ones take a thinking budget), so any other model
    keeps its default (None).
    """
    if thinking:
        return types.ThinkingConfig(include_thoughts=True)
    if str(model).removeprefix("models/").startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return None


def _retryable(exc):
    """Only an overloaded or failing Google server: never 4xx, timeouts or network errors."""
    from google.genai import errors

    return isinstance(exc, errors.ServerError) and exc.code in RETRY_CODES


def _key(api_key):
    if api_key:
        return api_key
    from services.capability_profiles import provider_key

    return provider_key()


def _messages_to_gemini_contents(messages: list[Message]) -> list:
    """Convert our Message objects to Gemini content format."""
    from google.genai import types

    contents = []
    for msg in messages:
        original = next((att['content'] for att in msg.attachments
                         if att.get('type') == 'provider_content'), None)
        if original is not None:
            contents.append(original)
            continue
        if msg.role == MessageRole.SYSTEM:
            continue  # System instruction is passed separately in Gemini

        role = "user" if msg.role in (MessageRole.USER, MessageRole.TOOL) else "model"

        parts = []
        if msg.content:
            parts.append(types.Part(text=msg.content))

        # Handle multimodal attachments
        for att in msg.attachments:
            if att.get("type") == "image":
                parts.append(
                    types.Part.from_bytes(
                        data=att["data"],
                        mime_type=att.get("mime_type", "image/jpeg"),
                    )
                )

        if msg.role == MessageRole.TOOL:
            parts = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=msg.name,
                        id=msg.tool_call_id,
                        response={"result": msg.content},
                    )
                )
            ]

        contents.append(types.Content(role=role, parts=parts))
    return contents


def _extract_tool_calls(candidate) -> list[ToolCall]:
    """Extract tool calls from a Gemini response candidate."""
    calls = []
    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if part.function_call:
                calls.append(
                    ToolCall(
                        id=getattr(part.function_call, "id", "") or "",
                        name=part.function_call.name,
                        args=dict(part.function_call.args) if part.function_call.args else {},
                    )
                )
    return calls


def diagnose(exc):
    """(HTTP status, Google ``status``, reason tag) for a google.genai or transport error."""
    try:
        from google.genai import errors
    except ImportError:
        errors = None
    if errors is not None and isinstance(exc, errors.APIError):
        status = exc.code if isinstance(exc.code, int) else None
        kind = str(exc.status) if exc.status else None
        upper = (kind or "").upper()
        # Only for choosing a reason: the message is never logged or shown.
        text = f"{exc.message or ''} {exc.details or ''}".lower()
        if (status == 400 or upper == "FAILED_PRECONDITION") and "not supported" in text and (
            "location" in text or "region" in text or "country" in text
        ):
            return status, kind, "region"
        if (
            status in (401, 403)
            or upper in KEY_STATUSES
            or (status == 400 and ("api key not valid" in text or "api_key_invalid" in text))
        ):
            return status, kind, "api_key_invalid"
        if status == 404 or upper == "NOT_FOUND":
            return status, kind, "model_not_found"
        if status == 429 or upper == "RESOURCE_EXHAUSTED":
            return status, kind, "quota"
        if status is not None and status >= 500:
            return status, kind, "unavailable"
        return status, kind, None
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return None, None, "timeout"
        network = isinstance(exc, (httpx.TransportError, OSError))
    except ImportError:
        network = isinstance(exc, OSError)
    if network:
        from services.secrets import classify_exception

        return None, None, "tls" if classify_exception(exc) == "tls_error" else "network"
    return None, None, None


def map_error(exc, model=None):
    """Gemini SDK/transport failure -> ServiceError with a plain message; never echoes SDK text."""
    _, _, reason = diagnose(exc)
    if reason == "api_key_invalid":
        return ServiceError(
            "provider_key_invalid",
            "Google rejected your Gemini key. Replace it in Preferences > AI.",
        )
    if reason == "region":
        return ServiceError(
            "provider_region", "Gemini isn't available in your region with this key."
        )
    if reason == "model_not_found":
        return ServiceError(
            "provider_model_not_found",
            "Gemini doesn't offer the model JARVIS asked for"
            + (f" ({model})." if model else "."),
        )
    if reason == "quota":
        return ServiceError(
            "provider_rate_limited",
            "Gemini's quota or rate limit is used up. Try again later, or check your plan "
            "in Google AI Studio.",
        )
    if reason == "unavailable":
        return ServiceError(
            "provider_unavailable", "Gemini is temporarily unavailable. Try again shortly."
        )
    if reason == "timeout":
        return ServiceError("provider_timeout", "The AI request timed out. Try again.")
    if reason == "tls":
        return ServiceError(
            "provider_network",
            "Couldn't make a secure connection to Gemini. A proxy or antivirus may be "
            "intercepting HTTPS.",
        )
    if reason == "network":
        return ServiceError(
            "provider_network", "Couldn't reach Gemini. Check your internet connection."
        )
    return ServiceError("provider_failed", GENERIC_FAILURE)


def provider_error(exc, model=None):
    """Log one safe diagnostic line for ``exc`` and return its ServiceError."""
    status, kind, reason = diagnose(exc)
    log_provider_failure("gemini", exc, status, kind, reason)
    return map_error(exc, model)


def _is_sdk_error(exc):
    """google.genai API errors and transport failures; other exceptions propagate as is."""
    return diagnose(exc)[2] is not None or type(exc).__module__.startswith("google.genai")


def _declaration(declaration):
    """A dict declaration's JSON Schema goes in ``parameters_json_schema``.

    ``parameters`` only takes Google's OpenAPI subset (no "uuid" format, no
    ``additionalProperties``), so dispatcher schemas sent there fail with a 400.
    """
    if (
        isinstance(declaration, dict)
        and "parameters" in declaration
        and "parameters_json_schema" not in declaration
    ):
        adapted = {key: value for key, value in declaration.items() if key != "parameters"}
        adapted["parameters_json_schema"] = declaration["parameters"]
        return adapted
    return declaration


def gemini_tools(tools):
    """Adapt dict tools' function declarations; google.genai types objects pass through."""
    adapted = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("function_declarations"), list):
            tool = {
                **tool,
                "function_declarations": [
                    _declaration(item) for item in tool["function_declarations"]
                ],
            }
        adapted.append(tool)
    return adapted


class GeminiProvider(BaseLLMProvider):
    """Gemini provider for text generation and tool calling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.8-flash",
    ):
        self._api_key = _key(api_key)
        self._model = model
        self.__client = None

    @property
    def _client(self):
        if self.__client is None:
            from google import genai

            from services.tls import genai_http_options

            self.__client = genai.Client(
                api_key=self._api_key,
                http_options=genai_http_options(retry_options={"attempts": 1}),
            )
        return self.__client

    @property
    def name(self) -> str:
        return "gemini"

    async def close(self):
        if self.__client is not None:
            await self.__client.aio.aclose()
            self.__client = None

    async def generate(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if kwargs.get("max_output_tokens") is not None:
            config.max_output_tokens = kwargs["max_output_tokens"]
        if tools:
            config.tools = gemini_tools(tools)
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        config.thinking_config = _thinking_config(types, kwargs.get("thinking", False), self._model)

        contents = _messages_to_gemini_contents(messages)

        # The budget is the caller's timeout for this call (ConversationService passes its
        # own), measured from here: the caller's asyncio.wait_for starts at the same moment.
        budget = kwargs.get("budget") or DEFAULT_BUDGET
        started = time.monotonic()
        retried = False
        while True:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as exc:
                remaining = budget - (time.monotonic() - started) - RETRY_DELAY
                if not retried and _retryable(exc) and remaining >= RETRY_MIN_REMAINING:
                    retried = True
                    status, kind, _ = diagnose(exc)
                    log_provider_retry("gemini", status, kind)
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                if _is_sdk_error(exc):
                    raise provider_error(exc, self._model) from exc
                raise

        if not response.candidates:
            return LLMResponse(raw=response)

        candidate = response.candidates[0]
        text_parts = []
        thinking_parts = []

        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if not part.text:
                    continue
                if getattr(part, "thought", False):
                    thinking_parts.append(part.text)
                else:
                    text_parts.append(part.text)

        return LLMResponse(
            text="".join(text_parts) if text_parts else None,
            tool_calls=_extract_tool_calls(candidate),
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
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if kwargs.get("max_output_tokens") is not None:
            config.max_output_tokens = kwargs["max_output_tokens"]
        if tools:
            config.tools = gemini_tools(tools)
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        config.thinking_config = _thinking_config(types, kwargs.get("thinking", False), self._model)

        contents = _messages_to_gemini_contents(messages)

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                for response in _chunk_responses(chunk):
                    yield response
        except Exception as exc:
            if _is_sdk_error(exc):
                raise provider_error(exc, self._model) from exc
            raise


def _chunk_responses(chunk):
    """Partial LLMResponses for one streamed chunk."""
    if not chunk.candidates:
        return
    candidate = chunk.candidates[0]
    if not candidate.content or not candidate.content.parts:
        return
    for part in candidate.content.parts:
        if part.function_call:
            yield LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=getattr(part.function_call, "id", "") or "",
                        name=part.function_call.name,
                        args=dict(part.function_call.args) if part.function_call.args else {},
                    )
                ],
                is_partial=True,
                raw=chunk,
            )
        elif part.text:
            if getattr(part, "thought", False):
                yield LLMResponse(thinking=part.text, is_partial=True, raw=chunk)
            else:
                yield LLMResponse(text=part.text, is_partial=True, raw=chunk)


class GeminiVoiceProvider(BaseVoiceProvider):
    """Gemini Native Audio (Live API) for real-time voice conversation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "models/gemini-2.5-flash-native-audio-preview-12-2025",
    ):
        from google import genai

        from services.tls import genai_http_options

        self._api_key = _key(api_key)
        self._model = model
        self._client = genai.Client(
            http_options=genai_http_options(api_version="v1beta"),
            api_key=self._api_key,
        )
        self._session = None

    async def connect_voice(
        self,
        system_instruction: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        voice_name: Optional[str] = None,
        **kwargs,
    ):
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=system_instruction,
        )
        if kwargs.get("max_output_tokens") is not None:
            config.max_output_tokens = kwargs["max_output_tokens"]
        if tools:
            config.tools = tools
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        if voice_name:
            config.speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            )

        self._session = await self._client.aio.live.connect(
            model=self._model,
            config=config,
        )

    async def send_audio(self, audio_data: bytes, mime_type: str = "audio/pcm"):
        if self._session:
            await self._session.send(
                input={"data": audio_data, "mime_type": mime_type},
                end_of_turn=False,
            )

    async def send_text(self, text: str):
        if self._session:
            await self._session.send(input=text, end_of_turn=True)

    async def send_image(self, image_data: bytes, mime_type: str = "image/jpeg"):
        """Send an image frame to the live session."""
        if self._session:
            await self._session.send(
                input={"data": image_data, "mime_type": mime_type},
                end_of_turn=False,
            )

    async def receive(self) -> AsyncIterator[LLMResponse]:
        if not self._session:
            return

        turn = self._session.receive()
        async for response in turn:
            result = LLMResponse(is_partial=True, raw=response)

            # Audio data
            if data := response.data:
                result.audio_data = data

            # Transcriptions
            if response.server_content:
                sc = response.server_content
                if sc.input_transcription and sc.input_transcription.text:
                    result.text = sc.input_transcription.text
                    # Tag as user transcription via raw
                if sc.output_transcription and sc.output_transcription.text:
                    result.text = sc.output_transcription.text

            # Tool calls
            if response.tool_call:
                for fc in response.tool_call.function_calls:
                    result.tool_calls.append(
                        ToolCall(
                            id=getattr(fc, "id", "") or "",
                            name=fc.name,
                            args=dict(fc.args) if fc.args else {},
                        )
                    )

            yield result

    async def send_tool_result(self, result: ToolResult):
        from google.genai import types

        if self._session:
            fn_response = types.FunctionResponse(
                id=result.tool_call_id,
                name=result.name,
                response=result.result,
            )
            await self._session.send(input=fn_response, end_of_turn=True)

    async def disconnect_voice(self):
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    @property
    def session(self):
        """Direct access to the underlying Gemini session for advanced usage."""
        return self._session
