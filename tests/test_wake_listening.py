"""'Hey Jarvis' in the tray: listening conditions, the shared microphone, pre-roll, detections,
barge-in, cues, the tray switch, the status RPC and the capability card.

Fake PortAudio module, fake listener and fake Live session only: no microphone, speaker,
models, network or provider is ever used.
"""

import asyncio
from array import array
from contextlib import asynccontextmanager
import json
import math
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from resident.state import Identity, State
from resident.win32 import MF_CHECKED, Tray
from services import voice as voice_module
from services.audio_contracts import wake_word_settings
from services.audio_devices import CUES, PREROLL_BYTES, Cue, Microphone, cue_pcm
from services.tools import ServiceError
from services.wake_word import MISSING_REASON
from telephony.audio import goertzel_power
from tests.test_local_voice import (
    OWNER,
    FakePortAudioError,
    FakeSoundDevice,
    FakeStream,
    FakeTray,
    audio_frames,
    pull,
    speech,
    stopped,
)
from tests.test_local_voice import host, tray  # noqa: F401 - the tray voice fixtures
from tests.test_voice_live import FakeConnector, until

AVAILABLE = {"installed": True, "models": "ok", "available": True, "reason": None}
LOCKED = "Unlock JARVIS in the workspace to use voice."
ROOT = Path(__file__).resolve().parents[1]


class WasapiSoundDevice(FakeSoundDevice):
    """Adds sounddevice.WasapiSettings and the extra_settings argument."""

    def __init__(self):
        super().__init__()
        self.refuse_16k = False

    @staticmethod
    def WasapiSettings(auto_convert=False):  # the sounddevice name
        return SimpleNamespace(auto_convert=auto_convert)

    def RawInputStream(self, extra_settings=None, **values):
        if extra_settings is not None and self.refuse_16k:
            raise FakePortAudioError("Invalid sample rate")
        stream = FakeStream(self, "input", **values)
        stream.extra_settings = extra_settings
        return stream

    def open_inputs(self):
        return [item for item in self.streams if item.kind == "input" and not item.released]


class FakeListener:
    """The WakeWordListener API with a hand-driven detection."""

    def __init__(self, on_detect, on_state, sensitivity):
        self.on_detect, self.on_state = on_detect, on_state
        self.sensitivity, self.audible = sensitivity, False
        self.running, self.state, self.error = False, "stopped", None
        self.chunks = []
        self.starts = self.stops = self.resets = 0

    def submit(self, pcm):
        if not self.running:
            return False
        self.chunks.append(bytes(pcm))
        return True

    def start(self):
        if self.running:
            return False
        self.running, self.state = True, "listening"
        self.starts += 1
        return True

    def stop(self, timeout=2.0):
        self.running, self.state = False, "stopped"
        self.stops += 1
        return True

    def reset(self):
        self.resets += 1

    def detect(self, score=0.9):
        """The listener thread hearing the phrase."""
        worker = threading.Thread(target=self.on_detect, args=(score, time.monotonic()))
        worker.start()
        worker.join()


@pytest.fixture
async def wake(tray):  # noqa: F811 - fixture
    app = tray.app
    backend = WasapiSoundDevice()
    tray.backend = backend
    tray.devices.loader = lambda: backend
    service = app.wake
    service.status_reader = lambda: dict(AVAILABLE)
    listeners = []

    def make_listener(on_detect, on_state, sensitivity):
        listeners.append(FakeListener(on_detect, on_state, sensitivity))
        return listeners[-1]

    service.listener_factory = make_listener
    service.microphone_factory = lambda on_lost: Microphone(
        app.audio_devices, on_lost=on_lost, clock=tray.clock, stall=1e9
    )
    statuses, notices, decided = [], [], []
    service.activate(observer=statuses.append, notice=notices.append)
    service.loop = asyncio.get_running_loop()
    original = service.handle_detection

    async def handle_detection(mic):
        try:
            await original(mic)
        finally:
            decided.append(mic)

    service.handle_detection = handle_detection
    context = SimpleNamespace(
        **vars(tray), service=service, listeners=listeners, wake_statuses=statuses,
        notices=notices, decided=decided,
    )
    yield context
    await app.voice.stop_local()
    await service.close()


@pytest.fixture(autouse=True)
def never_the_real_sounddevice():
    before = "sounddevice" in sys.modules
    yield
    assert before or "sounddevice" not in sys.modules


async def listening(ctx):
    await ctx.service.reconcile()
    assert ctx.service.status() == {"state": "listening", "message": None}
    (stream,) = ctx.backend.open_inputs()
    return ctx.listeners[-1], stream


def ramp(index, samples=320):
    """One 20 ms 16 kHz chunk of a counting signal (every sample identifies its position)."""
    start = index * samples
    return struct.pack(f"<{samples}h", *(((start + i) % 65536) - 32768 for i in range(samples)))


def feed_chunks(stream, first, count):
    for index in range(first, first + count):
        stream.callback(ramp(index), 320, None, 0)


def sent_audio(live):
    return [item.data for item in audio_frames(live)]


def cue_streams(backend):
    return [item for item in backend.streams if isinstance(getattr(item.callback, "__self__", None), Cue)]


async def detection(ctx, listener=None):
    """Detect and wait until the core has decided."""
    listener = listener or ctx.listeners[-1]
    count = len(ctx.decided)
    listener.detect()
    await until(lambda: len(ctx.decided) > count)


async def live_session(ctx):
    app = ctx.app
    await until(lambda: OWNER in app.voice.sessions and ctx.connector.connections)
    session = app.voice.sessions[OWNER]
    await until(lambda: session.live is not None and session.audio is not None and session.audio.ready)
    return session, ctx.connector.connections[-1]


# --- settings --------------------------------------------------------------------------------


def test_wake_settings_validate_and_read_with_defaults(tmp_path):
    from pydantic import ValidationError
    from services.settings import SettingsPatch, SettingsService, SettingsStore

    for bad in ({"wake_word": None}, {"wake_word": "yes"}, {"wake_word": 1},
                {"wake_sensitivity": None}, {"wake_sensitivity": "max"}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"voice": bad})
    assert wake_word_settings({}) == {"wake_word": True, "wake_sensitivity": "normal"}
    stale = {"voice": {"wake_word": "on", "wake_sensitivity": 3}}
    assert wake_word_settings(stale) == {"wake_word": True, "wake_sensitivity": "normal"}
    settings = {"tool_permissions": {}}
    service = SettingsService(settings, SettingsStore(tmp_path / "settings.json"), set())
    service.apply(SettingsPatch.model_validate({"voice": {"wake_sensitivity": "high"}}))
    assert settings["voice"]["wake_word"] is True and settings["voice"]["wake_sensitivity"] == "high"
    service.apply(SettingsPatch.model_validate({"voice": {"wake_word": False}}))
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["voice"]["wake_word"] is False and saved["voice"]["wake_sensitivity"] == "high"


# --- when listening runs ---------------------------------------------------------------------


def block_setting(app):
    app.settings["voice"] = {"wake_word": False}


def block_models(app):
    app.wake.status_reader = lambda: {
        "installed": True, "models": "missing", "available": False, "reason": MISSING_REASON,
    }


def block_owner(app):
    app.sessions.local_owner = None


def block_key(app):
    def missing():
        raise ServiceError("provider_not_configured", "Voice needs a Gemini API key.")

    app.voice.preflight = missing


def block_permission(app):
    app.settings["tool_permissions"]["speech_capture"] = "deny"


def block_gaming(app):
    app.resources.select("gaming")


def block_microphone(app):
    for item in app.audio_devices.loader().devices:
        item["max_input_channels"] = 0


@pytest.mark.parametrize(
    "block,state,message",
    [
        (block_setting, "off", None),
        (block_models, "unavailable", MISSING_REASON),
        (block_owner, "unavailable", "Register the desktop owner first."),
        (block_key, "unavailable", 'Add a Gemini API key in Setup to use "Hey Jarvis".'),
        (block_permission, "unavailable", "Microphone permission is turned off."),
        (block_gaming, "paused", None),
        (block_microphone, "unavailable", "No microphone is connected. Connect one and try again."),
    ],
)
async def test_each_condition_blocks_listening(wake, block, state, message):
    block(wake.app)
    await wake.service.reconcile()
    assert wake.service.status() == {"state": state, "message": message}
    assert wake.backend.open_inputs() == []
    assert not any(item.running for item in wake.listeners)
    assert wake.wake_statuses[-1] == {
        "setting": state != "off", "state": state, "message": message,
    }


async def test_listening_needs_the_native_host(tray):  # noqa: F811 - fixture
    service = tray.app.wake  # never activated: a bare server or test app
    service.status_reader = lambda: dict(AVAILABLE)
    await service.reconcile()
    assert service.microphone is None and service.listener is None and not tray.backend.streams
    assert service.status() == {
        "state": "unavailable", "message": 'Start JARVIS from the tray to use "Hey Jarvis".',
    }
    assert await service.session_microphone() is None


async def test_gaming_pauses_and_resumes_and_keeps_the_models(wake):
    app = wake.app
    listener, stream = await listening(wake)
    assert await app.lifecycle.set_resource_state("client", {"state": "gaming"}) == {"ok": True}
    assert stream.released and wake.backend.open_inputs() == []
    assert wake.service.listener is listener and not listener.running  # models kept
    assert wake.service.status() == {"state": "paused", "message": None}
    assert await app.lifecycle.set_resource_state("client", {"state": "chat"}) == {"ok": True}
    assert wake.service.listener is listener and listener.running and len(wake.listeners) == 1
    assert len(wake.backend.open_inputs()) == 1
    assert wake.service.status()["state"] == "listening"


async def test_turning_the_setting_off_drops_the_listener_and_on_again_listens(wake):
    app = wake.app
    listener, stream = await listening(wake)
    app.settings["voice"] = {"wake_word": False}
    await app.settings_changed({"voice": {"wake_word": False}})
    assert wake.service.listener is None and listener.stops == 1 and stream.released
    assert wake.service.status() == {"state": "off", "message": None}
    app.settings["voice"] = {"wake_word": True, "wake_sensitivity": "high"}
    await app.settings_changed({"voice": {"wake_word": True}})
    assert len(wake.listeners) == 2 and wake.listeners[-1].sensitivity == "high"
    assert wake.listeners[-1].running and len(wake.backend.open_inputs()) == 1


async def test_missing_key_and_denied_permission_recover_on_change(wake):
    app = wake.app
    block_key(app)
    await wake.service.reconcile()
    assert wake.service.status()["message"] == 'Add a Gemini API key in Setup to use "Hey Jarvis".'
    app.voice.preflight = lambda: None
    block_permission(app)
    await app.settings_changed({"voice": {"name": "Kore"}})
    assert wake.service.status()["message"] == "Microphone permission is turned off."
    assert wake.backend.open_inputs() == []
    app.settings["tool_permissions"]["speech_capture"] = True
    await app.settings_changed({"tool_permissions": {"speech_capture": True}})
    assert wake.service.status()["state"] == "listening" and len(wake.backend.open_inputs()) == 1


async def test_owner_registration_starts_listening(wake, host):  # noqa: F811 - fixture
    app = wake.app
    host.state.identity.owner = None
    app.sessions.local_owner = None
    host.loop = asyncio.get_running_loop()
    await wake.service.begin()
    await until(lambda: wake.wake_statuses)
    assert wake.service.status()["message"] == "Register the desktop owner first."
    await host.control(OWNER, {"action": "register"})
    await until(lambda: wake.wake_statuses[-1]["state"] == "listening")
    assert wake.wake_statuses[-1] == {"setting": True, "state": "listening", "message": None}
    assert len(wake.backend.open_inputs()) == 1


async def test_slow_recheck_picks_up_models_added_later(wake):
    block_models(wake.app)
    wake.service.recheck = 0.05
    await wake.service.begin()
    await until(lambda: wake.wake_statuses and wake.wake_statuses[-1]["state"] == "unavailable")
    assert wake.service._timeout() == 0.05
    wake.service.status_reader = lambda: dict(AVAILABLE)  # models fetched meanwhile
    await until(lambda: wake.wake_statuses[-1]["state"] == "listening", timeout=3)
    assert wake.service.listening() and len(wake.backend.open_inputs()) == 1
    assert wake.service._timeout() is None  # listening: no more re-checks


async def test_lost_microphone_retries_with_backoff(wake):
    app, service, clock = wake.app, wake.service, wake.clock
    service.clock = clock
    _, stream = await listening(wake)
    assert (await app.voice.start_local())["ok"]
    await live_session(wake)
    await asyncio.to_thread(stream.finished_callback)  # PortAudio stopped: unplugged
    status = await stopped(wake)
    assert status["notice"] == "The microphone was disconnected. Voice is off."
    lost = "The microphone was disconnected. JARVIS will listen again when it is back."
    assert service.status() == {"state": "unavailable", "message": lost}
    assert wake.wake_statuses[-1]["message"] == lost
    await until(lambda: stream.released)
    devices = wake.backend.devices
    saved = [item["max_input_channels"] for item in devices]
    for item in devices:
        item["max_input_channels"] = 0
    for delay, following in ((10, 30), (30, 60), (60, 60)):
        assert service._timeout() == pytest.approx(delay)
        clock.now += delay - 1
        await service.reconcile()
        assert service._timeout() == pytest.approx(1)  # not yet
        clock.now += 1
        await service.reconcile()  # tries, re-resolving the device, and fails
        assert service._timeout() == pytest.approx(following)
        assert service.status()["message"] == lost and wake.backend.open_inputs() == []
    for item, channels in zip(devices, saved, strict=True):
        item["max_input_channels"] = channels
    clock.now += 60
    await service.reconcile()
    assert service.status() == {"state": "listening", "message": None}
    assert len(wake.backend.open_inputs()) == 1 and service.lost == 0


# --- one microphone ----------------------------------------------------------------------------


async def test_listening_opens_16k_mono_with_wasapi_conversion(wake):
    _, stream = await listening(wake)
    assert (stream.device, stream.samplerate, stream.channels, stream.blocksize) == (2, 16000, 1, 320)
    assert stream.extra_settings.auto_convert is True and stream.started
    assert wake.service.microphone.direct


async def test_sessions_share_the_listener_stream_and_leave_it_open(wake):
    app = wake.app
    listener, stream = await listening(wake)
    for _ in range(2):
        result = await app.voice.start_local()
        assert result["ok"]
        session, live = await live_session(wake)
        assert wake.backend.open_inputs() == [stream]  # no second capture stream
        assert session.audio.input is None and session.audio.shared is wake.service.microphone
        speaker = wake.backend.stream("output")
        assert speaker.started and speaker.samplerate == 48000
        await asyncio.to_thread(feed_chunks, stream, 0, 4)  # 80 ms -> two 40 ms frames
        await until(lambda: len(sent_audio(live)) == 2)  # noqa: B023
        assert b"".join(sent_audio(live)) == b"".join(ramp(index) for index in range(4))
        assert listener.chunks[-4:] == [ramp(index) for index in range(4)]  # still listening
        await app.voice.stop_local()
        assert speaker.released and not stream.aborted and wake.backend.open_inputs() == [stream]
    assert wake.service.microphone.attached() is None


async def test_with_the_setting_off_tray_voice_is_unchanged(wake):
    app = wake.app
    app.settings["voice"] = {"wake_word": False}
    await wake.service.reconcile()
    assert not wake.backend.streams and wake.service.listener is None
    assert (await app.voice.start_local())["ok"]
    session, _ = await live_session(wake)
    microphone = wake.backend.stream("input")
    assert (microphone.samplerate, microphone.extra_settings) == (48000, None)  # J2's own stream
    assert session.audio.shared is None and not session.wake
    await app.voice.stop_local()
    assert microphone.released and wake.backend.open_inputs() == []


async def test_listening_waits_for_a_session_with_its_own_microphone(wake):
    app = wake.app
    app.settings["voice"] = {"wake_word": False}
    await wake.service.reconcile()
    assert (await app.voice.start_local())["ok"]
    await live_session(wake)
    own = wake.backend.stream("input")
    app.settings["voice"] = {"wake_word": True}
    await app.settings_changed({"voice": {"wake_word": True}})
    assert wake.backend.open_inputs() == [own]  # never two capture streams
    await app.voice.stop_local()
    await wake.service.reconcile()  # what session_ended asks for
    (shared,) = wake.backend.open_inputs()
    assert shared is not own and shared.samplerate == 16000


async def test_fallback_opens_the_device_rate_and_resamples_off_the_callback(wake):
    wake.backend.refuse_16k = True
    listener, stream = await listening(wake)
    microphone = wake.service.microphone
    assert (stream.samplerate, stream.blocksize, stream.extra_settings) == (48000, 960, None)
    assert not microphone.direct
    threads = []
    original = microphone.resampler.process

    def process(pcm):
        threads.append(threading.current_thread().name)
        return original(pcm)

    microphone.resampler.process = process
    callers = []

    def device_thread():
        callers.append(threading.current_thread().name)
        data = struct.pack("<h", 1000) * 960
        for _ in range(10):
            stream.callback(data, 960, None, 0)

    await asyncio.to_thread(device_thread)
    await until(lambda: sum(len(chunk) for chunk in listener.chunks) >= 6000)
    assert set(threads) == {"jarvis-mic-capture"} and callers[0] not in threads
    assert all(len(chunk) == 640 for chunk in listener.chunks)  # 20 ms at 16 kHz


async def test_idle_listening_never_wakes_the_core_loop(wake):
    listener, stream = await listening(wake)
    microphone = wake.service.microphone
    real = microphone.loop
    calls = []

    class Counting:
        def call_soon_threadsafe(self, *args):
            calls.append(args)
            return real.call_soon_threadsafe(*args)

    microphone.loop = Counting()
    await asyncio.to_thread(feed_chunks, stream, 0, 50)
    assert len(listener.chunks) == 50 and calls == []
    assert microphone.preroll() == b"".join(ramp(index) for index in range(50))[-PREROLL_BYTES:]


async def test_a_changed_microphone_reopens_once_no_session_uses_it(wake):
    app = wake.app
    _, stream = await listening(wake)
    assert (await app.voice.start_local())["ok"]
    await live_session(wake)
    choice = {"name": "Microphone (Yeti Orb)", "host_api": "Windows WASAPI"}
    app.settings["voice"] = {"local_microphone": choice}
    await app.settings_changed({"voice": {"local_microphone": choice}})
    assert wake.backend.open_inputs() == [stream]  # the session still uses it
    await app.voice.stop_local()
    await wake.service.reconcile()
    (reopened,) = wake.backend.open_inputs()
    assert stream.released and reopened.device == 3


async def test_device_listing_releases_the_listener_stream_only_without_a_session(wake):
    app = wake.app
    listener, stream = await listening(wake)
    handler = app.sio.handlers["/"]["audio_devices"]
    refreshed = wake.backend.refreshed
    assert (await handler("client", {}))["ok"]
    # Refreshed for the list, then again when the stream reopens (device re-resolved).
    assert wake.backend.refreshed == refreshed + 2 and stream.released
    (reopened,) = wake.backend.open_inputs()
    assert listener.resets == 1 and wake.service.status()["state"] == "listening"
    assert (await app.voice.start_local())["ok"]
    await live_session(wake)
    assert (await handler("client", {}))["ok"]
    assert wake.backend.refreshed == refreshed + 2 and wake.backend.open_inputs() == [reopened]


# --- pre-roll ------------------------------------------------------------------------------------


async def test_a_detection_sends_exactly_the_last_1_5_s_first_then_live_audio(wake):
    listener, stream = await listening(wake)
    await asyncio.to_thread(feed_chunks, stream, 0, 100)  # 2 s
    listener.detect()  # the phrase ends at chunk 100
    await asyncio.to_thread(feed_chunks, stream, 100, 5)  # held until the core decides
    session, live = await live_session(wake)
    assert session.wake and wake.service.microphone.attached() is session.audio
    await asyncio.to_thread(feed_chunks, stream, 105, 20)
    stream_bytes = b"".join(ramp(index) for index in range(125))
    start = 100 * 640 - PREROLL_BYTES
    expected = stream_bytes[start : 100 * 640 + 12 * 1280]  # 12 whole live frames
    await until(lambda: sum(map(len, sent_audio(live))) == len(expected))
    frames = sent_audio(live)
    assert b"".join(frames) == expected  # no gap, nothing twice
    assert [len(frame) for frame in frames[:38]] == [1280] * 37 + [640]  # the 1.5 s pre-roll
    assert all(len(frame) == 1280 for frame in frames[38:])


async def test_preroll_is_not_counted_against_the_queued_audio_limit(wake, monkeypatch):
    class SlowConnector(FakeConnector):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()

        @asynccontextmanager
        async def __call__(self, model, config):
            await self.gate.wait()
            async with FakeConnector.__call__(self, model, config) as live:
                yield live

    connector = SlowConnector()
    wake.app.voice.connector = connector
    monkeypatch.setattr(voice_module, "QUEUED_AUDIO_LIMIT", 3)
    listener, stream = await listening(wake)
    await asyncio.to_thread(feed_chunks, stream, 0, 100)
    listener.detect()
    await until(lambda: OWNER in wake.app.voice.sessions)
    session = wake.app.voice.sessions[OWNER]
    await until(lambda: session.audio is not None and session.audio.ready)
    await asyncio.to_thread(feed_chunks, stream, 100, 20)  # 10 live frames; 3 fit
    await until(lambda: session.audio.backlog_dropped == 7)
    assert session.queued_audio == 3
    connector.gate.set()
    await until(lambda: connector.connections and len(sent_audio(connector.connections[-1])) == 41)
    assert sum(map(len, sent_audio(connector.connections[-1])[:38])) == PREROLL_BYTES


async def test_a_tray_click_start_sends_no_preroll(wake):
    _, stream = await listening(wake)
    await asyncio.to_thread(feed_chunks, stream, 0, 100)
    assert (await wake.app.voice.start_local())["ok"]
    session, live = await live_session(wake)
    assert not session.wake
    await asyncio.to_thread(feed_chunks, stream, 100, 4)
    await until(lambda: len(sent_audio(live)) == 2)
    await asyncio.sleep(0.05)
    assert b"".join(sent_audio(live)) == b"".join(ramp(index) for index in range(100, 104))


# --- detections ------------------------------------------------------------------------------


async def test_a_detection_with_no_session_plays_the_wake_cue_and_starts_tray_voice(wake):
    listener, _ = await listening(wake)
    listener.detect()
    session, _ = await live_session(wake)
    (cue,) = cue_streams(wake.backend)
    session_speaker = wake.backend.stream("output")
    assert wake.backend.streams.index(cue) < wake.backend.streams.index(session_speaker)
    assert (cue.device, cue.samplerate) == (4, 48000) and any(pull(cue))
    assert session.wake and session.endpoint == "local"
    await until(lambda: cue.released, timeout=3)


async def test_a_detection_during_workspace_voice_is_ignored(wake):
    app = wake.app
    app.resources.select("chat")
    listener, stream = await listening(wake)
    payload = {"mode": "conversation", "conversation_id": str(OWNER)}
    assert (await app.sio.handlers["/"]["voice_start"]("client", payload))["ok"]
    statuses = len(wake.statuses)
    await detection(wake, listener)
    assert not cue_streams(wake.backend) and not wake.service.microphone.armed
    assert app.voice.sessions[OWNER].endpoint == "renderer" and len(wake.statuses) == statuses


async def test_a_detection_while_jarvis_is_quiet_is_ignored_without_a_gap(wake):
    listener, stream = await listening(wake)
    assert (await wake.app.voice.start_local())["ok"]
    session, live = await live_session(wake)
    await asyncio.to_thread(feed_chunks, stream, 0, 10)
    await detection(wake, listener)
    await asyncio.to_thread(feed_chunks, stream, 10, 10)
    await until(lambda: len(sent_audio(live)) == 10)
    assert b"".join(sent_audio(live)) == b"".join(ramp(index) for index in range(20))
    assert not cue_streams(wake.backend) and not wake.service.microphone.armed
    assert session.state == "listening"


async def test_a_locked_pc_refuses_with_the_denied_cue_notice_and_balloon(wake):
    app = wake.app
    listener, _ = await listening(wake)
    app.settings["face_auth_enabled"] = True
    await detection(wake, listener)
    assert not app.voice.sessions and not wake.service.microphone.armed
    assert wake.statuses[-1] == {"active": False, "state": "off", "microphone": "off", "notice": LOCKED}
    assert wake.notices == ["voice_locked"]
    await until(lambda: cue_streams(wake.backend))
    (denied,) = cue_streams(wake.backend)  # only the denied cue: nothing to overlap
    assert denied.callback.__self__.data == cue_pcm("denied", 48000)
    await until(lambda: denied.released, timeout=3)
    assert len(cue_streams(wake.backend)) == 1 and not wake.backend.open_inputs()[0].aborted


async def test_a_late_refusal_plays_the_denied_cue_after_the_wake_cue_has_closed(wake):
    app = wake.app
    listener, _ = await listening(wake)

    def failing(**callbacks):  # passes the synchronous checks, then the speaker refuses
        raise ServiceError("audio_open_failed", "JARVIS could not open the speaker.")

    app.voice.audio_factory = failing
    opened = []
    create = wake.backend.RawOutputStream

    def output(**values):
        stream = create(**values)
        if isinstance(getattr(stream.callback, "__self__", None), Cue):
            opened.append((stream, [item.released for item in cue_streams(wake.backend)[:-1]]))
        return stream

    wake.backend.RawOutputStream = output
    await detection(wake, listener)
    assert not app.voice.sessions and not wake.service.microphone.armed
    assert wake.statuses[-1]["notice"] == "JARVIS could not open the speaker."
    await until(lambda: len(opened) == 2, timeout=3)
    (rising, before_rising), (falling, before_falling) = opened
    assert rising.callback.__self__.data == cue_pcm("wake", 48000) and before_rising == []
    assert falling.callback.__self__.data == cue_pcm("denied", 48000)
    assert before_falling == [True]  # the wake cue's stream had already closed
    assert wake.notices == []  # the unlock balloon is for face lock only


def test_the_unlock_balloon_shows_at_most_once_per_ten_minutes(tmp_path):
    from resident.host import NOTICES, NativeHost

    class NotifyingTray(FakeTray):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.shown = []

        def notify(self, *notice):
            self.shown.append(notice)
            return True

    native = NativeHost(tmp_path, tmp_path / "profile", tray_factory=NotifyingTray, resident_only=True)
    assert native.show_notice("voice_locked", now=1000.0)
    assert not native.show_notice("voice_locked", now=1599.0)
    assert native.show_notice("voice_locked", now=1600.0)
    assert native.tray.shown == [NOTICES["voice_locked"]] * 2
    assert NOTICES["voice_locked"][1] == "Unlock JARVIS in the workspace to talk."
    assert not native.show_notice("free text, never shown", now=5000.0)


# --- barge-in ------------------------------------------------------------------------------


async def speaking_session(wake, turn_complete=False):
    app = wake.app
    app.voice.clock = wake.clock
    listener, stream = await listening(wake)
    assert (await app.voice.start_local())["ok"]
    session, live = await live_session(wake)
    live.push(model_turn=speech(b"\x10\x00" * 4800), turn_complete=turn_complete or None)
    await until(lambda: session.audio.outbox and wake.statuses[-1]["state"] == "speaking")
    pull(wake.backend.stream("output"))  # playing: the tail clock starts now
    assert session.audio.speaking() and listener.audible
    return listener, stream, session, live


async def test_barge_in_flushes_playback_and_ends_the_tail_at_once(wake):
    listener, stream, session, live = await speaking_session(wake)
    await detection(wake, listener)
    audio = session.audio
    assert not audio.outbox and not audio.speaking()  # same instant: no 300 ms tail
    assert session.state == "listening" and wake.statuses[-1]["state"] == "listening"
    assert wake.statuses[-1]["microphone"] == "on" and not listener.audible
    assert not cue_streams(wake.backend)
    assert pull(wake.backend.stream("output")) == bytes(1920)
    # Frames from the detection onward reach Live straight away.
    count = len(sent_audio(live))
    await asyncio.to_thread(feed_chunks, stream, 0, 4)
    await until(lambda: len(sent_audio(live)) == count + 2)


async def test_the_servers_own_interruption_keeps_the_tail(wake):
    _, _, session, live = await speaking_session(wake)
    live.push(interrupted=True)
    await until(lambda: not session.audio.outbox)
    assert session.audio.speaking()  # J2: still muted for the tail


@pytest.mark.parametrize("end", ["interrupted", "turn_complete", "timeout"])
async def test_after_barge_in_the_rest_of_the_answer_is_dropped_until(wake, end):
    listener, _, session, live = await speaking_session(wake)
    await detection(wake, listener)
    assert session.drop_until == pytest.approx(wake.clock.now + 5)
    live.push(model_turn=speech())  # the interrupted answer keeps streaming
    await asyncio.sleep(0.05)
    assert not session.audio.outbox and session.state == "listening"
    assert wake.statuses[-1]["state"] == "listening"
    if end == "timeout":
        wake.clock.now += 5.01
    else:
        live.push(**{end: True})
        await until(lambda: session.drop_until is None)
    live.push(model_turn=speech())
    await until(lambda: session.audio.outbox)
    assert session.state == "speaking"


async def test_barge_in_after_a_completed_turn_drops_nothing(wake):
    listener, _, session, live = await speaking_session(wake, turn_complete=True)
    assert not session.model_streaming
    await detection(wake, listener)
    assert session.drop_until is None and not session.audio.outbox
    live.push(model_turn=speech())  # the answer to what the owner says next
    await until(lambda: session.audio.outbox)


# --- cues ----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["wake", "denied"])
def test_cues_are_two_faded_tones_at_about_minus_18_dbfs(kind):
    rate = 48000
    samples = array("h", cue_pcm(kind, rate))
    tone, gap, fade = 3360, 960, 480
    assert len(samples) == 2 * tone + gap
    peak = max(abs(value) for value in samples)
    assert abs(20 * math.log10(peak / 32767) + 18) < 0.1
    first, second = samples[:tone], samples[tone + gap :]
    assert not any(samples[tone : tone + gap])
    for part in (first, second):
        assert part[0] == 0 and abs(part[-1]) <= 5
        for index in range(fade):
            envelope = 0.5 - 0.5 * math.cos(math.pi * index / fade)
            assert abs(part[index]) <= peak * envelope + 1
    low, high = CUES[kind]
    for part, frequency, other in ((first, low, high), (second, high, low)):
        pcm = part.tobytes()
        assert goertzel_power(pcm, frequency, rate) > 100 * goertzel_power(pcm, other, rate)
    assert (low < high) == (kind == "wake")


async def test_a_cue_never_gates_the_microphone_or_counts_as_speaking(wake):
    _, stream = await listening(wake)
    assert (await wake.app.voice.start_local())["ok"]
    session, live = await live_session(wake)
    task = wake.service.play_cue("wake")
    await until(lambda: cue_streams(wake.backend))
    (cue,) = cue_streams(wake.backend)
    assert any(pull(cue)) and not session.audio.speaking()
    await asyncio.to_thread(feed_chunks, stream, 0, 4)
    await until(lambda: len(sent_audio(live)) == 2)  # not muted
    await task
    assert cue.released and wake.devices.open_streams == 2  # the shared microphone + speaker


async def test_a_speaker_that_cannot_open_skips_the_cue(wake, caplog):
    wake.backend.refuse = {("output", 4, 1), ("output", 4, 2)}
    with caplog.at_level("INFO"):
        await wake.service.play_cue("denied")
    assert not cue_streams(wake.backend) and "Skipped the denied cue" in caplog.text


# --- tray ------------------------------------------------------------------------------------


def test_tray_menu_has_the_wake_switch_checked_when_on():
    items = Tray.menu_items(SimpleNamespace(talking=False, wake_word=True))
    assert [action for action, _ in items] == [
        "open", "quick", "talk", "wake_word", "gaming", "diagnostics", "retry", "quit",
    ]
    assert items[3] == ("wake_word", 'Listen for "Hey Jarvis"')
    assert Tray.menu_flags(SimpleNamespace(wake_word=True), "wake_word") == MF_CHECKED == 0x8
    assert Tray.menu_flags(SimpleNamespace(wake_word=False), "wake_word") == 0
    assert Tray.menu_flags(SimpleNamespace(wake_word=True), "gaming") == 0


async def test_tray_toggle_saves_the_setting_and_tells_preferences(wake, host, tmp_path):  # noqa: F811 - fixture
    from services.settings import SettingsStore

    app = wake.app
    path = tmp_path / "settings.json"
    app.settings_service.store = SettingsStore(path)
    wake.service.observer = host.wake_changed
    host.loop = asyncio.get_running_loop()
    _, stream = await listening(wake)
    assert host.tray.wake_word and host.state.tooltip() == 'JARVIS · Native resident · Listening for "Hey Jarvis"'
    def saved_off():
        return [c for c in app.sio.emit.await_args_list
                if c.args[0] == "settings" and c.args[1]["voice"]["wake_word"] is False]

    host.action("wake_word")
    await until(lambda: not host.tray.wake_word and saved_off())
    assert json.loads(path.read_text())["voice"]["wake_word"] is False
    assert stream.released and wake.service.listener is None
    settings_events = [c for c in app.sio.emit.await_args_list if c.args[0] == "settings"]
    assert settings_events[-1].kwargs["room"] == "client"
    assert settings_events[-1].args[1]["voice"]["wake_word"] is False
    assert host.state.tooltip() == "JARVIS · Native resident"
    host.action("wake_word")
    await until(lambda: host.tray.wake_word and wake.service.listening())
    assert json.loads(path.read_text())["voice"]["wake_word"] is True


def test_tray_toggle_before_the_core_is_ready_says_so(tmp_path):
    from resident.host import NativeHost

    native = NativeHost(tmp_path, tmp_path / "profile", tray_factory=FakeTray, resident_only=True)
    assert native.toggle_wake() is None
    assert native.state.voice["notice"] == "JARVIS is still starting. Try again in a moment."


def test_tooltip_shows_hey_jarvis_only_with_the_setting_on(tmp_path):
    state = State(Identity(tmp_path))
    state.wake = {"setting": True, "state": "listening", "message": None}
    assert state.tooltip() == 'JARVIS · Native resident · Listening for "Hey Jarvis"'
    state.identity.gaming = True
    state.wake = {"setting": True, "state": "paused", "message": None}
    assert state.tooltip() == 'JARVIS · Gaming mode · "Hey Jarvis" paused'
    state.identity.gaming = False
    state.wake = {"setting": True, "state": "unavailable", "message": "No microphone."}
    assert state.tooltip() == 'JARVIS · Native resident · "Hey Jarvis" unavailable'
    state.wake = {"setting": False, "state": "off", "message": None}
    assert state.tooltip() == "JARVIS · Native resident"
    state.wake = {"setting": True, "state": "listening", "message": None}
    state.voice = {"active": True, "state": "speaking", "microphone": "paused", "notice": None}
    assert state.tooltip() == "JARVIS · Speaking · mic paused while JARVIS speaks"
    state.voice = {"active": False, "state": "off", "microphone": "off", "notice": "x" * 200}
    assert len(state.tooltip()) == 127
    assert state.tooltip().startswith('JARVIS · Native resident · Listening for "Hey Jarvis" · xx')


# --- status RPC and capability card ---------------------------------------------------------


async def test_status_rpc_is_owner_only_and_never_opens_a_device(wake):
    app = wake.app
    handler = app.sio.handlers["/"]["wake_word_status"]
    await listening(wake)
    count = len(wake.backend.streams)
    assert await handler("client", {}) == {"ok": True, "state": "listening", "message": None}
    assert await handler("client") == {"ok": True, "state": "listening", "message": None}
    assert (await handler("client", {"refresh": True}))["code"] == "invalid_arguments"
    assert (await handler("native-resident", {}))["code"] == "authentication_required"
    assert (await handler("stranger", {}))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = True  # locked
    assert (await handler("client", {}))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = False
    app.resources.select("gaming")
    assert await handler("client", {}) == {"ok": True, "state": "paused", "message": None}
    app.resources.select("resident")
    app.settings["voice"] = {"wake_word": False}
    assert await handler("client", {}) == {"ok": True, "state": "off", "message": None}
    assert len(wake.backend.streams) == count  # answered from state, nothing opened


async def test_status_rpc_without_models_names_the_fetch_command(tray):  # noqa: F811 - fixture
    handler = tray.app.sio.handlers["/"]["wake_word_status"]
    result = await handler("client", {})  # conftest's empty model folder
    assert result["ok"] and result["state"] == "unavailable"
    assert "model files are missing" in result["message"] or "wake-word extras" in result["message"]
    assert not tray.backend.streams


async def test_capability_card_reports_hey_jarvis(wake, monkeypatch):
    app = wake.app
    context = {"principal": OWNER, "project_path": app.projects.get_current_project_path()}

    def card():
        cards = app.capabilities.snapshot(context)["capabilities"]
        return next(item for item in cards if item["id"] == "wake_word")

    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 35)
    current = card()
    assert set(current) == set(next(c for c in app.capabilities.snapshot(context)["capabilities"]
                                    if c["id"] == "voice_local"))
    assert current["title"] == "Hey Jarvis" and current["status"] == "available"
    assert current["installed"] and current["configured"] and current["blocked"] is None
    assert current["reason"] == (
        'Say "Hey Jarvis" to start tray voice hands-free. Detection runs on this PC.'
    )
    app.resources.select("gaming")
    assert card()["blocked"] == "Voice pauses in gaming mode." and card()["status"] == "blocked"
    app.resources.select("resident")
    block_models(app)
    current = card()
    assert not current["configured"] and current["status"] == "setup_required"
    assert current["reason"] == MISSING_REASON
    monkeypatch.delenv("GEMINI_API_KEY")
    wake.service.status_reader = lambda: dict(AVAILABLE)
    monkeypatch.setattr("services.capabilities.provider_key", lambda: None)
    assert card()["configured"] is False


# --- harnesses ----------------------------------------------------------------------------


def test_harnesses_that_start_a_core_point_at_an_empty_wake_word_folder():
    starters = []
    for path in sorted((ROOT / "scripts").glob("verify-*.py")):
        text = path.read_text(encoding="utf-8")
        if "JARVIS_DATA_DIR" in text and ("NativeHost" in text or "import server" in text
                                           or "create_application" in text
                                           or '("JARVIS_LEGACY_DATA_DIR", "legacy")' in text):
            starters.append(path.name)
            assert "JARVIS_WAKE_WORD_DIR" in text, path.name
    assert {"verify-native.py", "verify-desktop-install.py", "verify-browser.py"} <= set(starters)
    resident = (ROOT / "scripts/verify-resident.cjs").read_text(encoding="utf-8")
    assert "process.env.JARVIS_WAKE_WORD_DIR = path.join(output, 'wake-word-empty')" in resident
    recovery = (ROOT / "scripts/verify-recovery-activation.py").read_text(encoding="utf-8")
    assert 'os.environ["JARVIS_WAKE_WORD_DIR"] = tempfile.mkdtemp(' in recovery
