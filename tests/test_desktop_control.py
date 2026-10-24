"""Native setup worker policy and real deletion of isolated fixture payloads only."""

import importlib.util
import json
from pathlib import Path
import uuid
import pytest
from tests.test_desktop_install import (
    manager as slot_manager,  # noqa: F401
    candidate,
    install as fixture_install,
)  # noqa: F401

spec = importlib.util.spec_from_file_location(
    "desktop_control", Path(__file__).resolve().parents[1] / "scripts/desktop-control.py"
)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


@pytest.fixture
def panel(slot_manager, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(control.install.package, "verify", fixture_install.package.verify)
    directory = tmp_path / "control"
    directory.mkdir()
    service = control.Control(directory, verify=False)
    package = candidate(tmp_path)
    return service, slot_manager, package


def perform(service, action, root, **args):
    reviewed = service.review({"action": action, "root": str(root), **args})
    return service.apply(reviewed["token"])


def seed(panel):
    service, manager, package = panel
    result = perform(service, "add_version", manager.root, package=str(package))
    slot = result["slot"]
    perform(service, "select", manager.root, slot=slot)
    data = manager.data(manager.load(), slot)
    (data / "private.txt").write_text("PRIVATE_FIXTURE")
    return service, manager, package, slot, data


def test_install_select_remove_preserving_data_reinstall_and_explicit_erasure(panel):
    service, manager, package, slot, data = seed(panel)
    assert service.status(str(manager.root))["selected"] == slot
    removed = perform(service, "uninstall", manager.root)
    assert removed["data_preserved"] and (data / "private.txt").read_text() == "PRIVATE_FIXTURE"
    assert not (manager.root / "versions" / slot).exists() and manager.load()["slots"] == {}
    # Exact-build reinstall deliberately reuses only its retained owned data.
    reviewed = service.review(
        {"action": "add_version", "root": str(manager.root), "package": str(package)}
    )
    assert "retained original" in reviewed["plan"]["data_policy"]
    service.apply(reviewed["token"])
    assert (data / "private.txt").exists()
    perform(service, "uninstall", manager.root)
    reviewed = service.review({"action": "erase_data", "root": str(manager.root)})
    assert reviewed["plan"]["confirmation_required"]
    with pytest.raises(ValueError):
        service.apply(reviewed["token"], "yes")
    assert data.exists()
    reviewed = service.review({"action": "erase_data", "root": str(manager.root)})
    service.apply(reviewed["token"], control.ERASE)
    assert not data.exists()
    receipts = list((manager.root / "removal-receipts").glob("*.json"))
    assert receipts and all("private.txt" not in item.read_text() for item in receipts)


@pytest.mark.parametrize(
    "kind", ["wrong_token", "expired", "stale", "candidate_changed", "replay", "unknown_field"]
)
def test_reviews_are_bound_single_use_and_state_sensitive(panel, monkeypatch, kind):
    service, manager, package = panel
    params = {"action": "add_version", "root": str(manager.root), "package": str(package)}
    reviewed = service.review(params)
    if kind == "unknown_field":
        with pytest.raises(ValueError):
            service.review({**params, "shell": "arbitrary"})
        with pytest.raises(ValueError):
            service.apply(reviewed["token"])
        return
    if kind == "wrong_token":
        token = "wrong"
    else:
        token = reviewed["token"]
    if kind == "expired":
        monkeypatch.setattr(
            control.time,
            "monotonic",
            lambda: service.pending["expires"] + 1 if service.pending else 10**20,
        )
    elif kind == "stale":
        manager.deactivate()
        state = manager.load()
        manager.save(state)
    elif kind == "candidate_changed":
        (package / "desktop-pilot.json").write_text("{}")
    if kind == "replay":
        service.apply(token)
        with pytest.raises(ValueError):
            service.apply(token)
    else:
        with pytest.raises(ValueError):
            service.apply(token)
        assert manager.load()["slots"] == {}


@pytest.mark.parametrize(
    "kind", ["busy", "changed_file", "unknown_file", "foreign_data", "installed_data_erase"]
)
def test_removal_preflight_refuses_without_deleting_any_owned_payload(panel, kind):
    service, manager, package, slot, data = seed(panel)
    target = manager.root / "versions" / slot / "backend/resident_main.py"
    if kind == "busy":
        with manager.locked():
            with pytest.raises(ValueError):
                service.review({"action": "uninstall", "root": str(manager.root)})
    elif kind == "installed_data_erase":
        with pytest.raises(ValueError):
            service.review({"action": "erase_data", "root": str(manager.root)})
    elif kind == "foreign_data":
        perform(service, "uninstall", manager.root)
        marker = data / ".inara-data.json"
        value = json.loads(marker.read_text())
        value["installation"] = "other"
        marker.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            service.review({"action": "erase_data", "root": str(manager.root)})
        assert (data / "private.txt").exists()
        return
    else:
        reviewed = service.review({"action": "uninstall", "root": str(manager.root)})
        if kind == "changed_file":
            target.write_text("changed")
        else:
            (target.parent / "unknown.txt").write_text("preserve")
        with pytest.raises(ValueError):
            service.apply(reviewed["token"])
    assert target.exists() and (data / "private.txt").exists()


@pytest.mark.parametrize("point", ["after_journal", "mid_files", "after_metadata", "after_receipt"])
def test_interrupted_removal_blocks_launch_and_resumes_idempotently(panel, monkeypatch, point):
    service, manager, package, slot, data = seed(panel)
    reviewed = service.review({"action": "uninstall", "root": str(manager.root)})
    original_write, original_unlink = control.install.write, Path.unlink
    if point in {"after_journal", "after_metadata", "after_receipt"}:

        def interrupted(path, value):
            original_write(path, value)
            if (
                (point == "after_journal" and path.name == "removal-pending.json")
                or (point == "after_metadata" and path.name == "installation.json")
                or (point == "after_receipt" and path.parent.name == "removal-receipts")
            ):
                raise OSError("simulated interruption")

        monkeypatch.setattr(control.install, "write", interrupted)
    else:
        calls = []

        def interrupted_unlink(path, *args, **kwargs):
            original_unlink(path, *args, **kwargs)
            calls.append(True)
            if len(calls) == 1:
                raise OSError("simulated interruption")

        monkeypatch.setattr(Path, "unlink", interrupted_unlink)
    with pytest.raises(OSError):
        service.apply(reviewed["token"])
    with pytest.raises(ValueError):
        manager.status()
    assert service.status(str(manager.root))["needs_resume"]
    monkeypatch.setattr(control.install, "write", original_write)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    result = perform(service, "resume", manager.root)
    assert result["software_removed"] and (data / "private.txt").exists()
    assert not (manager.root / "removal-pending.json").exists()
    assert manager.load()["slots"] == {}


def test_journal_traversal_and_unknown_extras_refuse_before_resume_deletes(
    panel, monkeypatch, tmp_path
):
    service, manager, package, slot, data = seed(panel)
    original = control.install.write

    def stop(path, value):
        original(path, value)
        if path.name == "removal-pending.json":
            raise OSError("stop")

    monkeypatch.setattr(control.install, "write", stop)
    reviewed = service.review({"action": "uninstall", "root": str(manager.root)})
    with pytest.raises(OSError):
        service.apply(reviewed["token"])
    monkeypatch.setattr(control.install, "write", original)
    journal = manager.root / "removal-pending.json"
    value = json.loads(journal.read_text())
    good = json.loads(journal.read_text())
    value["records"][0]["path"] = "../outside"
    journal.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        control.remove(control.install.Installation(manager.root), "software")
    target = manager.root / "versions" / slot / "backend/resident_main.py"
    assert target.exists()
    journal.write_text(json.dumps(good))
    (target.parent / "unlisted.txt").write_text("preserve")
    with pytest.raises(ValueError):
        control.remove(control.install.Installation(manager.root), "software")
    assert target.exists()


@pytest.mark.parametrize("value", ["relative", r"\\\\server\share", "", None])
def test_control_paths_require_local_absolute_names(value):
    with pytest.raises(ValueError):
        control.path(value)


def test_same_build_reinstall_restores_explicitly_reviewed_recovery_selection(panel):
    service, manager, package, slot, data = seed(panel)
    owner = str(uuid.uuid4())
    (data / "desktop-profile").mkdir()
    (data / "desktop-profile/resident-identity.json").write_text(json.dumps({"id": owner}))
    profile = uuid.uuid4().hex
    target = manager.root / "recovery-profiles" / profile
    (target / "desktop-profile").mkdir(parents=True)
    (target / "desktop-profile/resident-identity.json").write_text(json.dumps({"id": owner}))
    (target / ".inara-data.json").write_text(
        json.dumps({"format": 1, "installation": manager.load()["id"], "slot": slot})
    )
    (target / ".inara-recovery.json").write_text(
        json.dumps(
            {
                "status": "prepared",
                "installation": manager.load()["id"],
                "slot": slot,
                "profile": profile,
                "owner": owner,
            }
        )
    )
    state = manager.load()
    state["format"] = 2
    state["recovery"] = {
        "format": 1,
        "installation": state["id"],
        "slots": {slot: {"current": profile, "previous": None}},
    }
    manager.save(state)
    perform(service, "uninstall", manager.root)
    reviewed = service.review(
        {"action": "add_version", "root": str(manager.root), "package": str(package)}
    )
    assert "selected recovery" in reviewed["plan"]["data_policy"]
    service.apply(reviewed["token"])
    assert manager.data(manager.load(), slot) == target
    assert manager.load()["current"] is None  # Reinstall never launches/selects by itself.


def test_empty_recovery_container_is_not_reported_as_retained_data(panel):
    service, manager, package = panel
    (manager.root / "recovery-profiles").mkdir()
    assert service.status(str(manager.root))["retained_data"] is False
