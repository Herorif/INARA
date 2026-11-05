"""This PC's microphone and speaker for tray voice (J2). Never imported audio at startup.

``sounddevice`` (PortAudio) is imported lazily, on one dedicated audio control thread,
the first time devices are listed or opened; every PortAudio control call (initialize,
query, open, start, abort, close) runs on that thread, so they are serialized and keep
one COM apartment. Streams are raw PCM16 bytes (no numpy). WASAPI shared mode runs at the
device's own mix rate, so the microphone records at the device rate and is resampled to
Live's 16 kHz, and Live's 24 kHz speech is resampled to the speaker's rate
(``telephony.audio.Resampler``; speech quality).

PortAudio callbacks never block and never call into the core: they copy one block into
a bounded deque (dropping the oldest block on overflow, counted) and wake the core loop
with ``call_soon_threadsafe``. Half-duplex echo control lives here too: while JARVIS's
audio is playing, and for ``tail`` seconds after the playback buffer drains,
``speaking()`` is true and the voice service drops microphone frames.

Audio is never logged or stored. Logs carry device names, host APIs, rates and counters.
"""

import asyncio
from array import array
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import importlib
import importlib.util
import re
import sys
import time

from services.audio_contracts import (
    HOST_API_LIMIT,
    NAME_LIMIT,
    SYSTEM_DEFAULT,
    AudioDevicesReport,
    local_devices,
)
from services.live_config import INPUT_RATE, OUTPUT_RATE
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)

PREFERRED_HOST_API = "Windows WASAPI"
BLOCKS_PER_SECOND = 50  # 20 ms device blocks
FRAME_BYTES = INPUT_RATE * 2 * 40 // 1000  # 40 ms of 16 kHz PCM16 per Live frame (as the renderer)
INBOX_BLOCKS = 50  # 1 s of microphone blocks waiting for the core loop
PLAYBACK_BLOCKS = 120 * BLOCKS_PER_SECOND  # at most 2 min of speech buffered ahead
TAIL_SECONDS = 0.3  # microphone stays muted this long after playback drains
STALL_SECONDS = 2.0  # no callbacks for this long: the device is gone
OPEN_GRACE_SECONDS = 3.0  # first callbacks may take a moment after opening
CONTROL_TIMEOUT = 10.0
UNAVAILABLE = (
    "Tray voice needs the sounddevice audio library. Run scripts/bootstrap.ps1 to repair setup."
)
_PRINTABLE = re.compile(r"^[^\x00-\x1f\x7f]+$")
_BIG_ENDIAN = sys.byteorder == "big"
LABELS = {"input": "microphone", "output": "speaker"}


def import_sounddevice():
    """The real backend. ImportError when missing; OSError when PortAudio cannot load."""
    return importlib.import_module("sounddevice")


def installed():
    """Whether the audio library is installed, without importing it."""
    try:
        return importlib.util.find_spec("sounddevice") is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    host_api: str
    inputs: int
    outputs: int
    rate: int
    default_input: bool
    default_output: bool

    def channels(self, kind):
        return self.inputs if kind == "input" else self.outputs

    def is_default(self, kind):
        return self.default_input if kind == "input" else self.default_output

    def entry(self, kind):
        return {
            "name": self.name,
            "host_api": self.host_api,
            "default": self.is_default(kind),
            "channels": self.channels(kind),
            "sample_rate": self.rate,
        }

    def label(self):
        return f"{self.name} ({self.host_api}, {self.rate} Hz)"


def listable(device):
    return (
        bool(_PRINTABLE.match(device.name))
        and len(device.name) <= NAME_LIMIT
        and bool(_PRINTABLE.match(device.host_api))
        and len(device.host_api) <= HOST_API_LIMIT
        and 8000 <= device.rate <= 384000
    )


def resolve(devices, preferred, kind, choice):
    """The device for a saved choice, falling back to the system default: (device, notice)."""
    label = LABELS[kind]
    pool = [item for item in devices if item.channels(kind) > 0]
    home = [item for item in pool if item.host_api == preferred]
    default = next((item for item in home if item.is_default(kind)), None) or next(
        (item for item in pool if item.is_default(kind)), None
    )
    default = default or (home[0] if home else pool[0] if pool else None)
    if default is None:
        raise ServiceError(
            "audio_device_missing", f"No {label} is connected. Connect one and try again."
        )
    if choice == SYSTEM_DEFAULT or not isinstance(choice, dict):
        return default, None
    match = next(
        (
            item
            for item in pool
            if item.name == choice.get("name") and item.host_api == choice.get("host_api")
        ),
        None,
    )
    if match is not None:
        return match, None
    return default, f"The saved {label} is not connected; using the system default."


def _samples(pcm):
    values = array("h")
    values.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if _BIG_ENDIAN:
        values.byteswap()
    return values


def _bytes(values):
    if _BIG_ENDIAN:
        values = array("h", values)
        values.byteswap()
    return values.tobytes()


def downmix(block, channels):
    """Interleaved PCM16 -> mono (the first channel; speech needs no more)."""
    if channels <= 1:
        return bytes(block)
    return _bytes(_samples(block)[0::channels])


def upmix(pcm, channels):
    """Mono PCM16 -> the same sample on every channel."""
    if channels <= 1:
        return pcm
    mono = _samples(pcm)
    wide = array("h", bytes(len(mono) * channels * 2))
    for channel in range(channels):
        wide[channel::channels] = mono
    return _bytes(wide)


class AudioDevices:
    """Device enumeration and the single audio control thread, shared by local sessions."""

    def __init__(self, loader=None, timeout=CONTROL_TIMEOUT):
        self.loader = loader or import_sounddevice
        self.timeout = timeout
        self.backend = None
        self.failure = None
        self.executor = None
        self.open_streams = 0
        self.summary = None  # {"inputs": n, "outputs": n} from the last successful listing

    # --- the audio control thread ---------------------------------------------------------

    async def call(self, function, *args):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(1, thread_name_prefix="jarvis-audio")
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, function, *args), self.timeout
            )
        except TimeoutError as exc:
            logger.warning("The audio system did not answer within %ss", self.timeout)
            raise ServiceError(
                "audio_unavailable", "The audio system is not responding. Restart JARVIS."
            ) from exc

    def close(self):
        executor, self.executor = self.executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def load(self):
        """The backend module (control thread); a failed load is reported as setup state."""
        if self.backend is None:
            try:
                self.backend = self.loader()
            except (ImportError, OSError) as exc:
                self.failure = UNAVAILABLE
                logger.warning("Local audio library unavailable (%s)", type(exc).__name__)
                raise ServiceError("audio_unavailable", UNAVAILABLE) from exc
            self.failure = None
        return self.backend

    def refresh(self):
        """Re-read the system's devices (new USB microphone, changed default) when idle."""
        backend = self.load()
        if self.open_streams:
            return
        terminate = getattr(backend, "_terminate", None)
        initialize = getattr(backend, "_initialize", None)
        if callable(terminate) and callable(initialize):
            try:
                terminate()
            finally:
                initialize()

    def devices(self, refresh=True):
        """(preferred host API name, every device) without opening any (control thread)."""
        backend = self.load()
        error = getattr(backend, "PortAudioError", OSError)
        try:
            if refresh:
                self.refresh()
            hostapis = list(backend.query_hostapis())
            listed = list(backend.query_devices())
        except error as exc:
            logger.warning("Audio devices could not be listed (%s)", type(exc).__name__)
            raise ServiceError(
                "audio_unavailable", "The audio system could not list devices. Try again."
            ) from exc
        names = [str(item.get("name", "")) for item in hostapis]
        if PREFERRED_HOST_API in names:
            preferred = names.index(PREFERRED_HOST_API)
        else:
            default = getattr(getattr(backend, "default", None), "hostapi", 0)
            preferred = default if isinstance(default, int) and 0 <= default < len(names) else 0
        defaults = {
            index: (item.get("default_input_device", -1), item.get("default_output_device", -1))
            for index, item in enumerate(hostapis)
        }
        devices = []
        for index, item in enumerate(listed):
            api = item.get("hostapi", -1)
            if not isinstance(api, int) or not 0 <= api < len(names):
                continue
            number = item.get("index", index)
            default_input, default_output = defaults.get(api, (-1, -1))
            devices.append(
                Device(
                    index=number,
                    name=str(item.get("name", "")).strip(),
                    host_api=names[api],
                    inputs=int(item.get("max_input_channels", 0) or 0),
                    outputs=int(item.get("max_output_channels", 0) or 0),
                    rate=int(round(float(item.get("default_samplerate", 0) or 0))),
                    default_input=number == default_input,
                    default_output=number == default_output,
                )
            )
        return (names[preferred] if names else None), devices

    # --- core-side views ------------------------------------------------------------------

    async def report(self):
        """The Preferences device list (``AudioDevicesReport``); unavailable is a state."""
        try:
            preferred, devices = await self.call(self.devices)
        except ServiceError as exc:
            return {
                "available": False,
                "code": exc.code,
                "message": str(exc),
                "host_api": None,
                "inputs": [],
                "outputs": [],
            }
        listed = [item for item in devices if item.host_api == preferred and listable(item)]
        inputs = [item.entry("input") for item in listed if item.inputs > 0][:64]
        outputs = [item.entry("output") for item in listed if item.outputs > 0][:64]
        self.summary = {"inputs": len(inputs), "outputs": len(outputs)}
        report = {
            "available": True,
            "code": None,
            "message": None,
            "host_api": preferred,
            "inputs": inputs,
            "outputs": outputs,
        }
        return AudioDevicesReport.model_validate(report).model_dump()

    def status(self):
        """Capability view without importing or opening anything."""
        if not installed():
            return {"installed": False, "reason": UNAVAILABLE}
        if self.failure:
            return {"installed": False, "reason": self.failure}
        summary = self.summary
        if summary is not None and not summary["inputs"]:
            return {"installed": True, "reason": "No microphone was found on this PC."}
        if summary is not None and not summary["outputs"]:
            return {"installed": True, "reason": "No speaker was found on this PC."}
        return {"installed": True, "reason": None}


class LocalAudio:
    """One local voice session's microphone and speaker.

    ``on_frame(pcm)`` receives 40 ms frames of 16 kHz PCM16 on the core loop;
    ``on_lost(kind)`` is called once if a device stops ("microphone" or "speaker");
    ``on_change()`` when playback starts or the half-duplex tail ends.
    """

    def __init__(
        self,
        devices,
        *,
        on_frame,
        on_lost,
        on_change=lambda: None,
        clock=time.monotonic,
        tail=TAIL_SECONDS,
        stall=STALL_SECONDS,
        grace=OPEN_GRACE_SECONDS,
        poll=0.1,
    ):
        self.devices = devices
        self.on_frame, self.on_lost, self.on_change = on_frame, on_lost, on_change
        self.clock, self.tail, self.stall, self.grace, self.poll = clock, tail, stall, grace, poll
        self.loop = None
        self.input = self.output = None
        self.microphone = self.speaker = None
        self.in_channels = self.out_channels = 1
        self.capture = self.playback = None
        self.output_latency = 0.0
        self.block_bytes = 0
        self.inbox = deque(maxlen=INBOX_BLOCKS)  # raw device blocks, PortAudio -> core
        self.outbox = deque(maxlen=PLAYBACK_BLOCKS)  # device-rate blocks, core -> PortAudio
        self.partial = None  # (block, offset) the output callback is part-way through
        self.drop_partial = False
        self.wake_pending = False
        self.pending = bytearray()  # resampled 16 kHz audio short of a whole frame
        self.opened_at = 0.0
        self.last_input = self.last_output = 0.0
        self.last_audible = float("-inf")
        self.closing = self.closed = False
        self.ready = False  # both streams opened and handed to the core loop
        self.lost = False
        self.monitor = None
        # Counters (logged at close; never audio).
        self.input_blocks = self.input_dropped = self.input_flags = 0
        self.output_blocks = self.output_dropped = self.output_flags = 0
        self.gated = self.backlog_dropped = 0

    # --- lifetime ---------------------------------------------------------------------------

    async def open(self, microphone=SYSTEM_DEFAULT, speaker=SYSTEM_DEFAULT):
        """Open both devices (saved choices, else the system default): the fallback notices."""
        self.loop = asyncio.get_running_loop()
        notices = await self.devices.call(self._open, microphone, speaker)
        if self.closing:
            raise ServiceError("voice_stopped", "Voice is off.")
        self.opened_at = self.last_input = self.last_output = self.clock()
        self.ready = True
        self.monitor = asyncio.create_task(self.watch(), name="local-audio-watch")
        return notices

    def _open(self, microphone, speaker):
        if self.closing:
            return []
        preferred, devices = self.devices.devices()
        mic, mic_notice = resolve(devices, preferred, "input", microphone)
        out, out_notice = resolve(devices, preferred, "output", speaker)
        backend = self.devices.backend
        from telephony.audio import Resampler

        try:
            self.in_channels, self.input = self._stream(
                backend.RawInputStream, mic, "input", self._capture_callback
            )
            self.out_channels, self.output = self._stream(
                backend.RawOutputStream, out, "output", self._play_callback
            )
            # Filter design for 44.1 kHz can take a moment: built here, off the core loop.
            self.capture = Resampler(mic.rate, INPUT_RATE)
            self.playback = Resampler(OUTPUT_RATE, out.rate)
            self.block_bytes = max(2, out.rate // BLOCKS_PER_SECOND) * 2 * self.out_channels
            latency = getattr(self.output, "latency", 0.0)
            self.output_latency = float(latency) if isinstance(latency, (int, float)) else 0.0
            self.input.start()
            self.output.start()
        except ServiceError:
            self._close_streams()
            raise
        except Exception as exc:
            logger.warning(
                "Local voice could not open its devices (%s): microphone %s, speaker %s",
                type(exc).__name__,
                mic.label(),
                out.label(),
            )
            self._close_streams()
            raise ServiceError(
                "audio_open_failed",
                "JARVIS could not open the microphone or speaker. "
                "Check them in Windows sound settings and try again.",
            ) from exc
        self.microphone, self.speaker = mic, out
        logger.info(
            "Local voice opened microphone %s (%s ch) and speaker %s (%s ch)",
            mic.label(),
            self.in_channels,
            out.label(),
            self.out_channels,
        )
        return [notice for notice in (mic_notice, out_notice) if notice]

    def _stream(self, factory, device, kind, callback):
        """Open mono when the host API mixes for us, else the device's own channel count."""
        error = None
        for channels in dict.fromkeys((1, max(1, min(device.channels(kind), 8)))):
            try:
                stream = factory(
                    device=device.index,
                    samplerate=device.rate,
                    channels=channels,
                    dtype="int16",
                    blocksize=max(1, device.rate // BLOCKS_PER_SECOND),
                    callback=callback,
                    finished_callback=lambda kind=kind: self._finished(kind),
                )
                self.devices.open_streams += 1
                return channels, stream
            except Exception as exc:  # PortAudioError: unsupported channel count, busy device
                error = exc
        raise error

    async def close(self):
        """Stop and release both devices; safe to call more than once and while opening."""
        if self.closed:
            return
        self.closed = self.closing = True
        monitor = self.monitor
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self.inbox.clear()
        self.outbox.clear()
        self.pending.clear()
        try:
            # Queued behind a still-running open on the same thread, so nothing leaks.
            await self.devices.call(self._close_streams)
        finally:
            logger.info(
                "Local voice closed: %s microphone blocks (%s dropped, %s flagged), "
                "%s speaker blocks (%s dropped, %s flagged), %s frames muted while speaking, "
                "%s frames over the Live backlog",
                self.input_blocks,
                self.input_dropped,
                self.input_flags,
                self.output_blocks,
                self.output_dropped,
                self.output_flags,
                self.gated,
                self.backlog_dropped,
            )

    def _close_streams(self):
        for name in ("input", "output"):
            stream = getattr(self, name)
            setattr(self, name, None)
            if stream is None:
                continue
            self.devices.open_streams = max(0, self.devices.open_streams - 1)
            for method in ("abort", "close"):
                try:
                    getattr(stream, method)()
                except Exception:
                    logger.debug("Local audio %s %s failed", name, method, exc_info=True)

    # --- PortAudio threads: copy, count, wake; never block or raise --------------------------

    def _capture_callback(self, indata, frames, time_info, status):
        try:
            if self.closing:
                return
            self.last_input = self.clock()
            self.input_blocks += 1
            if status:
                self.input_flags += 1
            if len(self.inbox) == self.inbox.maxlen:
                self.input_dropped += 1  # the deque drops the oldest block
            self.inbox.append(bytes(indata))
            if not self.wake_pending:
                self.wake_pending = True
                self.loop.call_soon_threadsafe(self._drain)
        except Exception:
            pass  # e.g. the loop closed during shutdown

    def _play_callback(self, outdata, frames, time_info, status):
        try:
            self.last_output = self.clock()
            self.output_blocks += 1
            if status:
                self.output_flags += 1
            need = len(outdata)
            filled = 0
            if self.drop_partial:
                self.drop_partial = False
                self.partial = None
            while filled < need and not self.closing:
                if self.partial is None:
                    try:
                        self.partial = (self.outbox.popleft(), 0)
                    except IndexError:
                        break
                block, offset = self.partial
                take = min(len(block) - offset, need - filled)
                outdata[filled : filled + take] = block[offset : offset + take]
                filled += take
                offset += take
                self.partial = None if offset >= len(block) else (block, offset)
            if filled < need:
                outdata[filled:need] = bytes(need - filled)
            if filled:
                self.last_audible = self.clock()
        except Exception:
            try:
                outdata[:] = bytes(len(outdata))
            except Exception:
                pass

    def _finished(self, kind):
        # A stream stopped. Ours stop only while closing (or a failed open); else the device went.
        if self.closing or not self.ready:
            return
        try:
            self.loop.call_soon_threadsafe(self._report_lost, LABELS[kind])
        except Exception:
            pass

    # --- core loop -------------------------------------------------------------------------

    def _drain(self):
        self.wake_pending = False
        while not self.closing:
            try:
                block = self.inbox.popleft()
            except IndexError:
                return
            self.pending += self.capture.process(downmix(block, self.in_channels))
            while len(self.pending) >= FRAME_BYTES and not self.closing:
                frame = bytes(self.pending[:FRAME_BYTES])
                del self.pending[:FRAME_BYTES]
                self.on_frame(frame)

    def _report_lost(self, kind):
        if self.closing or self.lost:
            return
        self.lost = True
        logger.warning("Local voice lost its %s", kind)
        self.on_lost(kind)

    def speaking(self):
        """True while JARVIS is audible, plus the tail after the playback buffer drains."""
        if self.outbox or self.partial is not None:
            return True
        return self.clock() - self.last_audible < self.tail + self.output_latency

    def play(self, pcm):
        """Queue 24 kHz PCM16 from Live for the speaker."""
        if self.closing or self.playback is None or not pcm:
            return
        data = upmix(self.playback.process(bytes(pcm[: len(pcm) - len(pcm) % 2])), self.out_channels)
        was_speaking = self.speaking()
        size = self.block_bytes or len(data)
        for start in range(0, len(data), size):
            if len(self.outbox) == self.outbox.maxlen:
                self.output_dropped += 1  # the deque drops the oldest block
            self.outbox.append(data[start : start + size])
        if not was_speaking:
            self.on_change()

    def flush(self):
        """Interrupted: drop everything not yet played."""
        self.outbox.clear()
        self.drop_partial = True
        if self.playback is not None:
            self.playback.reset()
        self.on_change()

    async def watch(self):
        speaking = self.speaking()
        try:
            while not self.closing:
                await asyncio.sleep(self.poll)
                if self.closing:
                    return
                now = self.clock()
                if now - self.opened_at > self.grace:
                    if now - self.last_input > self.stall:
                        self._report_lost("microphone")
                        return
                    if now - self.last_output > self.stall:
                        self._report_lost("speaker")
                        return
                current = self.speaking()
                if current != speaking:
                    speaking = current
                    self.on_change()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Local audio watch failed")
            self._report_lost("microphone")


def local_choices(settings):
    """(microphone, speaker) saved for tray voice."""
    devices = local_devices(settings)
    return devices["microphone"], devices["speaker"]
