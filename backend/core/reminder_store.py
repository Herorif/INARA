"""
Persistent storage for reminders and routines.

Reminders: backend/reminders.jsonl  (one JSON object per line)
Routines:  backend/routines.json    (single JSON array)
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Reminder:
    id: str
    task: str
    trigger_at: float           # Unix timestamp
    created_at: float
    recurring: Optional[str]    # "daily" | "weekly" | "weekdays" | None
    status: str                 # "pending" | "triggered" | "snoozed" | "done" | "cancelled"
    routine_name: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Reminder":
        return Reminder(
            id=d["id"],
            task=d["task"],
            trigger_at=float(d["trigger_at"]),
            created_at=float(d["created_at"]),
            recurring=d.get("recurring"),
            status=d.get("status", "pending"),
            routine_name=d.get("routine_name"),
        )


@dataclass
class Routine:
    name: str
    trigger: str                # e.g. "greeting:good_morning" | "manual"
    actions: list               # list of natural-language action strings
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Routine":
        return Routine(
            name=d["name"],
            trigger=d["trigger"],
            actions=d.get("actions", []),
            enabled=d.get("enabled", True),
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ReminderStore:
    def __init__(self, backend_dir: Path | None = None):
        if backend_dir is None:
            backend_dir = Path(__file__).parent.parent
        self._reminders_path = backend_dir / "reminders.jsonl"
        self._routines_path  = backend_dir / "routines.json"
        self._reminders: dict[str, Reminder] = {}
        self._routines:  dict[str, Routine]  = {}
        self._load()

    # --- Persistence --------------------------------------------------------

    def _load(self):
        # Reminders from JSONL
        if self._reminders_path.exists():
            with open(self._reminders_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = Reminder.from_dict(json.loads(line))
                        self._reminders[r.id] = r
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Routines from JSON
        if self._routines_path.exists():
            try:
                with open(self._routines_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for d in data:
                    rt = Routine.from_dict(d)
                    self._routines[rt.name] = rt
            except (json.JSONDecodeError, IOError):
                pass

    def _save_reminders(self):
        with open(self._reminders_path, "w", encoding="utf-8") as f:
            for r in self._reminders.values():
                f.write(json.dumps(r.to_dict()) + "\n")

    def _save_routines(self):
        with open(self._routines_path, "w", encoding="utf-8") as f:
            json.dump([rt.to_dict() for rt in self._routines.values()], f, indent=2)

    # --- Reminder CRUD ------------------------------------------------------

    def add_reminder(
        self,
        task: str,
        trigger_at: float,
        recurring: Optional[str] = None,
        routine_name: Optional[str] = None,
    ) -> Reminder:
        r = Reminder(
            id=str(uuid.uuid4()),
            task=task,
            trigger_at=trigger_at,
            created_at=time.time(),
            recurring=recurring,
            status="pending",
            routine_name=routine_name,
        )
        self._reminders[r.id] = r
        self._save_reminders()
        print(f"[ReminderStore] Created: '{task}' at {trigger_at} (recurring={recurring})")
        return r

    def get(self, reminder_id: str) -> Optional[Reminder]:
        return self._reminders.get(reminder_id)

    def get_due_reminders(self) -> list[Reminder]:
        """Return all pending reminders whose trigger_at <= now."""
        now = time.time()
        return [
            r for r in self._reminders.values()
            if r.status == "pending" and r.trigger_at <= now
        ]

    def list_reminders(self, filter: str = "all") -> list[Reminder]:
        now = time.time()
        midnight_today = now - (now % 86400)
        midnight_tomorrow = midnight_today + 86400

        if filter == "today":
            return [
                r for r in self._reminders.values()
                if r.status == "pending"
                and midnight_today <= r.trigger_at < midnight_tomorrow
            ]
        if filter == "overdue":
            return [
                r for r in self._reminders.values()
                if r.status == "pending" and r.trigger_at < now
            ]
        # "all" — exclude done/cancelled
        return [
            r for r in self._reminders.values()
            if r.status not in ("done", "cancelled")
        ]

    def mark_triggered(self, reminder_id: str):
        r = self._reminders.get(reminder_id)
        if r:
            r.status = "triggered"
            self._save_reminders()

    def mark_done(self, reminder_id: str):
        r = self._reminders.get(reminder_id)
        if r:
            r.status = "done"
            self._save_reminders()

    def cancel(self, reminder_id: str) -> bool:
        r = self._reminders.get(reminder_id)
        if not r:
            return False
        r.status = "cancelled"
        self._save_reminders()
        return True

    def snooze(self, reminder_id: str, minutes: int) -> Optional[Reminder]:
        r = self._reminders.get(reminder_id)
        if not r:
            return None
        r.trigger_at = time.time() + minutes * 60
        r.status = "pending"
        self._save_reminders()
        print(f"[ReminderStore] Snoozed '{r.task}' for {minutes}m")
        return r

    def reschedule_recurring(self, reminder: Reminder):
        """After firing, push trigger_at forward by the recurrence interval."""
        import datetime
        if not reminder.recurring:
            return

        dt = datetime.datetime.fromtimestamp(reminder.trigger_at)

        if reminder.recurring == "daily":
            dt += datetime.timedelta(days=1)
        elif reminder.recurring == "weekly":
            dt += datetime.timedelta(weeks=1)
        elif reminder.recurring == "weekdays":
            dt += datetime.timedelta(days=1)
            # Skip Saturday (5) and Sunday (6)
            while dt.weekday() >= 5:
                dt += datetime.timedelta(days=1)

        reminder.trigger_at = dt.timestamp()
        reminder.status = "pending"
        self._save_reminders()
        print(f"[ReminderStore] Rescheduled '{reminder.task}' -> {dt.isoformat()}")

    # --- Routine CRUD -------------------------------------------------------

    def add_routine(self, name: str, trigger: str, actions: list[str]) -> Routine:
        rt = Routine(name=name, trigger=trigger, actions=actions, enabled=True)
        self._routines[name] = rt
        self._save_routines()
        print(f"[ReminderStore] Routine created: '{name}' trigger={trigger}")
        return rt

    def get_routine_by_trigger(self, trigger: str) -> Optional[Routine]:
        for rt in self._routines.values():
            if rt.trigger == trigger and rt.enabled:
                return rt
        return None

    def get_routine(self, name: str) -> Optional[Routine]:
        return self._routines.get(name)

    def list_routines(self) -> list[Routine]:
        return list(self._routines.values())

    def set_routine_enabled(self, name: str, enabled: bool) -> bool:
        rt = self._routines.get(name)
        if not rt:
            return False
        rt.enabled = enabled
        self._save_routines()
        return True

    def delete_routine(self, name: str) -> bool:
        if name not in self._routines:
            return False
        del self._routines[name]
        self._save_routines()
        return True
