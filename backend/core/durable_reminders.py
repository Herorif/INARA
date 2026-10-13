"""Transactional reminders and leased, acknowledged deliveries for the local owner."""

import datetime as dt
import json
import math
import time
import uuid
from zoneinfo import ZoneInfo

from services.storage import Database, StorageError, scope_hash


def local_instant(wall, timezone):
    """Ambiguity uses fold=0; nonexistent wall time advances to the first valid minute."""
    zone = ZoneInfo(timezone)
    for _ in range(181):
        candidate = wall.replace(tzinfo=zone, fold=0)
        if dt.datetime.fromtimestamp(candidate.timestamp(), zone).replace(tzinfo=None) == wall:
            return candidate.timestamp()
        wall += dt.timedelta(minutes=1)
    raise ValueError("Cannot resolve local reminder time")


def next_occurrence(reminder, now):
    zone = ZoneInfo(reminder.timezone)
    local = dt.datetime.fromtimestamp(reminder.trigger_at, zone)
    clock = dt.time.fromisoformat(reminder.wall_time) if reminder.wall_time else local.time()
    wall = dt.datetime.combine(local.date(), clock)
    interval = 7 if reminder.recurring == "weekly" else 1
    elapsed = (dt.datetime.fromtimestamp(now, zone).date() - local.date()).days
    wall += dt.timedelta(days=max(0, elapsed // interval - 1) * interval)
    while True:
        wall += dt.timedelta(days=7 if reminder.recurring == "weekly" else 1)
        if reminder.recurring == "weekdays" and wall.weekday() >= 5:
            continue
        candidate = local_instant(wall, reminder.timezone)
        if candidate > now:
            return candidate


class DurableReminderStore:
    def __init__(self, backend_dir=None, database=None):
        from pathlib import Path
        from core.reminder_store import Reminder, Routine

        self.Reminder, self.Routine = Reminder, Routine
        # Explicit directories are used by tests/isolated callers; production uses user data.
        self.database = database or Database(Path(backend_dir) / "data-v1" if backend_dir else None)
        source = Path(backend_dir) if backend_dir else Path(__file__).parent.parent
        self.migrate(source)

    def _all(self, db):
        return [self.Reminder.from_dict(value) for value in self.database.all(db, "reminder")]

    def _get(self, db, key):
        value = self.database.get(db, "reminder", key)
        return self.Reminder.from_dict(value) if value else None

    def _save(self, db, reminder):
        self.database.put(db, "reminder", reminder.id, reminder.to_dict())

    def migrate(self, source):
        marker = f"reminders:{scope_hash(source.resolve())}"
        with self.database.connection() as db:
            if db.execute("SELECT 1 FROM migrations WHERE id=?", (marker,)).fetchone():
                return
        reminders, routines, digests = {}, {}, []
        for name in ("reminders.jsonl", "routines.json"):
            path = source / name
            if not path.exists():
                continue
            if path.resolve().parent != source.resolve():
                raise StorageError("Legacy reminder source points outside the backend directory.")
            raw = self.database.read_legacy(path)
            digests.append(self.database.backup(path, raw))
            try:
                records = (
                    [
                        json.loads(line)
                        for line in raw.decode("utf-8-sig").splitlines()
                        if line.strip()
                    ]
                    if name.endswith("jsonl")
                    else json.loads(raw.decode("utf-8-sig"))
                )
                if not isinstance(records, list):
                    raise ValueError("Invalid list")
                for value in records:
                    if name.endswith("jsonl"):
                        record = self.Reminder.from_dict(value)
                        self._validate(record)
                        if record.id in reminders and reminders[record.id] != record:
                            raise ValueError("Conflicting reminder IDs")
                        reminders[record.id] = record
                    else:
                        record = self.Routine.from_dict(value)
                        if (
                            not isinstance(record.name, str)
                            or not record.name
                            or not isinstance(record.actions, list)
                        ):
                            raise ValueError("Invalid routine")
                        if not all(isinstance(action, str) for action in record.actions):
                            raise ValueError("Invalid routine action")
                        if record.name in routines and routines[record.name] != record:
                            raise ValueError("Conflicting routine names")
                        routines[record.name] = record
            except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, OSError) as exc:
                raise StorageError(
                    "Legacy reminders/routines failed validation; originals and "
                    "encrypted backups preserved. Repair the source and retry."
                ) from exc
        if not digests:
            return
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM migrations WHERE id=?", (marker,)).fetchone():
                return
            for record in reminders.values():
                if self._get(db, record.id):
                    raise StorageError(
                        "Migration conflicts with an existing reminder; no records imported."
                    )
                self._save(db, record)
                # Legacy triggered reminders had no acknowledgement. Restore an open delivery.
                if record.status == "triggered":
                    self._enqueue(db, record)
                    if record.recurring:
                        record.trigger_at = next_occurrence(record, time.time())
                        record.status = "pending"
                        self._save(db, record)
            for record in routines.values():
                key = scope_hash(record.name)
                if self.database.get(db, "routine", key):
                    raise StorageError(
                        "Migration conflicts with an existing routine; no records imported."
                    )
                self.database.put(db, "routine", key, record.to_dict())
            db.execute("INSERT INTO migrations VALUES(?,?)", (marker, ":".join(digests)))

    def _validate(self, reminder):
        if (
            not isinstance(reminder.id, str)
            or not reminder.id
            or not isinstance(reminder.task, str)
            or not reminder.task.strip()
        ):
            raise ValueError("Invalid reminder")
        if not math.isfinite(reminder.trigger_at) or not math.isfinite(reminder.created_at):
            raise ValueError("Invalid timestamp")
        if reminder.recurring not in (None, "daily", "weekly", "weekdays"):
            raise ValueError("Invalid recurrence")
        if reminder.status not in ("pending", "snoozed", "triggered", "done", "cancelled"):
            raise ValueError("Invalid reminder status")
        ZoneInfo(reminder.timezone)
        if type(reminder.revision) is not int or reminder.revision < 0:
            raise ValueError("Invalid reminder revision")
        dt.datetime.fromtimestamp(reminder.trigger_at, dt.timezone.utc)
        dt.datetime.fromtimestamp(reminder.created_at, dt.timezone.utc)
        if reminder.wall_time is None:
            reminder.wall_time = (
                dt.datetime.fromtimestamp(reminder.trigger_at, ZoneInfo(reminder.timezone))
                .time()
                .isoformat()
            )
        if dt.time.fromisoformat(reminder.wall_time).tzinfo is not None:
            raise ValueError("Wall time must not include an offset")

    def add_reminder(
        self, task, trigger_at, recurring=None, routine_name=None, timezone="Asia/Kuala_Lumpur"
    ):
        reminder = self.Reminder(
            str(uuid.uuid4()),
            task,
            float(trigger_at),
            time.time(),
            recurring,
            "pending",
            routine_name,
            timezone,
        )
        self._validate(reminder)
        with self.database.transaction() as db:
            self._save(db, reminder)
        return reminder

    def get(self, reminder_id):
        with self.database.connection() as db:
            return self._get(db, reminder_id)

    def list_reminders(self, filter="all"):
        now = time.time()
        with self.database.connection() as db:
            records = self._all(db)

        def matches(reminder):
            if filter == "overdue":
                return reminder.status in ("pending", "snoozed") and reminder.trigger_at < now
            if filter == "today":
                zone = ZoneInfo(reminder.timezone)
                return (
                    reminder.status in ("pending", "snoozed")
                    and dt.datetime.fromtimestamp(reminder.trigger_at, zone).date()
                    == dt.datetime.fromtimestamp(now, zone).date()
                )
            return reminder.status not in ("done", "cancelled")

        return sorted([record for record in records if matches(record)], key=lambda r: r.trigger_at)

    def get_due_reminders(self):
        return self.list_reminders("overdue")

    def _retire(self, db, reminder_id):
        for delivery in self.database.all(db, "delivery"):
            if delivery["id"] == reminder_id and delivery["state"] not in ("completed", "retired"):
                delivery["state"] = "retired"
                self.database.put(db, "delivery", delivery["delivery_id"], delivery)

    def _edit(self, reminder_id, status, minutes=None):
        with self.database.transaction() as db:
            reminder = self._get(db, reminder_id)
            if not reminder or reminder.status in ("done", "cancelled"):
                return None
            self._retire(db, reminder_id)
            reminder.revision += 1
            reminder.status = status
            if minutes is not None:
                reminder.trigger_at = time.time() + minutes * 60
            self._save(db, reminder)
            return reminder

    def cancel(self, reminder_id):
        return bool(self._edit(reminder_id, "cancelled"))

    def mark_done(self, reminder_id):
        self._edit(reminder_id, "done")

    def snooze(self, reminder_id, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 10080:
            raise ValueError("Snooze must be 1 to 10080 whole minutes")
        return self._edit(reminder_id, "pending", minutes)

    def mark_triggered(self, reminder_id):
        # Compatibility entry point also creates a recoverable delivery.
        with self.database.transaction() as db:
            reminder = self._get(db, reminder_id)
            if reminder and reminder.status in ("pending", "snoozed"):
                self._enqueue(db, reminder)
                reminder.status = "triggered"
                self._save(db, reminder)

    def reschedule_recurring(self, reminder):
        with self.database.transaction() as db:
            current = self._get(db, reminder.id)
            if current and current.recurring and current.status == "triggered":
                current.trigger_at = next_occurrence(current, time.time())
                current.status = "pending"
                self._save(db, current)

    def _enqueue(self, db, reminder):
        key = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL, f"inara:{reminder.id}:{reminder.revision}:{reminder.trigger_at}"
            )
        )
        if not self.database.get(db, "delivery", key):
            self.database.put(
                db,
                "delivery",
                key,
                {
                    **reminder.to_dict(),
                    "delivery_id": key,
                    "state": "queued",
                    "recipient": None,
                    "lease_until": 0,
                    "attempts": 0,
                },
            )

    def claim_deliveries(self, recipient, now=None, lease_seconds=30):
        now = time.time() if now is None else now
        claimed = []
        with self.database.transaction() as db:
            for reminder in self._all(db):
                if reminder.status in ("pending", "snoozed") and reminder.trigger_at <= now:
                    self._enqueue(db, reminder)
                    # Missed occurrences coalesce into one alert, then advance to the next future date.
                    if reminder.recurring:
                        reminder.trigger_at = next_occurrence(reminder, now)
                        reminder.status = "pending"
                    else:
                        reminder.status = "triggered"
                    self._save(db, reminder)
            for delivery in self.database.all(db, "delivery"):
                if (
                    delivery["state"] in ("queued", "inflight")
                    and delivery["lease_until"] <= now
                    and delivery["recipient"] in (None, recipient)
                ):
                    delivery.update(
                        state="inflight",
                        recipient=recipient,
                        lease_until=now + lease_seconds,
                        attempts=delivery["attempts"] + 1,
                    )
                    self.database.put(db, "delivery", delivery["delivery_id"], delivery)
                    claimed.append(delivery)
        return claimed

    def acknowledge(self, delivery_id, recipient, complete=False):
        with self.database.transaction() as db:
            delivery = self.database.get(db, "delivery", delivery_id)
            if not delivery or delivery["recipient"] != recipient or delivery["state"] == "retired":
                return False
            if delivery["state"] == "completed":
                return True
            delivery["state"] = "completed" if complete else "acknowledged"
            self.database.put(db, "delivery", delivery_id, delivery)
            if complete:
                reminder = self._get(db, delivery["id"])
                if (
                    reminder
                    and not reminder.recurring
                    and reminder.revision == delivery["revision"]
                ):
                    reminder.status = "done"
                    self._save(db, reminder)
            return True

    def open_deliveries(self, recipient):
        with self.database.connection() as db:
            return [
                value
                for value in self.database.all(db, "delivery")
                if value["recipient"] == recipient
                and value["state"] in ("inflight", "acknowledged")
            ]

    def edit_delivery(self, delivery_id, recipient, minutes=None):
        # Reject an old alert action after its occurrence was retired or superseded.
        with self.database.transaction() as db:
            delivery = self.database.get(db, "delivery", delivery_id)
            if (
                not delivery
                or delivery["recipient"] != recipient
                or delivery["state"] not in ("inflight", "acknowledged")
            ):
                return False
            reminder = self._get(db, delivery["id"])
            if not reminder or reminder.revision != delivery["revision"]:
                return False
            if minutes is not None and (type(minutes) is not int or not 1 <= minutes <= 10080):
                return False
            self._retire(db, reminder.id)
            reminder.revision += 1
            reminder.status = "pending" if minutes else "cancelled"
            if minutes:
                reminder.trigger_at = time.time() + minutes * 60
            self._save(db, reminder)
            return True

    def list_routines(self):
        with self.database.connection() as db:
            return [self.Routine.from_dict(value) for value in self.database.all(db, "routine")]

    def add_routine(self, name, trigger, actions):
        routine = self.Routine(name, trigger, actions)
        with self.database.transaction() as db:
            self.database.put(db, "routine", scope_hash(name), routine.to_dict())
        return routine

    def get_routine(self, name):
        return next((record for record in self.list_routines() if record.name == name), None)

    def get_routine_by_trigger(self, trigger):
        return next(
            (
                record
                for record in self.list_routines()
                if record.trigger == trigger and record.enabled
            ),
            None,
        )

    def set_routine_enabled(self, name, enabled):
        with self.database.transaction() as db:
            value = self.database.get(db, "routine", scope_hash(name))
            if not value:
                return False
            value["enabled"] = bool(enabled)
            self.database.put(db, "routine", scope_hash(name), value)
            return True

    def delete_routine(self, name):
        with self.database.transaction() as db:
            return bool(
                db.execute(
                    "DELETE FROM documents WHERE kind='routine' AND id=?", (scope_hash(name),)
                ).rowcount
            )
