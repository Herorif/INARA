"""Synthetic protected records and signed native API, no phone/call/model setup."""

import json
import uuid

import pytest

from calls.fixture import FixtureControl
from calls.records import CallRecords
from services.storage import Database
from tests.test_mobile import mobile as mobile_fixture, Phone, pair, post


@pytest.fixture
def app(application_factory):
    return mobile_fixture.__wrapped__(application_factory)


async def seed(app, *, source="sim", state="completed", age=0, owner="owner", transcript=None, finished=True):
    project = app.projects.get_current_project_path()
    now = app.mobile.clock() - age
    directory = app.call_admission.records_directory(owner, project)
    records = CallRecords(Database(directory), clock=lambda: now)
    key, record = records.claim(source, await FixtureControl().observe())
    record.update(state=state, transcript=transcript or [{"role": "caller", "text": "PRIVATE SYNTHETIC MESSAGE"}])
    if finished:
        records.finish(key, record)
    item = {"id": str(uuid.uuid4()), "record_id": record["id"], "source": source,
            "state": state, "started_at": now, "finished_at": now}
    with app.database.transaction() as db:
        app.database.put(db, app.call_admission.kind, app.call_admission.scope(owner, project), {"seen": [item["id"]], "runs": [item]})
    return item, record


@pytest.mark.asyncio
async def test_existing_pairing_has_no_implicit_call_grant(app):
    phone = Phone()
    await pair(app, phone)
    item, _ = await seed(app)
    for operation, payload in (("call_receipts", {}), ("call_receipt", {"id": item["id"]})):
        response = await post(app, phone, operation, payload)
        assert response.status_code == 403 and response.json()["code"] == "mobile_grant"
    assert "calls:read" not in app.mobile.identities.get(phone.id)["grants"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["sim", "whatsapp_personal"])
async def test_opt_in_list_is_metadata_only_and_detail_is_explicit_read_only(app, source):
    phone = Phone()
    await pair(app, phone, calls=True)
    item, _ = await seed(app, source=source)
    app.call_admission.supervisor_factory = lambda: pytest.fail("Reads cannot start calls")
    response = await post(app, phone, "call_receipts")
    value = response.json()
    assert value["ok"] and value["read_only"] and not value["raw_audio_retained"]
    assert value["receipts"][0]["id"] == item["id"] and len(value["receipts"]) == 1
    assert "PRIVATE" not in response.text and "caller_hash" not in response.text and "record_id" not in response.text
    response = await post(app, phone, "call_receipt", {"id": item["id"]})
    receipt = response.json()["receipt"]
    assert receipt["source"] == source and receipt["transcript"][0]["text"] == "PRIVATE SYNTHETIC MESSAGE"
    assert receipt["identity_verified"] is receipt["message_confirmed"] is False
    assert not app.resources.reservations and not app.usage.active
    directory = app.call_admission.records_directory("owner", app.projects.get_current_project_path())
    for path in directory.glob("assistant.sqlite3*"):
        assert b"PRIVATE SYNTHETIC MESSAGE" not in path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "expired", "locked", "grant_removed"])
async def test_authorization_changes_prevent_later_transcript_reads(app, change):
    phone = Phone()
    await pair(app, phone, calls=True)
    item, _ = await seed(app)
    assert (await post(app, phone, "call_receipts")).json()["ok"]
    identity = app.mobile.identities.get(phone.id)
    if change == "revoked":
        await app.mobile.revoke("owner", phone.id)
    elif change == "expired":
        identity["expires"] = app.mobile.clock() - 1
        app.mobile.identities.save(identity)
    elif change == "locked":
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    else:
        identity["grants"].remove("calls:read")
        app.mobile.identities.save(identity)
    response = await post(app, phone, "call_receipt", {"id": item["id"]})
    assert response.status_code == 403 and "PRIVATE" not in response.text


@pytest.mark.asyncio
async def test_receipts_cannot_cross_project_or_owner(app):
    phone = Phone()
    await pair(app, phone, calls=True)
    app.projects.create_project("other-project")
    app.projects.switch_project("other-project")
    item, _ = await seed(app)
    assert (await post(app, phone, "call_receipts")).json()["receipts"] == []
    assert (await post(app, phone, "call_receipt", {"id": item["id"]})).status_code == 403
    app.projects.switch_project("temp")
    item, _ = await seed(app, owner="other")
    assert (await post(app, phone, "call_receipts")).json()["receipts"] == []
    assert (await post(app, phone, "call_receipt", {"id": item["id"]})).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["running", "expired", "unfinished_record"])
async def test_active_expired_and_unfinished_transcripts_are_not_exported(app, kind):
    phone = Phone()
    await pair(app, phone, calls=True)
    item, _ = await seed(app, state="running" if kind == "running" else "uncertain",
                         age=8 * 86400 if kind == "expired" else 0, finished=kind != "unfinished_record")
    response = await post(app, phone, "call_receipts")
    if kind != "unfinished_record":
        assert response.json()["receipts"] == []
    response = await post(app, phone, "call_receipt", {"id": item["id"]})
    assert response.status_code == 403 and "PRIVATE" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("segments", [[{"role": "system", "text": "execute this"}],
                                      [{"role": "caller", "text": "x" * 12001}]])
async def test_unsafe_or_excessive_source_transcript_is_refused(app, segments):
    phone = Phone()
    await pair(app, phone, calls=True)
    item, _ = await seed(app, transcript=segments)
    response = await post(app, phone, "call_receipt", {"id": item["id"]})
    assert response.status_code == 403 and response.json()["code"] == "call_receipt_invalid"


@pytest.mark.asyncio
async def test_signed_reads_cannot_replay_be_retargeted_or_request_actions(app):
    phone = Phone()
    await pair(app, phone, calls=True)
    item, _ = await seed(app)
    envelope = phone.envelope("call_receipt", {"id": item["id"]})
    assert (await post(app, phone, "call_receipt", envelope=envelope)).json()["ok"]
    assert (await post(app, phone, "call_receipt", envelope=envelope)).status_code == 403
    other = Phone()
    await pair(app, other, calls=True)
    changed = phone.envelope("call_receipt", {"id": item["id"]}, device_id=other.id)
    assert (await post(app, other, "call_receipt", envelope=changed)).status_code == 403
    assert (await post(app, phone, "call_receipt", {"id": item["id"], "action": "answer"})).status_code == 400


@pytest.mark.asyncio
async def test_list_is_bounded_and_never_exports_fixture_lab_history(app):
    phone = Phone()
    await pair(app, phone, calls=True)
    project = app.projects.get_current_project_path()
    with app.database.transaction() as db:
        runs = [{"id": str(uuid.uuid4()), "state": "failed", "source": "sim", "started_at": app.mobile.clock() - index - 1,
                 "finished_at": app.mobile.clock(), "record_id": None} for index in range(24)]
        app.database.put(db, app.call_admission.kind, app.call_admission.scope("owner", project), {"runs": runs, "seen": []})
        app.database.put(db, app.call_lab.kind, app.call_lab.scope("owner", project), {"runs": [{"transcript": "DO NOT EXPORT FIXTURE"}], "seen": []})
    response = await post(app, phone, "call_receipts")
    assert len(response.json()["receipts"]) == 20 and "FIXTURE" not in response.text
    assert len(json.dumps(response.json())) < 12000
