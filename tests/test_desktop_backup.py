"""Synthetic full profiles only: encryption, scope, bounded validation and safe recovery."""

import importlib.util
import io
import json
import os
from pathlib import Path
import uuid
import zipfile
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from services.storage import Database
from tests.test_desktop_install import manager, add  # noqa: F401

spec = importlib.util.spec_from_file_location(
    "desktop_backup", Path(__file__).resolve().parents[1] / "scripts/desktop-backup.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class Protection:
    def __init__(self):
        self.key = os.urandom(32)

    def protect(self, raw):
        nonce = os.urandom(12)
        return nonce + AESGCM(self.key).encrypt(nonce, raw, b"fixture-account")

    def unprotect(self, raw):
        return AESGCM(self.key).decrypt(raw[:12], raw[12:], b"fixture-account")


@pytest.fixture
def profile(manager, tmp_path):  # noqa: F811
    slot = add(manager, tmp_path)
    manager.activate(slot)
    data = manager.data(manager.load(), slot)
    (data / "desktop-profile").mkdir()
    (data / "desktop-profile/resident-identity.json").write_text(
        json.dumps({"id": str(uuid.uuid4()), "gaming": False})
    )
    (data / "settings.json").write_text(json.dumps({"fixture_secret": "PRIVATE_SETTING"}))
    (data / "projects/fixture/empty").mkdir(parents=True)
    (data / "projects/fixture/model.stl").write_bytes(b"PRIVATE_PROJECT")
    (data / "legacy").mkdir()
    protector = Protection()
    database = Database(data / "database", protection=protector)
    with database.transaction() as db:
        database.put(db, "fixture", "value", {"text": "PRIVATE_RECORD"})
    recovery = backup.Recovery(manager, protector)
    return recovery, slot, data, tmp_path / "profile.inara", protector


def create(profile):
    recovery, slot, data, output, protector = profile
    result = recovery.backup(slot, output)
    return recovery, slot, data, output, protector, result


def mutate(output, protector, change):
    raw = backup.unseal(output.read_bytes(), protector)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {
            entry.filename: archive.read(entry)
            for entry in archive.infolist()
            if entry.filename != "manifest.json"
        }
    change(manifest, files)
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, value in files.items():
            archive.writestr(name, value)
    output.write_bytes(backup.seal(target.getvalue(), protector))


def test_encrypted_full_profile_preview_and_detached_restore_preserve_all_content(
    profile, tmp_path
):
    recovery, slot, data, output, protector, created = create(profile)
    raw = output.read_bytes()
    assert all(
        value not in raw
        for value in (b"PRIVATE_SETTING", b"PRIVATE_PROJECT", b"PRIVATE_RECORD", b"model.stl")
    )
    before = recovery.manager.load()
    preview = recovery.preview(slot, output)
    assert preview["sha256"] == created["sha256"] and not preview["automatic_activation"]
    destination = tmp_path / "recovered"
    result = recovery.restore(slot, output, destination, preview["sha256"])
    assert result["restored"] and not result["activated"]
    files, dirs = backup.inventory(data)
    for name, path in files.items():
        assert (destination / name).read_bytes() == path.read_bytes()
    assert (destination / "projects/fixture/empty").is_dir()
    database = Database(destination / "database", protection=protector)
    with database.connection() as db:
        assert database.get(db, "fixture", "value")["text"] == "PRIVATE_RECORD"
    assert json.loads((destination / backup.RECEIPT).read_text())["status"] == "complete"
    assert recovery.manager.load() == before
    assert "PRIVATE" not in json.dumps(preview) and "owner" not in preview


@pytest.mark.parametrize(
    "kind",
    [
        "tamper",
        "truncate",
        "magic",
        "wrong_account",
        "stale_digest",
        "owner",
        "installation",
        "slot",
        "schema",
        "hash",
        "extra",
        "case",
        "traversal",
        "device",
        "missing_directory",
        "format",
    ],
)
def test_invalid_backups_never_create_destination_or_modify_profile(profile, tmp_path, kind):
    recovery, slot, data, output, protector, created = create(profile)
    before = {name: path.read_bytes() for name, path in backup.inventory(data)[0].items()}
    if kind in {"tamper", "truncate", "magic"}:
        raw = bytearray(output.read_bytes())
        if kind == "tamper":
            raw[-1] ^= 1
        elif kind == "truncate":
            raw = raw[:20]
        else:
            raw[0] ^= 1
        output.write_bytes(raw)
    elif kind == "wrong_account":
        recovery.protector = Protection()
    elif kind != "stale_digest":

        def change(manifest, files):
            if kind == "owner":
                manifest["owner"] = str(uuid.uuid4())
            elif kind == "installation":
                manifest["installation"] = "0" * 32
            elif kind == "slot":
                manifest["slot"] = "0" * 64
            elif kind == "schema":
                name = "database/assistant.sqlite3"
                altered = bytearray(files["data/" + name])
                altered[60:64] = (99).to_bytes(4, "big")
                value = bytes(altered)
                files["data/" + name] = value
                record = next(item for item in manifest["files"] if item["path"] == name)
                record.update(bytes=len(value), sha256=backup.digest(value))
            elif kind == "hash":
                files["data/settings.json"] = b"changed"
            elif kind == "extra":
                files["data/unlisted.txt"] = b"extra"
            elif kind == "case":
                manifest["directories"].append("PROJECTS")
            elif kind in {"traversal", "device"}:
                manifest["files"][0]["path"] = "../private" if kind == "traversal" else "CON.txt"
            elif kind == "missing_directory":
                manifest["directories"].remove("projects/fixture")
            elif kind == "format":
                manifest["format"] = 99

        mutate(output, protector, change)
    destination = tmp_path / "must-not-create"
    with pytest.raises(Exception):
        recovery.restore(
            slot,
            output,
            destination,
            "0" * 64 if kind == "stale_digest" else backup.digest(output.read_bytes()),
        )
    assert not destination.exists()
    assert before == {name: path.read_bytes() for name, path in backup.inventory(data)[0].items()}


@pytest.mark.parametrize(
    "kind",
    [
        "busy",
        "wal",
        "symlink",
        "oversized_file",
        "oversized_total",
        "file_count",
        "changed",
        "existing_backup",
        "inside_installation",
        "damaged_database",
    ],
)
def test_backup_refuses_unsafe_or_unstable_profiles_without_emitting_plaintext(
    profile, tmp_path, monkeypatch, kind
):
    recovery, slot, data, output, protector = profile
    if kind == "busy":
        with recovery.manager.locked():
            with pytest.raises(ValueError):
                recovery.backup(slot, output)
        assert not output.exists()
        return
    if kind == "wal":
        (data / "database/assistant.sqlite3-wal").write_bytes(b"pending")
    elif kind == "symlink":
        import subprocess

        outside = tmp_path / "outside"
        outside.mkdir()
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(data / "projects/link"), str(outside)],
            capture_output=True,
            check=True,
        )
    elif kind == "oversized_file":
        monkeypatch.setattr(backup, "MAX_FILE", 10)
    elif kind == "oversized_total":
        monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    elif kind == "file_count":
        monkeypatch.setattr(backup, "MAX_FILES", 2)
    elif kind == "existing_backup":
        output.write_bytes(b"preserve")
    elif kind == "inside_installation":
        output = recovery.manager.root / "backup.inara"
    elif kind == "damaged_database":
        (data / "database/assistant.sqlite3").write_bytes(b"broken")
    elif kind == "changed":
        original = backup.inventory
        calls = []

        def inventory(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                (data / "settings.json").write_text("{}")
            return original(*args, **kwargs)

        monkeypatch.setattr(backup, "inventory", inventory)
    with pytest.raises(Exception):
        recovery.backup(slot, output)
    if kind == "existing_backup":
        assert output.read_bytes() == b"preserve"
    else:
        assert not output.exists()


def test_restore_refuses_existing_destination_and_preserves_incomplete_restore(
    profile, tmp_path, monkeypatch
):
    recovery, slot, data, output, protector, created = create(profile)
    destination = tmp_path / "recovered"
    destination.mkdir()
    (destination / "keep").write_text("preserve")
    with pytest.raises(ValueError):
        recovery.restore(slot, output, destination, created["sha256"])
    assert (destination / "keep").read_text() == "preserve"
    second = tmp_path / "interrupted"
    original = backup.install.write

    def interrupted(path, value):
        if value.get("status") == "complete":
            raise OSError("simulated failure")
        original(path, value)

    monkeypatch.setattr(backup.install, "write", interrupted)
    with pytest.raises(OSError):
        recovery.restore(slot, output, second, created["sha256"])
    assert json.loads((second / backup.RECEIPT).read_text())["status"] == "incomplete"
    with pytest.raises(ValueError):
        recovery.restore(slot, output, second, created["sha256"])
    assert recovery.manager.load()["current"] == slot


@pytest.mark.parametrize(
    "name",
    [
        ".",
        "../escape",
        "C:/escape",
        "dir\\escape",
        "CON",
        "dir/trailing.",
        "dir/space ",
        "file:stream",
        "LPT1.txt",
        "a//b",
    ],
)
def test_windows_noncanonical_and_device_paths_reject(name):
    with pytest.raises(ValueError):
        backup.path_name(name)


@pytest.mark.parametrize(
    "kind",
    [
        "compressed",
        "duplicate",
        "oversized_entry",
        "manifest_duplicate_key",
        "extra_directory",
        "file_directory_conflict",
        "resident_owner",
    ],
)
def test_inner_archive_contract_rejects_authenticated_but_invalid_content(
    profile, tmp_path, monkeypatch, kind
):
    recovery, slot, data, output, protector, created = create(profile)
    if kind in {"compressed", "duplicate", "manifest_duplicate_key"}:
        raw = backup.unseal(output.read_bytes(), protector)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = {item.filename: archive.read(item) for item in archive.infolist()}
        target = io.BytesIO()
        with zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED if kind == "compressed" else zipfile.ZIP_STORED,
        ) as archive:
            for name, value in entries.items():
                if kind == "manifest_duplicate_key" and name == "manifest.json":
                    value = value.replace(b'{"format": 2,', b'{"format": 2, "format": 2,', 1)
                archive.writestr(name, value)
            if kind == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("manifest.json", entries["manifest.json"])
        output.write_bytes(backup.seal(target.getvalue(), protector))
    elif kind == "oversized_entry":
        monkeypatch.setattr(backup, "MAX_FILE", 128)
    else:

        def change(manifest, files):
            if kind == "extra_directory":
                manifest["directories"].append("projects/missing/child")
            elif kind == "file_directory_conflict":
                manifest["directories"].append("settings.json")
            else:
                identity = json.loads((data / "desktop-profile/resident-identity.json").read_text())
                identity["id"] = str(uuid.uuid4())
                (data / "desktop-profile/resident-identity.json").write_text(json.dumps(identity))

        mutate(output, protector, change)
    with pytest.raises(Exception):
        recovery.preview(slot, output)


def test_restore_after_original_profile_is_missing_preserves_scope_and_still_requires_registered_package(
    profile, tmp_path
):
    recovery, slot, data, output, protector, created = create(profile)
    # Missing original identity is allowed; the authenticated inner identity still binds to the original installation/slot.
    (data / "desktop-profile/resident-identity.json").unlink()
    destination = tmp_path / "recovered"
    assert recovery.restore(slot, output, destination, created["sha256"])["restored"]
    assert (destination / "desktop-profile/resident-identity.json").exists()
    with pytest.raises(ValueError):
        recovery.preview("0" * 64, output)
