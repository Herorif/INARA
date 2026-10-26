"""Focused regression tests for backend correctness audit findings M8-M10, L1, L2."""

import asyncio
import copy
import json
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from services import settings as settings_module
from services.settings import (
    RECOVERY_ERROR_CODE,
    SettingsPatch,
    SettingsService,
    SettingsStore,
    load_settings_file,
    recovery_backup,
)
from services.tools import ServiceError


# ---------------------------------------------------------------------------
# M8: corrupt settings are backed up and never overwritten
# ---------------------------------------------------------------------------

DEFAULTS = {"face_auth_enabled": False, "tool_permissions": {"launch_app": True}}
CORRUPT = '{"printers": [{"host": "10.0.0.5"}], "tool_permissions": {"write_file": "deny"'


def test_valid_settings_merge_and_save_normally(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"tool_permissions": {"write_file": "deny"}, "printers": [1]}))
    values = copy.deepcopy(DEFAULTS)
    assert load_settings_file(path, values) is True
    assert values["tool_permissions"] == {"launch_app": True, "write_file": "deny"}
    assert values["printers"] == [1]
    assert recovery_backup(path) == (False, None)
    SettingsStore(path).save({**values, "camera_flipped": True})
    assert json.loads(path.read_text())["camera_flipped"] is True
    assert not list(tmp_path.glob("*.corrupt-*"))


def test_missing_settings_file_is_not_recovery(tmp_path):
    path = tmp_path / "settings.json"
    values = copy.deepcopy(DEFAULTS)
    assert load_settings_file(path, values) is True
    assert values == DEFAULTS
    SettingsStore(path).save(values)
    assert path.exists()


@pytest.mark.parametrize("content", [CORRUPT, "[1, 2, 3]", "\xff\xfe garbage"])
def test_corrupt_settings_backed_up_defaults_used_and_saves_blocked(tmp_path, content, caplog):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    original = path.read_bytes()
    values = copy.deepcopy(DEFAULTS)

    assert load_settings_file(path, values) is False
    assert values == DEFAULTS  # Defaults untouched; nothing partially merged.
    backups = list(tmp_path.glob("settings.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert recovery_backup(path) == (True, backups[0])
    assert "could not be loaded" in caplog.text

    with pytest.raises(ServiceError) as raised:
        SettingsStore(path).save(values)
    assert raised.value.code == RECOVERY_ERROR_CODE
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_settings_service_refuses_saves_in_recovery(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(CORRUPT)
    values = copy.deepcopy(DEFAULTS)
    load_settings_file(path, values)
    service = SettingsService(values, SettingsStore(path), {"launch_app"})
    with pytest.raises(ServiceError) as raised:
        service.apply(SettingsPatch(camera_flipped=True))
    assert raised.value.code == RECOVERY_ERROR_CODE
    assert "camera_flipped" not in values
    assert path.read_text() == CORRUPT


def test_device_persist_refuses_saves_in_recovery(tmp_path):
    from services.device_printers import DevicePrinterService

    path = tmp_path / "settings.json"
    path.write_text(CORRUPT)
    values = copy.deepcopy(DEFAULTS)
    load_settings_file(path, values)
    service = SettingsService(values, SettingsStore(path), set())
    holder = SimpleNamespace(settings=service)
    with pytest.raises(ServiceError) as raised:
        DevicePrinterService.persist(holder, "printers", [{"host": "h"}], lambda item: item["host"])
    assert raised.value.code == RECOVERY_ERROR_CODE
    assert "printers" not in values
    assert path.read_text() == CORRUPT


def test_existing_backup_is_never_overwritten(tmp_path, monkeypatch):
    fixed = datetime(2026, 1, 2, 3, 4, 5)
    monkeypatch.setattr(
        settings_module, "datetime", SimpleNamespace(now=lambda: fixed)
    )
    path = tmp_path / "settings.json"
    existing = tmp_path / "settings.json.corrupt-20260102-030405"
    existing.write_text("earlier backup")
    path.write_text(CORRUPT)
    load_settings_file(path, copy.deepcopy(DEFAULTS))
    assert existing.read_text() == "earlier backup"
    blocked, backup = recovery_backup(path)
    assert blocked and backup != existing and backup.read_text() == CORRUPT


def test_server_load_settings_uses_recovery(tmp_path, monkeypatch):
    import server

    path = tmp_path / "settings.json"
    path.write_text(CORRUPT)
    values = copy.deepcopy(DEFAULTS)
    monkeypatch.setattr(server, "SETTINGS_FILE", str(path))
    monkeypatch.setattr(server, "SETTINGS", values)
    server.load_settings()
    assert values == DEFAULTS
    assert recovery_backup(path)[0]
    assert list(tmp_path.glob("settings.json.corrupt-*"))


# ---------------------------------------------------------------------------
# M9: upload timeout scales with G-code size; tool limit exceeds it
# ---------------------------------------------------------------------------

MIB = 1024 * 1024


def test_upload_timeout_scales_and_caps():
    from devices.printer_protocols import upload_timeout

    assert upload_timeout(0) == 30
    assert upload_timeout(10 * MIB) == pytest.approx(40)
    assert upload_timeout(128 * MIB) == pytest.approx(158)
    assert upload_timeout(10_000 * MIB) == 600


def test_upload_tool_timeout_exceeds_largest_upload_timeout():
    from devices.printer_protocols import MAX_GCODE, upload_timeout
    from services.printing import STAGE_TIMEOUTS

    assert STAGE_TIMEOUTS["upload_gcode"] > upload_timeout(MAX_GCODE)
    assert STAGE_TIMEOUTS["upload_gcode"] > 35  # Old fixed limit always timed out big files.


def test_upload_stage_registered_with_scaled_timeout():
    from services.printing import STAGE_TIMEOUTS, PrintService

    registered = {}
    dispatcher = SimpleNamespace(register=lambda spec: registered.__setitem__(spec.name, spec))
    PrintService(None, None, dispatcher, None, None, slicer=object())
    assert registered["upload_gcode"].execution_timeout == STAGE_TIMEOUTS["upload_gcode"]
    assert registered["slice_stl"].execution_timeout == 340
    assert registered["start_print"].execution_timeout == 35


@pytest.mark.asyncio
async def test_upload_uses_size_scaled_timeout(tmp_path, monkeypatch):
    from devices import printer_protocols
    from devices.printer_protocols import PrinterProtocolClient, upload_timeout

    path = tmp_path / ("a" * 32 + ".gcode")
    path.write_bytes(b"G28\n")
    fake_size = 64 * MIB
    real_stat = type(path).stat

    def stat(self, *args, **kwargs):
        value = real_stat(self, *args, **kwargs)
        if self.name == path.name:
            return SimpleNamespace(st_size=fake_size, st_mode=value.st_mode)
        return value

    monkeypatch.setattr(type(path), "stat", stat)
    used = {}
    real_timeout = asyncio.timeout

    def recording_timeout(delay):
        used.setdefault("asyncio", delay)
        return real_timeout(delay)

    monkeypatch.setattr(printer_protocols.asyncio, "timeout", recording_timeout)

    class Response:
        status = 201

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            return Response()

    def sessions(timeout):
        used["session"] = timeout
        return Session()

    class Form:
        def add_field(self, *args, **kwargs):
            pass

    printer = SimpleNamespace(host="127.0.0.1", port=7125, printer_type="moonraker", api_key=None)
    client = PrinterProtocolClient(sessions=sessions, forms=Form)
    assert await client.upload(printer, path) is True
    expected = upload_timeout(fake_size)
    assert used == {"asyncio": expected, "session": expected}
    assert expected > 30


# ---------------------------------------------------------------------------
# M10: screenshot description: profile model, real failures, single capture
# ---------------------------------------------------------------------------


class FakeModels:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate_content(self, model, contents):
        self.calls.append(model)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.result)


def patch_genai(monkeypatch, models):
    from google import genai

    from services.tls import provider_ssl_context

    def client(api_key, http_options):
        # Key comes from the accessor; HTTPS verifies against the provider TLS context.
        assert api_key == "test-key"
        assert http_options["client_args"]["verify"] is provider_ssl_context()
        return SimpleNamespace(models=models)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("INARA_VISION_MODEL", "profile-vision-model")


def test_describe_uses_vision_profile_model(monkeypatch):
    from desktop.screen_capture import ScreenCapture

    models = FakeModels(result="A code editor.")
    patch_genai(monkeypatch, models)
    result = ScreenCapture().describe_bytes(b"jpeg")
    assert result.success and result.description == "A code editor."
    assert models.calls == ["profile-vision-model"]


@pytest.mark.parametrize(
    "models", [FakeModels(error=RuntimeError("model retired")), FakeModels(result="")]
)
def test_describe_failure_is_not_success(monkeypatch, models):
    from desktop.screen_capture import ScreenCapture

    patch_genai(monkeypatch, models)
    result = ScreenCapture().describe_bytes(b"jpeg")
    assert result.success is False and result.error
    assert result.image == b"jpeg"


def test_describe_without_key_is_failure(monkeypatch):
    from desktop.screen_capture import ScreenCapture

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = ScreenCapture().describe_bytes(b"jpeg")
    assert result.success is False and "GEMINI_API_KEY" in result.error


class CountingCapture:
    def __init__(self, description):
        from desktop.screen_capture import ScreenDescription

        self.captures, self.description, self.cls = 0, description, ScreenDescription

    def capture_and_describe(self, region=None, prompt=None):
        self.captures += 1
        ok, text = self.description
        return self.cls(ok, text, b"one-capture", None if ok else text)

    def capture_to_base64(self, region=None):  # Must not be used: it would capture again.
        raise AssertionError("captured twice")


@pytest.mark.asyncio
@pytest.mark.parametrize("ok", [True, False])
async def test_take_screenshot_captures_once_and_reports_failure(ok):
    import base64

    from agents.desktop_agent import DesktopAgent
    from core.event_bus import EventBus

    agent = DesktopAgent(event_bus=EventBus())
    capture = CountingCapture((ok, "described" if ok else "vision analysis failed"))
    agent._capture = capture
    result = await agent.handle_tool_call("take_screenshot", {})
    assert capture.captures == 1
    assert result.success is ok
    assert result.data["image"] == base64.b64encode(b"one-capture").decode()
    if ok:
        assert result.message == "described"
    else:
        assert "failed" in result.message and result.data["error"]


# ---------------------------------------------------------------------------
# L1: launch_app exact matching, no shell, approval shows resolved command
# ---------------------------------------------------------------------------


def test_launch_resolution_is_exact():
    from desktop.app_registry import AppRegistry, AppResolutionError

    registry = AppRegistry()
    assert registry.resolve("c") is None
    assert registry.resolve("Chrome") == "start chrome"
    assert registry.resolve("  VS Code ") == "code"
    with pytest.raises(AppResolutionError) as raised:
        registry.resolve_target("c")
    assert "Unknown app 'c'" in str(raised.value)
    with pytest.raises(AppResolutionError) as raised:
        registry.resolve_target("chrom")
    assert "chrome" in raised.value.suggestions
    assert "chrome" in str(raised.value)


def test_launch_never_uses_shell(monkeypatch):
    from desktop import app_registry
    from desktop.app_registry import AppRegistry

    calls = []
    monkeypatch.setattr(
        app_registry.subprocess, "Popen", lambda *a, **k: calls.append(("popen", a, k))
    )
    monkeypatch.setattr(
        app_registry.os, "startfile", lambda target: calls.append(("open", target)), raising=False
    )
    monkeypatch.setattr(
        app_registry.shutil, "which", lambda name: None if "/" in name else f"C:/bin/{name}.exe"
    )
    registry = AppRegistry(custom_apps={"My Tool": '"C:/Program Files/Tool/tool.exe" --fast'})

    result = registry.launch("notepad")
    assert result["success"] and calls[-1][0] == "popen"
    assert calls[-1][1][0] == ["C:/bin/notepad.exe"] and calls[-1][2]["shell"] is False

    result = registry.launch("my tool")
    assert calls[-1][1][0] == ["C:/Program Files/Tool/tool.exe", "--fast"]
    assert calls[-1][2]["shell"] is False

    result = registry.launch("c")
    assert not result["success"] and "Unknown app" in result["message"]
    assert len(calls) == 2

    if sys.platform == "win32":
        result = registry.launch("chrome")
        assert calls[-1] == ("open", "chrome")
        assert result["command"] == "open chrome"


@pytest.mark.asyncio
async def test_launch_approval_shows_resolved_command(application_factory):
    app = application_factory()
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.settings["tool_permissions"]["launch_app"] = True
    requested = asyncio.Event()
    captured = {}

    async def emit(name, data, room=None):
        if name == "tool_confirmation_request":
            captured.update(data)
            requested.set()

    app.sio.emit = emit
    expected = app.local_actions.desktop.describe_launch("notepad")
    task = asyncio.create_task(app.local_transport.launch_app("client", {"name": "notepad"}))
    await asyncio.wait_for(requested.wait(), 2)
    assert captured["args"] == {"name": "notepad", "will_run": expected}
    assert "notepad" in expected.lower()
    assert app.dispatcher.resolve("owner", captured["id"], False)
    await task


@pytest.mark.asyncio
async def test_unknown_app_rejected_before_approval(application_factory):
    from unittest.mock import AsyncMock

    app = application_factory()
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.settings["tool_permissions"]["launch_app"] = True
    app.sio.emit = AsyncMock()
    await app.local_transport.launch_app("client", {"name": "c"})
    events = [call.args[0] for call in app.sio.emit.await_args_list]
    assert "tool_confirmation_request" not in events
    payload = app.sio.emit.await_args.args[1]
    assert payload["code"] == "app_not_found"
    assert not app.dispatcher.pending


# ---------------------------------------------------------------------------
# L2: ProjectManager refuses names that resolve to the projects root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "!!!", "/"])
def test_switch_project_rejects_root_names(tmp_path, name):
    from project_manager import ProjectManager

    manager = ProjectManager(str(tmp_path))
    ok, message = manager.switch_project(name)
    assert ok is False and "letter or number" in message
    assert manager.current_project == "temp"
    assert manager.get_current_project_path() != manager.projects_dir


def test_switch_project_still_switches_to_real_project(tmp_path):
    from project_manager import ProjectManager

    manager = ProjectManager(str(tmp_path))
    manager.create_project("Desk Lamp")
    assert manager.switch_project(" Desk Lamp ")[0] is True
    assert manager.current_project == "Desk Lamp"
