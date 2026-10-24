"""Private management review/session boundaries and real synthetic protected transitions."""

from io import BytesIO, StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_controller_trust import load
from tests import test_managed_update as helpers
from tests.test_managed_update import NATIVE, NOW, managed, proposal

ui = load("managed-ui")


@pytest.fixture
def managed_fixture(tmp_path, monkeypatch):
    return helpers.fixture.__wrapped__(tmp_path, monkeypatch)


def base(tmp_path, operation="status"):
    value = {"operation": operation, "root": str(tmp_path / "installation"), "anchor": str(tmp_path / "anchor"), "expected_state": "a" * 64}
    if operation in {"resume", "abort"}:
        value["previous_state"] = "b" * 64
    if operation == "change":
        value.update(action="update", expected_head="b" * 64, policy=str(tmp_path / "release.json"), expected_policy="c" * 64,
                     windows_policy=str(tmp_path / "windows.json"), expected_windows_policy="d" * 64,
                     grant=str(tmp_path / "grant.json"), change=str(tmp_path / "change.json"))
    return value


@pytest.fixture
def session(tmp_path, monkeypatch):
    calls = []
    clock = [100.0]
    control = ui.Control(clock=lambda: clock[0])

    def invoke(value, reviewed=None):
        calls.append((value.copy(), reviewed))
        return {"plan": {"checkpoint": "e" * 64, "launch": False}, "review_sha256": "f" * 64} if reviewed is None else {"applied": True, "checkpoint": "e" * 64, "launched": False}

    monkeypatch.setattr(control, "invoke", invoke)
    return control, clock, calls, base(tmp_path, "change")


def test_single_use_review_exact_inputs_and_backend_plan(session):
    control, _, calls, value = session
    result = control.dispatch({"op": "review", "request": value})
    assert result["expires_in_seconds"] == 300 and result["plan"]["launch"] is False
    assert calls[-1][1] is None
    assert control.dispatch({"op": "apply", "token": result["token"], "request": value})["applied"]
    assert calls[-1][1] == "f" * 64
    with pytest.raises(ValueError):
        control.dispatch({"op": "apply", "token": result["token"], "request": value})


@pytest.mark.parametrize("kind", ["expired", "edited", "wrong-token", "discard", "status", "replacement", "malformed"])
def test_review_revocation_and_failed_apply_consumption(session, kind):
    control, clock, calls, value = session
    result = control.dispatch({"op": "review", "request": value})
    message = {"op": "apply", "token": result["token"], "request": value.copy()}
    if kind == "expired":
        clock[0] += 300
    elif kind == "edited":
        message["request"]["expected_head"] = "9" * 64
    elif kind == "wrong-token":
        message["token"] = "0" * 64
    elif kind == "discard":
        control.dispatch({"op": "discard"})
    elif kind == "status":
        control.dispatch({"op": "status", "request": {k: v for k, v in {**value, "operation": "status"}.items() if k in ui.COMMON}})
    elif kind == "replacement":
        control.dispatch({"op": "review", "request": value})
    else:
        with pytest.raises(ValueError):
            control.dispatch({"op": "anything"})
    with pytest.raises(ValueError):
        control.dispatch(message)
    assert control.pending is None
    assert all(reviewed is None for _, reviewed in calls)


def test_backend_failure_consumes_review(session, monkeypatch):
    control, _, _, value = session
    result = control.dispatch({"op": "review", "request": value})

    def failed(*_):
        raise ValueError("State changed during review")

    monkeypatch.setattr(control, "invoke", failed)
    with pytest.raises(ValueError):
        control.dispatch({"op": "apply", "token": result["token"], "request": value})
    assert control.pending is None


@pytest.mark.parametrize("kind", ["relative", "unc", "bad-pin", "auto-new", "unsupported", "launch", "extra", "missing", "unpaired-trust", "newline"])
def test_request_schema_paths_and_trust_fail_closed(tmp_path, kind):
    value = base(tmp_path, "change")
    if kind == "relative":
        value["root"] = "relative"
    elif kind == "unc":
        value["root"] = r"\\server\private"
    elif kind == "bad-pin":
        value["expected_state"] = "A" * 64
    elif kind == "auto-new":
        value = base(tmp_path, "status")
        value["expected_state"] = "new"
    elif kind == "unsupported":
        value["action"] = "erase_data"
    elif kind == "launch":
        value["operation"] = "launch"
    elif kind == "extra":
        value["command"] = "arbitrary"
    elif kind == "missing":
        del value["grant"]
    elif kind == "unpaired-trust":
        value["next_policy"] = str(tmp_path / "next.json")
    else:
        value["root"] += "\n"
    with pytest.raises((ValueError, TypeError)):
        ui.request(value)


@pytest.mark.parametrize("operation", ["change", "resume", "abort", "status"])
def test_finite_backend_routes_without_launch(tmp_path, monkeypatch, operation):
    value = base(tmp_path, operation)
    calls = []
    sentinel = object()
    monkeypatch.setattr(ui.managed, "inputs", lambda *args: calls.append(("inputs", args)) or sentinel)
    for name in ("change", "resume", "abort", "status"):
        monkeypatch.setattr(ui.managed, name, lambda *args, name=name: calls.append((name, args)) or {"route": name})
    result = ui.Control().invoke(ui.request(value), "f" * 64)
    assert result["route"] == operation and calls[-1][0] == operation
    if operation == "change":
        assert calls[-1][1][0] is sentinel and calls[-1][1][-1] == "f" * 64
    elif operation != "status":
        assert calls[-1][1][-2:] == ("b" * 64, "f" * 64)


def test_protocol_ready_json_only_and_generic_failure():
    outgoing = StringIO()
    ui.serve(BytesIO(b'{"op":"shell","secret":"never echo"}\n'), outgoing)
    ready, result = map(json.loads, outgoing.getvalue().splitlines())
    assert ready["ready"] and ready["kind"] == "inara-protected-management"
    assert "signed-lifecycle" in ready["capabilities"]
    assert result["ok"] is False and "never echo" not in outgoing.getvalue()


@pytest.mark.parametrize("raw", [b"x" * 65537, b'{"op":"discard"}'], ids=["overlong", "truncated"])
def test_protocol_bounded_complete_frames(raw):
    with pytest.raises(ValueError):
        ui.serve(BytesIO(raw), StringIO())


def test_real_protected_enrollment_status_and_changed_grant_refusal(managed_fixture, monkeypatch):
    fixture = managed_fixture
    proposed = proposal(fixture)
    monkeypatch.setattr(ui, "managed", managed)
    original = managed.change

    def checked(*args):
        return original(*args, now=NOW, _native_check=NATIVE)

    monkeypatch.setattr(managed, "change", checked)
    value = {
        "operation": "change", "action": "enroll", "root": str(fixture["root"]), "anchor": str(fixture["anchor"]),
        "expected_state": "new", "expected_head": fixture["head"], "policy": str(fixture["policy_path"]),
        "expected_policy": fixture["pin"], "windows_policy": str(fixture["windows"]),
        "expected_windows_policy": fixture["windows_pin"], "grant": str(proposed["grant"]), "change": str(proposed["change"]),
    }
    control = ui.Control()
    result = control.dispatch({"op": "review", "request": value})
    assert not (fixture["root"] / "update-pending.json").exists()
    applied = control.dispatch({"op": "apply", "token": result["token"], "request": value})
    assert applied["applied"] and applied["checkpoint"] == result["plan"]["checkpoint"] and not applied["launched"]
    status = control.dispatch({"op": "status", "request": {
        "operation": "status", "root": value["root"], "anchor": value["anchor"], "expected_state": applied["checkpoint"],
    }})
    assert status["sequence_floor"] == 1 and status["selected"] == fixture["slot"]


def test_real_changed_signed_input_is_rejected_after_review(managed_fixture, monkeypatch):
    fixture = managed_fixture
    proposed = proposal(fixture)
    monkeypatch.setattr(ui, "managed", managed)
    original = managed.change
    monkeypatch.setattr(managed, "change", lambda *args: original(*args, now=NOW, _native_check=NATIVE))
    value = {"operation": "change", "action": "enroll", "root": str(fixture["root"]), "anchor": str(fixture["anchor"]),
             "expected_state": "new", "expected_head": fixture["head"], "policy": str(fixture["policy_path"]),
             "expected_policy": fixture["pin"], "windows_policy": str(fixture["windows"]), "expected_windows_policy": fixture["windows_pin"],
             "grant": str(proposed["grant"]), "change": str(proposed["change"])}
    control = ui.Control()
    reviewed = control.dispatch({"op": "review", "request": value})
    Path(proposed["grant"]).write_text("{}")
    with pytest.raises((ValueError, KeyError)):
        control.dispatch({"op": "apply", "token": reviewed["token"], "request": value})
    assert control.pending is None and not fixture["anchor"].exists()


@pytest.mark.parametrize("valid", [True, False], ids=["verified-native-entry", "missing-pin-refused"])
def test_native_entry_verifies_inventory_before_fixed_process(tmp_path, monkeypatch, valid):
    entry = load("controller")
    calls = []
    root = tmp_path / "controller with spaces"
    monkeypatch.setattr(entry, "ROOT", root)
    monkeypatch.setattr(entry.sys, "argv", ["controller.py", "managed-setup"] + (["--expected-manifest", "a" * 64] if valid else []))

    def verify(directory, expected):
        assert directory == root and expected == "a" * 64
        calls.append("verified")

    def run(arguments, **kwargs):
        assert calls == ["verified"]
        assert arguments[-4:] == ["-Directory", str(root), "-ExpectedManifest", "a" * 64]
        assert arguments[arguments.index("-File") + 1] == str(root / "scripts/managed-ui.ps1")
        assert "-STA" in arguments and kwargs == {"check": False}
        calls.append("started")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(entry, "load", lambda name: SimpleNamespace(verify=verify))
    monkeypatch.setattr(entry.subprocess, "run", run)
    with pytest.raises(SystemExit) as stopped:
        entry.main()
    assert stopped.value.code == (0 if valid else 1)
    assert calls == (["verified", "started"] if valid else [])


@pytest.mark.parametrize("operation", ["copy", "lifecycle"])
def test_profile_and_signed_lifecycle_worker_routes(tmp_path, monkeypatch, operation):
    value = base(tmp_path, operation)
    value.update({"copy_action": "backup", "slot": "e" * 64, "file": str(tmp_path / "profile.inara")} if operation == "copy" else {"change": str(tmp_path / "lifecycle.json")})
    calls = []
    fake = SimpleNamespace(copies=lambda *args: calls.append(args) or {"route": "copy"}, apply=lambda *args: calls.append(args) or {"route": "lifecycle"})
    monkeypatch.setattr(ui.managed, "module", lambda _: fake)
    result = ui.Control().invoke(ui.request(value), "f" * 64, confirmation="ERASE INARA DATA")
    assert result["route"] == operation
    assert calls[-1][-1] == ("f" * 64 if operation == "copy" else "ERASE INARA DATA")


@pytest.mark.parametrize("kind", ["missing-profile", "invalid-slot", "unknown-copy"])
def test_copy_request_refuses_incomplete_or_arbitrary_actions(tmp_path, kind):
    value = base(tmp_path, "copy")
    value.update(copy_action="prepare-profile", slot="e" * 64, file=str(tmp_path / "profile.inara"))
    if kind == "invalid-slot":
        value["slot"] = "not-a-version"
    elif kind == "unknown-copy":
        value["copy_action"] = "erase"
    with pytest.raises((ValueError, TypeError)):
        ui.request(value)
