"""Revision lineage, proposal policy and strict change semantics without provider setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import asyncio

import pytest
from pydantic import ValidationError
from services.cad import BuildRequest, Recipe
from services.cad_changes import ChangeSet, ChangePrompt, EditList, apply_changes, propose_changes
from services.revisions import recipe_fingerprint
from services.tools import ServiceError
from tests.test_cad_jobs import service, finish
from tests.test_image_jobs import service as image_service, request as image_request


def saved(instance, context, recipe=None):
    recipe = Recipe.model_validate(recipe or {}).model_dump()
    identifier = str(uuid.uuid4())
    value = {
        "request_id": identifier,
        "recipe": recipe,
        "project": context["project_path"].name,
        "state": "succeeded",
        "phase": "ready",
        "created_at": 1,
        "artifacts": {},
    }
    instance.save(context["principal"], context["project_path"], value)
    return {"base_request_id": identifier, "base_fingerprint": recipe_fingerprint(recipe)}


@pytest.mark.parametrize(
    "fields",
    [
        {"width": True},
        {"position": [True, 0, 0]},
        {"rotation": [0, float("inf"), 0]},
        {"scale": [0, 1, 1]},
        {"run": "code"},
        {},
    ],
)
def test_changes_reject_code_empty_and_invalid_values(fields):
    with pytest.raises(ValidationError):
        EditList(edits=[{"fields": fields}])


def test_apply_changes_validates_final_walls_object_scope_and_transforms():
    base = Recipe(shape="scene", objects=[{"name": "part"}]).model_dump()
    edits = EditList(
        edits=[
            {
                "object_index": 0,
                "fields": {"position": [10, 20, 30], "width": 120, "material": "amber"},
            }
        ]
    )
    updated = apply_changes(base, edits.edits)
    assert updated["objects"][0]["position"] == [10, 20, 30]
    assert base["objects"][0]["width"] == 80
    with pytest.raises(ServiceError):
        apply_changes(base, EditList(edits=[{"object_index": 1, "fields": {"width": 90}}]).edits)
    with pytest.raises(ServiceError):
        apply_changes(base, EditList(edits=[{"fields": {"width": 90}}]).edits)
    with pytest.raises(ValidationError):
        apply_changes(
            Recipe(shape="enclosure").model_dump(),
            EditList(edits=[{"fields": {"thickness": 100}}]).edits,
        )


@pytest.mark.asyncio
async def test_branch_exports_are_independent_and_parent_replay_is_exact(tmp_path):
    instance, context = service(tmp_path)
    first = BuildRequest()
    await instance.start(first, context)
    await finish(instance)
    parent = instance.public(instance.load("owner", context["project_path"], first.request_id))
    reference = {
        "base_request_id": first.request_id,
        "base_fingerprint": parent["recipe_fingerprint"],
    }
    child = BuildRequest(width=120, **reference)
    await instance.start(child, context)
    await finish(instance)
    assert instance.load("owner", context["project_path"], child.request_id)[
        "base_request_id"
    ] == str(first.request_id)
    assert (
        instance.load("owner", context["project_path"], first.request_id)["recipe"]["width"] == 80
    )
    assert (await instance.start(child, context))["state"] == "succeeded"
    with pytest.raises(ServiceError) as error:
        await instance.start(
            child.model_copy(update={"base_request_id": None, "base_fingerprint": None}), context
        )
    assert error.value.code == "request_conflict"
    # Branching deliberately from an older immutable base is permitted.
    sibling = BuildRequest(height=60, **reference)
    await instance.start(sibling, context)
    await finish(instance)
    assert (
        instance.load("owner", context["project_path"], sibling.request_id)["state"] == "succeeded"
    )


@pytest.mark.asyncio
async def test_missing_foreign_and_stale_parent_cannot_claim_worker(tmp_path):
    instance, context = service(tmp_path, factory=lambda *_: pytest.fail("Unexpected worker"))
    reference = saved(instance, context)
    for changes, scope in [
        ({"base_fingerprint": "0" * 64}, context),
        ({}, {**context, "principal": "other"}),
        ({}, {**context, "project_path": tmp_path / "elsewhere"}),
    ]:
        with pytest.raises(ServiceError):
            await instance.start(BuildRequest(**{**reference, **changes}), scope)
    assert not instance.governor.reservations
    assert len(instance.list("owner", context["project_path"])) == 1
    for fields in [{"base_request_id": uuid.uuid4()}, {"base_fingerprint": "0" * 64}]:
        with pytest.raises(ValidationError):
            BuildRequest(**fields)


@pytest.mark.asyncio
async def test_image_recipe_reuse_records_parent_without_contaminating_recipe(tmp_path):
    instance, context = image_service(tmp_path)
    first = image_request()
    await instance.start(first, context)
    await finish(instance)
    parent = instance.public(instance.load("owner", context["project_path"], first.request_id))
    child = image_request(
        seed=42, base_request_id=first.request_id, base_fingerprint=parent["recipe_fingerprint"]
    )
    await instance.start(child, context)
    await finish(instance)
    value = instance.load("owner", context["project_path"], child.request_id)
    assert value["state"] == "succeeded" and value["base_request_id"] == str(first.request_id)
    assert "base_request_id" not in value["recipe"]


@pytest.mark.asyncio
async def test_planner_returns_data_only_and_closes_provider():
    from llm.base import LLMResponse, ToolCall

    provider = SimpleNamespace(
        generate=AsyncMock(
            return_value=LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="one",
                        name="propose_scene_edits",
                        args={"edits": [{"fields": {"width": 123}}]},
                    )
                ]
            )
        ),
        close=AsyncMock(),
    )
    edits = await propose_changes("make it wider", Recipe().model_dump(), lambda: provider)
    assert edits.edits[0].fields.width == 123
    provider.close.assert_awaited_once()
    assert "$defs" not in str(provider.generate.call_args.kwargs["tools"])


@pytest.mark.asyncio
async def test_review_is_scoped_and_missing_provider_preserves_saved_base(
    application_factory, monkeypatch
):
    app = application_factory()
    context = {"principal": "owner", "project_path": app.projects.get_current_project_path()}
    reference = saved(app.cad, context)
    request = ChangeSet(**reference, edits=[{"fields": {"width": 100}}])
    result = app.cad_transport.review(request, context)
    assert result["proposal"]["recipe"]["width"] == 100 and not app.cad.active
    with pytest.raises(ServiceError):
        app.cad_transport.review(request, {**context, "principal": "other"})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app.sessions.local_owner = "owner"
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.settings["tool_permissions"]["generate_cad"] = False
    response = await app.cad_transport.guard(app.cad_transport.plan_changes)(
        "client", {**reference, "prompt": "wider"}
    )
    assert not response["ok"] and response["code"] == "provider_not_configured"
    assert not app.cad.active and not app.cad_transport.planning


@pytest.mark.asyncio
async def test_planned_changes_recheck_stale_base_and_owner_after_provider(application_factory):
    app = application_factory()
    context = {"principal": "owner", "project_path": app.projects.get_current_project_path()}
    reference = saved(app.cad, context)
    app.sessions.local_owner = "owner"
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"

    async def planner(*_):
        value = app.cad.load("owner", context["project_path"], reference["base_request_id"])
        value["recipe"]["width"] = 85
        app.cad.save("owner", context["project_path"], value)
        return EditList(edits=[{"fields": {"width": 100}}])

    app.cad_transport.change_planner = planner
    with pytest.raises(ServiceError) as error:
        await app.cad_transport.execute_change_plan(
            ChangePrompt(**reference, prompt="wider"), context
        )
    assert error.value.code == "revision_stale" and not app.cad_transport.planning


@pytest.mark.asyncio
async def test_denial_and_gaming_precede_provider_execution(application_factory):
    app = application_factory()
    context = {"principal": "owner", "project_path": app.projects.get_current_project_path()}
    reference = saved(app.cad, context)
    app.sessions.local_owner = "owner"
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    planner = AsyncMock()
    app.cad_transport.change_planner = planner
    app.settings["tool_permissions"]["generate_cad"] = "deny"
    with pytest.raises(ServiceError):
        await app.dispatcher.dispatch(
            "owner", "plan_cad_changes", {**reference, "prompt": "wider"}, context
        )
    app.resources.select("gaming")
    with pytest.raises(ServiceError):
        await app.cad_transport.execute_change_plan(
            ChangePrompt(**reference, prompt="wider"), context
        )
    planner.assert_not_called()


def test_fingerprint_is_stable_for_equivalent_numbers_and_dict_order():
    assert recipe_fingerprint({"width": 80, "height": 30.0}) == recipe_fingerprint(
        {"height": 30, "width": 80.0}
    )


def test_render_presets_are_fixed_data_and_extra_execution_fields_are_rejected():
    recipe = Recipe(
        shape="scene",
        objects=[{}],
        presentation={
            "camera": "top",
            "lighting": "soft",
            "quality": "standard",
            "background": "neutral",
        },
    )
    assert recipe.presentation.camera == "top"
    for presentation in [{"camera": "python"}, {"quality": "unlimited"}, {"script": "anything"}]:
        with pytest.raises(ValidationError):
            Recipe(presentation=presentation)


@pytest.mark.asyncio
async def test_panel_close_cancels_provider_plan_and_releases_planning_owner(application_factory):
    app = application_factory()
    context = {"principal": "owner", "project_path": app.projects.get_current_project_path()}
    reference = saved(app.cad, context)
    app.sessions.local_owner = "owner"
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.settings["tool_permissions"]["generate_cad"] = False
    started = asyncio.Event()

    async def planner(*_):
        started.set()
        await asyncio.Event().wait()

    app.cad_transport.change_planner = planner
    task = asyncio.create_task(
        app.cad_transport.plan_changes("client", {**reference, "prompt": "wider"}, context)
    )
    await started.wait()
    await app.cad_transport.close_panel("client", {}, context)
    assert task.cancelled() and not app.cad_transport.planning and not app.cad.active
