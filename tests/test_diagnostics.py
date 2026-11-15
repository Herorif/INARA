"""S4.2 diagnostics export: zip layout, redaction, folder default and the owner-only route.

Never the real AppData or the real logs: every log and output folder is under tmp_path.
"""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import zipfile

import pytest
from pydantic import ValidationError

from services import diagnostics
from services.diagnostics import (
    LOG_LINES,
    REMOVED,
    DiagnosticsService,
    default_folder,
    dev_checkout,
    export_folder,
    read_logs,
    redact_settings,
    scrub,
    secret_key,
)
from services.settings import SettingsPatch

NAMES = {
    "log.txt", "turn_timing.txt", "settings.json", "keys.json", "versions.json",
    "sidecars.json", "audio.json", "traces.json",
}
ANTHROPIC = "sk-ant-api03-" + "Zx9" * 20
GOOGLE = "AIzaSyD" + "q7" * 16
GOOGLE_AQ = "AQ.Ab8RN6" + "k3" * 12
BEARER = "c2VjcmV0dG9rZW5fdmFsdWU"
EMAIL = "owner.person@example.com"
OPAQUE = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
OWNER = "Aisyah Rahman"
PLACE = "Shah Alam, Selangor"
PHONE = "+60 12-345 6789"
STORED = "sk-ant-api03-" + "Stored9" * 8
TRACE_TEXT = "please remind me about the dentist"


def settings():
    return {
        "face_auth_enabled": False,
        "tool_permissions": {},
        "briefing": {"enabled": False},
        "world": {"enabled": False},
        "assistant": {
            "owner_name": OWNER, "address": "name",
            "home_place": {"name": PLACE, "lat": 3.07, "lon": 101.52},
        },
        "calls": {"facts": f"{OWNER} lives in Shah Alam. Call {PHONE}.", "enabled": False},
        "home_assistant": {"url": "http://192.168.1.20:8123", "token": "legacy-plain-token-value"},
        "mobile": {"pairing_pin": "482913", "session_cookie": "c0okie-value", "vip": ["0123456789"]},
        "custom": {"apiKey": "plain-api-key-value", "Authorization": "Basic dXNlcjpwYXNz",
                   "note": f"mail {EMAIL} or ring 012 345 6789"},
        "diagnostics": {"include_text": False},
    }


def write_logs(directory, current, previous=()):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "jarvis.log").write_text("\n".join(current) + "\n", encoding="utf-8")
    if previous:
        (directory / "jarvis.log.1").write_text("\n".join(previous) + "\n", encoding="utf-8")


def line(index, message="jarvis.services.voice: tick"):
    return f"2026-11-15 10:00:{index % 60:02d},000 INFO {message} {index}"


@pytest.fixture
def exported(application_factory, tmp_path):
    """An app with planted secrets in its settings, logs and key store; run ``export()``."""
    app = application_factory(settings=settings())
    app.sessions.principals.update({"client": "owner", "tray": "owner", "second": "other"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "second": "renderer"})
    app.sessions.local_owner = "owner"
    app.secrets.set("anthropic_api_key", STORED)
    app.audio_devices.report = AsyncMock(return_value={
        "available": True, "host_api": "Windows WASAPI",
        "inputs": [{"name": "Microphone (Aisyah Rahman's Headset)"}],
        "outputs": [{"name": "Speakers (Realtek)"}],
    })
    logs = tmp_path / "fake-appdata" / "logs"
    write_logs(logs, [
        line(1),
        line(2, f"jarvis.services.conversation: turn_timing request_id=r1 key={ANTHROPIC}"),
        line(3, f"jarvis.llm: got {GOOGLE} and {GOOGLE_AQ}"),
        line(4, f"jarvis.http: Authorization: Bearer {BEARER} for {EMAIL}"),
        line(5, f"jarvis.services.brain_check: brain_check provider=claude digest={OPAQUE}"),
        line(6, "jarvis.trace: id 3f2a1b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b kept"),
    ])
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    app.diagnostics = DiagnosticsService(
        app, root=repo, home=tmp_path / "home", log_dir=logs,
        clock=lambda: datetime(2026, 11, 15, 9, 30, 5),
    )
    return app, repo


def unzip(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


async def test_the_zip_has_every_part_and_its_name(exported):
    app, repo = exported
    result = await app.diagnostics.export("owner")
    assert result["ok"] is True
    path = Path(result["path"])
    assert path == repo / ".runtime" / "live-logs" / "diagnostics-20261115-093005.zip"
    files = unzip(path)
    assert set(files) == NAMES
    keys = json.loads(files["keys.json"])
    assert {"name": "anthropic_api_key", "configured": True} in keys
    assert all(set(item) == {"name", "configured"} for item in keys)
    assert any(item["configured"] is False for item in keys)
    versions = json.loads(files["versions.json"])
    assert versions["app"] == "9.9.9" and versions["python"] and versions["dev_checkout"] is True
    assert set(versions["packages"]) == {"anthropic", "google-genai", "httpx", "websockets"}
    sidecars = json.loads(files["sidecars.json"])
    assert set(sidecars) == {"world_view", "mcp_servers", "cad_kernel", "wake_word", "voice"}
    assert sidecars["cad_kernel"] in {"available", "unavailable", "running", "unknown"}
    assert sidecars["voice"] == "off"
    audio = json.loads(files["audio.json"])
    assert audio["outputs"] == ["Speakers (Realtek)"] and audio["chosen_input"] == "default"
    assert "turn_timing request_id=r1" in files["turn_timing.txt"]
    assert "brain_check provider=claude" in files["turn_timing.txt"]
    assert "tick 1" not in files["turn_timing.txt"]
    # A second export in the same second gets its own name.
    again = await app.diagnostics.export("owner")
    assert Path(again["path"]).name == "diagnostics-20261115-093005-1.zip"
    assert not list(path.parent.glob("*.tmp"))


async def test_no_secret_or_personal_value_reaches_any_file(exported):
    app, _ = exported
    files = unzip((await app.diagnostics.export("owner"))["path"])
    everything = "\n".join(files.values())
    for planted in (
        ANTHROPIC, GOOGLE, GOOGLE_AQ, BEARER, EMAIL, OPAQUE, STORED, STORED[-4:] + '"',
        OWNER, "Aisyah", "Rahman", "Shah Alam", "Selangor", "3.07", "101.52",
        "12-345 6789", "012 345 6789", "0123456789", "482913", "c0okie-value",
        "legacy-plain-token-value", "plain-api-key-value", "dXNlcjpwYXNz",
    ):
        assert planted not in everything, planted
    saved = json.loads(files["settings.json"])
    assert saved["assistant"]["owner_name"] == REMOVED
    assert saved["assistant"]["home_place"] == REMOVED
    assert saved["assistant"]["address"] == "name"
    assert saved["home_assistant"] == {"url": "http://192.168.1.20:8123", "token": REMOVED}
    assert saved["face_auth_enabled"] is False  # a bool is never secret
    assert saved["mobile"]["pairing_pin"] == REMOVED
    assert saved["calls"]["facts"] == REMOVED
    assert "Bearer [removed]" in files["log.txt"]
    # Trace ids (UUIDs) stay readable.
    assert "3f2a1b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b" in files["log.txt"]


async def test_traces_keep_text_only_while_include_text_is_on(exported):
    app, _ = exported
    app.trace.traces["t1"] = {
        "id": "t1", "origin": "chat", "spans": [], "approvals": [], "tokens": {},
        "request_text": TRACE_TEXT, "answer_text": "Done.",
    }
    app.trace._meta["t1"] = ("owner", 0.0)
    files = unzip((await app.diagnostics.export("owner"))["path"])
    traces = json.loads(files["traces.json"])
    assert [item["id"] for item in traces] == ["t1"]
    assert TRACE_TEXT not in files["traces.json"] and "request_text" not in traces[0]
    app.settings["diagnostics"] = {"include_text": True}
    files = unzip((await app.diagnostics.export("owner"))["path"])
    assert json.loads(files["traces.json"])[0]["request_text"] == TRACE_TEXT


async def test_at_most_twenty_traces(exported):
    app, _ = exported
    for index in range(25):
        key = f"t{index}"
        app.trace.traces[key] = {"id": key, "spans": [], "approvals": [], "tokens": {}}
        app.trace._meta[key] = ("owner", 0.0)
    files = unzip((await app.diagnostics.export("owner"))["path"])
    assert len(json.loads(files["traces.json"])) == 20


def test_logs_are_capped_at_2000_lines_from_the_current_then_the_previous_file(tmp_path):
    folder = tmp_path / "logs"
    write_logs(folder, [line(i, "jarvis.x: current") for i in range(1500)],
               [line(i, "jarvis.x: previous") for i in range(1000)]
               + [line(9, "jarvis.c: turn_timing old")])
    lines, timing = read_logs(folder)
    assert len(lines) == LOG_LINES == 2000
    assert lines[-1].endswith("current 1499")
    assert sum("previous" in item for item in lines) == 499
    assert timing == [line(9, "jarvis.c: turn_timing old")]
    write_logs(folder, [line(i) for i in range(2500)])
    lines, _ = read_logs(folder)
    assert len(lines) == 2000 and lines[0].endswith(" 500")
    assert read_logs(tmp_path / "missing") == ([], [])


def test_the_default_folder_in_a_dev_checkout_and_outside_one(tmp_path):
    checkout, pilot, home = tmp_path / "checkout", tmp_path / "pilot", tmp_path / "home"
    checkout.mkdir()
    pilot.mkdir()
    (pilot / "desktop-pilot.json").write_text("{}", encoding="utf-8")
    assert dev_checkout(checkout) is True and dev_checkout(pilot) is False
    assert default_folder(checkout, home) == checkout / ".runtime" / "live-logs"
    assert default_folder(pilot, home) == home / "Documents" / "JARVIS diagnostics"
    chosen = str(tmp_path / "chosen")
    assert export_folder({"diagnostics": {"folder": chosen}}, pilot, home) == Path(chosen)
    assert export_folder({"diagnostics": {"folder": 5}}, pilot, home) == default_folder(pilot, home)


def test_the_folder_setting_validates():
    assert SettingsPatch.model_validate(
        {"diagnostics": {"folder": "C:\\Users\\me\\Diagnostics"}}).diagnostics.folder
    assert SettingsPatch.model_validate({"diagnostics": {"folder": ""}}).diagnostics.folder == ""
    for bad in ("relative\\folder", None, 3, "C:\\a|b", "C:\\" + "x" * 300):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"diagnostics": {"folder": bad}})


def test_secret_like_key_names():
    for name in ("api_key", "apiKey", "session_token", "authToken", "Authorization",
                 "password", "pairing_pin", "pin", "cookie", "client_secret", "face_auth_enabled"):
        assert secret_key(name), name
    for name in ("owner_name", "address", "enabled", "url", "mapping", "typing", "tool_permissions"):
        assert not secret_key(name), name


def test_the_redaction_pass_counts_what_it_removes():
    text = (f"a {ANTHROPIC} b {GOOGLE} c {GOOGLE_AQ} d bearer {BEARER} e {EMAIL} f {OPAQUE} "
            "g 3f2a1b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b h long_snake_case_identifier_without_digits")
    cleaned, count = scrub(text)
    assert count == 6
    for planted in (ANTHROPIC, GOOGLE, GOOGLE_AQ, BEARER, EMAIL, OPAQUE):
        assert planted not in cleaned
    assert "3f2a1b4c-5d6e-4f70-8a9b-0c1d2e3f4a5b" in cleaned
    assert "long_snake_case_identifier_without_digits" in cleaned
    assert scrub(cleaned) == (cleaned, 0)


def test_settings_redaction_leaves_dates_and_times():
    saved = redact_settings({"calls": {"quiet_hours": {"start": "21:00", "end": "09:00"}},
                             "stamp": "2026-11-15", "assistant": {"owner_name": ""}})
    assert saved == {"calls": {"quiet_hours": {"start": "21:00", "end": "09:00"}},
                     "stamp": "2026-11-15", "assistant": {"owner_name": ""}}


async def test_a_failed_export_says_so_without_details(exported, monkeypatch):
    app, _ = exported

    def broken(*args):
        raise PermissionError(f"denied {ANTHROPIC}")

    monkeypatch.setattr(diagnostics, "write_zip", broken)
    result = await app.diagnostics.export("owner")
    assert result == {"ok": False, "code": "diagnostics_failed",
                      "message": diagnostics.EXPORT_FAILED}


async def test_the_route_is_owner_only(exported):
    app, repo = exported
    handler = app.sio.handlers["/"]["diagnostics_export"]
    for sid, code in (("unknown", "authentication_required"),
                      ("tray", "authentication_required"),
                      ("second", "permission_denied")):
        result = await handler(sid, {})
        assert result["ok"] is False and result["code"] == code, (sid, result)
    assert not (repo / ".runtime").exists()
    assert (await handler("client", {"extra": 1}))["code"] == "invalid_arguments"
    result = await handler("client", {})
    assert result["ok"] is True and Path(result["path"]).is_file()
    assert (await handler("client"))["ok"] is True
    app.settings["face_auth_enabled"] = True
    assert (await handler("client", {}))["code"] == "authentication_required"


def test_the_route_is_in_the_route_policy_matrix():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text()
    )
    assert matrix["socket_routes"]["diagnostics_export"]["status"] == "implemented"


# --- the tray ------------------------------------------------------------------------------


def test_the_tray_menu_offers_export_diagnostics():
    from resident.win32 import Tray

    items = Tray.menu_items(SimpleNamespace(talking=False, wake_word=False))
    assert ("diagnostics", "Export diagnostics") in items


def tray_host(result=None, phase="ready"):
    from resident.host import NativeHost

    notices = []
    host = NativeHost.__new__(NativeHost)
    host.state = SimpleNamespace(phase=phase, identity=SimpleNamespace(owner="owner"))
    host.tray = SimpleNamespace(notify=lambda title, text: notices.append((title, text)) or True,
                                post=lambda callback: callback())
    host.loop = None
    host.runtime = SimpleNamespace(runtime=SimpleNamespace(diagnostics=SimpleNamespace(
        export=AsyncMock(return_value=result))))
    return host, notices


def test_the_tray_balloon_names_the_folder_or_the_problem(tmp_path):
    folder = tmp_path / "out"
    host, notices = tray_host()
    assert host.show_diagnostics({"ok": True, "path": str(folder / "diagnostics-1.zip")})
    assert notices[-1] == ("JARVIS diagnostics", f"Saved to {folder}")
    host.show_diagnostics({"ok": False, "message": "Diagnostics couldn't be saved."})
    assert notices[-1] == ("JARVIS diagnostics", "Diagnostics couldn't be saved.")
    host.show_diagnostics({"ok": False})
    assert notices[-1][1].startswith("Diagnostics couldn't be saved")


def test_the_tray_export_waits_for_the_core(tmp_path):
    host, notices = tray_host(phase="starting")
    assert host.export_diagnostics() is None
    assert notices == [("JARVIS diagnostics", "JARVIS is still starting. Try again in a moment.")]


def test_the_tray_export_runs_on_the_core_loop_and_shows_the_result(tmp_path):
    import asyncio
    import threading

    path = str(tmp_path / "diagnostics-x.zip")
    host, notices = tray_host({"ok": True, "path": path})
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        host.loop = loop
        done = threading.Event()
        host.tray.post = lambda callback: (callback(), done.set())
        future = host.export_diagnostics()
        assert future.result(5) == {"ok": True, "path": path}
        assert done.wait(5)
        host.runtime.runtime.diagnostics.export.assert_awaited_once_with("owner")
        assert notices == [("JARVIS diagnostics", f"Saved to {tmp_path}")]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
