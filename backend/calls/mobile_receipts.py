"""Read-only, opt-in mobile view of finished core-owned calls, never lab fixtures."""

import math
import uuid

from calls.records import CallRecords
from services.storage import Database
from services.tools import ServiceError


class MobileCallReceipts:
    def __init__(self, mobile):
        self.mobile, self.app = mobile, mobile.app

    def runs(self, value):
        self.mobile.recheck(value, "calls:read")
        current = self.mobile.identities.get(value["device_id"])
        if current["owner"] != value["owner"] or current["project_path"] != value["project_path"]:
            raise ServiceError("mobile_scope", "The call receipt grant scope changed.")
        from pathlib import Path
        project = Path(value["project_path"])
        key = self.app.call_admission.scope(value["owner"], project)
        with self.app.database.connection() as db:
            book = self.app.database.get(db, self.app.call_admission.kind, key) or {"runs": []}
        now = self.mobile.clock()
        return [item for item in book["runs"] if item.get("state") in {"completed", "interrupted", "failed", "uncertain"}
                and item.get("source") in {"sim", "whatsapp_personal"}
                and all(type(item.get(k)) in (int, float) and math.isfinite(item[k]) for k in ("started_at", "finished_at"))
                and now - 7 * 86400 <= item["started_at"] <= item["finished_at"] <= now + 30]

    def summary(self, item):
        return {"id": str(uuid.UUID(item["id"])), "source": item["source"], "state": item["state"],
                "started_at": item["started_at"], "finished_at": item["finished_at"],
                "identity_verified": False, "message_confirmed": False}

    def list(self, value):
        receipts = [self.summary(item) for item in sorted(self.runs(value), key=lambda item: item["started_at"], reverse=True)[:20]]
        self.mobile.recheck(value, "calls:read")
        return {"project": value["project"], "receipts": receipts, "read_only": True, "raw_audio_retained": False}

    def detail(self, value, args):
        item = next((item for item in self.runs(value) if item["id"] == str(args.id)), None)
        if not item or not item.get("record_id"):
            raise ServiceError("call_receipt_unavailable", "This finished call record is unavailable or expired.")
        from pathlib import Path
        directory = self.app.call_admission.records_directory(value["owner"], Path(value["project_path"]))
        if not (directory / "assistant.sqlite3").is_file():
            raise ServiceError("call_receipt_unavailable", "This finished call record is unavailable or expired.")
        record = next((record for record in CallRecords(Database(directory), self.mobile.clock).recent()
                       if record["id"] == item["record_id"] and "finished_at" in record), None)
        if not record or record["source"] != item["source"]:
            raise ServiceError("call_receipt_unavailable", "This finished call record is unavailable or expired.")
        transcript = record.get("transcript", [])
        if (len(transcript) > 200 or any(segment.get("role") not in {"caller", "assistant"}
                or not isinstance(segment.get("text"), str) or len(segment["text"]) > 12000 for segment in transcript)
                or sum(len(segment["text"]) for segment in transcript) > 12000):
            raise ServiceError("call_receipt_invalid", "This call transcript exceeds the mobile boundary.")
        self.mobile.recheck(value, "calls:read")
        return {"project": value["project"], "receipt": {**self.summary(item),
                "transcript": [{"role": segment["role"], "text": segment["text"]} for segment in transcript]},
                "read_only": True, "raw_audio_retained": False}
