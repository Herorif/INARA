"""Private call records, separate from owner history. No raw call audio is retained.

Records are DPAPI-protected documents (services.storage) kept for seven days. Schema 1
records come from the local call lab (``claim``/``progress``/``finish``): id, source,
state, timestamps, caller_hash and the transcript. Schema 2 (C2, phone calls through the
telephony gateway, ``save_call``) adds the structured fields: direction, mode, a masked
counterpart number with a keyed hash for grouping, duration, the fields the call agent's
tools captured, the outcome and the triage. Older records are upgraded when read: they
gain the structured keys with empty values and are otherwise unchanged.
"""

import copy
import hashlib
import hmac
import secrets
import time
import uuid

from services.storage import scope_hash
from services.tools import ServiceError
from telephony.numbers import mask_display, normalize, withheld

SCHEMA = 2
RETENTION_SECONDS = 7 * 86400
RECORD_LIMIT = 256
KEY_KIND = "personal_call_lab_key_v1"
STRUCTURED = {
    "direction": None,
    "mode": None,
    "counterpart": None,  # {"masked": "+60 12-•••• 6789", "key": keyed hash} or None
    "duration_seconds": None,
    "fields": {},  # what the call agent's tools captured
    "outcome": None,
    "end_reason": None,
    "triage": None,
    "triage_state": None,  # pending | done | failed | skipped
}


def upgrade(item):
    """A stored record in the current schema; older records gain empty structured fields."""
    if item.get("schema") == SCHEMA:
        return item
    value = {**copy.deepcopy(STRUCTURED), **item, "schema": SCHEMA}
    started, finished = item.get("started_at"), item.get("finished_at")
    if (value["duration_seconds"] is None and isinstance(started, (int, float))
            and isinstance(finished, (int, float))):
        value["duration_seconds"] = round(max(0.0, finished - started), 3)
    return value


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

    def _expire(self, db, now):
        """Delete records older than seven days; returns the remaining ``(key, record)``."""
        kept = []
        for row in db.execute("SELECT id FROM documents WHERE kind=?", (self.kind,)).fetchall():
            item = self.database.get(db, self.kind, row["id"])
            if item["started_at"] < now - RETENTION_SECONDS:
                db.execute("DELETE FROM documents WHERE kind=? AND id=?", (self.kind, row["id"]))
            else:
                kept.append((row["id"], item))
        return kept

    def claim(self, channel, observation):
        key = scope_hash(channel + ":" + observation.fingerprint)
        with self.database.transaction() as db:
            now = self.stamp(db)
            self._expire(db, now)
            if self.database.get(db, self.kind, key):
                raise ServiceError("call_already_attempted", "This observed call was already attempted; it will not be answered again.")
            if db.execute("SELECT count(*) FROM documents WHERE kind=?", (self.kind,)).fetchone()[0] >= RECORD_LIMIT:
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
            for _key, item in self._expire(db, now):
                # An unfinished record after a restart is uncertain, never replayable.
                if "finished_at" not in item:
                    item = {**item, "state": "uncertain"}
                values.append(upgrade(item))
            return sorted(values, key=lambda item: item["started_at"], reverse=True)[:40]

    # --- phone calls (C2) --------------------------------------------------------------

    def _secret(self, db):
        value = self.database.get(db, KEY_KIND, "counterpart")
        if not (isinstance(value, dict) and isinstance(value.get("key"), str)):
            value = {"key": secrets.token_hex(32)}
            self.database.put(db, KEY_KIND, "counterpart", value)
        return bytes.fromhex(value["key"])

    def counterpart(self, number):
        """Masked display number and a keyed (per-profile HMAC) hash for grouping calls."""
        target = None if withheld(number) else normalize(number)
        if target is None:
            return {"masked": "withheld", "key": None}
        with self.database.transaction() as db:
            secret = self._secret(db)
        key = hmac.new(secret, target.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return {"masked": mask_display(target), "key": key}

    def save_call(self, record):
        """Store one finished phone call (schema 2). At the record limit the oldest record
        gives way, so a call that already happened is never refused."""
        value = {**copy.deepcopy(STRUCTURED), **record, "schema": SCHEMA}
        if not isinstance(value.get("id"), str) or not value["id"]:
            raise ValueError("A call record needs an id.")
        with self.database.transaction() as db:
            now = self.stamp(db)
            kept = [item for item in self._expire(db, now) if item[0] != value["id"]]
            for key, _item in sorted(kept, key=lambda pair: pair[1]["started_at"])[
                : max(0, len(kept) - RECORD_LIMIT + 1)
            ]:
                db.execute("DELETE FROM documents WHERE kind=? AND id=?", (self.kind, key))
            self.database.put(db, self.kind, value["id"], value)
        return value

    def get(self, record_id):
        """One record within retention (upgraded), or None."""
        with self.database.transaction() as db:
            now = self.stamp(db)
            for key, item in self._expire(db, now):
                if key == record_id or item.get("id") == record_id:
                    if "finished_at" not in item:
                        item = {**item, "state": "uncertain"}
                    return upgrade(item)
        return None

    def set_triage(self, record_id, triage, state):
        """Attach the triage result (or its failure) to a stored phone call record."""
        with self.database.transaction() as db:
            self.stamp(db)
            item = self.database.get(db, self.kind, record_id)
            if not item:
                return False
            self.database.put(
                db, self.kind, record_id, {**upgrade(item), "triage": triage, "triage_state": state}
            )
        return True
