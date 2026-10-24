"""Inert ports for an explicitly labeled offline bridge check. No SDK or devices."""

import asyncio
from contextlib import asynccontextmanager
import time
import uuid
import hashlib

from calls.contracts import BridgeProfile, Observation


def fixture_profile():
    return BridgeProfile(channel="whatsapp_personal", pid=1, executable="C:\\Synthetic\\WhatsApp.exe",
                         sha256="a" * 64, process_start="1", window_class="synthetic",
                         answer_id="answer", decline_id="decline", hangup_id="hangup",
                         caller_id="caller", ended_id="ended", capture_endpoint="synthetic receive",
                         playback_endpoint="synthetic transmit", route_confirmed=True, controls_confirmed=True)


class FixtureControl:
    def __init__(self):
        self.deadline, self.ended = None, False
        self.identity = hashlib.sha256(uuid.uuid4().bytes).hexdigest()

    async def observe(self):
        state = "ended" if self.ended or self.deadline and time.monotonic() >= self.deadline else "active" if self.deadline else "ringing"
        return Observation(state=state, fingerprint=self.identity, caller_hash="c" * 64,
                           view_id=self.identity, process_start="1")

    async def answer(self, expected):
        self.deadline = time.monotonic() + 2.5

    async def hangup(self, expected):
        self.ended = True


class FixtureAudio:
    async def open(self):
        pass

    async def close(self):
        pass

    async def clear(self):
        pass

    async def write(self, data):
        pass

    async def read(self):
        await asyncio.sleep(0.02)
        return b"\x00" * 640


class FixtureVoice:
    async def greet(self):
        pass

    async def send(self, data):
        pass

    async def events(self):
        yield {"kind": "transcript", "role": "caller", "text": "This is a synthetic bridge-check message."}
        yield {"kind": "transcript", "role": "assistant", "text": "This offline simulation leaves a local test record."}
        yield {"kind": "audio", "data": b"\x00" * 960}
        yield {"kind": "interrupted"}
        await asyncio.Event().wait()

    @asynccontextmanager
    async def connection(self):
        yield self
