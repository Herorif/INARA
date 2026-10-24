"""Core admission using inert supervisors only; no controls, audio or phone access."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from calls.admission import CallAdmission
from calls.fixture import fixture_profile
from services.tools import ServiceError
from services.usage_contracts import UsagePolicy


@pytest.fixture
def app(application_factory, monkeypatch):
    value = application_factory()
    value.sessions.accept("owner", {"client_id": str(uuid.uuid4())})
    value.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    monkeypatch.setattr("calls.local_voice.ready", lambda: None)
    return value


class ControlledSupervisor:
    last_record_id = None

    def __init__(self):
        self.entered = asyncio.Event()
        self.finish = asyncio.Event()
        self.closed = False

    async def run(self, bootstrap, stop, authorize, **kwargs):
        self.bootstrap, self.options = bootstrap, kwargs
        self.entered.set()
        try:
            while not stop.is_set() and not self.finish.is_set():
                try:
                    authorize()
                except ServiceError:
                    stop.set()
                await asyncio.sleep(0)
            return {"ok": True, "mode": "live", "id": None,
                    "state": "interrupted" if stop.is_set() else "completed", "code": None}
        finally:
            self.closed = True


async def start(app, *, identifier=None, acceptance=lambda profile: True):
    supervisor = ControlledSupervisor()
    app.call_admission.supervisor_factory = lambda: supervisor
    identifier = identifier or uuid.uuid4()
    app.call_admission.start("owner", identifier, fixture_profile(), acceptance_check=acceptance)
    task = app.call_admission.active["task"]
    await asyncio.wait_for(supervisor.entered.wait(), 1)
    return supervisor, identifier, task


def book(app):
    owner, project = app.call_admission.context("owner")
    with app.database.connection() as db:
        return app.database.get(db, app.call_admission.kind, app.call_admission.scope(owner, project))


def test_profile_flags_do_not_grant_physical_acceptance(app):
    app.call_admission.supervisor_factory = lambda: pytest.fail("No worker before acceptance")
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", uuid.uuid4(), fixture_profile())
    assert error.value.code == "call_physical_unverified"
    assert not app.resources.reservations and app.call_admission.active is None
    assert book(app) is None


@pytest.mark.parametrize("change,expected", [("gaming", "resource_policy"), ("resident", "resource_policy"),
                                            ("fault", "resource_fault"), ("capacity", "resource_capacity"),
                                            ("worker", "call_resources_busy")])
def test_readiness_is_truthful_and_never_acquires_resources(app, change, expected):
    if change in {"gaming", "resident"}:
        app.resources.select(change)
    elif change == "fault":
        app.resources.fault = "synthetic fault"
    elif change == "capacity":
        app.resources.capacity["ram_mb"] = 100
    else:
        app.resources.reserve("another", "verification_fixture")
    before = dict(app.resources.reservations)
    value = app.call_admission.availability("owner", components_ready=True)
    assert not value["admission_ready"] and expected in value["blockers"]
    assert not value["live_enabled"] and "call_physical_unverified" in value["blockers"]
    assert app.resources.reservations == before


@pytest.mark.asyncio
async def test_local_call_with_exhausted_cloud_caps_is_zero_cost_and_content_free(app):
    policy = app.usage.snapshot(app.sessions.local_owner)["policy"]
    app.usage.configure(app.sessions.local_owner, UsagePolicy(**{**policy, "enabled": True, "daily_microusd": 0,
                                              "monthly_microusd": 0, "per_call_microusd": 1}))
    supervisor, _, task = await start(app)
    assert app.resources.runner.startswith("local-call:")
    assert supervisor.bootstrap["voice_mode"] == "local"
    assert not {"api_key", "model", "provider"} & supervisor.bootstrap.keys()
    assert supervisor.options["timeout"] == 30 + fixture_profile().max_seconds + 35
    assert len(app.usage.active) == 1
    supervisor.finish.set()
    await asyncio.wait_for(task, 1)
    report = app.usage.snapshot(app.sessions.local_owner)
    receipt = report["records"][0]
    assert receipt["cloud"] is False and receipt["allowance_microusd"] == 0
    assert receipt["state"] == "completed" and receipt["feature"] == "local_call"
    assert not {"caller", "transcript", "profile", "endpoint", "owner"} & receipt.keys()
    assert report["cloud_calls_this_month"] == report["daily_authorized_microusd"] == 0
    assert not app.resources.reservations and not app.usage.active


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["lock", "project", "gaming", "resident", "fault", "disconnect", "close", "acceptance"])
async def test_lifecycle_changes_stop_session_and_release_admission(app, cause):
    accepted = [True]
    supervisor, _, task = await start(app, acceptance=lambda _: accepted[0])
    if cause == "lock":
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    elif cause == "project":
        app.projects.create_project("other")
        app.projects.switch_project("other")
    elif cause in {"gaming", "resident"}:
        app.resources.select(cause)
    elif cause == "fault":
        app.resources.fault = "synthetic"
    elif cause == "disconnect":
        await app.disconnect("owner")
    elif cause == "close":
        await app.close()
    else:
        accepted[0] = False
    await asyncio.wait_for(task, 1)
    assert supervisor.closed and app.call_admission.active is None
    assert not app.resources.reservations and not app.usage.active


@pytest.mark.asyncio
async def test_duplicate_restart_and_concurrent_requests_do_not_start_another_worker(app):
    supervisor, identifier, task = await start(app)
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True)
    assert error.value.code == "call_session_busy"
    # A different workspace's disconnect/stop must not stop this origin.
    await app.call_admission.stop_sid("foreign")
    assert not supervisor.closed
    supervisor.finish.set()
    await asyncio.wait_for(task, 1)
    app.call_admission = CallAdmission(app)
    app.call_admission.supervisor_factory = lambda: pytest.fail("Duplicate cannot replay")
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", identifier, fixture_profile(), acceptance_check=lambda _: True)
    assert error.value.code == "call_duplicate"
    assert not app.resources.reservations and len(book(app)["seen"]) == 1


@pytest.mark.asyncio
async def test_worker_construction_failure_finalizes_usage_and_resources(app):
    def fail():
        raise OSError("inert preparation failure")
    app.call_admission.supervisor_factory = fail
    app.call_admission.start("owner", uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True)
    task = app.call_admission.active["task"]
    await asyncio.wait_for(task, 1)
    assert not app.resources.reservations and not app.usage.active
    assert book(app)["runs"][0]["state"] == "uncertain"
    assert app.usage.snapshot(app.sessions.local_owner)["records"][0]["state"] == "uncertain"


@pytest.mark.asyncio
async def test_busy_creative_worker_refuses_call_without_replay_claim(app):
    app.resources.reserve("creative", "verification_fixture")
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True)
    assert error.value.code == "call_resources_busy"
    assert book(app) is None and set(app.resources.reservations) == {"creative"}


@pytest.mark.asyncio
async def test_standalone_cli_refuses_before_reading_profile_or_launching(app, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/call-bridge.py"
    spec = importlib.util.spec_from_file_location("call_admission_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "profile", lambda _: pytest.fail("No profile access"))
    with pytest.raises(ServiceError) as error:
        await module.run(SimpleNamespace(command="run", profile="not opened", live=True))
    assert error.value.code == "call_core_required"


@pytest.mark.parametrize("sid,role", [("foreign", "renderer"), ("resident", "resident"), ("workspace", "workspace")])
def test_only_current_owner_renderer_can_admit(app, sid, role):
    client = str(uuid.uuid4()) if sid == "foreign" else app.sessions.local_owner
    app.sessions.accept(sid, {"client_id": client, "role": role})
    with pytest.raises(ServiceError):
        app.call_admission.start(sid, uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True)
    assert not app.resources.reservations and not app.usage.active


@pytest.mark.asyncio
async def test_usage_admission_failure_keeps_no_worker_or_reservation_and_does_not_replay(app, monkeypatch):
    def fail(*_):
        raise ServiceError("usage_capacity", "synthetic capacity refusal")
    monkeypatch.setattr(app.usage, "begin_local_call", fail)
    app.call_admission.supervisor_factory = lambda: pytest.fail("No worker after usage refusal")
    identifier = uuid.uuid4()
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", identifier, fixture_profile(), acceptance_check=lambda _: True)
    assert error.value.code == "usage_capacity"
    assert book(app)["runs"][0]["state"] == "uncertain"
    assert not app.resources.reservations and not app.usage.active
    with pytest.raises(ServiceError) as error:
        app.call_admission.start("owner", identifier, fixture_profile(), acceptance_check=lambda _: True)
    assert error.value.code == "call_duplicate"


def test_restart_metadata_marks_running_uncertain_without_resuming(app):
    owner, project = app.call_admission.context("owner")
    identifier = str(uuid.uuid4())
    with app.database.transaction() as db:
        app.database.put(db, app.call_admission.kind, app.call_admission.scope(owner, project),
                         {"seen": [identifier], "runs": [{"id": identifier, "state": "running"}]})
    app.call_admission.supervisor_factory = lambda: pytest.fail("Restart never resumes")
    app.call_admission.availability("owner", components_ready=True)
    assert book(app)["runs"][0]["state"] == "uncertain"
    assert book(app)["runs"][0]["code"] == "core_restarted"


@pytest.mark.asyncio
async def test_call_and_fixture_checks_share_resource_slot(app):
    supervisor, _, task = await start(app)
    value = app.call_lab.state("owner")
    assert value["worker_busy"] and value["admission"]["active"]
    assert not value["admission"]["admission_ready"]
    supervisor.finish.set()
    await asyncio.wait_for(task, 1)
    assert not app.call_lab.state("owner")["admission"]["active"]
