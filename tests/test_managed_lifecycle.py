"""Synthetic signed lifecycle, actual account-protected checkpoints and bounded deletion."""

import base64
from datetime import timedelta
import json
import uuid

import pytest
from services.storage import Database

from tests import test_managed_update as updates
from tests.test_controller_trust import load
from tests.test_desktop_backup import Protection
from tests.test_signed_package import NOW, save

life = load("managed-lifecycle")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    value = updates.fixture.__wrapped__(tmp_path, monkeypatch)
    updates.apply(value, updates.proposal(value))
    monkeypatch.setattr(life, "managed", updates.managed)
    monkeypatch.setattr(life, "signed", updates.signed)
    monkeypatch.setattr(life, "trust", updates.signed.trust)
    monkeypatch.setattr(life, "review", updates.signed.review)
    original = updates.managed.module
    monkeypatch.setattr(updates.managed, "module", lambda name: life if name == "managed-lifecycle" else original(name))
    data = value["root"] / "data" / value["slot"]
    (data / "desktop-profile").mkdir(exist_ok=True)
    save(data / "desktop-profile/resident-identity.json", {"id": str(uuid.uuid4()), "gaming": False})
    (data / "projects/projects/temp").mkdir(parents=True)
    (data / "projects/projects/temp/model.stl").write_bytes(b"PRIVATE MODEL")
    protector = Protection()
    monkeypatch.setattr(life.backup, "protection", lambda: protector)
    Database(data / "database", protection=protector)
    value.update(data=data, protector=protector)
    return value


def common(value):
    return value["root"], value["anchor"], value["checkpoint"]


def sign(value, action, profile=None):
    directory = value["tmp"] / ("lifecycle-" + uuid.uuid4().hex)
    life.prepare(*common(value), action, value["slot"], profile, directory, now=NOW)
    statement = json.loads((directory / "statement.json").read_bytes())
    message = life.DOMAIN + life.review.encoded(statement)
    assert (directory / "signing-message.bin").read_bytes() == message
    signatures = [{"key_id": key["key_id"], "signature": base64.b64encode(secret.sign(message)).decode()} for key, secret in zip(value["policy"]["keys"], value["private"])]
    path = directory / "signed.json"
    save(path, {"statement": statement, "signatures_before": signatures, "signatures_after": signatures})
    return path


def apply(value, path, confirmation=""):
    reviewed = life.apply(*common(value), path, now=NOW)
    result = life.apply(*common(value), path, reviewed["review_sha256"], confirmation, now=NOW)
    value["checkpoint"] = result["checkpoint"]
    return result


def copy(value, operation, file, profile=None):
    reviewed = life.copies(*common(value), operation, value["slot"], file, profile, _protector=value["protector"])
    return life.copies(*common(value), operation, value["slot"], file, profile, reviewed["review_sha256"], _protector=value["protector"])


def test_encrypted_backup_typed_prepare_signed_activation_and_profile_rollback(fixture):
    value = fixture
    before = (value["root"] / "installation.json").read_bytes()
    file = value["tmp"] / "private.inara"
    assert copy(value, "backup", file)["backup_created"]
    assert b"PRIVATE MODEL" not in file.read_bytes()
    profile = uuid.uuid4().hex
    assert copy(value, "prepare-profile", file, profile)["prepared"]
    assert (value["root"] / "installation.json").read_bytes() == before
    path = sign(value, "activate-profile", profile)
    assert apply(value, path)["applied"]
    service = life.signed.manager.Installation(value["root"], authenticated=True)
    assert service.load()["format"] == 3
    assert service.data(service.load(), value["slot"]).name == profile
    assert (value["data"] / "projects/projects/temp/model.stl").read_bytes() == b"PRIVATE MODEL"
    path = sign(value, "rollback-profile")
    assert apply(value, path)["applied"]
    assert service.data(service.load(), value["slot"]) == value["data"]
    assert updates.managed.status(*common(value))["sequence_floor"] == 1
    with pytest.raises(ValueError):
        life.signed.manager.Installation(value["root"]).load()


def test_remove_retains_data_trust_and_separate_exact_phrase_erasure(fixture):
    value = fixture
    archive = value["tmp"] / "retained.inara"
    copy(value, "backup", archive)
    path = sign(value, "remove-software")
    assert apply(value, path)["data_preserved"]
    assert not any((value["root"] / "versions").iterdir())
    assert value["data"].is_dir() and (value["root"] / "admissions").is_dir()
    removed_pin = value["checkpoint"]
    assert updates.managed.status(*common(value))["selected"] is None
    path = sign(value, "erase-data")
    reviewed = life.apply(*common(value), path, now=NOW)
    with pytest.raises(ValueError):
        life.apply(*common(value), path, reviewed["review_sha256"], "yes", now=NOW)
    assert value["data"].exists() and not (value["root"] / "update-pending.json").exists()
    assert not apply(value, path, life.ERASE)["data_preserved"]
    assert not any((value["root"] / "data").iterdir()) and archive.is_file()
    assert (value["anchor"] / "checkpoints" / (removed_pin + ".bin")).is_file()
    assert (value["root"] / "authorizations/state.json").is_file()
    assert updates.managed.status(*common(value))["sequence_floor"] == 1


@pytest.mark.parametrize("kind", ["signature", "wrong-domain", "expired", "stale-state", "changed-file", "foreign-profile", "early-erase"])
def test_signed_lifecycle_refuses_before_journal_or_deletion(fixture, kind):
    value = fixture
    if kind == "foreign-profile":
        marker = value["data"] / ".inara-data.json"
        save(marker, {"format": 1, "installation": "0" * 32, "slot": value["slot"]})
        apply(value, sign(value, "remove-software"))
        with pytest.raises(ValueError):
            sign(value, "erase-data")
        return
    if kind == "early-erase":
        with pytest.raises(ValueError):
            sign(value, "erase-data")
        return
    path = sign(value, "remove-software")
    before = (value["root"] / "installation.json").read_bytes()
    now = NOW
    if kind in {"signature", "wrong-domain"}:
        envelope = json.loads(path.read_bytes())
        if kind == "signature":
            envelope["signatures_before"] = []
        else:
            message = updates.managed.message(envelope["statement"])
            envelope["signatures_before"] = [{"key_id": key["key_id"], "signature": base64.b64encode(secret.sign(message)).decode()} for key, secret in zip(value["policy"]["keys"], value["private"])]
        save(path, envelope)
    elif kind == "expired":
        now += timedelta(hours=2)
    elif kind == "stale-state":
        (value["root"] / "installation.json").write_bytes(before + b" ")
        before += b" "
    else:
        (value["root"] / "versions" / value["slot"] / "extra.txt").write_text("foreign")
    with pytest.raises((ValueError, KeyError)):
        life.apply(*common(value), path, now=now)
    assert not (value["root"] / "update-pending.json").exists()
    assert (value["root"] / "installation.json").read_bytes() == before
    assert (value["root"] / "versions" / value["slot"]).exists()


@pytest.mark.parametrize("phase", ["before-delete", "after-delete", "installation", "authorization", "pointer"])
def test_reviewed_resume_across_removal_and_metadata_boundaries(fixture, monkeypatch, phase):
    value = fixture
    path = sign(value, "remove-software")
    reviewed = life.apply(*common(value), path, now=NOW)
    previous, prepared = value["checkpoint"], reviewed["plan"]["checkpoint"]
    original_delete, original_atomic = life.delete, updates.managed.atomic

    def delete(*args):
        if phase == "before-delete":
            raise OSError("injected")
        original_delete(*args)
        if phase == "after-delete":
            raise OSError("injected")

    names = {"installation": "installation.json", "authorization": "state.json", "pointer": "head.json"}

    def atomic(target, raw):
        original_atomic(target, raw)
        if target.name == names.get(phase):
            raise OSError("injected")

    monkeypatch.setattr(life, "delete", delete)
    monkeypatch.setattr(updates.managed, "atomic", atomic)
    with pytest.raises(OSError):
        life.apply(*common(value), path, reviewed["review_sha256"], now=NOW)
    monkeypatch.setattr(life, "delete", original_delete)
    monkeypatch.setattr(updates.managed, "atomic", original_atomic)
    if phase != "before-delete":
        with pytest.raises(ValueError):
            updates.managed.abort(value["root"], value["anchor"], prepared, previous)
    review = updates.managed.resume(value["root"], value["anchor"], prepared, previous)
    result = updates.managed.resume(value["root"], value["anchor"], prepared, previous, review["review_sha256"])
    value["checkpoint"] = result["checkpoint"]
    assert result["resumed"] and updates.managed.status(*common(value))["selected"] is None
    assert value["data"].exists()


def interrupted(value, monkeypatch):
    path = sign(value, "remove-software")
    reviewed = life.apply(*common(value), path, now=NOW)
    original = life.delete
    monkeypatch.setattr(life, "delete", lambda *_: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        life.apply(*common(value), path, reviewed["review_sha256"], now=NOW)
    monkeypatch.setattr(life, "delete", original)
    return reviewed["plan"]["checkpoint"]


def test_cancel_before_deletion_retains_owned_software_and_protected_inventory(fixture, monkeypatch):
    value = fixture
    prepared = interrupted(value, monkeypatch)
    review = updates.managed.abort(value["root"], value["anchor"], prepared, value["checkpoint"])
    assert updates.managed.abort(value["root"], value["anchor"], prepared, value["checkpoint"], review["review_sha256"])["cancelled"]
    assert (value["root"] / "versions" / value["slot"]).exists()
    assert (value["anchor"] / "lifecycle-inventories").is_dir()
    assert updates.managed.status(*common(value))["selected"] == value["slot"]


@pytest.mark.parametrize("kind", ["unknown-file", "unknown-root", "corrupt-inventory", "partial-file"])
def test_unknown_partial_or_changed_recovery_evidence_refuses(fixture, monkeypatch, kind):
    value = fixture
    prepared = interrupted(value, monkeypatch)
    if kind == "unknown-file":
        (value["root"] / "versions" / value["slot"] / "foreign.txt").write_text("preserve")
    elif kind == "unknown-root":
        (value["root"] / "versions" / ("f" * 64)).mkdir()
    elif kind == "corrupt-inventory":
        next((value["anchor"] / "lifecycle-inventories").iterdir()).write_bytes(b"changed")
    else:
        (value["root"] / "versions" / value["slot"] / "desktop-pilot.json").write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        updates.managed.resume(value["root"], value["anchor"], prepared, value["checkpoint"])
    assert (value["root"] / "update-pending.json").is_file()


def test_backup_review_detects_changed_data_and_preserves_metadata(fixture):
    value = fixture
    output = value["tmp"] / "profile.inara"
    reviewed = life.copies(*common(value), "backup", value["slot"], output, _protector=value["protector"])
    (value["data"] / "projects/projects/temp/model.stl").write_text("changed")
    with pytest.raises(ValueError):
        life.copies(*common(value), "backup", value["slot"], output, expected_review=reviewed["review_sha256"], _protector=value["protector"])
    assert not output.exists() and updates.managed.status(*common(value))["selected"] == value["slot"]


@pytest.mark.parametrize("kind", ["owner", "payload", "unknown-record-with-rewritten-receipt"])
def test_prepared_activation_rechecks_owner_inventory_and_typed_data(fixture, kind):
    value = fixture
    archive = value["tmp"] / "profile.inara"
    copy(value, "backup", archive)
    profile = uuid.uuid4().hex
    copy(value, "prepare-profile", archive, profile)
    target = value["root"] / "recovery-profiles" / profile
    if kind == "owner":
        save(target / "desktop-profile/resident-identity.json", {"id": str(uuid.uuid4())})
    elif kind == "payload":
        (target / "projects/projects/temp/model.stl").write_bytes(b"altered")
    else:
        database = Database(target / "database", protection=value["protector"])
        with database.transaction() as db:
            database.put(db, "unreviewed_record", "fixture", {"unsupported": True})
        receipt = json.loads((target / life.backup.RECEIPT).read_bytes())
        actual = life.snapshot(target, True)
        receipt["inventory"] = {entry["path"]: entry["sha256"] for entry in actual["files"]}
        save(target / life.backup.RECEIPT, receipt)
    with pytest.raises(ValueError):
        sign(value, "activate-profile", profile)
    assert not (value["root"] / "update-pending.json").exists()


def test_actual_original_account_backup_and_preparation(fixture, monkeypatch):
    value = fixture
    storage = life.module("desktop-backup").protection()
    monkeypatch.setattr(life.backup, "protection", lambda: storage)
    value["protector"] = storage
    archive = value["tmp"] / "real-account.inara"
    assert copy(value, "backup", archive)["backup_created"]
    profile = uuid.uuid4().hex
    assert copy(value, "prepare-profile", archive, profile)["prepared"]
    assert apply(value, sign(value, "activate-profile", profile))["applied"]


def test_shared_payload_refuses_after_signed_review_without_touching_external_alias(fixture):
    import os

    value = fixture
    path = sign(value, "remove-software")
    payload = value["root"] / "versions" / value["slot"] / "desktop-pilot.json"
    alias = value["tmp"] / "retained-external-file.json"
    os.link(payload, alias)
    before = alias.read_bytes()
    with pytest.raises(ValueError):
        life.apply(*common(value), path, now=NOW)
    assert alias.read_bytes() == before and payload.is_file()


@pytest.mark.parametrize("unsafe", ["../external.txt", "data/../external.txt", "versions/" + "a" * 64 + "/../../external.txt"])
def test_deletion_inventory_cannot_escape_owned_scope(tmp_path, unsafe):
    (tmp_path / "transactions").mkdir()
    (tmp_path / "external.txt").write_text("preserve")
    with pytest.raises(ValueError):
        life.preflight(tmp_path, [{"path": unsafe, "directory": True}], "erase-data")
    assert (tmp_path / "external.txt").read_text() == "preserve"


def test_new_outputs_cannot_modify_trusted_controller(fixture):
    value = fixture
    with pytest.raises(ValueError):
        life.copies(*common(value), "backup", value["slot"], life.ROOT / "must-not-create.inara")
    assert not (life.ROOT / "must-not-create.inara").exists()


def test_interrupted_erasure_requires_phrase_again_at_resume(fixture, monkeypatch):
    value = fixture
    apply(value, sign(value, "remove-software"))
    path = sign(value, "erase-data")
    review = life.apply(*common(value), path, now=NOW)
    old_pin, new_pin = value["checkpoint"], review["plan"]["checkpoint"]
    original = life.delete
    monkeypatch.setattr(life, "delete", lambda *_: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        life.apply(*common(value), path, review["review_sha256"], life.ERASE, now=NOW)
    monkeypatch.setattr(life, "delete", original)
    reviewed = updates.managed.resume(value["root"], value["anchor"], new_pin, old_pin)
    assert reviewed["plan"]["confirmation_required"]
    with pytest.raises(ValueError):
        updates.managed.resume(value["root"], value["anchor"], new_pin, old_pin, reviewed["review_sha256"])
    assert value["data"].is_dir()
    result = updates.managed.resume(value["root"], value["anchor"], new_pin, old_pin, reviewed["review_sha256"], confirmation=life.ERASE)
    assert result["resumed"] and not value["data"].exists()


def test_relative_cli_paths_are_canonical_in_recoverable_journal(fixture, monkeypatch):
    value = fixture
    path = sign(value, "remove-software")
    monkeypatch.chdir(value["tmp"])
    root, anchor = value["root"].relative_to(value["tmp"]), value["anchor"].relative_to(value["tmp"])
    reviewed = life.apply(root, anchor, value["checkpoint"], path, now=NOW)
    original = life.delete
    monkeypatch.setattr(life, "delete", lambda *_: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        life.apply(root, anchor, value["checkpoint"], path, reviewed["review_sha256"], now=NOW)
    monkeypatch.setattr(life, "delete", original)
    journal = json.loads((value["root"] / "update-pending.json").read_bytes())
    assert journal["anchor"] == str(value["anchor"])
    result = updates.managed.resume(root, anchor, reviewed["plan"]["checkpoint"], value["checkpoint"])
    assert result["plan"]["checkpoint"] == reviewed["plan"]["checkpoint"]


def test_change_after_apply_snapshot_cannot_enter_backup(fixture, monkeypatch):
    value = fixture
    file = value["tmp"] / "must-not-write.inara"
    reviewed = life.copies(*common(value), "backup", value["slot"], file, _protector=value["protector"])
    original = life.backup.Recovery.backup

    def changed(adapter, *args, **kwargs):
        (value["data"] / "projects/projects/temp/model.stl").write_bytes(b"changed during apply")
        return original(adapter, *args, **kwargs)

    monkeypatch.setattr(life.backup.Recovery, "backup", changed)
    with pytest.raises(ValueError):
        life.copies(*common(value), "backup", value["slot"], file, expected_review=reviewed["review_sha256"], _protector=value["protector"])
    assert not file.exists()
