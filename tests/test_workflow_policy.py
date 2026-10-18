"""Owner-scoped reminder receipts and common planner authorization."""

import asyncio
from unittest.mock import AsyncMock
import uuid
import pytest


@pytest.fixture
def policy(application_factory):
    app = application_factory()
    owner = str(uuid.uuid4())
    for sid, principal, role in [
        ("ui", owner, "renderer"),
        ("tray", owner, "resident"),
        ("control", owner, "workspace"),
        ("foreign", str(uuid.uuid4()), "renderer"),
    ]:
        app.sessions.accept(sid, {"client_id": principal, "role": role})
    app.settings["tool_permissions"].update({"generate_cad": False, "create_reminder": False})
    app.cad_transport.planner = AsyncMock(return_value={"shape": "box"})
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["get_reminders", "dismiss_reminder", "create_reminder"])
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign"])
async def test_reminder_reads_and_mutations_require_owner_renderer(policy, name, sid):
    await policy.sio.handlers["/"][name](
        sid, {} if name != "create_reminder" else {"task": "fixture", "when": "in 5 minutes"}
    )
    assert policy.sio.emit.await_args.args[0] == "error"
    assert policy.sio.emit.await_args.kwargs["room"] == sid
    assert not policy.reminders.list_reminders()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"delivery_id": 123},
        {"delivery_id": "not-uuid"},
        {"delivery_id": str(uuid.uuid4()), "owner": "foreign"},
    ],
)
async def test_receipt_schema_rejects_malformed_or_identity_data(policy, payload):
    await policy.reminder_transport.acknowledge_reminder("ui", payload)
    assert policy.sio.emit.await_args.args[1]["code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_delivery_receipt_retry_and_completion_are_idempotent_and_scoped(policy):
    app = policy
    app.reminders.add_reminder("fixture", 1)
    delivery = app.reminders.claim_deliveries(app.sessions.local_owner, now=100)[0]
    payload = {"delivery_id": delivery["delivery_id"]}
    await app.reminder_transport.acknowledge_reminder("foreign", payload)
    assert app.sio.emit.await_args.args[1]["code"] == "permission_denied"
    app.sio.emit.reset_mock()
    await app.reminder_transport.acknowledge_reminder("ui", payload)
    await app.reminder_transport.acknowledge_reminder("ui", payload)
    assert app.reminders.open_deliveries(app.sessions.local_owner)[0]["state"] == "acknowledged"
    await app.reminder_transport.dismiss_reminder("ui", payload)
    await app.reminder_transport.dismiss_reminder("ui", payload)
    assert not app.reminders.open_deliveries(app.sessions.local_owner)
    assert all(c.kwargs["room"] in ("ui", "tray") for c in app.sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_locked_resident_can_acknowledge_but_not_complete_delivery(policy):
    app = policy
    app.reminders.add_reminder("fixture", 1)
    delivery = app.reminders.claim_deliveries(app.sessions.local_owner, now=100)[0]
    app.settings["face_auth_enabled"] = True
    await app.reminder_transport.acknowledge_reminder(
        "tray", {"delivery_id": delivery["delivery_id"]}
    )
    assert app.reminders.open_deliveries(app.sessions.local_owner)[0]["state"] == "acknowledged"
    await app.reminder_transport.dismiss_reminder("tray", {"delivery_id": delivery["delivery_id"]})
    assert app.sio.emit.await_args.args[0] == "error"


@pytest.mark.asyncio
async def test_foreign_channels_never_claim_owner_reminders(policy):
    app = policy
    app.reminders.claim_deliveries = AsyncMock()
    for sid in ("ui", "tray", "control"):
        app.sessions.remove(sid)
    await app.delivery.deliver_reminders_once()
    app.reminders.claim_deliveries.assert_not_called()


@pytest.mark.asyncio
async def test_origin_disconnect_cancels_reminder_approval_with_resident_remaining(policy):
    app = policy
    app.settings["tool_permissions"]["create_reminder"] = True
    waiting = asyncio.Event()

    async def emit(name, data, room=None):
        if name == "tool_confirmation_request":
            waiting.set()

    app.sio.emit = emit
    request = asyncio.create_task(
        app.reminder_transport.create_reminder("ui", {"task": "fixture", "when": "in 5 minutes"})
    )
    await asyncio.wait_for(waiting.wait(), 1)
    await app.disconnect("ui")
    assert request.cancelled() and not app.dispatcher.pending
    assert not app.reminders.list_reminders()


@pytest.mark.asyncio
async def test_planner_direct_and_model_paths_share_generation_denial(policy):
    app = policy
    app.settings["tool_permissions"]["generate_cad"] = "deny"
    response = await app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "a box"})
    assert response["code"] == "permission_denied"
    from services.tools import ServiceError

    with pytest.raises(ServiceError):
        await app.dispatcher.dispatch(
            app.sessions.local_owner,
            "plan_cad",
            {"prompt": "a box"},
            app.sessions.context("ui").tools(),
        )
    app.cad_transport.planner.assert_not_called()


@pytest.mark.asyncio
async def test_planner_own_deny_does_not_weaken_canonical_policy(policy):
    app = policy
    app.settings["tool_permissions"]["plan_cad"] = "deny"
    response = await app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "a box"})
    assert response["code"] == "permission_denied"
    app.cad_transport.planner.assert_not_called()


@pytest.mark.asyncio
async def test_planner_approved_result_and_wrong_owner_schema_gate(policy):
    app = policy
    response = await app.sio.handlers["/"]["cad_plan"]("foreign", {"prompt": "a box"})
    assert not response["ok"]
    response = await app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": 123})
    assert not response["ok"]
    response = await app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "a box"})
    assert response == {"ok": True, "recipe": {"shape": "box"}}
    app.cad_transport.planner.assert_awaited_once_with("a box")


@pytest.mark.asyncio
async def test_planner_close_cancels_unapproved_request_before_provider(policy):
    app = policy
    app.settings["tool_permissions"]["generate_cad"] = True
    waiting = asyncio.Event()

    async def emit(name, data, room=None):
        if name == "tool_confirmation_request":
            waiting.set()

    app.sio.emit = emit
    task = asyncio.create_task(app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "a box"}))
    await asyncio.wait_for(waiting.wait(), 1)
    await app.cad_transport.close()
    assert task.cancelled() and not app.dispatcher.pending and not app.cad_transport.planning
    app.cad_transport.planner.assert_not_called()


def test_all_provider_visible_schemas_validate_through_installed_sdk(policy):
    from google.genai import types

    declarations = policy.dispatcher.schemas()
    # Check the actual SDK request types without constructing a client or making a request.
    for item in declarations:
        types.FunctionDeclaration.model_validate(item)
