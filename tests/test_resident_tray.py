"""The native tray's state icons: which icon, at which size, switched only on change, the
jarvis.ico fallback, reloads, DPI awareness and the calls.enabled observer.

No real tray icon or window is created: Win32 calls go to recording fakes.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from resident import win32
from resident.host import NativeHost
from resident.state import TRAY_ICONS, Identity, State, tray_icon
from resident.win32 import NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_MODIFY, NotifyData, Tray


# --- choosing the icon -------------------------------------------------------------------
CASES = [
    # phase, error, gaming, talking, calls -> icon
    (("failed", None, False, False, False), "attention"),
    (("failed", "x", True, True, True), "attention"),
    (("ready", "Workspace startup timed out.", True, True, True), "attention"),
    (("starting", "x", False, False, False), "attention"),
    (("ready", None, True, True, True), "paused"),
    (("starting", None, False, True, True), "paused"),
    (("stopping", None, False, True, True), "paused"),
    (("ready", None, False, True, True), "talking"),
    (("ready", None, False, True, False), "talking"),
    (("ready", None, False, False, True), "calls"),
    (("ready", None, False, False, False), "ready"),
    (("ready", "", False, False, False), "ready"),
]


@pytest.mark.parametrize("args,expected", CASES)
def test_tray_icon_priority(args, expected):
    assert tray_icon(*args) == expected


def test_every_chosen_icon_is_a_published_state_icon():
    assert {expected for _args, expected in CASES} == set(TRAY_ICONS)
    assert TRAY_ICONS == ("ready", "talking", "calls", "attention", "paused")


def test_state_icon_reads_phase_error_gaming_voice_and_calls(tmp_path):
    state = State(Identity(tmp_path))
    assert state.icon() == "paused"                     # starting
    state.phase = "ready"
    assert state.icon() == "ready"
    state.calls = True
    assert state.icon() == "calls"
    state.voice = {"active": True, "state": "listening"}
    assert state.icon() == "talking"
    state.voice = {"active": False, "notice": "Voice stopped."}
    assert state.icon() == "calls"
    state.identity.gaming = True
    assert state.icon() == "paused"
    state.error = "The workspace could not start."
    assert state.icon() == "attention"


# --- Win32 fakes ---------------------------------------------------------------------------
class FakeUser:
    """user32 stand-in: small-icon metrics, LoadImageW handles, DestroyIcon."""

    def __init__(self, dpi=144, size=24, fail=()):
        self.dpi, self.size, self.fail = dpi, size, set(fail)
        self.metrics, self.loads, self.destroyed = [], [], []
        self.next = 100

        def GetDpiForSystem():
            return self.dpi

        def GetSystemMetricsForDpi(index, dpi):
            self.metrics.append((index, dpi))
            return self.size

        def GetSystemMetrics(index):
            self.metrics.append((index, None))
            return 16

        def LoadImageW(instance, path, kind, width, height, flags):
            self.loads.append((path, kind, width, height, flags))
            if any(path.endswith(name) for name in self.fail):
                return 0
            self.next += 1
            return self.next

        def DestroyIcon(handle):
            self.destroyed.append(handle)
            return 1

        for function in (GetDpiForSystem, GetSystemMetricsForDpi, GetSystemMetrics, LoadImageW,
                         DestroyIcon):
            setattr(self, function.__name__, function)


class FakeShell:
    def __init__(self):
        self.calls = []

        def Shell_NotifyIconW(message, data):
            data = data._obj
            self.calls.append((message, data.flags, data.icon))
            return 1

        self.Shell_NotifyIconW = Shell_NotifyIconW


@pytest.fixture
def fakes(monkeypatch):
    user, shell = FakeUser(), FakeShell()
    monkeypatch.setattr(win32, "user", user)
    monkeypatch.setattr(win32, "shell", shell)
    return user, shell


def tray(folder, state="ready"):
    """A Tray with its icon logic only: no window, mutex or notification area entry."""
    value = Tray.__new__(Tray)
    value.icon_folder, value.icon_state = folder, state
    value.data = NotifyData()
    value.icons = value.load_icons()
    value.icon = value.data.icon = value.icons[state]
    return value


def icons_folder(tmp_path):
    folder = tmp_path / "assets" / "icons"
    return folder


# --- icon size -----------------------------------------------------------------------------
@pytest.mark.parametrize("dpi,size", [(96, 16), (120, 20), (144, 24), (192, 32)])
def test_small_icon_size_comes_from_the_system_dpi_metrics(monkeypatch, dpi, size):
    user = FakeUser(dpi=dpi, size=size)
    monkeypatch.setattr(win32, "user", user)
    assert win32.small_icon_size() == size
    assert user.metrics == [(49, dpi)]                   # SM_CXSMICON at GetDpiForSystem()


def test_small_icon_size_falls_back_without_the_dpi_api(monkeypatch):
    user = FakeUser()
    del user.GetSystemMetricsForDpi
    monkeypatch.setattr(win32, "user", user)
    assert win32.small_icon_size() == 16 and user.metrics == [(49, None)]


def test_state_icons_load_at_the_small_icon_size_for_both_dimensions(fakes, tmp_path):
    user, _shell = fakes
    folder = icons_folder(tmp_path)
    value = tray(folder)
    assert set(value.icons) == set(TRAY_ICONS) and len(set(value.icons.values())) == 5
    assert [load[0] for load in user.loads] == [
        str((folder / "tray" / f"jarvis-{name}.ico").resolve()) for name in TRAY_ICONS]
    assert {load[1:] for load in user.loads} == {(1, 24, 24, 0x10)}   # IMAGE_ICON, LOADFROMFILE


def test_failed_state_icons_fall_back_to_the_app_icon_with_one_log_line(fakes, tmp_path, caplog):
    user, _shell = fakes
    user.fail = {"jarvis-calls.ico"}
    folder = icons_folder(tmp_path)
    with caplog.at_level(logging.WARNING):
        value = tray(folder)
    fallback = value.icons["ready"]
    assert set(value.icons.values()) == {fallback}
    assert user.loads[-1][0] == str((folder / "jarvis.ico").resolve())
    assert sorted(user.destroyed) == [101, 102]         # ready and talking, loaded before calls
    lines = [r for r in caplog.records if "Tray state icons could not load" in r.getMessage()]
    assert len(lines) == 1 and "jarvis.ico" in lines[0].getMessage()


def test_no_icon_at_all_still_raises(fakes, tmp_path):
    user, _shell = fakes
    user.fail = {".ico"}
    with pytest.raises(OSError):
        tray(icons_folder(tmp_path))


# --- switching -----------------------------------------------------------------------------
def test_nim_modify_with_nif_icon_only_when_the_icon_changes(fakes, tmp_path):
    _user, shell = fakes
    value = tray(icons_folder(tmp_path), "paused")
    assert value.show_icon("paused") is False and shell.calls == []
    assert value.show_icon("ready") is True
    assert shell.calls == [(NIM_MODIFY, NIF_ICON, value.icons["ready"])]
    assert value.show_icon("ready") is False and len(shell.calls) == 1
    value.show_icon("calls")
    value.show_icon("calls")
    value.show_icon("attention")
    assert shell.calls[1:] == [(NIM_MODIFY, NIF_ICON, value.icons["calls"]),
                               (NIM_MODIFY, NIF_ICON, value.icons["attention"])]
    assert value.show_icon("unknown") is False and len(shell.calls) == 3


# --- reloading -----------------------------------------------------------------------------
@pytest.mark.parametrize("message", [win32.WM_DISPLAYCHANGE, win32.WM_SETTINGCHANGE])
def test_display_and_setting_changes_reload_and_destroy_the_old_icons(fakes, tmp_path, message):
    user, shell = fakes
    value = tray(icons_folder(tmp_path), "talking")
    value.on_action = lambda action: pytest.fail(f"unexpected action {action}")
    old = dict(value.icons)
    user.size = 32
    assert value._message(None, message, 0, 0) == 0
    assert set(value.icons.values()).isdisjoint(old.values())
    assert sorted(user.destroyed) == sorted(old.values())
    assert {load[2:4] for load in user.loads[-5:]} == {(32, 32)}
    assert shell.calls == [(NIM_MODIFY, NIF_ICON, value.icons["talking"])]
    assert value.icon == value.data.icon == value.icons["talking"]


def test_a_recreated_taskbar_reloads_and_adds_the_icon_again(fakes, tmp_path):
    user, shell = fakes
    value = tray(icons_folder(tmp_path), "calls")
    value.on_action = lambda action: pytest.fail(f"unexpected action {action}")
    value.taskbar_message = 0xC123
    old = set(value.icons.values())
    value._message(None, 0xC123, 0, 0)
    assert shell.calls[0] == (NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP, value.icons["calls"])
    assert shell.calls[1][0] == 4                        # NIM_SETVERSION
    assert set(user.destroyed) == old


def test_a_failed_reload_keeps_the_current_icons(fakes, tmp_path):
    user, shell = fakes
    value = tray(icons_folder(tmp_path), "ready")
    current = dict(value.icons)
    user.fail = {".ico"}
    assert value.reload_icons() is False
    assert value.icons == current and user.destroyed == [] and value.icon == current["ready"]


def test_close_destroys_every_icon_once(fakes, tmp_path):
    user, _shell = fakes
    user.fail = {"jarvis-ready.ico"}
    value = tray(icons_folder(tmp_path))
    value.window = value.mutex = None
    value.close()
    assert len(user.destroyed) == 1 and value.icons == {} and value.icon is None


# --- DPI awareness -------------------------------------------------------------------------
def test_dpi_awareness_is_per_monitor_v2(monkeypatch):
    seen = []

    def SetProcessDpiAwarenessContext(context):
        seen.append(context)
        return 1

    monkeypatch.setattr(win32, "user", SimpleNamespace(
        SetProcessDpiAwarenessContext=SetProcessDpiAwarenessContext))
    assert win32.enable_dpi_awareness() is True and seen == [-4]


def test_dpi_awareness_fails_silently_where_unsupported(monkeypatch):
    monkeypatch.setattr(win32, "user", SimpleNamespace())
    assert win32.enable_dpi_awareness() is False

    def refuses(context):
        raise OSError("access denied")

    monkeypatch.setattr(win32, "user", SimpleNamespace(SetProcessDpiAwarenessContext=refuses))
    assert win32.enable_dpi_awareness() is False


def test_dpi_awareness_is_set_at_startup_before_the_host_creates_its_tray():
    source = (win32.Path(win32.__file__).resolve().parents[1] / "resident_main.py").read_text()
    assert source.index("enable_dpi_awareness()") < source.index("NativeHost(")


def test_real_dpi_aware_metrics_are_sane():
    """The real API, read-only: per-monitor v2 is already the default for this test process
    or not; either way the small-icon size is a plausible pixel size."""
    size = win32.small_icon_size()
    assert 16 <= size <= 64


def test_tray_menu_and_balloon_paths_are_unchanged(fakes, tmp_path):
    _user, shell = fakes
    value = tray(icons_folder(tmp_path), "ready")
    value.suppress_notifications, value.notification_count = False, 0
    assert value.notify("JARVIS call", "A call record is ready.") is True
    assert shell.calls[-1] == (NIM_MODIFY, 0x10, value.icons["ready"])   # NIF_INFO, icon kept
    value.tooltip("JARVIS · Native resident")
    assert shell.calls[-1] == (NIM_MODIFY, NIF_TIP, value.icons["ready"])
    value.talking, value.wake_word = False, True
    assert [item[0] for item in value.menu_items()] == [
        "open", "talk", "wake_word", "gaming", "retry", "quit"]


# --- the host ------------------------------------------------------------------------------
class IconTray:
    """A host tray that records tooltips and state icons (it has a window)."""

    window = 1
    secondary = False
    hotkey = False

    def __init__(self, *args, icon_state=None, **kwargs):
        self.args, self.first = args, icon_state
        self.icons, self.tips, self.posted = [], [], 0
        self.talking = self.wake_word = False

    def post(self, callback):
        self.posted += 1
        callback()

    def tooltip(self, value):
        self.tips.append(value)

    def show_icon(self, name):
        self.icons.append(name)

    def close(self):
        pass


@pytest.fixture
def host(tmp_path):
    native = NativeHost(tmp_path, tmp_path / "profile", tray_factory=IconTray, resident_only=True)
    native.state.phase = "ready"
    return native


def test_host_gives_the_tray_its_icon_folder_and_first_icon(host, tmp_path):
    assert host.tray.args[1] == tmp_path / "assets/icons"
    assert host.tray.first == "paused"                  # the resident starts "starting"


def test_calls_observer_posts_to_the_tray_and_switches_the_icon(host):
    host.calls_changed(True)
    assert host.tray.posted == 1 and host.state.calls is True and host.tray.icons[-1] == "calls"
    host.calls_changed(False)
    assert host.state.calls is False and host.tray.icons[-1] == "ready"
    host.calls_changed("yes")                          # only a real True turns it on
    assert host.state.calls is False


def test_host_icon_follows_voice_gaming_and_failure(host):
    host.calls_changed(True)
    host.show_voice({"active": True, "state": "listening", "microphone": "on"})
    assert host.tray.icons[-1] == "talking"
    host.action("gaming")
    assert host.tray.icons[-1] == "paused"
    host.action("gaming")
    host.show_voice({"active": False, "state": "off", "microphone": "off"})
    assert host.tray.icons[-1] == "calls"
    host.action("failed")
    assert host.tray.icons[-1] == "attention"


def test_telephony_settings_changed_reports_calls_enabled():
    from telephony.service import TelephonyService

    service = TelephonyService.__new__(TelephonyService)
    service.app = SimpleNamespace(settings={"calls": {"enabled": True}})
    service.observer = None
    service.settings_changed()                         # no observer: nothing to tell
    seen = []
    service.observer = seen.append
    service.settings_changed()
    service.app.settings = {}
    service.settings_changed()
    service.app.settings = {"calls": {"enabled": "true"}}
    service.settings_changed()
    assert seen == [True, False, False]

    def broken(enabled):
        raise RuntimeError("tray gone")

    service.observer = broken
    service.settings_changed()                         # logged, never raised


@pytest.mark.asyncio
async def test_a_calls_settings_change_reaches_the_observer(application_factory):
    app = application_factory()
    app.telephony.reconcile = AsyncMock()
    seen = []
    app.telephony.observer = seen.append
    app.settings["calls"] = {"enabled": True}
    await app.settings_changed({"calls": {"enabled": True}})
    app.settings["calls"] = {"enabled": False}
    await app.settings_changed({"calls": {"enabled": False}})
    await app.settings_changed({"camera_flipped": True})   # not a calls change
    assert seen == [True, False] and app.telephony.reconcile.await_count == 2


def test_host_core_startup_reports_calls_enabled_through_the_tray():
    source = (win32.Path(win32.__file__).resolve().parent / "host.py").read_text()
    core = source[source.index("    def _core(self):"):source.index("    def _attach_identity")]
    assert "server.runtime.telephony.observer = self.calls_changed" in core
    assert core.index("telephony.observer") < core.index("telephony.settings_changed()")

