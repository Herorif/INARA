"""Device/printer compatibility policies with isolated adapters; never a network scan."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid
import pytest
from pydantic import ValidationError
from services.device_contracts import AddPrinter, KasaControl
from services.tools import ServiceError


VALID = {
    "discover_kasa": {},
    "control_kasa": {"ip": "10.0.0.25", "action": "on"},
    "discover_printers": {},
    "add_printer": {"host": "10.0.0.42:7125", "name": "Test Printer"},
    "get_slicer_profiles": {},
}


@pytest.fixture
def devices(application_factory):
    app = application_factory()
    owner = str(uuid.uuid4())
    for sid, principal, role in (
        ("ui", owner, "renderer"),
        ("tray", owner, "resident"),
        ("control", owner, "workspace"),
        ("foreign", str(uuid.uuid4()), "renderer"),
    ):
        app.sessions.accept(sid, {"client_id": principal, "role": role})
    app.compat_service.kasa = SimpleNamespace(
        devices={"10.0.0.25": object()},
        discover_devices=AsyncMock(
            return_value=[{"ip": "10.0.0.25", "alias": "Desk Lamp", "model": "KP125"}]
        ),
        turn_on=AsyncMock(return_value=True),
        turn_off=AsyncMock(return_value=True),
        set_brightness=AsyncMock(return_value=True),
        set_color=AsyncMock(return_value=True),
    )
    app.compat_service.printer = SimpleNamespace(
        printers={},
        discover_printers=AsyncMock(return_value=[{}]),
        get_printer_list=lambda: [{"name": "Test Printer"}],
        get_slicer_status=lambda: {"available": False},
        get_available_profiles=lambda: {"machines": []},
        add_printer_manually=Mock(),
    )
    app.compat_service.start_monitor = Mock()
    app.settings_service.store.save = Mock()
    app.settings["tool_permissions"].update({name: False for name in VALID})
    app.settings["tool_permissions"]["control_device"] = False
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign"])
async def test_setup_routes_require_owner_renderer(devices, name, sid):
    await devices.sio.handlers["/"][name](sid, VALID[name])
    assert devices.sio.emit.await_args.args[1]["code"] in (
        "permission_denied",
        "authentication_required",
    )
    devices.compat_service.kasa.discover_devices.assert_not_called()
    devices.compat_service.printer.discover_printers.assert_not_called()
    devices.settings_service.store.save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VALID)
async def test_shared_policy_deny_blocks_before_adapter(devices, name):
    permission = "control_device" if name == "control_kasa" else name
    devices.settings["tool_permissions"][permission] = "deny"
    await devices.sio.handlers["/"][name]("ui", VALID[name])
    assert devices.sio.emit.await_args.args[1]["code"] == "permission_denied"
    with pytest.raises(ServiceError):
        await devices.dispatcher.dispatch(
            devices.sessions.local_owner, name, VALID[name], devices.sessions.context("ui").tools()
        )
    devices.settings_service.store.save.assert_not_called()
    devices.compat_service.kasa.turn_on.assert_not_called()


@pytest.mark.asyncio
async def test_discovery_merges_configuration_and_scopes_events(devices):
    devices.settings["kasa_devices"] = [
        {"ip": "10.0.0.9", "alias": "Offline", "model": "keep", "custom": True}
    ]
    await devices.compat_transport.discover_kasa("ui")
    assert len(devices.settings["kasa_devices"]) == 2
    assert devices.settings["kasa_devices"][0]["custom"]
    assert [c.args[0] for c in devices.sio.emit.await_args_list] == ["kasa_devices", "status"]
    assert all(c.kwargs["room"] == "ui" for c in devices.sio.emit.await_args_list)
    devices.sio.emit.reset_mock()
    await devices.compat_transport.discover_printers("ui")
    assert [c.args[0] for c in devices.sio.emit.await_args_list] == [
        "printer_system_status",
        "printer_list",
        "status",
    ]
    assert all(c.kwargs["room"] == "ui" for c in devices.sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_manual_printer_preserves_endpoint_type_and_known_configuration(devices):
    devices.settings["printers"] = [
        {"host": "10.0.0.1", "port": 80, "name": "Existing", "type": "unknown"}
    ]
    await devices.compat_transport.add_printer("ui", VALID["add_printer"])
    assert len(devices.settings["printers"]) == 2
    devices.compat_service.printer.add_printer_manually.assert_called_once_with(
        "Test Printer", "10.0.0.42", port=7125, printer_type="moonraker", camera_url=None
    )
    assert devices.settings["printers"][-1]["port"] == 7125


@pytest.mark.asyncio
async def test_failed_persistence_prevents_manual_adapter_mutation(devices):
    devices.settings_service.store.save.side_effect = OSError("private detail")
    before = dict(devices.settings)
    await devices.compat_transport.add_printer("ui", VALID["add_printer"])
    devices.compat_service.printer.add_printer_manually.assert_not_called()
    assert devices.settings == before
    assert "private detail" not in str(devices.sio.emit.await_args)


@pytest.mark.parametrize(
    "payload",
    [
        {"host": "http://example.com"},
        {"host": "../escape"},
        {"host": "host:70000"},
        {"host": "host:80", "port": 90},
        {"host": "host", "port": True},
        {"host": "host", "owner": "x"},
        {"host": "host", "camera_url": "http://other/stream"},
        {"host": "host", "camera_url": "http://user:secret@host/stream"},
    ],
)
def test_printer_schema_rejects_bad_addresses_and_identity(payload):
    with pytest.raises(ValidationError):
        AddPrinter.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"ip": "10.0.0.25", "action": "brightness", "value": True},
        {"ip": "10.0.0.25", "action": "color", "value": {"h": -1, "s": 50, "v": 50}},
        {"ip": "10.0.0.25", "action": "on", "value": True},
        {"ip": "example.com", "action": "on"},
    ],
)
def test_kasa_contract_is_discriminated_and_strict(payload):
    with pytest.raises(ValidationError):
        KasaControl.model_validate(payload)


@pytest.mark.asyncio
async def test_unknown_kasa_target_never_receives_control(devices):
    await devices.compat_transport.control_kasa("ui", {"ip": "10.0.0.99", "action": "on"})
    devices.compat_service.kasa.turn_on.assert_not_called()
    assert devices.sio.emit.await_args.args[1]["code"] == "device_missing"
