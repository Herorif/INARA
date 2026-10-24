"""Immutable desktop workspace pilots, fixed runtime layout and explicit external Python."""

import importlib.util
import json
from pathlib import Path
import pytest
from resident.layout import workspace_executable
from tests.test_release_tools import fixture_root
from tests.test_renderer_provenance import fixture_build

spec = importlib.util.spec_from_file_location(
    "desktop_package", Path(__file__).resolve().parents[1] / "scripts/desktop-package.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.fixture
def source(tmp_path):
    root = fixture_root(tmp_path)
    (root / "package.json").write_text(json.dumps({"devDependencies": {"electron": "44.7.0"}}))
    for name in (
        "backend/resident_main.py",
        "backend/resident/layout.py",
        "scripts/desktop-package.py",
        "scripts/desktop-install.py",
        "scripts/desktop-backup.py",
        "scripts/desktop-recovery.py",
        "scripts/desktop-control.py",
        "scripts/setup-ui.ps1",
        "INARA Setup.cmd",
        "INARA Setup.ps1",
        "native/setup/Setup.xaml",
        "scripts/pilot-start.ps1",
        "electron/native-main.cjs",
        "electron/preload.js",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    bundle = root / ".runtime/desktop-bundles/fixture"
    bundle.mkdir(parents=True)
    records = []
    for name in ("native-main.cjs", "preload.js"):
        path = bundle / name
        path.write_text("bundled fixture")
        records.append(
            {"path": name, "bytes": path.stat().st_size, "sha256": package.release.sha256(path)}
        )
    (bundle / "bundle-manifest.json").write_text(
        json.dumps(
            {
                "format": 1,
                "kind": "native-workspace-bundle",
                "electron_version": "44.7.0",
                "node_runtime_required": False,
                "inputs": [
                    {
                        "path": "electron/native-main.cjs",
                        "sha256": package.release.sha256(root / "electron/native-main.cjs"),
                    }
                ],
                "files": records,
            }
        )
    )
    runtime = root / "node_modules/electron/dist"
    for name in package.RUNTIME_REQUIRED:
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("44.7.0" if name == "version" else "runtime fixture")
    fixture_build(root)
    return root, bundle


def stage(source):
    root, bundle = source
    destination = root / ".runtime/releases/pilot"
    return destination, package.stage(destination, bundle, root)


def test_staged_pilot_is_node_free_but_not_self_contained_and_excludes_profiles(source):
    destination, result = stage(source)
    assert result["integrity"] == "passed" and result["external_python_required"]
    assert (
        not result["node_runtime_required"]
        and not result["self_contained"]
        and not result["signed"]
    )
    assert not (destination / "node_modules").exists() and not (destination / ".env").exists()
    assert not (destination / "backend/settings.json").exists()
    assert (destination / "runtime/electron/LICENSE").is_file()
    assert workspace_executable(destination) == destination / "runtime/electron/electron.exe"


@pytest.mark.parametrize(
    "kind", ["changed", "extra", "missing", "manifest_claim", "case_collision", "escape"]
)
def test_tampered_pilots_reject(source, kind):
    destination, _ = stage(source)
    manifest = destination / "desktop-pilot.json"
    value = json.loads(manifest.read_text())
    if kind == "changed":
        (destination / "electron/native-main.cjs").write_text("changed")
    elif kind == "extra":
        (destination / "extra.txt").write_text("unexpected")
    elif kind == "missing":
        (destination / "runtime/electron/electron.exe").unlink()
    elif kind == "manifest_claim":
        value["self_contained"] = True
    elif kind == "case_collision":
        value["files"].append({**value["files"][0], "path": value["files"][0]["path"].upper()})
    elif kind == "escape":
        value["files"][0]["path"] = "../outside"
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        package.verify(destination)


@pytest.mark.parametrize(
    "kind",
    [
        "stale_input",
        "bundle_tamper",
        "runtime_version",
        "runtime_missing",
        "runtime_extra",
        "outside_destination",
        "reuse",
    ],
)
def test_staging_rejects_invalid_inputs_or_overwrite(source, kind, tmp_path):
    root, bundle = source
    destination = root / ".runtime/releases/pilot"
    if kind == "stale_input":
        (root / "electron/native-main.cjs").write_text("changed")
    elif kind == "bundle_tamper":
        (bundle / "native-main.cjs").write_text("changed")
    elif kind == "runtime_version":
        (root / "node_modules/electron/dist/version").write_text("999")
    elif kind == "runtime_missing":
        (root / "node_modules/electron/dist/electron.exe").unlink()
    elif kind == "runtime_extra":
        (root / "node_modules/electron/dist/.env").write_text("private")
    elif kind == "outside_destination":
        destination = tmp_path / "outside"
    elif kind == "reuse":
        destination.mkdir(parents=True)
        (destination / "keep").write_text("preserve")
    with pytest.raises(ValueError):
        package.stage(destination, bundle, root)
    if kind == "reuse":
        assert (destination / "keep").read_text() == "preserve"


def test_layout_has_no_npm_fallback_when_packaged_runtime_is_missing(source):
    root, _ = source
    assert workspace_executable(root) == root / "node_modules/electron/dist/electron.exe"
    (root / "desktop-pilot.json").write_text(
        json.dumps({"format": 1, "kind": "desktop-workspace-pilot", "self_contained": False})
    )
    with pytest.raises(ValueError):
        workspace_executable(root)


def test_malformed_marker_does_not_select_development_runtime(source):
    root, _ = source
    (root / "desktop-pilot.json").write_text("not json")
    with pytest.raises(ValueError):
        workspace_executable(root)


@pytest.mark.parametrize("kind", ["missing_manifest", "stale_source", "extra_output", "changed_registry"])
def test_new_package_requires_current_renderer_provenance_before_creating_destination(source, kind):
    root, bundle = source
    if kind == "missing_manifest":
        (root / "dist/renderer-provenance.json").unlink()
    elif kind == "stale_source":
        (root / "src/main.js").write_text("changed")
    elif kind == "extra_output":
        (root / "dist/extra.js").write_text("extra")
    else:
        (root / "docs/ASSET_OWNERSHIP.json").write_text('{"format":1,"entries":[{}]}')
    target = root / ".runtime/releases/stale"
    with pytest.raises(ValueError):
        package.stage(target, bundle, root)
    assert not target.exists()


def test_new_package_cannot_drop_its_renderer_binding(source):
    destination, result = stage(source)
    assert result["renderer_provenance"] == "verified"
    marker = destination / "desktop-pilot.json"
    value = json.loads(marker.read_text())
    del value["renderer_provenance_sha256"]
    marker.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        package.verify(destination)
