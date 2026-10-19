"""Offline release boundary checks; never installs, updates or touches a real profile."""

import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "release_tools", Path(__file__).resolve().parents[1] / "scripts/release-tools.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def fixture_root(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for name in release.FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("fixture")
    (root / "package-lock.json").write_text(json.dumps({"packages": {}}))
    for name in release.SCRIPTS:
        path = root / "scripts" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture")
    for name in release.TREES:
        (root / name).mkdir()
    (root / "dist/index.html").write_text("fixture")
    (root / ".env").write_text("API_KEY=PRIVATE_FIXTURE")
    (root / "backend/settings.json").write_text("PRIVATE_FIXTURE")
    (root / "dist/assets").mkdir()
    (root / "dist/assets/vision.wasm").write_bytes(b"fixture wasm")
    return root


def test_pilot_integrity_excludes_secrets_and_detects_modified_extra_missing_files(tmp_path):
    root = fixture_root(tmp_path)
    destination = root / ".runtime/releases/pilot"
    assert release.stage(destination, root)["integrity"] == "passed"
    assert not (destination / ".env").exists()
    assert not (destination / "backend/settings.json").exists()
    assert (destination / "dist/assets/vision.wasm").is_file()
    assert "PRIVATE_FIXTURE" not in json.dumps(release.diagnostics(root))
    target = destination / "dist/index.html"
    target.write_text("tampered")
    with pytest.raises(ValueError):
        release.verify(destination)
    target.write_text("fixture")
    extra = destination / "unexpected.txt"
    extra.write_text("x")
    with pytest.raises(ValueError):
        release.verify(destination)
    extra.unlink()
    target.unlink()
    with pytest.raises(ValueError):
        release.verify(destination)


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/private",
        "backend/../../.env",
        "backend\\file",
        "backend/.env",
        "backend//file",
    ],
)
def test_manifest_paths_are_contained(path):
    with pytest.raises(ValueError):
        release.safe_relative(path)


def test_partial_stage_overwrite_and_outside_destination_are_rejected(tmp_path):
    root = fixture_root(tmp_path)
    with pytest.raises(ValueError):
        release.stage(tmp_path / "outside", root)
    partial = root / ".runtime/releases/partial"
    partial.mkdir(parents=True)
    with pytest.raises(ValueError):
        release.stage(partial, root)
    with pytest.raises(FileNotFoundError):
        release.verify(partial)


def test_diagnostics_whitelist_never_includes_environment_values(tmp_path, monkeypatch):
    root = fixture_root(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE_FIXTURE")
    monkeypatch.setenv("ANDROID_HOME", "PRIVATE_FIXTURE")
    report = release.diagnostics(root)
    assert report["private_content_included"] is False and report["network_accessed"] is False
    assert "PRIVATE_FIXTURE" not in json.dumps(report) and str(root) not in json.dumps(report)


def test_pending_required_gate_cannot_be_reported_as_released(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    file = folder / "RELEASE_GATES.json"
    gate = {"id": "android-build", "status": "blocked", "required": True, "evidence": "No SDK"}
    file.write_text(json.dumps({"format": 1, "gates": [gate]}))
    assert release.readiness(tmp_path)["release_ready"] is False
    file.write_text(json.dumps({"format": 1, "gates": [gate, gate]}))
    with pytest.raises(ValueError):
        release.readiness(tmp_path)
