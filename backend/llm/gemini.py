"""
Gemini LLM provider.

Wraps the Google GenAI SDK behind the BaseLLMProvider interface.
Also implements BaseVoiceProvider for Gemini Native Audio (Live API).
"""

import os
from typing import AsyncIterator, Optional

from dotenv import load_dotenv

from .base import (
    BaseLLMProvider,
    BaseVoiceProvider,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)

load_dotenv()


def _messages_to_gemini_contents(messages: list[Message]) -> list:
    """Convert our Message objects to Gemini content format."""
    from google.genai import types

    contents = []
    for msg in messages:
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


class GeminiProvider(BaseLLMProvider):
    """Gemini provider for text generation and tool calling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ):
        from google import genai

        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model = model
        self._client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=self._api_key,
        )

    @property
    def name(self) -> str:
        return "gemini"

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
        if tools:
            config.tools = tools
        if kwargs.get("thinking", False):
            config.thinking_config = types.ThinkingConfig(include_thoughts=True)

        contents = _messages_to_gemini_contents(messages)

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        if not response.candidates:
            return LLMResponse()

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
        if tools:
            config.tools = tools
        if kwargs.get("thinking", False):
            config.thinking_config = types.ThinkingConfig(include_thoughts=True)

        contents = _messages_to_gemini_contents(messages)

        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=config,
        )

        async for chunk in stream:
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            if not candidate.content or not candidate.content.parts:
                continue

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

        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model = model
        self._client = genai.Client(
            http_options={"api_version": "v1beta"},
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
        if tools:
            config.tools = tools
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
