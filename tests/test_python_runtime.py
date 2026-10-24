"""Curated runtime assembly fixtures; no package install, download or model execution."""

import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import pytest

spec = importlib.util.spec_from_file_location(
    "python_runtime", Path(__file__).resolve().parents[1] / "scripts/python-runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def pe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = bytearray(256)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 60, 128)
    value[128:134] = b"PE\x00\x00\x64\x86"
    path.write_bytes(value)


def record(site, extras=None):
    data = {
        "fixturepkg/__init__.py": b"VALUE = 1\n",
        "fixture_pkg-1.0.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: fixture-pkg\nVersion: 1.0.0\n",
        "fixture_pkg-1.0.0.dist-info/LICENSE": b"fixture license",
        **(extras or {}),
    }
    rows = []
    for name, raw in data.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows.append(
            [
                name,
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("="),
                len(raw),
            ]
        )
    output = io.StringIO(newline="")
    csv.writer(output).writerows([*rows, ["fixture_pkg-1.0.0.dist-info/RECORD", "", ""]])
    (site / "fixture_pkg-1.0.0.dist-info/RECORD").write_text(output.getvalue(), newline="")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("Assembler pinned to Python 3.12")
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    root = tmp_path / "source"
    root.mkdir()
    (root / "requirements-core.lock").write_text("fixture-pkg==1.0.0\n")
    (root / "scripts").mkdir()
    (root / "scripts/python-runtime-probe.py").write_text("# synthetic probe; not executed\n")
    base = root / "base"
    base.mkdir()
    for name in runtime.BASE_FILES:
        pe(base / name)
    for name in ("_ctypes.pyd", "_ssl.pyd", "_sqlite3.pyd"):
        pe(base / "DLLs" / name)
    (base / "Lib/encodings").mkdir(parents=True)
    (base / "Lib/encodings/__init__.py").write_text("# fixture standard library")
    (base / "Lib/sitecustomize.py").write_text("raise RuntimeError('must not be copied')")
    site = root / "environment/Lib/site-packages"
    record(site)
    (site / "unlocked_development.py").write_text("PRIVATE_FIXTURE")
    destination = root / ".runtime/python-runtimes/pilot"
    return root, base, site, destination


def assemble(inputs):
    root, base, site, destination = inputs
    return runtime.assemble(destination, root, base, site)


def test_curated_assembly_is_isolated_and_does_not_copy_environment(inputs):
    result = assemble(inputs)
    root, _, _, destination = inputs
    assert result["integrity"] == "passed" and result["dependencies"] == 1
    assert result["runtime_execution_verified"] is False
    assert not (destination / "pyvenv.cfg").exists()
    assert not (destination / "Lib/site-packages/unlocked_development.py").exists()
    assert (destination / "python312._pth").read_text() == runtime.PTH
    with runtime.zipfile.ZipFile(destination / "python312.zip") as archive:
        assert "sitecustomize.py" not in archive.namelist()
    assert runtime.verify(destination, root / "requirements-core.lock")["integrity"] == "passed"


@pytest.mark.parametrize(
    "kind",
    [
        "version",
        "hash",
        "escape",
        "pth",
        "missing_record",
            "missing_payload",
        "base_venv",
        "wrong_architecture",
        "reuse",
        "outside",
    ],
)
def test_invalid_local_inputs_or_destination_never_produce_valid_runtime(inputs, kind, tmp_path):
    root, base, site, destination = inputs
    if kind == "version":
        (root / "requirements-core.lock").write_text("fixture-pkg==2.0.0")
    elif kind == "hash":
        (site / "fixturepkg/__init__.py").write_text("changed")
    elif kind == "escape":
        with (site / "fixture_pkg-1.0.0.dist-info/RECORD").open("a") as stream:
            stream.write("../../private.txt,,\n")
    elif kind == "pth":
        record(site, {"execute.pth": b"import arbitrary"})
    elif kind == "missing_record":
        (site / "fixture_pkg-1.0.0.dist-info/RECORD").unlink()
    elif kind == "missing_payload":
        (site / "fixturepkg/__init__.py").unlink()
    elif kind == "base_venv":
        (base / "pyvenv.cfg").write_text("home=elsewhere")
    elif kind == "wrong_architecture":
        (base / "python.exe").write_bytes(b"not PE")
    elif kind == "reuse":
        destination.mkdir(parents=True)
        (destination / "keep").write_text("preserve")
    elif kind == "outside":
        destination = tmp_path / "outside"
    with pytest.raises(ValueError):
        runtime.assemble(destination, root, base, site)
    assert not (destination / "runtime-manifest.json").exists()
    if kind == "reuse":
        assert (destination / "keep").read_text() == "preserve"


def test_windows_shims_private_origin_and_cache_are_omitted_from_new_record(inputs):
    _, _, site, destination = inputs
    record(
        site,
        {
            "fixture_pkg-1.0.0.dist-info/direct_url.json": b"PRIVATE_FIXTURE",
            "fixturepkg/__pycache__/old.pyc": b"cache",
        },
    )
    with (site / "fixture_pkg-1.0.0.dist-info/RECORD").open("a") as stream:
        stream.write("../../Scripts/fixture.exe,,\n")
    assemble(inputs)
    target = destination / "Lib/site-packages"
    text = (target / "fixture_pkg-1.0.0.dist-info/RECORD").read_text()
    assert "direct_url" not in text and "Scripts" not in text and "__pycache__" not in text
    assert "PRIVATE_FIXTURE" not in json.dumps(runtime.verify(destination))


@pytest.mark.parametrize(
    "kind", ["changed", "extra", "missing", "isolation", "signed", "duplicate", "traversal", "lock"]
)
def test_runtime_drift_unsupported_claims_and_lock_changes_reject(inputs, kind):
    assemble(inputs)
    root, _, _, destination = inputs
    path = destination / "runtime-manifest.json"
    manifest = json.loads(path.read_text())
    if kind == "changed":
        (destination / "Lib/site-packages/fixturepkg/__init__.py").write_text("changed")
    elif kind == "extra":
        (destination / "unexpected.py").write_text("unexpected")
    elif kind == "missing":
        (destination / "python.exe").unlink()
    elif kind == "isolation":
        (destination / "python312._pth").write_text(runtime.PTH + "import site\n")
    elif kind == "signed":
        manifest["signed"] = True
    elif kind == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif kind == "traversal":
        manifest["files"][0]["path"] = "../escape"
    elif kind == "lock":
        (root / "requirements-core.lock").write_text("fixture-pkg==2.0.0")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        runtime.verify(destination, root / "requirements-core.lock")


def test_dynamic_or_duplicate_lock_versions_reject(tmp_path):
    path = tmp_path / "lock"
    for text in ("fixture>=1", "fixture==1\nfixture==2", ""):
        path.write_text(text)
        with pytest.raises(ValueError):
            runtime.locked(path)
