"""
Audio I/O  - PyAudio stream management, device enumeration, and video capture.

Handles all hardware interaction: microphone input, speaker output, camera frames.
Provider-agnostic  - knows nothing about Gemini or any LLM.
"""

import asyncio
import base64
import io
import math
import platform
import struct
import time
from typing import Optional

import cv2
import PIL.Image
import pyaudio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024


# ---------------------------------------------------------------------------
# Device Enumeration
# ---------------------------------------------------------------------------

def get_input_devices() -> list[tuple[int, str]]:
    """List available audio input devices as (index, name) pairs."""
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    count = info.get("deviceCount", 0)
    devices = []
    for i in range(count):
        dev = p.get_device_info_by_host_api_device_index(0, i)
        if dev.get("maxInputChannels", 0) > 0:
            devices.append((i, dev.get("name", f"Device {i}")))
    p.terminate()
    return devices


def get_output_devices() -> list[tuple[int, str]]:
    """List available audio output devices as (index, name) pairs."""
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    count = info.get("deviceCount", 0)
    devices = []
    for i in range(count):
        dev = p.get_device_info_by_host_api_device_index(0, i)
        if dev.get("maxOutputChannels", 0) > 0:
            devices.append((i, dev.get("name", f"Device {i}")))
    p.terminate()
    return devices


def resolve_input_device(
    pya: pyaudio.PyAudio,
    device_name: Optional[str] = None,
    device_index: Optional[int] = None,
) -> Optional[int]:
    """Resolve an input device by name or index. Returns device index or None for default."""
    resolved = None

    if device_name:
        print(f"[INARA] Attempting to find input device matching: '{device_name}'")
        count = pya.get_device_count()
        for i in range(count):
            try:
                info = pya.get_device_info_by_index(i)
                if info["maxInputChannels"] > 0:
                    name = info.get("name", "")
                    if device_name.lower() in name.lower() or name.lower() in device_name.lower():
                        print(f"[INARA] Resolved input device '{device_name}' to index {i} ({name})")
                        resolved = i
                        break
            except Exception:
                continue

        if resolved is None:
            print(f"[INARA] Could not find device matching '{device_name}'. Checking index...")

    if resolved is None and device_index is not None:
        try:
            resolved = int(device_index)
            print(f"[INARA] Requesting Input Device Index: {resolved}")
        except ValueError:
            print(f"[INARA] Invalid device index '{device_index}', reverting to default.")
            resolved = None

    if resolved is None:
        print("[INARA] Using Default Input Device")

    return resolved


# ---------------------------------------------------------------------------
# Audio Input (Microphone)
# ---------------------------------------------------------------------------

class AudioInput:
    """Manages microphone capture and feeds audio chunks to a queue."""

    def __init__(
        self,
        device_name: Optional[str] = None,
        device_index: Optional[int] = None,
        sample_rate: int = SEND_SAMPLE_RATE,
        chunk_size: int = CHUNK_SIZE,
    ):
        self.device_name = device_name
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self._pya = pyaudio.PyAudio()
        self._stream = None

    async def open(self) -> bool:
        """Open the microphone stream. Returns True on success."""
        resolved = resolve_input_device(self._pya, self.device_name, self.device_index)
        default_info = self._pya.get_default_input_device_info()
        index = resolved if resolved is not None else default_info["index"]

        try:
            self._stream = await asyncio.to_thread(
                self._pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=index,
                frames_per_buffer=self.chunk_size,
            )
            return True
        except OSError as e:
            print(f"[INARA] [ERR] Failed to open audio input stream: {e}")
            print("[INARA] [WARN] Audio features will be disabled. Please check microphone permissions.")
            return False

    async def read_chunk(self) -> Optional[bytes]:
        """Read one chunk of audio data. Returns None if stream is closed."""
        if not self._stream:
            return None
        try:
            kwargs = {"exception_on_overflow": False} if __debug__ else {}
            data = await asyncio.to_thread(self._stream.read, self.chunk_size, **kwargs)
            return data
        except Exception as e:
            print(f"[INARA] [ERR] Error reading audio: {e}")
            return None

    def close(self):
        """Close the microphone stream."""
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None


# ---------------------------------------------------------------------------
# Audio Output (Speaker)
# ---------------------------------------------------------------------------

class AudioOutput:
    """Manages speaker playback from a queue of PCM audio chunks."""

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = RECEIVE_SAMPLE_RATE,
    ):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self._pya = pyaudio.PyAudio()
        self._stream = None

    async def open(self):
        """Open the output audio stream."""
        self._stream = await asyncio.to_thread(
            self._pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=self.sample_rate,
            output=True,
            output_device_index=self.device_index,
        )

    async def play(self, audio_data: bytes):
        """Play a chunk of PCM audio data."""
        if self._stream:
            await asyncio.to_thread(self._stream.write, audio_data)

    async def play_loop(self, queue: asyncio.Queue, on_audio_data=None):
        """Continuously play audio from a queue. Blocks until cancelled."""
        await self.open()
        while True:
            chunk = await queue.get()
            if on_audio_data:
                on_audio_data(chunk)
            await self.play(chunk)

    def close(self):
        """Close the output stream."""
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None


# ---------------------------------------------------------------------------
# Audio Queue Utilities
# ---------------------------------------------------------------------------

def clear_queue(queue: asyncio.Queue) -> int:
    """Drain all items from an asyncio.Queue. Returns count cleared."""
    count = 0
    while not queue.empty():
        try:
            queue.get_nowait()
            count += 1
        except asyncio.QueueEmpty:
            break
    if count > 0:
        print(f"[INARA] [AUDIO] Cleared {count} chunks from playback queue.")
    return count


# ---------------------------------------------------------------------------
# RMS Calculation (for VAD)
# ---------------------------------------------------------------------------

def calculate_rms(data: bytes) -> int:
    """Calculate root mean square of 16-bit PCM audio data."""
    count = len(data) // 2
    if count == 0:
        return 0
    shorts = struct.unpack(f"<{count}h", data)
    sum_squares = sum(s ** 2 for s in shorts)
    return int(math.sqrt(sum_squares / count))


# ---------------------------------------------------------------------------
# Video Capture (Camera)
# ---------------------------------------------------------------------------

class VideoCapture:
    """Captures camera frames and provides them as base64 JPEG payloads."""

    def __init__(self, camera_index: int = 0, max_size: int = 1024):
        self.camera_index = camera_index
        self.max_size = max_size
        self._cap = None

    def _get_backend(self) -> int:
        """Return platform-appropriate OpenCV camera backend."""
        system = platform.system()
        if system == "Darwin":
            return cv2.CAP_AVFOUNDATION
        elif system == "Windows":
            return cv2.CAP_DSHOW
        else:
            return cv2.CAP_V4L2

    async def open(self) -> bool:
        """Open the camera. Returns True on success."""
        backend = self._get_backend()
        self._cap = await asyncio.to_thread(cv2.VideoCapture, self.camera_index, backend)
        if not self._cap.isOpened():
            # Fallback: let OpenCV pick
            self._cap = await asyncio.to_thread(cv2.VideoCapture, self.camera_index)
        return self._cap.isOpened()

    def _capture_frame(self) -> Optional[dict]:
        """Capture a single frame and return as {mime_type, data} payload."""
        if not self._cap:
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(frame_rgb)
        img.thumbnail([self.max_size, self.max_size])
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode()
        return {"mime_type": "image/jpeg", "data": encoded}

    async def get_frame(self) -> Optional[dict]:
        """Async wrapper around frame capture."""
        return await asyncio.to_thread(self._capture_frame)

    async def capture_loop(self, queue: asyncio.Queue, interval: float = 1.0, paused_fn=None):
        """Continuously capture frames into a queue at the given interval."""
        opened = await self.open()
        if not opened:
            print("[INARA] [WARN] Could not open camera.")
            return

        try:
            while True:
                if paused_fn and paused_fn():
                    await asyncio.sleep(0.1)
                    continue
                frame = await self.get_frame()
                if frame is None:
                    break
                await asyncio.sleep(interval)
                await queue.put(frame)
        finally:
            self.close()

    def close(self):
        """Release the camera."""
        if self._cap:
            self._cap.release()
            self._cap = None
