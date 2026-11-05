"""One-time move of a product folder from its INARA name to its JARVIS name.

The product was renamed from INARA to JARVIS, and so were its per-user folders
(``%LOCALAPPDATA%\\INARA`` -> ``%LOCALAPPDATA%\\JARVIS`` for the profile database and
``%APPDATA%\\inara`` -> ``%APPDATA%\\jarvis`` for the desktop profile). ``product_folder``
runs before anything opens the database and returns the folder this process must use:

* only the JARVIS folder exists (or neither): the JARVIS folder;
* both exist, only INARA holds real data (``has_data``): the fresh JARVIS folder is moved
  aside to ``JARVIS.fresh-<timestamp>`` (never deleted) and the migration below runs;
* both hold real data: the JARVIS folder; the INARA one is left untouched, nothing is
  merged, a warning is logged, ``.migration-conflict.json`` is written into the JARVIS
  folder and ``status()`` reports ``migration_conflict``;
* both exist and INARA holds no data: the JARVIS folder (logged);
* only the INARA folder exists: the tree is copied to a staging folder beside it, the copy
  is verified (same files, directories and sizes; ``PRAGMA integrity_check`` is ``ok`` for
  every SQLite file in it) and a small marker is written into it; then the INARA folder is
  renamed to ``INARA.migrated`` (never deleted), re-checked for changes made during the
  copy, and the staging folder becomes the JARVIS folder.

If any step fails, the partial copy is removed, any rename is undone (including a fresh
JARVIS folder that was moved aside), the INARA folder is
used for this run and a warning is logged, so the owner is never locked out of their data;
the next start tries again. DPAPI-protected values are bound to the Windows account, not
to the path, so they stay readable after the move.

Stdlib only: setup tools load this file directly, without the backend on ``sys.path``.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid

LEGACY = "INARA"  # Pre-rename folder name; this module exists to move it.
CURRENT = "JARVIS"
MARKER = ".migrated-from-inara.json"
CONFLICT_MARKER = ".migration-conflict.json"
SQLITE_HEADER = b"SQLite format 3\x00"

_logger = logging.getLogger("jarvis.migration")
_lock = threading.Lock()
_resolved = {}
_pending = []  # (level, message) logged before logging is configured, for replay.
_status = {}  # str(current folder) -> outcome; see status().


class MigrationError(RuntimeError):
    pass


def _log(level, message, *args):
    text = message % args if args else message
    _logger.log(level, text)
    if not logging.getLogger("jarvis").handlers:
        _pending.append((level, text))


def drain_pending():
    """Messages logged before ``configure_logging`` attached handlers (replayed once)."""
    with _lock:
        items = list(_pending)
        _pending.clear()
    return items


def _inventory(root):
    """{relative file: (bytes, mtime_ns)} and the set of relative directories; no links."""
    files, directories = {}, set()
    for folder, dirs, names in os.walk(root, followlinks=False):
        base = Path(folder)
        for name in dirs + names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise MigrationError(f"Linked entry is not migrated: {relative}")
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                status = path.stat()
                files[relative] = (status.st_size, status.st_mtime_ns)
            else:
                raise MigrationError(f"Unsupported entry is not migrated: {relative}")
    return files, directories


def _sizes(files):
    return {name: size for name, (size, _mtime) in files.items()}


def _is_sqlite(path):
    try:
        with open(path, "rb") as stream:
            return stream.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError as exc:
        raise MigrationError(f"Copied file is unreadable: {path.name}") from exc


def integrity_ok(path):
    """``PRAGMA integrity_check`` on one SQLite file (the copy, never the original)."""
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        return db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        db.close()


def _verify_copy(staging, expected_files, expected_directories):
    files, directories = _inventory(staging)
    if _sizes(files) != _sizes(expected_files) or directories != expected_directories:
        raise MigrationError("The copied file list or sizes differ from the original")
    for name in sorted(files):
        path = staging / name
        if _is_sqlite(path):
            try:
                ok = integrity_ok(path)
            except sqlite3.Error as exc:
                raise MigrationError(f"SQLite integrity check failed to run: {name}") from exc
            if not ok:
                raise MigrationError(f"SQLite integrity check is not ok: {name}")
    return files


def _retired_name(parent, legacy):
    target = parent / f"{legacy}.migrated"
    if not target.exists():
        return target
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return parent / f"{legacy}.migrated-{stamp}-{uuid.uuid4().hex[:6]}"


@contextmanager
def _exclusive(parent, current):
    """Serialise migrations of one folder across processes (released at process exit)."""
    path = parent / f".{current}.migration.lock"
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries for ~10 s
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        try:
            path.unlink()
        except OSError:
            pass  # Another process holds it open; it is an empty lock file.


def _writable_retry(function, path, _error):
    """rmtree helper: clear read-only and retry once; leave the entry if that also fails."""
    try:
        os.chmod(path, 0o700)
        function(path)
    except OSError:
        pass


def _migrate(old, new, legacy):
    parent = new.parent
    before_files, before_directories = _inventory(old)
    staging = parent / f".{new.name}.migrating-{uuid.uuid4().hex[:12]}"
    retired = None
    try:
        shutil.copytree(old, staging, symlinks=False, copy_function=shutil.copy2)
        copied = _verify_copy(staging, before_files, before_directories)
        marker = {
            "format": 1,
            "migrated_from": str(old),
            "original_kept_as": None,
            "files": len(copied),
            "bytes": sum(size for size, _mtime in copied.values()),
            "migrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        retired = _retired_name(parent, legacy)
        marker["original_kept_as"] = str(retired)
        (staging / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
        try:
            os.rename(old, retired)
        except OSError as exc:
            retired = None
            raise MigrationError("The original folder could not be renamed (is it in use?)") from exc
        after_files, after_directories = _inventory(retired)
        if after_files != before_files or after_directories != before_directories:
            raise MigrationError("The original folder changed while it was being copied")
        os.rename(staging, new)
        return retired
    except BaseException:
        if retired is not None and retired.exists() and not old.exists():
            try:
                os.rename(retired, old)
            except OSError:
                _log(
                    logging.ERROR,
                    "Could not restore %s from %s after a failed migration; your data is "
                    "intact in %s. Rename it back to %s before starting again.",
                    old.name, retired.name, retired, old.name,
                )
        if staging.exists():
            shutil.rmtree(staging, onexc=_writable_retry)
            if staging.exists():
                _log(logging.WARNING, "A partial migration copy remains at %s; it is safe to delete.", staging)
        raise


def _database_has_user_rows(path):
    """True when an assistant database holds any ``documents`` or ``sessions`` row.

    Opened read-only; an unreadable or damaged database counts as data (never set aside).
    """
    try:
        db = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return True
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return any(
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
            for table in ("documents", "sessions")
            if table in tables
        )
    except sqlite3.Error:
        return True
    finally:
        db.close()


def profile_has_data(folder):
    """Real owner data in a ``%LOCALAPPDATA%`` product folder.

    Either ``data-v1/assistant.sqlite3`` with at least one ``documents`` or ``sessions``
    row, or an installation root directly inside it (a child folder holding
    ``installation.json``). Logs, an empty database or empty folders alone are fresh.
    """
    folder = Path(folder)
    database = folder / "data-v1" / "assistant.sqlite3"
    if database.is_file() and _database_has_user_rows(database):
        return True
    try:
        return any(
            (child / "installation.json").is_file() for child in folder.iterdir() if child.is_dir()
        )
    except OSError:
        return True


def desktop_has_data(folder):
    """Real owner data in an ``%APPDATA%`` desktop profile: its ``resident-identity.json``.

    Everything else there is Chromium cache and state that a fresh profile recreates.
    """
    return (Path(folder) / "resident-identity.json").exists()


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _aside_name(parent, current):
    target = parent / f"{current}.fresh-{_stamp()}"
    return target if not target.exists() else parent / f"{target.name}-{uuid.uuid4().hex[:6]}"


def status():
    """Per-folder outcome for this process, for a capability/status snapshot.

    ``{str(current folder): {"state": ..., ...}}``; state is ``current`` (nothing to move),
    ``migrated``, ``fresh_replaced``, ``migration_conflict`` or ``failed``.
    """
    with _lock:
        return {key: dict(value) for key, value in _status.items()}


def _record(new, state, **details):
    with _lock:
        _status[str(new)] = {"state": state, **details}


def _write_conflict(new, old):
    marker = new / CONFLICT_MARKER
    if marker.exists():
        return
    value = {
        "format": 1,
        "state": "migration_conflict",
        "current": str(new),
        "legacy": str(old),
        "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Both folders hold data. JARVIS is used; nothing was merged or deleted.",
    }
    try:
        marker.write_text(json.dumps(value, indent=2), encoding="utf-8")
    except OSError:
        pass  # The warning and status() still report the conflict.


def product_folder(parent, legacy=LEGACY, current=CURRENT, has_data=profile_has_data):
    """The folder to use under ``parent``: ``current``, migrated from ``legacy`` if needed.

    ``has_data(folder)`` says whether a folder holds real owner data (see the module
    docstring for what happens when both folders exist).
    """
    parent = Path(parent)
    new, old = parent / current, parent / legacy
    key = (str(new).casefold(), str(old).casefold())
    with _lock:
        if key in _resolved:
            return _resolved[key]
    if not old.is_dir():
        result = new
        _record(new, "current")
    else:
        result = _locked_migration(parent, old, new, legacy, current, has_data)
    with _lock:
        _resolved[key] = result
    return result


def _both_exist(parent, old, new, current, has_data):
    """Both folders present (inside the lock): (folder to use, None) or (None, aside path)."""
    if not has_data(old):
        _log(
            logging.WARNING,
            "Both %s and %s exist and %s holds no data; using %s. %s was left untouched.",
            old, new, old, new, old,
        )
        _record(new, "current", legacy=str(old), legacy_has_data=False)
        return new, None
    if has_data(new):
        _log(
            logging.WARNING,
            "Both %s and %s hold data. Using %s and leaving %s untouched; nothing was "
            "merged. Move anything you need by hand (details in %s).",
            old, new, new, old, new / CONFLICT_MARKER,
        )
        _write_conflict(new, old)
        _record(new, "migration_conflict", legacy=str(old), marker=str(new / CONFLICT_MARKER))
        return new, None
    aside = _aside_name(parent, current)
    try:
        os.rename(new, aside)
    except OSError as exc:
        raise MigrationError(f"The fresh {new.name} folder could not be moved aside") from exc
    _log(logging.INFO, "%s held no data; moved it aside to %s before migrating.", new, aside)
    return None, aside


def _locked_migration(parent, old, new, legacy, current, has_data):
    aside = None
    try:
        with _exclusive(parent, current):
            if not old.is_dir():  # Another process finished the migration while we waited.
                _record(new, "current")
                return new
            if new.exists():
                chosen, aside = _both_exist(parent, old, new, current, has_data)
                if chosen is not None:
                    return chosen
            try:
                retired = _migrate(old, new, legacy)
            except BaseException:
                if aside is not None and not new.exists():
                    try:
                        os.rename(aside, new)
                        aside = None
                    except OSError:
                        _log(logging.ERROR, "Could not put %s back as %s; it is intact.", aside, new)
                raise
    except Exception as exc:
        _log(
            logging.WARNING,
            "Could not move %s to %s (%s: %s). Using %s for this run; nothing was deleted "
            "and the move will be retried on the next start.",
            old, new, type(exc).__name__, exc, old,
        )
        _record(new, "failed", legacy=str(old), error=type(exc).__name__)
        return old
    _log(logging.INFO, "Moved %s to %s; the original is kept as %s.", old, new, retired)
    details = {"legacy_kept_as": str(retired)}
    if aside is not None:
        details["fresh_moved_to"] = str(aside)
    _record(new, "fresh_replaced" if aside is not None else "migrated", **details)
    return new


def _reset_for_tests():
    with _lock:
        _resolved.clear()
        _pending.clear()
        _status.clear()
