"""Two explicitly enrolled WASAPI virtual endpoints; never system/default audio."""

import asyncio
from collections import deque
import threading

from services.tools import ServiceError


def resolve_endpoints(sd, profile):
    devices, hosts = sd.query_devices(), sd.query_hostapis()
    def select(name, direction):
        matches = [index for index, item in enumerate(devices)
                   if item["name"] == name and item[f"max_{direction}_channels"] >= 1
                   and hosts[item["hostapi"]]["name"] == "Windows WASAPI"]
        if len(matches) != 1:
            raise ServiceError("call_audio_ambiguous", "Each dedicated WASAPI endpoint must match exactly once.")
        return matches[0]
    return select(profile.capture_endpoint, "input"), select(profile.playback_endpoint, "output")


class DedicatedAudio:
    def __init__(self, profile, module=None):
        self.profile, self.module = profile, module
        self.input = self.output = None
        self.frames = asyncio.Queue(maxsize=16)
        self.playback = deque()
        self.queued = 0
        self.lock = threading.Lock()
        self.failure = None
        self.closed = True
        self.capturing = False
        self.playback_timeout = 2.5

    async def open(self):
        if not self.profile.route_confirmed:
            raise ServiceError("call_audio_unverified", "Manually prove dedicated routing before arming.")
        if self.module is None:
            try:
                import sounddevice
            except ImportError as exc:
                raise ServiceError("call_audio_missing", "The optional sounddevice adapter is not installed.") from exc
            self.module = sounddevice
        sd, self.loop = self.module, asyncio.get_running_loop()
        capture, playback = resolve_endpoints(sd, self.profile)
        sd.check_input_settings(device=capture, channels=1, dtype="int16", samplerate=16000)
        sd.check_output_settings(device=playback, channels=1, dtype="int16", samplerate=24000)
        self.closed = False
        def receive(data, frames, timestamp, status):
            if self.closed:
                return
            self.loop.call_soon_threadsafe(self.enqueue, bytes(data), bool(status))
        def render(data, frames, timestamp, status):
            data[:] = b"\x00" * len(data)
            with self.lock:
                if self.closed:
                    return
                if status and self.capturing:
                    self.failure = "call_audio_stalled"
                offset = 0
                while self.playback and offset < len(data):
                    chunk = self.playback.popleft()
                    count = min(len(chunk), len(data) - offset)
                    data[offset:offset + count] = chunk[:count]
                    self.queued -= count
                    offset += count
                    if count < len(chunk):
                        self.playback.appendleft(chunk[count:])
        try:
            self.input = sd.RawInputStream(device=capture, channels=1, dtype="int16", samplerate=16000, blocksize=320, callback=receive)
            self.output = sd.RawOutputStream(device=playback, channels=1, dtype="int16", samplerate=24000, blocksize=480, callback=render)
            self.output.start()
            self.input.start()
        except BaseException:
            await self.close()
            raise

    def enqueue(self, data, failed=False):
        if self.closed or not self.capturing:
            return
        if failed or len(data) != 640 or self.frames.full():
            self.failure = "call_audio_stalled"
            return
        self.frames.put_nowait(data)

    def activate(self):
        self.capturing = True

    def check(self):
        if self.closed or self.failure:
            raise ServiceError(self.failure or "call_audio_closed", "The dedicated call audio route stopped.")

    async def read(self):
        self.check()
        try:
            data = await asyncio.wait_for(self.frames.get(), 2)
        except TimeoutError as exc:
            raise ServiceError("call_audio_stalled", "The call receive route stopped producing frames.") from exc
        self.check()
        return data

    async def write(self, data):
        self.check()
        if not data or len(data) % 2 or len(data) > 96000:
            raise ServiceError("call_audio_format", "Invalid PCM output from voice provider.")
        # Live models can emit faster than real-time. Apply backpressure instead
        # of dropping speech or rejecting a healthy device during a normal burst.
        try:
            async with asyncio.timeout(self.playback_timeout):
                while True:
                    self.check()
                    with self.lock:
                        if self.queued + len(data) <= 96000:
                            self.playback.append(bytes(data))
                            self.queued += len(data)
                            return
                    await asyncio.sleep(0.01)
        except TimeoutError as exc:
            raise ServiceError("call_audio_stalled", "Assistant playback stalled with two seconds buffered.") from exc

    async def clear(self):
        with self.lock:
            self.playback.clear()
            self.queued = 0

    async def close(self):
        self.closed = True
        self.capturing = False
        errors = []
        for stream in (self.input, self.output):
            if stream:
                try:
                    stream.abort()
                except Exception as exc:
                    errors.append(exc)
                try:
                    stream.close()
                except Exception as exc:
                    errors.append(exc)
        self.input = self.output = None
        await self.clear()
        while not self.frames.empty():
            self.frames.get_nowait()
        if errors:
            raise ServiceError("call_audio_cleanup", "Audio cleanup failed; check the call client.")
