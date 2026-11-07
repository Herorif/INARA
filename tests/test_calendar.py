"""Google Calendar (P3, docs/CALENDAR.md): OAuth, the Calendar service, tools and routes.

Fake HTTP only (httpx.MockTransport) and a fake browser that follows the sign-in URL to the
loopback listener: no network, no real Google, no real browser.
"""

import asyncio
import base64
import datetime as dt
import hashlib
import json
import logging
import ssl
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from services import calendar as calendar_module
from services import calendar_tools
from services.calendar import TIMEZONE, merge_busy
from services.calendar_oauth import (
    AUTH_URL,
    CLOSE_PAGE,
    GoogleHttp,
    LoopbackCallback,
    authorization_url,
    google_error,
    id_token_email,
    pkce_pair,
)
from services.tools import ServiceError

CLIENT_ID = "1234567890-abcdefghijklmnop.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-abcdefghijklmnopqrstuvwxyz12"
REFRESH = "1//0refresh-token-value-for-tests_ABCDEFGHIJ"
ACCESS = "ya29.access-token-for-tests"
ACCESS_2 = "ya29.second-access-token"
CODE = "4/0auth-code-for-tests"
EMAIL = "you@gmail.com"
TITLE = "Dentist with Dr Tan"
NOW = dt.datetime(2026, 11, 8, 9, 30, tzinfo=TIMEZONE)  # a Sunday
SENSITIVE = (CLIENT_SECRET, REFRESH, ACCESS, ACCESS_2, CODE, EMAIL, TITLE)


def jwt(claims):
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{part}.sig"


class FakeGoogle:
    """Records requests; answers like Google's OAuth and Calendar endpoints."""

    def __init__(self):
        self.requests = []
        self.token = {
            "access_token": ACCESS,
            "expires_in": 3599,
            "refresh_token": REFRESH,
            "scope": "openid https://www.googleapis.com/auth/calendar.events "
            "https://www.googleapis.com/auth/userinfo.email",
            "id_token": jwt({"aud": CLIENT_ID, "email": EMAIL}),
        }
        self.refresh = {"access_token": ACCESS_2, "expires_in": 3599}
        self.items = []
        self.overrides = {}

    def __call__(self, request):
        self.requests.append(request)
        key = (request.method, request.url.host + request.url.path)
        if key in self.overrides:
            value = self.overrides[key]
            if isinstance(value, Exception):
                raise value
            if isinstance(value, list):
                value = value.pop(0) if len(value) > 1 else value[0]
            status, body = value
            return httpx.Response(status, json=body)
        if key == ("POST", "oauth2.googleapis.com/token"):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["refresh_token"]:
                return httpx.Response(200, json=self.refresh)
            return httpx.Response(200, json=self.token)
        if key == ("POST", "oauth2.googleapis.com/revoke"):
            return httpx.Response(200, json={})
        if key == ("GET", "www.googleapis.com/calendar/v3/calendars/primary/events"):
            return httpx.Response(200, json={"items": self.items})
        if key == ("POST", "www.googleapis.com/calendar/v3/calendars/primary/events"):
            return httpx.Response(200, json={"id": "evt1"})
        return httpx.Response(404, json={})

    def find(self, method, path):
        return [r for r in self.requests if r.method == method and r.url.path == path]


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def owner_app(application_factory, google, monkeypatch):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    app.calendar.http = GoogleHttp(transport=httpx.MockTransport(google))
    monkeypatch.setattr(calendar_module, "local_now", lambda: NOW)
    monkeypatch.setattr(calendar_tools, "local_now", lambda: NOW)
    return app


def set_client(app):
    app.secrets.set("google_oauth_client_id", CLIENT_ID)
    app.secrets.set("google_oauth_client_secret", CLIENT_SECRET)


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


async def browser_get(url):
    """A fake browser: GET the URL on the loopback listener; returns (status, body)."""
    parts = urlsplit(url)
    reader, writer = await asyncio.open_connection(parts.hostname, parts.port)
    target = parts.path + ("?" + parts.query if parts.query else "")
    writer.write(f"GET {target} HTTP/1.1\r\nHost: {parts.netloc}\r\n\r\n".encode())
    await writer.drain()
    data = await reader.read()
    writer.close()
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body.decode()


def redirect(auth_url, **params):
    query = parse_qs(urlsplit(auth_url).query)
    base = query["redirect_uri"][0]
    from urllib.parse import urlencode

    return base + "?" + urlencode(params)


async def connect(app, google, **callback):
    reply = await rpc(app, "calendar_connect", {})
    assert reply["ok"], reply
    url = reply["auth_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    status, body = await browser_get(redirect(url, state=state, **(callback or {"code": CODE})))
    flow = app.calendar.flow
    if flow is not None:
        await asyncio.wait_for(asyncio.shield(flow), 5)
    return url, status, body


def emitted(app, event):
    return [c.args[1] for c in app.sio.emit.await_args_list if c.args[0] == event]


# --- PKCE, state and the auth URL -------------------------------------------------------


def test_pkce_pair_is_s256_and_random():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.rstrip(b"=").decode()
    assert pkce_pair()[0] != verifier


def test_authorization_url_carries_scopes_pkce_state_and_offline_consent():
    url = authorization_url(CLIENT_ID, "http://127.0.0.1:5555/", "st", "ch")
    assert url.startswith(AUTH_URL + "?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query == {
        "client_id": CLIENT_ID,
        "redirect_uri": "http://127.0.0.1:5555/",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.events openid email",
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }


@pytest.mark.asyncio
async def test_connect_needs_the_client_first(owner_app):
    reply = await rpc(owner_app, "calendar_connect", {})
    assert reply["ok"] is False and reply["code"] == "setup_needed"
    status = (await rpc(owner_app, "calendar_status", {}))["calendar"]
    assert status["setup_needed"] is True and status["connected"] is False


# --- the one-shot loopback callback -------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_is_loopback_random_port_never_8000_and_one_shot():
    callback = await LoopbackCallback("state-1", timeout=5).start()
    assert callback.redirect_uri.startswith("http://127.0.0.1:") and callback.port != 8000
    assert callback.server.sockets[0].getsockname()[0] == "127.0.0.1"
    waiter = asyncio.create_task(callback.wait())
    status, body = await browser_get(callback.redirect_uri + "?state=state-1&code=abc")
    assert status == 200 and CLOSE_PAGE in body
    assert await waiter == ("code", "abc")
    assert not callback.listening
    with pytest.raises(OSError):
        await browser_get(callback.redirect_uri + "?state=state-1&code=again")


@pytest.mark.asyncio
async def test_wrong_state_and_other_paths_are_rejected_and_listening_continues():
    callback = await LoopbackCallback("right", timeout=5).start()
    waiter = asyncio.create_task(callback.wait())
    status, _ = await browser_get(callback.redirect_uri + "?state=wrong&code=evil")
    assert status == 400
    status, _ = await browser_get(f"http://127.0.0.1:{callback.port}/favicon.ico")
    assert status == 404
    assert not waiter.done() and callback.listening
    status, _ = await browser_get(callback.redirect_uri + "?state=right&code=good")
    assert status == 200 and await waiter == ("code", "good")


@pytest.mark.asyncio
async def test_timeout_stops_the_listener_and_reports_plainly(owner_app, google):
    set_client(owner_app)
    owner_app.calendar.callback_timeout = 0.2
    reply = await rpc(owner_app, "calendar_connect", {})
    port = urlsplit(parse_qs(urlsplit(reply["auth_url"]).query)["redirect_uri"][0]).port
    assert reply["calendar"]["connecting"] is True
    await asyncio.wait_for(owner_app.calendar.flow, 5)
    status = owner_app.calendar.status()
    assert status["connecting"] is False and status["connected"] is False
    assert status["last_error"]["code"] == "timeout"
    assert "timed out" in status["last_error"]["message"]
    with pytest.raises(OSError):
        await browser_get(f"http://127.0.0.1:{port}/?state=x&code=y")
    assert not google.requests


@pytest.mark.asyncio
async def test_cancel_stops_a_pending_sign_in(owner_app, google):
    set_client(owner_app)
    reply = await rpc(owner_app, "calendar_connect", {})
    flow = owner_app.calendar.flow
    cancelled = await rpc(owner_app, "calendar_cancel", {})
    assert cancelled["ok"] and cancelled["calendar"]["connecting"] is False
    assert flow.done() and owner_app.calendar.flow is None
    with pytest.raises(OSError):
        await browser_get(redirect(reply["auth_url"], state="x", code=CODE))
    assert not google.requests


# --- token exchange, storage and refresh -------------------------------------------------


@pytest.mark.asyncio
async def test_code_exchange_stores_refresh_token_encrypted_and_access_in_memory(owner_app, google):
    set_client(owner_app)
    url, status, body = await connect(owner_app, google)
    assert status == 200 and CLOSE_PAGE in body
    (token,) = google.find("POST", "/token")
    form = {k: v[0] for k, v in parse_qs(token.content.decode()).items()}
    redirect_uri = parse_qs(urlsplit(url).query)["redirect_uri"][0]
    assert form["grant_type"] == "authorization_code" and form["code"] == CODE
    assert form["client_id"] == CLIENT_ID and form["client_secret"] == CLIENT_SECRET
    assert form["redirect_uri"] == redirect_uri
    challenge = parse_qs(urlsplit(url).query)["code_challenge"][0]
    digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
    assert digest.rstrip(b"=").decode() == challenge
    assert str(token.url) == "https://oauth2.googleapis.com/token"
    calendar = owner_app.calendar
    assert calendar.refresh_token() == REFRESH and calendar.access[0] == ACCESS
    status = calendar.status()
    assert status["connected"] and status["email"] == EMAIL and status["calendar"] == "primary"
    assert status["last_error"] is None and not status["setup_needed"]
    raw = b"".join(p.read_bytes() for p in calendar.app.database.directory.iterdir() if p.is_file())
    for value in (REFRESH, ACCESS, EMAIL):
        assert value.encode() not in raw
    assert emitted(owner_app, "calendar_status")[-1]["connected"] is True


@pytest.mark.asyncio
async def test_email_falls_back_to_userinfo(owner_app, google):
    set_client(owner_app)
    google.token["id_token"] = jwt({"aud": "someone-else", "email": "x@y.z"})
    google.overrides[("GET", "openidconnect.googleapis.com/v1/userinfo")] = (200, {"email": EMAIL})
    await connect(owner_app, google)
    assert owner_app.calendar.status()["email"] == EMAIL
    assert id_token_email("not-a-jwt", CLIENT_ID) is None


@pytest.mark.asyncio
async def test_access_token_refreshes_when_expired_and_once_on_401(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    calendar = owner_app.calendar
    calendar.access = (ACCESS, 0)  # expired
    await calendar.events(NOW, NOW + dt.timedelta(hours=1))
    refresh = [r for r in google.find("POST", "/token") if b"refresh_token" in r.content][-1]
    form = {k: v[0] for k, v in parse_qs(refresh.content.decode()).items()}
    assert form == {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "refresh_token": REFRESH, "grant_type": "refresh_token"}
    assert google.requests[-1].headers["Authorization"] == f"Bearer {ACCESS_2}"
    calendar.access = (ACCESS, 10**12)  # Google rejects the cached one: refresh once
    key = ("GET", "www.googleapis.com/calendar/v3/calendars/primary/events")
    google.overrides[key] = [(401, {}), (200, {"items": []})]
    await calendar.events(NOW, NOW + dt.timedelta(hours=1))
    assert calendar.access[0] == ACCESS_2


@pytest.mark.asyncio
async def test_revoked_grant_disconnects_with_a_plain_message(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    owner_app.calendar.access = None
    google.overrides[("POST", "oauth2.googleapis.com/token")] = (400, {"error": "invalid_grant"})
    with pytest.raises(ServiceError) as error:
        await owner_app.calendar.events(NOW, NOW + dt.timedelta(hours=1))
    assert error.value.code == "calendar_expired"
    status = owner_app.calendar.status()
    assert status["connected"] is False and status["last_error"]["code"] == "expired"


# --- error mapping ------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case, code",
    [
        ("denied", "access_denied"),
        ("invalid_client", "invalid_client"),
        ("api_disabled", "api_disabled"),
        ("scope", "scope_missing"),
        ("network", "network_error"),
        ("tls", "tls_error"),
    ],
)
async def test_sign_in_errors_map_to_plain_messages(owner_app, google, case, code):
    set_client(owner_app)
    token_key = ("POST", "oauth2.googleapis.com/token")
    events_key = ("GET", "www.googleapis.com/calendar/v3/calendars/primary/events")
    callback = {"code": CODE}
    if case == "denied":
        callback = {"error": "access_denied"}
    elif case == "invalid_client":
        google.overrides[token_key] = (401, {"error": "invalid_client", "error_description": "x"})
    elif case == "api_disabled":
        google.overrides[events_key] = (403, {"error": {"code": 403, "errors": [
            {"reason": "accessNotConfigured", "message": "Calendar API has not been used"}]}})
    elif case == "scope":
        google.token["scope"] = "openid email"
    elif case == "network":
        google.overrides[token_key] = httpx.ConnectError("getaddrinfo failed")
    else:
        failure = httpx.ConnectError("handshake")
        failure.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
        google.overrides[token_key] = failure
    await connect(owner_app, google, **callback)
    status = owner_app.calendar.status()
    assert status["connected"] is False and status["connecting"] is False
    assert status["last_error"]["code"] == code
    assert owner_app.calendar.refresh_token() is None
    message = status["last_error"]["message"]
    assert message and "Calendar API has not been used" not in message and "\n" not in message
    if case in ("api_disabled", "scope"):
        assert google.find("POST", "/revoke")  # the useless grant is given back


def test_calendar_api_errors_map_by_reason():
    assert google_error(403, {"error": {"details": [{"reason": "SERVICE_DISABLED"}]}}) == "api_disabled"
    assert google_error(403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}) == "scope_missing"
    assert google_error(429, {}) == "rate_limited"
    assert google_error(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}) == "rate_limited"
    assert google_error(400, {"error": "invalid_grant"}, refreshing=True) == "expired"
    assert google_error(500, None) == "unexpected"


# --- disconnect ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_revokes_and_deletes(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    reply = await rpc(owner_app, "calendar_disconnect", {})
    assert reply["ok"] and reply["revoked"] is True
    (revoke,) = google.find("POST", "/revoke")
    assert parse_qs(revoke.content.decode()) == {"token": [REFRESH]}
    calendar = owner_app.calendar
    assert calendar.refresh_token() is None and calendar.access is None
    assert calendar.account() == {} and reply["calendar"]["connected"] is False
    assert reply["calendar"]["email"] is None and not reply["calendar"]["setup_needed"]


@pytest.mark.asyncio
async def test_disconnect_deletes_even_when_google_is_unreachable(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    google.overrides[("POST", "oauth2.googleapis.com/revoke")] = httpx.ConnectError("down")
    reply = await rpc(owner_app, "calendar_disconnect", {})
    assert reply["ok"] and reply["revoked"] is False
    assert owner_app.calendar.refresh_token() is None
    assert reply["calendar"]["last_error"]["code"] == "revoke_failed"


# --- events, busy times and add_event -----------------------------------------------------


@pytest.mark.asyncio
async def test_events_request_shape_and_sanitised_bounded_result(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    google.items = [
        {"status": "confirmed", "summary": "Dentist\u202e\x07 at ten",
         "start": {"dateTime": "2026-11-09T10:00:00+08:00"},
         "end": {"dateTime": "2026-11-09T10:30:00+08:00"}, "location": "Jalan  Ampang"},
        {"status": "cancelled", "summary": "Gone", "start": {"dateTime": "2026-11-09T11:00:00+08:00"},
         "end": {"dateTime": "2026-11-09T12:00:00+08:00"}},
        {"summary": "Holiday", "start": {"date": "2026-11-09"}, "end": {"date": "2026-11-10"}},
        {"summary": "x" * 500, "start": {"dateTime": "2026-11-09T07:00:00Z"},
         "end": {"dateTime": "2026-11-09T08:00:00Z"}},
    ]
    start = dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    result = await owner_app.calendar.events(start, start + dt.timedelta(days=1))
    request = google.requests[-1]
    params = dict(request.url.params)
    assert request.url.path == "/calendar/v3/calendars/primary/events"
    assert params["singleEvents"] == "true" and params["orderBy"] == "startTime"
    assert params["timeMin"] == "2026-11-09T00:00:00+08:00"
    assert params["timeMax"] == "2026-11-10T00:00:00+08:00"
    assert params["timeZone"] == "Asia/Kuala_Lumpur" and int(params["maxResults"]) <= 26
    assert "description" not in params["fields"] and "attendees" not in params["fields"]
    titles = [event["title"] for event in result["events"]]
    assert titles[0] == "Dentist at ten" and "Gone" not in titles
    assert result["events"][0] == {"title": "Dentist at ten", "day": "Monday 9 November",
                                   "date": "2026-11-09", "all_day": False, "start": "10:00",
                                   "end": "10:30", "location": "Jalan Ampang"}
    assert result["events"][1]["all_day"] is True and result["events"][1]["start"] is None
    assert result["events"][2]["start"] == "15:00" and len(result["events"][2]["title"]) <= 120


@pytest.mark.asyncio
async def test_busy_times_skip_free_and_cancelled_merge_overlaps_and_carry_no_titles(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    google.items = [
        {"summary": TITLE, "location": "Clinic", "start": {"dateTime": "2026-11-09T10:00:00+08:00"},
         "end": {"dateTime": "2026-11-09T11:00:00+08:00"}},
        {"summary": "Overlap", "start": {"dateTime": "2026-11-09T10:30:00+08:00"},
         "end": {"dateTime": "2026-11-09T12:00:00+08:00"}},
        {"summary": "Free", "transparency": "transparent",
         "start": {"dateTime": "2026-11-09T13:00:00+08:00"}, "end": {"dateTime": "2026-11-09T14:00:00+08:00"}},
        {"status": "cancelled", "start": {"dateTime": "2026-11-09T15:00:00+08:00"},
         "end": {"dateTime": "2026-11-09T16:00:00+08:00"}},
        {"summary": "Review", "start": {"dateTime": "2026-11-09T15:00:00+08:00"},
         "end": {"dateTime": "2026-11-09T16:00:00+08:00"}},
    ]
    start = dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    result = await owner_app.calendar.busy(start, start + dt.timedelta(days=1))
    params = dict(google.requests[-1].url.params)
    assert params["fields"] == "items(status,transparency,start,end)"
    assert "freeBusy" not in str(google.requests[-1].url)
    assert result["busy"] == [
        {"start": "2026-11-09T10:00:00+08:00", "end": "2026-11-09T12:00:00+08:00"},
        {"start": "2026-11-09T15:00:00+08:00", "end": "2026-11-09T16:00:00+08:00"},
    ]
    text = json.dumps(result)
    assert TITLE not in text and "Clinic" not in text and "Review" not in text
    assert set(result) == {"time_zone", "range", "busy"}


def test_merge_busy_clips_to_the_window():
    day = dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    hour = dt.timedelta(hours=1)
    assert merge_busy([(day - hour, day + hour), (day + 5 * hour, day + 30 * hour)], day,
                      day + 24 * hour) == [(day, day + hour), (day + 5 * hour, day + 24 * hour)]


@pytest.mark.asyncio
async def test_add_event_request_shape(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    start = dt.datetime(2026, 11, 9, 13, tzinfo=TIMEZONE)
    result = await owner_app.calendar.add_event("Lunch with Aisyah", start, start + dt.timedelta(hours=1),
                                                location="Bangsar", description="Booked by phone")
    request = google.requests[-1]
    assert request.method == "POST" and request.url.path == "/calendar/v3/calendars/primary/events"
    assert json.loads(request.content) == {
        "summary": "Lunch with Aisyah",
        "start": {"dateTime": "2026-11-09T13:00:00+08:00", "timeZone": "Asia/Kuala_Lumpur"},
        "end": {"dateTime": "2026-11-09T14:00:00+08:00", "timeZone": "Asia/Kuala_Lumpur"},
        "location": "Bangsar",
        "description": "Booked by phone",
    }
    assert result == {"added": True, "title": "Lunch with Aisyah",
                      "when": "Monday 9 November 13:00 to 14:00", "time_zone": "Asia/Kuala_Lumpur"}


@pytest.mark.asyncio
async def test_today_events_and_free_busy_entry_points(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    await owner_app.calendar.today_events()
    params = dict(google.requests[-1].url.params)
    assert params["timeMin"] == "2026-11-08T00:00:00+08:00"
    assert params["timeMax"] == "2026-11-09T00:00:00+08:00"
    result = await owner_app.calendar.free_busy()
    params = dict(google.requests[-1].url.params)
    assert params["timeMin"] == "2026-11-08T09:30:00+08:00" and "summary" not in params["fields"]
    assert result["busy"] == []


# --- settings gates -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switches_gate_each_use_and_act_only_while_connected(owner_app, google):
    calendar = owner_app.calendar
    start = dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    for call in (calendar.events, calendar.busy):
        with pytest.raises(ServiceError) as error:
            await call(start, start + dt.timedelta(hours=1))
        assert error.value.code == "not_connected"
    set_client(owner_app)
    await connect(owner_app, google)
    for switch, call in (("read_events", calendar.events), ("share_free_busy", calendar.busy),
                         ("add_events", None)):
        reply = await rpc(owner_app, "calendar_settings", {switch: False})
        assert reply["ok"] and reply["calendar"]["switches"][switch] is False
        before = len(google.requests)
        with pytest.raises(ServiceError) as error:
            if call is None:
                await calendar.add_event("x", start, start + dt.timedelta(hours=1))
            else:
                await call(start, start + dt.timedelta(hours=1))
        assert error.value.code == "calendar_off" and len(google.requests) == before
    assert owner_app.settings["calendar"] == {
        "read_events": False, "share_free_busy": False, "add_events": False}
    assert emitted(owner_app, "settings") and emitted(owner_app, "calendar_status")


@pytest.mark.asyncio
async def test_update_settings_calendar_also_publishes_status(owner_app):
    owner_app.sio.emit.reset_mock()
    await rpc(owner_app, "update_settings", {"calendar": {"read_events": False}})
    assert emitted(owner_app, "calendar_status")[-1]["switches"] == {
        "read_events": False, "share_free_busy": True, "add_events": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{}, {"read_events": None}, {"read_events": "yes"},
                                  {"read_events": True, "extra": 1}])
async def test_calendar_settings_are_validated(owner_app, data):
    reply = await rpc(owner_app, "calendar_settings", data)
    assert reply == {"ok": False, "code": "invalid_arguments", "message": "Invalid calendar request."}


def test_default_switches_are_on():
    from services.settings import CALENDAR_DEFAULTS

    assert CALENDAR_DEFAULTS == {"read_events": True, "share_free_busy": True, "add_events": True}


# --- the brain's tools --------------------------------------------------------------------


def server_permissions():
    import server

    return {key: server.DEFAULT_SETTINGS["tool_permissions"][key]
            for key in ("calendar_read", "calendar_write")}


def test_default_tool_permissions():
    assert server_permissions() == {"calendar_read": False, "calendar_write": True}


@pytest.mark.asyncio
async def test_calendar_events_never_asks_and_parses_day_words(owner_app, google):
    owner_app.settings["tool_permissions"].update(server_permissions())
    set_client(owner_app)
    await connect(owner_app, google)
    approval = pytest.fail  # never called
    result = await owner_app.dispatcher.dispatch(
        "owner", "calendar_events", {"start": "tomorrow", "end": "tomorrow"},
        owner_app.sessions.context("client").tools(), approval,
    )
    params = dict(google.requests[-1].url.params)
    assert params["timeMin"] == "2026-11-09T00:00:00+08:00"
    assert params["timeMax"] == "2026-11-10T00:00:00+08:00"
    assert result["events"] == []


@pytest.mark.asyncio
async def test_calendar_events_is_refused_when_not_connected_or_off(owner_app, google):
    owner_app.settings["tool_permissions"].update(server_permissions())
    context = owner_app.sessions.context("client").tools()
    with pytest.raises(ServiceError) as error:
        await owner_app.dispatcher.dispatch(
            "owner", "calendar_events", {"start": "today", "end": "today"}, context)
    assert error.value.code == "not_connected" and "Connect it in Connections" in str(error.value)
    set_client(owner_app)
    await connect(owner_app, google)
    owner_app.settings["calendar"] = {"read_events": False}
    with pytest.raises(ServiceError) as error:
        await owner_app.dispatcher.dispatch(
            "owner", "calendar_events", {"start": "today", "end": "today"}, context)
    assert error.value.code == "calendar_off"


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [True, False, "allow_within_scope"])
async def test_calendar_add_event_always_asks_with_the_approval_sentence(owner_app, google, policy):
    owner_app.settings["tool_permissions"]["calendar_write"] = policy
    set_client(owner_app)
    await connect(owner_app, google)
    requests = []

    async def approve(request):
        requests.append(request)
        owner_app.dispatcher.resolve("owner", request["id"], True)

    result = await owner_app.dispatcher.dispatch(
        "owner", "calendar_add_event",
        {"summary": "Lunch with Aisyah", "start": "2026-11-09T13:00", "end": "2026-11-09T14:00"},
        owner_app.sessions.context("client").tools(), approve,
    )
    (request,) = requests
    assert request["tool"] == "calendar_add_event"
    assert request["args"]["approval"] == (
        "Add “Lunch with Aisyah” to your calendar, Monday 9 November 13:00 to 14:00?")
    assert result["added"] is True and google.find("POST", "/calendar/v3/calendars/primary/events")


@pytest.mark.asyncio
async def test_calendar_add_event_declined_deny_and_off_add_nothing(owner_app, google):
    set_client(owner_app)
    await connect(owner_app, google)
    context = owner_app.sessions.context("client").tools()
    args = {"summary": "Lunch", "start": "2026-11-09T13:00", "end": "2026-11-09T14:00"}

    async def decline(request):
        owner_app.dispatcher.resolve("owner", request["id"], False)

    with pytest.raises(ServiceError) as error:
        await owner_app.dispatcher.dispatch("owner", "calendar_add_event", args, context, decline)
    assert error.value.code == "permission_denied"
    owner_app.settings["tool_permissions"]["calendar_write"] = "deny"
    with pytest.raises(ServiceError) as error:
        await owner_app.dispatcher.dispatch("owner", "calendar_add_event", args, context, decline)
    assert error.value.code == "permission_denied"
    owner_app.settings["tool_permissions"]["calendar_write"] = True
    owner_app.settings["calendar"] = {"add_events": False}
    asked = []

    async def record(request):
        asked.append(request)

    with pytest.raises(ServiceError) as error:
        await owner_app.dispatcher.dispatch("owner", "calendar_add_event", args, context, record)
    assert error.value.code == "calendar_off" and not asked
    assert not google.find("POST", "/calendar/v3/calendars/primary/events")


def test_tool_schemas_are_model_visible_with_guidance(owner_app):
    schemas = {item["name"]: item for item in owner_app.dispatcher.schemas()}
    assert "what's on" in schemas["calendar_events"]["description"]
    assert "approves on screen" in schemas["calendar_add_event"]["description"]
    assert set(schemas["calendar_add_event"]["parameters"]["properties"]) == {
        "summary", "start", "end", "location", "description"}
    tools = owner_app.dispatcher.tools
    assert tools["calendar_events"].permission == "calendar_read"
    assert tools["calendar_add_event"].permission == "calendar_write"
    assert tools["calendar_add_event"].always_ask is True


def test_day_words_and_dates():
    moment = calendar_tools.moment
    assert moment("today", now=NOW) == dt.datetime(2026, 11, 8, tzinfo=TIMEZONE)
    assert moment("Today", end=True, now=NOW) == dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    assert moment("friday", now=NOW).date() == dt.date(2026, 11, 13)
    assert moment("sunday", now=NOW).date() == dt.date(2026, 11, 8)
    assert moment("next sunday", now=NOW).date() == dt.date(2026, 11, 15)
    assert moment("2026-11-20", end=True, now=NOW) == dt.datetime(2026, 11, 21, tzinfo=TIMEZONE)
    assert moment("2026-11-09T15:00", now=NOW) == dt.datetime(2026, 11, 9, 15, tzinfo=TIMEZONE)
    assert moment("2026-11-09T07:00:00Z", now=NOW).hour == 15
    with pytest.raises(ValueError):
        moment("someday", now=NOW)


@pytest.mark.parametrize("args", [
    {"summary": "x", "start": "2026-11-09", "end": "2026-11-09T14:00"},
    {"summary": "  ", "start": "2026-11-09T13:00", "end": "2026-11-09T14:00"},
    {"summary": "x", "start": "2026-11-09T13:00", "end": "2026-11-09T14:00", "attendees": []},
])
def test_add_event_arguments_are_validated(args):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        calendar_tools.CalendarEvent.model_validate(args)


def test_add_event_end_must_follow_start():
    args = calendar_tools.CalendarEvent.model_validate(
        {"summary": "x", "start": "2026-11-09T14:00", "end": "2026-11-09T13:00"})
    with pytest.raises(ServiceError):
        args.window()


# --- routes: owner only -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["calendar_status", "calendar_connect", "calendar_cancel",
                                  "calendar_disconnect", "calendar_settings"])
@pytest.mark.parametrize("sid", ["unknown", "other", "tray", "locked"])
async def test_routes_need_the_unlocked_owner_renderer(owner_app, google, name, sid):
    set_client(owner_app)
    owner_app.calendar.secrets.set("google_calendar_refresh_token", REFRESH)
    if sid == "locked":
        sid = "client"
        owner_app.settings["face_auth_enabled"] = True
    data = {"read_events": False} if name == "calendar_settings" else {}
    reply = await rpc(owner_app, name, data, sid=sid)
    assert reply["ok"] is False
    assert reply["code"] in ("authentication_required", "permission_denied")
    assert owner_app.calendar.flow is None and not google.requests
    assert owner_app.calendar.refresh_token() == REFRESH
    assert "calendar" not in owner_app.settings


@pytest.mark.asyncio
async def test_status_is_published_only_to_the_unlocked_owners_renderers(owner_app):
    owner_app.sio.emit.reset_mock()
    await owner_app.calendar.publish()
    rooms = [c.kwargs["room"] for c in owner_app.sio.emit.await_args_list]
    assert rooms == ["client"]
    owner_app.settings["face_auth_enabled"] = True
    owner_app.sio.emit.reset_mock()
    await owner_app.calendar.publish()
    owner_app.sio.emit.assert_not_called()


# --- nothing sensitive in logs or replies -------------------------------------------------


@pytest.mark.asyncio
async def test_no_tokens_codes_secrets_emails_or_event_text_in_logs(owner_app, google, caplog):
    caplog.set_level(logging.DEBUG)
    set_client(owner_app)
    replies = [await rpc(owner_app, "calendar_status", {})]
    await connect(owner_app, google)
    google.items = [{"summary": TITLE, "start": {"dateTime": "2026-11-09T10:00:00+08:00"},
                     "end": {"dateTime": "2026-11-09T11:00:00+08:00"}}]
    start = dt.datetime(2026, 11, 9, tzinfo=TIMEZONE)
    await owner_app.calendar.events(start, start + dt.timedelta(days=1))
    await owner_app.calendar.busy(start, start + dt.timedelta(days=1))
    owner_app.calendar.access = (ACCESS, 0)
    google.overrides[("POST", "oauth2.googleapis.com/token")] = httpx.ConnectError(
        f"failed sending {REFRESH} {CLIENT_SECRET}")
    with pytest.raises(ServiceError):
        await owner_app.calendar.events(start, start + dt.timedelta(days=1))
    replies.append(await rpc(owner_app, "calendar_disconnect", {}))
    logged = caplog.text + "".join(str(r.args) for r in caplog.records)
    for value in SENSITIVE:
        assert value not in logged
    text = json.dumps(replies)
    for value in (CLIENT_SECRET, REFRESH, ACCESS, ACCESS_2, CODE, TITLE):
        assert value not in text
    status_events = json.dumps(emitted(owner_app, "calendar_status"))
    for value in (CLIENT_SECRET, REFRESH, ACCESS, ACCESS_2, CODE):
        assert value not in status_events


# --- the internal refresh-token secret ----------------------------------------------------


def test_internal_secret_is_never_listed(owner_app):
    owner_app.secrets.set("google_calendar_refresh_token", REFRESH)
    names = [item["name"] for item in owner_app.secrets.statuses()]
    assert "google_calendar_refresh_token" not in names
    assert {"google_oauth_client_id", "google_oauth_client_secret"} <= set(names)
    assert REFRESH not in json.dumps(owner_app.secrets.statuses())


@pytest.mark.asyncio
async def test_secrets_routes_refuse_the_internal_secret(owner_app):
    owner_app.secrets.set("google_calendar_refresh_token", REFRESH)
    listed = await rpc(owner_app, "secrets_status", {})
    assert "google_calendar_refresh_token" not in [item["name"] for item in listed["secrets"]]
    for route, data in (("secrets_set", {"name": "google_calendar_refresh_token", "value": "1//" + "a" * 40}),
                        ("secrets_clear", {"name": "google_calendar_refresh_token"}),
                        ("secrets_test", {"name": "google_calendar_refresh_token"})):
        reply = await rpc(owner_app, route, data)
        assert reply["ok"] is False and reply["code"] == "invalid_arguments"
    assert owner_app.secrets.get("google_calendar_refresh_token") == REFRESH


@pytest.mark.asyncio
async def test_client_id_and_secret_are_normal_user_secrets(owner_app):
    reply = await rpc(owner_app, "secrets_set", {"name": "google_oauth_client_id", "value": CLIENT_ID})
    assert reply["ok"] and reply["secret"]["configured"]
    reply = await rpc(owner_app, "secrets_set", {"name": "google_oauth_client_secret",
                                                 "value": "not-a-secret"})
    assert reply["ok"] is False and reply["code"] == "invalid_format"
    reply = await rpc(owner_app, "secrets_set", {"name": "google_oauth_client_secret",
                                                 "value": CLIENT_SECRET, "verify": True})
    assert reply["ok"] and reply["check"]["code"] == "no_check"
    assert CLIENT_SECRET not in json.dumps(reply)
    assert owner_app.calendar.status()["setup_needed"] is False


def test_cli_rejects_the_internal_secret(tmp_path, monkeypatch, capsys):
    import importlib.util
    import io
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/jarvis-secrets.py"
    spec = importlib.util.spec_from_file_location("jarvis_secrets_cli_p3", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    for command in ("set", "clear", "test"):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(REFRESH.encode()), encoding="utf-8"))
        code = cli.main(["--data-dir", str(tmp_path / "db"), command, "google_calendar_refresh_token"])
        result = json.loads(capsys.readouterr().out)
        assert code != 0 and result["code"] == "invalid_input"
        assert "google_calendar_refresh_token" not in result["message"]
    cli.main(["--data-dir", str(tmp_path / "db"), "status"])
    assert "google_calendar_refresh_token" not in capsys.readouterr().out
