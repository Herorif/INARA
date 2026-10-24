"""Offline version slots: crash recovery, explicit selection, data ownership and leases."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import pytest

spec = importlib.util.spec_from_file_location(
    "desktop_install", Path(__file__).resolve().parents[1] / "scripts/desktop-install.py"
)
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    def verify(path):
        value = json.loads((path / "desktop-pilot.json").read_text())
        for name, text in value["files"].items():
            if (path / name).read_text() != text:
                raise ValueError("fixture integrity changed")
        return {"kind": value["kind"], "self_contained": value["kind"] == "desktop-core-pilot"}

    monkeypatch.setattr(install.package, "verify", verify)
    return install.Installation.create(tmp_path / "installation")


def candidate(tmp_path, name="one", kind="desktop-core-pilot"):
    root = tmp_path / name
    root.mkdir()
    (root / "runtime/python").mkdir(parents=True)
    (root / "runtime/python/python.exe").write_text("fixture")
    (root / "backend").mkdir()
    (root / "backend/resident_main.py").write_text("fixture " + name)
    (root / "desktop-pilot.json").write_text(
        json.dumps(
            {
                "kind": kind,
                "files": {
                    "backend/resident_main.py": "fixture " + name,
                    "runtime/python/python.exe": "fixture",
                },
            }
        )
    )
    return root


def add(manager, tmp_path, name="one"):
    return manager.install(candidate(tmp_path, name))["slot"]


def test_install_never_selects_and_rollback_restores_separate_original_data(manager, tmp_path):
    a = add(manager, tmp_path)
    assert manager.status()["selected"] is None
    manager.activate(a)
    state = manager.load()
    data_a = manager.data(state, a)
    (data_a / "settings.json").write_text("original A")
    b = add(manager, tmp_path, "two")
    assert manager.status()["selected"] == a
    manager.activate(b)
    data_b = manager.data(manager.load(), b)
    assert data_b != data_a and not (data_b / "settings.json").exists()
    (data_b / "settings.json").write_text("B remains separate")
    assert manager.activate(rollback=True)["selected"] == a
    assert (data_a / "settings.json").read_text() == "original A"
    assert (data_b / "settings.json").read_text() == "B remains separate"
    assert manager.deactivate()["data_retained"]
    assert manager.status()["selected"] is None
    assert (manager.root / "versions" / a).is_dir()


@pytest.mark.parametrize("point", ["partial_copy", "complete_copy", "renamed", "owned_data"])
def test_interrupted_install_preserves_selection_and_recovers_only_complete_copy(
    manager, tmp_path, monkeypatch, point
):
    a = add(manager, tmp_path)
    manager.activate(a)
    source = candidate(tmp_path, "two")
    slot = install.package.release.sha256(source / "desktop-pilot.json")
    pending = manager.root / "transactions" / slot
    if point in {"partial_copy", "complete_copy"}:
        original = shutil.copytree

        def crash_copy(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            if Path(dst) != pending:
                return result
            if point == "partial_copy":
                (dst / "backend/resident_main.py").unlink()
            raise OSError("simulated power loss")

        monkeypatch.setattr(install.shutil, "copytree", crash_copy)
    else:
        original = manager.register

        def crash_register(state, value):
            if point == "owned_data":
                manager.data(state, value, create=True)
            raise OSError("simulated power loss")

        monkeypatch.setattr(manager, "register", crash_register)
    with pytest.raises(OSError):
        manager.install(source)
    assert manager.status()["selected"] == a
    assert manager.status()["recovery_candidates"]
    if point == "partial_copy":
        with pytest.raises((OSError, ValueError)):
            manager.recover(slot)
        assert pending.is_dir()
    else:
        if point in {"renamed", "owned_data"}:
            monkeypatch.setattr(manager, "register", original)
        result = manager.recover(slot)
        assert not result["activated"] and manager.status()["selected"] == a
        assert slot in manager.status()["slots"]


@pytest.mark.parametrize(
    "kind", ["manifest", "payload", "ownership", "unknown", "traversal", "linked_data"]
)
def test_activation_refuses_changed_or_unknown_slot_without_switch(manager, tmp_path, kind):
    a = add(manager, tmp_path)
    manager.activate(a)
    b = add(manager, tmp_path, "two")
    chosen = b
    if kind == "manifest":
        (manager.root / "versions" / b / "desktop-pilot.json").write_text("{}")
    elif kind == "payload":
        (manager.root / "versions" / b / "backend/resident_main.py").write_text("changed")
    elif kind == "ownership":
        (manager.root / "data" / b / ".inara-data.json").write_text("{}")
    elif kind == "unknown":
        chosen = "0" * 64
    elif kind == "traversal":
        chosen = "../outside"
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        # Windows junctions need no symlink privilege.
        import subprocess

        subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(manager.root / "data" / b / "projects"),
                str(outside),
            ],
            check=True,
            capture_output=True,
        )
    with pytest.raises((ValueError, OSError)):
        manager.activate(chosen)
    assert manager.load()["current"] == a


def test_busy_lock_blocks_mutation_and_releases_after_exception(manager, tmp_path):
    a = add(manager, tmp_path)
    with manager.locked():
        with pytest.raises(ValueError, match="busy"):
            manager.activate(a)
    manager.activate(a)
    with pytest.raises(ValueError):
        with manager.locked():
            raise ValueError("fixture")
    assert manager.status()["selected"] == a


def test_no_existing_root_duplicate_copy_or_workspace_runtime_adoption(manager, tmp_path):
    a = add(manager, tmp_path)
    with pytest.raises(ValueError):
        install.Installation.create(manager.root)
    with pytest.raises(ValueError):
        manager.install(tmp_path / "one")
    with pytest.raises(ValueError):
        manager.install(candidate(tmp_path, "external", "desktop-workspace-pilot"))
    with pytest.raises(ValueError):
        manager.install(manager.root / "versions" / a)
    assert manager.status()["slots"] == [a]


@pytest.mark.parametrize("kind", ["format", "unknown_field", "slot_path", "pointer", "generation"])
def test_invalid_state_is_preserved_and_never_repaired_by_guessing(manager, kind):
    path = manager.root / "installation.json"
    state = manager.load()
    if kind == "format":
        state["format"] = 2
    elif kind == "unknown_field":
        state["profile"] = "private"
    elif kind == "slot_path":
        state["slots"] = {"../outside": {}}
    elif kind == "pointer":
        state["current"] = "0" * 64
    else:
        state["generation"] = True
    text = json.dumps(state)
    path.write_text(text)
    with pytest.raises(ValueError):
        manager.status()
    assert path.read_text() == text


def test_launch_uses_selected_interpreter_and_holds_lease_for_entire_resident(
    manager, tmp_path, monkeypatch
):
    a = add(manager, tmp_path)
    manager.activate(a)
    with pytest.raises(ValueError, match="bundled Python"):
        manager.launch()
    executable = manager.root / "versions" / a / "runtime/python/python.exe"
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setenv("INARA_DATA_DIR", "sentinel-original")
    monkeypatch.setenv("INARA_DEV_SERVER", "http://invalid.example")

    def resident(path, run_name):
        assert path == str(manager.root / "versions" / a / "backend/resident_main.py")
        assert run_name == "__main__" and sys.argv[-1] == "--resident-only"
        assert os.environ["INARA_DATA_DIR"] == str(manager.root / "data" / a / "database")
        assert "INARA_DEV_SERVER" not in os.environ
        with pytest.raises(ValueError, match="busy"):
            manager.deactivate()
        raise SystemExit(0)

    monkeypatch.setattr(install.runpy, "run_path", resident)
    with pytest.raises(SystemExit) as result:
        manager.launch(resident_only=True)
    assert result.value.code == 0
    assert os.environ["INARA_DATA_DIR"] == "sentinel-original"
    assert os.environ["INARA_DEV_SERVER"] == "http://invalid.example"
    assert manager.status()["selected"] == a


def test_interrupted_selection_commit_keeps_original_pointer_and_data(
    manager, tmp_path, monkeypatch
):
    a = add(manager, tmp_path)
    manager.activate(a)
    b = add(manager, tmp_path, "two")
    before = (manager.root / "installation.json").read_bytes()

    def interrupted_replace(*args):
        raise OSError("interrupted state commit")

    monkeypatch.setattr(install.os, "replace", interrupted_replace)
    with pytest.raises(OSError):
        manager.activate(b)
    assert (manager.root / "installation.json").read_bytes() == before
    assert manager.load()["current"] == a
    assert manager.data(manager.load(), b).is_dir()


def test_unowned_existing_data_is_never_adopted_during_recovery(manager, tmp_path, monkeypatch):
    source = candidate(tmp_path)
    slot = install.package.release.sha256(source / "desktop-pilot.json")
    data = manager.root / "data" / slot
    data.mkdir()
    (data / "private.txt").write_text("preserve")
    with pytest.raises(ValueError):
        manager.install(source)
    with pytest.raises(ValueError):
        manager.recover(slot)
    assert (data / "private.txt").read_text() == "preserve"
    assert manager.load()["current"] is None


def test_operating_system_releases_lock_after_manager_process_crash(manager):
    import subprocess

    script = Path(install.__file__).resolve()
    code = (
        "import importlib.util,os,pathlib; "
        f"s=importlib.util.spec_from_file_location('child', {str(script)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        f"i=m.Installation(pathlib.Path({str(manager.root)!r})); "
        "c=i.locked(); c.__enter__(); os._exit(17)"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True)
    assert result.returncode == 17
    assert manager.status()["selected"] is None


def test_recovery_refuses_ambiguous_copies_and_does_not_delete_either(manager, tmp_path):
    source = candidate(tmp_path)
    slot = install.package.release.sha256(source / "desktop-pilot.json")
    pending = manager.root / "transactions" / slot
    target = manager.root / "versions" / slot
    shutil.copytree(source, pending)
    shutil.copytree(source, target)
    with pytest.raises(ValueError, match="Ambiguous"):
        manager.recover(slot)
    assert pending.is_dir() and target.is_dir()
    assert manager.load()["slots"] == {}
