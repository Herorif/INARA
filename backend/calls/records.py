"""Private lab records, separate from owner history. No raw call audio is retained."""

import time
import uuid

from services.storage import scope_hash
from services.tools import ServiceError


class CallRecords:
    kind = "personal_call_lab_v1"

    def __init__(self, database, clock=time.time):
        self.database, self.clock = database, clock

    def stamp(self, db):
        now = self.clock()
        clock = self.database.get(db, "personal_call_lab_clock_v1", "clock") or {"stamp": now}
        if now < clock["stamp"] - 30:
            raise ServiceError("call_clock", "Correct the clock before accessing the call lab.")
        self.database.put(db, "personal_call_lab_clock_v1", "clock", {"stamp": max(now, clock["stamp"])})
        return now

    def claim(self, channel, observation):
        key = scope_hash(channel + ":" + observation.fingerprint)
        with self.database.transaction() as db:
            now = self.stamp(db)
            for row in db.execute("SELECT id FROM documents WHERE kind=?", (self.kind,)).fetchall():
                item = self.database.get(db, self.kind, row["id"])
                if item["started_at"] < now - 7 * 86400:
                    db.execute("DELETE FROM documents WHERE kind=? AND id=?", (self.kind, row["id"]))
            if self.database.get(db, self.kind, key):
                raise ServiceError("call_already_attempted", "This observed call was already attempted; it will not be answered again.")
            if db.execute("SELECT count(*) FROM documents WHERE kind=?", (self.kind,)).fetchone()[0] >= 256:
                raise ServiceError("call_record_limit", "The seven-day call-lab ledger is full.")
            value = {"id": str(uuid.uuid4()), "source": channel, "state": "accepting",
                     "started_at": self.clock(), "caller_hash": observation.caller_hash,
                     "identity_verified": False, "transcript": [], "message_confirmed": False}
            self.database.put(db, self.kind, key, value)
        return key, value

    def finish(self, key, value):
        with self.database.transaction() as db:
            self.database.put(db, self.kind, key, {**value, "finished_at": self.stamp(db)})

    def progress(self, key, value):
        with self.database.transaction() as db:
            self.stamp(db)
            previous = self.database.get(db, self.kind, key)
            if not previous or "finished_at" in previous or previous["id"] != value["id"]:
                raise ServiceError("call_record_stale", "This call record is no longer active.")
            self.database.put(db, self.kind, key, value)

    def recent(self):
        with self.database.transaction() as db:
            now = self.stamp(db)
            values = []
            for row in db.execute("SELECT id FROM documents WHERE kind=?", (self.kind,)).fetchall():
                item = self.database.get(db, self.kind, row["id"])
                if item["started_at"] < now - 7 * 86400:
                    db.execute("DELETE FROM documents WHERE kind=? AND id=?", (self.kind, row["id"]))
                else:
                    # An unfinished record after a restart is uncertain, never replayable.
                    if "finished_at" not in item:
                        item = {**item, "state": "uncertain"}
                    values.append(item)
            return sorted(values, key=lambda item: item["started_at"], reverse=True)[:40]
