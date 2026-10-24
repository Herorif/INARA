"""Offline English message-taking: local Vosk recognition and Windows SAPI speech.

Bounded structured baseline with an optional evaluated local-model interpreter.
No external network, owner context, tools or automatic downloads. Half-duplex.
"""

import asyncio
from contextlib import asynccontextmanager
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import time
import wave

from services.tools import ServiceError

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".tools/local-voice/vosk-model-small-en-us-0.15"
SYNTH = ROOT / "scripts/local-call-speech.ps1"
QUESTIONS = (
    "May I have your name?",
    "What is the reason for your call?",
    "What message would you like me to leave? Please do not share passwords or verification codes.",
    "What callback details would you like to leave? You may say none.",
)


def ready():
    if os.name != "nt" or importlib.util.find_spec("vosk") is None:
        raise ServiceError("call_local_setup", "Install the optional local Vosk adapter on Windows first.")
    if MODEL.resolve() != MODEL or not all((MODEL / name).is_file() for name in ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst")) or not SYNTH.is_file():
        raise ServiceError("call_local_model_missing", "Provide the explicit local English model and Windows speech helper. No download or cloud fallback occurs.")
    return str(MODEL)


class MessageDialogue:
    def __init__(self):
        self.fields = []
        self.confirmed = False

    def reply(self, text):
        text = " ".join(text.split())[:160]
        if not text:
            return "I could not understand that. " + (QUESTIONS[len(self.fields)] if len(self.fields) < 4 else "Please say yes to confirm, or no to start again.")
        if self.confirmed:
            return "Your message is recorded for the owner. Please hang up when you are ready."
        if len(self.fields) < 4:
            self.fields.append(text)
            if len(self.fields) < 4:
                return QUESTIONS[len(self.fields)]
            name, reason, message, callback = self.fields
            return f"I heard: name, {name}. Reason, {reason}. Message, {message}. Callback, {callback}. Is that correct? Please say yes or no."
        answer = text.lower().strip(".!?,")
        words = set(answer.split())
        if words & {"no", "incorrect", "wrong", "not"}:
            self.fields.clear()
            return "Let us start again. " + QUESTIONS[0]
        if answer in {"yes", "correct", "yes correct", "that is correct", "yes that is correct", "that's correct"}:
            self.confirmed = True
            return "Thank you. I have recorded your confirmed message for the owner. I have not sent a reply or made a callback. Please hang up when you are ready."
        return "Please say yes to confirm the details, or no to start again."


async def synthesize(text):
    executable = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    process = await asyncio.create_subprocess_exec(str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SYNTH), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=0x08000000 if os.name == "nt" else 0)
    try:
        async with asyncio.timeout(20):
            stdout, _ = await process.communicate(json.dumps({"text": text}).encode("utf-8"))
        if process.returncode or len(stdout) > 4_194_304:
            raise ServiceError("call_local_speech_failed", "Local Windows speech synthesis failed.")
        with wave.open(io.BytesIO(stdout), "rb") as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 24000, "NONE"):
                raise ServiceError("call_local_speech_format", "Expected 24 kHz mono PCM speech.")
            return stream.readframes(stream.getnframes())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class LocalVoice:
    def __init__(self, recognizer, synth=synthesize, *, dialogue=None):
        self.recognizer, self.synth = recognizer, synth
        self.dialogue = dialogue or MessageDialogue()
        self.queue = asyncio.Queue(maxsize=128)
        self.speaking_until = 0.0
        self.frames = 0
        self.closed = False
        self.reply_task = None
        self.generating = False

    async def say(self, text):
        data = await self.synth(text)
        if not data or len(data) % 2:
            raise ServiceError("call_local_speech_format", "Invalid local speech PCM.")
        self.speaking_until = time.monotonic() + len(data) / 48000 + 0.4
        await self.queue.put({"kind": "transcript", "role": "assistant", "text": text})
        for offset in range(0, len(data), 9600):
            await self.queue.put({"kind": "audio", "data": data[offset:offset + 9600]})

    async def greet(self):
        await self.say("Hello, I am INARA, an AI assistant taking a message for the owner. " + QUESTIONS[0])

    async def send(self, pcm):
        if self.closed or len(pcm) != 640:
            raise ServiceError("call_local_audio_format", "Expected one 20 millisecond caller frame.")
        if self.reply_task is not None and self.reply_task.done():
            self.reply_task.result()
            self.reply_task = None
        if self.generating or time.monotonic() < self.speaking_until:
            return  # Initial local mode deliberately waits for assistant speech to finish.
        self.frames += 1
        accepted = await asyncio.to_thread(self.recognizer.AcceptWaveform, pcm)
        if accepted:
            result = json.loads(self.recognizer.Result())
            self.frames = 0
            text = result.get("text", "")
            if text:
                await self.queue.put({"kind": "transcript", "role": "caller", "text": text[:1000]})
                self.generating = True
                self.reply_task = asyncio.create_task(self.respond(text))
        elif self.frames >= 1500:
            raise ServiceError("call_local_utterance_limit", "The local caller utterance exceeded thirty seconds.")

    async def events(self):
        while not self.closed:
            yield await self.queue.get()

    async def respond(self, text):
        try:
            reply = self.dialogue.reply(text)
            await self.say(await reply if inspect.isawaitable(reply) else reply)
        finally:
            self.generating = False

    async def close(self):
        self.closed = True
        if self.reply_task is not None:
            self.reply_task.cancel()
            await asyncio.gather(self.reply_task, return_exceptions=True)
        while not self.queue.empty():
            self.queue.get_nowait()
        self.recognizer = None


@asynccontextmanager
async def connect_voice(*, conversational=False):
    from contextlib import AsyncExitStack
    path = ready()
    await synthesize("Ready.")  # Validate installed offline speech before a call can be answered.
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    model = await asyncio.to_thread(Model, path)  # Explicit existing path prevents downloads.
    async with AsyncExitStack() as stack:
        dialogue = None
        if conversational:
            from calls.local_model import LocalModel, ModelDialogue, require_evaluation
            require_evaluation()
            inference = await stack.enter_async_context(LocalModel())
            dialogue = ModelDialogue(inference)
        voice = LocalVoice(KaldiRecognizer(model, 16000), dialogue=dialogue)
        try:
            yield voice
        finally:
            await voice.close()
