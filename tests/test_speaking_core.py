"""The workspace's speaking core (C1): tray voice published to the owner's renderers
(``local_voice`` / ``local_voice_level``), the ``voice_stage`` report that decides when the
talking overlay opens, and the stage's ``local_voice_stop``.

Fake PortAudio, fake Live session and fake sockets only (the tray voice fixtures): no
microphone, speaker, Electron, network or provider is ever used, and no port is bound.
"""

import asyncio
import logging
import struct
from types import SimpleNamespace
import uuid

import pytest
from google.genai import types

from tests.test_local_voice import OWNER, pull, speech, stopped
from tests.test_local_voice import tray  # noqa: F401 - the tray voice fixture
from tests.test_voice_live import until
from tests.test_voice_overlay import OVERLAY, begin, fake_overlay, sent
from tests.test_voice_overlay import overlay  # noqa: F401 - the overlay fixture

RENDERER = "client"  # the tray fixture's owner renderer


def handler(app, name):
    return app.sio.handlers["/"][name]


async def stage(app, visible, sid=RENDERER):
    return await handler(app, "voice_stage")(sid, {"visible": visible})


def started_events(ctx):
    return [event for event in ctx.host_events if event[0] == "started"]


# --- local_voice to the owner's renderers ----------------------------------------------------


@pytest.mark.asyncio
async def test_renderers_get_the_snapshot_with_its_source(overlay):  # noqa: F811
    app = overlay.app
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="What's on today?"))
    await until(lambda: sent(app, "local_voice", RENDERER)
                and sent(app, "local_voice", RENDERER)[-1]["user"] == "What's on today?")
    snaps = sent(app, "local_voice", RENDERER)
    assert all(item["source"] == "tray" and item["session"] == session.id for item in snaps)
    assert snaps[-1] == {**overlay.model.snapshot(), "source": "tray"}
    # The overlay's own snapshot is unchanged: no source.
    assert all("source" not in item for item in sent(app))
    await app.voice.stop_local()
    await until(lambda: sent(app, "local_voice", RENDERER)[-1]["state"] == "ended")
    assert sent(app, "local_voice", RENDERER)[-1]["end"] == {"kind": "quiet", "message": None}


@pytest.mark.asyncio
async def test_a_hey_jarvis_session_is_wake_from_the_first_snapshot(overlay):  # noqa: F811
    app = overlay.app
    assert (await app.voice.start_local(wake=True))["ok"]
    await until(lambda: overlay.model.state == "listening")
    await until(lambda: sent(app, "local_voice", RENDERER)[-1]["state"] == "listening")
    snaps = sent(app, "local_voice", RENDERER)
    assert snaps and all(item["source"] == "wake" for item in snaps)
    await app.voice.stop_local()
    # A later tray start is "tray" again.
    await begin(overlay)
    assert sent(app, "local_voice", RENDERER)[-1]["source"] == "tray"
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_connecting_renderer_gets_the_running_snapshot_only(overlay):  # noqa: F811
    app = overlay.app
    app.sio.emit.reset_mock()
    await app.connection.hydrate(RENDERER)  # no session: nothing to show
    assert not sent(app, "local_voice", RENDERER)
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="Hello"))
    await until(lambda: overlay.model.user == "Hello")
    await asyncio.sleep(0.08)
    app.sio.emit.reset_mock()
    await app.connection.hydrate(RENDERER)  # a reload mid-session
    assert sent(app, "local_voice", RENDERER) == [{**overlay.model.snapshot(), "source": "tray"}]
    assert not sent(app, "local_voice", OVERLAY) and not sent(app, room=RENDERER)
    await app.voice.stop_local()
    await until(lambda: overlay.model.state == "ended")
    await asyncio.sleep(0.08)
    app.sio.emit.reset_mock()
    await app.connection.hydrate(RENDERER)  # ended: nothing is replayed
    assert not sent(app, "local_voice", RENDERER)


@pytest.mark.asyncio
async def test_a_locked_or_foreign_renderer_gets_nothing():
    model, emit, _ = fake_overlay(rooms=(), renderers=("r",))
    unlocked = [False]
    model.app.sessions.authenticated = lambda owner: unlocked[0]
    session = SimpleNamespace(id="s", closed=False, audio=SimpleNamespace(measure_level=None),
                              view="listening")
    model.started(session)
    model.caption("user", "private", False)
    await asyncio.sleep(0.08)
    emit.assert_not_called()
    assert session.audio.measure_level is False
    await model.renderer_attached("r")
    emit.assert_not_called()
    unlocked[0] = True
    await model.renderer_attached("r")
    assert [call.args[0] for call in emit.await_args_list] == ["local_voice"]
    assert session.audio.measure_level is True
    await model.close()


@pytest.mark.asyncio
async def test_renderer_snapshots_coalesce_and_the_end_goes_at_once():
    from tests.test_local_voice import Clock

    model, emit, _ = fake_overlay(rooms=(), renderers=("r",))
    clock = Clock()
    model.clock = clock
    session = SimpleNamespace(id="s", closed=False, audio=None, view="listening")
    model.started(session, "wake")

    def snaps():
        return [c.args[1] for c in emit.await_args_list if c.args[0] == "local_voice"]

    for index in range(100):
        model.caption("user", f"word {index}", False)
    await until(snaps)
    await asyncio.sleep(0.01)
    assert [item["user"] for item in snaps()] == ["word 99"]
    assert snaps()[0]["source"] == "wake"
    model.caption("jarvis", "a", False)
    clock.now += 0.049
    await asyncio.sleep(0.1)
    assert len(snaps()) == 1  # inside the 50 ms window
    session.closed = True
    model.ended(session, "error", "voice_failed", "Voice stopped unexpectedly.")
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(snaps()) == 2  # the end is never held back
    assert snaps()[-1]["end"] == {"kind": "error", "message": "Voice stopped unexpectedly."}
    assert snaps()[-1]["jarvis"] == "a"
    assert not [c for c in emit.await_args_list if c.args[0] == "voice_overlay"]
    await model.close()


@pytest.mark.asyncio
async def test_levels_reach_renderers_and_end_with_zero(overlay):  # noqa: F811
    app = overlay.app
    del app.sessions.principals[OVERLAY], app.sessions.roles[OVERLAY]  # the workspace only
    app.voice_overlay.interval = 0.01
    live, session = await begin(overlay)
    assert session.audio.measure_level is True
    speaker = overlay.backend.stream("output")
    live.push(model_turn=speech(struct.pack("<h", 8000) * 4800))
    await until(lambda: overlay.model.state == "speaking")
    for _ in range(10):
        pull(speaker)
    await until(lambda: any(item["level"] > 0.5 for item in sent(app, "local_voice_level", RENDERER)))
    assert all(0.0 <= item["level"] <= 1.0 for item in sent(app, "local_voice_level", RENDERER))
    overlay.clock.now += 1.0
    live.push(turn_complete=True)
    await until(lambda: sent(app, "local_voice_level", RENDERER)[-1] == {"level": 0.0}
                and overlay.model.state == "listening")
    await asyncio.sleep(0.05)
    count = len(sent(app, "local_voice_level", RENDERER))
    await asyncio.sleep(0.05)
    assert len(sent(app, "local_voice_level", RENDERER)) == count
    assert not sent(app, "voice_level", RENDERER)
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_the_speaker_is_measured_while_a_renderer_or_overlay_is_connected(overlay):  # noqa: F811
    app = overlay.app
    live, session = await begin(overlay)
    assert session.audio.measure_level is True  # both
    app.voice_overlay.detached(OVERLAY)
    assert session.audio.measure_level is True  # the renderer still counts
    del app.sessions.principals[OVERLAY], app.sessions.roles[OVERLAY]
    app.voice_overlay.detached(RENDERER)
    assert session.audio.measure_level is False  # neither
    await app.voice_overlay.renderer_attached(RENDERER)
    assert session.audio.measure_level is True
    await app.voice.stop_local()
    assert session.audio is None or session.audio.measure_level is False


# --- voice_stage ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_stage_validates_and_is_owner_renderer_only(overlay):  # noqa: F811
    app = overlay.app
    model = overlay.model
    assert await stage(app, True) == {"ok": True}
    assert model.stages == {RENDERER: True}
    assert await stage(app, False) == {"ok": True}
    assert model.stages == {RENDERER: False}
    for bad in (None, {}, [], "visible", {"visible": "true"}, {"visible": 1}, {"visible": None},
                {"visible": True, "extra": 1}):
        result = await handler(app, "voice_stage")(RENDERER, bad)
        assert result["ok"] is False and result["code"] == "invalid_arguments", bad
        assert isinstance(result["message"], str)
    assert model.stages == {RENDERER: False}
    for sid in (OVERLAY, "native-resident", "stranger"):
        assert (await stage(app, True, sid))["code"] == "authentication_required"
    app.sessions.principals["foreign"] = str(uuid.uuid4())
    app.sessions.roles["foreign"] = "renderer"
    assert (await stage(app, True, "foreign"))["code"] == "permission_denied"
    assert model.stages == {RENDERER: False}
    app.settings["face_auth_enabled"] = True  # locked: still accepted (it can only hide)
    assert await stage(app, True) == {"ok": True}
    assert not model.stage_shown()  # a locked owner's stage never counts as shown
    app.settings["face_auth_enabled"] = False
    assert model.stage_shown()
    await app.disconnect(RENDERER)
    assert model.stages == {}  # forgotten on disconnect


# --- the overlay rule -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_stage_shown_opens_the_overlay_at_start(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, False)
    await begin(overlay)
    assert overlay.host_events == [("started", None)]
    await app.voice.stop_local()
    assert overlay.host_events[-1] == ("ended", {"now": False})


@pytest.mark.asyncio
async def test_a_shown_stage_owes_the_overlay_until_it_goes(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, True)
    live, session = await begin(overlay)
    assert overlay.host_events == []
    live.push(input_transcription=types.Transcription(text="Hello"))
    await until(lambda: overlay.model.user == "Hello")
    await asyncio.sleep(0.08)
    # While owed, an overlay still open from an earlier session is never shown this one.
    assert not sent(app) and not sent(app, "voice_level")
    assert sent(app, "local_voice", RENDERER)[-1]["user"] == "Hello"
    await stage(app, False)  # minimised, another page, another app
    assert overlay.host_events == [("started", None)]
    await until(lambda: sent(app) and sent(app)[-1]["user"] == "Hello")  # it shows the session
    # It stays: the stage coming back never closes it, and it never opens twice.
    await stage(app, True)
    await stage(app, False)
    await stage(app, True)
    assert overlay.host_events == [("started", None)]
    await app.voice.stop_local()
    assert overlay.host_events == [("started", None), ("ended", {"now": False})]


@pytest.mark.asyncio
async def test_the_stage_shown_for_the_whole_session_never_opens_the_overlay(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, True)
    await begin(overlay)
    await app.voice.stop_local()
    await until(lambda: overlay.model.state == "ended")
    assert overlay.host_events == [("ended", {"now": False})]  # unchanged: the host ignores it
    await stage(app, False)  # after the session: nothing is owed
    assert started_events(overlay) == []


@pytest.mark.asyncio
async def test_a_renderer_disconnect_opens_the_owed_overlay(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, True)
    await begin(overlay)
    assert overlay.host_events == []
    await app.disconnect(RENDERER)
    assert overlay.host_events == [("started", None)]
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_any_visible_renderer_counts_as_shown(overlay):  # noqa: F811
    app = overlay.app
    app.sessions.principals["second"] = OWNER
    app.sessions.roles["second"] = "renderer"
    await stage(app, True)
    await stage(app, False, "second")
    await begin(overlay)
    assert overlay.host_events == []
    await stage(app, True, "second")
    await stage(app, False)
    assert overlay.host_events == []  # "second" still shows it
    await stage(app, False, "second")
    assert overlay.host_events == [("started", None)]
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_the_setting_off_cancels_an_owed_overlay(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, True)
    await begin(overlay)
    app.settings["voice"] = {"overlay": False}
    await app.settings_changed({"voice": {"overlay": False}})
    assert overlay.host_events == [("disabled", None)]
    await stage(app, False)
    app.settings["voice"] = {"overlay": True}
    await app.settings_changed({"voice": {"overlay": True}})
    await stage(app, True)
    await stage(app, False)
    assert started_events(overlay) == []  # nothing for this session any more
    await app.voice.stop_local()


@pytest.mark.asyncio
async def test_a_new_session_starts_the_rule_afresh(overlay):  # noqa: F811
    app = overlay.app
    await stage(app, False)
    await begin(overlay)
    await stage(app, True)  # the overlay is open: it stays
    await app.voice.stop_local()
    assert overlay.host_events == [("started", None), ("ended", {"now": False})]
    await begin(overlay)  # the stage is shown now: owed
    assert overlay.host_events == [("started", None), ("ended", {"now": False})]
    await stage(app, False)
    assert overlay.host_events[-1] == ("started", None)
    await app.voice.stop_local()


# --- local_voice_stop -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_voice_stop_is_the_stages_stop_talking(overlay):  # noqa: F811
    app = overlay.app
    stop = handler(app, "local_voice_stop")
    await begin(overlay)
    for sid in (OVERLAY, "native-resident", "stranger"):
        assert (await stop(sid, None))["code"] == "authentication_required"
    app.sessions.principals["foreign"] = str(uuid.uuid4())
    app.sessions.roles["foreign"] = "renderer"
    assert (await stop("foreign", None))["code"] == "permission_denied"
    for bad in ({"session_id": "x"}, [], "stop", 1):
        result = await stop(RENDERER, bad)
        assert result["code"] == "invalid_arguments" and result["message"]
    assert app.voice.sessions
    app.settings["face_auth_enabled"] = True  # a safety stop: allowed while locked
    assert await stop(RENDERER, {}) == {"ok": True}
    status = await stopped(overlay)
    assert status["notice"] is None
    assert await stop(RENDERER, None) == {"ok": True}  # nothing running: still fine


@pytest.mark.asyncio
async def test_local_voice_stop_never_ends_window_voice(overlay):  # noqa: F811
    app = overlay.app
    app.resources.select("chat")
    payload = {"mode": "conversation", "conversation_id": str(uuid.UUID(int=1))}
    ack = await handler(app, "voice_start")(RENDERER, payload)
    assert ack["ok"], ack
    assert await handler(app, "local_voice_stop")(RENDERER, {}) == {"ok": True}
    assert app.voice.sessions[OWNER].id == ack["session_id"]
    await handler(app, "voice_stop")(RENDERER, {"session_id": ack["session_id"]})


# --- privacy --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_captions_never_reach_the_logs(overlay, caplog):  # noqa: F811
    app = overlay.app
    caplog.set_level(logging.DEBUG)
    await stage(app, True)
    live, session = await begin(overlay)
    live.push(input_transcription=types.Transcription(text="my secret question"))
    live.push(output_transcription=types.Transcription(text="a secret answer"))
    await until(lambda: sent(app, "local_voice", RENDERER)
                and sent(app, "local_voice", RENDERER)[-1]["jarvis"] == "a secret answer")
    await app.connection.hydrate(RENDERER)
    await stage(app, False)
    await handler(app, "local_voice_stop")(RENDERER, {})
    await until(lambda: overlay.model.state == "ended")
    assert "secret" not in caplog.text
