"""This PC's microphone and speaker for tray voice. Never imports audio at startup.

``sounddevice`` (PortAudio) is imported lazily, on one dedicated audio control thread,
the first time devices are listed or opened; every PortAudio control call (initialize,
query, open, start, abort, close) runs on that thread, so they are serialized and keep
one COM apartment. Streams are raw PCM16 bytes (no numpy). WASAPI shared mode runs at the
device's own mix rate, so a session's own microphone records at the device rate and is
resampled to Live's 16 kHz, and Live's 24 kHz speech is resampled to the speaker's rate
(``telephony.audio.Resampler``; speech quality).

While "Hey Jarvis" listens (services/wake_listening.py), ``Microphone`` is the one capture
stream: opened at 16 kHz mono through WASAPI's own converter when it can be (its blocks
go straight from the PortAudio callback to the detector's queue), else at the device rate
and resampled on a capture worker thread. It stays open across tray voice sessions, which
attach to it instead of opening their own, and keeps the last 1.5 s of 16 kHz audio in
memory only (``PREROLL_SECONDS``), so a session started by the phrase can send it first.
With no session attached, no block reaches the core loop.

PortAudio callbacks never block and never call into the core: they copy one block into
a bounded deque (dropping the oldest block on overflow, counted) and wake the core loop
with ``call_soon_threadsafe`` (the shared microphone wakes the loop only for an attached
session). Half-duplex echo control lives here too: while JARVIS's audio is playing, and
for ``tail`` seconds after the playback buffer drains, ``speaking()`` is true and the
voice service drops microphone frames; a "Hey Jarvis" barge-in flushes playback and ends
the tail at once. The short wake and denied cues (``cue_pcm``) are generated here and
play on an output stream of their own (``Cue``), apart from any session.

``AudioDevices.input_fingerprint`` reads which microphone Windows uses by default straight
from Core Audio (services/default_input.py), so the always-open "Hey Jarvis" stream can follow
a new default without PortAudio re-reading its device list underneath an open stream.

Audio is never logged or stored. Logs carry device names, host APIs, rates and counters.
"""

import asyncio
from array import array
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import importlib
import importlib.util
import math
import re
import sys
import threading
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
PROBE_TIMEOUT = 2.0  # Windows' default-microphone probe (services/default_input.py)
CAPTURE_BLOCK = INPUT_RATE // BLOCKS_PER_SECOND  # 20 ms of 16 kHz (shared microphone)
PREROLL_SECONDS = 1.5
PREROLL_BYTES = int(INPUT_RATE * PREROLL_SECONDS) * 2
HOLD_BYTES = INPUT_RATE * 2 * 10  # audio held between a detection and its decision (10 s)
SHARED_INBOX = INBOX_BLOCKS + 4  # shared-microphone chunks waiting for a session's loop
WORKER_POLL = 1.0  # the capture worker checks for a stalled microphone this often
CUES = {"wake": (660.0, 880.0), "denied": (523.0, 392.0)}
CUE_TONE_SECONDS = 0.07
CUE_GAP_SECONDS = 0.02
CUE_FADE_SECONDS = 0.01
CUE_PEAK_DBFS = -18.0
OPEN_FAILED = (
    "JARVIS could not open the microphone or speaker. "
    "Check them in Windows sound settings and try again."
)
UNAVAILABLE = (
    "Tray voice needs the sounddevice audio library. Run scripts/bootstrap.ps1 to repair setup."
)
_PRINTABLE = re.compile(r"^[^\x00-\x1f\x7f]+$")
_BIG_ENDIAN = sys.byteorder == "big"
LABELS = {"input": "microphone", "output": "speaker"}
LEVEL_STRIDE = 4  # the output level reads every 4th int16 sample of a speaker block


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


def block_level(data, size, stride=LEVEL_STRIDE):
    """``min(1, 4 * rms / 32768)`` over every ``stride``-th int16 sample of ``data[:size]``,
    the scale of the workspace player (src/features/voice/playback.worklet.js).

    Runs on the PortAudio output thread: no copy of the block, one small view, no numpy.
    """
    size -= size % 2
    if size <= 0:
        return 0.0
    with memoryview(data) as raw, raw[:size] as part, part.cast("h") as samples:
        total = count = 0
        for value in samples[::stride]:
            total += value * value
            count += 1
    return min(1.0, 4.0 * math.sqrt(total / count) / 32768.0) if count else 0.0


class AudioDevices:
    """Device enumeration and the single audio control thread, shared by local sessions."""

    def __init__(self, loader=None, timeout=CONTROL_TIMEOUT, probe=None):
        self.loader = loader or import_sounddevice
        self.timeout = timeout
        self.backend = None
        self.failure = None
        self.executor = None
        self.open_streams = 0
        self.summary = None  # {"inputs": n, "outputs": n} from the last successful listing
        # Windows' view of the default microphone, for the real backend only (a fake loader,
        # in tests, gets no probe unless one is given).
        if probe is None and loader is None:
            from services.default_input import fingerprint as probe
        self.probe = probe
        self.probe_executor = None
        self.probe_failed = False

    # --- the audio control thread ---------------------------------------------------------

    def submit(self, function, *args):
        """Queue ``function`` on the control thread now; an asyncio future of its result."""
        if self.executor is None:
            self.executor = ThreadPoolExecutor(1, thread_name_prefix="jarvis-audio")
        return asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

    async def call(self, function, *args):
        try:
            return await asyncio.wait_for(self.submit(function, *args), self.timeout)
        except TimeoutError as exc:
            logger.warning("The audio system did not answer within %ss", self.timeout)
            raise ServiceError(
                "audio_unavailable", "The audio system is not responding. Restart JARVIS."
            ) from exc

    def close(self):
        for name in ("executor", "probe_executor"):
            executor = getattr(self, name)
            setattr(self, name, None)
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)

    async def input_fingerprint(self):
        """Which microphones Windows has and uses by default (comparable values), or None
        when that cannot be known here. Never touches PortAudio or opens a device; runs on a
        thread of its own. A probe that hangs is not asked again; a failure is logged once."""
        probe = self.probe
        if probe is None:
            return None
        if self.probe_executor is None:
            self.probe_executor = ThreadPoolExecutor(1, thread_name_prefix="jarvis-audio-probe")
        future = asyncio.get_running_loop().run_in_executor(self.probe_executor, probe)
        try:
            value = await asyncio.wait_for(future, PROBE_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                self.probe = None  # its thread is stuck: stop following the default
            if not self.probe_failed:
                self.probe_failed = True
                logger.warning(
                    "Windows' default microphone cannot be read (%s); voice picks it up when "
                    "it next opens the microphone",
                    type(exc).__name__,
                )
            return None
        self.probe_failed = False
        return value

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

    With ``microphone`` (the shared ``Microphone`` while "Hey Jarvis" listens) the session
    opens only its speaker and attaches to that stream; with ``preroll`` it first takes
    the audio held since the detection, handing the 1.5 s before it to ``on_preroll(pcm)``
    in 40 ms frames (the last one may be shorter). Closing detaches; the stream stays open.
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
        microphone=None,
        preroll=False,
        on_preroll=lambda pcm: None,
    ):
        self.devices = devices
        self.on_frame, self.on_lost, self.on_change = on_frame, on_lost, on_change
        self.shared, self.take_preroll, self.on_preroll = microphone, preroll, on_preroll
        self.shared_inbox = deque(maxlen=SHARED_INBOX)  # (preroll, 16 kHz pcm) from ``shared``
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
        # The talking overlay's output level (services/voice_overlay.py): measured in the
        # speaker callback only while ``measure_level`` is set.
        self.measure_level = False
        self.level = 0.0

    # --- lifetime ---------------------------------------------------------------------------

    async def open(self, microphone=SYSTEM_DEFAULT, speaker=SYSTEM_DEFAULT):
        """Open both devices (saved choices, else the system default): the fallback notices."""
        self.loop = asyncio.get_running_loop()
        notices = await self.devices.call(self._open, microphone, speaker)
        if self.closing:
            raise ServiceError("voice_stopped", "Voice is off.")
        self.opened_at = self.last_input = self.last_output = self.clock()
        self.ready = True
        if self.shared is not None:
            self.shared.attach(self, preroll=self.take_preroll)
        self.monitor = asyncio.create_task(self.watch(), name="local-audio-watch")
        return notices

    def _open(self, microphone, speaker):
        if self.closing:
            return []
        preferred, devices = self.devices.devices()
        if self.shared is None:
            mic, mic_notice = resolve(devices, preferred, "input", microphone)
        else:  # the listener's stream: already open, its device already resolved
            mic, mic_notice = self.shared.device, self.shared.notice
        out, out_notice = resolve(devices, preferred, "output", speaker)
        backend = self.devices.backend
        from telephony.audio import Resampler

        try:
            if self.shared is None:
                self.in_channels, self.input = self._stream(
                    backend.RawInputStream, mic, "input", self._capture_callback
                )
            self.out_channels, self.output = self._stream(
                backend.RawOutputStream, out, "output", self._play_callback
            )
            # Filter design for 44.1 kHz can take a moment: built here, off the core loop.
            self.capture = Resampler(INPUT_RATE if self.shared else mic.rate, INPUT_RATE)
            self.playback = Resampler(OUTPUT_RATE, out.rate)
            self.block_bytes = max(2, out.rate // BLOCKS_PER_SECOND) * 2 * self.out_channels
            latency = getattr(self.output, "latency", 0.0)
            self.output_latency = float(latency) if isinstance(latency, (int, float)) else 0.0
            if self.input is not None:  # None: the shared microphone is already running
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
            raise ServiceError("audio_open_failed", OPEN_FAILED) from exc
        self.microphone, self.speaker = mic, out
        logger.info(
            "Local voice opened microphone %s (%s ch%s) and speaker %s (%s ch)",
            mic.label(),
            self.in_channels,
            ", shared with the wake-word listener" if self.shared is not None else "",
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
        if self.shared is not None:
            self.shared.detach(self)  # the listener's stream stays open
        monitor = self.monitor
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self.inbox.clear()
        self.shared_inbox.clear()
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
            if filled and not self.drop_partial:  # a barge-in flush during this block wins
                self.last_audible = self.clock()
                if self.measure_level:
                    self.level = block_level(outdata, filled)
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

    def shared_audio(self, pcm, preroll):
        """The shared microphone's 16 kHz audio (any thread): copy, count, wake the loop."""
        try:
            if self.closing:
                return
            self.input_blocks += 1
            if len(self.shared_inbox) == self.shared_inbox.maxlen:
                self.input_dropped += 1  # the deque drops the oldest chunk
            self.shared_inbox.append((preroll, pcm))
            if not self.wake_pending:
                self.wake_pending = True
                self.loop.call_soon_threadsafe(self._drain)
        except Exception:
            pass  # e.g. the loop closed during shutdown

    def _drain(self):
        self.wake_pending = False
        if self.shared is not None:
            self._drain_shared()
            return
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

    def _drain_shared(self):
        while not self.closing:
            try:
                preroll, pcm = self.shared_inbox.popleft()
            except IndexError:
                return
            if preroll:
                for start in range(0, len(pcm), FRAME_BYTES):
                    self.on_preroll(pcm[start : start + FRAME_BYTES])
                continue
            self.pending += pcm
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
        if self.outbox or (self.partial is not None and not self.drop_partial):
            return True
        return self.clock() - self.last_audible < self.tail + self.output_latency

    def output_level(self):
        """0..1: the level of the last speaker block that had audio (while ``measure_level``
        is set), and 0.0 when JARVIS is not speaking."""
        return self.level if self.speaking() else 0.0

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

    def flush(self, reset_tail=False):
        """Interrupted: drop everything not yet played.

        ``reset_tail`` (a "Hey Jarvis" barge-in only) also ends the half-duplex tail, so
        the microphone reaches Live at once; every other flush keeps the tail.
        """
        self.outbox.clear()
        self.drop_partial = True
        if reset_tail:
            self.last_audible = float("-inf")
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
                    # A shared microphone watches itself (Microphone reports its loss).
                    if self.shared is None and now - self.last_input > self.stall:
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


class Microphone:
    """The one capture stream while "Hey Jarvis" listens; tray voice sessions attach to it.

    Every 16 kHz mono chunk goes to ``submit`` (the listener's non-blocking queue), into
    the 1.5 s pre-roll ring (memory only, overwritten continuously), and to the attached
    session, if any (``LocalAudio.shared_audio``). ``arm()`` (called at a detection)
    snapshots the ring and holds the following audio until the core decides: ``attach``
    hands a wake-started session the snapshot and the held audio, ``release()`` gives the
    held audio to the attached session, ``discard()`` drops it. Snapshot, hold and
    forwarding all happen under one lock, so nothing is lost or sent twice.

    ``on_lost()`` is called once, on the core loop, if the stream stops or goes silent.
    """

    def __init__(self, devices, *, on_lost, submit=None, clock=time.monotonic,
                 stall=STALL_SECONDS, grace=OPEN_GRACE_SECONDS, poll=WORKER_POLL):
        self.devices, self.on_lost, self.submit = devices, on_lost, submit
        self.clock, self.stall, self.grace, self.poll = clock, stall, grace, poll
        self.loop = None
        self.stream = None
        self.device = self.notice = None
        self.direct = False  # 16 kHz mono blocks straight from the callback
        self.channels = 1
        self.resampler = None
        self.inbox = deque(maxlen=INBOX_BLOCKS)  # device-rate blocks for the worker
        self._lock = threading.Lock()
        self._ring = deque()
        self._ring_bytes = 0
        self._held = None  # deque of chunks since arm(), or None
        self._held_bytes = 0
        self._armed_preroll = None
        self._sink = None
        self._wake = threading.Event()
        self._worker = None
        self.opened_at = self.last_input = 0.0
        self.closing = self.closed = False
        self.ready = False
        self.lost = False
        # Counters (logged at close; never audio).
        self.blocks = self.dropped = self.flags = self.held_dropped = 0

    # --- lifetime -------------------------------------------------------------------------

    async def open(self, choice=SYSTEM_DEFAULT):
        """Resolve and open the saved microphone (control thread); the fallback notice."""
        self.loop = asyncio.get_running_loop()
        await self.devices.call(self._open, choice)
        if self.closing:
            raise ServiceError("voice_stopped", "The microphone was closed.")
        self.ready = True
        return self.notice

    def _open(self, choice):
        if self.closing:
            return
        preferred, devices = self.devices.devices()
        mic, notice = resolve(devices, preferred, "input", choice)
        backend = self.devices.backend
        self.device, self.notice = mic, notice
        self.opened_at = self.last_input = self.clock()
        stream = None
        wasapi = getattr(backend, "WasapiSettings", None)
        if callable(wasapi) and mic.host_api == PREFERRED_HOST_API:
            # WASAPI converts to 16 kHz mono for us: no resampling at all.
            self.direct, self.channels = True, 1
            try:
                stream = self._start(
                    backend, mic, INPUT_RATE, 1, CAPTURE_BLOCK,
                    extra_settings=wasapi(auto_convert=True),
                )
            except Exception as exc:
                logger.info(
                    "Microphone %s refused 16 kHz (%s); using its own rate",
                    mic.label(),
                    type(exc).__name__,
                )
        if stream is None:
            from telephony.audio import Resampler

            self.direct = False
            self.resampler = Resampler(mic.rate, INPUT_RATE)  # filter design off the loop
            error = None
            for channels in dict.fromkeys((1, max(1, min(mic.inputs, 8)))):
                self.channels = channels
                try:
                    stream = self._start(
                        backend, mic, mic.rate, channels, max(1, mic.rate // BLOCKS_PER_SECOND)
                    )
                    break
                except Exception as exc:
                    error = exc
            if stream is None:
                logger.warning(
                    "The wake-word microphone could not open (%s): %s",
                    type(error).__name__,
                    mic.label(),
                )
                raise ServiceError("audio_open_failed", OPEN_FAILED) from error
        self.stream = stream
        if self.closing:  # close() is queued behind this open; it releases the stream
            return
        self._worker = threading.Thread(
            target=self._work, name="jarvis-mic-capture", daemon=True
        )
        self._worker.start()
        logger.info(
            "Wake-word microphone opened: %s (%s)",
            mic.label(),
            "16 kHz mono via WASAPI" if self.direct else f"{self.channels} ch, resampled",
        )

    def _start(self, backend, mic, rate, channels, blocksize, **extra):
        stream = backend.RawInputStream(
            device=mic.index,
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            callback=self._callback,
            finished_callback=self._finished,
            **extra,
        )
        self.devices.open_streams += 1
        try:
            stream.start()
        except BaseException:
            self.devices.open_streams = max(0, self.devices.open_streams - 1)
            for method in ("abort", "close"):
                try:
                    getattr(stream, method)()
                except Exception:
                    pass
            raise
        return stream

    async def close(self):
        """Stop and release the stream; safe to call more than once and while opening."""
        if self.closed:
            return
        self.closed = self.closing = True
        self._wake.set()
        with self._lock:
            self._sink = self._held = self._armed_preroll = None
            self._ring.clear()
            self._ring_bytes = 0
        self.inbox.clear()
        try:
            await self.devices.call(self._close_stream)
        finally:
            logger.info(
                "Wake-word microphone closed: %s blocks (%s dropped, %s flagged, %s held "
                "chunks dropped)",
                self.blocks,
                self.dropped,
                self.flags,
                self.held_dropped,
            )

    def _close_stream(self):
        self.closing = True
        self._wake.set()
        stream, self.stream = self.stream, None
        if stream is not None:
            self.devices.open_streams = max(0, self.devices.open_streams - 1)
            for method in ("abort", "close"):
                try:
                    getattr(stream, method)()
                except Exception:
                    logger.debug("Wake-word microphone %s failed", method, exc_info=True)
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(2)

    # --- PortAudio and worker threads: copy, count, never block or raise -------------------

    def _callback(self, indata, frames, time_info, status):
        try:
            if self.closing:
                return
            self.last_input = self.clock()
            self.blocks += 1
            if status:
                self.flags += 1
            if self.direct:
                self._distribute(bytes(indata))
                return
            if len(self.inbox) == self.inbox.maxlen:
                self.dropped += 1  # the deque drops the oldest block
            self.inbox.append(bytes(indata))
            self._wake.set()
        except Exception:
            pass

    def _work(self):
        """Resample device-rate blocks (fallback) and watch for a stalled stream."""
        while not self.closing:
            self._wake.wait(self.poll)
            self._wake.clear()
            while not self.closing:
                try:
                    block = self.inbox.popleft()
                except IndexError:
                    break
                try:
                    pcm = self.resampler.process(downmix(block, self.channels))
                except Exception:
                    continue
                if pcm:
                    self._distribute(pcm)
            if self.closing or self.lost or not self.ready:
                continue
            now = self.clock()
            if now - self.opened_at > self.grace and now - self.last_input > self.stall:
                self._signal_lost()
                return

    def _distribute(self, pcm):
        submit = self.submit
        if submit is not None:
            try:
                submit(pcm)
            except Exception:
                pass
        with self._lock:
            self._ring.append(pcm)
            self._ring_bytes += len(pcm)
            while self._ring_bytes - len(self._ring[0]) >= PREROLL_BYTES:
                self._ring_bytes -= len(self._ring.popleft())
            if self._held is not None:
                self._held.append(pcm)
                self._held_bytes += len(pcm)
                while self._held_bytes > HOLD_BYTES and self._held:
                    self._held_bytes -= len(self._held.popleft())
                    self.held_dropped += 1
                return
            sink = self._sink
            if sink is not None:
                sink.shared_audio(pcm, False)

    def _finished(self):
        # Ours stop only while closing (or a failed open); else the device went away.
        if self.closing or not self.ready:
            return
        self._signal_lost()

    def _signal_lost(self):
        try:
            self.loop.call_soon_threadsafe(self._report_lost)
        except Exception:
            pass

    def _report_lost(self):
        if self.closing or self.lost:
            return
        self.lost = True
        logger.warning("The wake-word microphone was lost")
        self.on_lost()

    # --- pre-roll and sessions (any thread) -------------------------------------------------

    def preroll(self):
        """The last 1.5 s of 16 kHz audio (a copy)."""
        with self._lock:
            return self._snapshot()

    def _snapshot(self):
        return b"".join(self._ring)[-PREROLL_BYTES:]

    def arm(self):
        """A detection: snapshot the pre-roll and hold what follows until the decision."""
        with self._lock:
            if self.closing or self._held is not None:
                return
            self._armed_preroll = self._snapshot()
            self._held, self._held_bytes = deque(), 0

    @property
    def armed(self):
        return self._held is not None

    def attach(self, sink, preroll=False):
        """``sink`` (a LocalAudio) receives audio from now on; a wake start takes the
        pre-roll and the held audio first."""
        with self._lock:
            self._sink = sink
            if self._held is None:
                return
            held, before = b"".join(self._held), self._armed_preroll
            self._held = self._armed_preroll = None
            if preroll and before:
                sink.shared_audio(before, True)
            if held:
                sink.shared_audio(held, False)

    def detach(self, sink):
        with self._lock:
            if self._sink is sink:
                self._sink = None

    def attached(self):
        return self._sink

    def release(self):
        """The decision was to keep listening: the held audio goes to the session, if any."""
        with self._lock:
            if self._held is None:
                return
            held = b"".join(self._held)
            self._held = self._armed_preroll = None
            if self._sink is not None and held:
                self._sink.shared_audio(held, False)

    def discard(self):
        with self._lock:
            self._held = self._armed_preroll = None


def cue_pcm(kind, rate):
    """A two-tone cue as mono PCM16 at ``rate``: "wake" rises 660 -> 880 Hz, "denied" falls
    523 -> 392 Hz. Each tone is 70 ms with 10 ms raised-cosine fades, 20 ms apart, peaking
    at about -18 dBFS."""
    peak = 32767 * 10 ** (CUE_PEAK_DBFS / 20)
    tone = round(rate * CUE_TONE_SECONDS)
    fade = max(1, round(rate * CUE_FADE_SECONDS))
    samples = array("h")
    for index, frequency in enumerate(CUES[kind]):
        if index:
            samples.extend([0] * round(rate * CUE_GAP_SECONDS))
        step = 2 * math.pi * frequency / rate
        for i in range(tone):
            edge = min(i, tone - 1 - i)
            envelope = 0.5 - 0.5 * math.cos(math.pi * edge / fade) if edge < fade else 1.0
            samples.append(round(peak * envelope * math.sin(step * i)))
    return _bytes(samples)


class Cue:
    """One short cue on the tray voice speaker, on an output stream of its own.

    It never counts as JARVIS speaking and never gates the microphone. ``open`` runs on
    the control thread and returns how long to keep the stream before closing it.
    """

    def __init__(self, devices, kind):
        self.devices, self.kind = devices, kind
        self.stream = None
        self.data = b""
        self.position = 0

    def open(self, choice):
        preferred, devices = self.devices.devices(refresh=False)
        out, _ = resolve(devices, preferred, "output", choice)
        backend = self.devices.backend
        error = None
        for channels in dict.fromkeys((1, max(1, min(out.outputs, 8)))):
            try:
                stream = backend.RawOutputStream(
                    device=out.index,
                    samplerate=out.rate,
                    channels=channels,
                    dtype="int16",
                    blocksize=max(1, out.rate // BLOCKS_PER_SECOND),
                    callback=self._callback,
                    finished_callback=lambda: None,
                )
                break
            except Exception as exc:
                error, stream = exc, None
        if stream is None:
            raise ServiceError("audio_open_failed", OPEN_FAILED) from error
        self.data = upmix(cue_pcm(self.kind, out.rate), channels)
        self.devices.open_streams += 1
        self.stream = stream
        try:
            stream.start()
        except Exception:
            self.close()
            raise
        latency = getattr(stream, "latency", 0.0)
        latency = float(latency) if isinstance(latency, (int, float)) else 0.0
        return len(self.data) / (2 * channels * out.rate) + latency

    def _callback(self, outdata, frames, time_info, status):
        try:
            need = len(outdata)
            chunk = self.data[self.position : self.position + need]
            self.position += len(chunk)
            outdata[: len(chunk)] = chunk
            if len(chunk) < need:
                outdata[len(chunk) : need] = bytes(need - len(chunk))
        except Exception:
            try:
                outdata[:] = bytes(len(outdata))
            except Exception:
                pass

    def close(self):
        stream, self.stream = self.stream, None
        if stream is None:
            return
        self.devices.open_streams = max(0, self.devices.open_streams - 1)
        for method in ("abort", "close"):
            try:
                getattr(stream, method)()
            except Exception:
                logger.debug("Cue stream %s failed", method, exc_info=True)


def local_choices(settings):
    """(microphone, speaker) saved for tray voice."""
    devices = local_devices(settings)
    return devices["microphone"], devices["speaker"]
