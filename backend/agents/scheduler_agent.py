"""
Scheduler Agent — creates and manages reminders and routines.

Follows the BaseAgent pattern (same as KasaSmartHomeAgent / PhoneAgent).
Handles 6 LLM-callable tools:
  create_reminder, list_reminders, cancel_reminder, snooze_reminder,
  create_routine, list_routines

Time parsing:
  The LLM is expected to pass 'when' as an ISO-8601 datetime string
  (e.g. "2026-04-12T09:00:00") or a relative string (e.g. "in 20 minutes",
  "tomorrow at 3pm"). We try datetime.fromisoformat() first, then fall back
  to the optional 'dateparser' library for natural-language strings.
"""

import datetime
import time
from typing import Any, Optional

from agents.base import AgentResult, BaseAgent
from core.event_bus import EventBus, Event, Events
from core.reminder_store import Reminder, ReminderStore, Routine
from llm.tools import Tool, ToolParameter, ToolParameterType


# ---------------------------------------------------------------------------
# Time parsing helpers
# ---------------------------------------------------------------------------

def _parse_when(when_str: str) -> Optional[float]:
    """
    Parse a 'when' string into a Unix timestamp.

    Accepts:
      - ISO-8601 strings: "2026-04-12T09:00:00"
      - Relative strings: "in 20 minutes", "tomorrow at 3pm", "next Monday"

    Returns None if parsing fails.
    """
    if not when_str:
        return None

    # Attempt ISO parse first
    try:
        dt = datetime.datetime.fromisoformat(when_str)
        # If no timezone info, treat as local time
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.timestamp()
    except ValueError:
        pass

    # Fall back to dateparser for natural-language strings
    try:
        import dateparser
        dt = dateparser.parse(
            when_str,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if dt:
            return dt.timestamp()
    except ImportError:
        pass

    # Last resort: simple relative parsing ("in N minutes/hours/days")
    return _parse_relative(when_str)


def _parse_relative(s: str) -> Optional[float]:
    """Handle 'in N unit' patterns without external dependencies."""
    import re
    now = time.time()
    s = s.lower().strip()
    m = re.match(r"in\s+(\d+)\s+(second|minute|hour|day|week)s?", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
        return now + n * multipliers[unit]
    return None


def _format_reminder(r: Reminder) -> str:
    dt = datetime.datetime.fromtimestamp(r.trigger_at)
    dt_str = dt.strftime("%a %b %d at %I:%M %p")
    parts = [f"[{r.id[:8]}] '{r.task}' — {dt_str}"]
    if r.recurring:
        parts.append(f"({r.recurring})")
    if r.status != "pending":
        parts.append(f"[{r.status}]")
    return " ".join(parts)


def _format_routine(rt: Routine) -> str:
    enabled = "ON" if rt.enabled else "OFF"
    actions = "; ".join(rt.actions[:3])
    if len(rt.actions) > 3:
        actions += f" +{len(rt.actions) - 3} more"
    return f"'{rt.name}' trigger={rt.trigger} [{enabled}]: {actions}"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SchedulerAgent(BaseAgent):
    """INARA agent for reminders and routines."""

    def __init__(self, event_bus: EventBus, reminder_store: ReminderStore):
        self._bus = event_bus
        self._store = reminder_store

    @property
    def name(self) -> str:
        return "scheduler"

    @property
    def description(self) -> str:
        return "Creates and manages reminders and daily routines"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="create_reminder",
                description=(
                    "Creates a reminder that fires at a specific time. "
                    "Pass 'when' as an ISO-8601 datetime string (e.g. '2026-04-12T09:00:00') "
                    "or a natural-language expression (e.g. 'in 20 minutes', 'tomorrow at 3pm'). "
                    "For recurring reminders pass 'recurring' as 'daily', 'weekly', or 'weekdays'."
                ),
                parameters=[
                    ToolParameter("task", ToolParameterType.STRING, "What to remind the user about."),
                    ToolParameter("when", ToolParameterType.STRING, "When to fire the reminder (ISO datetime or natural language)."),
                    ToolParameter("recurring", ToolParameterType.STRING, "Recurrence: 'daily', 'weekly', or 'weekdays'. Omit for one-time.", required=False),
                ],
            ),
            Tool(
                name="list_reminders",
                description="Lists reminders. Use filter='today' for today's reminders, 'overdue' for past-due, or 'all' for everything pending.",
                parameters=[
                    ToolParameter("filter", ToolParameterType.STRING, "Filter: 'today', 'overdue', or 'all' (default).", required=False),
                ],
            ),
            Tool(
                name="cancel_reminder",
                description="Cancels a reminder so it will not fire.",
                parameters=[
                    ToolParameter("reminder_id", ToolParameterType.STRING, "The reminder ID (or first 8 characters of it)."),
                ],
            ),
            Tool(
                name="snooze_reminder",
                description="Snoozes a reminder, rescheduling it to fire again after the given number of minutes.",
                parameters=[
                    ToolParameter("reminder_id", ToolParameterType.STRING, "The reminder ID (or first 8 characters of it)."),
                    ToolParameter("minutes", ToolParameterType.INTEGER, "How many minutes to snooze for."),
                ],
            ),
            Tool(
                name="create_routine",
                description=(
                    "Creates a named routine that runs automatically when a greeting is detected. "
                    "Trigger format: 'greeting:good_morning', 'greeting:im_home', "
                    "'greeting:goodnight', or 'greeting:leaving'."
                ),
                parameters=[
                    ToolParameter("name", ToolParameterType.STRING, "A short name for the routine (e.g. 'Morning Routine')."),
                    ToolParameter("trigger", ToolParameterType.STRING, "When this routine fires (e.g. 'greeting:good_morning')."),
                    ToolParameter("actions", ToolParameterType.STRING, "Comma-separated list of actions for INARA to perform."),
                ],
            ),
            Tool(
                name="list_routines",
                description="Lists all defined routines and whether they are enabled.",
                parameters=[],
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "create_reminder":
            return self._create_reminder(args)
        if tool_name == "list_reminders":
            return self._list_reminders(args)
        if tool_name == "cancel_reminder":
            return self._cancel_reminder(args)
        if tool_name == "snooze_reminder":
            return self._snooze_reminder(args)
        if tool_name == "create_routine":
            return self._create_routine(args)
        if tool_name == "list_routines":
            return self._list_routines()
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    # -----------------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------------

    def _create_reminder(self, args: dict) -> AgentResult:
        task = args.get("task", "").strip()
        when_str = args.get("when", "").strip()
        recurring = args.get("recurring") or None

        if not task:
            return AgentResult(success=False, message="No task provided.")
        if not when_str:
            return AgentResult(success=False, message="No 'when' provided.")

        trigger_at = _parse_when(when_str)
        if trigger_at is None:
            return AgentResult(success=False, message=f"Could not parse time '{when_str}'. Use ISO format or plain English like 'in 30 minutes'.")

        if trigger_at <= time.time():
            return AgentResult(success=False, message=f"The time '{when_str}' is in the past. Please provide a future time.")

        valid_recurring = {None, "daily", "weekly", "weekdays"}
        if recurring not in valid_recurring:
            return AgentResult(success=False, message=f"Invalid recurring value '{recurring}'. Use 'daily', 'weekly', or 'weekdays'.")

        reminder = self._store.add_reminder(task=task, trigger_at=trigger_at, recurring=recurring)

        self._bus.emit_nowait(Event(
            type=Events.REMINDER_CREATED,
            data=reminder.to_dict(),
            source=self.name,
        ))

        dt_str = datetime.datetime.fromtimestamp(trigger_at).strftime("%A %B %d at %I:%M %p")
        msg = f"Reminder set: '{task}' on {dt_str}"
        if recurring:
            msg += f" (repeats {recurring})"
        msg += f". ID: {reminder.id[:8]}"
        return AgentResult(success=True, data=reminder.to_dict(), message=msg)

    def _list_reminders(self, args: dict) -> AgentResult:
        filter_val = args.get("filter", "all")
        reminders = self._store.list_reminders(filter=filter_val)

        if not reminders:
            return AgentResult(success=True, data={"reminders": []}, message=f"No reminders found (filter: {filter_val}).")

        lines = [_format_reminder(r) for r in sorted(reminders, key=lambda r: r.trigger_at)]
        msg = f"{len(reminders)} reminder(s):\n" + "\n".join(lines)
        return AgentResult(success=True, data={"reminders": [r.to_dict() for r in reminders]}, message=msg)

    def _cancel_reminder(self, args: dict) -> AgentResult:
        reminder_id = args.get("reminder_id", "").strip()
        if not reminder_id:
            return AgentResult(success=False, message="No reminder_id provided.")

        # Support short IDs (first 8 chars)
        matched = self._resolve_id(reminder_id)
        if not matched:
            return AgentResult(success=False, message=f"Reminder '{reminder_id}' not found.")

        ok = self._store.cancel(matched)
        if not ok:
            return AgentResult(success=False, message=f"Could not cancel reminder '{reminder_id}'.")

        self._bus.emit_nowait(Event(
            type=Events.REMINDER_CANCELLED,
            data={"id": matched},
            source=self.name,
        ))
        return AgentResult(success=True, message=f"Reminder {reminder_id} cancelled.")

    def _snooze_reminder(self, args: dict) -> AgentResult:
        reminder_id = args.get("reminder_id", "").strip()
        minutes = int(args.get("minutes", 15))

        matched = self._resolve_id(reminder_id)
        if not matched:
            return AgentResult(success=False, message=f"Reminder '{reminder_id}' not found.")

        updated = self._store.snooze(matched, minutes)
        if not updated:
            return AgentResult(success=False, message=f"Could not snooze reminder '{reminder_id}'.")

        dt_str = datetime.datetime.fromtimestamp(updated.trigger_at).strftime("%I:%M %p")
        return AgentResult(success=True, data=updated.to_dict(), message=f"Snoozed for {minutes} minutes. Will fire at {dt_str}.")

    def _create_routine(self, args: dict) -> AgentResult:
        name = args.get("name", "").strip()
        trigger = args.get("trigger", "").strip()
        actions_raw = args.get("actions", "")

        if not name:
            return AgentResult(success=False, message="No routine name provided.")
        if not trigger:
            return AgentResult(success=False, message="No trigger provided.")

        valid_triggers = {
            "greeting:good_morning", "greeting:im_home",
            "greeting:goodnight", "greeting:leaving", "manual",
        }
        if trigger not in valid_triggers:
            return AgentResult(
                success=False,
                message=f"Unknown trigger '{trigger}'. Valid options: {', '.join(sorted(valid_triggers))}",
            )

        # Parse actions — accept list or comma-separated string
        if isinstance(actions_raw, list):
            actions = [a.strip() for a in actions_raw if a.strip()]
        else:
            actions = [a.strip() for a in str(actions_raw).split(",") if a.strip()]

        if not actions:
            return AgentResult(success=False, message="No actions provided.")

        routine = self._store.add_routine(name=name, trigger=trigger, actions=actions)
        msg = f"Routine '{name}' created. Trigger: {trigger}. {len(actions)} action(s)."
        return AgentResult(success=True, data=routine.to_dict(), message=msg)

    def _list_routines(self) -> AgentResult:
        routines = self._store.list_routines()

        if not routines:
            return AgentResult(success=True, data={"routines": []}, message="No routines defined yet.")

        lines = [_format_routine(rt) for rt in routines]
        msg = f"{len(routines)} routine(s):\n" + "\n".join(lines)
        return AgentResult(success=True, data={"routines": [rt.to_dict() for rt in routines]}, message=msg)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _resolve_id(self, partial_id: str) -> Optional[str]:
        """Resolve a full or partial (8-char prefix) reminder ID."""
        reminders = self._store.list_reminders(filter="all")
        for r in reminders:
            if r.id == partial_id or r.id.startswith(partial_id):
                return r.id
        return None
