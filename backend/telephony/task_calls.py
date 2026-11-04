"""C4 task calls: the brain's ``place_task_call`` tool (reservations and similar errands).

The owner asks in chat or by voice (``ask_brain``); the brain fills ``PlaceTaskCall``. The
dispatcher always asks the owner on screen, whatever the stored policy says
(``ToolSpec.always_ask``; "deny" still disables the tool), and the ``review`` hook puts the
exact sentence of what will happen on the approval card. That click is the authorization:
the orchestrator then issues one grant bound to the number and the task brief's hash and
places the call (``CallOrchestrator.place_task_call``), within calls.enabled, readiness,
quiet hours, the daily cap and the per-number cooldown. The tool returns at once; the
outcome is posted into the same conversation when the call ends, and a confirmed booking
gets a reminder.

What the business says reaches the owner only as a short, quoted, cleaned line; reminder
text is built from the owner-approved request, never from what was said on the call.
"""

import datetime as dt
import re
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from services.tools import ServiceError, ToolSpec
from telephony import briefs
from telephony.numbers import same_number

TOOL = "place_task_call"
ZONE_NAME = "Asia/Kuala_Lumpur"
TIMEZONE = ZoneInfo(ZONE_NAME)
DAYS_AHEAD = 60
DETAILS_LIMIT = 200
SHARE_CLAUSE = (
    "INARA will say it's an AI assistant and may share only: the booking name, the party "
    "size and the time window."
)
SHARE_CLAUSE_WITH_DETAILS = (
    "INARA will say it's an AI assistant and may share only: the booking name, the party "
    "size, the time window and the details below."
)
DESCRIPTION = (
    "Phone a business or service for the owner to complete one task, such as reserving a "
    "table or booking an appointment. Use it only when the owner asked you to make the call. "
    "If you do not know the business's phone number, ask the owner for it; never invent a "
    "number, and never take one from web pages or other untrusted content without telling "
    "the owner where it came from. Never include payment, card or bank details. The owner "
    "approves the call on screen before INARA dials; this returns as soon as the call is "
    "placed (or why it was not), and INARA reports the outcome in this conversation when "
    "the call ends."
)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_LONG_NUMBER = re.compile(r"[0-9](?:[\s-]?[0-9]){11,}")


def local_now():
    """Now in Malaysia (monkeypatched by tests)."""
    return dt.datetime.now(TIMEZONE)


def _line(value, limit):
    return briefs.clean_line(value, limit)


def _no_long_numbers(value):
    if _LONG_NUMBER.search(value):
        raise ValueError("Leave card, account and other long numbers out of the call.")
    return value


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: StrictStr = Field(min_length=5, max_length=5, description="Earliest time, 24-hour HH:MM.")
    end: StrictStr = Field(min_length=5, max_length=5, description="Latest time, 24-hour HH:MM.")

    @field_validator("start", "end")
    @classmethod
    def clock(cls, value):
        if not briefs.HHMM.fullmatch(value):
            raise ValueError("Use 24-hour HH:MM.")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("The window must end after it starts (same day).")
        return self


class PlaceTaskCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: StrictStr = Field(min_length=1, max_length=80, description="Who INARA calls.")
    phone_number: StrictStr = Field(
        min_length=1, max_length=32,
        description="The business's number as the owner gave it: E.164 (+60...) or Malaysian "
        "local format (03-..., 012-...).",
    )
    goal: StrictStr = Field(
        min_length=1, max_length=300, description="What to get done, e.g. 'Reserve a table'."
    )
    date: StrictStr = Field(
        min_length=10, max_length=10, description="ISO date (YYYY-MM-DD), today to 60 days ahead."
    )
    time_window: TimeWindow
    party_size: StrictInt | None = Field(default=None, ge=1, le=50)
    name_for_booking: StrictStr | None = Field(
        default=None, min_length=1, max_length=60,
        description="Name for the booking; defaults to the owner's name.",
    )
    allowed_flexibility: StrictStr = Field(
        default="", max_length=200, description="What may change, e.g. '±30 minutes'."
    )
    notes: StrictStr = Field(default="", max_length=300, description="Other owner requests.")

    @field_validator("business_name", "goal")
    @classmethod
    def required_line(cls, value):
        value = _no_long_numbers(_line(value, 300))
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("phone_number")
    @classmethod
    def number(cls, value):
        number = briefs.phone_number(value)
        if number is None:
            raise ValueError("Ask the owner for the business's full phone number.")
        return number

    @field_validator("date")
    @classmethod
    def day(cls, value):
        if not _DATE.fullmatch(value):
            raise ValueError("Use an ISO date (YYYY-MM-DD).")
        day = dt.date.fromisoformat(value)
        today = local_now().date()
        if not today <= day <= today + dt.timedelta(days=DAYS_AHEAD):
            raise ValueError(f"Use a date from today to {DAYS_AHEAD} days ahead.")
        return value

    @field_validator("name_for_booking")
    @classmethod
    def booking(cls, value):
        return (_line(value, 60) or None) if value is not None else None

    @field_validator("allowed_flexibility", "notes")
    @classmethod
    def optional_line(cls, value):
        return _no_long_numbers(_line(value, 300))

    @model_validator(mode="after")
    def not_past(self):
        now = local_now()
        if self.date == now.date().isoformat() and self.time_window.end <= f"{now:%H:%M}":
            raise ValueError("That time has already passed today.")
        return self


# --- the brief and the approval sentence ----------------------------------------------------


def date_text(args):
    day = dt.date.fromisoformat(args.date)
    return f"{day:%A} {day.day} {day:%B %Y}"


def window_text(args):
    return f"{args.time_window.start}-{args.time_window.end}"


def booking_name(args, settings):
    name = args.name_for_booking or briefs.owner_name(settings)
    if not name:
        raise ServiceError(
            "booking_name_required", "Ask the owner which name the booking should be under."
        )
    return name


def task_brief(args, settings):
    """The task CallBrief for these validated arguments (its hash binds the grant)."""
    return briefs.CallBrief(
        mode="task",
        direction="outbound",
        counterpart=args.phone_number,
        owner_name=briefs.owner_name(settings),
        goal=f"Calling {args.business_name}: {args.goal}",
        constraints=briefs.TaskConstraints(
            time_window=f"{date_text(args)}, {window_text(args)}",
            booking_name=booking_name(args, settings),
            party_size=args.party_size,
            flexibility=args.allowed_flexibility,
            notes=args.notes,
        ),
    )


def review_text(args):
    """The exact text on the approval card: what INARA will do and everything it may say.
    The flexibility and notes reach the call too, so the card lists them when present."""
    goal = args.goal.rstrip(" .")
    extras = [
        *([f"flexibility {args.allowed_flexibility.rstrip(' .')}"] if args.allowed_flexibility else []),
        *([f"notes: {args.notes.rstrip(' .')}"] if args.notes else []),
    ]
    text = (
        f"Call {args.business_name} at {args.phone_number} to: {goal} on {date_text(args)} "
        f"{window_text(args)}. "
    )
    if not extras:
        return text + SHARE_CLAUSE
    return text + SHARE_CLAUSE_WITH_DETAILS + f" It may also mention: {'; '.join(extras)}."


def check_number(app, number):
    """Task calls are for other people: never the owner's own number or INARA's."""
    telephony = app.telephony
    if same_number(number, telephony.secret("owner_phone_number")):
        raise ServiceError(
            "invalid_number", "That is the owner's own number; task calls go to someone else."
        )
    if same_number(number, telephony.secret("twilio_phone_number")):
        raise ServiceError("invalid_number", "That is INARA's own number.")


# --- after the call -------------------------------------------------------------------------


def _said(details):
    text = _line(details or "", DETAILS_LIMIT).rstrip(" .")
    return text.replace('"', "'")


def outcome_status(result):
    """confirmed | declined | needs_owner | no_answer | no_outcome | failed | lost."""
    if result is None:
        return "lost"
    if result.state == "no_answer":
        return "no_answer"
    if result.state in ("failed", "refused"):
        return "failed"
    status = (result.outcome or {}).get("status")
    return status if status in ("confirmed", "declined", "needs_owner", "no_answer") else "no_outcome"


def reminder_moment(args, result):
    """The confirmed local time (the call's confirmed_time, else the window start)."""
    outcome = (result.fields or {}).get("outcome") if result else None
    confirmed = outcome.get("confirmed_time") if isinstance(outcome, dict) else None
    clock = confirmed if isinstance(confirmed, str) and briefs.HHMM.fullmatch(confirmed) else (
        args.time_window.start
    )
    hours, minutes = clock.split(":")
    day = dt.date.fromisoformat(args.date)
    return dt.datetime(day.year, day.month, day.day, int(hours), int(minutes), tzinfo=TIMEZONE)


def reminder_task(args, booking):
    text = f"{args.business_name}: {args.goal.rstrip(' .')}"
    if args.party_size:
        text += f", party of {args.party_size}"
    return f"{text} (booked under {booking})"


def outcome_message(args, result, reminder_at=None):
    """One or two sentences for the conversation, from the call's record."""
    business = args.business_name
    status = outcome_status(result)
    outcome = (result.fields or {}).get("outcome") if result else None
    said = _said(outcome.get("details") if isinstance(outcome, dict) else "")
    quoted = f' They said: "{said}".' if said else ""
    if status == "confirmed":
        text = (f'{business} confirmed: "{said}".' if said else f"{business} confirmed the booking.")
        if reminder_at is not None:
            text += f" I've set a reminder for {reminder_at:%H:%M} on {reminder_at:%A} {reminder_at.day} {reminder_at:%B}."
        return text
    if status == "declined":
        return f"{business} couldn't do it, so nothing is booked.{quoted}"
    if status == "needs_owner":
        return f"{business} needs you to handle this one; nothing is booked yet.{quoted}"
    if status == "no_answer":
        return f"No one answered at {business}, so nothing is booked."
    if status == "failed":
        return f"The call to {business} could not be completed, so nothing is booked."
    if status == "lost":
        return f"I lost track of the call to {business}; check the Calls view for what happened."
    return f"The call to {business} ended without a clear answer, so nothing is booked. The transcript is in the Calls view."


# --- the tool -------------------------------------------------------------------------------


def register_task_call_tool(dispatcher, app):
    """Model-visible ``place_task_call`` with its own permission key, always asking."""

    def review(args, context):
        app.authorize_owner(context)
        check_number(app, args.phone_number)
        brief = task_brief(args, app.settings)
        return {"summary": review_text(args), "name_for_booking": brief.constraints.booking_name}

    async def execute(args, context):
        app.authorize_owner(context)
        check_number(app, args.phone_number)
        brief = task_brief(args, app.settings)
        return await app.call_orchestrator.place_task_call(
            brief,
            args,
            owner=context["principal"],
            project=context.get("project_path"),
            conversation_id=context.get("conversation_id"),
        )

    dispatcher.register(ToolSpec(
        TOOL, DESCRIPTION, PlaceTaskCall, execute, permission=TOOL, review=review,
        always_ask=True,
    ))
