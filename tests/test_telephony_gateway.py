"""The telephony gateway over a real loopback listener, and the owner-only
calls_status route on the composition root. Loopback only; no Twilio."""

import asyncio
import base64
import json
from pathlib import Path
import uuid
from urllib.parse import urlencode

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from services.tools import ServiceError
from telephony.gateway import PATHS, GatewayServer, build_app, configured_port
from telephony.service import TelephonyService
from telephony.signature import compute_signature

from tests.test_telephony import (
    ACCOUNT, BASE, CALL, INARA, STREAM, TOKEN, FakeApp, Tunnel, inbound_params, make_service,
    media_message, start_message,
)


@pytest.fixture
async def gateway():
    received = []

    async def agent(session):
        received.append(await session.read(timeout=5))
        await session.send(b"\x00\x00" * 160, 8000)
        await session.hangup()

    service = make_service(agent=agent)
    await service.gateway.start()
    service.received = received
    try:
        yield service, f"http://127.0.0.1:{service.gateway.bound_port}"
    finally:
        await service.gateway.stop()


def signed(path, params, url=None):
    signature = compute_signature(TOKEN, url or BASE + path, params)
    return {"X-Twilio-Signature": signature, "Content-Type": "application/x-www-form-urlencoded"}


async def post(local, path, params, headers):
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        return await client.post(local + path, content=urlencode(params), headers=headers)


async def test_only_the_four_telephony_paths_exist(gateway):
    service, local = gateway
    assert service.gateway.status() == {"listening": True, "host": "127.0.0.1",
                                        "port": service.gateway.bound_port}
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        for method, path in (
            ("GET", "/"), ("GET", "/status"), ("GET", "/docs"), ("GET", "/openapi.json"),
            ("POST", "/telephony"), ("POST", "/telephony/voice"), ("POST", "/telephony/other"),
            ("GET", "/telephony/voice/inbound"), ("PUT", "/telephony/status"),
            ("GET", "/telephony/media"), ("POST", "/socket.io/"),
        ):
            response = await client.request(method, local + path)
            assert response.status_code == 404, (method, path)
            assert response.content == b""
            assert "server" not in response.headers


async def test_webhooks_require_a_valid_signature_over_the_public_url(gateway):
    service, local = gateway
    path = "/telephony/voice/inbound"
    params = inbound_params()
    for headers in (
        {"Content-Type": "application/x-www-form-urlencoded"},
        {**signed(path, params), "X-Twilio-Signature": "bogus"},
        signed(path, params, url=local + path),  # signed over the local URL
        signed(path, {**params, "From": INARA}),  # signed over different params
        {**signed(path, params), "Content-Type": "application/json"},
    ):
        response = await post(local, path, params, headers)
        assert response.status_code == 403 and response.content == b""
    wrong_account = {**params, "AccountSid": "AC" + "9" * 32}
    response = await post(local, path, wrong_account, signed(path, wrong_account))
    assert response.status_code == 403
    response = await post(local, path, params, signed(path, params))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert b"<Connect><Stream url=\"wss://calls.example.com/telephony/media\">" in response.content


async def test_signature_covers_the_query_string(gateway):
    service, local = gateway
    await service.status_callback({})  # no-op
    path = "/telephony/status"
    params = {"AccountSid": ACCOUNT, "CallSid": CALL, "CallStatus": "completed"}
    query_url = BASE + path + "?x=1"
    response = await post(local, path + "?x=1", params, signed(path, params))
    assert response.status_code == 403
    response = await post(local, path + "?x=1", params, signed(path, params, url=query_url))
    assert response.status_code == 204


async def test_unconfigured_gateway_refuses_everything():
    service = make_service(calls={"public_base_url": ""})
    await service.gateway.start()
    try:
        local = f"http://127.0.0.1:{service.gateway.bound_port}"
        path = "/telephony/voice/inbound"
        response = await post(local, path, inbound_params(), signed(path, inbound_params()))
        assert response.status_code == 403
    finally:
        await service.gateway.stop()


async def test_media_upgrade_requires_signature_and_stream_token(gateway):
    service, local = gateway
    uri = local.replace("http://", "ws://") + "/telephony/media"
    with pytest.raises(InvalidStatus) as error:
        async with connect(uri, proxy=None, open_timeout=5):
            pass
    assert error.value.response.status_code == 403
    bad = {"X-Twilio-Signature": compute_signature(TOKEN, uri, ())}  # local URL
    with pytest.raises(InvalidStatus):
        async with connect(uri, proxy=None, additional_headers=bad, open_timeout=5):
            pass
    headers = {"X-Twilio-Signature": compute_signature(TOKEN, "wss://calls.example.com/telephony/media", ())}
    token = service.stream_tokens.issue(CALL, "inbound")
    async with connect(uri, proxy=None, additional_headers=headers, open_timeout=5) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps(start_message(token)))
        await ws.send(json.dumps(media_message(b"\xff" * 160)))
        replies = []
        with pytest.raises(ConnectionClosed):
            while True:
                replies.append(json.loads(await asyncio.wait_for(ws.recv(), 5)))
    assert ws.close_code == 1000  # the agent hung up
    assert [reply["event"] for reply in replies] == ["media"]  # 20 ms of agent audio
    assert all(reply["streamSid"] == STREAM for reply in replies)
    assert len(base64.b64decode(replies[0]["media"]["payload"])) == 160
    assert len(service.received[0]) == 640
    # The same token cannot open a second stream.
    async with connect(uri, proxy=None, additional_headers=headers, open_timeout=5) as ws:
        await ws.send(json.dumps(start_message(token)))
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(ws.recv(), 5)
    assert ws.close_code == 1008


async def test_gateway_never_uses_the_core_port():
    service = make_service()
    service.gateway.port = 8000
    with pytest.raises(ServiceError) as error:
        await service.gateway.start()
    assert error.value.code == "telephony_port"
    assert configured_port({"INARA_TELEPHONY_PORT": "8000"}) == 8790
    assert configured_port({"INARA_TELEPHONY_PORT": "9123"}) == 9123
    assert configured_port({}) == 8790


def test_route_matrix_lists_the_gateway_routes():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json").read_text(
            encoding="utf-8"
        )
    )
    app = build_app(make_service())
    assert set(matrix["telephony_routes"]) == {route.path for route in app.routes} == set(PATHS)
    for item in matrix["telephony_routes"].values():
        assert all(item.get(key) for key in ("method", "authentication", "effects"))
    assert "calls_status" in matrix["socket_routes"]


# --- composition root ---------------------------------------------------------------


@pytest.fixture
def owner_app(application_factory, monkeypatch):
    for name in ("INARA_TWILIO_ACCOUNT_SID", "INARA_TWILIO_AUTH_TOKEN", "INARA_TWILIO_PHONE_NUMBER",
                 "INARA_OWNER_PHONE_NUMBER", "INARA_CLOUDFLARE_TUNNEL_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    app = application_factory()
    owner, other = str(uuid.uuid4()), str(uuid.uuid4())
    for sid, principal, role in (
        ("renderer", owner, "renderer"),
        ("tray", owner, "resident"),
        ("control", owner, "workspace"),
        ("foreign", other, "renderer"),
    ):
        assert app.sessions.accept(sid, {"token": "t", "client_id": principal, "role": role}, "t")
    app.secrets.environ = {}
    return app


@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign", "locked"])
async def test_calls_status_is_owner_renderer_only(owner_app, sid):
    if sid == "locked":
        sid = "renderer"
        owner_app.settings["face_auth_enabled"] = True
    result = await owner_app.sio.handlers["/"]["calls_status"](sid, {})
    assert result["ok"] is False
    assert result["code"] in {"authentication_required", "permission_denied"}


async def test_calls_status_reports_readiness_and_never_values(owner_app):
    owner_app.secrets.set("twilio_auth_token", TOKEN)
    handler = owner_app.sio.handlers["/"]["calls_status"]
    assert (await handler("renderer", {"extra": 1}))["code"] == "invalid_arguments"
    result = await handler("renderer", None)
    assert result["ok"] is True
    calls = result["calls"]
    assert calls["enabled"] is False and calls["kill_switch"] is True and calls["ready"] is False
    assert calls["secrets"]["twilio_auth_token"]["configured"] is True
    assert calls["secrets"]["twilio_account_sid"]["configured"] is False
    assert calls["gateway"]["listening"] is False and calls["tunnel"]["state"] == "stopped"
    assert calls["agent"] == "none"
    assert TOKEN not in json.dumps(result)


async def test_core_starts_without_telephony_and_reconciles_on_settings(owner_app):
    app = owner_app
    await app.start()
    try:
        assert not app.telephony.gateway.listening  # off by default, no secrets needed
        app.telephony.gateway.port = 0
        app.telephony.tunnel = Tunnel()
        result = await app.sio.handlers["/"]["update_settings"](
            "renderer", {"calls": {"enabled": True, "public_base_url": BASE}}
        )
        assert result == {"ok": True}
        assert app.telephony.gateway.listening
        assert app.settings["calls"]["public_base_url"] == BASE
        await app.sio.handlers["/"]["update_settings"]("renderer", {"calls": {"enabled": False}})
        assert not app.telephony.gateway.listening
    finally:
        await app.close()
    assert not app.telephony.gateway.listening


async def test_gateway_start_failure_is_reported_not_raised():
    service = TelephonyService(FakeApp(), port=0, tunnel=Tunnel(), environ={})
    blocker = GatewayServer(service, port=0)
    await blocker.start()
    try:
        service.gateway.port = blocker.bound_port  # already taken
        status = await service.reconcile()
        assert status["failure"] == "telephony_listener" and not status["gateway"]["listening"]
    finally:
        await blocker.stop()
