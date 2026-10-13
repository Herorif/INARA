"""Versioned local storage. Private JSON is protected before SQLite/WAL sees it."""

import ctypes
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class StorageError(RuntimeError):
    pass


class WindowsProtection:
    """Windows user-bound DPAPI; no machine-wide key or plaintext fallback."""

    def __init__(self):
        if os.name != "nt":
            raise StorageError("OS-protected storage currently requires Windows.")

    def _transform(self, data, decrypt=False):
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        target = Blob()
        library = ctypes.WinDLL("crypt32", use_last_error=True)
        function = library.CryptUnprotectData if decrypt else library.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise StorageError("Windows could not protect or unlock private storage.")
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
            free.argtypes = [ctypes.c_void_p]
            free.restype = ctypes.c_void_p
            free(target.data)

    def protect(self, data):
        return self._transform(data)

    def unprotect(self, data):
        return self._transform(data, decrypt=True)


def user_data_directory():
    override = os.getenv("INARA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.getenv("LOCALAPPDATA")
    if not local:
        raise StorageError("Set INARA_DATA_DIR to an OS-protected data directory.")
    return Path(local) / "INARA" / "data-v1"


def scope_hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


class Database:
    def __init__(self, directory=None, protection=None):
        self.directory = Path(directory) if directory is not None else user_data_directory()
        self.protection = protection or WindowsProtection()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "assistant.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise StorageError("Unsupported database version; keep this data for recovery.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, id TEXT NOT NULL, payload BLOB NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, project TEXT NOT NULL,
                    payload BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    session TEXT NOT NULL REFERENCES sessions(id), id TEXT NOT NULL,
                    payload BLOB NOT NULL, PRIMARY KEY(session,id));
                CREATE TABLE IF NOT EXISTS migrations (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def encode(self, context, value):
        data = json.dumps({"context": context, "value": value}, allow_nan=False).encode()
        return self.protection.protect(data)

    def decode(self, context, payload):
        try:
            data = json.loads(self.protection.unprotect(payload))
            if data["context"] != context:
                raise ValueError("Scope mismatch")
            return data["value"]
        except Exception as exc:
            raise StorageError(
                "Private storage could not be decoded; preserve it for recovery."
            ) from exc

    def put(self, db, kind, key, value):
        db.execute(
            "INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,id) "
            "DO UPDATE SET payload=excluded.payload",
            (kind, key, self.encode(f"{kind}:{key}", value)),
        )

    def get(self, db, kind, key):
        row = db.execute(
            "SELECT payload FROM documents WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return self.decode(f"{kind}:{key}", row[0]) if row else None

    def all(self, db, kind):
        return [
            self.decode(f"{kind}:{row['id']}", row["payload"])
            for row in db.execute("SELECT id,payload FROM documents WHERE kind=?", (kind,))
        ]

    def backup(self, source, raw):
        """Immutable encrypted source snapshot; the original is never modified."""
        digest = hashlib.sha256(raw).hexdigest()
        key = f"{scope_hash(Path(source).resolve())}-{digest}"
        folder = self.directory / "migration-backups"
        folder.mkdir(exist_ok=True)
        path = folder / f"{key}.dpapi"
        # Concurrent migrators may create the same complete snapshot; use atomic replace.
        if not path.exists():
            import uuid

            temporary = folder / f"{key}.{uuid.uuid4()}.tmp"
            try:
                temporary.write_bytes(self.encode(f"backup:{key}", {"bytes_hex": raw.hex()}))
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        restored = self.decode(f"backup:{key}", path.read_bytes())
        if bytes.fromhex(restored["bytes_hex"]) != raw:
            raise StorageError(
                "Migration backup did not match the source; preserve both for recovery."
            )
        return digest

    def read_legacy(self, source):
        # Bound one-time migration memory independently of the resident runtime.
        limit = 16 * 1024 * 1024
        with Path(source).open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise StorageError(
                "Legacy record file exceeds the 16 MiB migration limit. "
                "Preserve it and use a reviewed split/import before retrying."
            )
        return raw
