"""Observed build graphs, copied assets and source/output drift checks."""

import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "renderer", Path(__file__).resolve().parents[1] / "scripts/renderer-provenance.py"
)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_build(root):
    for name in (
        "index.html",
        "package.json",
        "package-lock.json",
        "vite.config.js",
        "scripts/renderer-provenance.cjs",
        "scripts/renderer-provenance.py",
        "src/main.js",
    ):
        if not (root / name).exists():
            write(root, name, "fixture")
    write(root, "docs/ASSET_OWNERSHIP.json", '{"format":1,"entries":[]}')
    write(root, "dist/index.html", "compiled HTML fixture")
    write(root, "dist/main.js", "compiled fixture")

    def record(path, base):
        return {
            "path": path.relative_to(base).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": renderer.sha(path),
        }

    inputs = [
        record(root / name, root)
        for name in (
            "index.html",
            "package.json",
            "package-lock.json",
            "vite.config.js",
            "scripts/renderer-provenance.cjs",
            "docs/ASSET_OWNERSHIP.json",
            "src/main.js",
        )
    ]
    value = {
        "format": 1,
        "kind": "inara-renderer-build",
        "coverage": "observed-rollup-graph",
        "redistribution_cleared": False,
        "reproducible_build_claimed": False,
        "inputs": inputs,
        "outputs": [
            record(p, root / "dist")
            for p in (root / "dist").rglob("*")
            if p.is_file() and p.name != renderer.NAME
        ],
        "graph": [
            {
                "id": "main|src/main.js",
                "target": "main",
                "path": "src/main.js",
                "imports": [],
                "external": False,
            }
        ],
        "chunks": [{"path": "main.js", "target": "main", "modules": ["main|src/main.js"]}],
        "public_copies": [],
        "byte_identical_copies": [],
        "assets": [],
        "ownership_registry": {"format": 1, "entries": []},
    }
    write(root, "dist/" + renderer.NAME, json.dumps(value))
    return value


@pytest.fixture
def built(tmp_path):
    root = tmp_path / "source"
    fixture_build(root)
    return root


def test_source_and_detached_output_checks(built):
    result = renderer.verify(built / "dist", built)
    assert (
        result["source_revalidated"]
        and result["modules"] == 1
        and not result["redistribution_cleared"]
    )
    assert not renderer.verify(built / "dist")["source_revalidated"]


@pytest.mark.parametrize(
    "kind",
    [
        "output_changed",
        "output_extra",
        "output_missing",
        "source_changed",
        "source_added",
        "source_removed",
        "input_escape",
        "output_escape",
        "input_duplicate",
        "graph_open",
        "graph_input",
        "chunk_module",
        "chunk_output",
        "virtual_leak",
        "target",
        "false_clearance",
        "false_reproducibility",
        "forged_ownership",
    ],
)
def test_drift_and_inconsistent_graphs_refuse(built, kind):
    p = built / "dist" / renderer.NAME
    value = json.loads(p.read_text())
    if kind == "output_changed":
        write(built, "dist/main.js", "changed")
    elif kind == "output_extra":
        write(built, "dist/extra.js", "extra")
    elif kind == "output_missing":
        (built / "dist/main.js").unlink()
    elif kind == "source_changed":
        write(built, "src/main.js", "changed")
    elif kind == "source_added":
        write(built, "src/extra.js", "extra")
    elif kind == "source_removed":
        (built / "src/main.js").unlink()
    elif kind == "input_escape":
        value["inputs"][0]["path"] = "../private"
    elif kind == "output_escape":
        value["outputs"][0]["path"] = "../private"
    elif kind == "input_duplicate":
        value["inputs"].append(value["inputs"][0])
    elif kind == "graph_open":
        value["graph"][0]["imports"] = ["missing"]
    elif kind == "graph_input":
        value["graph"][0]["path"] = "missing.js"
    elif kind == "chunk_module":
        value["chunks"][0]["modules"] = ["missing"]
    elif kind == "chunk_output":
        value["chunks"][0]["path"] = "missing.js"
    elif kind == "virtual_leak":
        value["graph"][0].update(path=None, id="C:/secret")
    elif kind == "target":
        value["graph"][0]["target"] = "other"
    elif kind == "false_clearance":
        value["redistribution_cleared"] = True
    elif kind == "false_reproducibility":
        value["reproducible_build_claimed"] = True
    else:
        value["ownership_registry"]["entries"] = [{"path": "src/main.js", "decision": "approved"}]
    p.write_text(json.dumps(value))
    with pytest.raises((ValueError, KeyError)):
        renderer.verify(built / "dist", built)


def test_copied_model_requires_complete_identical_provenance(built):
    write(built, "public/test.task", "model fixture")
    write(built, "dist/test.task", "model fixture")
    p = built / "dist" / renderer.NAME
    value = json.loads(p.read_text())
    raw = {"bytes": 13, "sha256": renderer.sha(built / "public/test.task")}
    item = {"path": "public/test.task", **raw}
    value["inputs"].append(item)
    value["assets"].append(item)
    value["outputs"].append({"path": "test.task", **raw})
    value["public_copies"].append({"input": "public/test.task", "output": "test.task", **raw})
    value["byte_identical_copies"] = list(value["public_copies"])
    p.write_text(json.dumps(value))
    assert renderer.verify(built / "dist", built)["pending_asset_reviews"] == 1
    value["public_copies"] = []
    p.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        renderer.verify(built / "dist", built)


def test_worker_chunks_preserve_target_and_npm_origin(built):
    write(built, "node_modules/@vendor/worker/index.js", "worker raw")
    write(built, "dist/worker.js", "worker compiled")
    p = built / "dist" / renderer.NAME
    value = json.loads(p.read_text())
    name = "node_modules/@vendor/worker/index.js"
    value["inputs"].append({"path": name, "bytes": 10, "sha256": renderer.sha(built / name)})
    value["outputs"].append(
        {"path": "worker.js", "bytes": 15, "sha256": renderer.sha(built / "dist/worker.js")}
    )
    value["graph"].append(
        {
            "id": "worker-1|" + name,
            "target": "worker-1",
            "path": name,
            "imports": [],
            "external": False,
        }
    )
    value["chunks"].append(
        {"path": "worker.js", "target": "worker-1", "modules": ["worker-1|" + name]}
    )
    p.write_text(json.dumps(value))
    result = renderer.verify(built / "dist", built)
    assert result["worker_targets"] == 1 and result["renderer_packages"] == [
        "node_modules/@vendor/worker"
    ]


def test_shared_output_refuses(built):
    alias = built / "alias"
    alias.hardlink_to(built / "dist/main.js")
    with pytest.raises(ValueError):
        renderer.verify(built / "dist", built)
