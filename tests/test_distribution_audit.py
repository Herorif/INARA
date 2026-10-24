"""Candidate-bound offline notices; no real profile, network or signing identity."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location(
    "distribution_audit", Path(__file__).resolve().parents[1] / "scripts/distribution-audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    source, candidate, output = (tmp_path / name for name in ("source", "candidate", "audit"))
    lock = {"packages": {"": {}, "node_modules/fixture": {"version": "1.2.3"}, "node_modules/tool": {"version": "2", "dev": True}}}
    write(source, "package-lock.json", lock)
    write(candidate, "package-lock.json", lock)
    write(candidate, "desktop-pilot.json", {"files": [{"path": "LICENSE", "bytes": 7, "sha256": "fixture"}], "electron_version": "44.7.0"})
    write(candidate, "package.json", {"name": "inara", "version": "1", "license": "MIT"})
    write(candidate, "requirements-core.lock", "fixture-pkg==1.0.0\n")
    write(candidate, "LICENSE", "Project notice\n")
    write(candidate, "runtime/python/runtime-manifest.json", {"python_version": "3.12.10", "dependencies": {"fixture-pkg": "1.0.0"}})
    write(candidate, "runtime/python/LICENSE.txt", "CPython notice\n")
    write(candidate, "runtime/electron/LICENSE", "Electron notice\n")
    write(candidate, "runtime/electron/LICENSES.chromium.html", "<html>Chromium notice</html>\n")
    folder = "runtime/python/Lib/site-packages/fixture_pkg-1.0.0.dist-info/"
    write(candidate, folder + "METADATA", "Metadata-Version: 2.4\nName: fixture-pkg\nVersion: 1.0.0\nLicense-Expression: MIT\nLicense-File: LICENSE\n")
    write(candidate, folder + "licenses/LICENSE", "Dependency notice with non-ASCII: caf\u00e9\n")
    write(source, "node_modules/fixture/package.json", {"name": "fixture", "version": "1.2.3", "license": "MIT"})
    write(source, "node_modules/fixture/LICENSE", "Npm notice\n")
    write(source, "node_modules/fixture/index.js", "module.exports=1;\n")
    raw = (source / "node_modules/fixture/index.js").read_bytes()
    write(candidate, "electron/bundle-manifest.json", {"inputs": [{"path": "node_modules/fixture/index.js", "sha256": audit.digest(raw)}]})
    monkeypatch.setattr(audit.package, "verify", lambda _: {"kind": "desktop-core-pilot"})
    return source, candidate, output


def test_exact_collection_retains_verbatim_notices_and_blocks_release(fixture):
    source, candidate, output = fixture
    before = {p.relative_to(candidate): p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
    result = audit.create(candidate, output, source)
    assert result["components"] == 5 and result["notice_files"] == 6
    assert not result["release_ready"] and not result["publisher_authenticated"] and not result["license_clearance"]
    report = json.loads((output / "distribution-audit.json").read_text())
    assert all(c["redistribution_decision"] == "pending_owner_review" for c in report["components"])
    assert not report["network_accessed"] and not report["private_profile_read"]
    assert len(report["review_gaps"]) == 6
    assert "source" not in (output / "THIRD_PARTY_NOTICES.txt").read_text().splitlines()[0]
    assert b"caf\xc3\xa9" in (output / "THIRD_PARTY_NOTICES.txt").read_bytes()
    for entry in report["license_evidence"]:
        base = candidate if entry["scope"] == "candidate" else source
        assert (base / entry["path"]).read_bytes() == (output / entry["copy"]).read_bytes()
    assert before == {p.relative_to(candidate): p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
    assert audit.verify(candidate, output, source) == result


@pytest.mark.parametrize("kind", ["report", "notice", "extra", "missing", "claim", "candidate", "source"])
def test_verifier_rederives_evidence_and_refuses_tampering(fixture, kind):
    source, candidate, output = fixture
    audit.create(candidate, output, source)
    if kind == "report":
        write(output, "distribution-audit.json", {})
    elif kind == "notice":
        next((output / "notices").iterdir()).write_text("altered")
    elif kind == "extra":
        write(output, "extra.txt", "extra")
    elif kind == "missing":
        (output / "THIRD_PARTY_NOTICES.txt").unlink()
    elif kind == "claim":
        p = output / "distribution-audit.json"
        report = json.loads(p.read_text())
        report["license_clearance"] = True
        write(output, "distribution-audit.json", report)
    elif kind == "candidate":
        write(candidate, "LICENSE", "changed project notice")
    else:
        write(source, "node_modules/fixture/LICENSE", "changed source notice")
    with pytest.raises(ValueError):
        audit.verify(candidate, output, source)


@pytest.mark.parametrize("kind", ["npm_lock", "npm_version", "native_input", "python_version", "declared_missing", "declared_escape"])
def test_incompatible_or_missing_source_evidence_refuses_before_output(fixture, kind):
    source, candidate, output = fixture
    if kind == "npm_lock":
        write(source, "package-lock.json", {"packages": {}})
    elif kind == "npm_version":
        write(source, "node_modules/fixture/package.json", {"name": "fixture", "version": "2"})
    elif kind == "native_input":
        write(source, "node_modules/fixture/index.js", "changed")
    else:
        meta = candidate / "runtime/python/Lib/site-packages/fixture_pkg-1.0.0.dist-info/METADATA"
        text = meta.read_text()
        text = text.replace("Version: 1.0.0", "Version: 2") if kind == "python_version" else text.replace("License-File: LICENSE", "License-File: " + ("missing.txt" if kind == "declared_missing" else "../../secret"))
        meta.write_text(text)
    with pytest.raises(ValueError):
        audit.create(candidate, output, source)
    assert not output.exists()


def test_missing_undeclared_npm_notice_is_a_visible_gap_not_clearance(fixture):
    source, candidate, output = fixture
    (source / "node_modules/fixture/LICENSE").unlink()
    result = audit.create(candidate, output, source)
    assert result["missing_notice_components"] == [{"ecosystem": "npm", "name": "fixture", "version": "1.2.3", "metadata": "source:node_modules/fixture/package.json"}]
    assert not result["license_clearance"]
    assert "NOTICE EVIDENCE MISSING" in (output / "THIRD_PARTY_NOTICES.txt").read_text()


@pytest.mark.parametrize("kind", ["existing", "inside_candidate", "parent_candidate", "source"])
def test_outputs_never_replace_candidate_or_existing_evidence(fixture, kind):
    source, candidate, output = fixture
    if kind == "existing":
        output.mkdir()
        write(output, "keep.txt", "retain")
    elif kind == "inside_candidate":
        output = candidate / "audit"
    elif kind == "parent_candidate":
        output = candidate.parent
    else:
        output = source
    with pytest.raises(ValueError):
        audit.create(candidate, output, source)
    if kind == "existing":
        assert (output / "keep.txt").read_text() == "retain"


@pytest.mark.parametrize("name", ["../secret", "C:/secret", "/secret", "a\\b", "a/./b", "a//b", "a\nfile"])
def test_evidence_paths_refuse_noncanonical_and_escaping_names(name):
    with pytest.raises(ValueError):
        audit.relative(name)


def test_nested_scoped_package_ownership():
    assert audit.npm_owner("node_modules/@a/b/node_modules/@c/d/index.js") == "node_modules/@a/b/node_modules/@c/d"
    assert audit.npm_owner("electron/preload.js") is None


def test_hardlinked_notice_refuses_before_output(fixture):
    source, candidate, output = fixture
    notice = source / "node_modules/fixture/LICENSE"
    alias = source / "shared-notice"
    alias.hardlink_to(notice)
    with pytest.raises(ValueError):
        audit.create(candidate, output, source)
    assert not output.exists()


def test_candidate_integrity_failure_never_produces_evidence(fixture, monkeypatch):
    source, candidate, output = fixture
    def reject(_):
        raise ValueError("Changed candidate")
    monkeypatch.setattr(audit.package, "verify", reject)
    with pytest.raises(ValueError):
        audit.create(candidate, output, source)
    assert not output.exists()


def test_oversized_notice_is_not_silently_truncated(fixture, monkeypatch):
    source, candidate, output = fixture
    monkeypatch.setattr(audit, "MAX_NOTICE", 4)
    with pytest.raises(ValueError):
        audit.create(candidate, output, source)
    assert not output.exists()


def test_repeated_notice_output_is_bounded_before_join(fixture, monkeypatch):
    source, candidate, _ = fixture
    report, blobs = audit.collect(candidate, source)
    # Content-addressed copies deduplicate raw notices, but the readable document repeats attribution.
    report["components"] *= 100
    monkeypatch.setattr(audit, "MAX_EVIDENCE", 4096)
    with pytest.raises(ValueError, match="Combined notices"):
        audit.artifacts(report, blobs)


def test_exact_renderer_audit_omits_unused_lock_packages_and_keeps_asset_reviews(fixture, monkeypatch):
    source, candidate, output = fixture
    marker = json.loads((candidate / "desktop-pilot.json").read_text())
    marker["renderer_provenance_sha256"] = "fixture"
    write(candidate, "desktop-pilot.json", marker)
    write(candidate, "dist/renderer-provenance.json", {"inputs": [], "assets": [{"path": "public/model.task", "bytes": 1, "sha256": "fixture"}]})
    lock = json.loads((source / "package-lock.json").read_text())
    lock["packages"]["node_modules/unused"] = {"version": "1"}
    write(source, "package-lock.json", lock)
    write(candidate, "package-lock.json", lock)
    info = {"renderer_packages": ["node_modules/fixture"], "source_revalidated": True}
    monkeypatch.setattr(audit.package, "renderer_tool", lambda: SimpleNamespace(verify=lambda *_: info))
    result = audit.create(candidate, output, source)
    report = json.loads((output / "distribution-audit.json").read_text())
    assert result["components"] == 5
    assert report["renderer_provenance"] == info
    npm = [c for c in report["components"] if c["ecosystem"] == "npm"]
    assert [c["scope"] for c in npm] == ["native-and-renderer-bundled"]
    assert report["asset_reviews"][0]["decision"] == "pending_owner_review"
    assert "main/worker" in report["review_gaps"][0]
