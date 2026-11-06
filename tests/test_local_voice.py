"""Tray voice (J2) with a fake PortAudio backend and a fake Live session.

No real audio stream is ever opened: no microphone, no speaker, no network, no provider.
"""

import asyncio
from array import array
import struct
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from google.genai import types

from services.audio_contracts import local_devices
from services.audio_devices import AudioDevices, LocalAudio, downmix, upmix
from telephony.audio import Resampler, goertzel_power, tone
from tests.test_voice_live import FakeConnector, until

OWNER = str(uuid.UUID(int=7))
WASAPI = "Windows WASAPI"
GONE = "The saved microphone is not connected; using the system default."


class FakePortAudioError(Exception):
    pass


class FakeStream:
    def __init__(self, backend, kind, *, device, samplerate, channels, dtype, blocksize,
                 callback, finished_callback):
        if (kind, device, channels) in backend.refuse:
            raise FakePortAudioError("Invalid number of channels")
        assert dtype == "int16"
        self.backend, self.kind, self.device = backend, kind, device
        self.samplerate, self.channels, self.blocksize = samplerate, channels, blocksize
        self.callback, self.finished_callback = callback, finished_callback
        self.started = self.aborted = self.closed = False
        self.latency = 0.0
        backend.streams.append(self)

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True
        self.finished_callback()

    def close(self):
        self.closed = True

    @property
    def released(self):
        return self.aborted and self.closed


class FakeSoundDevice:
    """The slice of the sounddevice module that services/audio_devices.py uses."""

    PortAudioError = FakePortAudioError

    def __init__(self):
        self.hostapis = [
            {"name": "MME", "default_input_device": 0, "default_output_device": 1},
            {"name": WASAPI, "default_input_device": 2, "default_output_device": 4},
        ]
        self.devices = [
            {"name": "Microphone (Yeti Orb)", "hostapi": 0, "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "Speakers (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0,
             "max_output_channels": 2, "default_samplerate": 44100.0},
            {"name": "Microphone Array (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2,
             "max_output_channels": 0, "default_samplerate": 48000.0},
            {"name": "Microphone (Yeti Orb)", "hostapi": 1, "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 48000.0},
            {"name": "Speakers (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 0,
             "max_output_channels": 2, "default_samplerate": 48000.0},
            {"name": "Headphones (USB)", "hostapi": 1, "max_input_channels": 0,
             "max_output_channels": 2, "default_samplerate": 44100.0},
        ]
        self.streams = []
        self.refuse = set()
        self.refreshed = 0

    def query_hostapis(self):
        return [dict(item) for item in self.hostapis]

    def query_devices(self):
        return [dict(item, index=index) for index, item in enumerate(self.devices)]

    def RawInputStream(self, **values):  # the sounddevice names
        return FakeStream(self, "input", **values)

    def RawOutputStream(self, **values):
        return FakeStream(self, "output", **values)

    def _terminate(self):
        self.refreshed += 1

    def _initialize(self):
        pass

    def stream(self, kind):
        return next(item for item in reversed(self.streams) if item.kind == kind)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def block(stream, value=1000):
    """One device block of a constant level (never real audio)."""
    return struct.pack("<h", value) * stream.blocksize * stream.channels


def feed(stream, count, value=1000):
    """The PortAudio input thread delivering ``count`` blocks."""
    data = block(stream, value)
    for _ in range(count):
        stream.callback(data, stream.blocksize, None, 0)


def pull(stream):
    """The PortAudio output thread asking for one block."""
    out = bytearray(stream.blocksize * stream.channels * 2)
    stream.callback(out, stream.blocksize, None, 0)
    return bytes(out)


def audio_frames(live):
    return [item["audio"] for item in live.sent if "audio" in item]


def speech(chunk=b"\x10\x00" * 1200):
    return types.Content(
        role="model",
        parts=[types.Part(inline_data=types.Blob(data=chunk, mime_type="audio/pcm;rate=24000"))],
    )


@pytest.fixture
def tray(application_factory):
    app = application_factory()
    app.sessions.attach_native(OWNER)  # the resident's own channel: local owner, authenticated
    app.sessions.principals["client"] = OWNER
    app.sessions.roles["client"] = "renderer"
    app.resources.select("resident")  # the workspace is closed
    connector = FakeConnector()
    app.voice.connector = connector
    app.voice.preflight = lambda: None
    app.voice.retry_delay = 0
    app.voice.tick = 0.01
    backend = FakeSoundDevice()
    devices = AudioDevices(loader=lambda: backend)
    app.audio_devices = devices
    clock = Clock()
    options = {"clock": clock, "stall": 1e9, "poll": 0.01}

    def factory(**callbacks):
        return LocalAudio(app.audio_devices, **{**options, **callbacks})

    app.voice.audio_factory = factory
    statuses = []
    app.voice.local_observer = statuses.append
    context = SimpleNamespace(
        app=app, connector=connector, backend=backend, devices=devices, clock=clock,
        statuses=statuses, options=options,
    )
    yield context
    devices.close()


async def start(tray):
    count = len(tray.connector.connections)
    result = await tray.app.voice.start_local()
    assert result["ok"], result
    await until(lambda: len(tray.connector.connections) > count)
    live = tray.connector.connections[-1]
    session = tray.app.voice.sessions[OWNER]
    await until(lambda: session.live is live)
    return result, live, session


async def stopped(tray):
    await until(lambda: not tray.app.voice.sessions and tray.statuses[-1]["active"] is False)
    return tray.statuses[-1]


# --- resampling and channel conversion ---------------------------------------------------


@pytest.mark.parametrize(
    "source,target", [(48000, 16000), (44100, 16000), (24000, 48000), (24000, 44100)]
)
def test_device_rate_resampling_keeps_pitch_length_and_level(source, target):
    signal = tone(1000, 1.0, source, 0.5)
    block_bytes = source // 50 * 2  # 20 ms device blocks, streamed
    resampler = Resampler(source, target)
    output = b"".join(
        resampler.process(signal[start : start + block_bytes])
        for start in range(0, len(signal), block_bytes)
    )
    assert abs(len(output) // 2 - target) <= 1
    steady = output[len(output) // 4 :]
    wanted = goertzel_power(steady, 1000, target)
    for other in (500, 1500, 3000, 6000):
        assert wanted > 1000 * goertzel_power(steady, other, target)  # > 30 dB
    rms = lambda pcm: (sum(v * v for v in array("h", pcm)) / (len(pcm) // 2)) ** 0.5  # noqa: E731
    middle = signal[len(signal) // 4 : len(signal) * 3 // 4]
    assert abs(rms(steady) / rms(middle) - 1) < 0.05


def test_capture_rejects_aliases_above_live_nyquist():
    reference = Resampler(48000, 16000).process(tone(1000, 0.5, 48000, 0.5))
    aliased = Resampler(48000, 16000).process(tone(12000, 0.5, 48000, 0.5))  # would fold to 4 kHz
    assert goertzel_power(aliased[3200:], 4000, 16000) * 1e5 < goertzel_power(
        reference[3200:], 1000, 16000
    )


def test_channel_conversion():
    stereo = struct.pack("<6h", 1, 100, 2, 200, 3, 300)
    assert downmix(stereo, 2) == struct.pack("<3h", 1, 2, 3)
    assert downmix(stereo, 1) == stereo
    assert upmix(struct.pack("<2h", 5, -6), 3) == struct.pack("<6h", 5, 5, 5, -6, -6, -6)


# --- device listing ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_reads_wasapi_devices_without_opening_any(tray):
    report = await tray.devices.report()
    assert report["available"] and report["host_api"] == WASAPI
    assert [item["name"] for item in report["inputs"]] == [
        "Microphone Array (Realtek(R) Audio)",
        "Microphone (Yeti Orb)",
    ]
    assert report["inputs"][0] == {
        "name": "Microphone Array (Realtek(R) Audio)",
        "host_api": WASAPI,
        "default": True,
        "channels": 2,
        "sample_rate": 48000,
    }
    assert [(item["name"], item["default"]) for item in report["outputs"]] == [
        ("Speakers (Realtek(R) Audio)", True),
        ("Headphones (USB)", False),
    ]
    assert not tray.backend.streams and tray.backend.refreshed == 1
    assert tray.devices.status() == {"installed": True, "reason": None}


@pytest.mark.asyncio
async def test_missing_library_is_a_setup_state_not_a_crash(tray, monkeypatch):
    def missing():
        raise ImportError("No module named 'sounddevice'")

    devices = AudioDevices(loader=missing)
    report = await devices.report()
    assert report["available"] is False and report["code"] == "audio_unavailable"
    assert "sounddevice" in report["message"] and report["inputs"] == report["outputs"] == []
    assert devices.status()["installed"] is False
    devices.close()
    tray.app.audio_devices = devices
    result = await tray.app.voice.start_local()
    assert result["ok"] is False and result["code"] == "audio_unavailable"
    assert not tray.app.voice.sessions and not tray.connector.connections
    assert tray.statuses[-1] == {
        "active": False, "state": "off", "microphone": "off", "notice": result["message"],
    }


@pytest.mark.asyncio
async def test_audio_devices_route_is_owner_renderer_only(tray):
    app = tray.app
    handler = app.sio.handlers["/"]["audio_devices"]
    ack = await handler("client", {})
    assert ack["ok"] and ack["available"] and len(ack["outputs"]) == 2
    assert (await handler("client", {"refresh": True}))["code"] == "invalid_arguments"
    assert (await handler("native-resident", {}))["code"] == "authentication_required"
    assert (await handler("stranger", {}))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = True  # locked
    assert (await handler("client", {}))["code"] == "authentication_required"


def test_composing_the_core_never_imports_the_audio_library(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; from application import create_application; "
        "from services.storage import Database; "
        f"app = create_application(settings={{'tool_permissions': {{}}}}, project_root=r'{tmp_path}', "
        f"legacy_data_dir=r'{tmp_path}', database=Database(r'{tmp_path / 'db'}')); "
        "app.audio_devices.status(); "
        "assert 'sounddevice' not in sys.modules and '_sounddevice' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={**__import__("os").environ, "PYTHONPATH": "backend"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    not __import__("services.audio_devices", fromlist=["installed"]).installed(),
    reason="sounddevice is not installed",
)
@pytest.mark.asyncio
async def test_real_device_enumeration_smoke():
    """Enumerates this PC's devices through PortAudio; opens none."""
    devices = AudioDevices()
    try:
        report = await devices.report()
    finally:
        devices.close()
    assert isinstance(report["available"], bool)
    if report["available"]:
        assert all(item["sample_rate"] >= 8000 for item in report["inputs"] + report["outputs"])
    assert devices.open_streams == 0


# --- capture, half-duplex, playback ------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_resamples_to_16k_frames_for_live(tray):
    result, live, session = await start(tray)
    assert result["notices"] == [] and result["conversation_id"]
    microphone, speaker = tray.backend.stream("input"), tray.backend.stream("output")
    assert (microphone.device, microphone.samplerate, microphone.channels) == (2, 48000, 1)
    assert (speaker.device, speaker.samplerate, speaker.blocksize) == (4, 48000, 960)
    assert microphone.started and speaker.started
    # Hands-free: Gemini server VAD.
    assert live.config.realtime_input_config.automatic_activity_detection.disabled is False
    # 200 ms of 48 kHz blocks from the PortAudio thread -> five 40 ms frames at 16 kHz.
    await asyncio.to_thread(feed, microphone, 10)
    await until(lambda: len(audio_frames(live)) >= 4)
    frames = audio_frames(live)
    assert all(item.mime_type == "audio/pcm;rate=16000" and len(item.data) == 1280 for item in frames)
    # The steady level survives resampling (the first frame holds the filter's ramp-up).
    level = array("h", frames[-1].data)
    assert all(abs(sample - 1000) <= 20 for sample in level[len(level) // 2 :])
    assert tray.statuses[-1] == {
        "active": True, "state": "listening", "microphone": "on", "notice": None,
    }
    await tray.app.voice.stop_local()
    assert microphone.released and speaker.released


@pytest.mark.asyncio
async def test_input_overflow_drops_the_oldest_blocks_and_counts(tray):
    _, live, session = await start(tray)
    audio = session.audio
    microphone = tray.backend.stream("input")
    gate = threading.Event()
    original = audio._drain
    audio._drain = lambda: gate.wait(5) and original()  # the core loop is busy
    data = block(microphone)
    try:
        for _ in range(audio.inbox.maxlen + 5):
            microphone.callback(data, microphone.blocksize, None, 0)
        assert len(audio.inbox) == audio.inbox.maxlen and audio.input_dropped == 5
    finally:
        gate.set()
        audio._drain = original
    await tray.app.voice.stop_local()


@pytest.mark.asyncio
async def test_half_duplex_mutes_the_microphone_while_speaking_and_for_the_tail(tray):
    _, live, session = await start(tray)
    audio, clock = session.audio, tray.clock
    microphone, speaker = tray.backend.stream("input"), tray.backend.stream("output")
    await asyncio.to_thread(feed, microphone, 2)
    await until(lambda: len(audio_frames(live)) == 1)
    live.push(model_turn=speech())
    await until(lambda: audio.outbox)
    assert tray.app.voice.local_status(session)["microphone"] == "paused"
    assert tray.statuses[-1]["state"] == "speaking" and tray.statuses[-1]["microphone"] == "paused"
    # 50 ms of 24 kHz speech -> 2400 samples at 48 kHz in 20 ms speaker blocks.
    assert sum(len(item) for item in audio.outbox) == 4800
    await asyncio.to_thread(feed, microphone, 4)
    await asyncio.sleep(0.05)
    assert len(audio_frames(live)) == 1 and audio.gated >= 1
    played = [pull(speaker) for _ in range(3)]
    assert not audio.outbox and any(any(chunk) for chunk in played)
    assert pull(speaker) == bytes(1920)  # drained: silence
    # The tail: still muted 0.25 s after the last audible block.
    clock.now += 0.25
    gated = audio.gated
    await asyncio.to_thread(feed, microphone, 4)
    await asyncio.sleep(0.05)
    assert len(audio_frames(live)) == 1 and audio.gated > gated
    clock.now += 0.1  # past the 300 ms tail
    await until(lambda: tray.statuses[-1]["microphone"] == "on")
    await asyncio.to_thread(feed, microphone, 4)
    await until(lambda: len(audio_frames(live)) >= 2)
    await tray.app.voice.stop_local()


@pytest.mark.asyncio
async def test_interruption_flushes_playback_at_once(tray):
    _, live, session = await start(tray)
    audio, speaker = session.audio, tray.backend.stream("output")
    live.push(model_turn=speech(b"\x10\x00" * 4800))
    await until(lambda: len(audio.outbox) >= 5)
    pull(speaker)  # part-way through playback
    live.push(interrupted=True)
    await until(lambda: not audio.outbox)
    assert pull(speaker) == bytes(1920)  # the partly played block is dropped too
    await tray.app.voice.stop_local()


@pytest.mark.asyncio
async def test_stereo_only_devices_are_opened_with_their_channels(tray):
    tray.backend.refuse = {("input", 2, 1), ("output", 4, 1)}
    _, live, session = await start(tray)
    microphone, speaker = tray.backend.stream("input"), tray.backend.stream("output")
    assert microphone.channels == speaker.channels == 2
    await asyncio.to_thread(feed, microphone, 4)
    await until(lambda: audio_frames(live))
    assert len(audio_frames(live)[0].data) == 1280  # mono 16 kHz regardless
    live.push(model_turn=speech())
    await until(lambda: session.audio.outbox)
    samples = array("h", pull(speaker))
    assert len(samples) == 1920 and samples[0::2] == samples[1::2]  # same sample both sides
    await tray.app.voice.stop_local()


# --- devices: fallback and loss ----------------------------------------------------------


@pytest.mark.asyncio
async def test_saved_devices_are_used_and_a_missing_one_falls_back_to_default(tray):
    app = tray.app
    app.settings["voice"] = {
        "local_microphone": {"name": "Microphone (Yeti Orb)", "host_api": WASAPI},
        "local_speaker": {"name": "Headphones (USB)", "host_api": WASAPI},
    }
    result, _, _ = await start(tray)
    assert result["notices"] == []
    assert tray.backend.stream("input").device == 3
    speaker = tray.backend.stream("output")
    assert (speaker.device, speaker.samplerate, speaker.blocksize) == (5, 44100, 882)
    await app.voice.stop_local()
    app.settings["voice"]["local_microphone"] = {"name": "Unplugged mic", "host_api": WASAPI}
    result, _, _ = await start(tray)
    assert result["notices"] == [GONE]
    assert tray.backend.stream("input").device == 2  # the WASAPI default
    assert tray.statuses[-1]["notice"] == GONE and tray.statuses[-1]["active"]
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_no_microphone_at_all_refuses_with_a_message(tray):
    for item in tray.backend.devices:
        item["max_input_channels"] = 0
    result = await tray.app.voice.start_local()
    assert result == {
        "ok": False,
        "code": "audio_device_missing",
        "message": "No microphone is connected. Connect one and try again.",
    }
    assert not tray.app.voice.sessions and not tray.connector.connections
    assert not tray.backend.streams


@pytest.mark.asyncio
async def test_failed_open_releases_what_was_opened(tray):
    tray.backend.refuse = {("output", 4, 1), ("output", 4, 2)}
    result = await tray.app.voice.start_local()
    assert result["ok"] is False and result["code"] == "audio_open_failed"
    (microphone,) = tray.backend.streams
    assert microphone.released and tray.devices.open_streams == 0
    assert not tray.app.voice.sessions and not tray.connector.connections


@pytest.mark.asyncio
async def test_device_lost_mid_session_ends_cleanly_with_a_message(tray):
    _, live, session = await start(tray)
    microphone, speaker = tray.backend.stream("input"), tray.backend.stream("output")
    # PortAudio stops the stream on its own thread (the device was unplugged).
    await asyncio.to_thread(microphone.finished_callback)
    status = await stopped(tray)
    assert status == {
        "active": False,
        "state": "off",
        "microphone": "off",
        "notice": "The microphone was disconnected. Voice is off.",
    }
    assert microphone.released and speaker.released and live.closed
    assert tray.devices.open_streams == 0


@pytest.mark.asyncio
async def test_a_silent_device_counts_as_lost(tray):
    tray.options.update(clock=time.monotonic, stall=0.1, grace=0.0)
    _, live, _ = await start(tray)
    speaker = tray.backend.stream("output")
    stop = threading.Event()

    def speaker_thread():  # the speaker keeps calling back; the microphone never does
        while not stop.is_set():
            pull(speaker)
            time.sleep(0.01)

    worker = threading.Thread(target=speaker_thread)
    worker.start()
    try:
        status = await stopped(tray)
    finally:
        stop.set()
        worker.join()
    assert status["notice"] == "The microphone was disconnected. Voice is off."
    assert live.closed and tray.devices.open_streams == 0


# --- policy: resident, gaming, one session per owner -------------------------------------


@pytest.mark.asyncio
async def test_resident_allowed_gaming_refused_and_stops_an_active_session(tray):
    app = tray.app
    assert app.resources.state == "resident"
    # Hold the watchdog back so the explicit restriction is what stops this session (with a
    # 10 ms tick the watchdog could win the race and end it with its own message).
    app.voice.tick = 60
    _, live, _ = await start(tray)
    microphone, speaker = tray.backend.stream("input"), tray.backend.stream("output")
    # Closing the workspace again (resident restriction) leaves tray voice running.
    await app.restrict_resources()
    assert app.voice.sessions and not microphone.aborted
    app.resources.select("gaming")
    await app.restrict_resources()
    status = await stopped(tray)
    assert status["notice"] == "Voice stopped for gaming mode."
    assert microphone.released and speaker.released and live.closed
    count = len(tray.backend.streams)
    result = await app.voice.start_local()
    assert result["code"] == "gaming_mode" and len(tray.backend.streams) == count
    # The watchdog also refuses gaming mode each second for a session that slipped through.
    app.voice.tick = 0.01
    app.resources.select("chat")
    await start(tray)
    app.resources.select("gaming")
    assert (await stopped(tray))["notice"] == "Voice pauses in gaming mode. Typed input is available."


@pytest.mark.asyncio
async def test_lock_and_denied_microphone_permission_refuse_tray_voice(tray):
    app = tray.app
    app.settings["tool_permissions"]["start_audio"] = "deny"
    assert (await app.voice.start_local())["code"] == "permission_denied"
    app.settings["tool_permissions"]["start_audio"] = False
    app.settings["face_auth_enabled"] = True
    assert (await app.voice.start_local())["code"] == "authentication_required"
    assert not tray.backend.streams


@pytest.mark.asyncio
async def test_one_session_per_owner_across_tray_and_renderer(tray):
    app = tray.app
    app.resources.select("chat")  # workspace open
    payload = {"mode": "conversation", "conversation_id": str(uuid.uuid4())}
    ack = await app.sio.handlers["/"]["voice_start"]("client", payload)
    assert ack["ok"]
    result = await app.voice.start_local()
    assert result == {
        "ok": False,
        "code": "voice_busy",
        "message": "Voice is already on in the workspace. Stop it there first.",
    }
    assert not tray.backend.streams
    await app.sio.handlers["/"]["voice_stop"]("client", {"session_id": ack["session_id"]})
    await start(tray)
    busy = await app.sio.handlers["/"]["voice_start"]("client", payload)
    assert busy == {
        "ok": False,
        "code": "voice_busy",
        "message": "Voice is already on from the tray. Stop it there first.",
    }
    assert (await app.voice.start_local())["message"] == "Voice is already on."
    # The renderer's own stop and disconnect never reach the tray session.
    await app.disconnect("client")
    assert app.voice.sessions[OWNER].endpoint == "local"
    await app.voice.stop_local()


# --- conversations ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turns_join_the_conversation_the_workspace_showed(tray):
    app = tray.app
    project = app.projects.get_current_project_path().resolve()
    shown = str(uuid.uuid4())
    await app.sio.handlers["/"]["resume_conversation"]("client", {"conversation_id": shown})
    restored = [c.args[1] for c in app.sio.emit.await_args_list if c.args[0] == "conversation_restored"]
    assert "latest_conversation_id" not in restored[-1]
    result, live, _ = await start(tray)
    assert result["conversation_id"] == shown
    app.sio.emit.reset_mock()
    live.push(input_transcription=types.Transcription(text="What's on today?"))
    live.push(output_transcription=types.Transcription(text="Two meetings."))
    live.push(turn_complete=True)

    def history():
        return app.conversation.restore(OWNER, shown, project)

    await until(lambda: len(history()) == 2)
    assert history() == [
        {"role": "user", "content": "What's on today?"},
        {"role": "assistant", "content": "Two meetings."},
    ]
    # The open workspace (on that conversation) is refreshed; captions never go to sockets.
    await until(lambda: any(c.args[0] == "conversation_restored" for c in app.sio.emit.await_args_list))
    events = [(c.args[0], c.kwargs.get("room")) for c in app.sio.emit.await_args_list]
    assert ("conversation_restored", "client") in events
    assert not {"voice_caption", "voice_state", "voice_audio_out"} & {name for name, _ in events}
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_without_a_shown_conversation_tray_voice_uses_the_latest_or_a_new_one(tray):
    app = tray.app
    project = app.projects.get_current_project_path().resolve()
    # Nothing yet for this project: a new conversation, which the workspace adopts on open.
    result, live, _ = await start(tray)
    created = result["conversation_id"]
    live.push(input_transcription=types.Transcription(text="Hello"))
    live.push(output_transcription=types.Transcription(text="Hello."))
    live.push(turn_complete=True)
    await until(lambda: len(app.conversation.restore(OWNER, created, project)) == 2)
    await app.voice.stop_local()
    stale = str(uuid.uuid4())  # the workspace's own (empty) conversation id
    await app.sio.handlers["/"]["resume_conversation"]("client", {"conversation_id": stale})
    restored = [c.args[1] for c in app.sio.emit.await_args_list if c.args[0] == "conversation_restored"]
    assert restored[-1]["conversation_id"] == stale
    assert restored[-1]["latest_conversation_id"] == created
    await app.sio.handlers["/"]["resume_conversation"]("client", {"conversation_id": created})
    restored = [c.args[1] for c in app.sio.emit.await_args_list if c.args[0] == "conversation_restored"]
    assert restored[-1]["conversation_id"] == created and "latest_conversation_id" not in restored[-1]
    assert len(restored[-1]["messages"]) == 2
    # Later tray sessions follow what the workspace shows.
    result, _, _ = await start(tray)
    assert result["conversation_id"] == created
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_an_existing_conversation_is_joined_when_none_was_shown(tray):
    app = tray.app
    project = app.projects.get_current_project_path().resolve()
    earlier = str(uuid.uuid4())
    await app.conversation.append_turns(
        OWNER, earlier, project,
        [{"role": "user", "content": "Earlier"}, {"role": "assistant", "content": "Noted."}],
    )
    result, _, _ = await start(tray)
    assert result["conversation_id"] == earlier
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_brain_approvals_need_an_open_workspace(tray):
    from llm.base import LLMResponse, ToolCall
    from tests.test_voice_live import FakeProvider

    app = tray.app
    app.settings["tool_permissions"]["write_file"] = True  # asks the owner first
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})]),
            LLMResponse(text="I need your approval on screen for that."),
        ]
    )
    app.conversation.provider_factory = lambda: provider
    app.sessions.principals.pop("client")  # no workspace open
    _, live, _ = await start(tray)
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="fc", name="ask_brain", args={"request": "write a"})]
        )
    )
    await until(lambda: live.tool_responses)
    assert live.tool_responses[0][0].response == {"result": "I need your approval on screen for that."}
    tool_result = provider.calls[1][-1]
    assert "approval_unavailable" in str(tool_result.content)
    assert not (app.projects.get_current_project_path() / "a.txt").exists()
    assert not [c for c in app.sio.emit.await_args_list if c.args[0] == "tool_confirmation_request"]
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_brain_approvals_go_to_the_open_workspace(tray):
    from llm.base import LLMResponse, ToolCall
    from tests.test_voice_live import FakeProvider

    app = tray.app
    app.settings["tool_permissions"]["write_file"] = True
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[ToolCall("c1", "write_file", {"path": "b.txt", "content": "y"})]),
            LLMResponse(text="Saved b.txt."),
        ]
    )
    app.conversation.provider_factory = lambda: provider
    _, live, session = await start(tray)
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="fc", name="ask_brain", args={"request": "write b"})]
        )
    )
    await until(lambda: app.dispatcher.pending)
    (request,) = [c for c in app.sio.emit.await_args_list if c.args[0] == "tool_confirmation_request"]
    assert request.kwargs["room"] == "client" and request.args[1]["voice_session_id"] == session.id
    assert app.dispatcher.resolve(OWNER, request.args[1]["id"], True)
    await until(lambda: live.tool_responses)
    assert live.tool_responses[0][0].response == {"result": "Saved b.txt."}
    assert (app.projects.get_current_project_path() / "b.txt").read_text() == "y"
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_silence_watchdog_ends_tray_voice_quietly(tray):
    tray.app.voice.silence = 0.1
    _, live, _ = await start(tray)
    status = await stopped(tray)
    assert status["notice"] is None and live.closed
    assert tray.backend.stream("input").released


# --- the resident tray ------------------------------------------------------------------


class FakeTray:
    window = None
    secondary = False
    hotkey = False

    def __init__(self, *args, **kwargs):
        self.talking = False

    def post(self, callback):
        callback()

    def close(self):
        pass


@pytest.fixture
def host(tray, tmp_path):
    from resident.host import NativeHost

    native = NativeHost(tmp_path, tmp_path / "profile", tray_factory=FakeTray, resident_only=True)
    native.state.identity.register(OWNER)
    native.state.phase = "ready"
    app = tray.app
    native.runtime = SimpleNamespace(
        runtime=app,
        set_resource_state=app.lifecycle.set_resource_state,
        client_principals={},
        sio=app.sio,
    )
    app.sessions.native_desktop = native
    app.voice.local_observer = native.voice_changed
    return native


@pytest.mark.asyncio
async def test_tray_talk_and_stop_through_the_resident_action_path(tray, host):
    app = tray.app
    host.action("talk")  # the core loop is not running yet in this host
    assert host.state.voice["notice"] == "JARVIS is still starting. Try again in a moment."
    host.loop = asyncio.get_running_loop()
    host.action("talk")
    await until(lambda: app.voice.sessions and tray.connector.connections)
    await until(lambda: host.tray.talking and host.state.voice["state"] == "listening")
    assert host.state.tooltip() == "JARVIS · Listening · mic on"
    microphone = tray.backend.stream("input")
    assert microphone.started and not microphone.aborted
    tray.connector.connections[-1].push(model_turn=speech())
    await until(lambda: host.state.voice["microphone"] == "paused")
    assert host.state.tooltip() == "JARVIS · Speaking · mic paused while JARVIS speaks"
    host.action("stop_talking")
    await until(lambda: not app.voice.sessions and not host.tray.talking)
    assert microphone.released and tray.backend.stream("output").released
    assert host.state.tooltip() == "JARVIS · Native resident"


@pytest.mark.asyncio
async def test_tray_gaming_toggle_stops_tray_voice_and_closes_devices(tray, host):
    app = tray.app
    host.loop = asyncio.get_running_loop()
    host.action("talk")
    await until(lambda: host.tray.talking)
    microphone = tray.backend.stream("input")
    host.action("gaming")
    await until(lambda: not app.voice.sessions and not host.tray.talking)
    assert app.resources.state == "gaming" and microphone.released
    assert host.state.tooltip() == "JARVIS · Gaming mode · Voice stopped for gaming mode."
    host.action("talk")
    await until(lambda: host.state.voice["notice"].startswith("Voice pauses in gaming mode"))
    assert not app.voice.sessions and len(tray.backend.streams) == 2


def test_tray_menu_offers_talk_or_stop():
    from resident.win32 import Tray

    assert [item[1] for item in Tray.menu_items(SimpleNamespace(talking=False))] == [
        "Open JARVIS", "Talk to JARVIS", 'Listen for "Hey Jarvis"', "Toggle gaming mode",
        "Retry backend", "Quit JARVIS",
    ]
    assert Tray.menu_items(SimpleNamespace(talking=True))[1] == ("stop_talking", "Stop talking")


def test_tooltip_text_for_each_state(tmp_path):
    from resident.state import Identity, State

    state = State(Identity(tmp_path))
    assert state.tooltip() == "JARVIS · Native resident"
    state.voice = {"active": True, "state": "thinking", "microphone": "on", "notice": GONE}
    assert state.tooltip() == f"JARVIS · Thinking · mic on · {GONE}"
    state.voice = {"active": False, "state": "off", "microphone": "off", "notice": None}
    state.visible = True
    assert state.tooltip() == "JARVIS · Workspace open"


# --- settings and capability -------------------------------------------------------------


def test_device_settings_validate_and_read_with_defaults(tmp_path):
    from pydantic import ValidationError
    from services.settings import SettingsPatch, SettingsService, SettingsStore

    choice = {"name": "Microphone (Yeti Orb)", "host_api": WASAPI}
    for bad in (
        {"local_microphone": None},
        {"local_microphone": "Default"},
        {"local_microphone": 2},  # an index is never a stable identifier
        {"local_microphone": {"name": "Yeti"}},
        {"local_microphone": {**choice, "index": 3}},
        {"local_speaker": {"name": "Bad\r\nname", "host_api": WASAPI}},
        {"local_speaker": {"name": "x" * 201, "host_api": WASAPI}},
    ):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"voice": bad})
    settings = {"tool_permissions": {}}
    assert local_devices(settings) == {"microphone": "default", "speaker": "default"}
    service = SettingsService(settings, SettingsStore(tmp_path / "settings.json"), set())
    service.apply(SettingsPatch.model_validate({"voice": {"local_microphone": choice}}))
    assert settings["voice"]["local_microphone"] == choice and settings["voice"]["name"] == "Kore"
    service.apply(SettingsPatch.model_validate({"voice": {"local_speaker": "default"}}))
    assert local_devices(settings) == {"microphone": choice, "speaker": "default"}
    # A stale value on disk reads as the default; files are never migrated on startup.
    assert local_devices({"voice": {"local_microphone": {"name": 3}}})["microphone"] == "default"


@pytest.mark.asyncio
async def test_capability_card_reports_tray_voice(tray, monkeypatch):
    app = tray.app
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 35)
    context = {"principal": OWNER, "project_path": app.projects.get_current_project_path()}
    card = next(c for c in app.capabilities.snapshot(context)["capabilities"] if c["id"] == "voice_local")
    assert card["installed"] is __import__("services.audio_devices", fromlist=["x"]).installed()
    assert card["blocked"] is None  # resident mode is where tray voice lives
    app.resources.select("gaming")
    card = next(c for c in app.capabilities.snapshot(context)["capabilities"] if c["id"] == "voice_local")
    assert card["blocked"] == "Voice pauses in gaming mode."
    tray.devices.failure = "Tray voice needs the sounddevice audio library."
    card = next(c for c in app.capabilities.snapshot(context)["capabilities"] if c["id"] == "voice_local")
    assert card["installed"] is False and card["status"] == "setup_required"
