"""Validated reminder tools shared by typed chat and deterministic desktop actions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from services.tools import ServiceError, ToolSpec


class CreateReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: StrictStr = Field(min_length=1, max_length=2000)
    when: StrictStr = Field(min_length=1, max_length=128)
    recurring: Literal["daily", "weekly", "weekdays"] | None = None
    timezone: StrictStr = Field(default="Asia/Kuala_Lumpur", min_length=1, max_length=100)


class ListReminders(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: Literal["all", "today", "overdue"] = "all"


class ReminderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reminder_id: StrictStr = Field(min_length=1, max_length=36)
    delivery_id: StrictStr | None = Field(default=None, max_length=36)


class SnoozeReminder(ReminderAction):
    minutes: StrictInt = Field(ge=1, le=10080)


def register_scheduler_tools(dispatcher, agent, store):
    for name, arguments, description in (
        (
            "create_reminder",
            CreateReminder,
            "Create a local reminder using ISO-8601 or 'in N minutes'. "
            "The timezone is an IANA name; recurrence follows its local calendar.",
        ),
        ("list_reminders", ListReminders, "List local reminders and their IDs."),
        ("cancel_reminder", ReminderAction, "Cancel a reminder by ID."),
        ("snooze_reminder", SnoozeReminder, "Snooze a reminder by ID for whole minutes."),
    ):

        async def execute(args, context, tool_name=name):
            if getattr(args, "delivery_id", None):
                if tool_name not in ("cancel_reminder", "snooze_reminder"):
                    raise ServiceError("invalid_arguments", "Unexpected reminder delivery.")
                ok = store.edit_delivery(
                    args.delivery_id, context["principal"], getattr(args, "minutes", None)
                )
                if not ok:
                    raise ServiceError(
                        "stale_reminder", "This reminder alert is no longer actionable."
                    )
                return {"success": True, "message": "Reminder updated."}
            result = await agent.handle_tool_call(tool_name, args.model_dump(exclude_none=True))
            return {"success": result.success, "message": result.message, "data": result.data}

        dispatcher.register(ToolSpec(name, description, arguments, execute))
