"""One-use outbound call grants and third-party call limits.

Calls to the owner's number need no grant. Every other number needs a grant
issued by this process (C3 issues one after the owner approves a call brief):
bound to the exact E.164 number and the SHA-256 of the purpose text, expiring
after at most ten minutes, and consumed by the first ``place_call`` that uses
it. Third-party calls are also held to quiet hours, a daily cap and a
per-number cooldown, recorded in the profile database so a restart does not
reset them.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import secrets
import time
from zoneinfo import ZoneInfo

from services.tools import ServiceError
from telephony.numbers import normalize, number_key

GRANT_TTL_MAX = 600.0
TIMEZONE = "Asia/Kuala_Lumpur"
LEDGER_KIND = "telephony"
LEDGER_ID = "outbound_ledger"
LEDGER_KEEP_SECONDS = 8 * 24 * 3600


def purpose_hash(purpose):
    return hashlib.sha256(purpose.encode("utf-8")).hexdigest()


@dataclass(eq=False)
class CallGrant:
    id: str
    number: str
    purpose_hash: str
    expires_at: float
    consumed: bool = False


class CallGrants:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.grants = {}

    def issue(self, number, purpose, ttl=GRANT_TTL_MAX):
        """A grant for one call to ``number`` about ``purpose``; ttl is capped at 10 min."""
        target = normalize(number)
        if target is None:
            raise ServiceError("invalid_number", "Use a full international number (E.164).")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ServiceError("invalid_arguments", "A call grant needs the approved call purpose.")
        self._prune()
        ttl = min(float(ttl), GRANT_TTL_MAX)
        if ttl <= 0:
            raise ServiceError("invalid_arguments", "A call grant must expire in the future.")
        grant = CallGrant(secrets.token_urlsafe(16), target, purpose_hash(purpose), self.clock() + ttl)
        self.grants[grant.id] = grant
        return grant

    def check(self, grant, number, purpose):
        """The registered grant for this call; raises unless it is valid and unused."""
        if grant is None:
            raise ServiceError(
                "call_grant_required", "Calls to anyone but the owner need the owner's approval."
            )
        grant_id = grant.id if isinstance(grant, CallGrant) else grant
        registered = self.grants.get(grant_id) if isinstance(grant_id, str) else None
        # A CallGrant built outside this registry is never accepted.
        if registered is None or (isinstance(grant, CallGrant) and grant is not registered):
            raise ServiceError("call_grant_invalid", "This call approval is not valid.")
        if registered.consumed:
            raise ServiceError("call_grant_used", "This call approval was already used.")
        if registered.expires_at <= self.clock():
            raise ServiceError("call_grant_expired", "This call approval has expired.")
        if registered.number != number or registered.purpose_hash != purpose_hash(purpose):
            raise ServiceError(
                "call_grant_mismatch", "This approval was for a different number or purpose."
            )
        return registered

    def consume(self, grant):
        grant.consumed = True

    def revoke(self, grant_id):
        self.grants.pop(grant_id, None)

    def _prune(self):
        now = self.clock()
        for key in [key for key, grant in self.grants.items() if grant.expires_at <= now - 60]:
            del self.grants[key]


def _minutes(text):
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def in_quiet_hours(moment, quiet_hours):
    start, end = _minutes(quiet_hours["start"]), _minutes(quiet_hours["end"])
    if start == end:
        return False  # start == end disables quiet hours
    current = moment.hour * 60 + moment.minute
    if start < end:
        return start <= current < end
    return current >= start or current < end


class OutboundLimits:
    def __init__(self, database, clock=time.time, timezone=TIMEZONE):
        self.database, self.clock = database, clock
        self.zone = ZoneInfo(timezone)

    def local_now(self):
        return datetime.fromtimestamp(self.clock(), self.zone)

    def _ledger(self, db):
        ledger = self.database.get(db, LEDGER_KIND, LEDGER_ID)
        if not isinstance(ledger, dict):
            ledger = {}
        today = self.local_now().date().isoformat()
        if ledger.get("day") != today:
            ledger["day"], ledger["count"] = today, 0
        numbers = ledger.get("numbers")
        ledger["numbers"] = numbers if isinstance(numbers, dict) else {}
        return ledger

    def today_count(self):
        with self.database.connection() as db:
            return int(self._ledger(db).get("count", 0))

    def check(self, number, settings):
        """Raise when a third-party call to ``number`` is not allowed right now."""
        if in_quiet_hours(self.local_now().time().replace(tzinfo=None), settings["quiet_hours"]):
            raise ServiceError(
                "call_quiet_hours",
                f"Calls to other people are paused between {settings['quiet_hours']['start']} "
                f"and {settings['quiet_hours']['end']}.",
            )
        with self.database.connection() as db:
            ledger = self._ledger(db)
        if ledger["count"] >= settings["daily_outbound_cap"]:
            raise ServiceError("call_daily_cap", "Today's limit for calls to other people is reached.")
        last = ledger["numbers"].get(number_key(number))
        cooldown = settings["number_cooldown_minutes"] * 60
        if isinstance(last, (int, float)) and self.clock() - last < cooldown:
            raise ServiceError("call_number_cooldown", "INARA called this number recently. Try later.")

    def record(self, number):
        now = self.clock()
        with self.database.transaction() as db:
            ledger = self._ledger(db)
            ledger["count"] = int(ledger["count"]) + 1
            ledger["numbers"] = {
                key: stamp
                for key, stamp in ledger["numbers"].items()
                if isinstance(stamp, (int, float)) and now - stamp < LEDGER_KEEP_SECONDS
            }
            ledger["numbers"][number_key(number)] = now
            self.database.put(db, LEDGER_KIND, LEDGER_ID, ledger)

