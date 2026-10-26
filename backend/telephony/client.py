"""Twilio REST: placing and ending calls from INARA's own number.

``place_call`` enforces the outbound policy in code: the owner's number is
always allowed; any other number needs a valid one-use grant (see grants.py)
and passes quiet hours, the daily cap and the per-number cooldown. The caller
ID is always INARA's Twilio number; there is no way to choose another.
"""

import asyncio
import re
import uuid

from services.log import get_logger
from services.tools import ServiceError
from telephony.numbers import mask, mask_sid, normalize, same_number

logger = get_logger("telephony.client")

API_BASE = "https://api.twilio.com/2010-04-01"
RING_TIMEOUT = 15  # shorter than the owner's 20-30 s no-reply forwarding timer
REQUEST_TIMEOUT = 10.0
MAX_PURPOSE = 2000
CALL_SID = re.compile(r"CA[0-9a-f]{32}")
STATUS_EVENTS = ("initiated", "ringing", "answered", "completed")


class TwilioClient:
    def __init__(self, service, *, transport=None, timeout=REQUEST_TIMEOUT):
        self.service = service
        self.transport, self.timeout = transport, timeout
        self.lock = asyncio.Lock()

    def _client(self, credentials):
        import httpx

        options = {
            "auth": (credentials["account_sid"], credentials["auth_token"]),
            "timeout": self.timeout,
            "follow_redirects": False,
        }
        if self.transport is not None:
            options["transport"] = self.transport
        else:
            from services.tls import provider_ssl_context

            options["verify"] = provider_ssl_context()
        return httpx.AsyncClient(**options)

    async def _post(self, credentials, path, data):
        import httpx

        url = f"{API_BASE}/Accounts/{credentials['account_sid']}/{path}"
        try:
            async with self._client(credentials) as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            logger.warning("Twilio request failed: %s", type(exc).__name__)
            raise ServiceError("twilio_unreachable", "Couldn't reach Twilio.") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code in (401, 403):
            raise ServiceError("twilio_auth_failed", "Twilio rejected INARA's account details.")
        if response.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            logger.warning(
                "Twilio refused a request: HTTP %s, Twilio code %s", response.status_code, code
            )
            raise ServiceError(
                "twilio_rejected",
                "Twilio refused the call" + (f" (error {code})." if isinstance(code, int) else "."),
            )
        return body if isinstance(body, dict) else {}

    async def place_call(self, to, purpose, context=None, *, grant=None):
        """Ring ``to`` from INARA's number; returns ``{call_id, call_sid, status, owner}``."""
        service = self.service
        settings = service.calls_settings()
        if not settings["enabled"]:
            raise ServiceError("calls_disabled", "Calls are turned off.")
        target = normalize(to)
        if target is None:
            raise ServiceError("invalid_number", "Use a full international number (E.164).")
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > MAX_PURPOSE:
            raise ServiceError("invalid_arguments", "Describe the call's purpose briefly.")
        credentials = service.credentials()
        base = service.public_base_url()
        if credentials is None or base is None:
            raise ServiceError(
                "calls_not_configured", "Add the Twilio details and the public tunnel address first."
            )
        if same_number(target, credentials["phone_number"]):
            raise ServiceError("invalid_number", "INARA can't call its own number.")
        owner = same_number(target, credentials["owner_number"])
        async with self.lock:
            if not owner:
                approved = service.grants.check(grant, target, purpose)
                service.limits.check(target, settings)
                service.grants.consume(approved)
                service.limits.record(target)
            call_id = uuid.uuid4().hex
            ticket = service.tickets.issue(call_id)
            record = service.register_outbound(call_id, target, purpose, context, owner)
        data = {
            "To": target,
            "From": credentials["phone_number"],
            "Url": f"{base}/telephony/voice/outbound?ticket={ticket}",
            "Method": "POST",
            "Timeout": str(RING_TIMEOUT),
            "StatusCallback": f"{base}/telephony/status",
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": list(STATUS_EVENTS),
        }
        try:
            body = await self._post(credentials, "Calls.json", data)
        except ServiceError:
            service.outbound_failed(call_id)
            raise
        call_sid = body.get("sid")
        if not isinstance(call_sid, str) or not CALL_SID.fullmatch(call_sid):
            service.outbound_failed(call_id)
            raise ServiceError("twilio_rejected", "Twilio gave an unexpected answer.")
        service.outbound_placed(call_id, call_sid, body.get("status"))
        logger.info(
            "Placed %s call %s to %s",
            "owner" if owner else "approved", mask_sid(call_sid), mask(target),
        )
        return {
            "call_id": call_id,
            "call_sid": call_sid,
            "status": record.get("status"),
            "owner": owner,
        }

    async def hangup(self, call_sid):
        """End a call INARA is part of (``Status=completed``)."""
        if not isinstance(call_sid, str) or not CALL_SID.fullmatch(call_sid):
            raise ServiceError("invalid_arguments", "Unknown call.")
        credentials = self.service.credentials()
        if credentials is None:
            raise ServiceError("calls_not_configured", "Add the Twilio details first.")
        await self._post(credentials, f"Calls/{call_sid}.json", {"Status": "completed"})
