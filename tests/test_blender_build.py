"""scripts/blender-build.py: discovery, version gate, arguments, staging and publish.

Subprocess is faked; no Blender needed. The one live test is opt-in
(JARVIS_LIVE_BLENDER_TESTS=1) and runs a tiny scene twice to prove byte-identical GLBs.
"""

import importlib.util
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "blender_build", Path(__file__).resolve().parents[1] / "scripts/blender-build.py"
)
bb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bb)

SCENE = "import sys\n"


class FakeBlender:
    """Stands in for subprocess.run: answers --version and 'renders' scene outputs."""

    def __init__(self, version="Blender 5.2.3 LTS\n\tbuild date: x\n", outputs=None, code=0):
        self.version = version
        self.outputs = {"thing.glb": b"glTF-fixture"} if outputs is None else outputs
        self.code = code
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout=self.version, stderr="")
        out = Path(argv[argv.index("--out") + 1])
        for name, data in self.outputs.items():
            (out / name).write_bytes(data)
        kwargs["stdout"].write("scene ran\n")
        return SimpleNamespace(returncode=self.code)


@pytest.fixture
def root(tmp_path):
    scenes = tmp_path / "art" / "blender"
    scenes.mkdir(parents=True)
    (scenes / "tiny.py").write_text(SCENE)
    return tmp_path


@pytest.fixture
def blender(tmp_path):
    exe = tmp_path / "bin" / "blender.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    return exe


def exit_code(*args, **kwargs):
    """main() returns its code; argparse usage errors exit through SystemExit."""
    try:
        return bb.main(*args, **kwargs)
    except SystemExit as error:
        return error.code


def env(blender, **extra):
    return {"JARVIS_BLENDER": str(blender), "SYSTEMROOT": r"C:\Windows", **extra}


# --- discovery ------------------------------------------------------------------------
def test_env_var_wins_over_default(blender, monkeypatch, tmp_path):
    default = tmp_path / "default.exe"
    default.write_bytes(b"")
    monkeypatch.setattr(bb, "DEFAULT_BLENDER", default)
    assert bb.find_blender({"JARVIS_BLENDER": str(blender)}) == blender


def test_env_var_pointing_nowhere_is_refused_not_ignored(monkeypatch, tmp_path):
    default = tmp_path / "default.exe"
    default.write_bytes(b"")
    monkeypatch.setattr(bb, "DEFAULT_BLENDER", default)
    with pytest.raises(bb.BuildError, match="JARVIS_BLENDER"):
        bb.find_blender({"JARVIS_BLENDER": str(tmp_path / "missing.exe")})


def test_default_used_when_env_unset_or_blank(monkeypatch, tmp_path):
    default = tmp_path / "default.exe"
    default.write_bytes(b"")
    monkeypatch.setattr(bb, "DEFAULT_BLENDER", default)
    assert bb.find_blender({}) == default
    assert bb.find_blender({"JARVIS_BLENDER": "  "}) == default


def test_missing_everywhere_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(bb, "DEFAULT_BLENDER", tmp_path / "nope.exe")
    with pytest.raises(bb.BuildError, match="Blender not found"):
        bb.find_blender({})


# --- version --------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("Blender 5.2.3 LTS\n\tbuild date: 2026-10-22\n", "5.2.3"),
    ("noise\nBlender 5.2.0\n", "5.2.0"),
    ("Blender 5.2.11 LTS (hash x)\n", "5.2.11"),
])
def test_supported_versions(text, expected):
    assert bb.check_version(bb.parse_version(text)) == expected


@pytest.mark.parametrize("text", ["Blender 4.2.9 LTS", "Blender 5.3.0", "Blender 6.2.3",
                                  "Blender 5.20.1"])
def test_other_versions_are_refused(text):
    with pytest.raises(bb.BuildError, match=r"requires 5\.2\.x"):
        bb.check_version(bb.parse_version(text))


def test_unreadable_version_is_refused():
    with pytest.raises(bb.BuildError, match="Could not read"):
        bb.parse_version("Something else 5.2.3")


def test_wrong_version_never_runs_the_scene(root, blender, capsys):
    fake = FakeBlender(version="Blender 4.5.1 LTS\n")
    assert bb.main(["tiny"], environ=env(blender), root=root, run=fake) == 1
    assert len(fake.calls) == 1 and "--version" in fake.calls[0][0]
    assert "4.5.1 is not supported" in capsys.readouterr().err
    assert not (root / ".runtime/blender/review/tiny.manifest.json").exists()


# --- running a scene ------------------------------------------------------------------
def test_build_runs_headless_with_clean_env_and_stages_outputs(root, blender, capsys):
    fake = FakeBlender()
    parent_env = env(blender, OPENAI_API_KEY="secret", PYTHONPATH="evil",
                     PATH=r"C:\tools;C:\evil", APPDATA=r"C:\Users\x\AppData\Roaming")
    assert bb.main(["tiny", "--", "--only", "glb"], environ=parent_env, root=root,
                   run=fake) == 0
    argv, kwargs = fake.calls[1]
    staging = root / ".runtime/blender/build/tiny"
    assert argv == [str(blender), "-b", "--factory-startup", "-noaudio",
                    "--python-exit-code", "1", "--python",
                    str(root / "art/blender/tiny.py"), "--", "--out", str(staging),
                    "--only", "glb"]
    child = kwargs["env"]
    assert "OPENAI_API_KEY" not in child and "PYTHONPATH" not in child
    assert "evil" not in child["PATH"] and "tools" not in child["PATH"]
    assert child["APPDATA"] == r"C:\Users\x\AppData\Roaming"   # GPU driver caches
    assert child["BLENDER_USER_RESOURCES"] == str(root / ".runtime/blender/home")
    assert kwargs["cwd"] == str(staging)
    review = root / ".runtime/blender/review"
    assert (review / "thing.glb").read_bytes() == b"glTF-fixture"
    manifest = json.loads((review / "tiny.manifest.json").read_text())
    assert manifest["blender_version"] == "5.2.3"
    assert manifest["generator"] == "art/blender/tiny.py"
    assert manifest["generator_sha256"] == bb.sha256(root / "art/blender/tiny.py")
    assert manifest["outputs"]["thing.glb"]["sha256"] == bb.sha256(review / "thing.glb")
    log = (root / ".runtime/blender/logs/tiny.log").read_text()
    assert "scene ran" in log and "--factory-startup" in log
    assert "Blender 5.2.3" in capsys.readouterr().out


def test_rebuild_drops_outputs_the_scene_no_longer_makes(root, blender):
    bb.main(["tiny"], environ=env(blender), root=root,
             run=FakeBlender(outputs={"a.png": b"1", "b.png": b"2"}))
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender(outputs={"a.png": b"3"}))
    review = root / ".runtime/blender/review"
    assert (review / "a.png").read_bytes() == b"3" and not (review / "b.png").exists()


def test_failed_scene_reports_log_and_writes_no_manifest(root, blender, capsys):
    assert bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender(code=1)) == 1
    assert "tiny.log" in capsys.readouterr().err
    assert not (root / ".runtime/blender/review/tiny.manifest.json").exists()


def test_scene_without_outputs_fails(root, blender):
    assert bb.main(["tiny"], environ=env(blender), root=root,
                   run=FakeBlender(outputs={})) == 1


def test_timeout_is_reported_not_raised(root, blender, capsys):
    def slow(argv, **kwargs):
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout="Blender 5.2.3\n")
        raise subprocess.TimeoutExpired(argv, 5)
    assert bb.main(["tiny", "--timeout", "5"], environ=env(blender), root=root, run=slow) == 1
    assert "timed out" in capsys.readouterr().err


# --- arguments ------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["../tiny", "Tiny", "_lib", "tiny.py", "a b", "-x", ""])
def test_bad_scene_names_are_refused(root, blender, name):
    fake = FakeBlender()
    assert exit_code([name] if name else ["--", "x"], environ=env(blender), root=root,
                     run=fake) != 0
    assert fake.calls == []


def test_unknown_scene_is_refused(root, blender, capsys):
    fake = FakeBlender()
    assert bb.main(["nothere"], environ=env(blender), root=root, run=fake) == 1
    assert "No scene script" in capsys.readouterr().err and fake.calls == []


@pytest.mark.parametrize("extra", [["--out", "C:/elsewhere"], ["bad\nline"]])
def test_scene_arguments_are_checked(root, blender, extra):
    fake = FakeBlender()
    assert bb.main(["tiny", "--", *extra], environ=env(blender), root=root, run=fake) == 1
    assert fake.calls == []


def test_list_shows_scenes(root, capsys):
    (root / "art/blender/_helper.py").write_text("")
    (root / "art/blender/other-scene.py").write_text("")
    assert bb.main(["--list"], environ={}, root=root) == 0
    assert capsys.readouterr().out.split() == ["other-scene", "tiny"]


def test_timeout_bounds(root, blender):
    assert bb.main(["tiny", "--timeout", "0"], environ=env(blender), root=root,
                   run=FakeBlender()) == 1


# --- publish --------------------------------------------------------------------------
def approve(root, mapping):
    (root / "art/blender/publish.json").write_text(
        json.dumps({"format": 1, "scenes": {"tiny": mapping}}))


def test_publish_requires_approval(root, blender, capsys):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1
    assert "No approved outputs" in capsys.readouterr().err


def test_publish_refuses_scene_args(root, capsys):
    assert bb.main(["tiny", "--publish", "--", "--only", "glb"], environ={}, root=root) == 1
    assert "no scene arguments" in capsys.readouterr().err


def test_publish_copies_reviewed_bytes_and_prints_ownership_entry(root, blender, capsys):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    approve(root, {"thing.glb": "public/models/thing.glb"})
    capsys.readouterr()
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 0
    assert (root / "public/models/thing.glb").read_bytes() == b"glTF-fixture"
    out = capsys.readouterr().out
    entry = json.loads(out[out.index("["):])[0]
    assert entry["path"] == "public/models/thing.glb"
    assert entry["sha256"] == bb.sha256(root / "public/models/thing.glb")
    assert "art/blender/tiny.py" in entry["origin"] and "Blender 5.2.3" in entry["origin"]
    assert (entry["owner"], entry["license_evidence"], entry["decision"]) == (None, [], "pending")


def test_publish_accepts_native_setup_art_without_an_ownership_entry(root, blender, capsys):
    outputs = {"thing.glb": b"glTF-fixture", "banner.png": b"png-fixture"}
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender(outputs=outputs))
    approve(root, {"thing.glb": "src/assets/models/thing.glb",
                   "banner.png": "native/setup/setup-banner.png"})
    capsys.readouterr()
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 0
    assert (root / "native/setup/setup-banner.png").read_bytes() == b"png-fixture"
    out = capsys.readouterr().out
    assert "published banner.png -> native/setup/setup-banner.png" in out
    # Only renderer assets get docs/ASSET_OWNERSHIP.json entries.
    entries = json.loads(out[out.index("["):])
    assert [entry["path"] for entry in entries] == ["src/assets/models/thing.glb"]


@pytest.mark.parametrize("target", ["native/x.png", "native/setup", "native/setup/",
                                    "native/setup/../x.png", "native/setupx/x.png"])
def test_publish_refuses_other_native_destinations(root, blender, target):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    approve(root, {"thing.glb": target})
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1


def test_publish_refuses_when_script_changed_since_review(root, blender, capsys):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    approve(root, {"thing.glb": "public/models/thing.glb"})
    (root / "art/blender/tiny.py").write_text(SCENE + "# edited\n")
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1
    assert "changed since review" in capsys.readouterr().err
    assert not (root / "public/models/thing.glb").exists()


def test_publish_refuses_tampered_output(root, blender):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    approve(root, {"thing.glb": "public/models/thing.glb"})
    (root / ".runtime/blender/review/thing.glb").write_bytes(b"other")
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1


@pytest.mark.parametrize("target", ["../outside.glb", "backend/x.glb", "public/../x.glb",
                                    "public\\x.glb", "/public/x.glb", "public//x.glb"])
def test_publish_refuses_unapproved_destinations(root, blender, target):
    bb.main(["tiny"], environ=env(blender), root=root, run=FakeBlender())
    approve(root, {"thing.glb": target})
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1


def test_publish_without_review_is_refused(root, capsys):
    approve(root, {"thing.glb": "public/models/thing.glb"})
    assert bb.main(["tiny", "--publish"], environ={}, root=root) == 1
    assert "build it first" in capsys.readouterr().err


# --- the repository's approvals -------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]


def test_published_core_outputs_match_their_ownership_entries():
    approvals = json.loads((REPO / "art/blender/publish.json").read_text(encoding="utf-8"))
    targets = approvals["scenes"]["jarvis-core"]
    assert targets == {
        "jarvis-core.glb": "src/assets/models/jarvis-core.glb",
        "splash-core-720.png": "src/assets/brand/splash-core-720.png",
        "lock-dial-720.png": "src/assets/brand/lock-dial-720.png",
        "setup-banner-410x1700.png": "native/setup/setup-banner.png",
    }
    assert bb.publish_targets(REPO, "jarvis-core") == targets
    entries = {e["path"]: e for e in json.loads(
        (REPO / "docs/ASSET_OWNERSHIP.json").read_text(encoding="utf-8"))["entries"]}
    origins = set()
    for target in targets.values():
        if not target.startswith(bb.RENDERER_PREFIXES):
            assert target not in entries, target   # Setup art is not a renderer asset
            continue
        entry = entries[target]
        assert entry["sha256"] == bb.sha256(REPO / target), target
        assert (entry["owner"], entry["license_evidence"], entry["decision"]) == (None, [], "pending")
        origins.add(entry["origin"])
    # One review build published them all: the same generator hash and Blender version.
    assert len(origins) == 1
    assert re.fullmatch(r"owner-generated: art/blender/jarvis-core\.py \(sha256 [0-9a-f]{64}\), "
                        r"Blender 5\.2\.\d+", origins.pop())


# --- optional: real Blender -----------------------------------------------------------
TINY_SCENE = '''
import sys
from pathlib import Path
import bpy
out = Path(sys.argv[sys.argv.index("--out") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("ring")
mesh.from_pydata([(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1)],
                 [(0, 1), (1, 2), (2, 3), (3, 0)], [])
bpy.context.scene.collection.objects.link(bpy.data.objects.new("ring", mesh))
bpy.ops.export_scene.gltf(filepath=str(out / "tiny.glb"), export_format="GLB",
                          use_mesh_edges=True, export_animations=False)
'''


@pytest.mark.live_blender
def test_real_blender_tiny_scene_is_byte_identical(tmp_path):
    import os

    root = tmp_path / "repo"
    (root / "art/blender").mkdir(parents=True)
    (root / "art/blender/tiny.py").write_text(TINY_SCENE)
    hashes = []
    for _ in range(2):
        manifest = bb.build(root, "tiny", [], os.environ, timeout=300)
        hashes.append(manifest["outputs"]["tiny.glb"]["sha256"])
    assert hashes[0] == hashes[1]
    raw = (root / ".runtime/blender/review/tiny.glb").read_bytes()
    assert raw[:4] == b"glTF" and b'"mode":1' in raw
