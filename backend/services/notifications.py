"""Read-only selected notification ledger. No provider, tools or notification actions."""

import asyncio
import hashlib
import json
import re
import uuid
from collections import Counter
from typing import Annotated, Literal
from pydantic import Field, StrictBool, StrictInt, model_validator
from services.mobile_contracts import MobileModel, DeviceRequest
from services.tools import ServiceError

Package = Annotated[
    str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$", max_length=160)
]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class NotificationRule(MobileModel):
    package: Package
    all_conversations: StrictBool = False
    conversations: list[Digest] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def selected(self):
        if not self.all_conversations and not self.conversations:
            raise ValueError("Select conversation IDs or explicitly allow every conversation.")
        return self


class NotificationPolicy(DeviceRequest):
    enabled: StrictBool = False
    include_text: StrictBool = False
    retention_hours: Annotated[StrictInt, Field(ge=1, le=168)] = 24
    rules: list[NotificationRule] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_rules(self):
        packages = [rule.package for rule in self.rules]
        if len(set(packages)) != len(packages) or (self.enabled and not packages):
            raise ValueError("Select distinct application packages before enabling.")
        return self


class NotificationEvent(MobileModel):
    event_id: uuid.UUID
    source_id: Digest
    conversation: Digest
    package: Package
    timestamp: Annotated[StrictInt, Field(ge=0)]
    sequence: Annotated[StrictInt, Field(ge=0, le=9007199254740991)] = 0
    kind: Literal["posted", "removed"] = "posted"
    title: str = Field(default="", max_length=160, strict=True)
    text: str = Field(default="", max_length=1000, strict=True)


class NotificationBatch(MobileModel):
    revision: uuid.UUID
    events: list[NotificationEvent] = Field(min_length=1, max_length=10)


def redact(text):
    """Defense in depth, not a guarantee that free text contains no personal data."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    for pattern in (
        r"(?i)\b(?:https?://|www\.)\S+",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"(?i)\b(?:bearer\s+\S+|(?:password|token|secret|otp|code)\s*[:=]?\s*\S+)",
        r"(?<!\w)\+?\d[\d ()-]{3,}\d(?!\w)",
    ):
        text = re.sub(pattern, "[redacted]", text)
    return text.strip()


class NotificationInbox:
    kind = "notification_inbox_v1"

    def __init__(self, mobile):
        self.mobile = mobile
        self.database = mobile.app.database

    async def maintain(self):
        while True:
            try:
                self.expire()
            except Exception:
                # Never log content, device names, paths or raw storage errors.
                print("[SERVER] Notification expiry delayed; retrying in one minute.")
            await asyncio.sleep(60)

    def expire(self):
        for value in self.mobile.identities.list():
            with self.database.transaction() as db:
                if self.database.get(db, self.kind, value["device_id"]) is not None:
                    self.save(db, value, self.load(db, value))

    def device(self, owner, project, identifier):
        self.mobile.owner(owner)
        value = self.mobile.identities.get(str(identifier))
        if not value or value["owner"] != owner or value["project_path"] != str(project.resolve()):
            raise ServiceError("notification_scope", "Select a device paired to this project.")
        return value

    def load(self, db, value):
        saved = self.database.get(db, self.kind, value["device_id"]) or {
            "policy": {
                "enabled": False,
                "include_text": False,
                "retention_hours": 24,
                "rules": [],
                "revision": str(uuid.uuid4()),
            },
            "items": {},
            "seen": {},
            "clock": self.mobile.clock(),
        }
        now = self.mobile.clock()
        policy = saved["policy"]
        valid = not value["revoked"] and value["expires"] > now
        if now < saved["clock"] - 30 or not valid:
            policy["enabled"] = False
            policy["revision"] = str(uuid.uuid4())
            saved["items"], saved["seen"] = {}, {}
        cutoff = now - policy["retention_hours"] * 3600
        saved["items"] = {k: v for k, v in saved["items"].items() if v["timestamp"] > cutoff}
        saved["seen"] = {k: v for k, v in saved["seen"].items() if v["expires"] > now}
        saved["clock"] = max(now, saved["clock"])
        return saved

    def save(self, db, value, saved):
        self.database.put(db, self.kind, value["device_id"], saved)

    def configure(self, owner, project, args):
        value = self.device(owner, project, args.device_id)
        if args.enabled and (value["revoked"] or value["expires"] <= self.mobile.clock()):
            raise ServiceError("notification_scope", "Pair an active device first.")
        with self.database.transaction() as db:
            # Every scope change clears content and invalidates queued events, even regrant.
            saved = self.load(db, value)
            saved.update(
                policy={
                    **args.model_dump(mode="json", exclude={"device_id"}),
                    "revision": str(uuid.uuid4()),
                },
                items={},
                seen={},
            )
            self.save(db, value, saved)
        return self.view(owner, project, args.device_id)

    def clear(self, owner, project, identifier):
        value = self.device(owner, project, identifier)
        with self.database.transaction() as db:
            saved = self.load(db, value)
            saved["items"], saved["seen"] = {}, {}
            saved["policy"]["revision"] = str(uuid.uuid4())
            self.save(db, value, saved)
        return self.view(owner, project, identifier)

    def revoke(self, value):
        with self.database.transaction() as db:
            saved = self.load(db, value)
            saved["policy"]["enabled"] = False
            saved["policy"]["revision"] = str(uuid.uuid4())
            saved["items"], saved["seen"] = {}, {}
            self.save(db, value, saved)

    def policy(self, value):
        with self.database.transaction() as db:
            saved = self.load(db, value)
            self.save(db, value, saved)
        return {
            "project": value["project"],
            "policy": saved["policy"],
            "grant": "notifications:sync" if saved["policy"]["enabled"] else None,
        }

    def ingest(self, value, args):
        now = self.mobile.clock()
        with self.database.transaction() as db:
            saved = self.load(db, value)
            policy = saved["policy"]
            if not policy["enabled"] or str(args.revision) != policy["revision"]:
                raise ServiceError(
                    "notification_grant",
                    "Notification permission changed. Refresh and discard the old queue.",
                )
            rules = {rule["package"]: rule for rule in policy["rules"]}
            accepted = []
            for event in args.events:
                rule = rules.get(event.package)
                if not rule or (
                    not rule["all_conversations"]
                    and event.conversation not in rule["conversations"]
                ):
                    raise ServiceError(
                        "notification_scope", "Notification is outside the selected scope."
                    )
                if not now - policy["retention_hours"] * 3600 < event.timestamp <= now + 30:
                    raise ServiceError(
                        "notification_expired", "Notification timestamp is outside retention."
                    )
                event_id = str(event.event_id)
                # Hash redacted representation only; never persist a digest of raw secrets.
                item = event.model_dump(mode="json", exclude={"event_id"})
                item["title"] = redact(event.title) if policy["include_text"] else ""
                item["text"] = redact(event.text) if policy["include_text"] else ""
                fingerprint = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                seen = saved["seen"].get(event_id)
                if seen and seen["digest"] != fingerprint:
                    raise ServiceError(
                        "notification_conflict", "An event ID was reused with different content."
                    )
                if not seen:
                    if len(saved["seen"]) >= 2000:
                        raise ServiceError(
                            "notification_capacity",
                            "Retention ledger is full. Clear the inbox or wait for expiry.",
                        )
                    previous = saved["items"].get(event.source_id)
                    # Removal wins ties and remains a bounded tombstone to prevent resurrection.
                    if not previous or (
                        event.timestamp,
                        event.sequence,
                        event.kind == "removed",
                    ) > (
                        previous["timestamp"],
                        previous.get("sequence", 0),
                        previous["kind"] == "removed",
                    ):
                        saved["items"][event.source_id] = item
                    saved["seen"][event_id] = {
                        "digest": fingerprint,
                        "expires": event.timestamp + policy["retention_hours"] * 3600,
                    }
                accepted.append(event_id)
            # Do not evict live tombstones. Reject atomically until owner clears/expiry.
            if len(saved["items"]) > 200:
                raise ServiceError(
                    "notification_capacity", "Inbox is full. Clear it before syncing again."
                )
            self.save(db, value, saved)
        return {"accepted": accepted, "revision": policy["revision"]}

    def view(self, owner, project, identifier):
        value = self.device(owner, project, identifier)
        with self.database.transaction() as db:
            saved = self.load(db, value)
            self.save(db, value, saved)
        items = sorted(
            (item for item in saved["items"].values() if item["kind"] == "posted"),
            key=lambda item: item["timestamp"],
            reverse=True,
        )
        counts = Counter(item["package"] for item in items)
        return {
            "device_id": value["device_id"],
            "project": value["project"],
            "policy": saved["policy"],
            "items": items,
            "summary": {
                "total": len(items),
                "by_app": dict(counts),
                "method": "local_counts",
                "provider_used": False,
            },
            "read_only": True,
        }
