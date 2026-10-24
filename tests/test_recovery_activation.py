"""Reviewed recovery compatibility and pointers; synthetic data and fixture account keys."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
import pytest
from services.storage import Database, scope_hash
from services.sessions import SessionStore
from services.project_memory import ProjectMemory
from services.memory_contracts import MemoryWrite
from project_manager import ProjectManager
from services.cad import Recipe
from tests.test_desktop_install import manager  # noqa: F401
from tests.test_desktop_backup import profile  # noqa: F401

spec = importlib.util.spec_from_file_location(
    "recovery_activation", Path(__file__).resolve().parents[1] / "scripts/desktop-recovery.py"
)
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)


def seed(data, protector):
    owner = json.loads((data / "desktop-profile/resident-identity.json").read_text())["id"]
    database = Database(data / "database", protection=protector)
    with database.transaction() as db:
        db.execute("DELETE FROM documents")
    projects = ProjectManager(str(data / "projects"), state_store=database)
    projects.switch_project("temp")
    project = projects.get_current_project_path().resolve()
    app = SimpleNamespace(
        database=database,
        projects=projects,
        sessions=SimpleNamespace(
            is_owner=lambda value: value == owner, authenticated=lambda value: value == owner
        ),
    )
    memory = ProjectMemory(app)
    snap = memory.snapshot(owner, project)
    text = "Keep literal old path: " + str(project)
    memory.write(
        owner,
        project,
        MemoryWrite(revision=snap["revision"], id=uuid.uuid4(), title="Fixture note", text=text),
    )
    conversation, request = str(uuid.uuid4()), str(uuid.uuid4())
    sessions = SessionStore(database)
    sessions.claim(conversation, owner, str(project), request, "fixture")
    sessions.finish(
        conversation,
        owner,
        str(project),
        request,
        "fixture",
        {"state": "succeeded", "result": {"text": "fixture"}},
        [{"role": "user", "content": text}],
    )
    job = str(uuid.uuid4())
    relative = "cad/designs/" + str(uuid.uuid4())
    artifact = project / relative / "model.stl"
    artifact.parent.mkdir(parents=True)
    raw = b"solid fixture\nendsolid fixture\n"
    artifact.write_bytes(raw)
    with database.transaction() as db:
        database.put(
            db,
            "cad_jobs:" + scope_hash(owner + ":" + str(project)),
            job,
            {
                "request_id": job,
                "project": project.name,
                "recipe": Recipe().model_dump(),
                "state": "succeeded",
                "phase": "ready",
                "created_at": 1.0,
                "error": None,
                "reference": None,
                "directory": relative,
                "artifacts": {"stl": {"bytes": len(raw), "sha256": activation.backup.digest(raw)}},
            },
        )
    return owner, conversation, job, text, relative


@pytest.fixture
def prepared_source(profile):  # noqa: F811
    recovery, slot, data, archive, protector = profile
    seeded = seed(data, protector)
    recovery.backup(slot, archive)
    service = activation.Activation(recovery.manager, protector)
    return service, slot, data, archive, seeded


def test_prepare_explicit_activation_services_and_rollback_preserve_original(prepared_source):
    service, slot, original, archive, seeded = prepared_source
    owner, conversation, job, literal, relative = seeded
    pid = uuid.uuid4().hex
    preview = service.preview(slot, archive, pid)
    assert preview["counts"] == {
        "memory": 1,
        "conversations": 1,
        "creative_jobs": 1,
        "workspace": 1,
    }
    assert service.manager.data(service.manager.load(), slot) == original
    service.prepare(slot, archive, pid, preview["review_sha256"])
    assert service.manager.data(service.manager.load(), slot) == original
    service.activate(slot, pid, preview["review_sha256"])
    recovered = service.manager.data(service.manager.load(), slot)
    assert recovered != original
    database = Database(recovered / "database", protection=service.recovery.protector)
    projects = ProjectManager(str(recovered / "projects"), state_store=database)
    project = projects.get_current_project_path().resolve()
    app = SimpleNamespace(
        database=database,
        projects=projects,
        sessions=SimpleNamespace(
            is_owner=lambda value: value == owner, authenticated=lambda value: value == owner
        ),
    )
    assert ProjectMemory(app).snapshot(owner, project)["items"][0]["text"] == literal
    assert (
        SessionStore(database).restore(conversation, owner, str(project))[0]["content"] == literal
    )
    with database.connection() as db:
        value = database.get(db, "cad_jobs:" + scope_hash(owner + ":" + str(project)), job)
        assert value["directory"] == relative
    assert (project / relative / "model.stl").read_bytes() == (
        original / "projects/projects/temp" / relative / "model.stl"
    ).read_bytes()
    service.rollback(slot)
    assert service.manager.data(service.manager.load(), slot) == original
    service.rollback(slot)
    assert service.manager.data(service.manager.load(), slot) == recovered


@pytest.mark.parametrize(
    "kind",
    [
        "unknown",
        "wrong_memory_owner",
        "wrong_memory_scope",
        "wrong_session_owner",
        "migrations",
        "running_job",
        "external_directory",
        "changed_artifact",
        "extra_table",
        "trigger",
    ],
)
def test_incompatible_records_reject_before_creating_profile(profile, kind):  # noqa: F811
    recovery, slot, data, archive, protector = profile
    owner, session, job, text, relative = seed(data, protector)
    database = Database(data / "database", protection=protector)
    project = data / "projects/projects/temp"
    with database.transaction() as db:
        if kind == "extra_table":
            db.execute("CREATE TABLE unknown_scope(path TEXT)")
        elif kind == "trigger":
            db.execute(
                "CREATE TRIGGER unknown_trigger AFTER INSERT ON documents BEGIN SELECT 1; END"
            )
        elif kind == "unknown":
            database.put(db, "mobile_device", "fixture", {})
        elif kind.startswith("wrong_memory"):
            key = scope_hash(owner + "\n" + str(project))
            value = database.get(db, "project_memory_v1", key)
            value["owner" if kind.endswith("owner") else "project"] = "other"
            database.put(db, "project_memory_v1", key, value)
        elif kind == "wrong_session_owner":
            db.execute("UPDATE sessions SET owner='other'")
        elif kind == "migrations":
            db.execute("INSERT INTO migrations VALUES('unsupported','fixture')")
        elif kind in {"running_job", "external_directory"}:
            namespace = "cad_jobs:" + scope_hash(owner + ":" + str(project))
            value = database.get(db, namespace, job)
            value["state" if kind == "running_job" else "directory"] = (
                "running" if kind == "running_job" else "../outside"
            )
            database.put(db, namespace, job, value)
    if kind == "changed_artifact":
        (project / relative / "model.stl").write_bytes(b"changed")
    recovery.backup(slot, archive)
    service = activation.Activation(recovery.manager, protector)
    pid = uuid.uuid4().hex
    with pytest.raises(Exception):
        service.preview(slot, archive, pid)
    assert not (recovery.manager.root / "recovery-profiles" / pid).exists()
    assert recovery.manager.data(recovery.manager.load(), slot) == data


@pytest.mark.parametrize(
    "kind", ["stale", "payload", "receipt", "identity", "busy", "incomplete", "current_owner"]
)
def test_activation_refuses_stale_changed_busy_or_incomplete_profiles(prepared_source, kind):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    if kind == "stale":
        service.manager.deactivate()
        with pytest.raises(ValueError):
            service.prepare(slot, archive, pid, review)
        return
    service.prepare(slot, archive, pid, review)
    path = service.manager.root / "recovery-profiles" / pid
    if kind == "current_owner":
        (data / "desktop-profile/resident-identity.json").write_text(
            json.dumps({"id": str(uuid.uuid4())})
        )
    elif kind == "payload":
        (path / "settings.json").write_text("{}")
    elif kind == "receipt":
        review = "0" * 64
    elif kind == "identity":
        (path / "desktop-profile/resident-identity.json").write_text(
            json.dumps({"id": str(uuid.uuid4())})
        )
    elif kind == "incomplete":
        receipt = json.loads((path / ".inara-recovery.json").read_text())
        receipt["status"] = "incomplete"
        (path / ".inara-recovery.json").write_text(json.dumps(receipt))
    elif kind == "busy":
        with service.manager.locked():
            with pytest.raises(ValueError):
                service.activate(slot, pid, review)
        return
    with pytest.raises(ValueError):
        service.activate(slot, pid, review)
    assert service.manager.data(service.manager.load(), slot) == data


def test_new_backup_after_activation_preserves_new_source_and_rebinds_again(
    prepared_source, tmp_path
):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    service.prepare(slot, archive, pid, review)
    service.activate(slot, pid, review)
    next_archive = tmp_path / "active-backup.inara"
    service.recovery.backup(slot, next_archive)
    next_pid = uuid.uuid4().hex
    review = service.preview(slot, next_archive, next_pid)["review_sha256"]
    service.prepare(slot, next_archive, next_pid, review)
    service.activate(slot, next_pid, review)
    assert service.manager.data(service.manager.load(), slot).name == next_pid


def test_activation_state_change_after_preparation_invalidates_review(prepared_source):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    service.prepare(slot, archive, pid, review)
    service.manager.deactivate()
    with pytest.raises(ValueError):
        service.activate(slot, pid, review)
    assert service.manager.data(service.manager.load(), slot) == data


def test_interrupted_prepare_is_not_launchable_and_pointer_commit_failure_preserves_original(
    prepared_source, monkeypatch
):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    original = activation.install.write

    def fail_completion(path, value):
        if value.get("status") == "prepared":
            raise OSError("interrupted prepare")
        return original(path, value)

    monkeypatch.setattr(activation.install, "write", fail_completion)
    with pytest.raises(OSError):
        service.prepare(slot, archive, pid, review)
    with pytest.raises(ValueError):
        service.activate(slot, pid, review)
    assert service.manager.data(service.manager.load(), slot) == data
    monkeypatch.setattr(activation.install, "write", original)
    other = uuid.uuid4().hex
    review = service.preview(slot, archive, other)["review_sha256"]
    service.prepare(slot, archive, other, review)

    def fail_commit(state):
        raise OSError("interrupted activation")

    monkeypatch.setattr(service.manager, "save", fail_commit)
    with pytest.raises(OSError):
        service.activate(slot, other, review)
    assert service.manager.data(service.manager.load(), slot) == data


def test_activation_upgrades_one_state_record_and_older_controls_fail_closed(prepared_source):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    service.prepare(slot, archive, pid, review)
    service.activate(slot, pid, review)
    state = service.manager.load()
    assert state["format"] == 2 and state["recovery"]["slots"][slot]["current"] == pid
    assert not (service.manager.root / "recovery-selection.json").exists()
    # The previously accepted control manifest requires format 1, so it cannot silently use original data.
    assert state["format"] != 1


def test_legacy_encrypted_backup_format_one_is_supported(prepared_source):
    service, slot, data, archive, _ = prepared_source
    protector = service.recovery.protector
    from tests.test_desktop_backup import mutate

    def legacy(manifest, files):
        manifest["format"] = 1
        manifest.pop("source_data")

    mutate(archive, protector, legacy)
    assert service.preview(slot, archive, uuid.uuid4().hex)["counts"]["memory"] == 1


def test_rollback_refuses_owner_change_without_switching(prepared_source):
    service, slot, data, archive, _ = prepared_source
    pid = uuid.uuid4().hex
    review = service.preview(slot, archive, pid)["review_sha256"]
    service.prepare(slot, archive, pid, review)
    service.activate(slot, pid, review)
    (data / "desktop-profile/resident-identity.json").write_text(
        json.dumps({"id": str(uuid.uuid4())})
    )
    with pytest.raises(ValueError):
        service.rollback(slot)
    assert service.manager.data(service.manager.load(), slot).name == pid
