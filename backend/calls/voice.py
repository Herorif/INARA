"""Optional tool-free live model adapter. No SDK/client/key access at import time."""

import asyncio
from contextlib import asynccontextmanager
import os

from calls.contracts import CALL_INSTRUCTION
from services.capability_profiles import provider_key
from services.tools import ServiceError


def ready():
    model = os.getenv("INARA_CALL_MODEL", "").strip()
    if not provider_key() or not model:
        raise ServiceError("call_voice_setup", "Explicitly configure GEMINI_API_KEY and INARA_CALL_MODEL for the lab.")
    return model


class LiveVoice:
    def __init__(self, session):
        self.session = session

    async def greet(self):
        await self.session.send_realtime_input(
            text="Start the call now. Identify yourself as INARA, an AI assistant taking a message, and ask how you can help."
        )

    async def send(self, pcm):
        from google.genai import types
        await self.session.send_realtime_input(audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))

    async def events(self):
        # receive() ends at each model turn, rather than at the end of the call.
        while True:
            received = False
            async for response in self.session.receive():
                received = True
                if response.tool_call:
                    # An unexpected tool request terminates the call; there is no dispatcher.
                    raise ServiceError("call_tool_rejected", "Callers cannot invoke assistant tools.")
                content = response.server_content
                if not content:
                    continue
                if content.interrupted:
                    yield {"kind": "interrupted"}
                    continue
                for role, value in (("caller", content.input_transcription), ("assistant", content.output_transcription)):
                    if value and value.text:
                        yield {"kind": "transcript", "role": role, "text": value.text}
                turn = content.model_turn
                if turn:
                    for part in turn.parts or []:
                        blob = part.inline_data
                        if blob and blob.data:
                            if blob.mime_type not in ("audio/pcm;rate=24000", "audio/pcm;rate=24000;channels=1"):
                                raise ServiceError("call_voice_format", "The provider changed its audio format.")
                            yield {"kind": "audio", "data": blob.data}
            if not received:
                raise ServiceError("call_voice_closed", "The live voice connection stopped.")


@asynccontextmanager
async def connect_voice():
    model = ready()
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=provider_key(), http_options={"retry_options": {"attempts": 1}})
    try:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"], system_instruction=CALL_INSTRUCTION,
            input_audio_transcription={}, output_audio_transcription={},
            max_output_tokens=256,
        )
        async with client.aio.live.connect(model=model, config=config) as session:
            yield LiveVoice(session)
    finally:
        await asyncio.wait_for(client.aio.aclose(), 5)
