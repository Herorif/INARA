"""Controlled arming with synthetic backend capture and inert supervisors only."""

import asyncio
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest

from calls.fixture import fixture_profile
from calls.testing import CapturedEvidence, CHECKS
from tests.test_call_admission import ControlledSupervisor


@pytest.fixture
def setup(application_factory, monkeypatch, tmp_path):
    import calls.testing as module

    app = application_factory()
    app.sessions.accept("owner", {"client_id": str(uuid.uuid4())})
    app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    monkeypatch.setattr("calls.local_voice.ready", lambda: None)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "source_digest", lambda: "c" * 64)
    helper = tmp_path / ".runtime/call-bridge/bin/CallControl.exe"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"INERT TEST BYTES; NEVER EXECUTED")
    policy = tmp_path / "config/call-test-policy.json"
    policy.parent.mkdir()
    policy.write_text(
        json.dumps({"format": 1, "enabled": False, "channels": ["sim", "whatsapp_personal"]})
    )
    app.call_testing.components_ready = lambda: True
    clock = [100.0]
    app.call_testing.clock = lambda: clock[0]
    return SimpleNamespace(app=app, module=module, helper=helper, policy=policy, clock=clock)


async def rpc(setup, event, data=None, sid="owner"):
    return await setup.app.sio.handlers["/"][event](sid, {} if data is None else data)


async def prepare(setup):
    value = fixture_profile().model_copy(
        update={"controls_confirmed": False, "route_confirmed": False}
    )
    response = await rpc(setup, "call_test_prepare", {"profile": value.model_dump()})
    assert response["ok"], response
    return response["draft"]


async def accepted_fixture(setup):
    from calls.testing import profile_digest

    setup.policy.write_text(
        json.dumps({"format": 1, "enabled": True, "channels": ["sim", "whatsapp_personal"]})
    )
    draft = await prepare(setup)
    owner, project = setup.app.call_testing.context("owner")
    stored = setup.app.call_testing.load(owner, project)
    proof = CapturedEvidence(
        str(uuid.uuid4()),
        setup.app.call_admission.scope(owner, project),
        draft["revision"],
        profile_digest(
            fixture_profile().model_copy(
                update={"controls_confirmed": False, "route_confirmed": False}
            )
        ),
        stored["source_sha256"],
        hashlib.sha256(setup.helper.read_bytes()).hexdigest(),
        100,
        700,
        CHECKS,
    )
    collector = SimpleNamespace(proof=proof)
    collector.current = lambda *_: collector.proof
    setup.app.call_testing.collector = collector
    return draft, collector


def arm_args(draft, review, identifier=None):
    return {
        "revision": draft["revision"],
        "review_id": review["review_id"],
        "request_id": identifier or str(uuid.uuid4()),
        "confirmation": "ANSWER ONE CONTROLLED TEST CALL",
    }


@pytest.mark.asyncio
async def test_default_policy_no_collector_cannot_mint_review_or_start_worker(setup):
    setup.app.call_admission.supervisor_factory = lambda: pytest.fail("No physical acceptance")
    draft = await prepare(setup)
    state = await rpc(setup, "call_test_state")
    assert state["ok"] and not state["ready"] and not state["policy_enabled"]
    assert {"policy_disabled", "evidence_missing"} <= set(state["blockers"])
    assert state["unattended_enabled"] is False
    assert "executable" not in json.dumps(state) and "capture_endpoint" not in json.dumps(state)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    assert (
        not review["ready"] and review["review_id"] is None and not setup.app.call_testing.reviews
    )
    args = {
        "revision": draft["revision"],
        "review_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "confirmation": "ANSWER ONE CONTROLLED TEST CALL",
    }
    assert (await rpc(setup, "call_test_arm", args))["code"] == "call_test_review"
    assert not setup.app.resources.reservations


@pytest.mark.asyncio
async def test_imported_flags_and_proof_payloads_cannot_verify_routes(setup):
    assert (await rpc(setup, "call_test_prepare", {"profile": fixture_profile().model_dump()}))[
        "code"
    ] == "call_test_claimed_proof"
    for event in ("call_test_state", "call_test_prepare", "call_test_review", "call_test_arm"):
        value = await rpc(
            setup,
            event,
            {"physical_verified": True, "policy_enabled": True, "proof": {"checks": list(CHECKS)}},
        )
        assert not value["ok"] and value["code"] == "invalid_arguments"
    assert setup.app.call_testing.collector is None and not setup.app.call_admission.active


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["foreign", "resident", "workspace", "missing"])
async def test_non_owner_renderers_cannot_prepare_or_arm(setup, role):
    if role != "missing":
        setup.app.sessions.accept(
            role,
            {
                "client_id": str(uuid.uuid4())
                if role == "foreign"
                else setup.app.sessions.local_owner,
                "role": "renderer" if role == "foreign" else role,
            },
        )
    for event in (
        "call_test_state",
        "call_test_prepare",
        "call_test_review",
        "call_test_arm",
        "call_test_stop",
    ):
        assert not (await rpc(setup, event, sid=role))["ok"]


@pytest.mark.asyncio
async def test_review_is_exact_origin_bound_one_use_and_starts_only_structured_one_call(setup):
    draft, _ = await accepted_fixture(setup)
    supervisor = ControlledSupervisor()
    setup.app.call_admission.supervisor_factory = lambda: supervisor
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    assert review["ready"] and review["review_id"]
    setup.app.sessions.accept("second", {"client_id": setup.app.sessions.local_owner})
    args = arm_args(draft, review)
    assert (await rpc(setup, "call_test_arm", args, sid="second"))["code"] == "call_test_review"
    assert (await rpc(setup, "call_test_arm", {**args, "confirmation": "yes"}))[
        "code"
    ] == "invalid_arguments"
    armed = await rpc(setup, "call_test_arm", args)
    assert armed["active_id"] == args["request_id"] and not armed["ready"]
    await asyncio.wait_for(supervisor.entered.wait(), 1)
    assert (
        supervisor.bootstrap["voice_mode"] == "local"
        and supervisor.bootstrap["dialogue_mode"] == "structured"
    )
    assert supervisor.bootstrap["arm_seconds"] == 30
    assert (await rpc(setup, "call_test_arm", args))["code"] == "call_test_review"
    assert (await rpc(setup, "call_test_stop", {"id": args["request_id"]}, sid="second"))[
        "code"
    ] == "call_test_origin"
    assert (await rpc(setup, "call_test_stop", {"id": args["request_id"]}))["active_id"] is None
    assert supervisor.closed and not setup.app.resources.reservations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "expired_review",
        "helper",
        "source",
        "proof_scope",
        "proof_revision",
        "proof_checks",
        "proof_expired",
        "policy",
        "resources",
    ],
)
async def test_changed_bindings_refuse_before_worker_and_consume_review(setup, monkeypatch, change):
    draft, collector = await accepted_fixture(setup)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    setup.app.call_admission.supervisor_factory = lambda: pytest.fail(
        "Changed proof must not start"
    )
    if change == "expired_review":
        setup.clock[0] += 61
    elif change == "helper":
        setup.helper.write_bytes(b"different inert helper")
    elif change == "source":
        monkeypatch.setattr(setup.module, "source_digest", lambda: "d" * 64)
    elif change == "proof_scope":
        collector.proof = replace(collector.proof, owner_project_scope="other")
    elif change == "proof_revision":
        collector.proof = replace(collector.proof, revision=str(uuid.uuid4()))
    elif change == "proof_checks":
        collector.proof = replace(collector.proof, checks=frozenset({"controls"}))
    elif change == "proof_expired":
        collector.proof = replace(collector.proof, expires=100)
    elif change == "policy":
        setup.policy.write_text('{"format":1,"enabled":false,"channels":["sim"]}')
    else:
        setup.app.resources.select("gaming")
    result = await rpc(setup, "call_test_arm", arm_args(draft, review))
    assert not result["ok"] and not setup.app.call_admission.active
    assert review["review_id"] not in setup.app.call_testing.reviews
    assert not setup.app.resources.reservations


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "proof", "disconnect", "close", "project"])
async def test_active_lease_rechecks_proof_and_lifecycle_stops(setup, change):
    draft, collector = await accepted_fixture(setup)
    supervisor = ControlledSupervisor()
    setup.app.call_admission.supervisor_factory = lambda: supervisor
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    await rpc(setup, "call_test_arm", arm_args(draft, review))
    task = setup.app.call_admission.active["task"]
    await supervisor.entered.wait()
    if change == "policy":
        setup.policy.write_text('{"format":1,"enabled":false,"channels":["sim"]}')
    elif change == "proof":
        collector.proof = None
    elif change == "disconnect":
        await setup.app.disconnect("owner")
    elif change == "close":
        await setup.app.close()
    else:
        setup.app.projects.create_project("other")
        setup.app.projects.switch_project("other")
    await asyncio.wait_for(task, 1)
    assert (
        supervisor.closed
        and not setup.app.call_admission.active
        and not setup.app.resources.reservations
    )


@pytest.mark.asyncio
async def test_scope_changes_and_restart_cannot_reuse_review_or_proof(setup):
    from calls.testing import ControlledCalls

    draft, _ = await accepted_fixture(setup)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    setup.app.call_testing = ControlledCalls(setup.app)
    assert setup.app.call_testing.collector is None
    assert (await rpc(setup, "call_test_arm", arm_args(draft, review)))[
        "code"
    ] == "call_test_review"
    assert not setup.app.call_admission.active


@pytest.mark.asyncio
async def test_policy_toggle_alone_is_not_physical_acceptance_and_model_flags_refuse(setup):
    setup.policy.write_text('{"format":1,"enabled":true,"channels":["sim","whatsapp_personal"]}')
    draft = await prepare(setup)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    assert review["blockers"] == ["evidence_missing"] and review["review_id"] is None
    draft, _ = await accepted_fixture(setup)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    response = await rpc(
        setup, "call_test_arm", {**arm_args(draft, review), "dialogue_mode": "model"}
    )
    assert response["code"] == "invalid_arguments" and not setup.app.resources.reservations


@pytest.mark.asyncio
async def test_replacing_draft_invalidates_reviews_and_old_physical_capture(setup):
    draft, _ = await accepted_fixture(setup)
    review = await rpc(setup, "call_test_review", {"revision": draft["revision"]})
    replacement = await prepare(setup)
    assert replacement["revision"] != draft["revision"]
    assert not setup.app.call_testing.reviews
    assert "evidence_invalid" in (await rpc(setup, "call_test_state"))["blockers"]
    assert (await rpc(setup, "call_test_arm", arm_args(draft, review)))[
        "code"
    ] == "call_test_review"
