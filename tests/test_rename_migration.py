"""INARA -> JARVIS rename: env fallback, one-time folder move, old backups, product copy."""

import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import struct
import sys
import zipfile

import pytest

from services import data_migration, env
from services.storage import Database, WindowsProtection, user_data_directory
from tests.test_desktop_backup import backup, create, profile  # noqa: F401
from tests.test_desktop_install import add, manager  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_state():
    env._reset_warnings_for_tests()
    data_migration._reset_for_tests()
    yield
    env._reset_warnings_for_tests()
    data_migration._reset_for_tests()


# --- environment variables -------------------------------------------------------------


def test_jarvis_name_wins_and_legacy_is_not_consulted(caplog):
    environ = {"JARVIS_BRAIN_MODEL": "new-model", "INARA_BRAIN_MODEL": "old-model"}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        assert env.getenv("BRAIN_MODEL", environ=environ) == "new-model"
        assert env.getenv("JARVIS_BRAIN_MODEL", environ=environ) == "new-model"
    assert not caplog.records
    # Set-but-empty still wins: callers blank a value this way.
    assert env.getenv("BRAIN_MODEL", "d", environ={"JARVIS_BRAIN_MODEL": "", "INARA_BRAIN_MODEL": "x"}) == ""


def test_legacy_name_falls_back_with_one_warning_per_variable_and_never_the_value(caplog):
    secret = "legacy-secret-value-0123456789"
    environ = {"INARA_SESSION_TOKEN": secret, "INARA_DATA_DIR": r"C:\private\profile"}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        for _ in range(3):
            assert env.getenv("SESSION_TOKEN", environ=environ) == secret
            assert env.getenv("JARVIS_DATA_DIR", environ=environ) == r"C:\private\profile"
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert any("INARA_SESSION_TOKEN" in m and "JARVIS_SESSION_TOKEN" in m for m in messages)
    assert any("INARA_DATA_DIR" in m and "JARVIS_DATA_DIR" in m for m in messages)
    assert all(secret not in m and "private" not in m for m in messages)
    assert env.getenv("MISSING", "default", environ=environ) == "default"


def test_lookup_applies_the_fallback_only_to_product_variables():
    environ = {"INARA_TWILIO_AUTH_TOKEN": "t", "GEMINI_API_KEY": "g"}
    assert env.lookup("JARVIS_TWILIO_AUTH_TOKEN", environ) == "t"
    assert env.lookup("GEMINI_API_KEY", environ) == "g"
    assert env.lookup("JARVIS_GEMINI_API_KEY", environ) is None
    assert env.names("DEV_SERVER") == ("JARVIS_DEV_SERVER", "INARA_DEV_SERVER")


def test_core_readers_accept_the_legacy_names(monkeypatch, tmp_path):
    from llm.router import brain_model
    from services.capability_profiles import model_id
    from services.secrets import resolve
    from telephony.gateway import configured_port
    from transport.session_token import current_token

    monkeypatch.delenv("JARVIS_BRAIN_MODEL", raising=False)
    monkeypatch.setenv("INARA_BRAIN_MODEL", "claude-legacy-name")
    monkeypatch.delenv("JARVIS_TEXT_MODEL", raising=False)
    monkeypatch.setenv("INARA_TEXT_MODEL", "gemini-legacy-name")
    assert brain_model() == "claude-legacy-name"
    assert model_id("text") == "gemini-legacy-name"
    assert configured_port({"INARA_TELEPHONY_PORT": "9123"}) == 9123
    assert configured_port({"INARA_TELEPHONY_PORT": "9123", "JARVIS_TELEPHONY_PORT": "9124"}) == 9124
    assert current_token({"INARA_SESSION_TOKEN": "legacy-token"}) == "legacy-token"
    assert resolve("twilio_phone_number", {"INARA_TWILIO_PHONE_NUMBER": "+60312345678"}) == "+60312345678"
    monkeypatch.delenv("JARVIS_DATA_DIR")
    monkeypatch.setenv("INARA_DATA_DIR", str(tmp_path / "legacy-override"))
    assert user_data_directory() == (tmp_path / "legacy-override").resolve()


# --- one-time folder move --------------------------------------------------------------


def make_database(path, rows=1, table="documents"):
    """An assistant-shaped database; ``rows`` user rows in ``table``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE documents(kind TEXT, id TEXT, payload BLOB)")
    db.execute("CREATE TABLE sessions(id TEXT, owner TEXT, project TEXT, payload BLOB)")
    for index in range(rows):
        db.execute(f"INSERT INTO {table} VALUES(?,?,?{',?' if table == 'sessions' else ''})",
                   (f"kept-{index}", "x", b"p", *((b"q",) if table == "sessions" else ())))
    db.commit()
    db.close()


def make_legacy(parent, name="INARA"):
    old = parent / name
    (old / "data-v1/logs").mkdir(parents=True)
    (old / "data-v1/logs/inara.log").write_text("old log\n")
    (old / "data-v1/empty").mkdir()
    make_database(old / "data-v1/assistant.sqlite3")
    return old


def make_fresh(parent, name="JARVIS", database=True):
    """What a first JARVIS start leaves behind: logs and an empty database."""
    new = parent / name
    (new / "data-v1/logs").mkdir(parents=True)
    (new / "data-v1/logs/jarvis.log").write_text("fresh log\n")
    if database:
        make_database(new / "data-v1/assistant.sqlite3", rows=0)
    return new


def tree(root):
    return {
        path.relative_to(root).as_posix(): (path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    }


def test_inara_only_is_copied_verified_and_kept_as_migrated(tmp_path):
    old = make_legacy(tmp_path)
    before = tree(old)
    result = data_migration.product_folder(tmp_path)
    new = tmp_path / "JARVIS"
    assert result == new and new.is_dir() and not old.exists()
    kept = tmp_path / "INARA.migrated"
    assert tree(kept) == before  # the original is renamed, never modified or deleted
    copied = {name: value for name, value in tree(new).items() if name != data_migration.MARKER}
    assert copied == before
    marker = json.loads((new / data_migration.MARKER).read_text())
    assert marker["original_kept_as"] == str(kept) and marker["files"] == 2
    db = sqlite3.connect(new / "data-v1/assistant.sqlite3")
    assert db.execute("SELECT kind FROM documents").fetchall() == [("kept-0",)]
    db.close()
    assert data_migration.status()[str(new)]["state"] == "migrated"
    assert not list(tmp_path.glob(".JARVIS.migrating-*"))
    # A second call (and a second process start) use JARVIS without touching anything.
    data_migration._reset_for_tests()
    assert data_migration.product_folder(tmp_path) == new and kept.exists()


@pytest.mark.parametrize("fresh", ["empty_database", "no_database", "bare_folder"])
def test_fresh_jarvis_is_moved_aside_and_inara_data_migrates(tmp_path, fresh):
    old = make_legacy(tmp_path)
    if fresh == "bare_folder":
        (tmp_path / "JARVIS/Pilot").mkdir(parents=True)  # e.g. an abandoned setup choice
    else:
        make_fresh(tmp_path, database=fresh == "empty_database")
    fresh_before = tree(tmp_path / "JARVIS")
    before = tree(old)
    new = data_migration.product_folder(tmp_path)
    assert new == tmp_path / "JARVIS"
    (aside,) = tmp_path.glob("JARVIS.fresh-*")
    assert tree(aside) == fresh_before  # set aside, never deleted
    assert tree(tmp_path / "INARA.migrated") == before
    assert {k: v for k, v in tree(new).items() if k != data_migration.MARKER} == before
    state = data_migration.status()[str(new)]
    assert state["state"] == "fresh_replaced" and state["fresh_moved_to"] == str(aside)


def test_both_with_real_data_keep_jarvis_and_record_a_conflict(tmp_path, caplog):
    old = make_legacy(tmp_path)
    new = make_fresh(tmp_path)
    (new / "data-v1/assistant.sqlite3").unlink()
    make_database(new / "data-v1/assistant.sqlite3", rows=2, table="sessions")
    before_old, before_new = tree(old), tree(new)
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        assert data_migration.product_folder(tmp_path) == new
    assert tree(old) == before_old and not (tmp_path / "INARA.migrated").exists()
    marker = json.loads((new / data_migration.CONFLICT_MARKER).read_text())
    assert marker["state"] == "migration_conflict" and marker["legacy"] == str(old)
    assert {k: v for k, v in tree(new).items() if k != data_migration.CONFLICT_MARKER} == before_new
    assert not list(tmp_path.glob("JARVIS.fresh-*"))
    assert data_migration.status()[str(new)]["state"] == "migration_conflict"
    assert any("hold data" in r.getMessage() and "nothing was merged" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)


def test_an_installation_root_counts_as_real_data(tmp_path):
    make_legacy(tmp_path)
    root = tmp_path / "JARVIS" / "Pilot"
    root.mkdir(parents=True)
    (root / "installation.json").write_text("{}")
    assert data_migration.product_folder(tmp_path) == tmp_path / "JARVIS"
    assert data_migration.status()[str(tmp_path / "JARVIS")]["state"] == "migration_conflict"
    assert (tmp_path / "INARA").is_dir() and (root / "installation.json").is_file()


def test_both_present_with_no_inara_data_keep_jarvis_untouched(tmp_path):
    old = make_fresh(tmp_path, "INARA")
    new = make_legacy(tmp_path, "JARVIS")
    before_old, before_new = tree(old), tree(new)
    assert data_migration.product_folder(tmp_path) == new
    assert tree(old) == before_old and tree(new) == before_new
    assert data_migration.status()[str(new)]["state"] == "current"


def test_failed_migration_puts_the_fresh_jarvis_folder_back(tmp_path, monkeypatch):
    old = make_legacy(tmp_path)
    new = make_fresh(tmp_path)
    fresh_before = tree(new)
    monkeypatch.setattr(data_migration, "integrity_ok", lambda path: False)
    assert data_migration.product_folder(tmp_path) == old
    assert tree(new) == fresh_before and not list(tmp_path.glob("JARVIS.fresh-*"))
    assert data_migration.status()[str(new)]["state"] == "failed"


def make_desktop(parent, name, identity=True):
    folder = parent / name
    (folder / "Cache").mkdir(parents=True)
    (folder / "Cache/data_0").write_bytes(b"chromium cache")
    db = sqlite3.connect(folder / "DIPS")  # Chromium creates SQLite files in every profile
    db.execute("CREATE TABLE t(x)")
    db.commit()
    db.close()
    if identity:
        (folder / "resident-identity.json").write_text(json.dumps({"id": name}))
    return folder


def test_desktop_profile_rule_uses_the_resident_identity(tmp_path):
    rule = {"legacy": "inara", "current": "jarvis", "has_data": data_migration.desktop_has_data}
    make_desktop(tmp_path, "inara")
    make_desktop(tmp_path, "jarvis", identity=False)
    assert data_migration.product_folder(tmp_path, **rule) == tmp_path / "jarvis"
    assert json.loads((tmp_path / "jarvis/resident-identity.json").read_text()) == {"id": "inara"}
    assert len(list(tmp_path.glob("jarvis.fresh-*"))) == 1 and (tmp_path / "inara.migrated").is_dir()

    other = tmp_path / "both"
    other.mkdir()
    make_desktop(other, "inara")
    make_desktop(other, "jarvis")
    data_migration._reset_for_tests()
    assert data_migration.product_folder(other, **rule) == other / "jarvis"
    assert (other / "jarvis" / data_migration.CONFLICT_MARKER).is_file()
    assert json.loads((other / "jarvis/resident-identity.json").read_text()) == {"id": "jarvis"}
    assert (other / "inara").is_dir()


def test_installation_create_migrates_before_making_a_root_inside_jarvis(tmp_path, monkeypatch):
    from tests.test_desktop_install import install

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(tmp_path)
    make_fresh(tmp_path)  # created by an earlier attempt, before any data was written
    install.Installation.create(tmp_path / "JARVIS" / "Pilot")
    assert (tmp_path / "JARVIS/data-v1/assistant.sqlite3").is_file()
    assert (tmp_path / "JARVIS/Pilot/installation.json").is_file()
    assert (tmp_path / "INARA.migrated").is_dir() and len(list(tmp_path.glob("JARVIS.fresh-*"))) == 1


def test_neither_present_uses_jarvis_without_creating_anything(tmp_path):
    assert data_migration.product_folder(tmp_path) == tmp_path / "JARVIS"
    assert list(tmp_path.iterdir()) == []


def partial_copy(source, target, **_):
    Path(target).mkdir()
    (Path(target) / "half.bin").write_bytes(b"partial")
    raise OSError("disk full (simulated)")


@pytest.mark.parametrize("failure", ["copy", "integrity", "rename", "changed"])
def test_any_failed_step_removes_the_copy_and_keeps_using_inara(tmp_path, monkeypatch, caplog, failure):
    old = make_legacy(tmp_path)
    before = tree(old)
    if failure == "copy":
        monkeypatch.setattr(data_migration.shutil, "copytree", partial_copy)
    elif failure == "integrity":
        monkeypatch.setattr(data_migration, "integrity_ok", lambda path: False)
    elif failure == "rename":
        real = os.rename

        def refuse(source, target):
            if Path(source) == old:
                raise PermissionError("in use (simulated)")
            return real(source, target)

        monkeypatch.setattr(data_migration.os, "rename", refuse)
    else:
        real_inventory = data_migration._inventory
        calls = []

        def drifting(root):
            calls.append(root)
            files, directories = real_inventory(root)
            if Path(root).name == "INARA.migrated":  # a writer touched it mid-copy
                files = {**files, "data-v1/late.txt": (1, 1)}
            return files, directories

        monkeypatch.setattr(data_migration, "_inventory", drifting)
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        assert data_migration.product_folder(tmp_path) == old
    assert tree(old) == before
    assert not (tmp_path / "JARVIS").exists() and not (tmp_path / "INARA.migrated").exists()
    assert not list(tmp_path.glob(".JARVIS.migrating-*"))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Using" in m and "nothing was deleted" in m for m in warnings)


def test_user_data_directory_migrates_the_default_location(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_DATA_DIR")
    monkeypatch.delenv("INARA_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(tmp_path)
    assert user_data_directory() == tmp_path / "JARVIS" / "data-v1"
    assert (tmp_path / "JARVIS/data-v1/assistant.sqlite3").is_file()
    assert (tmp_path / "INARA.migrated/data-v1/assistant.sqlite3").is_file()


def test_override_never_migrates(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "explicit"))
    assert user_data_directory() == (tmp_path / "explicit").resolve()
    assert (tmp_path / "INARA").is_dir() and not (tmp_path / "JARVIS").exists()


def test_messages_logged_before_logging_is_configured_are_replayed_to_the_log_file(tmp_path):
    from services.log import configure_logging, reset_logging

    reset_logging()
    make_legacy(tmp_path)
    data_migration.product_folder(tmp_path)
    stream = io.StringIO()
    try:
        path = configure_logging(directory=tmp_path / "logs", stream=stream)
        logging.getLogger("jarvis").handlers[0].flush()
        assert "Moved" in path.read_text(encoding="utf-8") and "INARA.migrated" in stream.getvalue()
    finally:
        reset_logging()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_protected_documents_stay_readable_after_the_move(tmp_path):
    old = tmp_path / "INARA" / "data-v1"
    database = Database(old, protection=WindowsProtection())
    with database.transaction() as db:
        database.put(db, "secrets", "gemini_api_key", {"value": "AIza-fixture-not-a-key"})
    assert data_migration.product_folder(tmp_path) == tmp_path / "JARVIS"
    moved = Database(tmp_path / "JARVIS" / "data-v1", protection=WindowsProtection())
    with moved.connection() as db:
        assert moved.get(db, "secrets", "gemini_api_key") == {"value": "AIza-fixture-not-a-key"}
    raw = (tmp_path / "JARVIS/data-v1/assistant.sqlite3").read_bytes()
    assert b"AIza-fixture-not-a-key" not in raw


# --- .inara backups ----------------------------------------------------------------------


def legacy_backup(source, target, protector):
    """Rewrite a current backup the way the pre-rename tool wrote it."""
    raw = backup.unseal(source.read_bytes(), protector)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {e.filename: archive.read(e) for e in archive.infolist() if e.filename != "manifest.json"}
    manifest["kind"] = backup.LEGACY_KIND
    for record in manifest["files"]:
        if record["path"] == backup.MARKER:
            record["path"] = backup.LEGACY_MARKER
    files["data/" + backup.LEGACY_MARKER] = files.pop("data/" + backup.MARKER)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, value in files.items():
            archive.writestr(name, value)
    key, nonce = os.urandom(32), os.urandom(12)
    wrapped = protector.protect(key)
    header = backup.LEGACY_MAGIC + struct.pack("<I", len(wrapped)) + wrapped + nonce
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    target.write_bytes(header + AESGCM(key).encrypt(nonce, payload.getvalue(), header))


def test_new_backups_are_jarvis_and_inara_backups_still_restore(profile, tmp_path):  # noqa: F811
    recovery, slot, data, output, protector, created = create(profile)
    assert output.suffix == ".jarvis" and output.read_bytes().startswith(b"JARVIS-PROFILE-1\x00")
    old = tmp_path / "profile.inara"
    legacy_backup(output, old, protector)
    assert old.read_bytes().startswith(b"INARA-PROFILE-1\x00")
    preview = recovery.preview(slot, old)
    assert preview["valid"]
    destination = tmp_path / "recovered-from-inara"
    assert recovery.restore(slot, old, destination, preview["sha256"])["restored"]
    files, _dirs = backup.inventory(data)
    for name, path in files.items():
        assert (destination / name).read_bytes() == path.read_bytes()
    assert (destination / backup.MARKER).is_file() and not (destination / backup.LEGACY_MARKER).exists()
    database = Database(destination / "database", protection=protector)
    with database.connection() as db:
        assert database.get(db, "fixture", "value")["text"] == "PRIVATE_RECORD"


# --- product copy ---------------------------------------------------------------------------


def test_persona_disclosures_and_spoken_lines_say_jarvis():
    from calls import contracts
    from services.conversation import PERSONA
    from services.voice_preview import PREVIEW_LINE
    from telephony import briefs, twiml

    assert PREVIEW_LINE == "Hello, I'm JARVIS. How can I help?"
    assert PERSONA.startswith("You are JARVIS,")
    assert contracts.CALL_INSTRUCTION.startswith("You are JARVIS, an AI assistant")
    assert "You've reached JARVIS, an AI assistant." in twiml.VOICEMAIL_MESSAGE
    nudges = [
        briefs.NUDGE_ONE_MINUTE, briefs.NUDGE_TIME_UP, briefs.NUDGE_SILENCE_CHECK,
        briefs.NUDGE_SILENCE_END, briefs.NUDGE_WRAP_UP,
    ]
    assert all(text.startswith("(JARVIS system: ") for text in nudges)
    assert "start with 'JARVIS system:' come from JARVIS itself" in briefs.COMMON
    assert "I'm JARVIS, an AI assistant." in briefs.opening_line(
        briefs.screening_brief({"direction": "inbound", "from": "+60111111111"}, {})
    )
    spoken = [PERSONA, PREVIEW_LINE, contracts.CALL_INSTRUCTION, twiml.VOICEMAIL_MESSAGE,
              briefs.COMMON, *nudges]
    for text in spoken:
        assert "INARA" not in text.upper() and "J.A.R.V.I.S" not in text, text
