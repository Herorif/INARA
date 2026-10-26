"""Short-lived single-use tokens signed with a per-process secret.

* Stream tokens travel as a TwiML ``<Parameter name="token">`` and come back in
  the Media Stream ``start`` message. Each is bound to one CallSid and one
  direction, expires after two minutes and can be redeemed once, so a leaked
  stream URL or captured handshake cannot be replayed.
* Outbound tickets ride in the query of the TwiML URL INARA gives Twilio when it
  places a call. They bind the TwiML fetch to INARA's own call record.

The secret never leaves memory; a core restart invalidates every token.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

STREAM_TTL = 120.0
TICKET_TTL = 120.0
MAX_TOKEN_LENGTH = 1024


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TokenError(Exception):
    """Invalid, expired, mismatched or replayed token. ``code`` is safe to log."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Signer:
    def __init__(self, secret=None, clock=time.time):
        self.secret = secret if secret is not None else secrets.token_bytes(32)
        self.clock = clock
        self.used = {}  # nonce -> expiry, pruned as tokens expire

    def issue(self, purpose, claims, ttl):
        body = {
            "p": purpose,
            "n": secrets.token_urlsafe(12),
            "x": int(self.clock() + ttl),
            **claims,
        }
        payload = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
        mac = hmac.new(self.secret, f"{purpose}.{payload}".encode(), hashlib.sha256).digest()
        return f"{payload}.{_b64(mac)}"

    def redeem(self, purpose, token, expect):
        """Verify, check every ``expect`` claim and burn the token; returns its claims."""
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
            raise TokenError("token_missing")
        payload, _, signature = token.partition(".")
        try:
            provided = _unb64(signature)
        except (ValueError, TypeError):
            raise TokenError("token_invalid") from None
        expected = hmac.new(self.secret, f"{purpose}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, provided):
            raise TokenError("token_invalid")
        try:
            body = json.loads(_unb64(payload))
        except (ValueError, TypeError):
            raise TokenError("token_invalid") from None
        if not isinstance(body, dict) or body.get("p") != purpose:
            raise TokenError("token_invalid")
        now = self.clock()
        self._prune(now)
        expires = body.get("x")
        if not isinstance(expires, int) or expires < now:
            raise TokenError("token_expired")
        for key, value in expect.items():
            if body.get(key) != value:
                raise TokenError("token_mismatch")
        nonce = body.get("n")
        if not isinstance(nonce, str) or nonce in self.used:
            raise TokenError("token_replayed")
        self.used[nonce] = expires
        return body

    def _prune(self, now):
        for nonce in [nonce for nonce, expires in self.used.items() if expires < now]:
            del self.used[nonce]


class StreamTokens:
    purpose = "inara-media-stream-v1"

    def __init__(self, signer, ttl=STREAM_TTL):
        self.signer, self.ttl = signer, ttl

    def issue(self, call_sid, direction):
        return self.signer.issue(self.purpose, {"c": call_sid, "d": direction}, self.ttl)

    def redeem(self, token, call_sid, direction):
        self.signer.redeem(self.purpose, token, {"c": call_sid, "d": direction})


class OutboundTickets:
    purpose = "inara-outbound-twiml-v1"

    def __init__(self, signer, ttl=TICKET_TTL):
        self.signer, self.ttl = signer, ttl

    def issue(self, call_id):
        return self.signer.issue(self.purpose, {"i": call_id}, self.ttl)

    def redeem(self, token):
        return self.signer.redeem(self.purpose, token, {})["i"]
