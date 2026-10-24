"""Read-only recipe handoffs and durable, revalidated provenance; no paid models."""

import hashlib
import json
import uuid
from unittest.mock import AsyncMock
import pytest
from services.cad import Recipe, BuildRequest
from services.images import ImageRecipe
from services.handoff_contracts import CreativeReference
from services.tools import ServiceError
from tests.test_cad_jobs import finish


@pytest.fixture
def prepared(application_factory):
    app = application_factory()
    app.sessions.accept("ui", {"client_id": str(uuid.uuid4())})
    owner = app.sessions.local_owner
    project = app.projects.get_current_project_path()
    app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    for kind, recipe in [
        ("cad", Recipe(name="Base plate").model_dump()),
        (
            "image",
            ImageRecipe(
                name="Amber study", prompt="A ceramic organiser with amber accents"
            ).model_dump(),
        ),
    ]:
        identifier = str(uuid.uuid4())
        directory = f"fixtures/{kind}"
        folder = project / directory
        folder.mkdir(parents=True)
        raw = json.dumps(recipe).encode()
        (folder / "model.json").write_bytes(raw)
        service = app.cad if kind == "cad" else app.images
        service.save(
            owner,
            project,
            {
                "request_id": identifier,
                "project": project.name,
                "recipe": recipe,
                "state": "succeeded",
                "phase": "ready",
                "created_at": 1,
                "directory": directory,
                "artifacts": {
                    "json": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                },
            },
        )
    return app


def request(app, kind="cad", destination="image"):
    value = (app.cad if kind == "cad" else app.images).list(
        app.sessions.local_owner, app.projects.get_current_project_path()
    )[0]
    return {
        "source_kind": kind,
        "source_request_id": value["request_id"],
        "source_fingerprint": value["recipe_fingerprint"],
        "destination": destination,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,destination", [("cad", "image"), ("image", "cad"), ("cad", "cad"), ("image", "image")]
)
async def test_read_only_handoff_preserves_source_and_never_starts_adapters(
    prepared, kind, destination
):
    app = prepared
    app.cad.process_factory = app.images.process_factory = lambda *_: pytest.fail(
        "No worker during handoff"
    )
    app.cad_transport.scene_planner = AsyncMock()
    args = request(app, kind, destination)
    result = await app.sio.handlers["/"]["creative_handoff"]("ui", args)
    assert result["ok"], result
    draft = result["draft"]
    assert (
        draft["metadata_only"]
        and draft["destination"] == destination
        and len(draft["prompt"]) <= 2000
    )
    assert draft["reference"]["source_fingerprint"] == args["source_fingerprint"]
    assert not app.cad.active and not app.images.active and not app.resources.reservations
    app.cad_transport.scene_planner.assert_not_called()
    assert (
        len(
            (app.cad if kind == "cad" else app.images).list(
                app.sessions.local_owner, app.projects.get_current_project_path()
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_owner_project_roles_lock_and_strict_source_gate(prepared):
    app = prepared
    route = app.sio.handlers["/"]["creative_handoff"]
    args = request(app)
    for role in ("resident", "workspace"):
        app.sessions.accept(role, {"client_id": app.sessions.local_owner, "role": role})
        assert not (await route(role, args))["ok"]
    app.sessions.accept("foreign", {"client_id": str(uuid.uuid4())})
    assert not (await route("foreign", args))["ok"]
    for patch in (
        {"path": "anything"},
        {"source_kind": "camera"},
        {"destination": "whatsapp"},
        {"source_fingerprint": "0" * 64},
        {"source_request_id": str(uuid.uuid4())},
    ):
        assert not (await route("ui", {**args, **patch}))["ok"]
    app.projects.create_project("other")
    app.projects.switch_project("other")
    assert not (await route("ui", args))["ok"]
    app.projects.switch_project("temp")
    app.settings["face_auth_enabled"] = True
    assert not (await route("ui", args))["ok"]


@pytest.mark.asyncio
async def test_edited_source_export_rejects_before_provider_and_worker(prepared):
    app = prepared
    args = request(app, "image", "cad")
    draft = (await app.sio.handlers["/"]["creative_handoff"]("ui", args))["draft"]
    source = app.projects.get_current_project_path() / "fixtures/image/model.json"
    source.write_text("changed")
    assert not (await app.sio.handlers["/"]["creative_handoff"]("ui", args))["ok"]
    app.settings["tool_permissions"]["generate_cad"] = False
    app.cad_transport.scene_planner = AsyncMock()
    result = await app.sio.handlers["/"]["cad_plan"](
        "ui", {"prompt": draft["prompt"], "target": "scene", "reference": draft["reference"]}
    )
    assert not result["ok"]
    app.cad_transport.scene_planner.assert_not_called()
    with pytest.raises(ServiceError):
        await app.cad.start(
            BuildRequest(reference=draft["reference"]),
            {
                "principal": app.sessions.local_owner,
                "project_path": app.projects.get_current_project_path(),
            },
        )
    assert not app.cad.active and not app.resources.reservations


@pytest.mark.asyncio
async def test_reference_persists_in_real_build_receipt_and_dedupe(prepared):
    app = prepared
    reference = (
        await app.sio.handlers["/"]["creative_handoff"]("ui", request(app, "image", "cad"))
    )["draft"]["reference"]
    context = {
        "principal": app.sessions.local_owner,
        "project_path": app.projects.get_current_project_path(),
    }
    args = BuildRequest(reference=reference)
    await app.cad.start(args, context)
    await finish(app.cad)
    job = app.cad.list(context["principal"], context["project_path"])[0]
    assert job["state"] == "succeeded" and job["reference"] == reference
    assert (await app.cad.start(args, context))["reference"] == reference
    with pytest.raises(ServiceError) as caught:
        await app.cad.start(args.model_copy(update={"reference": None}), context)
    assert caught.value.code == "request_conflict"


@pytest.mark.asyncio
async def test_queued_reference_is_rechecked_before_worker_start(prepared):
    app = prepared
    reference = (
        await app.sio.handlers["/"]["creative_handoff"]("ui", request(app, "image", "cad"))
    )["draft"]["reference"]
    context = {
        "principal": app.sessions.local_owner,
        "project_path": app.projects.get_current_project_path(),
    }
    app.cad.process_factory = lambda *_: pytest.fail("Changed reference must not launch")
    app.resources.reserve("ahead", "verification_fixture")
    args = BuildRequest(reference=reference)
    await app.cad.start(args, context)
    (context["project_path"] / "fixtures/image/model.json").write_text("changed")
    app.resources.release("ahead")
    await finish(app.cad)
    job = app.cad.load(context["principal"], context["project_path"], args.request_id)
    assert job["state"] == "failed" and not app.resources.reservations


def test_forged_digest_rejects_against_protected_receipt(prepared):
    app = prepared
    args = request(app)
    reference = CreativeReference(
        **{key: value for key, value in args.items() if key != "destination"},
        source_sha256="0" * 64,
    )
    with pytest.raises(ServiceError) as caught:
        app.handoffs.validate(
            app.sessions.local_owner, app.projects.get_current_project_path(), reference
        )
    assert caught.value.code == "reference_stale"


@pytest.mark.asyncio
async def test_cad_reference_survives_image_fixture_build_and_reopen(prepared):
    from tests.image_support import FixtureImageService
    from services.images import ImageRequest

    app = prepared
    draft = (await app.sio.handlers["/"]["creative_handoff"]("ui", request(app)))["draft"]
    service = FixtureImageService(app.database, app.resources)
    service.reference_validator = app.handoffs.validate
    context = {
        "principal": app.sessions.local_owner,
        "project_path": app.projects.get_current_project_path(),
    }
    args = ImageRequest(name=draft["name"], prompt=draft["prompt"], reference=draft["reference"])
    await service.start(args, context)
    await finish(service)
    # The production metadata reader sees provenance without loading an image model.
    restored = app.images.load(context["principal"], context["project_path"], args.request_id)
    assert restored["state"] == "succeeded" and restored["reference"] == draft["reference"]
    assert service.public(restored)["reference"] == draft["reference"]
