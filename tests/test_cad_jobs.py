"""Geometry, actual exports, durable scopes and isolated worker admission/cleanup."""

import asyncio
import base64
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from creative.geometry import build, validate, stl, glb
from llm.base import LLMResponse, ToolCall
from services.cad import (
    Recipe,
    SolidRecipe,
    BuildRequest,
    ArtifactRequest,
    CadService,
    plan_recipe,
    register_cad_tools,
)
from services.resources import ResourceGovernor
from services.storage import Database
from services.tools import ToolDispatcher, ServiceError


@pytest.mark.parametrize(
    "shape,volume", [("box", 144000), ("bracket", 20880), ("enclosure", 36108)]
)
def test_geometry_has_expected_bounds_volume_and_closed_winding(shape, volume):
    recipe = Recipe(shape=shape).model_dump()
    vertices, faces = build(recipe)
    stats = validate(vertices, faces)
    assert stats["bounds_mm"] == [[0, 0, 0], [80, 60, 30]]
    assert stats["volume_mm3"] == pytest.approx(volume)
    payload = stl(vertices, faces)
    triangles = struct.unpack_from("<I", payload, 80)[0]
    assert len(payload) == 84 + triangles * 50
    # Independently inspect the export's binary coordinates, not just its manifest.
    coordinates = []
    for i in range(triangles):
        values = struct.unpack_from("<12fH", payload, 84 + 50 * i)
        coordinates.extend([values[3:6], values[6:9], values[9:12]])
    assert [max(p[i] for p in coordinates) for i in range(3)] == [80, 60, 30]
    binary = glb(vertices, faces, "test")
    assert struct.unpack_from("<III", binary) == (0x46546C67, 2, len(binary))
    length, chunk = struct.unpack_from("<II", binary, 12)
    assert chunk == 0x4E4F534A and length % 4 == 0
    document = json.loads(binary[20 : 20 + length])
    assert document["accessors"][0]["max"] == [0.08, 0.03, 0]
    assert document["accessors"][0]["min"] == [0, 0, -0.06]
    assert document["buffers"][0]["byteLength"] == struct.unpack_from("<I", binary, 20 + length)[0]
    with pytest.raises(ValueError, match="closed"):
        validate(vertices, faces[:-1])


@pytest.mark.parametrize(
    "args",
    [
        {"width": True},
        {"height": float("inf")},
        {"width": 0},
        {"width": 1001},
        {"shape": "python"},
        {"script": "danger"},
        {"shape": "enclosure", "width": 6, "thickness": 3},
        {"shape": "bracket", "height": 3, "thickness": 3},
        {"name": "\n"},
        {"shape": "enclosure", "width": 6.00000001, "thickness": 3},
        {"shape": "bracket", "height": 3.00000001, "thickness": 3},
    ],
)
def test_dimensions_and_code_like_arguments_are_rejected(args):
    with pytest.raises(ValidationError):
        Recipe.model_validate(args)


def service(tmp_path, factory=None, timeout=30):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    governor = ResourceGovernor()
    instance = CadService(
        Database(tmp_path / "database"), governor, process_factory=factory, timeout=timeout
    )
    return instance, {"principal": "owner", "project_path": project}


async def finish(instance):
    await asyncio.gather(*(running["task"] for running in tuple(instance.active.values())))


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["box", "bracket", "enclosure"])
async def test_real_owned_worker_exports_and_completed_duplicate_never_replays(tmp_path, shape):
    instance, context = service(tmp_path)
    args = BuildRequest(shape=shape, name="private-revision-name")
    await instance.start(args, context)
    await finish(instance)
    saved = instance.load("owner", context["project_path"], args.request_id)
    assert saved["state"] == "succeeded", saved
    assert instance.active == {}
    for extension in ("stl", "glb", "json"):
        artifact = instance.artifact(
            "owner",
            context["project_path"],
            ArtifactRequest(request_id=args.request_id, format=extension),
        )
        assert len(base64.b64decode(artifact["data"])) == artifact["bytes"]
    other = CadService(
        instance.database,
        ResourceGovernor(),
        process_factory=lambda *_: pytest.fail("Replayed completed job"),
    )
    assert (await other.start(args, context))["state"] == "succeeded"
    with pytest.raises(ServiceError, match="already used"):
        await other.start(args.model_copy(update={"width": 81}), context)
    assert other.list("different-owner", context["project_path"]) == []
    with pytest.raises(ServiceError):
        other.artifact(
            "different-owner", context["project_path"], ArtifactRequest(request_id=args.request_id)
        )
    assert other.list("owner", tmp_path / "different-project") == []
    with instance.database.connection() as db:
        encrypted = db.execute(
            "SELECT payload FROM documents WHERE kind=?",
            (instance.kind("owner", context["project_path"]),),
        ).fetchone()[0]
    assert b"private-revision-name" not in encrypted
    (context["project_path"] / saved["directory"] / "model.stl").write_bytes(b"altered")
    with pytest.raises(ServiceError, match="changed"):
        instance.artifact(
            "owner", context["project_path"], ArtifactRequest(request_id=args.request_id)
        )


class SlowProcess:
    def __init__(self, *args):
        self.closed = False

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True

    def exit_code(self):
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "gaming", "close", "timeout"])
async def test_cancel_gaming_shutdown_timeout_release_worker_and_temporary_files(tmp_path, stop):
    processes = []

    def factory(*args):
        process = SlowProcess(*args)
        processes.append(process)
        return process

    instance, context = service(tmp_path, factory, 0.1 if stop == "timeout" else 30)
    args = BuildRequest()
    await instance.start(args, context)
    await asyncio.sleep(0.01)
    with pytest.raises(ServiceError, match="already running"):
        await instance.start(BuildRequest(), context)
    if stop == "cancel":
        await instance.cancel("owner", context["project_path"], args.request_id)
    elif stop == "gaming":
        instance.governor.select("gaming")
        await finish(instance)
    elif stop == "close":
        await instance.close()
    else:
        await finish(instance)
    assert not instance.active and processes[0].closed
    result = instance.load("owner", context["project_path"], args.request_id)
    assert result["state"] == ("failed" if stop == "timeout" else "cancelled")
    assert list((context["project_path"] / "cad/.work").iterdir()) == []


@pytest.mark.asyncio
async def test_close_before_worker_starts_is_durable_and_gaming_admits_nothing(tmp_path):
    instance, context = service(tmp_path, lambda *_: pytest.fail("Worker must not start"))
    args = BuildRequest()
    await instance.start(args, context)
    await instance.close()
    assert instance.load("owner", context["project_path"], args.request_id)["state"] == "cancelled"
    instance.governor.select("gaming")
    with pytest.raises(ServiceError):
        await instance.start(BuildRequest(), context)


@pytest.mark.asyncio
async def test_shared_dispatcher_denial_and_approval_recheck_precede_claim(tmp_path):
    instance, context = service(tmp_path, lambda *_: pytest.fail("Denied worker started"))
    policy = {"generate_cad": "deny"}
    dispatcher = ToolDispatcher(lambda: policy)
    register_cad_tools(dispatcher, instance)
    args = BuildRequest().model_dump(mode="json")
    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "generate_cad", args, context)
    policy["generate_cad"] = True

    async def approve(payload):
        policy["generate_cad"] = "deny"
        dispatcher.resolve("owner", payload["id"], True)

    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "generate_cad", args, context, approve)
    assert instance.list("owner", context["project_path"]) == []


@pytest.mark.asyncio
async def test_interrupted_claim_is_preserved_and_not_replayed(tmp_path):
    instance, context = service(tmp_path, lambda *_: pytest.fail("Interrupted job replayed"))
    args = BuildRequest()
    instance.save(
        "owner",
        context["project_path"],
        {
            "request_id": str(args.request_id),
            "recipe": Recipe().model_dump(),
            "project": "project",
            "state": "running",
            "phase": "building",
            "created_at": 1,
            "error": None,
        },
    )
    assert (await instance.start(args, context))["state"] == "interrupted"
    assert not instance.active


@pytest.mark.asyncio
async def test_optional_planner_returns_validated_data_and_closes_provider():
    provider = SimpleNamespace(
        generate=AsyncMock(
            return_value=LLMResponse(
                tool_calls=[
                    ToolCall(
                        "proposal", "propose_cad_recipe", SolidRecipe(shape="enclosure").model_dump()
                    )
                ]
            )
        ),
        close=AsyncMock(),
    )
    recipe = await plan_recipe("An enclosure", lambda: provider)
    assert recipe["shape"] == "enclosure"
    provider.close.assert_awaited_once()
    provider.generate.return_value = LLMResponse(
        tool_calls=[ToolCall("proposal", "run_python", {"code": "anything"})]
    )
    with pytest.raises(ServiceError):
        await plan_recipe("Unsupported", lambda: provider)


@pytest.mark.asyncio
async def test_cad_transport_rejects_unconnected_or_control_role(monkeypatch):
    import server

    handler = server.sio.handlers["/"]["cad_list"]
    monkeypatch.setattr(server, "client_principals", {"main": "owner"})
    monkeypatch.setattr(server, "client_roles", {"main": "workspace"})
    assert not (await handler("unknown"))["ok"]
    assert not (await handler("main"))["ok"]


@pytest.mark.asyncio
async def test_duplicate_pending_approval_keeps_original_cancellable(tmp_path):
    from services.cad_transport import CadTransport

    instance, context = service(tmp_path, lambda *_: pytest.fail("Unapproved worker started"))
    dispatcher = ToolDispatcher(lambda: {"generate_cad": True})
    register_cad_tools(dispatcher, instance)
    sio = SimpleNamespace(on=lambda *args, **kwargs: None, emit=AsyncMock())
    transport = CadTransport(sio, instance, dispatcher, lambda _: context)
    args = BuildRequest().model_dump(mode="json")
    first = asyncio.create_task(transport.guard(transport.cad_submit)("client", args))
    await asyncio.sleep(0.01)
    original = dict(transport.approvals)
    duplicate = await transport.guard(transport.cad_submit)("client", args)
    assert not duplicate["ok"] and transport.approvals == original
    cancelled = await transport.guard(transport.cad_cancel)(
        "client", {"request_id": args["request_id"]}
    )
    assert cancelled["job"]["state"] == "cancelled"
    assert not (await first)["ok"]
    assert not transport.approvals and not instance.active


@pytest.mark.asyncio
async def test_worker_failure_preserves_prior_files_and_releases_slot(tmp_path):
    class FailedProcess(SlowProcess):
        def alive(self):
            return False

        def exit_code(self):
            return 1

    instance, context = service(tmp_path, FailedProcess)
    saved = context["project_path"] / "cad/keep.stl"
    saved.parent.mkdir()
    saved.write_bytes(b"original")
    args = BuildRequest()
    await instance.start(args, context)
    await finish(instance)
    assert instance.load("owner", context["project_path"], args.request_id)["state"] == "failed"
    assert not instance.active and saved.read_bytes() == b"original"


@pytest.mark.asyncio
async def test_storage_failure_after_claim_keeps_uncertain_record_and_releases_worker(
    tmp_path, monkeypatch
):
    from services.storage import StorageError

    instance, context = service(tmp_path, SlowProcess)
    args = BuildRequest()
    await instance.start(args, context)

    def fail(*args):
        raise StorageError("Test storage failure")

    monkeypatch.setattr(instance, "save", fail)
    await instance.close()
    assert not instance.active
    assert (
        instance.load("owner", context["project_path"], args.request_id)["state"] == "interrupted"
    )
