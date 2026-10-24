"""Owner settings and native/fallback lifecycle policy regressions for R2b2."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest
from services.settings import SettingsStore


@pytest.fixture
def admin_runtime(application_factory):
    app = application_factory()
    owner = str(uuid.uuid4())
    other = str(uuid.uuid4())
    for sid, principal, role in (
        ("renderer", owner, "renderer"),
        ("second", owner, "renderer"),
        ("tray", owner, "resident"),
        ("control", owner, "workspace"),
        ("foreign", other, "renderer"),
    ):
        assert app.sessions.accept(sid, {"client_id": principal, "role": role})
    app.settings_service.store.save = Mock()
    app.lifecycle.restrict = AsyncMock()
    app.lifecycle.close_app = AsyncMock()
    app.lifecycle.request_exit = Mock()
    return app


SETTINGS_EVENTS = (
    "get_settings",
    "update_settings",
    "get_tool_permissions",
    "update_tool_permissions",
)
PAYLOADS = {
    "get_settings": {},
    "update_settings": {"camera_flipped": True},
    "get_tool_permissions": {},
    "update_tool_permissions": {"write_file": False},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", SETTINGS_EVENTS)
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign", "locked"])
async def test_settings_gate_cannot_be_changed_by_request(admin_runtime, name, sid):
    app = admin_runtime
    if sid == "locked":
        sid = "renderer"
        app.settings["face_auth_enabled"] = True
    before = copy.deepcopy(app.settings)
    result = await app.sio.handlers["/"][name](sid, PAYLOADS[name])
    assert not result["ok"]
    assert app.settings == before
    app.settings_service.store.save.assert_not_called()
    assert all(call.kwargs["room"] == sid for call in app.sio.emit.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"face_auth_enabled": "false"},
        {"face_auth_enabled": None},
        {"face_auth_enabled": 0},
        {"camera_flipped": 1},
        {"tool_permissions": None},
        {"tool_permissions": []},
        {"tool_permissions": {"write_file": 0}},
        {"tool_permissions": {"write_file": "yes"}},
        {"tool_permissions": {"manage_settings": False}},
        {"tool_permissions": {"write_file": False}, "owner": "foreign"},
        {"printers": []},
        {"native_desktop": False},
    ],
)
async def test_settings_malformed_or_escalating_patch_is_atomic(admin_runtime, payload):
    before = copy.deepcopy(admin_runtime.settings)
    result = await admin_runtime.settings_transport.update_settings("renderer", payload)
    assert result == {"ok": False, "code": "invalid_arguments"}
    assert admin_runtime.settings == before
    admin_runtime.settings_service.store.save.assert_not_called()


@pytest.mark.asyncio
async def test_locked_owner_cannot_disable_auth_in_same_request(admin_runtime):
    app = admin_runtime
    app.settings["face_auth_enabled"] = True
    result = await app.settings_transport.update_settings(
        "renderer", {"face_auth_enabled": False, "tool_permissions": {"write_file": False}}
    )
    assert not result["ok"] and app.settings["face_auth_enabled"]
    assert not app.settings["tool_permissions"]


@pytest.mark.asyncio
async def test_settings_success_is_owner_scoped_and_reconnect_restores(admin_runtime):
    app = admin_runtime
    change = Mock()
    app.settings_service.on_change = change
    app.settings["printers"] = [{"host": "existing-host"}]
    app.settings["unknown_legacy_config"] = {"preserve": True}
    result = await app.settings_transport.update_settings(
        "renderer",
        {
            "tool_permissions": {"write_file": "deny", "create_directory": False},
            "camera_flipped": True,
        },
    )
    assert result["ok"]
    assert app.settings["tool_permissions"]["write_file"] == "deny"
    assert app.settings["printers"] == [{"host": "existing-host"}]
    assert app.settings["unknown_legacy_config"] == {"preserve": True}
    change.assert_called_once()
    assert {call.kwargs["room"] for call in app.sio.emit.await_args_list} == {"renderer", "second"}
    app.sessions.remove("renderer")
    app.sessions.accept("reopened", {"client_id": app.sessions.local_owner})
    app.sio.emit.reset_mock()
    await app.settings_transport.get_settings("reopened")
    assert app.sio.emit.await_args.kwargs["room"] == "reopened"
    assert app.sio.emit.await_args.args[1]["camera_flipped"] is True
    snapshot = app.sio.emit.await_args.args[1]
    snapshot["tool_permissions"]["write_file"] = False
    assert app.settings["tool_permissions"]["write_file"] == "deny"


@pytest.mark.asyncio
async def test_permission_compatibility_route_and_face_gate_notifications(admin_runtime):
    app = admin_runtime
    await app.settings_transport.update_tool_permissions(
        "renderer", {"read_file": "allow_within_scope"}
    )
    assert app.sio.emit.await_args.args[0] == "tool_permissions"
    await app.settings_transport.update_settings("renderer", {"face_auth_enabled": True})
    assert app.sio.emit.await_args.args == ("auth_status", {"authenticated": False})
    app.sessions.face_authenticated = lambda: True
    await app.settings_transport.update_settings("renderer", {"face_auth_enabled": False})
    assert app.sio.emit.await_args.args == ("auth_status", {"authenticated": True})


@pytest.mark.asyncio
async def test_failed_store_preserves_file_and_in_memory_state(
    admin_runtime, tmp_path, monkeypatch
):
    app = admin_runtime
    path = tmp_path / "settings.json"
    path.write_text('{"original":true}')
    app.settings_service.store = SettingsStore(path)
    before = copy.deepcopy(app.settings)

    def fail(*args):
        raise OSError("private file path and secret details")

    monkeypatch.setattr("services.settings.os.replace", fail)
    result = await app.settings_transport.update_settings("renderer", {"camera_flipped": True})
    assert result["code"] == "settings_unavailable"
    assert app.settings == before and path.read_text() == '{"original":true}'
    assert not list(tmp_path.glob("settings.json.*.tmp"))
    assert "private file path" not in str(app.sio.emit.await_args)


@pytest.mark.asyncio
async def test_real_atomic_store_roundtrip_preserves_unrelated_records(admin_runtime, tmp_path):
    app = admin_runtime
    path = tmp_path / "settings.json"
    app.settings_service.store = SettingsStore(path)
    assert (await app.settings_transport.update_settings("renderer", {"camera_flipped": True}))[
        "ok"
    ]
    assert json.loads(path.read_text())["camera_flipped"] is True
    assert not list(tmp_path.glob("*.tmp"))


def native(app, owner=None, gaming=False):
    owner = app.sessions.local_owner if owner is None else owner
    host = SimpleNamespace(
        state=SimpleNamespace(identity=SimpleNamespace(owner=owner, gaming=gaming)),
        control=AsyncMock(return_value={"phase": "ready"}),
    )
    app.sessions.native_desktop = host
    return host


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": "gaming"},
        {"action": "gaming", "gaming": "false"},
        {"action": "quit", "gaming": False},
        {"action": "register", "owner": "foreign"},
        {"action": "unknown"},
        [],
        {"action": "gaming", "gaming": 1},
    ],
)
async def test_native_control_schema_rejects_extra_fields_and_truthy_booleans(
    admin_runtime, payload
):
    host = native(admin_runtime)
    result = await admin_runtime.lifecycle.desktop_control("control", payload)
    assert not result["ok"]
    host.control.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["unknown", "renderer", "tray", "foreign"])
async def test_native_control_is_workspace_owner_only(admin_runtime, sid):
    host = native(admin_runtime)
    assert not (await admin_runtime.lifecycle.desktop_control(sid, {"action": "quit"}))["ok"]
    host.control.assert_not_called()


@pytest.mark.asyncio
async def test_native_registration_locked_cleanup_and_owner_pin(admin_runtime):
    app = admin_runtime
    host = native(app)
    host.state.identity.owner = None
    assert not (await app.lifecycle.desktop_control("control", {"action": "state"}))["ok"]
    assert (await app.lifecycle.desktop_control("control", {"action": "register"}))["ok"]
    host.state.identity.owner = app.sessions.local_owner
    app.settings["face_auth_enabled"] = True
    app.sio.disconnect = AsyncMock()
    assert (await app.lifecycle.desktop_control("control", {"action": "close"}))["ok"]
    assert {c.args[0] for c in app.sio.disconnect.await_args_list} == {"renderer", "second"}
    app.sessions.principals["control"] = str(uuid.uuid4())
    assert not (await app.lifecycle.desktop_control("control", {"action": "quit"}))["ok"]


@pytest.mark.asyncio
async def test_native_failure_is_scoped_and_redacted(admin_runtime):
    host = native(admin_runtime)
    host.control.side_effect = ValueError("sensitive native detail")
    result = await admin_runtime.lifecycle.desktop_control("control", {"action": "quit"})
    assert result["code"] == "desktop_rejected"
    assert admin_runtime.sio.emit.await_args.kwargs["room"] == "control"
    assert "sensitive" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["unknown", "foreign", "control"])
async def test_resource_updates_require_authorized_owner_role(admin_runtime, sid):
    result = await admin_runtime.lifecycle.set_resource_state(sid, {"state": "studio"})
    assert not result["ok"]
    admin_runtime.lifecycle.restrict.assert_not_called()
    assert admin_runtime.resources.state == "chat"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"state": "invalid"}, {"state": "gaming", "owner": "foreign"}, [], {"state": True}],
)
async def test_invalid_resource_state_never_changes_governor(admin_runtime, payload):
    assert not (await admin_runtime.lifecycle.set_resource_state("renderer", payload))["ok"]
    assert admin_runtime.resources.state == "chat"


@pytest.mark.asyncio
async def test_native_gaming_override_internal_receipt_and_locked_state(admin_runtime):
    app = admin_runtime
    native(app, gaming=True)
    app.sessions.attach_native(app.sessions.local_owner)
    await app.lifecycle.set_resource_state("renderer", {"state": "studio"})
    assert app.resources.state == "gaming"
    app.settings["face_auth_enabled"] = True
    assert not (await app.lifecycle.set_resource_state("renderer", {"state": "chat"}))["ok"]
    assert (await app.lifecycle.set_resource_state("native-resident", {"state": "resident"}))["ok"]
    assert app.resources.state == "gaming"
    assert not (await app.lifecycle.set_resource_state("tray", {"state": "studio"}))["ok"]
    assert not any(call.kwargs["room"] == "foreign" for call in app.sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_fallback_manual_gaming_latch_survives_renderer_requests(admin_runtime):
    app = admin_runtime
    await app.lifecycle.set_resource_state("tray", {"state": "gaming"})
    await app.lifecycle.set_resource_state("renderer", {"state": "studio"})
    assert app.resources.state == "gaming"
    await app.lifecycle.set_resource_state("tray", {"state": "chat"})
    await app.lifecycle.set_resource_state("renderer", {"state": "studio"})
    assert app.resources.state == "studio"


@pytest.mark.asyncio
async def test_shutdown_only_fallback_resident_and_closes_before_exit(admin_runtime):
    app = admin_runtime
    order = []

    async def close():
        order.append("close")

    app.lifecycle.close_app = close
    app.lifecycle.request_exit = lambda: order.append("exit")
    for sid in ("unknown", "foreign", "renderer", "control"):
        assert not (await app.lifecycle.shutdown(sid))["ok"]
    assert not order
    app.settings["face_auth_enabled"] = True
    assert (await app.lifecycle.shutdown("tray"))["ok"]
    assert order == ["close", "exit"]
    native(app)
    assert not (await app.lifecycle.shutdown("tray"))["ok"]


@pytest.mark.asyncio
async def test_resource_cleanup_failure_stays_restricted(admin_runtime):
    app = admin_runtime
    app.lifecycle.restrict.side_effect = RuntimeError("private error detail")
    result = await app.lifecycle.set_resource_state("renderer", {"state": "gaming"})
    assert result["code"] == "lifecycle_failed"
    assert app.resources.state == "gaming"
    assert "private error" not in str(app.sio.emit.await_args)


@pytest.mark.asyncio
async def test_application_resource_transition_closes_all_owners(application_factory):
    app = application_factory()
    app.workspace.close = AsyncMock()
    app.cad_transport.close = AsyncMock(side_effect=RuntimeError("failed worker close"))
    app.image_transport.close = AsyncMock()
    app.local_transport.stop_sid = AsyncMock()
    with pytest.raises(RuntimeError):
        await app.restrict_resources()
    app.workspace.close.assert_awaited_once()
    app.image_transport.close.assert_awaited_once()
    app.local_transport.stop_sid.assert_awaited_once()
