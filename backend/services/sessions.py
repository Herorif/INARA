"""Durable scoped request ledger. An uncertain tool request is never auto-replayed."""

import json
from pathlib import Path

from services.storage import StorageError, scope_hash
from services.tools import ServiceError


class SessionStore:
    def __init__(self, database):
        self.database = database

    def _load(self, db, key, owner, project):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (key,)).fetchone()
        if row:
            if row["owner"] != scope_hash(owner) or row["project"] != scope_hash(project):
                raise ServiceError(
                    "conversation_scope", "Start a new conversation for this project."
                )
            return self.database.decode(
                f"session:{key}:{row['owner']}:{row['project']}", row["payload"]
            )
        return None

    def _save(self, db, key, owner, project, messages):
        owner, project = scope_hash(owner), scope_hash(project)
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET payload=excluded.payload",
            (
                key,
                owner,
                project,
                self.database.encode(f"session:{key}:{owner}:{project}", messages),
            ),
        )

    def restore(self, key, owner, project):
        with self.database.transaction() as db:
            return self._load(db, key, owner, project) or []

    def claim(self, key, owner, project, request_id, text):
        with self.database.transaction() as db:
            history = self._load(db, key, owner, project)
            if history is None:
                self._save(db, key, owner, project, [])
                history = []
            row = db.execute(
                "SELECT payload FROM requests WHERE session=? AND id=?", (key, request_id)
            ).fetchone()
            if row:
                previous = self.database.decode(f"request:{key}:{request_id}", row[0])
                if previous["text"] != text:
                    raise ServiceError("request_conflict", "This request ID was already used.")
                if previous["state"] == "running":
                    raise ServiceError(
                        "request_uncertain",
                        "This request is running or was interrupted. "
                        "Check its effects before submitting a new request.",
                    )
                return history, previous
            for row in db.execute("SELECT id,payload FROM requests WHERE session=?", (key,)):
                if (
                    self.database.decode(f"request:{key}:{row['id']}", row["payload"])["state"]
                    == "running"
                ):
                    raise ServiceError(
                        "conversation_busy",
                        "A previous request may be incomplete. "
                        "Check its effects and start a new conversation.",
                    )
            db.execute(
                "INSERT INTO requests VALUES(?,?,?)",
                (
                    key,
                    request_id,
                    self.database.encode(
                        f"request:{key}:{request_id}", {"text": text, "state": "running"}
                    ),
                ),
            )
            return history, None

    def finish(self, key, owner, project, request_id, text, result, history=None):
        with self.database.transaction() as db:
            self._load(db, key, owner, project)
            if history is not None:
                self._save(db, key, owner, project, history[-20:])
            db.execute(
                "UPDATE requests SET payload=? WHERE session=? AND id=?",
                (
                    self.database.encode(f"request:{key}:{request_id}", {"text": text, **result}),
                    key,
                    request_id,
                ),
            )

    def migrate_history(self, key, owner, project, source):
        """Import legacy project chat once, without mutating or executing its content."""
        if not source.exists():
            return
        if not source.resolve().is_relative_to(Path(project).resolve()):
            raise StorageError("Legacy chat path is outside the selected project.")
        marker = f"chat:{scope_hash(source.resolve())}"
        with self.database.connection() as db:
            if db.execute("SELECT 1 FROM migrations WHERE id=?", (marker,)).fetchone():
                return
        raw = self.database.read_legacy(source)
        digest = self.database.backup(source, raw)
        try:
            records = [
                json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()
            ]
            history = []
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                    raise ValueError("Invalid history")
                role = {"You": "user", "User": "user", "INARA": "assistant"}.get(
                    record.get("sender")
                )
                if role:
                    history.append({"role": role, "content": record["text"]})
        except (ValueError, TypeError, UnicodeError) as exc:
            raise StorageError(
                "Legacy chat validation failed; original and encrypted backup preserved."
            ) from exc
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM migrations WHERE id=?", (marker,)).fetchone():
                return
            if self._load(db, key, owner, project) is None:
                self._save(db, key, owner, project, history[-20:])
            db.execute("INSERT INTO migrations VALUES(?,?)", (marker, digest))
