"""Build acceptance fixtures only. No JDK, Gradle, real APK, network or device."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import pytest

spec = importlib.util.spec_from_file_location(
    "android_build", Path(__file__).resolve().parents[1] / "scripts/android-build.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def dependencies(root):
    path = root / "android/app/gradle.lockfile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture:fixture:1=" + ",".join(sorted(build.CONFIGURATIONS)) + "\nempty=\n")
    path = root / "android/gradle/verification-metadata.xml"
    path.parent.mkdir()
    path.write_text(
        '<verification-metadata xmlns="https://schema.gradle.org/dependency-verification"><configuration><verify-metadata>true</verify-metadata></configuration><components><component group="fixture" name="fixture" version="1"><artifact name="fixture.jar"><sha256 value="'
        + "a" * 64
        + '"/></artifact></component></components></verification-metadata>'
    )


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    dependencies(root)
    (root / "android/app/build.gradle.kts").write_text("// synthetic build input")
    monkeypatch.setattr(
        build,
        "preflight",
        lambda root: {"tools_present": {"java": True}, "sdk_present": {"platform": True}},
    )
    return root


def outputs(root, identifier):
    directory = build.run_directory(root, identifier)
    (directory / "toolchain.json").write_text(json.dumps({key: build.PINS[key] for key in ("java", "gradle")}))
    (directory / "apksigner.txt").write_text("Signer #1 certificate SHA-256 digest: " + "b" * 64)
    apk = root / "android/app/build/outputs/apk/debug/app-debug.apk"
    apk.parent.mkdir(parents=True)
    with zipfile.ZipFile(apk, "w") as archive:
        for name in ("AndroidManifest.xml", "classes.dex", "resources.arsc"):
            archive.writestr(name, b"synthetic fixture, not compiled Android data")
    tests = (
        root
        / "android/app/build/test-results/testDebugUnitTest/TEST-com.inara.companion.MobileProtocolTest.xml"
    )
    tests.parent.mkdir(parents=True)
    tests.write_text(
        '<testsuite tests="1" failures="0" errors="0"><testcase name="vector"/></testsuite>'
    )
    return directory, apk, tests


def test_synthetic_receipt_accepts_all_required_evidence_without_release_claim(fixture):
    identifier = build.begin(fixture)
    outputs(fixture, identifier)
    report = build.complete(fixture, identifier, 0, 0)
    assert report["accepted_debug_build"] and report["junit"]["tests"] == 1
    assert not report["release_signed"] and not report["device_verified"]
    assert len(report["apk"]["sha256"]) == 64


@pytest.mark.parametrize(
    "kind",
    [
        "build_exit",
        "signature_exit",
        "source",
        "dependency",
        "toolchain",
        "old_gradle",
        "signature",
        "stale_apk",
        "stale_tests",
        "failed_tests",
        "skipped_tests",
        "zero_tests",
        "suite_missing",
        "bad_apk",
        "unsafe_apk",
        "missing_apk",
    ],
)
def test_failed_incomplete_or_stale_evidence_cannot_pass(fixture, kind):
    identifier = build.begin(fixture)
    directory, apk, tests = outputs(fixture, identifier)
    status = [0, 0]
    if kind == "build_exit":
        status[0] = 1
    elif kind == "signature_exit":
        status[1] = 1
    elif kind == "source":
        (fixture / "android/app/build.gradle.kts").write_text("changed")
    elif kind == "dependency":
        path = fixture / "android/app/gradle.lockfile"
        path.write_text(path.read_text() + "other:other:2=debugRuntimeClasspath\n")
    elif kind == "toolchain":
        (directory / "toolchain.json").write_text(json.dumps({"java": "21", "gradle": build.PINS["gradle"]}))
    elif kind == "old_gradle":
        (directory / "toolchain.json").write_text(json.dumps({"java": build.PINS["java"], "gradle": "8.11.1"}))
    elif kind == "signature":
        (directory / "apksigner.txt").write_text("No signature certificate")
    elif kind == "stale_apk":
        os.utime(apk, ns=(1, 1))
    elif kind == "stale_tests":
        os.utime(tests, ns=(1, 1))
    elif kind == "failed_tests":
        tests.write_text(
            '<testsuite tests="1" failures="1"><testcase><failure/></testcase></testsuite>'
        )
    elif kind == "skipped_tests":
        tests.write_text('<testsuite tests="1"><testcase><skipped/></testcase></testsuite>')
    elif kind == "zero_tests":
        tests.write_text('<testsuite tests="0"/>')
    elif kind == "suite_missing":
        tests.rename(tests.with_name("TEST-unrelated.xml"))
    elif kind == "bad_apk":
        apk.write_bytes(b"not zip")
    elif kind == "unsafe_apk":
        with zipfile.ZipFile(apk, "a") as archive:
            archive.writestr("../escape", b"fixture")
    elif kind == "missing_apk":
        apk.unlink()
    result = build.complete(fixture, identifier, *status)
    assert not result["accepted_debug_build"] and "error" in result
    assert (
        json.loads((directory / "verification.json").read_text())["accepted_debug_build"] is False
    )


def test_bootstrap_records_dependencies_but_never_claims_accepted_build(fixture):
    identifier = build.begin(fixture, record=True)
    outputs(fixture, identifier)
    result = build.complete(fixture, identifier, 0, 0)
    assert result["signature_verified"] and result["dependency_review_required"]
    assert not result["accepted_debug_build"]


@pytest.mark.parametrize(
    "value",
    ["", "fixture:fixture:1=debugRuntimeClasspath", "fixture:fixture:1+=debugRuntimeClasspath"],
)
def test_missing_partial_or_dynamic_locks_reject_before_build(fixture, value):
    (fixture / "android/app/gradle.lockfile").write_text(value)
    with pytest.raises(ValueError):
        build.begin(fixture)


def test_missing_checksum_or_broad_trust_cannot_pass(fixture):
    path = fixture / "android/gradle/verification-metadata.xml"
    initial = path.read_text()
    for value in (
        initial.replace("a" * 64, "bad"),
        initial.replace(
            "</configuration>",
            '<trusted-artifacts><trust group=".*"/></trusted-artifacts></configuration>',
        ),
    ):
        path.write_text(value)
        with pytest.raises(ValueError):
            build.dependency_state(fixture)


def test_receipt_path_cannot_escape_workspace(fixture):
    with pytest.raises(ValueError):
        build.run_directory(fixture, "../../elsewhere")


def test_real_preflight_is_presence_only_and_does_not_emit_private_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(build.shutil, "which", lambda name: None)
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    # Use the original function, restored separately from the source-fixture patch.
    result = build.preflight(tmp_path)
    assert not result["can_attempt_offline_build"] and not result["apk_compiled"]
    assert not result["network_accessed"] and not result["device_accessed"]
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows PowerShell runner")
def test_actual_runner_preflight_and_missing_tool_gate_leave_inputs_untouched(tmp_path):
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("powershell.exe")
    assert executable
    environment = dict(os.environ)
    environment["PATH"] = str(tmp_path)
    environment.pop("ANDROID_HOME", None)
    environment.pop("ANDROID_SDK_ROOT", None)
    command = [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(root / "android/build.ps1"),
    ]
    before = build.inputs(root)
    result = subprocess.run(
        command + ["-Preflight"], env=environment, capture_output=True, timeout=15
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert not report["apk_compiled"] and not report["can_attempt_offline_build"]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=15)
    assert result.returncode != 0 and b"Provide JDK 17" in result.stderr
    assert before == build.inputs(root)
