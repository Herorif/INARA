"""Synthetic signed renewals and owned finite process fixtures; no real resident."""

import base64
import ctypes as c
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.test_controller_trust import installed, load
from tests.test_signed_package import NOW, save, signed

admission = load("admission")
admission.signed, admission.trust, admission.review = signed, signed.trust, signed.review


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    value = installed(tmp_path, monkeypatch)
    path = tmp_path / "windows.json"
    save(
        path,
        {
            "format": 1,
            "kind": "inara-windows-signing-policy",
            "mode": "production",
            "targets": [
                {
                    "path": "runtime/python/python.exe",
                    "signer_sha256": "a" * 64,
                    "timestamp_sha256": "b" * 64,
                }
            ],
        },
    )
    value.update(windows=path, windows_pin=signed.digest_file(path), tmp=tmp_path)
    return value


def common(fixture, head="new"):
    return (
        fixture["root"],
        fixture["policy_path"],
        fixture["pin"],
        fixture["windows"],
        fixture["windows_pin"],
        1,
        head,
    )


def sign(fixture, statement, path):
    envelope = {
        "statement": statement,
        "signatures": [
            {
                "key_id": key["key_id"],
                "signature": base64.b64encode(private.sign(admission.message(statement))).decode(),
            }
            for key, private in zip(fixture["policy"]["keys"], fixture["private"])
        ],
    }
    save(path, envelope)
    return path


def grant(fixture, head="new", number=1, now=NOW):
    request = fixture["tmp"] / ("request-" + str(number))
    result = admission.prepare(*common(fixture, head), request, hours=12, now=now)
    assert result["prepared"] and not result["signed"] and not result["launched"]
    statement = json.loads((request / "statement.json").read_text())
    assert (request / "signing-message.bin").read_bytes() == admission.message(statement)
    return sign(fixture, statement, fixture["tmp"] / ("grant-" + str(number) + ".json"))


def admit(fixture, path, head="new", now=NOW, expected=None):
    return admission.admit(
        fixture["root"],
        path,
        fixture["policy_path"],
        fixture["pin"],
        fixture["windows"],
        fixture["windows_pin"],
        1,
        head,
        expected,
        now,
        _native_check=lambda *_: {"authenticode_verified": True},
    )


def commit(fixture, path, head="new", now=NOW):
    reviewed = admit(fixture, path, head, now)
    assert not reviewed["plan"]["launch"]
    return admit(fixture, path, head, now, reviewed["review_sha256"])["expected_head"]


def test_renew_after_package_and_previous_grant_expiry(fixture):
    first = grant(fixture)
    head = commit(fixture, first)
    later = NOW + timedelta(hours=13)
    second = grant(fixture, head, 2, later)
    new_head = commit(fixture, second, head, later)
    assert new_head != head
    retained = json.loads((fixture["root"] / "authorizations/state.json").read_text())
    assert retained["number"] == 2 and retained["grant_sha256"] == new_head
    assert (fixture["root"] / "authorizations" / (head + ".json")).is_file()
    with pytest.raises(ValueError):
        commit(fixture, first, "new", later)


@pytest.mark.parametrize(
    "mutation",
    [
        "unsigned",
        "one-role",
        "bad-signature",
        "duplicate",
        "root",
        "installation",
        "slot",
        "manifest",
        "envelope",
        "policy",
        "windows",
        "sequence",
        "number",
        "parent",
        "future",
        "expired",
        "long-window",
        "boolean",
        "extra",
    ],
)
def test_invalid_grants_cannot_admit(fixture, mutation):
    path = grant(fixture)
    envelope, _ = signed.read(path)
    statement = envelope["statement"]
    changes = {
        "root": ("root", str(fixture["tmp"])),
        "installation": ("installation", "f" * 32),
        "slot": ("slot", "f" * 64),
        "manifest": ("manifest_sha256", "f" * 64),
        "envelope": ("attestation_sha256", "f" * 64),
        "policy": ("policy_sha256", "f" * 64),
        "windows": ("windows_policy_sha256", "f" * 64),
        "sequence": ("sequence", 2),
        "number": ("number", 2),
        "parent": ("previous", "f" * 64),
        "future": ("issued_at", "2026-10-23T00:00:00Z"),
        "expired": ("expires_at", "2026-10-22T00:00:00Z"),
        "long-window": ("expires_at", "2027-01-01T00:00:00Z"),
        "boolean": ("number", True),
        "extra": ("ignore_expiry", True),
    }
    if mutation in changes:
        key, value = changes[mutation]
        statement[key] = value
        sign(fixture, statement, path)
    else:
        if mutation == "unsigned":
            envelope["signatures"] = []
        elif mutation == "one-role":
            envelope["signatures"] = envelope["signatures"][:1]
        elif mutation == "duplicate":
            envelope["signatures"] *= 2
        else:
            envelope["signatures"][0]["signature"] = base64.b64encode(b"X" * 64).decode()
        save(path, envelope)
    with pytest.raises((ValueError, KeyError)):
        admit(fixture, path)
    assert not (fixture["root"] / "authorizations/state.json").exists()


def test_review_changed_and_native_failure_refuse(fixture):
    path = grant(fixture)
    reviewed = admit(fixture, path)
    fixture["service"].deactivate()
    with pytest.raises(ValueError):
        admit(fixture, path, expected=reviewed["review_sha256"])
    fixture["service"].activate(fixture["slot"])

    def refuse(*_):
        raise ValueError("No owned certificate")

    with pytest.raises(ValueError):
        admission.admit(
            fixture["root"],
            path,
            fixture["policy_path"],
            fixture["pin"],
            fixture["windows"],
            fixture["windows_pin"],
            1,
            "new",
            now=NOW,
            _native_check=refuse,
        )
    assert not (fixture["root"] / "authorizations/state.json").exists()


def test_interrupted_commit_reuses_only_exact_orphan(fixture, monkeypatch):
    path = grant(fixture)
    reviewed = admit(fixture, path)
    original = signed.manager.write

    def interrupted(*_):
        raise OSError("Simulated pointer commit interruption")

    monkeypatch.setattr(signed.manager, "write", interrupted)
    with pytest.raises(OSError):
        admit(fixture, path, expected=reviewed["review_sha256"])
    assert list((fixture["root"] / "authorizations").glob("*.json"))
    monkeypatch.setattr(signed.manager, "write", original)
    head = commit(fixture, path)
    assert signed.digest_file(path) == head


def test_launch_holds_manager_and_file_leases_after_old_package_expiry(fixture):
    head = commit(fixture, grant(fixture))
    calls = []

    def run(executable, arguments, directory, environment, expires):
        calls.append(True)
        assert executable == directory / "runtime/python/python.exe"
        assert arguments[:2] == ["-I", "-B"] and arguments[-1] == "--resident-only"
        assert environment["INARA_DESKTOP_DATA_DIR"] == str(
            fixture["root"] / "data" / fixture["slot"] / "desktop-profile"
        )
        with pytest.raises(ValueError, match="busy"):
            fixture["service"].deactivate()
        with pytest.raises(PermissionError):
            executable.write_text("NEVER WRITE")
        return {"exit_code": 0, "authorization_expired": False, "process_tree_contained": True}

    result = admission.launch(
        *common(fixture, head),
        resident_only=True,
        now=NOW + timedelta(hours=2),
        _native_check=lambda *_: None,
        _run=run,
    )
    assert result["launched"] and len(calls) == 1 and not result["release_authorized"]
    fixture["service"].deactivate()  # Released after the owned process lifetime.


@pytest.mark.parametrize("mutation", ["head", "source", "expiry", "signature"])
def test_launch_refuses_without_running(fixture, mutation):
    path = grant(fixture)
    head = commit(fixture, path)
    now = NOW
    if mutation == "head":
        head = "0" * 64
    elif mutation == "source":
        (fixture["root"] / "versions" / fixture["slot"] / "runtime/python/python.exe").write_text(
            "BAD"
        )
    elif mutation == "expiry":
        now += timedelta(days=1)
    else:
        (fixture["root"] / "authorizations" / (head + ".json")).write_text("{}")

    def forbidden(*_):
        raise AssertionError("Execution reached after trust refusal")

    with pytest.raises((ValueError, KeyError)):
        admission.launch(
            *common(fixture, head), now=now, _native_check=lambda *_: None, _run=forbidden
        )


def test_file_lease_release_on_exception(tmp_path):
    path = tmp_path / "leased.txt"
    path.write_text("owned")
    with pytest.raises(RuntimeError):
        with admission.launcher.file_leases([path]):
            with pytest.raises(PermissionError):
                path.write_text("changed")
            raise RuntimeError("fixture")
    path.write_text("released")


def test_actual_native_process_exit_and_expiry(tmp_path):
    script = tmp_path / "owned fixture.py"
    marker = tmp_path / "result.txt"
    script.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('ran')\n")
    result = admission.launcher.run(
        Path(sys.executable),
        ["-I", "-B", str(script), str(marker)],
        tmp_path,
        dict(os.environ),
        datetime.now(timezone.utc) + timedelta(seconds=15),
    )
    assert result["exit_code"] == 0 and marker.read_text() == "ran"
    result = admission.launcher.run(
        Path(sys.executable),
        ["-I", "-c", "import time; time.sleep(30)"],
        tmp_path,
        dict(os.environ),
        datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    assert result["authorization_expired"] and result["exit_code"] != 0


def test_controller_death_kills_owned_process_tree(tmp_path):
    pid_file = tmp_path / "owned-pid.txt"
    grandchild_file = tmp_path / "owned-grandchild.txt"
    grandchild = (
        "import os,time;from pathlib import Path;"
        f"Path({str(grandchild_file)!r}).write_text(str(os.getpid()));time.sleep(60)"
    )
    child = (
        "import os,subprocess,sys,time;from pathlib import Path;"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()));"
        f"subprocess.Popen([sys.executable,'-I','-c',{grandchild!r}]);time.sleep(60)"
    )
    launcher_path = Path(admission.launcher.__file__)
    worker = tmp_path / "controller-fixture.py"
    worker.write_text(
        "import importlib.util, os, sys\nfrom pathlib import Path\n"
        "from datetime import datetime,timedelta,timezone\n"
        f"spec=importlib.util.spec_from_file_location('guard', {str(launcher_path)!r})\n"
        "guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)\n"
        f"code={child!r}\n"
        "guard.run(Path(sys.executable),['-I','-c',code],Path.cwd(),dict(os.environ),"
        "datetime.now(timezone.utc)+timedelta(seconds=60))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", str(worker)],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    handles = []
    dll = admission.launcher.api()
    dll.OpenProcess.argtypes = [c.c_ulong, c.c_int, c.c_ulong]
    dll.OpenProcess.restype = c.c_void_p
    try:
        deadline = time.monotonic() + 12
        while (
            not all(p.exists() and p.stat().st_size for p in (pid_file, grandchild_file))
            and time.monotonic() < deadline
            and process.poll() is None
        ):
            time.sleep(0.05)
        assert all(p.exists() for p in (pid_file, grandchild_file)), (
            process.stderr.read() if process.poll() is not None else b"No process tree markers"
        )
        for path in (pid_file, grandchild_file):
            handle = dll.OpenProcess(0x100000, False, int(path.read_text()))
            assert handle
            handles.append(handle)
        process.kill()  # Only the fixture process we created, never an arbitrary PID.
        process.wait(timeout=5)
        assert all(dll.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stderr.close()
        for handle in handles:
            dll.CloseHandle(handle)


def test_failed_job_assignment_never_resumes_process(tmp_path, monkeypatch):
    calls = []

    class Fake:
        def __getattr__(self, name):
            def invoke(*args):
                calls.append(name)
                if name == "CreateJobObjectW":
                    return 10
                if name == "CreateProcessW":
                    args[-1]._obj.process, args[-1]._obj.thread = 11, 12
                if name == "AssignProcessToJobObject":
                    return 0
                return 1

            return invoke

    monkeypatch.setattr(admission.launcher, "api", lambda: Fake())
    with pytest.raises(OSError):
        admission.launcher.run(
            Path(sys.executable),
            [],
            tmp_path,
            {},
            datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    assert "ResumeThread" not in calls
    assert "TerminateProcess" in calls and "CloseHandle" in calls


def test_external_latest_head_rejects_restored_old_pointer(fixture):
    first = commit(fixture, grant(fixture))
    pointer = fixture["root"] / "authorizations/state.json"
    old = pointer.read_bytes()
    second = commit(fixture, grant(fixture, first, 2), first)
    pointer.write_bytes(old)
    with pytest.raises(ValueError):
        admission.launch(*common(fixture, second), now=NOW)


def test_expired_grant_refuses_before_payload_walk(fixture, monkeypatch):
    head = commit(fixture, grant(fixture))

    def forbidden(*_):
        raise AssertionError("Walked payload after grant expiry")

    monkeypatch.setattr(signed.audit.package, "files_in", forbidden)
    with pytest.raises(ValueError):
        admission.launch(*common(fixture, head), now=NOW + timedelta(days=2))
