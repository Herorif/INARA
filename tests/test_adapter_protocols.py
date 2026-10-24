"""Injected network protocols and local readiness only; no physical-device traffic."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from devices.printer_models import Printer, PrinterType
from devices.printer_protocols import PrinterProtocolClient, MAX_JSON, MAX_GCODE
from devices.printer_discovery import discover_printers, PrinterDiscoveryListener
from devices.kasa import KasaController
from tests.test_workspace_policy import workspace as workspace_fixture


@pytest.fixture
def app(application_factory):
    return workspace_fixture.__wrapped__(application_factory)


def printer(kind="moonraker", **extra):
    return Printer("Fixture", "printer.test", 7125, PrinterType(kind), **extra)


class Response:
    def __init__(self, data=None, status=200, raw=None):
        self.status, self.closed = status, False
        self.raw = raw if raw is not None else json.dumps(data or {}).encode()
        self.offset = 0
        self.content = self

    async def read(self, size):
        value = self.raw[self.offset : self.offset + min(size, 4096)]
        self.offset += len(value)
        return value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True


class Form:
    def __init__(self):
        self.fields = []

    def add_field(self, *args, **kwargs):
        self.fields.append((args, kwargs))


def client(responses):
    requests = []
    sessions = []

    class Session:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        def request(self, method, url, **kw):
            requests.append((method, url, kw))
            return responses.pop(0)

        def get(self, url, **kw):
            return self.request("GET", url, **kw)

        def post(self, url, **kw):
            return self.request("POST", url, **kw)

    def factory(timeout):
        session = Session()
        session.timeout = timeout
        sessions.append(session)
        return session

    return PrinterProtocolClient(factory, Form), requests, sessions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,route", [("moonraker", "/server/files/upload"), ("octoprint", "/api/files/local")]
)
async def test_upload_is_one_exact_request_without_physical_start(tmp_path, kind, route):
    path = tmp_path / ("a" * 32 + ".gcode")
    path.write_text("; fixture")
    api, calls, sessions = client([Response(status=201)])
    assert await api.upload(printer(kind, api_key="fixture-secret"), path)
    assert len(calls) == 1 and calls[0][:2] == ("POST", "http://printer.test:7125" + route)
    request = calls[0][2]
    assert request["allow_redirects"] is False and request["headers"] == {
        "X-Api-Key": "fixture-secret"
    }
    assert [field[0][0] for field in request["data"].fields] == (
        ["file", "root"] if kind == "moonraker" else ["file"]
    )
    assert request["data"].fields[0][0][1].closed and sessions[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 401, 404, 500])
async def test_upload_failures_never_fall_back_retry_or_start(tmp_path, status):
    path = tmp_path / ("b" * 32 + ".gcode")
    path.write_text("; fixture")
    api, calls, sessions = client([Response(status=status)])
    assert not await api.upload(printer(), path)
    assert len(calls) == 1 and sessions[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["file.gcode", "../unsafe.gcode", "A" * 32 + ".gcode"])
async def test_upload_rejects_non_generated_names(tmp_path, name):
    api, calls, _ = client([])
    assert not await api.upload(printer(), tmp_path / name)
    assert calls == []


@pytest.mark.asyncio
async def test_upload_size_limit_and_unknown_protocol_do_not_open_session(tmp_path):
    path = tmp_path / ("a" * 32 + ".gcode")
    with path.open("wb") as stream:
        stream.truncate(MAX_GCODE + 1)
    api, calls, _ = client([])
    assert not await api.upload(printer(), path)
    path.write_text("; fixture")
    assert not await api.upload(printer("unknown"), path)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,route,payload",
    [
        ("moonraker", "/printer/print/start", {"filename": "a" * 32 + ".gcode"}),
        (
            "octoprint",
            "/api/files/local/" + "a" * 32 + ".gcode",
            {"command": "select", "print": True},
        ),
    ],
)
async def test_start_is_a_separate_exact_nonredirecting_request(kind, route, payload):
    api, calls, sessions = client([Response(status=204)])
    assert await api.start(printer(kind), "a" * 32 + ".gcode")
    assert calls == [
        (
            "POST",
            "http://printer.test:7125" + route,
            {"json": payload, "headers": {}, "allow_redirects": False},
        )
    ]
    assert sessions[0].closed
    assert not await api.start(printer(kind), "../unsafe.gcode") and len(calls) == 1


def moon(**changes):
    stats = {"state": "printing", "filename": "fixture.gcode", "print_duration": 65, **changes}
    return {
        "result": {
            "status": {
                "print_stats": stats,
                "display_status": {"progress": 0.4},
                "extruder": {"temperature": 201, "target": 210},
                "heater_bed": {"temperature": 59, "target": 60},
            }
        }
    }


@pytest.mark.asyncio
async def test_moonraker_status_whitelist_numeric_conversion_and_auth():
    api, calls, sessions = client([Response(moon())])
    value = await api.status(printer(api_key="fixture"))
    assert value.progress_percent == 40 and value.time_elapsed == "00:01:05"
    assert value.temperatures["hotend"] == {"current": 201, "target": 210}
    assert (
        len(calls) == 1
        and calls[0][2]["headers"] == {"X-Api-Key": "fixture"}
        and sessions[0].closed
    )


@pytest.mark.asyncio
async def test_octoprint_status_uses_exact_job_and_temperature_endpoints():
    api, calls, sessions = client(
        [
            Response(
                {
                    "state": "Printing",
                    "progress": {"completion": 35, "printTime": 120, "printTimeLeft": 60},
                    "job": {"file": {"name": "fixture.gcode"}},
                }
            ),
            Response({"temperature": {"tool0": {"actual": 200, "target": 210}}}),
        ]
    )
    value = await api.status(printer("octoprint"))
    assert (
        value.state == "printing"
        and value.progress_percent == 35
        and value.time_remaining == "00:01:00"
    )
    assert [call[1] for call in calls] == [
        "http://printer.test:7125/api/job",
        "http://printer.test:7125/api/printer",
    ]
    assert sessions[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        Response(status=401),
        Response(status=302),
        Response(raw=b"x" * (MAX_JSON + 1)),
        Response(raw=b"not json"),
        Response(moon(print_duration=float("nan"))),
        Response(moon(state=None)),
        Response({}),
    ],
)
async def test_invalid_status_is_not_reported_online(response):
    api, calls, sessions = client([response])
    with pytest.raises(Exception):
        await api.status(printer())
    assert len(calls) == 1 and sessions[0].closed and response.closed


@pytest.mark.asyncio
async def test_chunked_status_can_exceed_one_read_without_truncation():
    data = moon()
    data["ignored"] = "x" * 9000
    api, _, _ = client([Response(data)])
    assert (await api.status(printer())).state == "printing"


@pytest.mark.asyncio
async def test_status_cancel_releases_response_and_session():
    entered = asyncio.Event()
    response = Response()

    async def hang(size):
        entered.set()
        await asyncio.Event().wait()

    response.read = hang
    api, _, sessions = client([response])
    task = asyncio.create_task(api.status(printer()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert response.closed and sessions[0].closed


@pytest.fixture
def facade(tmp_path, monkeypatch):
    from printer_agent import PrinterAgent

    monkeypatch.setattr(PrinterAgent, "_detect_slicer_path", lambda self: None)
    monkeypatch.setattr(PrinterAgent, "_detect_orca_profiles_dir", lambda self: None)
    return PrinterAgent(profiles_dir=str(tmp_path / "profiles"))


def test_facade_preserves_same_host_distinct_ports_and_masks_keys(facade):
    first = facade.add_printer_manually("First", "printer.test", 80, "octoprint", api_key="secret")
    second = facade.add_printer_manually("Second", "printer.test", 7125, "moonraker")
    assert len(facade.printers) == 2 and facade._resolve_printer("printer.test") is None
    assert (
        facade._resolve_printer("printer.test:80") is first
        and facade._resolve_printer("printer.test:7125") is second
    )
    replacement = facade.add_printer_manually("Renamed", "printer.test", 80, "octoprint")
    assert replacement.api_key == "secret" and len(facade.printers) == 2
    facade._record_status_failure(first, "fixture")
    assert not facade.should_poll_printer("printer.test:80")
    assert facade.should_poll_printer("printer.test:7125")
    assert (
        "secret" not in json.dumps(facade.get_printer_list()) and "api_key" not in first.to_dict()
    )


@pytest.mark.asyncio
async def test_facade_legacy_combined_upload_start_fails_before_network(facade):
    facade.add_printer_manually("First", "printer.test", 80, "octoprint")
    facade.add_printer_manually("Unknown", "unknown.test", 80, "unknown")
    assert not facade.should_poll_printer("unknown.test")
    facade.protocol = SimpleNamespace(upload=AsyncMock())
    assert not await facade.upload_gcode("First", "unused.gcode", start_print=True)
    facade.protocol.upload.assert_not_called()


@pytest.mark.asyncio
async def test_facade_protocol_failure_preserves_backoff_and_sanitizes_details(facade):
    facade.add_printer_manually("First", "printer.test", 80, "octoprint")
    facade.protocol = SimpleNamespace(status=AsyncMock(side_effect=RuntimeError("SECRET")))
    value = await facade.get_print_status("First")
    assert value.state == "offline" and "SECRET" not in value.details
    assert not facade.should_poll_printer("printer.test:80")
    assert facade._status_failures["printer.test:80"] == 1


@pytest.mark.asyncio
async def test_discovery_never_replaces_saved_endpoint_or_acquires_camera(facade, monkeypatch):
    saved = facade.add_printer_manually(
        "Saved", "printer.test", 7125, "moonraker", api_key="fixture"
    )
    discover = AsyncMock(return_value=[printer("octoprint")])
    monkeypatch.setattr("devices.printer_discovery.discover_printers", discover)
    await facade.discover_printers()
    assert facade._resolve_printer("Saved") is saved and saved.camera_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel,fail", [(False, False), (True, False), (False, True)])
async def test_mdns_browser_and_zeroconf_close_on_success_cancel_and_setup_error(cancel, fail):
    zc = SimpleNamespace(close=Mock())
    browsers = []
    entered = asyncio.Event()

    def browse(*args):
        if fail and len(browsers) == 2:
            raise RuntimeError("fixture")
        browser = SimpleNamespace(cancel=Mock())
        browsers.append(browser)
        entered.set()
        return browser

    task = asyncio.create_task(
        discover_printers(0.01 if not cancel else 5, factories=lambda: (lambda: zc, browse))
    )
    if cancel:
        await entered.wait()
        task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], BaseException) if cancel or fail else result == [[]]
    assert all(browser.cancel.call_count == 1 for browser in browsers) and zc.close.call_count == 1


def test_mdns_uses_only_advertised_protocols_and_valid_endpoints():
    listener = PrinterDiscoveryListener()
    info = SimpleNamespace(parsed_addresses=lambda: ["10.0.0.8"], server=None, port=7125)
    zc = SimpleNamespace(get_service_info=lambda *a: info)
    listener.add_service(zc, "_http._tcp.local.", "Fixture._http._tcp.local.")
    assert (
        listener.printers[0].printer_type == PrinterType.UNKNOWN
        and listener.printers[0].camera_url is None
    )
    info.port = 70000
    listener.add_service(zc, "_moonraker._tcp.local.", "Bad")
    assert len(listener.printers) == 1


def device():
    return SimpleNamespace(
        alias="Fixture lamp",
        model="KL-fixture",
        is_on=False,
        is_bulb=True,
        is_plug=False,
        is_strip=False,
        is_dimmer=False,
        is_color=True,
        is_dimmable=True,
        brightness=50,
        hsv=(180, 100, 50),
        update=AsyncMock(),
        turn_on=AsyncMock(),
        turn_off=AsyncMock(),
        set_brightness=AsyncMock(),
        set_hsv=AsyncMock(),
        disconnect=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_kasa_is_lazy_preserves_missing_saved_targets_and_closes_sdk_handles():
    current = device()
    sdk = SimpleNamespace(
        discover=AsyncMock(return_value={"10.0.0.2": current}), discover_single=AsyncMock()
    )
    controller = KasaController(
        [{"ip": "10.0.0.1", "alias": "Offline", "model": "Fixture"}], lambda: sdk
    )
    sdk.discover.assert_not_called()
    assert controller.snapshot()[0]["online"] is False
    values = await controller.discover_devices()
    assert len(values) == 2 and sum(item["online"] for item in values) == 1
    assert values[1]["hsv"] == {"h": 180, "s": 100, "v": 50}
    current.disconnect.assert_awaited_once()
    assert await controller.turn_on("10.0.0.2")
    assert current.disconnect.await_count == 2
    assert not await controller.turn_on("10.0.0.99")
    sdk.discover_single.assert_not_called()


@pytest.mark.asyncio
async def test_kasa_update_failure_does_not_mark_saved_device_online():
    current = device()
    current.update.side_effect = RuntimeError("private credential")
    sdk = SimpleNamespace(discover=AsyncMock(return_value={"10.0.0.2": current}))
    controller = KasaController([{"ip": "10.0.0.2", "alias": "Saved"}], lambda: sdk)
    result = await controller.discover_devices()
    assert result[0]["online"] is False and result[0]["observed_at"] is None
    current.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_kasa_cancel_releases_handle_without_retry():
    current = device()
    entered = asyncio.Event()

    async def hang():
        entered.set()
        await asyncio.Event().wait()

    current.update.side_effect = hang
    sdk = SimpleNamespace(discover=AsyncMock(return_value={"10.0.0.2": current}))
    controller = KasaController(discover_factory=lambda: sdk)
    task = asyncio.create_task(controller.discover_devices())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    current.disconnect.assert_awaited_once()
    sdk.discover.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, -1, 101, "50"])
async def test_kasa_controls_validate_before_sdk_call(value):
    current = device()
    controller = KasaController()
    controller.devices["10.0.0.2"] = current
    assert not await controller.set_brightness("10.0.0.2", value)
    current.set_brightness.assert_not_called()


def test_readiness_uses_local_metadata_without_loading_adapters_or_secrets(app):
    app.settings["kasa_devices"] = [{"ip": "SECRET-ADDRESS", "alias": "PRIVATE"}]
    app.settings["printers"] = [{"host": "PRIVATE-HOST", "api_key": "SECRET-KEY"}]
    app.connections.package_probe = lambda name: True
    report = app.connections.snapshot()
    assert all(item["state"] == "unverified" and not item["loaded"] for item in report["cards"])
    assert app.kasa.instance is None and app.printer.instance is None
    assert (
        not report["network_used"]
        and not report["physical_verified"]
        and not report["slicer_inspected"]
    )
    assert not any(
        value in json.dumps(report)
        for value in ("SECRET-ADDRESS", "PRIVATE-HOST", "SECRET-KEY", "PRIVATE")
    )


def test_readiness_reports_missing_dependencies_and_cached_observations(app):
    app.connections.package_probe = lambda name: False
    assert all(
        item["state"] == "missing_dependency" for item in app.connections.snapshot()["cards"]
    )
    app.connections.package_probe = lambda name: True
    app.kasa.instance = SimpleNamespace(observations={"fixture": {"observed_at": 123}})
    app.printer.instance = SimpleNamespace(
        _last_status={"fixture": SimpleNamespace(state="printing")}, slicer_path="private-path"
    )
    report = app.connections.snapshot()
    assert all(
        item["state"] == "observed" and item["observed_count"] == 1 for item in report["cards"]
    )
    assert report["slicer_available"] and "private-path" not in json.dumps(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["unknown", "other", "tray", "control"])
async def test_readiness_requires_owner_renderer(app, sid):
    assert not (await app.sio.handlers["/"]["connections_state"](sid, {}))["ok"]
    assert app.kasa.instance is None and app.printer.instance is None


@pytest.mark.asyncio
async def test_locked_or_malformed_readiness_request_rejected(app):
    handler = app.sio.handlers["/"]["connections_state"]
    assert not (await handler("client", {"scan": True}))["ok"]
    app.settings["face_auth_enabled"] = True
    assert not (await handler("client", {}))["ok"]


@pytest.mark.asyncio
async def test_ambiguous_kasa_alias_never_selects_a_physical_target():
    first, second = device(), device()
    controller = KasaController()
    for ip, item in (("10.0.0.1", first), ("10.0.0.2", second)):
        controller.devices[ip] = item
        controller.remember(ip, item)
    assert not await controller.turn_on("Fixture lamp")
    first.turn_on.assert_not_called()
    second.turn_on.assert_not_called()
    assert await controller.turn_on("10.0.0.2")
    second.turn_on.assert_awaited_once()


@pytest.mark.parametrize(
    "address", ["printer.test", "8.8.8.8", "127.0.0.1", "0.0.0.0", "224.0.0.1", "::1", "192.0.2.1"]
)
def test_mdns_rejects_external_dns_loopback_and_special_advertisements(address):
    listener = PrinterDiscoveryListener()
    info = SimpleNamespace(
        parsed_addresses=lambda: [address], server="external.example.com", port=80
    )
    listener.add_service(
        SimpleNamespace(get_service_info=lambda *args: info), "_moonraker._tcp.local.", "Untrusted"
    )
    assert listener.printers == []


def test_saved_printer_activation_preserves_credentials_without_network(app):
    from services.lazy import LazyService

    adapter = SimpleNamespace(add_printer_manually=Mock())
    lazy = LazyService("unused-fixture")

    def activate():
        lazy.instance = adapter
        return adapter

    lazy.get = activate
    app.compat_service.printer = lazy
    app.settings["printers"] = [
        {
            "host": "printer.test",
            "port": 7125,
            "name": "Saved",
            "type": "moonraker",
            "api_key": "fixture-secret",
        }
    ]
    assert app.compat_service.activate_printer() is lazy
    adapter.add_printer_manually.assert_called_once_with(
        "Saved",
        "printer.test",
        port=7125,
        printer_type="moonraker",
        camera_url=None,
        api_key="fixture-secret",
    )
