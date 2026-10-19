"""R7 protocol acceptance with generated device keys and isolated storage, no phone/API."""

import asyncio
import base64
import json
import socket
import ssl
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from services.mobile_identity import signing_bytes
from services.mobile_listener import private_host
from services.tools import ServiceError
from transport.mobile_api import MobileAPI


@pytest.fixture
def mobile(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"desktop": "owner", "other": "other", "tray": "owner"})
    app.sessions.roles.update({"desktop": "renderer", "other": "renderer", "tray": "resident"})
    app.mobile.listener = SimpleNamespace(
        running=True,
        endpoint="https://192.168.1.2:8443",
        certificate="fixture-certificate",
        snapshot=lambda: {"enabled": True, "endpoint": "https://192.168.1.2:8443"},
        stop=AsyncMock(),
    )
    return app


class Phone:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = str(uuid.uuid4())
        self.public = base64.b64encode(
            self.key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ).decode()

    def envelope(self, operation, payload, **overrides):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        identifier = str(uuid.uuid4())
        timestamp = int(time.time())
        signature = self.key.sign(
            signing_bytes("/v1/" + operation, self.id, identifier, timestamp, body),
            ec.ECDSA(hashes.SHA256()),
        )
        return {
            "device_id": self.id,
            "request_id": identifier,
            "timestamp": timestamp,
            "signature": base64.b64encode(signature).decode(),
            "payload": body,
            **overrides,
        }


async def post(app, phone, operation, payload=None, envelope=None, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MobileAPI(app.mobile).app),
        base_url="https://192.168.1.2:8443",
    ) as client:
        return await client.post(
            "/v1/" + operation, json=envelope or phone.envelope(operation, payload or {}), **kwargs
        )


async def pair(app, phone, chat=False, approve=True):
    bundle = app.mobile.pair("owner", app.projects.get_current_project_path(), chat)
    response = await post(
        app,
        phone,
        "claim",
        {
            "challenge_id": bundle["challenge_id"],
            "secret": bundle["secret"],
            "public_key": phone.public,
            "name": "Fixture phone",
        },
    )
    assert response.json()["state"] == "pending", response.text
    if approve:
        app.mobile.decide("owner", phone.id, True)
    return bundle


@pytest.mark.asyncio
async def test_pair_is_owner_confirmed_single_use_and_pending_has_no_read_access(mobile):
    phone = Phone()
    bundle = await pair(mobile, phone, approve=False)
    assert (await post(mobile, phone, "finish")).json()["state"] == "pending"
    assert not (await post(mobile, phone, "status")).json()["ok"]
    assert not (
        await post(
            mobile,
            Phone(),
            "claim",
            {
                "challenge_id": bundle["challenge_id"],
                "secret": bundle["secret"],
                "public_key": phone.public,
                "name": "Intruder",
            },
        )
    ).json()["ok"]
    with pytest.raises(ServiceError):
        mobile.mobile.decide("other", phone.id, True)
    mobile.mobile.decide("owner", phone.id, True)
    assert (await post(mobile, phone, "finish")).json()["state"] == "approved"
    assert (await post(mobile, phone, "status")).json()["tools_enabled"] is False


@pytest.mark.asyncio
async def test_replay_and_device_state_survive_service_restart(mobile):
    from services.mobile import MobileService

    phone = Phone()
    await pair(mobile, phone)
    envelope = phone.envelope("status", {})
    assert (await post(mobile, phone, "status", envelope=envelope)).json()["ok"]
    mobile.mobile = MobileService(mobile)
    assert (await post(mobile, phone, "status", envelope=envelope)).json()[
        "code"
    ] == "mobile_replay"
    assert (await post(mobile, phone, "status")).json()["ok"]
    await mobile.mobile.revoke("owner", phone.id)
    assert (await post(mobile, phone, "status")).json()["code"] == "mobile_auth"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", 0),
        ("device_id", str(uuid.uuid4())),
        ("payload", '{"owner":"other"}'),
        ("signature", "A" * 96),
    ],
)
async def test_tampered_signed_requests_fail_closed(mobile, field, value):
    phone = Phone()
    await pair(mobile, phone)
    assert not (
        await post(mobile, phone, "status", envelope={**phone.envelope("status", {}), field: value})
    ).json()["ok"]


@pytest.mark.asyncio
async def test_invitation_and_grant_expiry_and_pending_restart(mobile):
    phone = Phone()
    bundle = mobile.mobile.pair("owner", mobile.projects.get_current_project_path(), False)
    mobile.mobile.challenge["expires"] = 0
    response = await post(
        mobile,
        phone,
        "claim",
        {
            "challenge_id": bundle["challenge_id"],
            "secret": bundle["secret"],
            "public_key": phone.public,
            "name": "Fixture",
        },
    )
    assert response.json()["code"] == "mobile_pair"
    await pair(mobile, phone, approve=False)
    mobile.mobile.pending[phone.id]["pair_expires"] = 0
    with pytest.raises(ServiceError):
        mobile.mobile.decide("owner", phone.id, True)
    await pair(mobile, phone)
    value = mobile.mobile.identities.get(phone.id)
    value["expires"] = 0
    mobile.mobile.identities.save(value)
    assert (await post(mobile, phone, "status")).json()["code"] == "mobile_auth"


@pytest.mark.asyncio
async def test_project_and_two_device_history_scope_do_not_follow_global_project(mobile):
    phone = Phone()
    await pair(mobile, phone, chat=True)
    old = mobile.projects.get_current_project_path()
    mobile.projects.create_project("Second")
    mobile.projects.switch_project("Second")
    other = Phone()
    await pair(mobile, other, chat=True)
    assert (await post(mobile, other, "status")).json()["project"] == "Second"
    calls = []
    mobile.cad.list = lambda owner, project: calls.append((owner, project)) or []
    mobile.images.list = lambda owner, project: []
    assert (await post(mobile, phone, "jobs")).json()["project"] == old.name
    assert calls == [("owner", old.resolve())]
    conversation = str(uuid.uuid4())
    mobile.mobile.chat.store.restore(
        conversation,
        mobile.mobile.principal(mobile.mobile.identities.get(phone.id)),
        str(old.resolve()),
    )
    with mobile.database.transaction() as db:
        mobile.mobile.chat.store._save(
            db,
            conversation,
            mobile.mobile.principal(mobile.mobile.identities.get(phone.id)),
            str(old.resolve()),
            [],
        )
    assert (await post(mobile, other, "history", {"conversation_id": conversation})).json()[
        "code"
    ] == "conversation_scope"


@pytest.mark.asyncio
async def test_chat_has_no_tools_idempotent_receipts_and_no_grant_by_default(mobile):
    from llm.base import LLMResponse, ToolCall

    phone = Phone()
    await pair(mobile, phone)
    args = {
        "conversation_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "text": "Hello fixture",
    }
    assert (await post(mobile, phone, "chat", args)).json()["code"] == "mobile_grant"
    value = mobile.mobile.identities.get(phone.id)
    value["grants"].append("chat:ask")
    mobile.mobile.identities.save(value)

    class Provider:
        count = 0
        closed = False

        async def generate(self, messages, **kwargs):
            self.count += 1
            assert kwargs["tools"] is None
            if self.count == 1:
                return LLMResponse(
                    tool_calls=[ToolCall("one", "write_file", {"path": "blocked", "content": "no"})]
                )
            assert "tool_unavailable" in messages[-1].content
            return LLMResponse(text="Tool-free fixture answer")

        async def close(self):
            self.closed = True

    provider = Provider()
    mobile.mobile.chat.provider_factory = lambda: provider
    response = await post(mobile, phone, "chat", args)
    assert response.json()["text"] == "Tool-free fixture answer", response.text
    assert not (mobile.projects.get_current_project_path() / "blocked").exists()
    assert (await post(mobile, phone, "chat", args)).json()["text"] == "Tool-free fixture answer"
    assert provider.count == 2 and provider.closed
    receipt = {k: v for k, v in args.items() if k != "text"}
    assert (await post(mobile, phone, "receipt", receipt)).json()["state"] == "succeeded"
    receipt["request_id"] = str(uuid.uuid4())
    assert (await post(mobile, phone, "receipt", receipt)).json()["state"] == "absent"


@pytest.mark.asyncio
async def test_revoke_cancels_provider_and_uncertain_chat_is_not_replayed(mobile):
    from services.mobile_contracts import MobileChat, MobileReceipt

    phone = Phone()
    await pair(mobile, phone, chat=True)
    value = mobile.mobile.identities.get(phone.id)
    entered = asyncio.Event()
    closed = asyncio.Event()

    class Provider:
        async def generate(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def close(self):
            closed.set()

    mobile.mobile.chat.provider_factory = Provider
    args = MobileChat(conversation_id=uuid.uuid4(), request_id=uuid.uuid4(), text="Fixture")
    task = asyncio.create_task(mobile.mobile.ask(value, args))
    await asyncio.wait_for(entered.wait(), 3)
    await mobile.mobile.revoke("owner", phone.id)
    assert task.cancelled() and closed.is_set() and not mobile.mobile.running
    assert (
        mobile.mobile.receipt(
            value, MobileReceipt(conversation_id=args.conversation_id, request_id=args.request_id)
        )["state"]
        == "uncertain"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["other", "tray", "unknown"])
@pytest.mark.parametrize(
    "operation",
    ["mobile_listener", "mobile_pair", "mobile_decide", "mobile_revoke", "mobile_pair_cancel"],
)
async def test_desktop_mobile_controls_require_owner_renderer(mobile, sid, operation):
    result = await mobile.sio.handlers["/"][operation](sid, {})
    assert not result["ok"] and mobile.mobile.challenge is None


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "8.8.8.8", "169.254.1.1", "localhost", "192.168.1.1.evil", "255.255.255.255"],
)
def test_listener_rejects_wildcard_public_and_dns_hosts(host):
    with pytest.raises(ServiceError):
        private_host(host)


@pytest.mark.asyncio
async def test_mobile_api_is_not_on_desktop_and_refuses_http_origin_and_oversize(mobile):
    phone = Phone()
    await pair(mobile, phone)
    api = MobileAPI(mobile.mobile).app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://192.168.1.2:8443"
    ) as client:
        assert (
            await client.post("/v1/status", json=phone.envelope("status", {}))
        ).status_code == 403
    assert (
        await post(mobile, phone, "status", headers={"Origin": "https://evil.invalid"})
    ).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://192.168.1.2:8443"
    ) as client:
        assert (await client.post("/v1/status", content=b"x" * 65537)).status_code == 413
        assert (await client.post("/user_input", json={})).status_code == 404
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile.app), base_url="https://desktop"
    ) as client:
        assert (await client.post("/v1/status", json={})).status_code == 404


@pytest.mark.asyncio
async def test_real_loopback_tls_identity_protected_no_plaintext_key_and_clean_stop(
    application_factory,
    monkeypatch,
):
    app = application_factory()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    import uvicorn
    from pathlib import Path

    load = uvicorn.Config.load

    def inspected_load(config):
        assert b"ENCRYPTED PRIVATE KEY" in Path(config.ssl_keyfile).read_bytes()
        assert config.ssl_keyfile_password
        return load(config)

    monkeypatch.setattr(uvicorn.Config, "load", inspected_load)
    import signal

    original_signal = signal.getsignal(signal.SIGINT)
    await app.mobile.listener.start("127.0.0.1", port)
    assert signal.getsignal(signal.SIGINT) == original_signal
    try:
        from cryptography import x509

        cert = x509.load_der_x509_certificate(base64.b64decode(app.mobile.listener.certificate))
        pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        context = ssl.create_default_context(cadata=pem)
        async with httpx.AsyncClient(verify=context, trust_env=False) as client:
            result = await client.post(app.mobile.listener.endpoint + "/v1/status", json={})
            assert result.status_code == 400
        assert not list(app.database.directory.glob("inara-tls-*"))
        assert b"PRIVATE KEY" not in app.database.path.read_bytes()
    finally:
        await app.mobile.close()
    assert not app.mobile.listener.task and not app.mobile.listener.socket


@pytest.mark.asyncio
async def test_clock_rollback_and_path_replay_are_rejected(mobile):
    phone = Phone()
    await pair(mobile, phone)
    assert (await post(mobile, phone, "jobs", envelope=phone.envelope("status", {}))).json()[
        "code"
    ] == "mobile_auth"
    mobile.mobile.identities.clock = lambda: time.time() - 100
    assert (await post(mobile, phone, "status")).json()["code"] == "mobile_clock"


@pytest.mark.asyncio
async def test_mobile_previews_are_project_bound_and_image_size_bounded(mobile):
    phone = Phone()
    await pair(mobile, phone)
    project = mobile.projects.get_current_project_path()
    identifier = str(uuid.uuid4())
    mobile.cad.save(
        "owner",
        project,
        {
            "request_id": identifier,
            "state": "succeeded",
            "recipe": {"name": "Fixture box"},
            "stats": {"triangles": 12},
        },
    )
    assert (await post(mobile, phone, "preview", {"kind": "cad", "request_id": identifier})).json()[
        "recipe"
    ] == {"name": "Fixture box"}
    mobile.projects.create_project("Other")
    foreign = str(uuid.uuid4())
    mobile.cad.save(
        "owner",
        mobile.projects.projects_dir / "Other",
        {"request_id": foreign, "state": "succeeded", "recipe": {"name": "Private other project"}},
    )
    assert (await post(mobile, phone, "preview", {"kind": "cad", "request_id": foreign})).json()[
        "code"
    ] == "mobile_preview"
    mobile.images.save(
        "owner",
        project,
        {
            "request_id": identifier,
            "state": "succeeded",
            "recipe": {},
            "artifacts": {"png": {"bytes": 2097153}},
        },
    )
    assert (
        await post(mobile, phone, "preview", {"kind": "image", "request_id": identifier})
    ).json()["code"] == "mobile_preview"


@pytest.mark.asyncio
async def test_http_disconnect_cancels_owned_chat(mobile):
    from services.mobile_contracts import MobileChat

    phone = Phone()
    await pair(mobile, phone, chat=True)
    value = mobile.mobile.identities.get(phone.id)
    entered = asyncio.Event()
    closed = asyncio.Event()

    class Provider:
        async def generate(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def close(self):
            closed.set()

    class Request:
        async def receive(self):
            await entered.wait()
            return {"type": "http.disconnect"}

    mobile.mobile.chat.provider_factory = Provider
    with pytest.raises(ServiceError, match="receipt"):
        await MobileAPI(mobile.mobile).ask_connected(
            Request(),
            value,
            MobileChat(conversation_id=uuid.uuid4(), request_id=uuid.uuid4(), text="Fixture"),
        )
    assert closed.is_set() and not mobile.mobile.running


def test_mobile_inventory_matches_isolated_api(mobile):
    from pathlib import Path
    from fastapi.routing import APIRoute

    matrix = json.loads(Path("docs/ROUTE_POLICY_MATRIX.json").read_text(encoding="utf-8"))
    assert set(matrix["mobile_http_routes"]) == {
        route.path for route in MobileAPI(mobile.mobile).app.routes if isinstance(route, APIRoute)
    }
    assert not mobile.mobile.chat.dispatcher.tools


def test_utf8_signature_vector_matches_android_protocol_contract():
    assert (
        signing_bytes("/v1/status", "device", "request", 123, '{"text":"\u4f60\u597d"}').decode()
        == "INARA-MOBILE-1\nPOST\n/v1/status\ndevice\nrequest\n123\nac72dedbe8e0d53dda6f5cbfd5e1c9e6f7f8bac70c7423177e450174b1c09d83"
    )


@pytest.mark.asyncio
async def test_phone_history_never_migrates_legacy_desktop_chat(mobile):
    phone = Phone()
    await pair(mobile, phone, chat=True)
    legacy = mobile.projects.get_current_project_path() / "chat_history.jsonl"
    legacy.write_text(
        '{"sender":"User","text":"Private desktop legacy transcript"}\n', encoding="utf-8"
    )
    result = await post(mobile, phone, "history", {"conversation_id": str(uuid.uuid4())})
    assert result.json()["messages"] == []
