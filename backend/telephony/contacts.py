"""The owner's people for call screening (P1): VIP, known and blocked callers.

A person is ``{id, name, numbers, group, note, created_at, updated_at}``: a name of 1-60
printable characters, one to five E.164 numbers (``numbers.normalize``; a number belongs to
at most one person), a group (``vip``, ``known`` or ``blocked``) and an optional note of at
most 300 printable characters ("Who they are to you"), checked like ``calls.facts``. At most
500 people, each one a DPAPI-protected document in the profile database (services.storage).

``Contacts.match(number)`` finds the person for a caller ID; withheld or unknown numbers
return None. The call agent places a matched person's name and note in that call's
instruction only (telephony/briefs.py), as owner-approved text.

Owner-only routes (``ContactsTransport``): ``contacts_list``, ``contacts_save``,
``contacts_delete``, and for the Calls view's call detail ``contacts_call_draft`` and
``contacts_call_mark``. Every change sends ``contacts_changed`` (an empty payload) to the
owner's renderers. Names, notes and numbers are never logged.
"""

import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

from services.log import get_logger
from services.settings import EmptyRequest
from services.storage import StorageError
from services.tools import ServiceError
from telephony.briefs import clean_line, clean_text
from telephony.numbers import normalize, withheld

logger = get_logger("telephony.contacts")

KIND = "call_people_v1"
EVENT_CHANGED = "contacts_changed"
GROUPS = ("vip", "known", "blocked")
PEOPLE_LIMIT = 500
NUMBERS_LIMIT = 5
NAME_LIMIT = 60
NOTE_LIMIT = 300
# The note goes into a call instruction: printable text and line breaks only (as calls.facts).
_NOTE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SEPARATORS = re.compile(r"[\s\-().]")
NUMBER_ERROR = "Enter a phone number, like 012-345 6789 or +60 12-345 6789."


def owner_number(value):
    """A number the owner typed -> E.164, or None. Malaysian local trunk format (one leading
    "0", not "00") becomes +60 without the 0: "012-345 6789" -> "+60123456789". "+..." and
    everything else go through ``numbers.normalize`` unchanged. Caller IDs are never read
    this way: Twilio sends E.164."""
    if not isinstance(value, str):
        return None
    digits = _SEPARATORS.sub("", value.strip())
    if digits.startswith("0") and not digits.startswith("00"):
        digits = "+60" + digits[1:]
    number = normalize(digits)
    return None if number is None or withheld(number) else number


def display_number(number):
    """``+60 12-345 6789`` for a Malaysian E.164 number; other numbers as E.164."""
    digits = number[1:]
    if digits.startswith("60") and len(digits) >= 9:
        national = digits[2:]
        prefix = national[:2] if national[:1] in ("1", "8") else national[:1]
        rest = national[len(prefix):]
        return f"+60 {prefix}-{rest[:-4]} {rest[-4:]}"
    return number


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def view(person):
    """A stored person as the owner's renderer sees it (full numbers: the owner's own list)."""
    return {
        "id": person["id"],
        "name": person["name"],
        "numbers": list(person["numbers"]),
        "group": person["group"],
        "note": person.get("note", ""),
        "created_at": _iso(person["created_at"]),
        "updated_at": _iso(person["updated_at"]),
    }


def clean_person(name, numbers, group, note):
    """Validated person fields, or ServiceError with a field-specific code. Messages are
    plain sentences and never repeat what was submitted."""
    if not isinstance(name, str):
        raise ServiceError("invalid_name", "Enter a name.")
    name = clean_line(name, NAME_LIMIT + 1)
    if not name:
        raise ServiceError("invalid_name", "Enter a name.")
    if len(name) > NAME_LIMIT:
        raise ServiceError("invalid_name", f"Use at most {NAME_LIMIT} characters for the name.")
    if not isinstance(numbers, list) or not numbers:
        raise ServiceError("invalid_number", "Add at least one phone number.")
    if len(numbers) > NUMBERS_LIMIT:
        raise ServiceError("too_many_numbers", f"A person can have at most {NUMBERS_LIMIT} numbers.")
    cleaned = []
    for value in numbers:
        number = owner_number(value)
        if number is None:
            raise ServiceError("invalid_number", NUMBER_ERROR)
        if number in cleaned:
            raise ServiceError("duplicate_number", "This number is already listed.")
        cleaned.append(number)
    if group not in GROUPS:
        raise ServiceError("invalid_group", "Choose VIP, Known or Blocked.")
    if not isinstance(note, str):
        raise ServiceError("invalid_note", "The note must be text.")
    if _NOTE_CONTROL.search(note):
        raise ServiceError("invalid_note", "The note can only contain printable text.")
    note = clean_text(note, NOTE_LIMIT + 1)
    if len(note) > NOTE_LIMIT:
        raise ServiceError("invalid_note", f"Use at most {NOTE_LIMIT} characters for the note.")
    return name, cleaned, group, note


class Contacts:
    """The people store. Writes run in one database transaction each; reads are cached
    in memory until the next write."""

    def __init__(self, app, *, wall=time.time):
        self.app, self.wall = app, wall
        self._cache = None

    @property
    def database(self):
        return self.app.database

    def _all(self, db):
        return [item for item in self.database.all(db, KIND) if isinstance(item, dict)]

    def people(self):
        """Every stored person (stored form), sorted by name."""
        if self._cache is None:
            with self.database.transaction() as db:
                self._cache = self._all(db)
        return sorted(self._cache, key=lambda item: (item["name"].casefold(), item["id"]))

    def by_id(self, person_id):
        return next((item for item in self.people() if item["id"] == person_id), None)

    def match(self, number):
        """The person whose numbers include this caller ID, or None (withheld, unknown or
        not saved)."""
        if not isinstance(number, str) or withheld(number):
            return None
        target = normalize(number)
        if target is None:
            return None
        return next((item for item in self.people() if target in item["numbers"]), None)

    def save(self, person_id, name, numbers, group, note):
        """Create (``person_id`` None) or update one person; returns the stored person."""
        name, numbers, group, note = clean_person(name, numbers, group, note)
        now = self.wall()
        try:
            with self.database.transaction() as db:
                people = self._all(db)
                current = None
                if person_id is not None:
                    current = next((item for item in people if item["id"] == person_id), None)
                    if current is None:
                        raise ServiceError("not_found", "That person is no longer saved.")
                elif len(people) >= PEOPLE_LIMIT:
                    raise ServiceError("people_limit", f"You can save at most {PEOPLE_LIMIT} people.")
                taken = {number for item in people if item["id"] != person_id for number in item["numbers"]}
                if any(number in taken for number in numbers):
                    raise ServiceError("duplicate_number", "This number is already saved for someone else.")
                value = {
                    "id": person_id or str(uuid.uuid4()),
                    "name": name,
                    "numbers": numbers,
                    "group": group,
                    "note": note,
                    "created_at": current["created_at"] if current else now,
                    "updated_at": now,
                }
                self.database.put(db, KIND, value["id"], value)
        finally:
            self._cache = None
        return value

    def delete(self, person_id):
        try:
            with self.database.transaction() as db:
                if self.database.get(db, KIND, person_id) is None:
                    raise ServiceError("not_found", "That person is no longer saved.")
                db.execute("DELETE FROM documents WHERE kind=? AND id=?", (KIND, person_id))
        finally:
            self._cache = None

    # --- from a call record (the Calls view's call detail) -------------------------------

    def call_number(self, record):
        """The caller's number on a stored call record: the caller ID, else the callback
        number the caller gave; None when there is neither."""
        if not isinstance(record, dict) or record.get("direction") == "outbound":
            return None
        for value in (record.get("caller_number"), _message(record).get("callback_number")):
            number = normalize(value) if isinstance(value, str) else None
            if number is not None and not withheld(number):
                return number
        return None

    def _record(self, record_id):
        record = self.app.call_agent.records.get(record_id)
        if record is None or record.get("source") != "twilio":
            raise ServiceError("not_found", "That call record no longer exists.")
        number = self.call_number(record)
        if number is None:
            raise ServiceError("no_number", "There is no number for this caller.")
        return record, number

    def call_draft(self, record_id):
        """"Add to people": the saved person for this caller, or an unsaved draft with the
        number and any name the caller gave. Nothing is stored."""
        record, number = self._record(record_id)
        person = self.match(number)
        if person is not None:
            return {"existing": True, "person": view(person)}
        name = clean_line(str(_message(record).get("name") or ""), NAME_LIMIT)
        return {"existing": False, "person": {
            "id": None, "name": name, "numbers": [number], "group": "known", "note": "",
            "created_at": None, "updated_at": None,
        }}

    def call_mark(self, record_id, group):
        """"Mark VIP" / "Block": set the caller's group, adding them when they are not saved
        yet (named after the name they gave, else after the number)."""
        record, number = self._record(record_id)
        person = self.match(number)
        if person is not None:
            return self.save(person["id"], person["name"], person["numbers"], group, person.get("note", ""))
        given = clean_line(str(_message(record).get("name") or ""), NAME_LIMIT)
        name = display_number(number) if group == "blocked" or not given else given
        return self.save(None, name, [number], group, "")

    # --- events -------------------------------------------------------------------------

    async def changed(self):
        """``contacts_changed`` (no payload fields) to the owner's renderers."""
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        owner = native.state.identity.owner if native else sessions.local_owner
        if owner is None or not sessions.authenticated(owner):
            return
        try:
            for sid in sessions.rooms(owner, "renderer"):
                await self.app.sio.emit(EVENT_CHANGED, {}, room=sid)
        except Exception:
            logger.warning("People change could not be delivered", exc_info=True)


def _message(record):
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    message = fields.get("message")
    return message if isinstance(message, dict) else {}


# --- owner-only routes -----------------------------------------------------------------------


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _uuid(value):
    return str(uuid.UUID(value))


class PersonSave(StrictRequest):
    id: StrictStr | None = Field(default=None, max_length=64)
    name: StrictStr = Field(max_length=200)
    numbers: list[StrictStr] = Field(max_length=NUMBERS_LIMIT * 2)
    group: Literal[GROUPS]
    note: StrictStr = Field(default="", max_length=NOTE_LIMIT * 2)

    @field_validator("id")
    @classmethod
    def person_id(cls, value):
        return None if value is None else _uuid(value)

    @field_validator("numbers")
    @classmethod
    def bounded(cls, value):
        if any(len(item) > 40 for item in value):
            raise ValueError("number too long")
        return value


class PersonReference(StrictRequest):
    id: StrictStr = Field(max_length=64)

    @field_validator("id")
    @classmethod
    def person_id(cls, value):
        return _uuid(value)


class CallMark(PersonReference):
    group: Literal[GROUPS]


class ContactsTransport:
    events = (
        "contacts_list",
        "contacts_save",
        "contacts_delete",
        "contacts_call_draft",
        "contacts_call_mark",
    )

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                return await method({} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                # Never echo pydantic details: they can include names, notes or numbers.
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid people request."}
            except (StorageError, sqlite3.Error):
                return {
                    "ok": False,
                    "code": "storage_error",
                    "message": "Protected storage could not be opened.",
                }

        return handle

    @property
    def contacts(self):
        return self.app.contacts

    async def _contacts_list(self, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "people": [view(item) for item in self.contacts.people()],
                "limit": PEOPLE_LIMIT}

    async def _contacts_save(self, data):
        request = PersonSave.model_validate(data)
        person = self.contacts.save(request.id, request.name, request.numbers, request.group, request.note)
        await self.contacts.changed()
        return {"ok": True, "person": view(person)}

    async def _contacts_delete(self, data):
        self.contacts.delete(PersonReference.model_validate(data).id)
        await self.contacts.changed()
        return {"ok": True}

    async def _contacts_call_draft(self, data):
        request = PersonReference.model_validate(data)
        return {"ok": True, **self.contacts.call_draft(request.id)}

    async def _contacts_call_mark(self, data):
        request = CallMark.model_validate(data)
        person = self.contacts.call_mark(request.id, request.group)
        await self.contacts.changed()
        return {"ok": True, "person": view(person)}
