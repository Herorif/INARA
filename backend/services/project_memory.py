"""Small encrypted project collections and bounded local lexical retrieval.

No plaintext search index, background model, file scan, automatic saves or mobile grant.
"""

import base64
import binascii
from collections import Counter
import json
import math
from pathlib import Path
import re
import time
import unicodedata
import uuid
from services.memory_contracts import MemoryWrite
from services.storage import scope_hash
from services.tools import ServiceError

STOP = set(
    "a an the is are to for and or of in on my me it this that what how with please remember about".split()
)


def tokens(text):
    return [
        word
        for word in re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
        if word not in STOP and len(word) > 1
    ][:2000]


class ProjectMemory:
    kind = "project_memory_v1"

    def __init__(self, app, clock=time.time):
        self.app, self.database, self.clock = app, app.database, clock
        self.previews = {}

    def scope(self, owner, project):
        if not self.app.sessions.is_owner(owner) or not self.app.sessions.authenticated(owner):
            raise ServiceError("memory_owner", "Unlock the desktop owner to access project memory.")
        project = Path(project).resolve()
        if not project.is_dir() or project.parent != self.app.projects.projects_dir.resolve():
            raise ServiceError("memory_scope", "Select an available project first.")
        return scope_hash(owner + "\n" + str(project)), str(project)

    def load(self, db, owner, project):
        key, path = self.scope(owner, project)
        value = self.database.get(db, self.kind, key) or {
            "owner": owner,
            "project": path,
            "revision": str(uuid.uuid4()),
            "days": 90,
            "clock": self.clock(),
            "items": {},
        }
        if value["owner"] != owner or value["project"] != path:
            raise ServiceError("memory_scope", "Memory scope does not match this project.")
        if self.clock() < value["clock"] - 30:
            raise ServiceError(
                "memory_clock", "Laptop clock moved backwards. Correct it before using memory."
            )
        retained = {
            k: item for k, item in value["items"].items() if item["expires_at"] > self.clock()
        }
        if retained != value["items"]:
            value["items"], value["revision"] = retained, str(uuid.uuid4())
        value["clock"] = max(value["clock"], self.clock())
        self.database.put(db, self.kind, key, value)
        return key, value

    def check_revision(self, value, revision):
        if value["revision"] != str(revision):
            raise ServiceError(
                "memory_stale", "Memory changed. Refresh and review before applying this edit."
            )

    def commit(self, db, key, value):
        if len(json.dumps(value["items"]).encode()) > 750000:
            raise ServiceError(
                "memory_capacity",
                "Memory exceeds the protected collection size limit. Shorten or forget notes first.",
            )
        value["revision"] = str(uuid.uuid4())
        self.database.put(db, self.kind, key, value)

    def snapshot(self, owner, project, query="", include_archived=False):
        with self.database.transaction() as db:
            _, value = self.load(db, owner, project)
        items = [
            item for item in value["items"].values() if include_archived or not item["archived"]
        ]
        results = (
            self.rank(items, query)
            if query.strip()
            else sorted(items, key=lambda item: item["updated_at"], reverse=True)
        )
        return {
            "project": Path(project).name,
            "revision": value["revision"],
            "retention_days": value["days"],
            "total": len(value["items"]),
            "items": results,
            "search_method": "local_lexical",
            "provider_used": False,
            "limit": 200,
        }

    @staticmethod
    def rank(items, query):
        terms = set(tokens(query))
        if not terms:
            return []
        documents = [
            (
                item,
                Counter(tokens(item["text"])),
                Counter(tokens(item["title"] + " " + " ".join(item["tags"]))),
            )
            for item in items
        ]
        frequencies = Counter(
            term for _, body, title in documents for term in terms if term in body or term in title
        )
        scored = []
        for item, body, title in documents:
            score = sum(
                (1 + math.log((len(items) + 1) / (frequencies[term] + 1)))
                * (min(body[term], 3) + 4 * min(title[term], 2))
                for term in terms
            )
            if score:
                scored.append((score, item))
        return [
            item
            for _, item in sorted(
                scored, key=lambda pair: (-pair[0], -pair[1]["updated_at"], pair[1]["id"])
            )
        ]

    def write(self, owner, project, args):
        now = self.clock()
        with self.database.transaction() as db:
            key, value = self.load(db, owner, project)
            self.check_revision(value, args.revision)
            identifier = str(args.id)
            old = value["items"].get(identifier)
            if not old and len(value["items"]) >= 200:
                raise ServiceError(
                    "memory_capacity",
                    "This project holds 200 notes. Forget or export notes before adding more.",
                )
            item = args.model_dump(mode="json", exclude={"revision", "retention_days"})
            item.update(
                created_at=old["created_at"] if old else now,
                updated_at=now,
                expires_at=now + min(args.retention_days, value["days"]) * 86400,
                version=(old["version"] + 1) if old else 1,
            )
            value["items"][identifier] = item
            self.commit(db, key, value)
        return self.snapshot(owner, project, include_archived=True)

    def forget(self, owner, project, args):
        with self.database.transaction() as db:
            key, value = self.load(db, owner, project)
            self.check_revision(value, args.revision)
            value["items"].pop(str(args.id), None)
            self.commit(db, key, value)
        self.previews.clear()
        return self.snapshot(owner, project, include_archived=True)

    def retention(self, owner, project, args):
        with self.database.transaction() as db:
            key, value = self.load(db, owner, project)
            self.check_revision(value, args.revision)
            value["days"] = args.days
            for item in value["items"].values():
                # A longer policy never silently extends previously approved retention.
                item["expires_at"] = min(item["expires_at"], self.clock() + args.days * 86400)
            self.commit(db, key, value)
        return self.snapshot(owner, project, include_archived=True)

    def export(self, owner, project):
        with self.database.transaction() as db:
            _, value = self.load(db, owner, project)
        payload = {
            "format": 1,
            "owner": owner,
            "project": str(Path(project).resolve()),
            "items": list(value["items"].values()),
            "exported_at": self.clock(),
        }
        encrypted = self.database.encode("project-memory-backup-v1", payload)
        return {
            "backup": base64.b64encode(encrypted).decode(),
            "count": len(payload["items"]),
            "protection": "windows_user_bound",
            "portable": False,
        }

    def preview(self, owner, project, args):
        _, path = self.scope(owner, project)
        try:
            encrypted = base64.b64decode(args.backup, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ServiceError(
                "memory_backup", "Choose an intact INARA protected memory backup."
            ) from exc
        payload = self.database.decode("project-memory-backup-v1", encrypted)
        if (
            payload.get("format") != 1
            or payload.get("owner") != owner
            or payload.get("project") != path
        ):
            raise ServiceError("memory_scope", "This backup belongs to another owner or project.")
        if not isinstance(payload.get("items"), list) or len(payload["items"]) > 200:
            raise ServiceError("memory_backup", "Backup exceeds the memory collection limit.")
        current = self.snapshot(owner, project, include_archived=True)
        existing = {item["id"] for item in current["items"]}
        candidates = []
        seen = set()
        for item in payload["items"]:
            # Validate backup records too; protected bytes are not executable instructions.
            request = MemoryWrite.model_validate(
                {key: item[key] for key in MemoryWrite.model_fields if key in item}
                | {"revision": current["revision"]}
            )
            identifier = str(request.id)
            if identifier in seen:
                raise ServiceError("memory_backup", "Duplicate identifiers in backup.")
            seen.add(identifier)
            expiry = item.get("expires_at")
            if (
                not isinstance(expiry, (int, float))
                or not math.isfinite(expiry)
                or expiry <= self.clock()
                or identifier in existing
            ):
                continue
            candidate = request.model_dump(mode="json", exclude={"revision", "retention_days"})
            # Recovery always disables assistant sharing and starts a new reviewed version.
            candidate.update(
                assistant_enabled=False,
                created_at=self.clock(),
                updated_at=self.clock(),
                expires_at=min(expiry, self.clock() + current["retention_days"] * 86400),
                version=1,
            )
            candidates.append(candidate)
        if current["total"] + len(candidates) > 200:
            raise ServiceError(
                "memory_capacity", "Restoring these notes would exceed 200. No data was changed."
            )
        combined = {item["id"]: item for item in [*current["items"], *candidates]}
        if len(json.dumps(combined).encode()) > 750000:
            raise ServiceError(
                "memory_capacity",
                "Recovery would exceed the protected collection size limit. No data was changed.",
            )
        self.prune_previews()
        if len(self.previews) >= 4:
            raise ServiceError(
                "memory_preview_limit", "Close another recovery preview or wait two minutes."
            )
        identifier = str(uuid.uuid4())
        self.previews[identifier] = {
            "owner": owner,
            "project": path,
            "expires": self.clock() + 120,
            "revision": current["revision"],
            "items": candidates,
        }
        return {
            "preview_id": identifier,
            "revision": current["revision"],
            "items": candidates,
            "skipped": len(payload["items"]) - len(candidates),
            "expires_in": 120,
            "assistant_enabled": False,
        }

    def prune_previews(self):
        self.previews = {k: v for k, v in self.previews.items() if v["expires"] > self.clock()}

    def restore(self, owner, project, args):
        _, path = self.scope(owner, project)
        self.prune_previews()
        preview = self.previews.get(str(args.preview_id))
        if not preview or preview["owner"] != owner or preview["project"] != path:
            raise ServiceError(
                "memory_preview", "Recovery preview expired. Preview the backup again."
            )
        with self.database.transaction() as db:
            key, value = self.load(db, owner, project)
            self.check_revision(value, args.revision)
            self.check_revision(value, preview["revision"])
            for item in preview["items"]:
                if item["expires_at"] > self.clock():
                    value["items"][item["id"]] = item
            self.commit(db, key, value)
        self.previews.pop(str(args.preview_id), None)
        return self.snapshot(owner, project, include_archived=True)

    def context(self, owner, project, query, sid):
        if (
            self.app.sessions.roles.get(sid) != "renderer"
            or self.app.sessions.principals.get(sid) != owner
            or not self.app.sessions.is_owner(owner)
        ):
            return {"revision": None, "items": [], "sources": []}
        with self.database.transaction() as db:
            _, value = self.load(db, owner, project)
        items = self.rank(
            [
                item
                for item in value["items"].values()
                if item["assistant_enabled"] and not item["archived"]
            ],
            query,
        )
        selected, size = [], 0
        for item in items[:4]:
            if (
                size
                + len(json.dumps({key: item[key] for key in ("id", "title", "text", "source")}))
                > 6000
            ):
                continue
            selected.append(item)
            size += len(json.dumps({key: item[key] for key in ("id", "title", "text", "source")}))
        return {
            "revision": value["revision"],
            "items": [
                {key: item[key] for key in ("id", "title", "text", "source")} for item in selected
            ],
            "sources": [
                {key: item[key] for key in ("id", "title", "source", "version")}
                for item in selected
            ],
        }

    def validate_context(self, owner, project, context):
        if context["revision"] is not None:
            with self.database.transaction() as db:
                _, value = self.load(db, owner, project)
                self.check_revision(value, context["revision"])

    async def maintain(self):
        import asyncio

        while True:
            try:
                self.prune_previews()
                with self.database.transaction() as db:
                    rows = db.execute("SELECT id,payload FROM documents WHERE kind=?", (self.kind,))
                    for row in rows:
                        value = self.database.decode(f"{self.kind}:{row['id']}", row["payload"])
                        items = {
                            k: item
                            for k, item in value["items"].items()
                            if item["expires_at"] > self.clock()
                        }
                        if items != value["items"]:
                            value["items"] = items
                            self.commit(
                                db, scope_hash(value["owner"] + "\n" + value["project"]), value
                            )
            except Exception:
                print("[SERVER] Project memory expiry delayed; retrying in one minute.")
            await asyncio.sleep(60)
