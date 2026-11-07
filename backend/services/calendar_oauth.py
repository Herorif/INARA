"""Google sign-in for Google Calendar: PKCE, a one-shot loopback callback and Google HTTP.

The owner's own OAuth client (type "Desktop app", docs/CALENDAR.md) signs in through the
system browser. A listener on 127.0.0.1 with a random free port (never 8000) accepts
exactly one callback whose ``state`` matches, within five minutes, then stops.

Nothing here logs or returns a token, an authorization code, the client secret, an email
address or event text: failures carry only a code from ``MESSAGES``.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from services.log import get_logger

logger = get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPES = (CALENDAR_SCOPE, "openid", "email")
CALLBACK_TIMEOUT = 300.0
CALLBACK_PATH = "/"
# JARVIS's own core port; the loopback listener never uses it.
RESERVED_PORTS = frozenset({8000})
REQUEST_LIMIT = 8192
HTTP_TIMEOUT = 15.0
BODY_LIMIT = 2_000_000
CLOSE_PAGE = "You can close this tab and return to JARVIS."
MISMATCH_PAGE = "This sign-in link doesn't match. Return to JARVIS and press Connect again."

MESSAGES = {
    "setup_needed": "Add your Google OAuth Client ID and Client secret first.",
    "access_denied": "Google sign-in was cancelled, so your calendar wasn't connected.",
    "timeout": "Google sign-in timed out after 5 minutes. Press Connect to try again.",
    "invalid_client": (
        "Google didn't accept the Client ID and Client secret. Check them in the one-time "
        "setup."
    ),
    "api_disabled": (
        "The Google Calendar API isn't enabled in your Google Cloud project. Enable it, wait "
        "a minute, then connect again."
    ),
    "scope_missing": (
        "Google didn't grant access to your calendar. Connect again and allow calendar access."
    ),
    "expired": "Google Calendar access has expired or was removed. Connect again.",
    "rate_limited": "Google Calendar is limiting requests right now. Try again in a minute.",
    "network_error": "Couldn't reach Google. Check your connection.",
    "tls_error": (
        "Couldn't make a secure connection to Google. A proxy or antivirus may be "
        "intercepting HTTPS."
    ),
    "unexpected": "Google gave an unexpected answer. Try again later.",
}


class OAuthError(Exception):
    """A Google failure with a plain, fixed message (never Google's own text)."""

    def __init__(self, code):
        code = code if code in MESSAGES else "unexpected"
        super().__init__(MESSAGES[code])
        self.code = code

    def public(self):
        return {"code": self.code, "message": MESSAGES[self.code]}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair():
    """(verifier, S256 challenge): an 86-character verifier, inside RFC 7636's 43-128."""
    verifier = secrets.token_urlsafe(64)
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state():
    return secrets.token_urlsafe(32)


def authorization_url(client_id, redirect_uri, state, challenge):
    return AUTH_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def id_token_email(id_token, client_id):
    """The email claim of an id_token received directly from Google's token endpoint over
    TLS (OpenID Connect allows skipping the signature check there); audience must match."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (AttributeError, IndexError, ValueError):
        return None
    if not isinstance(claims, dict) or claims.get("aud") != client_id:
        return None
    email = claims.get("email")
    return email if valid_email(email) else None


def valid_email(value):
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 254
        and value.count("@") == 1
        and all(31 < ord(ch) < 127 and ch not in "<>\"' " for ch in value)
    )


def classify_exception(exc):
    from services.secrets import classify_exception as classify

    code = classify(exc)
    return code if code in ("network_error", "tls_error") else "unexpected"


def google_error(status, body, *, refreshing=False):
    """Map a Google OAuth or Calendar error response to a code in MESSAGES."""
    body = body if isinstance(body, dict) else {}
    error = body.get("error")
    if isinstance(error, str):  # OAuth endpoints: {"error": "invalid_client", ...}
        if error in ("invalid_client", "unauthorized_client"):
            return "invalid_client"
        if error == "invalid_grant":
            return "expired" if refreshing else "unexpected"
        if error == "access_denied":
            return "access_denied"
        return "unexpected"
    reasons = set()
    if isinstance(error, dict):  # Calendar API: {"error": {"errors": [...], "details": [...]}}
        for item in (error.get("errors") or []) + (error.get("details") or []):
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                reasons.add(item["reason"])
    if status == 401:
        return "expired"
    if status == 429 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return "rate_limited"
    if status == 403:
        if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
            return "api_disabled"
        if reasons & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
            return "scope_missing"
        return "api_disabled" if not reasons else "unexpected"
    return "unexpected"


class GoogleHttp:
    """One bounded HTTPS request per call through the provider TLS context (services/tls.py).

    ``transport`` is an httpx transport for tests (httpx.MockTransport); production uses the
    OS certificate store so antivirus HTTPS scanning still verifies."""

    def __init__(self, transport=None, timeout=HTTP_TIMEOUT):
        self.transport = transport
        self.timeout = timeout

    async def request(self, method, url, *, data=None, json_body=None, params=None, headers=None):
        """(status, parsed JSON body or None). Transport and TLS errors raise OAuthError."""
        import httpx

        options = {"timeout": self.timeout, "follow_redirects": False}
        if self.transport is not None:
            options["transport"] = self.transport
        else:
            from services.tls import provider_ssl_context

            options["verify"] = provider_ssl_context()
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(
                    method, url, data=data, json=json_body, params=params, headers=headers
                )
        except Exception as exc:  # the exception text can carry the URL: never logged
            code = classify_exception(exc)
            logger.warning("Google request failed (%s)", code)
            raise OAuthError(code) from None
        if len(response.content) > BODY_LIMIT:
            raise OAuthError("unexpected")
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        return response.status_code, body


class LoopbackCallback:
    """One-shot redirect listener on 127.0.0.1 for a single sign-in attempt."""

    def __init__(self, state, *, timeout=CALLBACK_TIMEOUT):
        self.state = state
        self.timeout = timeout
        self.server = None
        self.port = None
        self.result = None

    @property
    def redirect_uri(self):
        return f"http://127.0.0.1:{self.port}{CALLBACK_PATH}"

    async def start(self):
        self.result = asyncio.get_running_loop().create_future()
        for _attempt in range(5):
            server = await asyncio.start_server(
                self._handle, host="127.0.0.1", port=0, limit=REQUEST_LIMIT
            )
            port = server.sockets[0].getsockname()[1]
            if port not in RESERVED_PORTS:
                self.server, self.port = server, port
                return self
            server.close()
        raise OAuthError("unexpected")

    async def wait(self):
        """("code", value) or ("error", value); OAuthError("timeout") after the deadline.
        The listener always stops before this returns."""
        try:
            return await asyncio.wait_for(asyncio.shield(self.result), self.timeout)
        except TimeoutError:
            raise OAuthError("timeout") from None
        finally:
            await self.close()

    async def close(self):
        server, self.server = self.server, None
        if server is None:
            return
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2)
        except TimeoutError:
            pass  # A browser keep-alive socket; the listener itself is already closed.
        if self.result is not None and not self.result.done():
            self.result.cancel()

    @property
    def listening(self):
        return self.server is not None

    async def _handle(self, reader, writer):
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                return
            outcome = self._parse(head)
            if outcome is None:
                await self._respond(writer, 404, "Not found.")
            elif outcome == "mismatch":
                await self._respond(writer, 400, MISMATCH_PAGE)
            elif self.result is None or self.result.done():
                await self._respond(writer, 410, CLOSE_PAGE)
            else:
                await self._respond(writer, 200, CLOSE_PAGE)
                self.result.set_result(outcome)
        except Exception as exc:
            logger.warning("Google sign-in callback could not be read (%s)", type(exc).__name__)
        finally:
            writer.close()

    def _parse(self, head):
        try:
            line = head.split(b"\r\n", 1)[0].decode("ascii")
            method, target, _version = line.split(" ", 2)
        except (UnicodeDecodeError, ValueError):
            return None
        parts = urlsplit(target)
        if method != "GET" or parts.path != CALLBACK_PATH:
            return None
        query = parse_qs(parts.query, max_num_fields=20)
        state = (query.get("state") or [""])[0]
        if not hmac.compare_digest(state.encode(), self.state.encode()):
            return "mismatch"
        code, error = (query.get("code") or [""])[0], (query.get("error") or [""])[0]
        if code and len(code) <= 2048:
            return ("code", code)
        return ("error", error[:64] or "unexpected")

    async def _respond(self, writer, status, text):
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 410: "Gone"}[status]
        page = (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>JARVIS</title>'
            '<body style="font-family:system-ui,sans-serif;margin:3rem">'
            f"<p>{text}</p></body></html>"
        ).encode()
        writer.write(
            (
                f"HTTP/1.1 {status} {reason}\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(page)}\r\n"
                "Cache-Control: no-store\r\n"
                "Referrer-Policy: no-referrer\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            + page
        )
        try:
            await asyncio.wait_for(writer.drain(), 5)
        except (TimeoutError, ConnectionError):
            pass  # The browser closed the tab first.
