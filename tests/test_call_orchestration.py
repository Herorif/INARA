"""C3a call orchestration: briefing policy, callbacks, budget voicemail, the briefing PIN
secret, the Calls view RPCs and call_progress. No network: Twilio is an httpx mock, the
call agent's Live side is never reached (calls are placed, their results are simulated)."""

import asyncio
import json
import logging
import time
import uuid

import httpx
import pytest

from core.event_bus import Event
from services.settings import SettingsPatch
from telephony import briefs
from telephony.agent import CallHandle, CallResult
from telephony.grants import purpose_hash
from telephony.orchestrator import migrate_briefing_pin, should_brief
from telephony.service import EVENT_CALL_STATUS, EVENT_SESSION

from tests.test_call_agent import (  # noqa: F401  (the phone fixture is used by name)
    ACCOUNT,
    CALLER,
    INARA,
    OWNER,
    OUT_CALL,
    phone,
    until,
)

CALL_SID = "CA" + "c" * 32

LIST_KEYS = {
    "id", "direction", "mode", "counterpart_masked", "name", "started_at", "duration_seconds",
    "urgency", "needs_owner", "summary", "status", "outcome_status",
}
DETAIL_KEYS = LIST_KEYS | {"fields", "triage", "triage_state", "transcript", "outcome", "related_ids"}
ROUTES = ("calls_status", "calls_list", "calls_get", "calls_mark_done", "calls_delete",
          "calls_callback_draft", "calls_callback_approve", "presence_ping")


class Twilio:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        request.read()
        self.requests.append(request)
        return httpx.Response(201, json={"sid": OUT_CALL, "status": "queued"})


def triage(urgency="urgent", needs_owner=True):
    return {"summary": "Aiman called about a parcel.", "urgency": urgency, "needs_owner": needs_owner,
            "suggested_actions": ["Call back about the delivery", "Confirm the gate code"],
            "suggested_reply": "Hi Aiman, Hiro got your message about the parcel. Thank you."}


def save(app, *, urgency="urgent", needs_owner=True, triage_state="done", number=CALLER, **extra):
    now = time.time()
    record = {
        "id": str(uuid.uuid4()), "source": "twilio", "state": "completed",
        "direction": "inbound", "mode": "screening",
        "counterpart": app.call_agent.records.counterpart(number),
        "started_at": now, "finished_at": now, "duration_seconds": 42.0,
        "fields": {"message": {"name": "Aiman", "reason": "Parcel delivery", "urgency": "normal",
                               "callback_number": number or "none",
                               "message": "The parcel is at the gate."}},
        "transcript": [{"role": "assistant", "text": "Hi, you've reached Hiro."},
                       {"role": "caller", "text": "Hello, it's Aiman."}],
        "outcome": {"status": "message_taken"},
        "triage": triage(urgency, needs_owner) if triage_state == "done" else None,
        "triage_state": triage_state,
        **extra,
    }
    app.call_agent.records.save_call(record)
    return record["id"]


def away(app):
    app.call_orchestrator.presence.last -= 600


def emitted(app, name):
    return [call.args[1] for call in app.sio.emit.await_args_list if call.args[0] == name]


class FakeCalls:
    """Stands in for CallAgent.call: records every brief and grant, results on demand."""

    def __init__(self, app, real=False):
        self.app, self.real, self.placed, self.handles = app, app.call_agent.call, [], []
        self.delegate = real

    async def __call__(self, brief, grant=None):
        self.placed.append((brief, grant))
        if self.delegate and brief.mode != "owner_briefing":
            return await self.real(brief, grant)
        future = asyncio.get_running_loop().create_future()
        handle = CallHandle(uuid.uuid4().hex, CALL_SID, future)
        self.handles.append(handle)
        return handle


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, {} if data is None else data)


# --- briefing policy ---------------------------------------------------------------------------


@pytest.mark.parametrize("setting", ["off", "urgent", "needs_owner"])
@pytest.mark.parametrize("urgency,needs", [("urgent", False), ("normal", True), ("low", False)])
@pytest.mark.parametrize("is_away", [True, False])
@pytest.mark.parametrize("quiet", [True, False])
def test_briefing_policy_matrix(setting, urgency, needs, is_away, quiet):
    urgent = urgency == "urgent"
    wanted = {"off": False, "urgent": urgent, "needs_owner": urgent or needs}[setting]
    expected = wanted and is_away and (urgent or not quiet)
    assert should_brief(setting, triage(urgency, needs), away=is_away, quiet=quiet) is expected
    assert should_brief(setting, None, away=True, quiet=False) is False  # no triage, no call


async def test_record_ready_briefs_the_owner_only_when_away(phone):
    app = phone
    calls = app.call_agent.call = FakeCalls(app)
    record_id = save(app)
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": record_id}))
    assert calls.placed == []  # the owner is at the PC: desktop notice only
    away(app)
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": record_id}))
    (brief, grant), = calls.placed
    assert grant is None and brief.mode == "owner_briefing" and brief.counterpart == OWNER
    assert str(brief.briefing.source_record_id) == record_id and brief.owner_name == "Hiro"
    record = app.call_agent.records.get(record_id)
    assert record["briefing"]["state"] == "calling"
    # Delivered again (e.g. a later notice): never a second briefing for the same record.
    await app.bus.emit(Event(type="call_record_ready", data={"record_id": record_id}))
    assert len(calls.placed) == 1
    progress = emitted(app, "call_progress")
    assert progress[-1]["state"] == "dialing" and progress[-1]["mode"] == "owner_briefing"
    assert progress[-1]["record_id"] == record_id and progress[-1]["direction"] == "outbound"


async def test_presence_ping_keeps_the_owner_present_and_no_renderer_means_away(phone):
    app = phone
    presence = app.call_orchestrator.presence
    away(app)
    assert presence.away()
    assert await rpc(app, "presence_ping") == {"ok": True}
    assert not presence.away()
    app.sessions.principals.pop("client")
    assert presence.away()


@pytest.mark.parametrize("setting,urgency,needs,quiet,placed", [
    ("urgent", "normal", True, False, False),
    ("needs_owner", "normal", True, False, True),
    ("needs_owner", "normal", True, True, False),   # quiet hours: only urgent calls
    ("needs_owner", "urgent", False, True, True),
    ("urgent", "urgent", False, True, True),
    ("off", "urgent", True, False, False),
])
async def test_briefing_settings_and_quiet_hours(phone, setting, urgency, needs, quiet, placed):
    app = phone
    calls = app.call_agent.call = FakeCalls(app)
    app.settings["calls"]["brief_by_phone"] = setting
    if quiet:
        app.settings["calls"]["quiet_hours"] = {"start": "00:00", "end": "23:59"}
        app.call_orchestrator.telephony.limits.local_now = lambda: __import__("datetime").datetime(
            2026, 11, 4, 12, 0)
    away(app)
    record_id = save(app, urgency=urgency, needs_owner=needs)
    assert await app.call_orchestrator.consider_briefing(record_id) is placed
    assert len(calls.placed) == int(placed)


async def test_briefing_needs_calls_on_a_screening_record_and_triage(phone):
    app = phone
    calls = app.call_agent.call = FakeCalls(app)
    away(app)
    pending = save(app, triage_state="pending")
    assert not await app.call_orchestrator.consider_briefing(pending)
    briefing = save(app, mode="owner_briefing", direction="outbound")
    assert not await app.call_orchestrator.consider_briefing(briefing)
    app.settings["calls"]["enabled"] = False
    assert not await app.call_orchestrator.consider_briefing(save(app))
    assert calls.placed == []


# --- callbacks after a voice decision ------------------------------------------------------------


def approved(record_id, number=CALLER):
    return briefs.CallBrief(mode="approved_callback", direction="outbound", counterpart=number,
                            owner_name="Hiro", message="Hiro will collect it tonight.",
                            caller_name="Aiman", source_record_id=record_id)


async def test_voice_confirmed_callback_is_placed_promptly_and_linked(phone):
    app = phone
    twilio = Twilio()
    app.telephony.client.transport = httpx.MockTransport(twilio)
    calls = app.call_agent.call = FakeCalls(app, real=True)
    away(app)
    record_id = save(app)
    assert await app.call_orchestrator.consider_briefing(record_id)
    (_brief, _), = calls.placed
    callback = approved(record_id)
    grant = app.telephony.grants.issue(callback.counterpart, callback.purpose())
    briefing_record = save(app, mode="owner_briefing", direction="outbound", number=OWNER)
    calls.handles[0].result.set_result(CallResult(
        briefing_record, "owner_briefing", "outbound", "completed", {"status": "callback"},
        {"decision": {"action": "callback", "message_for_caller": callback.message}}, 30.0,
        callback=(callback, grant),
    ))
    await until(lambda: len(calls.placed) == 2)
    brief, used = calls.placed[1]
    assert brief is callback and used is grant
    await until(lambda: len(twilio.requests) == 1)
    assert grant.consumed
    record = app.call_agent.records.get(record_id)
    assert record["briefing"]["state"] == "completed" and record["briefing"]["decision"] == "callback"
    assert record["callback"]["state"] == "calling" and briefing_record in record["related_ids"]
    assert record_id in app.call_agent.records.get(briefing_record)["related_ids"]
    item = (await rpc(app, "calls_get", {"id": record_id}))["call"]
    assert item["status"] == "in_progress" and item["related_ids"] == [briefing_record]


async def test_blocked_voice_callback_is_marked_and_notified_never_dropped(phone):
    app = phone
    twilio = Twilio()
    app.telephony.client.transport = httpx.MockTransport(twilio)
    record_id = save(app)
    app.settings["calls"]["quiet_hours"] = {"start": "00:00", "end": "23:59"}
    app.telephony.limits.local_now = lambda: __import__("datetime").datetime(2026, 11, 4, 12, 0)
    callback = approved(record_id)
    grant = app.telephony.grants.issue(callback.counterpart, callback.purpose())
    handle, code, _ = await app.call_orchestrator._place_callback(
        record_id, callback, grant, origin="voice")
    assert handle is None and code == "quiet_hours" and twilio.requests == []
    assert not grant.consumed and grant.id not in app.telephony.grants.grants  # revoked
    record = app.call_agent.records.get(record_id)
    assert record["callback"]["state"] == "blocked" and record["callback"]["reason"] == "quiet_hours"
    assert {"record_id": record_id} in emitted(app, "call_record_ready")
    summary = (await rpc(app, "calls_list", {"filter": "needs_you"}))["calls"]
    assert [item["status"] for item in summary if item["id"] == record_id] == ["callback_blocked"]
    detail = (await rpc(app, "calls_get", {"id": record_id}))["call"]
    assert detail["outcome"]["details"] == "Callback not placed: it is quiet hours."
    draft = await rpc(app, "calls_callback_draft", {"id": record_id})
    assert draft == {"ok": True, "message": "Hiro will collect it tonight."}


# --- desktop-approved callbacks --------------------------------------------------------------------


async def test_desktop_approval_issues_a_bound_grant_and_places_once(phone, monkeypatch):
    app = phone
    twilio = Twilio()
    app.telephony.client.transport = httpx.MockTransport(twilio)
    app.call_agent._preflight = lambda: None
    record_id = save(app)
    issued = []
    original = app.telephony.grants.issue

    def issue(number, purpose, ttl=600.0):
        grant = original(number, purpose, ttl)
        issued.append((number, purpose, grant))
        return grant

    monkeypatch.setattr(app.telephony.grants, "issue", issue)
    result = await rpc(app, "calls_callback_approve", {"id": record_id, "message": "On my way."})
    assert result["ok"] is True and isinstance(result["call_id"], str)
    (number, purpose, grant), = issued
    expected = briefs.CallBrief(mode="approved_callback", direction="outbound", counterpart=CALLER,
                                owner_name="Hiro", message="On my way.", caller_name="Aiman",
                                source_record_id=record_id)
    assert number == CALLER and purpose == expected.purpose()
    assert grant.purpose_hash == purpose_hash(expected.purpose()) and grant.consumed
    assert len(twilio.requests) == 1
    form = dict(httpx.QueryParams(twilio.requests[0].content.decode()))
    assert form["To"] == CALLER and form["From"] == INARA
    # The same record cannot be called back twice while the first callback runs.
    again = await rpc(app, "calls_callback_approve", {"id": record_id, "message": "On my way."})
    assert again["ok"] is False and again["code"] == "busy" and len(twilio.requests) == 1
    assert app.call_agent.records.get(record_id)["callback"]["state"] == "calling"


@pytest.mark.parametrize("case,code", [
    ("disabled", "calls_disabled"),
    ("no_number", "no_callback_number"),
    ("quiet", "quiet_hours"),
    ("cap", "daily_cap"),
    ("cooldown", "cooldown"),
    ("not_ready", "not_ready"),
])
async def test_desktop_approval_refusals(phone, case, code):
    app = phone
    twilio = Twilio()
    app.telephony.client.transport = httpx.MockTransport(twilio)
    record_id = save(app, number=None if case == "no_number" else CALLER)
    calls = app.settings["calls"]
    if case == "disabled":
        calls["enabled"] = False
    elif case == "quiet":
        calls["quiet_hours"] = {"start": "00:00", "end": "23:59"}
        app.telephony.limits.local_now = lambda: __import__("datetime").datetime(2026, 11, 4, 12, 0)
    elif case == "cap":
        calls["daily_outbound_cap"] = 0
    elif case == "cooldown":
        calls["number_cooldown_minutes"] = 60
        app.telephony.limits.record(CALLER)
    elif case == "not_ready":
        app.secrets.values.pop("twilio_auth_token")
    result = await rpc(app, "calls_callback_approve", {"id": record_id, "message": "Hello."})
    assert result["ok"] is False and result["code"] == code and isinstance(result["message"], str)
    assert twilio.requests == [] and not app.telephony.grants.grants


# --- budget exhausted: voicemail ------------------------------------------------------------------


def exhaust_budget(app):
    usage = app.usage
    with app.database.transaction() as db:
        key, policy = usage.load(db, "owner")
        policy.update(enabled=True, daily_microusd=0, monthly_microusd=0, per_call_microusd=1)
        app.database.put(db, usage.policy_kind, key, policy)


async def test_budget_exhausted_inbound_call_gets_voicemail_and_a_minimal_record(phone):
    app = phone
    params = {"CallSid": CALL_SID, "From": CALLER, "To": INARA, "AccountSid": ACCOUNT}
    assert b"<Connect>" in app.telephony.inbound_twiml(params)  # budget fine: screened
    exhaust_budget(app)
    body = app.telephony.inbound_twiml({**params, "CallSid": "CA" + "d" * 32}).decode()
    assert "<Record" in body and "<Connect>" not in body
    await until(lambda: not app.call_agent.tasks)
    record = next(item for item in app.call_agent.records.phone_calls())
    assert record["state"] == "missed" and record["outcome"] == {"status": "missed", "reason": "budget"}
    assert record["triage_state"] == "skipped" and record["transcript"] == []
    assert record["counterpart"]["masked"] == "+60 19-•••• 5432"
    assert {"record_id": record["id"]} in emitted(app, "call_record_ready")
    item = (await rpc(app, "calls_list", {"filter": "all"}))["calls"][0]
    assert item["id"] == record["id"] and item["outcome_status"] == "missed"
    # A missed call needs the owner until it is marked done.
    assert item["status"] == "needs_you"
    needs = (await rpc(app, "calls_list", {"filter": "needs_you"}))["calls"]
    assert [entry["id"] for entry in needs] == [record["id"]]
    assert (await rpc(app, "calls_status"))["calls"]["needs_you_count"] == 1
    assert await rpc(app, "calls_mark_done", {"id": record["id"]}) == {"ok": True}
    assert (await rpc(app, "calls_list", {"filter": "needs_you"}))["calls"] == []
    assert (await rpc(app, "calls_list", {"filter": "done"}))["calls"][0]["id"] == record["id"]
    assert (await rpc(app, "calls_status"))["calls"]["needs_you_count"] == 0


@pytest.mark.parametrize("direction,mode,state,status,needs", [
    ("inbound", "screening", "failed", "needs_you", True),       # the agent failed: missed
    ("inbound", "screening", "uncertain", "needs_you", True),
    ("outbound", "approved_callback", "failed", "failed", False),  # INARA's own call failed
    ("outbound", "task", "failed", "failed", False),
])
async def test_missed_incoming_calls_need_the_owner_and_failed_outbound_calls_fail(
    phone, direction, mode, state, status, needs
):
    app = phone
    record_id = save(app, direction=direction, mode=mode, state=state, triage_state="skipped")
    item = next(entry for entry in (await rpc(app, "calls_list", {"filter": "all"}))["calls"]
                if entry["id"] == record_id)
    assert item["status"] == status
    needs_you = [entry["id"] for entry in (await rpc(app, "calls_list", {"filter": "needs_you"}))["calls"]]
    assert (record_id in needs_you) is needs


# --- the briefing PIN secret -----------------------------------------------------------------------


async def test_briefing_pin_migrates_to_the_secret_store_and_is_never_returned(
    application_factory, tmp_path, caplog
):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "settings.json"
    settings = {"face_auth_enabled": False, "tool_permissions": {}, "kasa_devices": [],
                "calls": {"enabled": False, "briefing_pin": "2468"}}
    path.write_text(json.dumps(settings), encoding="utf-8")
    app = application_factory(settings=settings, settings_path=path)
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner"})
    app.sessions.roles.update({"client": "renderer"})
    assert migrate_briefing_pin(app) is True
    assert app.secrets.get("call_briefing_pin") == "2468"
    assert "briefing_pin" not in app.settings["calls"]
    assert "2468" not in path.read_text(encoding="utf-8")
    assert app.call_agent.briefing_pin() == "2468"
    status = await rpc(app, "calls_status")
    assert status["ok"] and status["calls"]["briefing_pin_set"] is True
    secrets = await rpc(app, "secrets_status")
    pin = next(item for item in secrets["secrets"] if item["name"] == "call_briefing_pin")
    assert pin["configured"] is True and pin["hint"] is None
    assert "2468" not in json.dumps(status) + json.dumps(secrets) and "2468" not in caplog.text
    assert migrate_briefing_pin(app) is False  # nothing left to move
    with pytest.raises(Exception):
        SettingsPatch.model_validate({"calls": {"briefing_pin": "1357"}})
    refused = await rpc(app, "update_settings", {"calls": {"briefing_pin": "1357"}})
    assert refused == {"ok": False, "code": "invalid_arguments"}
    assert "1357" not in json.dumps([call.args for call in app.sio.emit.await_args_list])


async def test_an_existing_secret_wins_and_start_runs_the_migration(application_factory, tmp_path):
    settings = {"face_auth_enabled": False, "tool_permissions": {}, "kasa_devices": [],
                "calls": {"briefing_pin": "1111"}}
    app = application_factory(settings=settings, settings_path=tmp_path / "settings.json")
    app.secrets.set("call_briefing_pin", "9999")
    await app.start()
    try:
        assert app.secrets.get("call_briefing_pin") == "9999"
        assert "briefing_pin" not in app.settings["calls"]
    finally:
        await app.close()


# --- RPC contract ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ROUTES)
@pytest.mark.parametrize("sid,code", [("unknown", "authentication_required"),
                                      ("tray", "authentication_required"),
                                      ("second", "permission_denied"),
                                      ("locked", "authentication_required")])
async def test_every_calls_route_is_owner_renderer_only(phone, name, sid, code):
    app = phone
    app.sessions.principals.update({"tray": "owner", "second": "other"})
    app.sessions.roles.update({"tray": "resident", "second": "renderer"})
    record_id = save(app)
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    data = {"id": record_id, "message": "Hi.", "filter": "all"}
    data = {key: data[key] for key in {
        "calls_list": ("filter",), "calls_callback_approve": ("id", "message"),
        "calls_status": (), "presence_ping": (),
    }.get(name, ("id",))}
    result = await rpc(app, name, data, sid)
    assert result["ok"] is False and result["code"] == code
    assert app.call_agent.records.get(record_id) is not None


async def test_list_and_get_shapes_are_exact_and_numbers_masked(phone):
    app = phone
    urgent = save(app)
    calm = save(app, urgency="low", needs_owner=False)
    for bad in ({"filter": "everything"}, {"filter": "all", "limit": 0}, {"filter": "all", "limit": 101},
                {"filter": "all", "extra": 1}, {}):
        assert (await rpc(app, "calls_list", bad))["code"] == "invalid_arguments"
    listed = await rpc(app, "calls_list", {"filter": "all"})
    assert listed["ok"] and {item["id"] for item in listed["calls"]} == {urgent, calm}
    item = next(item for item in listed["calls"] if item["id"] == urgent)
    assert set(item) == LIST_KEYS
    assert item["direction"] == "inbound" and item["mode"] == "screening"
    assert item["counterpart_masked"] == "+60 19-•••• 5432" and item["name"] == "Aiman"
    assert item["started_at"].endswith("+00:00") and item["duration_seconds"] == 42.0
    assert item["urgency"] == "urgent" and item["needs_owner"] is True and item["status"] == "needs_you"
    assert item["summary"] == "Aiman called about a parcel." and item["outcome_status"] == "message_taken"
    needs = await rpc(app, "calls_list", {"filter": "needs_you", "limit": 1})
    assert [entry["id"] for entry in needs["calls"]] == [urgent]
    done = await rpc(app, "calls_list", {"filter": "done"})
    assert [entry["id"] for entry in done["calls"]] == [calm]
    detail = (await rpc(app, "calls_get", {"id": urgent}))["call"]
    assert set(detail) == DETAIL_KEYS
    assert detail["fields"] == {"name": "Aiman", "reason": "Parcel delivery", "urgency": "normal",
                                "callback_number_masked": "+60 19-•••• 5432",
                                "message": "The parcel is at the gate."}
    assert detail["triage"] == {"summary": "Aiman called about a parcel.", "urgency": "urgent",
                                "needs_owner": True, "suggested_actions": [
                                    "Call back about the delivery", "Confirm the gate code"]}
    assert detail["triage_state"] == "done" and detail["related_ids"] == []
    assert detail["transcript"] == [{"role": "inara", "text": "Hi, you've reached Hiro."},
                                    {"role": "caller", "text": "Hello, it's Aiman."}]
    assert detail["outcome"] == {"status": "message_taken", "details": None}
    text = json.dumps([listed, detail])
    assert CALLER not in text and CALLER[1:] not in text and OWNER not in text
    assert (await rpc(app, "calls_get", {"id": str(uuid.uuid4())}))["code"] == "not_found"
    assert (await rpc(app, "calls_get", {"id": "not-a-uuid"}))["code"] == "invalid_arguments"


async def test_owner_briefing_transcripts_name_the_owner(phone):
    app = phone
    record_id = save(app, mode="owner_briefing", direction="outbound", number=OWNER)
    detail = (await rpc(app, "calls_get", {"id": record_id}))["call"]
    assert [segment["role"] for segment in detail["transcript"]] == ["inara", "owner"]
    assert detail["status"] == "done"  # a briefing never waits on the owner itself


async def test_mark_done_delete_and_draft(phone):
    app = phone
    record_id = save(app)
    draft = await rpc(app, "calls_callback_draft", {"id": record_id})
    # The caller-facing suggested_reply, never the owner-facing suggested_actions.
    assert draft == {"ok": True,
                     "message": "Hi Aiman, Hiro got your message about the parcel. Thank you."}
    no_reply = save(app)
    app.call_agent.records.set_triage(no_reply, {**triage(), "suggested_reply": ""}, "done")
    assert (await rpc(app, "calls_callback_draft", {"id": no_reply}))["message"] == ""
    legacy = save(app)  # a triage stored before suggested_reply existed
    old = {key: value for key, value in triage().items() if key != "suggested_reply"}
    app.call_agent.records.set_triage(legacy, old, "done")
    assert (await rpc(app, "calls_callback_draft", {"id": legacy}))["message"] == ""
    for extra in (no_reply, legacy):
        await rpc(app, "calls_mark_done", {"id": extra})
    assert await rpc(app, "calls_mark_done", {"id": record_id}) == {"ok": True}
    item = next(entry for entry in (await rpc(app, "calls_list", {"filter": "done"}))["calls"]
                if entry["id"] == record_id)
    assert item["status"] == "done"
    assert (await rpc(app, "calls_list", {"filter": "needs_you"}))["calls"] == []
    empty = save(app, triage_state="failed")
    assert (await rpc(app, "calls_callback_draft", {"id": empty}))["message"] == ""
    assert await rpc(app, "calls_delete", {"id": record_id}) == {"ok": True}
    assert app.call_agent.records.get(record_id) is None
    assert (await rpc(app, "calls_delete", {"id": record_id}))["code"] == "not_found"
    assert (await rpc(app, "calls_mark_done", {"id": record_id}))["code"] == "not_found"
    long_text = {"id": empty, "message": "x" * 501}
    assert (await rpc(app, "calls_callback_approve", long_text))["code"] == "invalid_arguments"


async def test_calls_status_extension(phone):
    app = phone
    save(app)
    save(app, urgency="low", needs_owner=False)
    status = (await rpc(app, "calls_status"))["calls"]
    assert status["answering"] is True and status["needs_you_count"] == 1
    assert status["active_call"] is None and status["briefing_pin_set"] is False
    assert status["inara_number"] == INARA  # owner-only: the full E.164 number
    app.secrets.values.pop("twilio_phone_number")
    assert (await rpc(app, "calls_status"))["calls"]["inara_number"] is None
    app.secrets.values["twilio_phone_number"] = INARA
    assert "enabled" in status and "ready" in status  # C1 fields are unchanged
    app.secrets.values["call_briefing_pin"] = "4321"
    await app.bus.emit(Event(type=EVENT_SESSION, data={
        "call_sid": CALL_SID, "direction": "inbound", "state": "opened", "call_id": None}))
    status = (await rpc(app, "calls_status"))["calls"]
    assert status["briefing_pin_set"] is True and "4321" not in json.dumps(status)
    assert set(status["active_call"]) == {"id", "mode", "direction", "state"}
    assert status["active_call"]["mode"] == "screening" and status["active_call"]["state"] == "in_progress"


# --- call_progress ---------------------------------------------------------------------------------


async def test_call_progress_events_follow_twilio_and_the_stream(phone):
    app = phone
    call_id = uuid.uuid4().hex
    app.telephony.outbound[call_id] = {"purpose": f"{briefs.PURPOSE_PREFIX}:task:{'0' * 64}"}
    for status in ("initiated", "ringing", "in-progress", "ringing", "completed", "completed"):
        await app.bus.emit(Event(type=EVENT_CALL_STATUS, data={"call_id": call_id, "status": status}))
    states = [item["state"] for item in emitted(app, "call_progress")]
    assert states == ["dialing", "ringing", "in_progress", "completed"]
    assert all("message" not in item for item in emitted(app, "call_progress"))  # only failures
    payload = emitted(app, "call_progress")[0]
    assert payload == {"call_id": call_id, "record_id": None, "mode": "task",
                       "direction": "outbound", "state": "dialing"}
    other = uuid.uuid4().hex
    await app.bus.emit(Event(type=EVENT_CALL_STATUS, data={"call_id": other, "status": "no-answer"}))
    assert emitted(app, "call_progress")[-1]["state"] == "no_answer"
    assert emitted(app, "call_progress")[-1]["message"] == "No one answered."
    for status, state, text in (("busy", "no_answer", "The line was busy."),
                                ("failed", "failed", "The call could not be connected."),
                                ("canceled", "no_answer",
                                 "The call was cancelled before anyone answered.")):
        call_id = uuid.uuid4().hex
        await app.bus.emit(Event(type=EVENT_CALL_STATUS, data={"call_id": call_id, "status": status}))
        last = emitted(app, "call_progress")[-1]
        assert last["call_id"] == call_id and last["state"] == state and last["message"] == text
        assert set(last) == {"call_id", "record_id", "mode", "direction", "state", "message"}
        assert len(last["message"]) <= 200
    app.sio.emit.reset_mock()
    for state in ("opened", "closed"):
        await app.bus.emit(Event(type=EVENT_SESSION, data={
            "call_sid": CALL_SID, "direction": "inbound", "state": state, "call_id": None}))
    inbound = emitted(app, "call_progress")
    assert [item["state"] for item in inbound] == ["in_progress", "completed"]
    assert inbound[0]["direction"] == "inbound" and inbound[0]["mode"] == "screening"
    assert inbound[0]["call_id"] == inbound[1]["call_id"] and CALL_SID not in json.dumps(inbound)
    assert all(call.kwargs["room"] == "client" for call in app.sio.emit.await_args_list)
    assert (await rpc(app, "calls_status"))["calls"]["active_call"] is None


async def test_session_events_come_from_the_gateway_service(phone):
    app = phone
    seen = []

    async def collect(event):
        seen.append(event.data)

    app.bus.on(EVENT_SESSION, collect)

    class Session:
        call_sid, direction, end_reason = CALL_SID, "outbound", "stopped"
        info = {"call_id": "abc", "purpose": "p"}

    app.telephony.session_opened(Session())
    app.telephony.session_closed(Session())
    await until(lambda: len(seen) == 2)
    assert [item["state"] for item in seen] == ["opened", "closed"]
    assert seen[0] == {"call_sid": CALL_SID, "direction": "outbound", "state": "opened",
                       "call_id": "abc", "purpose": "p"}


# --- triage: suggested_reply -------------------------------------------------------------------


def test_triage_suggested_reply_is_validated():
    from pydantic import ValidationError

    from telephony import triage as triage_module

    base = {"summary": "Aiman called.", "urgency": "normal", "needs_owner": True}
    assert "suggested_reply" in triage_module.SYSTEM and "300" in triage_module.SYSTEM
    missing = triage_module.parse(json.dumps(base))
    assert missing.suggested_reply == ""  # missing means no reply
    clean = triage_module.parse(json.dumps({**base, "suggested_reply": " Hi Aiman,\n\tthanks. "}))
    assert clean.suggested_reply == "Hi Aiman, thanks."
    long_reply = " ".join(["word"] * 100)  # 499 characters: cut at a word boundary
    cut = triage_module.parse(json.dumps({**base, "suggested_reply": long_reply})).suggested_reply
    assert len(cut) <= 300 and cut.endswith("word") and long_reply.startswith(cut)
    for bad in ("x" * 601, 42, None, ["Hi"]):
        with pytest.raises((ValidationError, ValueError)):
            triage_module.parse(json.dumps({**base, "suggested_reply": bad}))
    stored = triage_module.parse(json.dumps({**base, "suggested_reply": "Hi."})).model_dump()
    assert stored["suggested_reply"] == "Hi." and stored["suggested_actions"] == []
