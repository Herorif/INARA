"""
Persistent storage for reminders and routines.

Legacy JSON/JSONL records are imported non-destructively into encrypted SQLite storage.
"""

from dataclasses import dataclass, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Reminder:
    id: str
    task: str
    trigger_at: float  # Unix timestamp
    created_at: float
    recurring: Optional[str]  # "daily" | "weekly" | "weekdays" | None
    status: str  # "pending" | "triggered" | "snoozed" | "done" | "cancelled"
    routine_name: Optional[str] = None
    timezone: str = "Asia/Kuala_Lumpur"
    revision: int = 0
    wall_time: Optional[str] = None

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
            timezone=d.get("timezone", "Asia/Kuala_Lumpur"),
            revision=d.get("revision", 0),
            wall_time=d.get("wall_time"),
        )


@dataclass
class Routine:
    name: str
    trigger: str  # e.g. "greeting:good_morning" | "manual"
    actions: list  # list of natural-language action strings
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
    """Compatibility constructor for the versioned transactional store."""

    def __new__(cls, backend_dir=None, database=None):
        from core.durable_reminders import DurableReminderStore

        return DurableReminderStore(backend_dir, database)
