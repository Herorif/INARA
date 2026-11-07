"""The talking overlay (J4a): the setting, the ``overlay`` socket role and its two events,
the caption/state snapshot, the output level and the native host's overlay process.

Fake PortAudio, fake Live session, fake tray and fake processes only: no microphone,
speaker, Electron, network or provider is ever used, and no port is bound.
"""

import asyncio
import json
import logging
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from google.genai import types
from pydantic import ValidationError

from services import audio_devices
from services.audio_contracts import overlay_settings
from services.audio_devices import LocalAudio, block_level
from services.tools import ServiceError
from services.voice_overlay import VoiceOverlay
from tests.test_local_voice import OWNER, Clock, pull, speech, stopped
from tests.test_local_voice import tray  # noqa: F401 - the tray voice fixture
from tests.test_voice_live import FakeProvider, until

OVERLAY = "overlay-sid"
TOKEN = "test-session-token"


def sent(app, event="voice_overlay", room=OVERLAY):
    return [
        call.args[1]
        for call in app.sio.emit.await_args_list
        if call.args[0] == event and call.kwargs.get("room") == room
    ]


def events_to(app, room):
    return [call.args[0] for call in app.sio.emit.await_args_list if call.kwargs.get("room") == room]


@pytest.fixture
def overlay(tray):  # noqa: F811 - fixture
    app = tray.app
    app.sessions.principals[OVERLAY] = OWNER
    app.sessions.roles[OVERLAY] = "overlay"
    host_events = []
    app.voice_overlay.observer = lambda event, data: host_events.append((event, data))
    return SimpleNamespace(**vars(tray), model=app.voice_overlay, host_events=host_events)


async def begin(ctx):
    count = len(ctx.connector.connections)
    result = await ctx.app.voice.start_local()
    assert result["ok"], result
    await until(lambda: len(ctx.connector.connections) > count)
    live = ctx.connector.connections[-1]
    session = ctx.app.voice.sessions[OWNER]
    await until(lambda: session.live is live and ctx.model.state == "listening")
    return live, session


async def shown(ctx, **expected):
    """Wait until the last snapshot sent to the overlay has these values."""

    def matches():
        items = sent(ctx.app)
        return items and all(items[-1][key] == value for key, value in expected.items())

    await until(matches)
    return sent(ctx.app)[-1]


# --- the live design flag --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_flag_is_published_when_a_live_design_starts_and_ends(overlay):
    app = overlay.app
    assert app.live_design.observer == app.voice_overlay.design_changed
    app.settings["tool_permissions"]["live_design"] = False
    live, session = await begin(overlay)
    await shown(overlay, state="listening", design=False)
    context = {"principal": OWNER, "project_path": app.projects.get_current_project_path().resolve()}
    part = {"name": "shell", "shape": "enclosure", "width": 160.0, "depth": 200.0,
            "height": 180.0, "thickness": 3.0, "material": "titanium"}
    await app.dispatcher.dispatch(
        OWNER, "start_live_design", {"name": "NAS case", "objects": [part]}, context, None
    )
    assert (await shown(overlay, design=True))["state"] == "listening"
    assert sent(app, "local_voice", "client")[-1]["design"] is True
    design_id = app.live_design.snapshot(OWNER)["design"]["id"]
    count = len(sent(app))
    ended = await app.sio.handlers["/"]["cad_design_end"]("client", {"design_id": design_id})
    assert ended == {"ok": True, "design": None}
    await shown(overlay, design=False)
    assert len(sent(app)) > count
    await app.voice.stop_local()


def test_design_flag_follows_only_the_local_owner_and_publishes_only_while_running(overlay):
    model = overlay.model
    model.publish = lambda urgent=False: published.append(urgent)
    published = []
    model.design_changed("someone-else", True)
    assert model.snapshot()["design"] is False
    model.design_changed(OWNER, True)  # no session runs: nothing is sent
    assert model.snapshot()["design"] is True and published == []
    model.design_changed(OWNER, False)
    assert model.snapshot()["design"] is False and published == []


# --- the setting ----------------------------------------------------------------------------


def test_overlay_setting_defaults_on_and_validates(tmp_path):
    from services.settings import SettingsPatch, SettingsService, SettingsStore

    assert overlay_settings({}) == {"overlay": True}
    assert overlay_settings({"voice": {"overlay": False}}) == {"overlay": False}
    for stale in ({"voice": {"overlay": "false"}}, {"voice": {"overlay": 0}}, {"voice": []}, None):
        assert overlay_settings(stale) == {"overlay": True}
    for bad in ({"overlay": None}, {"overlay": "true"}, {"overlay": 1}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"voice": bad})
    settings = {"tool_permissions": {}}
    service = SettingsService(settings, SettingsStore(tmp_path / "settings.json"), set())
    service.apply(SettingsPatch.model_validate({"voice": {"mode": "conversation"}}))
    assert settings["voice"]["overlay"] is True  # filled in from the defaults
    service.apply(SettingsPatch.model_validate({"voice": {"overlay": False}}))
    assert json.loads((tmp_path / "settings.json").read_text())["voice"]["overlay"] is False


@pytest.mark.asyncio
async def test_turning_the_setting_off_closes_and_on_waits_for_the_next_session(overlay):
    app = overlay.app
    app.settings["voice"] = {"overlay": False}
    await app.settings_changed({"voice": {"overlay": False}})
    assert overlay.host_events == [("disabled", None)]
    live, session = await begin(overlay)
    assert overlay.host_events == [("disabled", None)]  # off: no process for this session
    app.settings["voice"] = {"overlay": True}
    await app.settings_changed({"voice": {"overlay": True}})
    assert overlay.host_events == [("disabled", None)]  # on mid-session: nothing until next
    await app.voice.stop_local()
    await begin(overlay)
    assert overlay.host_events[-1] == ("started", None)
    await app.voice.stop_local()


# --- the snapshot ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchanges_captions_and_finals(overlay):
    app = overlay.app
    live, session = await begin(overlay)
    first = await shown(overlay, state="listening")
    assert first == {
        "session": session.id, "state": "listening", "user": "", "user_final": False,
        "jarvis": "", "jarvis_final": False, "approval": False, "design": False, "end": None,
    }
    assert overlay.host_events == [("started", None)]
    live.push(input_transcription=types.Transcription(text="What's"))
    live.push(input_transcription=types.Transcription(text=" on today?"))
    await shown(overlay, user="What's on today?", user_final=False)
    live.push(output_transcription=types.Transcription(text="Two meetings"))
    await shown(overlay, jarvis="Two meetings", jarvis_final=False, user="What's on today?")
    live.push(turn_complete=True)
    await shown(overlay, user_final=True, jarvis_final=True, jarvis="Two meetings")
    # Owner words after the completed turn start a new exchange.
    live.push(input_transcription=types.Transcription(text="And tomorrow?"))
    snap = await shown(overlay, user="And tomorrow?")
    assert snap["jarvis"] == "" and not snap["user_final"] and not snap["jarvis_final"]
    # Long captions keep only their end; the conversation records the whole text.
    live.push(input_transcription=types.Transcription(text=" " + "u" * 400))
    live.push(output_transcription=types.Transcription(text="j" * 700))
    snap = await shown(overlay, jarvis="j" * 600)
    assert snap["user"] == "u" * 300
    live.push(turn_complete=True)
    project = app.projects.get_current_project_path().resolve()
    await until(lambda: len(app.conversation.restore(OWNER, session.conversation_id, project)) == 4)
    recorded = app.conversation.restore(OWNER, session.conversation_id, project)
    assert recorded[2]["content"] == "And tomorrow? " + "u" * 400
    assert recorded[3]["content"] == "j" * 700
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_live_barge_in_marks_jarvis_final_and_keeps_its_text(overlay):
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Tell me a story"))
    live.push(output_transcription=types.Transcription(text="Once upon"))
    await shown(overlay, jarvis="Once upon")
    live.push(interrupted=True)
    snap = await shown(overlay, jarvis_final=True)
    assert snap["jarvis"] == "Once upon" and snap["user"] == "Tell me a story"
    await overlay.app.voice.stop_local()


@pytest.mark.asyncio
async def test_hey_jarvis_barge_in_freezes_the_dropped_answer(overlay):
    app = overlay.app
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Read the news"))
    live.push(model_turn=speech(), output_transcription=types.Transcription(text="First,"))
    await shown(overlay, jarvis="First,", state="speaking")
    await app.voice.barge_in(session)
    snap = await shown(overlay, jarvis_final=True, state="listening")
    assert snap["jarvis"] == "First,"
    # The dropped rest of the answer still streams its transcription: never shown.
    live.push(output_transcription=types.Transcription(text=" the weather"))
    live.push(turn_complete=True)
    await until(lambda: overlay.model.turn_done)
    await asyncio.sleep(0.08)
    assert sent(app)[-1]["jarvis"] == "First," and sent(app)[-1]["user_final"]
    # The next exchange shows normally again.
    live.push(input_transcription=types.Transcription(text="Thanks"))
    live.push(output_transcription=types.Transcription(text="Any time."))
    await shown(overlay, user="Thanks", jarvis="Any time.")
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_approval_unavailable_offers_open_and_resets_with_the_next_exchange(overlay):
    from llm.base import LLMResponse, ToolCall

    app = overlay.app
    app.settings["tool_permissions"]["write_file"] = True  # asks the owner first
    provider = FakeProvider(
        [
            LLMResponse(text="", tool_calls=[ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})]),
            LLMResponse(text="I need your approval on screen for that."),
        ]
    )
    app.conversation.provider_factory = lambda: provider
    app.sessions.principals.pop("client")  # no workspace open
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Write a"))
    live.message(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="fc", name="ask_brain", args={"request": "write a"})]
        )
    )
    await until(lambda: live.tool_responses)
    snap = await shown(overlay, approval=True)
    assert snap["user"] == "Write a"
    # Approvals never reach the overlay (only renderers get tool_confirmation_request).
    assert "tool_confirmation_request" not in events_to(app, OVERLAY)
    live.push(output_transcription=types.Transcription(text="I need your approval."))
    live.push(turn_complete=True)
    await shown(overlay, jarvis="I need your approval.", approval=True, jarvis_final=True)
    live.push(input_transcription=types.Transcription(text="Never mind"))
    await shown(overlay, user="Never mind", approval=False)
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_quiet_end_keeps_the_last_exchange(overlay):
    app = overlay.app
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Bye"))
    live.push(output_transcription=types.Transcription(text="Goodbye."))
    await shown(overlay, jarvis="Goodbye.")
    await app.voice.stop_local()
    snap = await shown(overlay, state="ended")
    assert snap["end"] == {"kind": "quiet", "message": None}
    assert snap["user"] == "Bye" and snap["jarvis"] == "Goodbye."
    assert snap["user_final"] and snap["jarvis_final"]
    assert overlay.host_events[-1] == ("ended", {"now": False})


@pytest.mark.asyncio
async def test_error_end_shows_the_message(overlay):
    live, session = await begin(overlay)
    microphone = overlay.backend.stream("input")
    await asyncio.to_thread(microphone.finished_callback)  # unplugged
    snap = await shown(overlay, state="ended")
    assert snap["end"] == {
        "kind": "error", "message": "The microphone was disconnected. Voice is off.",
    }
    assert overlay.host_events[-1] == ("ended", {"now": False})


@pytest.mark.parametrize("reason", ["gaming_mode", "authentication_required", "permission_denied"])
@pytest.mark.asyncio
async def test_now_ends_clear_everything_and_close_at_once(overlay, reason):
    app = overlay.app
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="My bank PIN is"))
    live.push(output_transcription=types.Transcription(text="Noted"))
    await shown(overlay, jarvis="Noted")
    if reason == "gaming_mode":
        app.resources.select("gaming")
        await app.restrict_resources()
    elif reason == "authentication_required":
        app.settings["face_auth_enabled"] = True  # face lock: the watchdog ends it
    else:
        app.settings["tool_permissions"]["start_audio"] = "deny"
    snap = await shown(overlay, state="ended")
    assert snap["end"] == {"kind": "now", "message": None}
    assert snap["user"] == "" and snap["jarvis"] == ""
    assert overlay.host_events[-1] == ("ended", {"now": True})
    assert overlay.model.snapshot() == snap


@pytest.mark.asyncio
async def test_a_refused_start_never_shows_or_spawns_an_overlay(overlay):
    app = overlay.app
    app.resources.select("gaming")
    result = await app.voice.start_local()
    assert result["code"] == "gaming_mode"
    app.resources.select("resident")
    app.settings["face_auth_enabled"] = True
    assert (await app.voice.start_local())["code"] == "authentication_required"
    assert overlay.model.session is None and not overlay.host_events
    assert not sent(app)


@pytest.mark.asyncio
async def test_nothing_is_sent_without_an_overlay_and_connect_sends_the_snapshot(overlay):
    app = overlay.app
    del app.sessions.principals[OVERLAY], app.sessions.roles[OVERLAY]
    del app.sessions.principals["client"], app.sessions.roles["client"]  # no workspace either
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Hello"))
    await until(lambda: overlay.model.user == "Hello")
    assert not [
        c for c in app.sio.emit.await_args_list
        if c.args[0] in ("voice_overlay", "voice_level", "local_voice", "local_voice_level")
    ]
    assert session.audio.measure_level is False
    app.sessions.principals[OVERLAY] = OWNER
    app.sessions.roles[OVERLAY] = "overlay"
    await app.voice_overlay.attached(OVERLAY)
    assert sent(app) == [overlay.model.snapshot()] and sent(app)[0]["user"] == "Hello"
    assert session.audio.measure_level is True
    app.voice_overlay.detached(OVERLAY)
    assert session.audio.measure_level is False
    await app.voice.stop_local()


def test_caption_text_is_never_logged(overlay, caplog):
    model = overlay.model
    session = SimpleNamespace(id="s", closed=False, audio=None)
    caplog.set_level(logging.DEBUG)
    model.started(session)
    model.delivered(session, "voice_caption", {"role": "user", "text": "secret words", "final": False})
    model.delivered(session, "voice_caption", {"role": "jarvis", "text": "secret reply", "final": True})
    assert model.user == "secret words" and model.jarvis == "secret reply"
    assert "secret" not in caplog.text


# --- coalescing -----------------------------------------------------------------------------


def fake_overlay(rooms=("one",), renderers=()):
    rooms, renderers = list(rooms), list(renderers)
    emit = AsyncMock()
    by_role = {"overlay": rooms, "renderer": renderers}
    app = SimpleNamespace(
        settings={},
        sio=SimpleNamespace(emit=emit),
        voice=SimpleNamespace(
            local_owner=lambda: "owner",
            local_status=lambda session: {"state": session.view},
        ),
        sessions=SimpleNamespace(
            is_owner=lambda owner: owner == "owner",
            authenticated=lambda owner: owner == "owner",
            rooms=lambda owner, role: tuple(by_role.get(role, ())),
        ),
    )
    return VoiceOverlay(app), emit, rooms


def snapshots(emit):
    return [call.args[1] for call in emit.await_args_list if call.args[0] == "voice_overlay"]


@pytest.mark.asyncio
async def test_snapshots_coalesce_to_20_per_second_latest_wins_end_at_once():
    model, emit, _ = fake_overlay()
    clock = Clock()
    model.clock = clock  # the 50 ms window moves only when this clock does
    session = SimpleNamespace(id="s", closed=False, audio=None, view="listening")
    model.started(session)
    for index in range(100):  # a burst on the core loop
        model.caption("user", f"word {index}", False)
    await until(lambda: snapshots(emit))
    await asyncio.sleep(0.01)
    assert [item["user"] for item in snapshots(emit)] == ["word 99"]
    model.caption("jarvis", "a", False)
    model.caption("jarvis", "ab", False)
    clock.now += 0.049
    await asyncio.sleep(0.1)
    assert len(snapshots(emit)) == 1  # inside the 50 ms window
    clock.now += 0.001
    await until(lambda: len(snapshots(emit)) == 2)
    assert snapshots(emit)[-1]["jarvis"] == "ab"
    # The end snapshot is never held back by the window.
    model.caption("jarvis", "last words", False)
    await asyncio.sleep(0.01)
    assert len(snapshots(emit)) == 2
    session.closed = True
    model.ended(session, "ended", "stopped", "Voice is off.")
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(snapshots(emit)) == 3  # the pending change rides with the end, now
    assert snapshots(emit)[-1]["end"] == {"kind": "quiet", "message": None}
    assert snapshots(emit)[-1]["jarvis"] == "last words"
    await model.close()


@pytest.mark.asyncio
async def test_a_steady_stream_of_changes_sends_at_most_20_per_second():
    model, emit, _ = fake_overlay()
    session = SimpleNamespace(id="s", closed=False, audio=None, view="listening")
    model.started(session)
    # A steady stream of changes for 0.5 s: at most 20 per second.
    start = asyncio.get_running_loop().time()
    count = len(snapshots(emit))
    while asyncio.get_running_loop().time() - start < 0.5:
        model.caption("jarvis", f"x{asyncio.get_running_loop().time()}", False)
        await asyncio.sleep(0.004)
    assert len(snapshots(emit)) - count <= 11
    await until(lambda: not model.dirty)
    assert snapshots(emit)[-1] == model.snapshot()  # the latest state wins
    await model.close()


@pytest.mark.asyncio
async def test_no_overlay_connected_sends_nothing():
    model, emit, rooms = fake_overlay(rooms=())
    session = SimpleNamespace(id="s", closed=False, audio=None, view="listening")
    model.started(session)
    model.caption("user", "hello", False)
    session.closed = True
    model.ended(session, "error", "voice_failed", "Voice stopped unexpectedly.")
    await asyncio.sleep(0.06)
    emit.assert_not_called()
    assert model.end == {"kind": "error", "message": "Voice stopped unexpectedly."}


def test_end_kinds():
    from services.voice_overlay import end_kind

    for code in ("stopped", "conversation_ended", "silence_timeout"):
        assert end_kind("ended", code) == "quiet"
    for code in ("gaming_mode", "authentication_required", "permission_denied"):
        assert end_kind("ended", code) == end_kind("error", code) == "now"
    for code in ("audio_device_lost", "voice_scope", "offline", "resource_policy", "voice_failed"):
        assert end_kind("ended", code) == end_kind("error", code) == "error"


# --- the output level -----------------------------------------------------------------------


def test_level_formula_and_stride():
    loud = struct.pack("<h", 8192)
    assert block_level(loud * 8, 16) == pytest.approx(1.0)  # 4 * 8192 / 32768
    assert block_level(struct.pack("<h", 1000) * 8, 16) == pytest.approx(4000 / 32768)
    assert block_level(struct.pack("<h", -32768) * 4, 8) == 1.0  # clamped
    # Every 4th sample: the three in between are never read.
    pattern = struct.pack("<4h", 1000, 30000, -30000, 30000) * 10
    assert block_level(pattern, len(pattern)) == pytest.approx(4000 / 32768)
    # Only the filled part counts, in whole samples.
    block = bytearray(struct.pack("<h", 2000) * 4 + bytes(8))
    assert block_level(block, 8) == pytest.approx(8000 / 32768)
    assert block_level(block, 9) == pytest.approx(8000 / 32768)
    assert block_level(block, 1) == block_level(block, 0) == 0.0
    assert block_level(bytes(64), 64) == 0.0


def local_audio(clock):
    audio = LocalAudio(None, on_frame=lambda pcm: None, on_lost=lambda kind: None, clock=clock)
    audio.block_bytes = 16
    return audio


def play(audio, size=16):
    out = bytearray(size)
    audio._play_callback(out, size // 2, None, 0)
    return bytes(out)


def test_output_level_is_measured_only_when_asked_and_zero_when_quiet():
    clock = Clock()
    audio = local_audio(clock)
    audio.outbox.append(struct.pack("<h", 8192) * 8)
    play(audio)
    assert audio.level == 0.0 and audio.output_level() == 0.0  # not measuring
    audio.measure_level = True
    audio.outbox.append(struct.pack("<h", 4096) * 8)
    play(audio)
    assert audio.speaking() and audio.output_level() == pytest.approx(0.5)
    assert play(audio) == bytes(16)  # drained: silence keeps the last audible level
    assert audio.output_level() == pytest.approx(0.5)  # still inside the tail
    clock.now += 1.0
    assert not audio.speaking() and audio.output_level() == 0.0


def test_the_speaker_callback_never_raises(monkeypatch):
    clock = Clock()
    audio = local_audio(clock)
    audio.measure_level = True

    def broken(data, size, stride=4):
        raise ValueError("bad buffer")

    monkeypatch.setattr(audio_devices, "block_level", broken)
    audio.outbox.append(struct.pack("<h", 4096) * 8)
    assert play(audio) == bytes(16)  # failed: silence, never an exception
    monkeypatch.undo()
    audio.outbox.append(struct.pack("<h", 4096) * 4 + b"\x01")  # an odd tail byte
    play(audio, 10)
    assert audio.output_level() == pytest.approx(0.5)
    audio._play_callback(memoryview(bytearray(16)).toreadonly(), 8, None, 0)  # unwritable


@pytest.mark.asyncio
async def test_levels_follow_speech_then_one_final_zero(overlay):
    app = overlay.app
    app.voice_overlay.interval = 0.01
    live, session = await begin(overlay)
    assert session.audio.measure_level is True
    speaker = overlay.backend.stream("output")
    live.push(model_turn=speech(struct.pack("<h", 8000) * 4800))
    await until(lambda: overlay.model.state == "speaking")
    for _ in range(10):
        pull(speaker)
    await until(lambda: any(item["level"] > 0.5 for item in sent(app, "voice_level")))
    assert all(0.0 <= item["level"] <= 1.0 for item in sent(app, "voice_level"))
    overlay.clock.now += 1.0  # drained and past the tail
    live.push(turn_complete=True)
    await until(lambda: sent(app, "voice_level")[-1] == {"level": 0.0} and overlay.model.state == "listening")
    await asyncio.sleep(0.05)
    count = len(sent(app, "voice_level"))
    await asyncio.sleep(0.05)
    assert len(sent(app, "voice_level")) == count  # nothing while not speaking
    await app.voice.stop_local()


# --- the overlay socket role ----------------------------------------------------------------


@pytest.fixture
def sockets(application_factory, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_TOKEN", TOKEN)
    app = application_factory()
    return app


def auth(principal, role=None):
    return {"token": TOKEN, "client_id": principal, **({"role": role} if role else {})}


def test_overlay_is_its_own_role_and_never_registers_an_owner(sockets):
    app = sockets
    owner = str(uuid.uuid4())
    assert not app.sessions.accept("o1", auth(owner, "overlay"), TOKEN)
    assert app.sessions.local_owner is None and "o1" not in app.sessions.principals
    assert app.sessions.accept("r1", auth(owner), TOKEN)
    assert app.sessions.accept("o2", auth(owner, "overlay"), TOKEN)
    assert app.sessions.roles["o2"] == "overlay"
    assert not app.sessions.accept("o3", auth(str(uuid.uuid4()), "overlay"), TOKEN)
    assert app.sessions.accept("x", auth(owner, "something"), TOKEN)
    assert app.sessions.roles["x"] == "renderer"  # unknown roles stay renderers
    with pytest.raises(ServiceError):
        app.sessions.context("o2")
    with pytest.raises(ServiceError):
        app.sessions.context("o2", renderer=True)
    native = SimpleNamespace(state=SimpleNamespace(identity=SimpleNamespace(owner=None)))
    app.sessions.native_desktop = native  # a resident with no owner registered yet
    assert not app.sessions.accept("o4", auth(owner, "overlay"), TOKEN)


@pytest.mark.asyncio
async def test_overlay_connect_gets_only_its_snapshot(sockets):
    app = sockets
    owner = str(uuid.uuid4())
    await app.connection.connect("renderer", {}, auth(owner))
    app.sio.emit.reset_mock()
    assert await app.connection.connect(OVERLAY, {}, auth(owner, "overlay")) is not False
    assert [(c.args[0], c.kwargs["room"]) for c in app.sio.emit.await_args_list] == [
        ("voice_overlay", OVERLAY)
    ]
    assert app.sio.emit.await_args.args[1]["session"] is None
    assert await app.connection.connect("stranger", {}, auth(str(uuid.uuid4()), "overlay")) is False
    assert "stranger" not in app.sessions.principals
    assert OVERLAY not in app.connection.renderers()
    await app.close()


@pytest.mark.asyncio
async def test_renderer_broadcasts_never_reach_the_overlay(sockets, monkeypatch):
    app = sockets
    owner = str(uuid.uuid4())
    await app.connection.connect("renderer", {}, auth(owner))
    await app.connection.connect(OVERLAY, {}, auth(owner, "overlay"))
    app.sio.emit.reset_mock()
    await app.sio.handlers["/"]["update_settings"]("renderer", {"camera_flipped": True})
    await app.sio.handlers["/"]["set_resource_state"]("renderer", {"state": "studio"})
    await app.connection.hydrate(OVERLAY)
    monkeypatch.setattr(
        app.delivery, "reminders",
        SimpleNamespace(claim_deliveries=lambda _: [{"delivery_id": "one"}]),
    )
    monkeypatch.setattr(app.dispatcher, "authenticated", lambda _: True)
    for _ in range(5):  # reminder delivery picks one non-workspace room
        await app.delivery.deliver_reminders_once()
    await app.delivery.publish_job("cad_job", owner, {"id": "job"})
    assert {"settings", "resource_state", "reminder_triggered", "cad_job"} <= set(events_to(app, "renderer"))
    assert events_to(app, OVERLAY) == []
    await app.close()


RENDERER_ONLY = {
    "get_settings": None,
    "update_settings": {"camera_flipped": True},
    "user_input": {"text": "hi", "conversation_id": str(uuid.UUID(int=1)), "request_id": str(uuid.UUID(int=2))},
    "resume_conversation": {"conversation_id": str(uuid.UUID(int=1))},
    "voice_start": {"mode": "conversation", "conversation_id": str(uuid.UUID(int=1))},
    "wake_word_status": {},
    "audio_devices": {},
    "get_reminders": None,
    "memory_list": {},
}
WORKSPACE_ONLY = {"desktop_control": {"action": "state"}}
RESIDENT_OR_RENDERER = {"set_resource_state": {"state": "studio"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,data", [*RENDERER_ONLY.items(), *WORKSPACE_ONLY.items(), *RESIDENT_OR_RENDERER.items()])
async def test_renderer_and_workspace_handlers_reject_the_overlay(sockets, name, data):
    app = sockets
    owner = str(uuid.uuid4())
    await app.connection.connect("renderer", {}, auth(owner))
    await app.connection.connect(OVERLAY, {}, auth(owner, "overlay"))
    app.sessions.native_desktop = SimpleNamespace(
        state=SimpleNamespace(identity=SimpleNamespace(owner=owner, gaming=False)),
        control=AsyncMock(return_value={}),
    )
    app.conversation.reply = AsyncMock()
    before = app.resources.state
    app.sio.emit.reset_mock()
    result = await app.sio.handlers["/"][name](OVERLAY, data)
    assert not (isinstance(result, dict) and result.get("ok"))
    if isinstance(result, dict) and "code" in result:
        assert result["code"] in ("authentication_required", "permission_denied")
    # Only the handler's own refusal (and user_input's idle status) answers the overlay.
    assert not set(events_to(app, OVERLAY)) - {"error", "conversation_restore_failed", "text_status"}
    for call in app.sio.emit.await_args_list:
        if call.kwargs.get("room") == OVERLAY and call.args[0] == "error":
            assert call.args[1]["code"] in ("authentication_required", "permission_denied")
    app.sessions.native_desktop.control.assert_not_called()
    app.conversation.reply.assert_not_called()
    assert app.resources.state == before and not app.voice.sessions
    await app.close()


@pytest.mark.asyncio
async def test_no_other_socket_event_accepts_an_overlay_sid(sockets):
    """Every registered handler, called by the owner's overlay: never an ``ok`` result and
    nothing private back; only overlay_stop / overlay_open answer it."""
    app = sockets
    owner = str(uuid.uuid4())
    await app.connection.connect("renderer", {}, auth(owner))
    await app.connection.connect(OVERLAY, {}, auth(owner, "overlay"))
    codes = set()
    for name, handler in app.sio.handlers["/"].items():
        if name in ("connect", "disconnect", "overlay_stop", "overlay_open"):
            continue
        app.sio.emit.reset_mock()
        for data in ({}, None):
            try:
                result = await asyncio.wait_for(handler(OVERLAY, data), 5)
            except (ServiceError, ValidationError, TypeError, AttributeError):
                continue
            assert not (isinstance(result, dict) and result.get("ok")), name
            if isinstance(result, dict) and "code" in result:
                codes.add(result["code"])
        for call in app.sio.emit.await_args_list:
            if call.kwargs.get("room") != OVERLAY:
                continue
            event, payload = call.args[0], call.args[1]
            # Only refusals answer it (an error code, the legacy CAD error status), plus
            # user_input's "idle" status from its finally block; never data.
            refusal = isinstance(payload, dict) and (
                "code" in payload
                or event == "conversation_restore_failed"
                or (event == "cad_status" and payload.get("status") == "error")
                or (event == "text_status" and payload.get("state") == "idle")
            )
            assert refusal, (name, event)
            if "code" in payload:
                codes.add(payload["code"])
    assert codes <= {
        "authentication_required", "permission_denied", "invalid_arguments", "invalid_request",
    }, codes
    await app.close()


# --- overlay_stop / overlay_open ------------------------------------------------------------


@pytest.mark.asyncio
async def test_overlay_stop_is_the_trays_stop_talking(overlay):
    app = overlay.app
    handler = app.sio.handlers["/"]["overlay_stop"]
    live, session = await begin(overlay)
    for sid in ("client", "native-resident", "stranger"):  # renderer, resident, unknown
        assert (await handler(sid, None))["code"] == "authentication_required"
    app.sessions.principals["foreign-overlay"] = str(uuid.uuid4())
    app.sessions.roles["foreign-overlay"] = "overlay"
    assert (await handler("foreign-overlay", None))["code"] == "permission_denied"
    for bad in ({"session_id": session.id}, [], "stop", 1):
        assert (await handler(OVERLAY, bad))["code"] == "invalid_arguments"
    assert app.voice.sessions
    app.settings["face_auth_enabled"] = True  # a safety stop: allowed while locked
    assert await handler(OVERLAY, {}) == {"ok": True}
    status = await stopped(overlay)
    assert status["notice"] is None
    assert await handler(OVERLAY, None) == {"ok": True}  # nothing running: still fine


@pytest.mark.asyncio
async def test_overlay_open_is_the_trays_open_jarvis(overlay):
    app = overlay.app
    handler = app.sio.handlers["/"]["overlay_open"]
    result = await handler(OVERLAY, None)
    assert result["ok"] is False and result["code"] == "workspace_unavailable"
    posted, opened = [], []
    app.sessions.native_desktop = SimpleNamespace(
        state=SimpleNamespace(identity=SimpleNamespace(owner=OWNER)),
        tray=SimpleNamespace(post=posted.append),
        open_workspace=lambda quick=False: opened.append(quick),
    )
    assert (await handler("client", {}))["code"] == "authentication_required"
    assert (await handler(OVERLAY, {"quick": True}))["code"] == "invalid_arguments"
    assert not posted
    assert await handler(OVERLAY, {}) == {"ok": True}
    assert opened == [] and len(posted) == 1  # runs on the tray thread, not here
    posted[0]()
    assert opened == [False]


# --- the native host's overlay process ------------------------------------------------------


class HostTray:
    window = None
    secondary = False
    hotkey = False

    def __init__(self, *args, **kwargs):
        self.posted = 0

    def post(self, callback):
        self.posted += 1
        callback()

    def close(self):
        pass


class Process:
    def __init__(self, executable, entrypoint, bootstrap, cwd):
        self.executable, self.entrypoint, self.bootstrap, self.cwd = (
            executable, entrypoint, bootstrap, cwd,
        )
        self.running, self.closed = True, 0

    def alive(self):
        return self.running

    def close(self):
        self.closed += 1
        self.running = False


@pytest.fixture
def native(tmp_path):
    from resident.host import NativeHost

    root = tmp_path.resolve() / "root"
    (root / "dist").mkdir(parents=True)
    (root / "dist/overlay.html").write_text("<!doctype html>")
    electron = root / "node_modules/electron/dist/electron.exe"
    electron.parent.mkdir(parents=True)
    electron.write_bytes(b"")
    processes = []

    def factory(*args):
        processes.append(Process(*args))
        return processes[-1]

    host = NativeHost(root, tmp_path / "profile", tray_factory=HostTray, process_factory=factory,
                      resident_only=True)
    host.state.identity.register(OWNER)
    host.state.phase = "ready"
    return SimpleNamespace(host=host, root=root, electron=electron, processes=processes,
                           profile=tmp_path / "profile")


def test_host_spawns_the_overlay_with_its_own_profile(native, monkeypatch):
    monkeypatch.delenv("JARVIS_DEV_SERVER", raising=False)
    monkeypatch.delenv("INARA_DEV_SERVER", raising=False)
    host = native.host
    host.overlay_changed("started")
    (process,) = native.processes
    assert process.executable == native.electron
    assert process.entrypoint == native.root / "electron/overlay-main.cjs"
    assert process.cwd == native.root
    overlay_profile = (native.profile / "overlay").resolve()
    assert process.bootstrap == {
        "token": host.token,
        "clientId": OWNER,
        "profile": str(overlay_profile),
        "core": "http://127.0.0.1:8000",
        "dev": False,
    }
    assert overlay_profile.is_dir() and overlay_profile != native.profile.resolve()
    # A new session while it is still alive (fading out) reuses it.
    host.overlay_changed("ended", {"now": False})
    host.overlay_changed("started")
    assert len(native.processes) == 1 and host.overlay_ended is None


def test_host_dev_flag_follows_the_workspace_rule(native, monkeypatch):
    monkeypatch.setenv("JARVIS_DEV_SERVER", "1")
    native.host.overlay_changed("started")
    assert native.processes[-1].bootstrap["dev"] is True


@pytest.mark.parametrize("missing", ["page", "electron", "quitting"])
def test_host_spawn_conditions(native, missing):
    host = native.host
    if missing == "page":
        (native.root / "dist/overlay.html").unlink()
    elif missing == "electron":
        native.electron.unlink()
    else:
        host.state.quitting = True
    host.overlay_changed("started")
    assert not native.processes and host.overlay is None


def test_host_spawn_failure_logs_one_line_without_the_token(native, caplog):
    host = native.host

    def failing(*args):
        raise OSError("CreateProcessW failed")

    host.process_factory = failing
    caplog.set_level(logging.DEBUG)
    host.overlay_changed("started")
    assert host.overlay is None
    records = [r for r in caplog.records if "overlay" in r.getMessage()]
    assert len(records) == 1 and host.token not in caplog.text


def test_host_closes_a_lingering_overlay_30_s_after_the_session(native):
    host = native.host
    host.overlay_changed("started")
    process = native.processes[-1]
    host.overlay_changed("ended", {"now": False})
    ended = host.overlay_ended
    host.check_overlay(now=ended + 29.9)
    assert process.running and host.overlay is process
    host.check_overlay(now=ended + 30.0)
    assert process.closed == 1 and host.overlay is None
    # One that quit after its fade-out is simply forgotten.
    host.overlay_changed("started")
    native.processes[-1].running = False
    host.tick()
    assert host.overlay is None and len(native.processes) == 2
    host.overlay_changed("started")
    assert len(native.processes) == 3  # a dead one is never reused


@pytest.mark.parametrize("event,data", [("ended", {"now": True}), ("disabled", None)])
def test_host_closes_the_overlay_at_once(native, event, data):
    host = native.host
    host.overlay_changed("started")
    process = native.processes[-1]
    host.overlay_changed(event, data)
    assert process.closed == 1 and host.overlay is None and host.overlay_ended is None


def test_quitting_closes_the_overlay(native):
    host = native.host
    host.overlay_changed("started")
    process = native.processes[-1]
    host.action("quit")
    assert process.closed == 1 and host.overlay is None
    host.overlay_changed("started")
    assert len(native.processes) == 1


@pytest.mark.asyncio
async def test_workspace_checks_never_count_or_touch_overlay_sockets(native):
    import time

    host = native.host
    disconnect = AsyncMock()
    emit = AsyncMock()
    host.runtime = SimpleNamespace(
        client_roles={"native-resident": "resident", "r": "renderer", "w": "workspace",
                      OVERLAY: "overlay"},
        client_principals={"native-resident": OWNER, "r": OWNER, "w": OWNER, OVERLAY: OWNER},
        sio=SimpleNamespace(disconnect=disconnect, emit=emit),
        set_resource_state=AsyncMock(),
    )
    host.loop = asyncio.get_running_loop()
    host.overlay_changed("started")
    overlay = host.overlay
    host.workspace = Process("electron", "native-main.cjs", {}, native.root)
    host.release_workspace()
    await until(lambda: disconnect.await_count == 2)
    assert {call.args[0] for call in disconnect.await_args_list} == {"r", "w"}
    assert host.overlay is overlay and overlay.running
    await until(lambda: emit.await_count == 2)
    assert {call.kwargs["room"] for call in emit.await_args_list} == {"r", "w"}  # resident_state
    # An overlay socket is never a workspace: a workspace that never connected times out.
    del host.runtime.client_roles["w"], host.runtime.client_roles["r"]
    host.workspace = Process("electron", "native-main.cjs", {}, native.root)
    host.state.visible = True
    host.workspace_started = time.monotonic() - 21
    host.tick()
    assert host.workspace is None and host.state.error.startswith("Workspace startup timed out")
    assert host.overlay is overlay and overlay.running
    host.close_overlay()


@pytest.mark.asyncio
async def test_tray_voice_drives_the_overlay_process_end_to_end(overlay, native):
    app = overlay.app
    host = native.host
    app.voice_overlay.observer = host.overlay_changed
    live, session = await begin(overlay)
    (process,) = native.processes
    await app.voice.stop_local()
    await until(lambda: host.overlay_ended is not None)
    assert process.running  # it fades out and quits by itself
    await begin(overlay)
    assert len(native.processes) == 1 and host.overlay_ended is None  # reused
    app.resources.select("gaming")
    await app.restrict_resources()
    await until(lambda: process.closed)
    assert host.overlay is None
