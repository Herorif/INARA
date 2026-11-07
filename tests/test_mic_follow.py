"""Automatic microphone (voice.local_microphone "default") follows Windows' default in the core.

While "Hey Jarvis" listens its stream stays open, so PortAudio never re-reads the devices by
itself; the wake listener compares Windows' own view (a probe, faked here) and reopens on a
change, never during a voice session. Fake PortAudio module, fake probe, fake listener and
the tray fixtures' fake clock only: no real microphone is opened.
"""

import sys
import time

import pytest

from services import audio_devices as audio_module
from services.audio_devices import AudioDevices
from tests.test_local_voice import host, tray  # noqa: F401 - the tray voice fixtures
from tests.test_voice_live import until
from tests.test_wake_listening import listening, live_session, wake  # noqa: F401 - fixtures

REALTEK, YETI = 2, 3  # the fake WASAPI microphones (test_local_voice.FakeSoundDevice)
HEADSET = ("{headset}", "{headset}"), ("{headset}", "{yeti}")
DESK = ("{yeti}", "{yeti}"), ("{headset}", "{yeti}")


class Probe:
    """Windows' microphones as Core Audio would report them, changed by hand."""

    def __init__(self, value=HEADSET):
        self.value, self.calls = value, 0

    def __call__(self):
        self.calls += 1
        return self.value


def follow_windows(ctx, value=HEADSET):
    probe = Probe(value)
    ctx.app.audio_devices.probe = probe
    return probe


def windows_default(ctx, index):
    """Windows makes another microphone the default (PortAudio sees it once re-read)."""
    ctx.backend.hostapis[1]["default_input_device"] = index


async def test_automatic_reopens_on_a_new_windows_default(wake):  # noqa: F811 - fixture
    probe = follow_windows(wake)
    listener, stream = await listening(wake)
    assert stream.device == REALTEK and wake.service.following()
    refreshed = wake.backend.refreshed
    assert await wake.service.follow() is False  # nothing changed: no reopen
    assert wake.backend.open_inputs() == [stream] and wake.backend.refreshed == refreshed

    windows_default(wake, YETI)
    probe.value = DESK
    assert await wake.service.follow() is True
    await wake.service.reconcile()
    (reopened,) = wake.backend.open_inputs()
    assert stream.released and reopened.device == YETI
    assert wake.backend.refreshed > refreshed  # PortAudio re-read its devices with none open
    assert listener.resets == 1 and listener.running
    assert wake.service.status() == {"state": "listening", "message": None}
    assert await wake.service.follow() is False  # the new view is the baseline


async def test_a_plugged_in_microphone_reopens_even_if_the_default_stays(wake):  # noqa: F811 - fixture
    probe = follow_windows(wake)
    _, stream = await listening(wake)
    probe.value = (HEADSET[0], HEADSET[1] + ("{usb}",))
    assert await wake.service.follow() is True
    await wake.service.reconcile()
    (reopened,) = wake.backend.open_inputs()
    assert stream.released and reopened.device == REALTEK


async def test_no_switch_during_an_active_voice_session(wake):  # noqa: F811 - fixture
    app = wake.app
    probe = follow_windows(wake)
    _, stream = await listening(wake)
    assert (await app.voice.start_local())["ok"]
    session, _ = await live_session(wake)
    windows_default(wake, YETI)
    probe.value = DESK
    calls = probe.calls
    assert await wake.service.follow() is False
    assert probe.calls == calls  # not even asked while the session runs
    await wake.service.reconcile()
    assert wake.backend.open_inputs() == [stream] and not stream.released
    assert app.voice.sessions[session.owner] is session and session.audio.ready

    await app.voice.stop_local()  # the next session gets the new default
    assert await wake.service.follow() is True
    await wake.service.reconcile()
    (reopened,) = wake.backend.open_inputs()
    assert stream.released and reopened.device == YETI


async def test_a_detection_being_decided_is_not_interrupted(wake):  # noqa: F811 - fixture
    probe = follow_windows(wake)
    _, stream = await listening(wake)
    wake.service.microphone.arm()
    probe.value = DESK
    assert await wake.service.follow() is False
    wake.service.default_moved = True  # even if a change was already seen
    await wake.service.reconcile()
    assert wake.backend.open_inputs() == [stream]
    wake.service.microphone.discard()
    assert await wake.service.follow() is True


async def test_a_named_microphone_is_never_followed(wake):  # noqa: F811 - fixture
    app = wake.app
    probe = follow_windows(wake)
    choice = {"name": "Microphone (Yeti Orb)", "host_api": "Windows WASAPI"}
    app.settings["voice"] = {"local_microphone": choice}
    _, stream = await listening(wake)
    assert stream.device == YETI and not wake.service.following()
    probe.value = DESK
    assert await wake.service.follow() is False and probe.calls == 0
    assert wake.service._timeout() is None  # no 5 s checks either


async def test_without_a_probe_nothing_is_followed(wake):  # noqa: F811 - fixture
    _, stream = await listening(wake)
    assert wake.app.audio_devices.probe is None and not wake.service.following()
    assert await wake.service.follow() is False and wake.backend.open_inputs() == [stream]


async def test_a_playing_cue_postpones_the_switch(wake):  # noqa: F811 - fixture
    probe = follow_windows(wake)
    _, stream = await listening(wake)
    probe.value = DESK
    wake.app.audio_devices.open_streams += 1  # a cue's output stream
    assert await wake.service.follow() is False
    wake.app.audio_devices.open_streams -= 1
    assert await wake.service.follow() is True


async def test_the_listener_checks_windows_every_few_seconds_while_idle(wake):  # noqa: F811 - fixture
    service = wake.service
    probe = follow_windows(wake)
    service.follow_every = 0.02  # FOLLOW_SECONDS is 5 s; short here
    _, stream = await listening(wake)
    await service.begin()
    await until(lambda: probe.calls >= 3)
    assert wake.backend.open_inputs() == [stream]
    windows_default(wake, YETI)
    probe.value = DESK
    await until(lambda: stream.released and len(wake.backend.open_inputs()) == 1)
    assert wake.backend.open_inputs()[0].device == YETI


async def test_the_probe_runs_off_the_loop_and_a_hung_probe_is_dropped(monkeypatch):
    devices = AudioDevices(loader=lambda: None, probe=lambda: ("a", ()))
    try:
        assert await devices.input_fingerprint() == ("a", ())

        def broken():
            raise OSError("Core Audio refused")

        devices.probe = broken
        assert await devices.input_fingerprint() is None
        assert devices.probe is broken  # a failure is retried next time

        monkeypatch.setattr(audio_module, "PROBE_TIMEOUT", 0.05)

        def hung():
            time.sleep(0.3)
            return ("late", ())

        devices.probe = hung
        assert await devices.input_fingerprint() is None
        assert devices.probe is None  # stuck: not asked again
        assert await devices.input_fingerprint() is None
    finally:
        devices.close()


def test_the_real_backend_gets_the_windows_probe_and_fakes_do_not():
    from services.default_input import fingerprint

    assert AudioDevices().probe is fingerprint
    assert AudioDevices(loader=lambda: None).probe is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Core Audio")
def test_real_windows_probe_reads_endpoint_ids_only():
    """Reads this PC's capture endpoint ids through Core Audio; activates and opens nothing."""
    from services.default_input import fingerprint

    value = fingerprint()
    assert isinstance(value, tuple) and len(value) == 2
    defaults, active = value
    assert len(defaults) == 2 and all(item is None or isinstance(item, str) for item in defaults)
    assert all(isinstance(item, str) for item in active) and list(active) == sorted(active)
    assert fingerprint() == value  # stable while nothing changes
