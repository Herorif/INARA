"""Synthetic call/control/media fixtures. No actual app, phone, audio or API activation."""

import asyncio
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from calls.audio import DedicatedAudio, resolve_endpoints
from calls.contracts import BridgeProfile, Observation, CALL_INSTRUCTION
from calls.records import CallRecords
from calls.session import CallSession
from calls.voice import LiveVoice
from services.storage import Database
from services.tools import ServiceError


def profile(**changes):
    value = dict(
        channel="whatsapp_personal", pid=123, executable="C:\\CallClient\\WhatsApp.exe",
        sha256="a" * 64, process_start="123456789", window_class="fixture-call-window",
        answer_id="fixture-answer", decline_id="fixture-decline", hangup_id="fixture-hangup",
        caller_id="fixture-caller", ended_id="fixture-ended", capture_endpoint="Dedicated call receive",
        playback_endpoint="Dedicated call transmit", route_confirmed=True,
        controls_confirmed=True)
    return BridgeProfile.model_validate({**value, **changes})


def observed(state="ringing", **changes):
    return Observation(state=state, fingerprint="b" * 64, caller_hash="c" * 64,
                       view_id="e" * 64, process_start="123456789").model_copy(update=changes)


class Control:
    def __init__(self, values=None, answer_error=None):
        self.values = list(values or [observed(), observed(), observed("active"), observed("ended"), observed("ended")])
        self.last = self.values[-1]
        self.answers, self.hangups = [], []
        self.answer_error = answer_error

    async def observe(self):
        return self.values.pop(0) if self.values else self.last

    async def answer(self, value):
        self.answers.append(value)
        if self.answer_error:
            raise self.answer_error

    async def hangup(self, value):
        self.hangups.append(value)


class Audio:
    def __init__(self, fail=False):
        self.fail, self.opened, self.closed, self.activated = fail, False, False, False
        self.output, self.cleared = [], 0

    async def open(self):
        self.opened = True
        if self.fail:
            raise ServiceError("call_audio_unverified", "fixture")

    def activate(self):
        self.activated = True

    async def close(self):
        self.closed = True

    async def read(self):
        await asyncio.Event().wait()

    async def write(self, data):
        self.output.append(data)

    async def clear(self):
        self.cleared += 1


class Voice:
    def __init__(self, events=None):
        self.values = events if events is not None else [
            {"kind": "transcript", "role": "caller", "text": "Please call me tomorrow"},
            {"kind": "transcript", "role": "assistant", "text": "I will leave your message."},
            {"kind": "audio", "data": b"\x00\x00" * 480},
            {"kind": "interrupted"},
        ]
        self.greeted = False
        self.closed = False

    async def greet(self):
        self.greeted = True

    async def send(self, data):
        pass

    async def events(self):
        for item in self.values:
            if isinstance(item, Exception):
                raise item
            yield item
        await asyncio.Event().wait()

    @asynccontextmanager
    async def connection(self):
        try:
            yield self
        finally:
            self.closed = True


def fixture(tmp_path, control=None, audio=None, voice=None, config=None):
    control, audio, voice = control or Control(), audio or Audio(), voice or Voice()
    records = CallRecords(Database(tmp_path))
    session = CallSession(config or profile(), control, audio, voice.connection, records)
    return session, control, audio, voice, records


@pytest.mark.parametrize("field,value", [
    ("route_confirmed", "true"), ("pid", True), ("max_seconds", 181),
    ("executable", "WhatsApp.exe"), ("executable", "C:\\tools\\powershell.exe"),
    ("channel", "business"), ("answer_id", "fixture-hangup"),
    ("playback_endpoint", "Dedicated call receive"), ("owner_tools", True),
])
def test_profile_rejects_unsafe_or_ambiguous_enrollment(field, value):
    with pytest.raises(ValidationError):
        profile(**{field: value})


@pytest.mark.asyncio
async def test_one_call_lifecycle_transcript_interruption_and_protected_record(tmp_path):
    session, control, audio, voice, records = fixture(tmp_path)
    result = await session.run()
    assert result["state"] == "completed"
    assert len(control.answers) == 1 and not control.hangups
    assert audio.activated and audio.closed and voice.closed and voice.greeted
    assert audio.output and audio.cleared == 1 and not session.tasks
    assert result["identity_verified"] is False and result["message_confirmed"] is False
    assert records.recent()[0]["transcript"][0]["text"] == "Please call me tomorrow"
    with records.database.connection() as db:
        payload = db.execute("SELECT payload FROM documents WHERE kind=?", (records.kind,)).fetchone()[0]
        assert b"Please call me tomorrow" not in payload


@pytest.mark.asyncio
async def test_route_failure_never_answers_or_starts_voice(tmp_path):
    session, control, audio, voice, records = fixture(tmp_path, audio=Audio(fail=True))
    result = await session.run()
    assert result["state"] == "failed" and not control.answers
    assert not voice.greeted and audio.closed


@pytest.mark.asyncio
async def test_unconfirmed_route_never_observes_or_opens_audio(tmp_path):
    session, control, audio, voice, _ = fixture(tmp_path, config=profile(route_confirmed=False))
    with pytest.raises(ServiceError, match="Prove"):
        await session.run()
    assert len(control.values) == 5 and not audio.opened and not voice.greeted


@pytest.mark.asyncio
async def test_changed_ring_is_not_answered(tmp_path):
    control = Control([observed(), observed(fingerprint="d" * 64)])
    session, _, audio, voice, _ = fixture(tmp_path, control=control)
    result = await session.run()
    assert result["code"] == "call_stale" and not control.answers
    assert audio.closed and voice.closed


@pytest.mark.asyncio
async def test_lost_answer_ack_is_not_retried_and_live_call_is_ended(tmp_path):
    control = Control([observed(), observed(), observed("active"), observed("ended")],
                      answer_error=ServiceError("call_control_unavailable", "private SDK secret"))
    session, _, audio, voice, records = fixture(tmp_path, control=control)
    result = await session.run()
    assert len(control.answers) == 1 and len(control.hangups) == 1
    assert result["state"] == "uncertain" and audio.closed and voice.closed
    assert "secret" not in json.dumps(result)
    with pytest.raises(ServiceError, match="already attempted"):
        CallRecords(records.database).claim(profile().channel, observed())


@pytest.mark.asyncio
async def test_provider_error_does_not_hang_up_a_different_caller(tmp_path):
    control = Control([observed(), observed(), observed("active"),
                       observed("active", caller_hash="d" * 64)])
    voice = Voice([ServiceError("call_tool_rejected", "no tools")])
    session, _, audio, _, _ = fixture(tmp_path, control=control, voice=voice)
    result = await session.run()
    assert not control.hangups and audio.closed and voice.closed
    assert result["state"] == "uncertain" and result["code"] == "call_handoff_required"


@pytest.mark.asyncio
async def test_owner_cancellation_stops_streams_ends_matching_call_and_saves(tmp_path):
    control = Control([observed(), observed(), observed("active")])
    session, _, audio, voice, records = fixture(tmp_path, control=control)
    task = asyncio.create_task(session.run())
    while not voice.greeted:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(control.hangups) == 1 and audio.closed and voice.closed
    assert not session.tasks and records.recent()[0]["state"] == "uncertain"


@pytest.mark.asyncio
async def test_deadline_ends_matching_call_and_releases_streams(tmp_path):
    control = Control([observed(), observed(), observed("active"), observed("active"), observed("ended")])
    session, _, audio, voice, _ = fixture(tmp_path, control=control)
    # Accelerate the production timeout without weakening accepted enrollment limits.
    session.profile = session.profile.model_copy(update={"max_seconds": 0.03})
    result = await session.run()
    assert result["state"] == "interrupted" and result["code"] == "call_time_limit"
    assert len(control.hangups) == 1 and audio.closed and voice.closed and not session.tasks


@pytest.mark.asyncio
async def test_ambiguous_call_never_opens_audio_or_answers(tmp_path):
    session, control, audio, voice, _ = fixture(tmp_path, control=Control([observed("ambiguous")]))
    with pytest.raises(ServiceError, match="ambiguous"):
        await session.run()
    assert not audio.opened and not control.answers and not voice.greeted


@pytest.mark.asyncio
async def test_disappearing_window_is_not_claimed_as_successful_hangup(tmp_path):
    control = Control([observed(), observed(), observed("active"), observed("absent"), observed("absent")])
    session, _, audio, voice, _ = fixture(tmp_path, control=control)
    result = await session.run()
    assert result["state"] == "uncertain" and result["code"] == "call_handoff_required"
    assert not control.hangups and audio.closed and voice.closed


@pytest.mark.asyncio
async def test_same_caller_in_a_replacement_view_is_never_hung_up(tmp_path):
    control = Control([observed(), observed(), observed("active"),
                       observed("active", view_id="d" * 64)])
    voice = Voice([ServiceError("call_stream_ended", "fixture")])
    session, _, audio, _, _ = fixture(tmp_path, control=control, voice=voice)
    result = await session.run()
    assert result["state"] == "uncertain" and not control.hangups and audio.closed


def test_partial_message_survives_restart_without_replaying_call(tmp_path):
    records = CallRecords(Database(tmp_path))
    key, value = records.claim("sim", observed())
    value["transcript"] = [{"role": "caller", "text": "A partial courier message"}]
    records.progress(key, value)
    restored = CallRecords(records.database).recent()[0]
    assert restored["state"] == "uncertain" and restored["transcript"] == value["transcript"]
    records.finish(key, value)
    with pytest.raises(ServiceError, match="no longer active"):
        records.progress(key, value)


def sound_module(devices=None):
    devices = devices or [
        {"name": "Dedicated call receive", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
        {"name": "Dedicated call transmit", "max_input_channels": 0, "max_output_channels": 1, "hostapi": 0},
    ]
    return SimpleNamespace(query_devices=lambda: devices, query_hostapis=lambda: [{"name": "Windows WASAPI"}])


def test_audio_never_selects_default_or_ambiguous_device():
    sd = sound_module()
    assert resolve_endpoints(sd, profile()) == (0, 1)
    duplicated = sd.query_devices() * 2
    with pytest.raises(ServiceError, match="exactly once"):
        resolve_endpoints(sound_module(duplicated), profile())
    missing = sd.query_devices()[:1]
    with pytest.raises(ServiceError, match="exactly once"):
        resolve_endpoints(sound_module(missing), profile())


@pytest.mark.asyncio
async def test_audio_pre_answer_discard_bounds_and_cleanup():
    audio = DedicatedAudio(profile())
    audio.closed = False
    audio.enqueue(b"\x00" * 640)
    assert audio.frames.empty()  # Ring/other pre-answer data never goes to the model.
    audio.activate()
    audio.enqueue(b"\x00" * 640)
    assert len(await audio.read()) == 640
    await audio.write(b"\x01\x00" * 48000)
    audio.playback_timeout = 0.01
    with pytest.raises(ServiceError, match="two seconds"):
        await audio.write(b"\x01\x00")
    await audio.clear()
    assert audio.queued == 0
    for _ in range(17):
        audio.enqueue(b"\x00" * 640)
    with pytest.raises(ServiceError, match="route stopped"):
        await audio.read()
    await audio.close()
    assert audio.closed and audio.frames.empty()


@pytest.mark.asyncio
async def test_playback_backpressure_resumes_without_dropping_speech():
    audio = DedicatedAudio(profile())
    audio.closed = False
    await audio.write(b"\x01\x00" * 48000)
    pending = asyncio.create_task(audio.write(b"\x02\x00" * 480))
    await asyncio.sleep(0)
    assert not pending.done() and audio.queued == 96000
    # Simulate the output device consuming its queued samples.
    await audio.clear()
    await pending
    assert audio.queued == 960 and audio.playback[0] == b"\x02\x00" * 480
    await audio.close()


@pytest.mark.asyncio
async def test_audio_partial_open_failure_closes_both_streams():
    sd = sound_module()
    opened = []
    class Stream:
        def __init__(self, **kwargs):
            opened.append(self)
            self.closed = self.aborted = False
        def start(self):
            if self is opened[0]:
                raise RuntimeError("fixture driver failed")
        def abort(self):
            self.aborted = True
        def close(self):
            self.closed = True
    sd.RawInputStream = sd.RawOutputStream = Stream
    sd.check_input_settings = sd.check_output_settings = lambda **kwargs: None
    audio = DedicatedAudio(profile(), sd)
    with pytest.raises(RuntimeError):
        await audio.open()
    assert len(opened) == 2 and all(stream.closed and stream.aborted for stream in opened)


def test_restart_uncertain_retention_and_clock_guard(tmp_path):
    now = [1000.0]
    records = CallRecords(Database(tmp_path), clock=lambda: now[0])
    records.claim("sim", observed())
    assert CallRecords(records.database, clock=lambda: now[0]).recent()[0]["state"] == "uncertain"
    now[0] = 500
    with pytest.raises(ServiceError, match="clock"):
        records.claim("sim", observed(fingerprint="d" * 64))
    now[0] = 1000 + 8 * 86400
    assert records.recent() == []
    now[0] = 1001
    with pytest.raises(ServiceError, match="clock"):
        records.claim("sim", observed())


@pytest.mark.asyncio
async def test_provider_session_has_no_tools_context_or_automatic_retry(monkeypatch):
    from google import genai
    from calls import voice as module
    seen = {}
    @asynccontextmanager
    async def connect(**kwargs):
        seen.update(kwargs)
        yield SimpleNamespace()
    close = AsyncMock()
    client = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=close))
    def factory(**kwargs):
        seen["client_options"] = kwargs
        return client
    monkeypatch.setattr(genai, "Client", factory)
    monkeypatch.setattr(module, "provider_key", lambda: "fixture-key")
    monkeypatch.setenv("INARA_CALL_MODEL", "explicit-fixture-voice-model")
    async with module.connect_voice() as voice:
        assert isinstance(voice, LiveVoice)
        assert seen["config"].tools is None
        assert seen["config"].max_output_tokens == 256
        assert seen["config"].system_instruction == CALL_INSTRUCTION
        assert seen["model"] == "explicit-fixture-voice-model"
        assert seen["client_options"]["http_options"]["retry_options"]["attempts"] == 1
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_voice_rejects_tools_and_has_no_dispatcher():
    async def receive():
        yield SimpleNamespace(tool_call=SimpleNamespace(function_calls=["read_file"]))
    voice = LiveVoice(SimpleNamespace(receive=receive))
    with pytest.raises(ServiceError, match="cannot invoke"):
        await anext(voice.events())
    assert not hasattr(voice, "dispatcher")
    assert "no tools" in CALL_INSTRUCTION and "AI assistant" in CALL_INSTRUCTION


@pytest.mark.asyncio
async def test_live_voice_empty_connection_fails_without_busy_loop():
    async def receive():
        if False:
            yield None
    with pytest.raises(ServiceError, match="connection stopped"):
        await anext(LiveVoice(SimpleNamespace(receive=receive)).events())


@pytest.mark.asyncio
async def test_interrupted_provider_packet_never_requeues_its_stale_audio():
    content = SimpleNamespace(interrupted=True, model_turn=SimpleNamespace(parts=[
        SimpleNamespace(inline_data=SimpleNamespace(data=b"old speech", mime_type="audio/pcm;rate=24000"))]))
    async def receive():
        yield SimpleNamespace(tool_call=None, server_content=content)
        await asyncio.Event().wait()
    events = LiveVoice(SimpleNamespace(receive=receive)).events()
    assert await anext(events) == {"kind": "interrupted"}
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(events), 0.01)
