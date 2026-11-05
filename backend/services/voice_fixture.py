"""Inert Live provider for offline verification: no network, no model, no stored audio.

The harness selects it explicitly (``app.voice.connector = FixtureLive()``). A finished
push-to-talk hold, or enough hands-free audio, produces one scripted exchange: a user
caption, a soft 24 kHz tone streamed in 100 ms chunks, a JARVIS caption, usage counts and
turn completion. A new push-to-talk hold while the tone is streaming interrupts it.
"""

import asyncio
from contextlib import asynccontextmanager
import math
import struct

USER_CAPTION = "Fixture question - no speech recognition ran"
JARVIS_CAPTION = "Fixture spoken answer - no AI provider ran"
CHUNK_SAMPLES = 2400  # 100 ms at 24 kHz


def tone(index, samples=CHUNK_SAMPLES, rate=24000, frequency=440.0, amplitude=0.05):
    start = index * samples
    return b"".join(
        struct.pack("<h", int(32767 * amplitude * math.sin(2 * math.pi * frequency * (start + n) / rate)))
        for n in range(samples)
    )


class FixtureLiveSession:
    def __init__(self, config, chunks, pace):
        from google.genai import types

        self.types = types
        self.config = config
        self.chunks, self.pace = chunks, pace
        detection = config.realtime_input_config.automatic_activity_detection
        self.hands_free = not (detection and detection.disabled)
        self.messages = asyncio.Queue()
        self.sent = []
        self.heard = 0
        self.reply_task = None
        self.closed = False
        self.messages.put_nowait(
            types.LiveServerMessage(
                session_resumption_update=types.LiveServerSessionResumptionUpdate(
                    new_handle="fixture-resumption-handle", resumable=True
                )
            )
        )

    def content(self, **values):
        return self.types.LiveServerMessage(server_content=self.types.LiveServerContent(**values))

    def speaking(self):
        return self.reply_task is not None and not self.reply_task.done()

    async def send_realtime_input(self, **values):
        (kind,) = values
        self.sent.append(kind)
        if kind == "activity_start":
            self.heard = 0
            if self.speaking():
                self.reply_task.cancel()
                self.messages.put_nowait(self.content(interrupted=True))
        elif kind == "activity_end":
            self.reply()
        elif kind == "audio":
            self.heard += 1
            if self.hands_free and self.heard >= 10 and not self.speaking():
                self.heard = 0
                self.reply()

    def reply(self):
        if not self.speaking():
            self.reply_task = asyncio.create_task(self.script())

    async def script(self):
        types = self.types
        self.messages.put_nowait(
            self.content(input_transcription=types.Transcription(text=USER_CAPTION))
        )
        for index in range(self.chunks):
            self.messages.put_nowait(
                self.content(
                    model_turn=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(data=tone(index), mime_type="audio/pcm;rate=24000")
                            )
                        ],
                    )
                )
            )
            if index == 0:
                self.messages.put_nowait(
                    self.content(output_transcription=types.Transcription(text=JARVIS_CAPTION))
                )
            await asyncio.sleep(self.pace)
        self.messages.put_nowait(
            types.LiveServerMessage(
                usage_metadata=types.UsageMetadata(
                    prompt_token_count=40,
                    response_token_count=60,
                    total_token_count=100,
                    prompt_tokens_details=[
                        types.ModalityTokenCount(modality=types.MediaModality.AUDIO, token_count=40)
                    ],
                    response_tokens_details=[
                        types.ModalityTokenCount(modality=types.MediaModality.AUDIO, token_count=60)
                    ],
                )
            )
        )
        self.messages.put_nowait(self.content(turn_complete=True))

    async def send_tool_response(self, **values):
        self.sent.append("tool_response")

    async def receive(self):
        while True:
            message = await self.messages.get()
            yield message
            content = message.server_content
            if content and (content.turn_complete or content.interrupted):
                return

    async def close(self):
        self.closed = True
        if self.reply_task:
            self.reply_task.cancel()


class FixtureLive:
    """Connector with the same signature as ``services.voice.connect_live``."""

    def __init__(self, chunks=30, pace=0.1):
        self.chunks, self.pace = chunks, pace
        self.sessions = []

    @asynccontextmanager
    async def __call__(self, model, config):
        session = FixtureLiveSession(config, self.chunks, self.pace)
        self.sessions.append(session)
        try:
            yield session
        finally:
            await session.close()
