"""TelephonyService: owns the gateway, tunnel, tokens, grants and call records.

Created by the composition root; nothing starts until ``reconcile()`` sees
``calls.enabled``. Secrets are read from the profile store on each use.
"""

import asyncio
import os
import re
import time

from core.event_bus import Event
from services.log import get_logger
from services.settings import CALLS_DEFAULTS
from services.tools import ServiceError
from telephony import twiml
from telephony.client import TwilioClient
from telephony.gateway import GatewayServer, MEDIA, public_url
from telephony.grants import CallGrants, OutboundLimits
from telephony.numbers import mask, mask_sid, normalize, same_number, withheld
from telephony.signature import valid_signature
from telephony.stub_agent import stub_agent
from telephony.tokens import OutboundTickets, Signer, StreamTokens, TokenError
from telephony.tunnel import TunnelSupervisor

logger = get_logger("telephony.service")

EVENT_OWNER_UNREACHABLE = "telephony.owner_unreachable"
EVENT_CALL_STATUS = "telephony.call_status"
EVENT_VOICEMAIL = "telephony.voicemail"
SECRET_NAMES = (
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_phone_number",
    "owner_phone_number",
    "cloudflare_tunnel_token",
)
REQUIRED_SECRETS = ("twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
                    "cloudflare_tunnel_token")
CALL_SID = re.compile(r"CA[0-9a-f]{32}")
TERMINAL = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})
PENDING_LIMIT = 64
PENDING_SECONDS = 300.0
OWNER_CALL_WINDOW = 120.0
PUBLIC_BASE = re.compile(r"https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
HHMM = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


def calls_settings(settings):
    """``settings['calls']`` merged over the defaults; malformed values fall back."""
    raw = settings.get("calls") if isinstance(settings, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    value = {**CALLS_DEFAULTS, "quiet_hours": dict(CALLS_DEFAULTS["quiet_hours"])}
    if type(raw.get("enabled")) is bool:
        value["enabled"] = raw["enabled"]
    base = raw.get("public_base_url")
    if isinstance(base, str) and (base == "" or PUBLIC_BASE.fullmatch(base)):
        value["public_base_url"] = base
    quiet = raw.get("quiet_hours")
    if (isinstance(quiet, dict) and isinstance(quiet.get("start"), str)
            and isinstance(quiet.get("end"), str) and HHMM.fullmatch(quiet["start"])
            and HHMM.fullmatch(quiet["end"])):
        value["quiet_hours"] = {"start": quiet["start"], "end": quiet["end"]}
    for key, upper in (("daily_outbound_cap", 100), ("number_cooldown_minutes", 10080)):
        if type(raw.get(key)) is int and 0 <= raw[key] <= upper:
            value[key] = raw[key]
    if raw.get("when_disabled") in ("voicemail", "hangup"):
        value["when_disabled"] = raw["when_disabled"]
    return value


class TelephonyService:
    def __init__(self, app, *, port=None, clock=time.time, transport=None, tunnel=None,
                 signer=None, environ=None):
        environ = os.environ if environ is None else environ
        self.app, self.clock = app, clock
        signer = signer or Signer(clock=clock)
        self.stream_tokens = StreamTokens(signer)
        self.tickets = OutboundTickets(signer)
        self.grants = CallGrants(clock)
        self.limits = OutboundLimits(app.database, clock)
        self.client = TwilioClient(self, transport=transport)
        self.gateway = GatewayServer(self, port)
        self.tunnel = tunnel or TunnelSupervisor(lambda: self.secret("cloudflare_tunnel_token"))
        # C2 installs the real call agent with set_agent(). The stub is developer-only.
        self.agent, self.agent_input_rate = None, 16000
        if environ.get("INARA_TELEPHONY_STUB_AGENT") == "1":
            self.agent = stub_agent
        self.inbound = {}
        self.outbound = {}
        self.outbound_by_sid = {}
        self.sessions = {}
        self.failure = None
        self.lock = asyncio.Lock()

    # --- configuration ------------------------------------------------------------
    def set_agent(self, agent, input_rate=16000):
        """``agent(session)`` is awaited once per connected call (C2)."""
        self.agent, self.agent_input_rate = agent, input_rate

    def calls_settings(self):
        return calls_settings(self.app.settings)

    def public_base_url(self):
        return self.calls_settings()["public_base_url"] or None

    def secret(self, name):
        try:
            return self.app.secrets.get(name)
        except Exception as exc:  # protected storage unavailable: treat as not configured
            logger.warning("Telephony secret %s unavailable: %s", name, type(exc).__name__)
            return None

    def credentials(self):
        values = {
            "account_sid": self.secret("twilio_account_sid"),
            "auth_token": self.secret("twilio_auth_token"),
            "phone_number": normalize(self.secret("twilio_phone_number")),
        }
        if not all(values.values()):
            return None
        values["owner_number"] = normalize(self.secret("owner_phone_number"))
        return values

    # --- request authentication -----------------------------------------------------
    def verify_http(self, scope, headers, form):
        base, token = self.public_base_url(), self.secret("twilio_auth_token")
        if base is None or token is None:
            return "not_configured"
        signature = headers.get("x-twilio-signature")
        if not signature:
            return "missing_signature"
        if not valid_signature(token, [public_url(base, scope)], form, signature):
            return "bad_signature"
        account = self.secret("twilio_account_sid")
        values = [value for name, value in form if name == "AccountSid"]
        if account is None or values != [account]:
            return "wrong_account"
        return "ok"

    def verify_websocket(self, scope, headers):
        base, token = self.public_base_url(), self.secret("twilio_auth_token")
        if base is None or token is None:
            return "not_configured"
        signature = headers.get("x-twilio-signature")
        if not signature:
            return "missing_signature"
        # Twilio signs the stream URL it was given (wss://); the https:// spelling is
        # also accepted because Twilio does not document which scheme it signs.
        urls = [public_url(base, scope, "wss"), public_url(base, scope, "https")]
        return "ok" if valid_signature(token, urls, (), signature) else "bad_signature"

    # --- TwiML ----------------------------------------------------------------------
    def _unavailable(self, settings):
        return twiml.voicemail() if settings["when_disabled"] == "voicemail" else twiml.say_and_hangup()

    def _stream_url(self, base):
        return "wss://" + base[len("https://") :] + MEDIA

    def _emit(self, kind, data):
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            bus.emit_nowait(Event(type=kind, data=data, source="telephony"))

    def _owner_call_in_flight(self):
        now = self.clock()
        for record in self.outbound.values():
            if (record["owner"] and record["status"] not in TERMINAL
                    and now - record["created"] <= OWNER_CALL_WINDOW):
                return record
        return None

    def loop_guard(self, params, credentials):
        """Reason to reject an inbound call that is INARA's own call coming back, or None."""
        caller = params.get("From")
        if same_number(caller, credentials["phone_number"]):
            return "forwarded_back"
        if withheld(caller) and same_number(params.get("ForwardedFrom"), credentials["owner_number"]):
            caller_name = params.get("CallerName") or ""
            if same_number(caller_name, credentials["phone_number"]) or self._owner_call_in_flight():
                return "forwarded_withheld"
        return None

    def inbound_twiml(self, params):
        call_sid = params.get("CallSid", "")
        if params.get("RecordingSid"):
            self._emit(EVENT_VOICEMAIL, {
                "call_sid": call_sid,
                "recording_sid": params.get("RecordingSid"),
                "duration": params.get("RecordingDuration"),
            })
            return twiml.thanks()
        credentials = self.credentials()
        settings = self.calls_settings()
        if credentials is None:  # the loop guard cannot run without INARA's own number
            return self._unavailable(settings)
        reason = self.loop_guard(params, credentials)
        if reason is not None:
            owner_call = self._owner_call_in_flight()
            logger.warning("Loop guard rejected inbound call %s (%s)", mask_sid(call_sid), reason)
            self._emit(EVENT_OWNER_UNREACHABLE, {
                "reason": reason,
                "inbound_call_sid": call_sid,
                "outbound_call_sid": owner_call["call_sid"] if owner_call else None,
                "call_id": owner_call["call_id"] if owner_call else None,
            })
            return twiml.reject()
        if not settings["enabled"]:
            return self._unavailable(settings)
        base = self.public_base_url()
        if self.agent is None or base is None or not CALL_SID.fullmatch(call_sid):
            logger.info("Inbound call %s sent to the unavailable path", mask_sid(call_sid))
            return self._unavailable(settings)
        self._prune_inbound()
        self.inbound[call_sid] = {
            "direction": "inbound",
            "from": params.get("From"),
            "to": params.get("To"),
            "forwarded_from": params.get("ForwardedFrom"),
            "caller_name": params.get("CallerName"),
            "received": self.clock(),
        }
        logger.info("Inbound call %s from %s", mask_sid(call_sid), mask(params.get("From")))
        token = self.stream_tokens.issue(call_sid, "inbound")
        return twiml.connect_stream(self._stream_url(base), {"token": token, "direction": "inbound"})

    def outbound_twiml(self, ticket, params):
        try:
            call_id = self.tickets.redeem(ticket)
        except TokenError as exc:
            raise ServiceError(exc.code, "Unknown outbound call.") from None
        record = self.outbound.get(call_id)
        credentials = self.credentials()
        call_sid = params.get("CallSid", "")
        if record is None or credentials is None or not CALL_SID.fullmatch(call_sid):
            raise ServiceError("unknown_call", "Unknown outbound call.")
        if record["call_sid"] not in (None, call_sid):
            raise ServiceError("call_mismatch", "Unknown outbound call.")
        if not same_number(params.get("To"), record["number"]) or not same_number(
            params.get("From"), credentials["phone_number"]
        ):
            raise ServiceError("call_mismatch", "Unknown outbound call.")
        record["call_sid"] = call_sid
        self.outbound_by_sid[call_sid] = record
        settings, base = self.calls_settings(), self.public_base_url()
        if not settings["enabled"] or self.agent is None or base is None:
            return twiml.hangup()
        token = self.stream_tokens.issue(call_sid, "outbound")
        return twiml.connect_stream(self._stream_url(base), {"token": token, "direction": "outbound"})

    async def status_callback(self, params):
        call_sid, status = params.get("CallSid", ""), params.get("CallStatus", "")
        if not CALL_SID.fullmatch(call_sid) or not re.fullmatch(r"[a-z-]{1,20}", status):
            return
        record = self.outbound_by_sid.get(call_sid)
        if record is not None:
            record["status"] = status
        self._emit(EVENT_CALL_STATUS, {
            "call_sid": call_sid,
            "status": status,
            "direction": params.get("Direction"),
            "call_id": record["call_id"] if record else None,
        })
        if record is not None and status in TERMINAL:
            self.outbound_by_sid.pop(call_sid, None)
            self.outbound.pop(record["call_id"], None)

    # --- outbound records (TwilioClient) ---------------------------------------------
    def register_outbound(self, call_id, number, purpose, context, owner):
        self._prune_outbound()
        record = {
            "call_id": call_id, "call_sid": None, "number": number, "purpose": purpose,
            "context": context, "owner": owner, "status": "queued", "created": self.clock(),
        }
        self.outbound[call_id] = record
        return record

    def outbound_failed(self, call_id):
        self.outbound.pop(call_id, None)

    def outbound_placed(self, call_id, call_sid, status):
        record = self.outbound.get(call_id)
        if record is None:
            return
        if record["call_sid"] is None:
            record["call_sid"] = call_sid
        if isinstance(status, str) and record["status"] == "queued":
            record["status"] = status
        self.outbound_by_sid[call_sid] = record

    async def place_call(self, to, purpose, context=None, *, grant=None):
        return await self.client.place_call(to, purpose, context, grant=grant)

    def _prune_inbound(self):
        now = self.clock()
        for key in [k for k, v in self.inbound.items() if now - v["received"] > PENDING_SECONDS]:
            del self.inbound[key]
        while len(self.inbound) >= PENDING_LIMIT:
            del self.inbound[next(iter(self.inbound))]

    def _prune_outbound(self):
        now = self.clock()
        for key in [k for k, v in self.outbound.items() if now - v["created"] > 3600]:
            record = self.outbound.pop(key)
            self.outbound_by_sid.pop(record["call_sid"], None)

    # --- Media Streams ----------------------------------------------------------------
    def authorize_stream(self, fields):
        account = self.secret("twilio_account_sid")
        if account is None or fields["account_sid"] != account:
            raise ServiceError("wrong_account", "Unknown account.")
        direction = fields["direction"]
        if direction not in ("inbound", "outbound"):
            raise ServiceError("bad_direction", "Unknown stream.")
        self.stream_tokens.redeem(fields["token"], fields["call_sid"], direction)
        if not self.calls_settings()["enabled"]:
            raise ServiceError("calls_disabled", "Calls are turned off.")
        if direction == "inbound":
            info = self.inbound.pop(fields["call_sid"], None) or {"direction": "inbound"}
        else:
            record = self.outbound_by_sid.get(fields["call_sid"]) or {}
            info = {
                "direction": "outbound",
                "to": record.get("number"),
                "owner": record.get("owner", False),
                "purpose": record.get("purpose"),
                "context": record.get("context"),
                "call_id": record.get("call_id"),
            }
        info = {key: value for key, value in info.items() if key != "received"}
        return info, self.agent, self.agent_input_rate

    def session_opened(self, session):
        self.sessions[session.call_sid] = session

    def session_closed(self, session):
        if self.sessions.get(session.call_sid) is session:
            del self.sessions[session.call_sid]
        logger.info("Media Stream ended call=%s reason=%s", mask_sid(session.call_sid), session.end_reason)

    # --- lifecycle --------------------------------------------------------------------
    async def reconcile(self):
        """Start or stop the gateway and tunnel to match ``calls.enabled``. Never raises."""
        async with self.lock:
            enabled = self.calls_settings()["enabled"]
            try:
                if enabled:
                    self.failure = None
                    await self.gateway.start()
                    await self.tunnel.start()
                else:
                    await self._stop()
            except ServiceError as exc:
                self.failure = exc.code
                logger.error("Telephony gateway could not start: %s", exc.code)
                await self._stop()
            except Exception as exc:
                self.failure = "telephony_failed"
                logger.error("Telephony gateway failed: %s", type(exc).__name__, exc_info=True)
                await self._stop()
        return self.status()

    async def _stop(self):
        await self.tunnel.stop()
        for session in list(self.sessions.values()):
            try:
                await session.hangup()
            except Exception:
                logger.warning("Ending a call during shutdown failed", exc_info=True)
        await self.gateway.stop()

    async def close(self):
        async with self.lock:
            await self._stop()

    def status(self):
        settings = self.calls_settings()
        secrets = {}
        for name in SECRET_NAMES:
            try:
                item = self.app.secrets.status(name)
            except Exception:
                item = {"configured": False, "verified_at": None, "source": None}
            secrets[name] = {
                "configured": bool(item.get("configured")),
                "verified": bool(item.get("verified_at")),
                "source": item.get("source"),
            }
        try:
            outbound_today = self.limits.today_count()
        except Exception:
            outbound_today = None
        gateway, tunnel = self.gateway.status(), self.tunnel.status()
        base = settings["public_base_url"]
        ready = (
            settings["enabled"]
            and all(secrets[name]["configured"] for name in REQUIRED_SECRETS)
            and bool(base)
            and gateway["listening"]
            and tunnel["state"] == "running"
        )
        return {
            "enabled": settings["enabled"],
            "kill_switch": not settings["enabled"],
            "when_disabled": settings["when_disabled"],
            "public_base_url": base or None,
            "public_url_configured": bool(base),
            "secrets": secrets,
            "gateway": gateway,
            "tunnel": tunnel,
            "agent": "none" if self.agent is None else ("stub" if self.agent is stub_agent else "ready"),
            "active_calls": len(self.sessions),
            "outbound_today": outbound_today,
            "daily_outbound_cap": settings["daily_outbound_cap"],
            "failure": self.failure,
            "ready": bool(ready),
        }
