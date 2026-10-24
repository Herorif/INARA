"""Offline provenance refuses drift and never turns collected evidence into approval."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("test_controller_provenance_tool", ROOT / "scripts/controller-provenance.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tool.encoded(value) if isinstance(value, dict) else value.encode())


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    candidate, source, output = (tmp_path / x for x in ("controller", "source", "evidence"))
    for base in (candidate, source):
        write(base, "LICENSE", "MIT fixture notice: café\n")
    for name in tool.EXTERNAL:
        write(source, name, "inert fixture source\n")
    write(candidate, "runtime/LICENSE.txt", "CPython fixture notice\n")
    write(candidate, "runtime/runtime-manifest.json", {"python_version": "fixture", "dependencies": {"fixture": "1"}})
    folder = "runtime/Lib/site-packages/fixture-1.dist-info/"
    write(candidate, folder + "METADATA", "Name: fixture\nVersion: 1\nLicense-Expression: MIT\nLicense-File: terms.txt\nProject-URL: Source, https://example.invalid/fixture\n")
    write(candidate, folder + "licenses/terms.txt", "Dependency fixture notice\n")
    write(candidate, "controller-manifest.json", {"files": [{"path": "runtime/python.exe", "bytes": 5, "sha256": "0" * 64}]})
    pin = tool.audit.digest((candidate / "controller-manifest.json").read_bytes())

    def verify(directory, expected):
        if tool.audit.digest((directory / "controller-manifest.json").read_bytes()) != expected:
            raise ValueError("Wrong manifest pin")
        return {"files": 6}

    monkeypatch.setattr(tool.controller, "verify", verify)
    monkeypatch.setattr(tool.controller, "SOURCE", ("LICENSE",))
    return candidate, pin, output, source


def test_bound_verbatim_notices_and_pending_separate_queue(fixture):
    candidate, pin, output, source = fixture
    before = {p.relative_to(candidate): p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
    result = tool.run("collect", candidate, pin, output, source)
    assert result["components"] == result["notice_files"] == 3
    assert result["pending_reviews"] == 5 + len(tool.EXTERNAL) and result["native_files"] == 1
    assert not result["release_authorized"]
    report = json.loads((output / "controller-provenance.json").read_bytes())
    queue = json.loads((output / "controller-review-queue.json").read_bytes())
    assert queue["report_sha256"] == tool.audit.digest((output / "controller-provenance.json").read_bytes())
    assert queue["decisions_recorded"] == 0
    assert all(s["status"] == "pending" for s in queue["subjects"])
    assert len({s["id"] for s in queue["subjects"]}) == len(queue["subjects"])
    assert all(not report[x] for x in ("network_accessed", "private_profile_read", "runtime_executed", "release_ready", "license_clearance", "publisher_authenticated"))
    for e in report["license_evidence"]:
        assert (candidate / e["path"]).read_bytes() == (output / e["copy"]).read_bytes()
    assert b"caf\xc3\xa9" in (output / "THIRD_PARTY_NOTICES.txt").read_bytes()
    assert before == {p.relative_to(candidate): p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
    assert tool.run("verify", candidate, pin, output, source) == result


@pytest.mark.parametrize("kind", ["report", "notice", "queue", "extra", "missing", "external", "bootstrap", "source", "metadata", "pin"])
def test_tampering_and_stale_inputs_refuse(fixture, kind):
    candidate, pin, output, source = fixture
    tool.run("collect", candidate, pin, output, source)
    if kind in {"report", "queue"}:
        name = "controller-" + ("provenance" if kind == "report" else "review-queue") + ".json"
        value = json.loads((output / name).read_bytes())
        if kind == "report":
            value["license_clearance"] = True
        else:
            value["subjects"][0]["status"] = "approved"
        write(output, name, value)
    elif kind == "notice":
        next((output / "notices").iterdir()).write_bytes(b"changed")
    elif kind == "extra":
        write(output, "unregistered.txt", "extra")
    elif kind == "missing":
        (output / "THIRD_PARTY_NOTICES.txt").unlink()
    elif kind == "external":
        write(output, "external/" + tool.EXTERNAL[0], "changed")
    elif kind == "bootstrap":
        write(source, tool.EXTERNAL[0], "changed")
    elif kind == "source":
        write(source, "LICENSE", "changed")
    elif kind == "metadata":
        write(candidate, "runtime/Lib/site-packages/fixture-1.dist-info/METADATA", "Name: fixture\nVersion: 2\n")
    else:
        pin = "f" * 64
    with pytest.raises(ValueError):
        tool.run("verify", candidate, pin, output, source)


@pytest.mark.parametrize("declared", ["missing.txt", "../../private.txt", "C:/private.txt"])
def test_declared_missing_or_escaping_notice_refuses_before_output(fixture, declared):
    candidate, pin, output, source = fixture
    path = candidate / "runtime/Lib/site-packages/fixture-1.dist-info/METADATA"
    path.write_text(path.read_text().replace("terms.txt", declared))
    with pytest.raises(ValueError):
        tool.run("collect", candidate, pin, output, source)
    assert not output.exists()


def test_undeclared_missing_notice_becomes_pending_subject(fixture):
    candidate, pin, output, source = fixture
    path = candidate / "runtime/Lib/site-packages/fixture-1.dist-info/METADATA"
    path.write_text("Name: fixture\nVersion: 1\n")
    result = tool.run("collect", candidate, pin, output, source)
    assert result["missing_notice_components"][0]["name"] == "fixture"
    assert result["pending_reviews"] == 6 + len(tool.EXTERNAL) and not result["release_authorized"]


@pytest.mark.parametrize("location", ["existing", "inside", "parent", "source"])
def test_unsafe_output_or_overwrite_refuses(fixture, location):
    candidate, pin, output, source = fixture
    if location == "existing":
        output.mkdir()
    elif location == "inside":
        output = candidate / "audit"
    elif location == "parent":
        output = candidate.parent
    else:
        output = source
    with pytest.raises(ValueError):
        tool.run("collect", candidate, pin, output, source)


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "incomplete", "shared"])
def test_incomplete_duplicate_unknown_or_shared_metadata_refuses(fixture, kind):
    candidate, pin, output, source = fixture
    site = "runtime/Lib/site-packages/"
    original = candidate / site / "fixture-1.dist-info/METADATA"
    if kind == "duplicate":
        write(candidate, site + "duplicate.dist-info/METADATA", original.read_text())
    elif kind == "unknown":
        original.write_text(original.read_text().replace("Name: fixture", "Name: unknown"))
    elif kind == "incomplete":
        manifest = candidate / "runtime/runtime-manifest.json"
        value = json.loads(manifest.read_bytes())
        value["dependencies"]["missing"] = "1"
        write(candidate, "runtime/runtime-manifest.json", value)
    else:
        import os

        os.link(original, candidate / "shared-metadata.txt")
    with pytest.raises(ValueError):
        tool.run("collect", candidate, pin, output, source)
    assert not output.exists()
