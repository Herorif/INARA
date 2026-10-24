"""Inert receipt/controller fixtures; no real identities, residents or signers."""

from datetime import timedelta
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_signed_package import NOW, save, setup_package, signed

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("test_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows, controller = load("windows-signature"), load("controller-package")


def installed(tmp_path, monkeypatch):
    fixture = setup_package(tmp_path, monkeypatch, "production")
    args = [fixture["package"], fixture["policy_path"], fixture["pin"], 1, fixture["root"]]
    planned = signed.install_plan(*args, now=NOW)
    result = signed.install(*args, planned["review_sha256"], now=NOW)
    service = signed.manager.Installation(fixture["root"])
    service.activate(result["slot"])
    fixture.update(service=service, slot=result["slot"])
    return fixture


def check(fixture, now=NOW):
    return signed.launch_check(fixture["root"], fixture["policy_path"], fixture["pin"], 1, now=now)


def test_installed_evidence_checks_without_original_source(tmp_path, monkeypatch):
    fixture = installed(tmp_path, monkeypatch)
    fixture["package"].rename(tmp_path / "source-unavailable")
    result = check(fixture)
    assert result["source_authorization_checked"]
    assert not result["installation_metadata_signed"]
    assert not result["launch_authorized"] and not result["launched"]
    with pytest.raises(ValueError):
        check(fixture, NOW + timedelta(hours=2))


@pytest.mark.parametrize(
    "mutation",
    [
        "binding",
        "signature",
        "evidence",
        "payload",
        "extra",
        "missing",
        "policy",
        "selection",
        "profile",
        "no-receipt",
    ],
)
def test_launch_contract_refuses_changes(tmp_path, monkeypatch, mutation):
    fixture = installed(tmp_path, monkeypatch)
    root, slot = fixture["root"], fixture["slot"]
    capsule = root / "admissions" / slot
    if mutation == "binding":
        path = root / "admissions" / (slot + ".json")
        value, _ = signed.read(path)
        value["installation"] = "f" * 32
        save(path, value)
    elif mutation == "signature":
        (capsule / signed.ENVELOPE).write_text("{}")
    elif mutation == "evidence":
        (capsule / "ledger/ledger.json").write_text("{}")
    elif mutation == "payload":
        (root / "versions" / slot / "runtime/python/python.exe").write_text("ALTERED")
    elif mutation == "extra":
        (capsule / "unregistered.py").write_text("NEVER EXECUTE")
    elif mutation == "missing":
        (capsule / signed.MANIFEST).unlink()
    elif mutation == "policy":
        fixture["policy_path"].write_text("{}")
    elif mutation == "selection":
        fixture["service"].deactivate()
    elif mutation == "profile":
        (root / "data" / slot / ".inara-data.json").write_text("{}")
    else:
        capsule.rename(root / "admissions" / "retained")
    with pytest.raises((ValueError, OSError, KeyError)):
        check(fixture)


def test_partial_receipt_prevents_registration_and_is_preserved(tmp_path, monkeypatch):
    fixture = setup_package(tmp_path, monkeypatch, "production")
    args = [fixture["package"], fixture["policy_path"], fixture["pin"], 1, fixture["root"]]
    planned = signed.install_plan(*args, now=NOW)
    original = signed.retain_admission

    def interrupted(package, service, state, slot, *rest):
        base = service.root / "admissions" / slot
        base.mkdir(parents=True)
        (base / "interrupted").write_text("RETAIN")
        raise ValueError("Simulated power loss")

    monkeypatch.setattr(signed, "retain_admission", interrupted)
    with pytest.raises(ValueError):
        signed.install(*args, planned["review_sha256"], now=NOW)
    service = signed.manager.Installation(fixture["root"])
    assert service.load()["slots"] == {}
    assert service.load()["current"] is None
    monkeypatch.setattr(signed, "retain_admission", original)
    review = signed.install_plan(*args, now=NOW, resume=True)
    with pytest.raises((ValueError, OSError)):
        signed.install(*args, review["review_sha256"], now=NOW, resume=True)
    assert service.load()["slots"] == {}
    assert list((fixture["root"] / "admissions").rglob("interrupted"))


def test_complete_receipt_supports_registration_recovery(tmp_path, monkeypatch):
    fixture = setup_package(tmp_path, monkeypatch, "production")
    args = [fixture["package"], fixture["policy_path"], fixture["pin"], 1, fixture["root"]]
    review = signed.install_plan(*args, now=NOW)
    original = signed.manager.Installation.register
    monkeypatch.setattr(
        signed.manager.Installation,
        "register",
        lambda *_: (_ for _ in ()).throw(ValueError("Interrupted registration")),
    )
    with pytest.raises(ValueError):
        signed.install(*args, review["review_sha256"], now=NOW)
    monkeypatch.setattr(signed.manager.Installation, "register", original)
    review = signed.install_plan(*args, now=NOW, resume=True)
    result = signed.install(*args, review["review_sha256"], now=NOW, resume=True)
    assert result["installed"] and not result["selected"]


def test_launch_refuses_signature_before_installed_payload_walk(tmp_path, monkeypatch):
    fixture = installed(tmp_path, monkeypatch)
    path = fixture["root"] / "admissions" / fixture["slot"] / signed.ENVELOPE
    path.write_text("{}")

    def forbidden(*_):
        raise AssertionError("Payload walk reached before signature refusal")

    monkeypatch.setattr(signed.audit.package, "files_in", forbidden)
    with pytest.raises((ValueError, KeyError)):
        check(fixture)


def test_receipt_cannot_hide_a_second_payload(tmp_path, monkeypatch):
    fixture = installed(tmp_path, monkeypatch)
    source = fixture["root"] / "versions" / fixture["slot"] / "desktop-pilot.json"
    target = fixture["root"] / "admissions" / fixture["slot"] / "payload/desktop-pilot.json"
    target.parent.mkdir()
    target.write_bytes(source.read_bytes())
    with pytest.raises(ValueError):
        check(fixture)


def test_receipt_respects_reviewed_wrapper_snapshot(tmp_path, monkeypatch):
    fixture = setup_package(tmp_path, monkeypatch, "production")
    args = [fixture["package"], fixture["policy_path"], fixture["pin"], 1, fixture["root"]]
    review = signed.install_plan(*args, now=NOW)
    original = signed.retain_admission

    def changed(package, *rest):
        envelope, _ = signed.read(package / signed.ENVELOPE)
        # Semantically identical signatures, different raw bytes after review.
        (package / signed.ENVELOPE).write_text(__import__("json").dumps(envelope))
        return original(package, *rest)

    monkeypatch.setattr(signed, "retain_admission", changed)
    with pytest.raises(ValueError):
        signed.install(*args, review["review_sha256"], now=NOW)
    assert signed.manager.Installation(fixture["root"]).load()["slots"] == {}


def windows_fixture(tmp_path):
    directory = tmp_path / "native"
    directory.mkdir()
    (directory / "owned.exe").write_text("INERT")
    path = tmp_path / "windows.json"
    value = {
        "format": 1,
        "kind": "inara-windows-signing-policy",
        "mode": "production",
        "targets": [{"path": "owned.exe", "signer_sha256": "a" * 64, "timestamp_sha256": "b" * 64}],
    }
    save(path, value)
    report = {
        "status": "0x00000000",
        "signer_sha256": "a" * 64,
        "timestamp_sha256": "b" * 64,
        "cache_only": True,
    }
    return directory, path, signed.digest_file(path), report


def test_native_policy_requires_exact_identity_timestamp_and_coverage(tmp_path):
    directory, path, pin, report = windows_fixture(tmp_path)
    result = windows.check(directory, path, pin, _probe=lambda _: report)
    assert result["authenticode_verified"] and not result["release_authorized"]
    (directory / "uncovered.dll").write_text("INERT")
    with pytest.raises(ValueError):
        windows.check(directory, path, pin, _probe=lambda _: report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "0x80092013"),
        ("cache_only", False),
        ("signer_sha256", "c" * 64),
        ("timestamp_sha256", None),
    ],
)
def test_native_refusal(tmp_path, field, value):
    directory, path, pin, report = windows_fixture(tmp_path)
    report[field] = value
    with pytest.raises(ValueError):
        windows.check(directory, path, pin, _probe=lambda _: report)


def test_disabled_policy_and_wrong_pin_refuse(tmp_path):
    directory, path, _, report = windows_fixture(tmp_path)
    with pytest.raises(ValueError):
        windows.check(directory, path, "0" * 64, _probe=lambda _: report)
    path = ROOT / "docs/WINDOWS_SIGNING_POLICY.json"
    with pytest.raises(ValueError):
        windows.check(directory, path, signed.digest_file(path), _probe=lambda _: report)


def test_native_provider_is_cache_only_and_closes_failed_state(tmp_path, monkeypatch):
    actions = []

    class Function:
        def __call__(self, _, __, pointer):
            data = pointer._obj
            actions.append((data.action, data.flags, data.ui, data.revocation))
            return -2146762496

    class Library:
        WinVerifyTrust = Function()
        WTHelperProvDataFromStateData = Function()
        WTHelperGetProvSignerFromChain = Function()

    def dll(name, winmode):
        assert name == "wintrust.dll" and winmode == 0x800
        return Library()

    monkeypatch.setattr(windows.c, "WinDLL", dll)
    windows.native_probe(tmp_path / "inert.exe")
    assert actions == [(1, 0x3080, 2, 1), (2, 0x3080, 2, 1)]


def controller_fixture(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_text("INERT NEVER EXECUTE")

    class Runtime:
        def verify(self, *_):
            return {"integrity": "passed"}

    monkeypatch.setattr(controller.signed.audit.package, "runtime_tool", lambda: Runtime())
    output = tmp_path / "controller"
    result = controller.stage(runtime, output)
    return output, result["manifest_sha256"]


@pytest.mark.parametrize("mutation", ["bytes", "extra", "missing", "wrong-pin", "shared"])
def test_controller_exact_inventory(tmp_path, monkeypatch, mutation):
    output, pin = controller_fixture(tmp_path, monkeypatch)
    assert controller.verify(output, pin)["integrity"] == "passed"
    if mutation == "bytes":
        (output / "scripts/controller.py").write_text("ALTERED")
    elif mutation == "extra":
        (output / "extra.py").write_text("INERT")
    elif mutation == "missing":
        (output / "runtime/python.exe").unlink()
    elif mutation == "wrong-pin":
        pin = "0" * 64
    else:
        os.link(output / "runtime/python.exe", tmp_path / "shared.exe")
    with pytest.raises((ValueError, OSError)):
        controller.verify(output, pin)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell bootstrap")
@pytest.mark.parametrize("mutation", ["bytes", "extra", "wrong-pin"])
def test_bootstrap_refuses_before_runtime(tmp_path, monkeypatch, mutation):
    output, pin = controller_fixture(tmp_path, monkeypatch)
    if mutation == "bytes":
        (output / "runtime/python.exe").write_text("MUTATED")
    elif mutation == "extra":
        (output / "extra.py").write_text("INERT")
    else:
        pin = "0" * 64
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/open-trusted-controller.ps1"),
            "-Directory",
            str(output),
            "-ExpectedManifest",
            pin,
            "policy-status",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "bootstrap refused" in result.stderr
    assert "not a valid" not in result.stderr  # Never reached the inert executable.
    assert not list(output.rglob("__pycache__"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction/bootstrap")
def test_bootstrap_rejects_linked_controller_ancestor(tmp_path, monkeypatch):
    import _winapi

    (tmp_path / "owned").mkdir()
    output, pin = controller_fixture(tmp_path / "owned", monkeypatch)
    linked = tmp_path / "linked"
    _winapi.CreateJunction(str(output.parent), str(linked))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts/open-trusted-controller.ps1"), "-Directory",
         str(linked / output.name), "-ExpectedManifest", pin, "policy-status"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "Linked controller path" in result.stderr


def test_windows_signature_adapter_actual_unsigned_input():
    if sys.platform != "win32":
        pytest.skip("Windows trust provider")
    result = windows.probe(ROOT / "scripts/controller.py")
    assert result["status"] != "0x00000000" and result["signer_sha256"] is None


def test_controller_rejects_implicit_or_missing_configuration():
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/controller.py"), "launch-check"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1 and "controller refused" in result.stderr
    assert not result.stdout
