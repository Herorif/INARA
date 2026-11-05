"""STUB call agent until C2 (Gemini Live) exists. Never enabled by default.

Only used when the developer sets ``JARVIS_TELEPHONY_STUB_AGENT=1``: it plays a
short synthesized tone (no recording), holds the line for at most ten seconds
and hangs up. It proves the gateway, stream token and audio path end to end.
"""

import asyncio

from telephony.audio import PHONE_RATE, tone
from telephony.media import StreamClosed

HOLD_SECONDS = 10.0
TONE = (440.0, 0.4)


async def stub_agent(session, hold_seconds=HOLD_SECONDS):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + hold_seconds
    try:
        await session.send(tone(*TONE, rate=PHONE_RATE), PHONE_RATE)
        await session.mark("stub-tone")
        while not session.closed.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            if await session.read(timeout=min(remaining, 1.0)) is None and session.closed.is_set():
                break
    except StreamClosed:
        return
    await session.hangup()
