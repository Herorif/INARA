"""AI scene data stays reviewed, bounded, scoped and separately built."""
import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from llm.base import LLMResponse, ToolCall
from services.cad import Recipe, SceneObject, BuildRequest, ArtifactRequest, plan_scene
from services.tools import ServiceError
from tests.test_cad_jobs import service, finish
from tests.test_scene_jobs import unpack


def blueprint():
    return {"name": "Desk organiser", "shape": "scene", "objects": [
        SceneObject(name="Base", width=120, height=5, material="ceramic").model_dump(),
        SceneObject(name="Tray", shape="enclosure", position=[10, 5, 5], material="amber").model_dump(),
    ]}


def provider(data):
    return SimpleNamespace(_model="fixture-only", generate=AsyncMock(return_value=LLMResponse(
        tool_calls=[ToolCall("fixture", "propose_cad_recipe", data)])), close=AsyncMock())


@pytest.mark.asyncio
async def test_scene_proposal_builds_real_offline_exports_only_after_separate_submit(tmp_path):
    fake = provider(blueprint())
    result = await plan_scene("Two part organiser", lambda: fake)
    assert result["engine"] == "offline" and len(result["objects"]) == 2
    fake.close.assert_awaited_once()
    instance, context = service(tmp_path)
    assert not instance.active and not instance.list("owner", context["project_path"])
    args = BuildRequest(**result)
    await instance.start(args, context)
    await finish(instance)
    job = instance.load("owner", context["project_path"], args.request_id)
    assert job["state"] == "succeeded"
    artifact = instance.artifact("owner", context["project_path"], ArtifactRequest(request_id=args.request_id, format="glb"))
    doc, _ = unpack(base64.b64decode(artifact["data"]))
    assert [node["name"] for node in doc["nodes"]] == ["Base", "Tray"]
    assert len(doc["materials"]) == 2


@pytest.mark.parametrize("patch", [
    {"engine": "blender"}, {"script": "anything"}, {"objects": []},
    {"objects": [{}] * 9}, {"shape": "box"}, {"name": "\n"},
    {"objects": [{"shape": "scene", "objects": [{}]}]},
    {"objects": [{"scale": [1, 0, 1]}]},
    {"objects": [{"position": [float("nan"), 0, 0]}]},
    {"objects": [{"rotation": [0, 0, 361]}]},
    {"objects": [{"shape": "enclosure", "width": 3, "thickness": 3}]},
    {"objects": [{"material": "custom shader"}]},
])
@pytest.mark.asyncio
async def test_provider_rejects_unsupported_scene_data_and_closes(patch):
    fake = provider({**blueprint(), **patch})
    with pytest.raises(ServiceError) as caught:
        await plan_scene("fixture", lambda: fake)
    assert caught.value.code == "plan_invalid"
    fake.close.assert_awaited_once()


@pytest.fixture
def app(application_factory):
    value = application_factory()
    value.sessions.accept("ui", {"client_id": str(uuid.uuid4())})
    value.settings["tool_permissions"]["generate_cad"] = False
    return value


@pytest.mark.asyncio
async def test_scene_route_owner_permissions_strict_target_and_no_worker(app):
    app.cad_transport.scene_planner = AsyncMock(return_value=Recipe(**blueprint()).model_dump())
    request = {"prompt": "fixture", "target": "scene"}
    route = app.sio.handlers["/"]["cad_plan"]
    assert not (await route("unknown", request))["ok"]
    assert not (await route("ui", {**request, "target": "execute"}))["ok"]
    app.settings["tool_permissions"]["generate_cad"] = "deny"
    assert not (await route("ui", request))["ok"]
    app.cad_transport.scene_planner.assert_not_called()
    app.settings["tool_permissions"]["generate_cad"] = False
    result = await route("ui", request)
    assert result["ok"] and result["recipe"]["shape"] == "scene"
    assert not app.cad.active and not app.cad_transport.planning


@pytest.mark.asyncio
async def test_scene_provider_uses_existing_per_call_budget_before_generation(app):
    owner = app.sessions.local_owner
    # Existing helper configures owner-wide limits; this owner is a generated ID.
    from services.usage_contracts import UsagePolicy
    policy = app.usage.snapshot(owner)["policy"]
    app.usage.configure(owner, UsagePolicy(revision=policy["revision"], enabled=True,
        daily_microusd=60, monthly_microusd=60, per_call_microusd=60))
    fake = provider(blueprint())
    app.cad_transport.scene_planner = lambda prompt: plan_scene(prompt, lambda: fake)
    route = app.sio.handlers["/"]["cad_plan"]
    assert (await route("ui", {"prompt": "fixture", "target": "scene"}))["ok"]
    result = await route("ui", {"prompt": "fixture", "target": "scene"})
    assert not result["ok"] and fake.generate.await_count == 1
    assert app.usage.snapshot(owner)["records"][0]["feature"] == "cad_plan"
    assert not app.cad.active


@pytest.mark.asyncio
async def test_closing_panel_cancels_provider_and_closes_without_revision(app):
    started = asyncio.Event()
    fake = provider(blueprint())
    async def wait(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    fake.generate.side_effect = wait
    app.cad_transport.scene_planner = lambda prompt: plan_scene(prompt, lambda: fake)
    task = asyncio.create_task(app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "fixture", "target": "scene"}))
    await asyncio.wait_for(started.wait(), 1)
    await app.cad_transport.stop_owner(app.sessions.local_owner)
    assert task.cancelled() and not app.cad.active and not app.cad_transport.planning
    fake.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scope_rechecked_after_scene_provider_returns(app):
    async def change_project(prompt):
        app.projects.create_project("other")
        app.projects.switch_project("other")
        return Recipe(**deepcopy(blueprint())).model_dump()
    app.cad_transport.scene_planner = change_project
    result = await app.sio.handlers["/"]["cad_plan"]("ui", {"prompt": "fixture", "target": "scene"})
    assert not result["ok"] and not app.cad.active
