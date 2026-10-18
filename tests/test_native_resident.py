"""Native boundary checks: identity preservation, scoped receipt and process ownership."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from resident.state import Identity, State
from resident.host import NativeHost


class FakeTray:
    window = None
    secondary = False
    hotkey = False

    def __init__(self, *args, **kwargs):
        self.notifications = 0

    def post(self, callback):
        callback()

    def notify(self):
        self.notifications += 1
        return True

    def close(self):
        pass


def test_identity_adopts_existing_owner_and_preserves_on_conflict(tmp_path):
    owner = str(uuid.uuid4())
    identity = Identity(tmp_path)
    identity.register(owner)
    state = State(identity)
    state.mode(True)
    original = identity.path.read_bytes()
    restored = Identity(tmp_path)
    assert restored.owner == owner and restored.gaming
    with pytest.raises(ValueError):
        restored.register(str(uuid.uuid4()))
    assert identity.path.read_bytes() == original
    with pytest.raises(ValueError):
        state.mode("false")


@pytest.mark.parametrize("payload", ["broken JSON", '{"id":"bad"}', '{"id":null}'])
def test_invalid_identity_is_never_replaced(tmp_path, payload):
    path = tmp_path / "resident-identity.json"
    path.write_text(payload)
    with pytest.raises(ValueError):
        Identity(tmp_path)
    assert path.read_text() == payload


@pytest.mark.asyncio
async def test_native_control_rejects_other_owner_and_suppresses_gaming_notices(tmp_path):
    host = NativeHost(tmp_path, tmp_path / "profile", tray_factory=FakeTray, resident_only=True)
    owner = str(uuid.uuid4())
    await host.control(owner, {"action": "register"})
    with pytest.raises(ValueError):
        await host.control(str(uuid.uuid4()), {"action": "gaming", "gaming": True})
    assert await host.notify({"delivery_id": "one"})
    assert await host.notify({"delivery_id": "one"})
    assert host.tray.notifications == 1
    await host.control(owner, {"action": "gaming", "gaming": True})
    assert not await host.notify({"delivery_id": "two"})
    assert Identity(tmp_path / "profile").gaming


@pytest.mark.asyncio
async def test_native_receipt_only_after_notice_queued_and_workspace_excluded(monkeypatch, application_factory):
    runtime = application_factory()

    store = SimpleNamespace(
        claim_deliveries=lambda _: [{"delivery_id": "one"}], acknowledge=AsyncMock()
    )
    # The production store's acknowledgement is synchronous.
    receipts = []
    store.acknowledge = lambda key, owner: receipts.append((key, owner))
    desktop = SimpleNamespace(notify=AsyncMock(return_value=False), state=SimpleNamespace(identity=SimpleNamespace(owner="owner")))
    runtime.sessions.native_desktop = desktop
    runtime.delivery.reminders = store
    runtime.sessions.principals.update({"native-resident": "owner", "main": "owner"})
    monkeypatch.setattr(
        runtime.sessions, "roles", {"native-resident": "resident", "main": "workspace"}
    )
    monkeypatch.setattr(runtime.dispatcher, "authenticated", lambda _: True)
    emit = AsyncMock()
    monkeypatch.setattr(runtime.sio, "emit", emit)
    await runtime.delivery.deliver_reminders_once()
    assert receipts == []
    emit.assert_not_called()
    desktop.notify.return_value = True
    await runtime.delivery.deliver_reminders_once()
    assert receipts == [("one", "owner")]


@pytest.mark.asyncio
async def test_desktop_control_requires_workspace_role(application_factory):
    runtime = application_factory()
    desktop = SimpleNamespace(control=AsyncMock(return_value={"gaming": True}),
        state=SimpleNamespace(identity=SimpleNamespace(owner="owner", gaming=False)))
    runtime.sessions.native_desktop = desktop
    runtime.sessions.principals.update({"renderer": "owner", "main": "owner"})
    runtime.sessions.roles.update({"renderer": "renderer", "main": "workspace"})
    assert not (await runtime.lifecycle.desktop_control("renderer", {"action": "quit"}))["ok"]
    desktop.control.assert_not_called()
    assert (await runtime.lifecycle.desktop_control("main", {"action": "gaming", "gaming": True}))["ok"]
    desktop.control.assert_awaited_once_with("owner", {"action": "gaming", "gaming": True})


def test_job_owns_descendants_and_pipe_keeps_credentials_out_of_argv_env(tmp_path, monkeypatch):
    from resident.win32 import WorkspaceProcess, api, kernel, W
    import sys
    import time

    script = tmp_path / "child.py"
    report = tmp_path / "report.json"
    script.write_text("""import json, os, subprocess, sys, time
data=json.load(sys.stdin)
child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
with open(data['report'], 'w') as f:
    json.dump({'child': child.pid, 'argv': sys.argv, 'secret': os.getenv('OPENAI_API_KEY'), 'token': os.getenv('INARA_SESSION_TOKEN'), 'pipe': data['token']}, f)
time.sleep(60)
""")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("INARA_SESSION_TOKEN", "test-bootstrap")
    process = WorkspaceProcess(
        sys.executable, script, {"report": str(report), "token": "test-bootstrap"}, tmp_path
    )
    handles = []
    try:
        deadline = time.monotonic() + 10
        while not report.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        data = json.loads(report.read_text())
        assert data["secret"] is None and data["token"] is None
        assert data["pipe"] == "test-bootstrap" and "test-bootstrap" not in str(data["argv"])
        for pid in (process.pid, data["child"]):
            handle = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                0x100000, False, pid
            )
            assert handle
            handles.append(handle)
        process.close()
        for handle in handles:
            assert (
                api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)(handle, 5000) == 0
            )
    finally:
        process.close()
        for handle in handles:
            kernel.CloseHandle(handle)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,recipient", [("resident", "tray"), ("studio", "renderer")])
async def test_reminder_destination_follows_lifetime_not_stale_renderer(
    monkeypatch, mode, recipient, application_factory
):
    runtime = application_factory()
    runtime.sessions.local_owner = "owner"

    monkeypatch.setattr(
        runtime.sessions, "principals", {"renderer": "owner", "tray": "owner", "control": "owner"}
    )
    monkeypatch.setattr(
        runtime.sessions, "roles", {"renderer": "renderer", "tray": "resident", "control": "workspace"}
    )
    monkeypatch.setattr(runtime.resources, "state", mode)
    monkeypatch.setattr(runtime.dispatcher, "authenticated", lambda _: True)
    monkeypatch.setattr(
        runtime.delivery,
        "reminders",
        SimpleNamespace(claim_deliveries=lambda _: [{"delivery_id": "one"}]),
    )
    monkeypatch.setattr(runtime.sio, "emit", AsyncMock())
    await runtime.delivery.deliver_reminders_once()
    assert runtime.sio.emit.await_args.kwargs["room"] == recipient
