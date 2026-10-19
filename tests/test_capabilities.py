"""R4 admission and lifetime acceptance without a provider, GPU or physical device."""

import asyncio
import sys
import time
import uuid

import pytest
from services.cad import BuildRequest, CadService
from services.resources import ResourceGovernor
from services.storage import Database, StorageError
from services.tools import ServiceError
from services.creative_transport import JobLifetime
from pydantic import ValidationError


def hardware():
    return {"cpu_count": 8, "ram_available_mb": 16000, "ram_total_mb": 32000, "vram_mb": None}


class ControlledProcess:
    def __init__(self, *args):
        self.stopped = self.closed = False

    def alive(self):
        return not self.stopped

    def exit_code(self):
        return 1  # A deliberate crash exercises the failure and release path.

    def close(self):
        self.closed = True


async def until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Job did not settle")


def service(tmp_path, governor=None):
    processes = []

    def factory(*args):
        process = ControlledProcess(*args)
        processes.append(process)
        return process

    governor = governor or ResourceGovernor(probe=hardware)
    instance = CadService(Database(tmp_path / "db"), governor, process_factory=factory)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return instance, {"principal": "owner", "project_path": project}, processes


@pytest.mark.asyncio
async def test_fifo_queue_capacity_crash_and_explicit_release(tmp_path):
    instance, context, processes = service(tmp_path)
    requests = [BuildRequest(name=str(index)) for index in range(4)]
    for args in requests:
        assert (await instance.start(args, context))["state"] == "queued"
    await until(lambda: len(processes) == 1)
    with pytest.raises(ServiceError) as error:
        await instance.start(BuildRequest(), context)
    assert error.value.code == "worker_busy"
    assert len(instance.list("owner", context["project_path"])) == 4
    for index, args in enumerate(requests):
        await until(lambda: len(processes) == index + 1)
        assert instance.governor.runner[1] == str(args.request_id)
        assert all(p.closed for p in processes[:index])
        processes[index].stopped = True
    await until(lambda: not instance.active)
    assert not instance.governor.reservations and instance.governor.runner is None
    assert all(process.closed for process in processes)
    assert all(job["state"] == "failed" for job in instance.list("owner", context["project_path"]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capacity", [{"cpu": 1, "ram_mb": 8192, "vram_mb": 0}, {"cpu": 2, "ram_mb": 100, "vram_mb": 0}]
)
async def test_capacity_rejects_without_claim_or_process(tmp_path, capacity):
    instance, context, processes = service(
        tmp_path, ResourceGovernor(capacity=capacity, probe=hardware)
    )
    with pytest.raises(ServiceError) as error:
        await instance.start(BuildRequest(), context)
    assert error.value.code == "resource_capacity"
    assert not instance.list("owner", context["project_path"])
    assert not instance.governor.reservations and not processes


@pytest.mark.asyncio
async def test_background_is_explicit_scoped_and_cannot_survive_owner_disconnect(tmp_path):
    instance, context, processes = service(tmp_path)
    first, second = BuildRequest(), BuildRequest()
    await instance.start(first, context)
    await instance.start(second, context)
    with pytest.raises(ServiceError):
        await instance.set_background("other", context["project_path"], first.request_id, True)
    with pytest.raises(ServiceError):
        await instance.set_background("owner", tmp_path / "elsewhere", first.request_id, True)
    await instance.set_background("owner", context["project_path"], first.request_id, True)
    await instance.cancel_owner("owner", panel_only=True)
    assert instance.load("owner", context["project_path"], first.request_id)["background"]
    assert (
        instance.load("owner", context["project_path"], second.request_id)["state"] == "cancelled"
    )
    await instance.cancel_owner("owner")
    assert all(p.closed for p in processes)
    assert not instance.governor.reservations


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["gaming", "resident", "close"])
async def test_restriction_cancels_background_and_queue_without_launching_more(tmp_path, action):
    instance, context, processes = service(tmp_path)
    first = BuildRequest()
    await instance.start(first, context)
    await instance.set_background("owner", context["project_path"], first.request_id, True)
    await until(lambda: len(processes) == 1)
    await instance.start(BuildRequest(), context)
    if action != "close":
        instance.governor.select(action)
    await instance.close()
    assert len(processes) == 1 and processes[0].closed
    assert not instance.governor.reservations
    assert all(
        job["state"] == "cancelled" for job in instance.list("owner", context["project_path"])
    )


@pytest.mark.asyncio
async def test_queue_timeout_and_capacity_recheck(tmp_path):
    readings = hardware()
    governor = ResourceGovernor(probe=lambda: dict(readings))
    instance, context, processes = service(tmp_path, governor)
    await instance.start(BuildRequest(), context)
    await until(lambda: len(processes) == 1)
    governor.queue_timeout = 0.01
    waiting = BuildRequest()
    await instance.start(waiting, context)
    await until(
        lambda: (
            instance.load("owner", context["project_path"], waiting.request_id)["state"] == "failed"
        )
    )
    governor.queue_timeout = 120
    waiting = BuildRequest()
    await instance.start(waiting, context)
    readings["ram_available_mb"] = 100
    governor.probed_at = None
    processes[0].stopped = True
    await until(lambda: not instance.active)
    assert len(processes) == 1 and not governor.reservations


@pytest.mark.asyncio
async def test_diagnostics_cheap_private_unknown_and_read_only(application_factory, monkeypatch):
    app = application_factory()
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.sessions.local_owner = "owner"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("INARA_IMAGE_MODEL_DIR", raising=False)
    calls = []
    app.resources.probe = lambda: calls.append(1) or hardware()
    before = set(sys.modules)
    report = await app.capabilities.diagnostics("client", {})
    assert report["ok"]
    cards = {card["id"]: card for card in report["capabilities"]}
    assert cards["text"]["status"] == cards["image_cpu"]["status"] == "setup_required"
    assert not cards["cad_offline"]["verified"]
    assert cards["cad_offline"]["last_duration_seconds"] is None
    assert report["hardware"]["vram_mb"] is None
    assert app.resources.state == "chat"
    assert not app.cad.active and not app.images.active
    app.resources.select("gaming")
    report = await app.capabilities.diagnostics("client", {})
    assert (
        next(c for c in report["capabilities"] if c["id"] == "cad_offline")["status"] == "blocked"
    )
    assert len(calls) == 1
    assert not {"torch", "diffusers", "creative.geometry"} & (set(sys.modules) - before)
    assert not (await app.capabilities.diagnostics("unknown", {}))["ok"]
    assert not (await app.capabilities.diagnostics("client", {"principal": "other"}))["ok"]
    app.sessions.roles["client"] = "resident"
    assert not (await app.capabilities.diagnostics("client", {}))["ok"]


@pytest.mark.parametrize("value", [1, "true", None])
def test_lifetime_requires_actual_boolean(value):
    with pytest.raises(ValidationError):
        JobLifetime(request_id=uuid.uuid4(), background=value)


def test_unsupported_hardware_reports_unknown():
    def unsupported():
        raise OSError("Unavailable")

    governor = ResourceGovernor(probe=unsupported)
    assert all(value is None for value in governor.inspect_hardware().values())


@pytest.mark.asyncio
async def test_suspension_gap_interrupts_owned_worker_and_releases_slot(tmp_path, monkeypatch):
    instance, context, processes = service(tmp_path)
    args = BuildRequest()
    await instance.start(args, context)
    await until(lambda: len(processes) == 1)
    original = instance.governor.poll
    monkeypatch.setattr(instance.governor, "poll", lambda _: original(time.monotonic() - 16))
    await until(lambda: not instance.active)
    assert (
        instance.load("owner", context["project_path"], args.request_id)["state"] == "interrupted"
    )
    assert processes[0].closed and not instance.governor.reservations


@pytest.mark.asyncio
async def test_placeholder_key_is_missing_configuration(application_factory, monkeypatch):
    app = application_factory()
    monkeypatch.setenv("GEMINI_API_KEY", "changeme")
    report = app.capabilities.snapshot({"principal": "owner", "project_path": "."})
    assert (
        next(c for c in report["capabilities"] if c["id"] == "text")["status"] == "setup_required"
    )


@pytest.mark.asyncio
async def test_cross_adapter_fifo_and_cancelled_waiter_do_not_steal_slot(tmp_path):
    from tests.image_support import FixtureImageService
    from services.images import ImageRequest

    cad, context, processes = service(tmp_path)
    image = FixtureImageService(cad.database, cad.governor, process_factory=cad.process_factory)
    await cad.start(BuildRequest(), context)
    await until(lambda: len(processes) == 1)
    cancelled, waiting = ImageRequest(prompt="cancel me"), ImageRequest(prompt="queued image")
    await image.start(cancelled, context)
    await image.start(waiting, context)
    await image.cancel("owner", context["project_path"], cancelled.request_id)
    processes[0].stopped = True
    await until(lambda: len(processes) == 2)
    assert cad.governor.runner[1] == str(waiting.request_id)
    await image.close()
    assert all(p.closed for p in processes) and not cad.governor.reservations


@pytest.mark.asyncio
async def test_close_failure_still_releases_and_blocks_further_admission(tmp_path):
    instance, context, processes = service(tmp_path)
    await instance.start(BuildRequest(), context)
    await until(lambda: len(processes) == 1)

    def broken_close():
        raise OSError("Cannot release process")

    processes[0].close = broken_close
    await instance.close()
    assert not instance.governor.reservations and instance.governor.state == "resident"
    instance.governor.select("studio")
    with pytest.raises(ServiceError) as error:
        instance.governor.require_heavy()
    assert error.value.code == "resource_fault"


def test_success_evidence_and_performance_are_owner_and_profile_scoped(application_factory):
    app = application_factory()
    context = {"principal": "owner", "project_path": app.projects.get_current_project_path()}
    args = BuildRequest()
    app.cad.save(
        "owner",
        context["project_path"],
        {
            "request_id": str(args.request_id),
            "project": context["project_path"].name,
            "recipe": args.model_dump(mode="json", exclude={"request_id"}),
            "created_at": time.time(),
            "state": "succeeded",
            "phase": "ready",
            "resources": {"profile": "cad_offline"},
            "duration_seconds": 1.25,
        },
    )
    report = app.capabilities.snapshot(context)
    card = next(c for c in report["capabilities"] if c["id"] == "cad_offline")
    assert card["verified"] and card["last_duration_seconds"] == 1.25
    other = app.capabilities.snapshot({**context, "principal": "someone-else"})
    assert not next(c for c in other["capabilities"] if c["id"] == "cad_offline")["verified"]


@pytest.mark.asyncio
async def test_external_workflow_lock_does_not_create_unbounded_waiting_claims(tmp_path):
    instance, context, processes = service(tmp_path)
    async with instance.lock:
        with pytest.raises(ServiceError) as error:
            await instance.start(BuildRequest(), context)
    assert error.value.code == "worker_busy"
    assert not instance.governor.reservations and not processes
    assert not instance.list("owner", context["project_path"])


@pytest.mark.asyncio
async def test_lifetime_persistence_failure_preserves_default_cancellation(tmp_path, monkeypatch):
    instance, context, _ = service(tmp_path)
    args = BuildRequest()
    await instance.start(args, context)
    original = instance.save

    def fail_save(*_):
        raise StorageError("storage_failed", "Fixture write failed")

    monkeypatch.setattr(instance, "save", fail_save)
    with pytest.raises(StorageError):
        await instance.set_background("owner", context["project_path"], args.request_id, True)
    monkeypatch.setattr(instance, "save", original)
    await instance.cancel_owner("owner", panel_only=True)
    assert not instance.active and not instance.governor.reservations
    assert not instance.load("owner", context["project_path"], args.request_id)["background"]
