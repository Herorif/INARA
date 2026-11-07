"""Live CAD co-design: in-memory drafts, brain tools, renderer RPCs and events (no providers)."""

import asyncio
import logging
import re
import uuid

import pytest
from pydantic import ValidationError

from services.cad_design import LiveDesigns, bounds, part_detail
from services.tools import ServiceError

TOKEN = "test-session-token"
SNAPSHOT_KEYS = {"id", "project", "name", "status", "recipe", "steps", "job", "updated"}
STEP_KEYS = {
    "n", "who", "kind", "title", "detail", "added", "changed", "removed", "before", "undoable"
}


def shell(**fields):
    return {
        "name": "shell", "shape": "enclosure", "width": 160.0, "depth": 200.0,
        "height": 180.0, "thickness": 3.0, "material": "titanium", **fields,
    }


def stand(**fields):
    return {"name": "stand", "width": 150.0, "depth": 190.0, "height": 10.0, **fields}


class FailedProcess:
    def __init__(self, *args):
        pass

    def alive(self):
        return False

    def exit_code(self):
        return 1

    def close(self):
        pass


@pytest.fixture
def app(application_factory):
    runtime = application_factory()
    owner = str(uuid.uuid4())
    assert runtime.sessions.accept("ui", {"token": TOKEN, "client_id": owner}, TOKEN)
    # Mirrors server DEFAULT_SETTINGS: drafting never asks, building asks.
    runtime.settings["tool_permissions"].update({"live_design": False, "generate_cad": True})
    runtime.owner = owner
    return runtime


def context(app, principal=None):
    return {
        "principal": principal or app.owner,
        "project_path": app.projects.get_current_project_path().resolve(),
    }


async def call(app, name, args=None, approve=None, principal=None):
    return await app.dispatcher.dispatch(
        principal or app.owner, name, args or {}, context(app, principal), approve
    )


async def start(app, parts=None, name="Speaker box"):
    return await call(app, "start_live_design", {"name": name, "objects": parts or [shell()]})


def snap(app, principal=None):
    return app.live_design.snapshot(principal or app.owner)["design"]


def rpc(app, name):
    return app.sio.handlers["/"][f"cad_design_{name}"]


def events(app, name="cad_design"):
    return [c for c in app.sio.emit.await_args_list if c.args[0] == name]


async def finish(app):
    await asyncio.gather(*(running["task"] for running in tuple(app.cad.active.values())))


# --- start, replace and snapshot -----------------------------------------------------


@pytest.mark.asyncio
async def test_start_records_one_add_step_per_part_without_approval_or_disk(app):
    project = context(app)["project_path"]
    before = sorted(project.rglob("*"))
    result = await start(app, [shell(), stand(position=[5.0, 5.0, -10.0])])
    assert [part["name"] for part in result["parts"]] == ["shell", "stand"]
    assert result["bounds_mm"] == [160, 200, 190]
    assert result["summary"] == "2 parts: shell, stand. Overall 160 × 200 × 190 mm."
    design = snap(app)
    assert set(design) == SNAPSHOT_KEYS
    assert design["status"] == "draft" and design["job"] is None
    assert design["project"] == project.name and design["name"] == "Speaker box"
    uuid.UUID(design["id"])
    recipe = design["recipe"]
    assert recipe["shape"] == "scene" and recipe["engine"] == "offline"
    assert len(recipe["objects"]) == 2
    steps = design["steps"]
    assert all(set(step) == STEP_KEYS for step in steps)
    assert [(s["n"], s["who"], s["kind"], s["title"]) for s in steps] == [
        (1, "jarvis", "add", "+ shell"),
        (2, "jarvis", "add", "+ stand"),
    ]
    assert steps[0]["detail"] == "open enclosure 160 × 200 × 180 mm, 3 mm walls, titanium"
    assert steps[1]["detail"] == "box 150 × 190 × 10 mm, cyan"
    assert [s["added"] for s in steps] == [[0], [1]]
    assert [s["undoable"] for s in steps] == [False, True]
    assert sorted(project.rglob("*")) == before and not app.cad.active


@pytest.mark.asyncio
async def test_start_replaces_the_design_and_resets_steps(app):
    await start(app, [shell(), stand()])
    first = snap(app)["id"]
    await start(app, [stand(name="  lid\x00\n ")], name="Lid\tonly")
    design = snap(app)
    assert design["id"] != first and design["name"] == "Lid only"
    assert [s["title"] for s in design["steps"]] == ["+ lid"]
    assert design["steps"][0]["n"] == 1 and design["steps"][0]["undoable"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {"name": "x", "objects": []},
        {"name": "x", "objects": [stand()] * 9},
        {"name": "", "objects": [stand()]},
        {"name": "x", "objects": [{"width": 10}]},  # part name is required
        {"name": "x", "objects": [stand(shape="scene")]},
        {"name": "x", "objects": [stand(material="custom shader")]},
        {"name": "x", "objects": [stand(path="C:/x")]},
        {"name": "x", "objects": [stand()], "engine": "blender"},
    ],
)
async def test_start_rejects_unbounded_or_unsupported_parts(app, args):
    with pytest.raises(ValidationError):
        await call(app, "start_live_design", args)
    assert snap(app) is None


def test_part_detail_strings():
    assert part_detail(shell()) == "open enclosure 160 × 200 × 180 mm, 3 mm walls, titanium"
    bracket = shell(shape="bracket", width=40.5, thickness=2.5, material="amber")
    assert part_detail(bracket) == "L bracket 40.5 × 200 × 180 mm, 2.5 mm walls, amber"
    assert part_detail({**stand(), "shape": "box", "thickness": 3, "material": "cyan"}) == (
        "box 150 × 190 × 10 mm, cyan"
    )


def test_bounds_follow_scale_rotation_and_position():
    part = {**stand(), "position": [0, 0, 0], "rotation": [0, 0, 90], "scale": [2, 1, 1]}
    assert bounds([part]) == [190, 300, 10]


# --- changes -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_updates_and_adds_with_generated_detail(app):
    await start(app)
    result = await call(
        app,
        "change_live_design",
        {
            "request": "make it 200 tall and add a stand",
            "update": [{"object_index": 0, "fields": {"height": 200.0}}],
            "add": [stand()],
        },
    )
    assert result["steps"] == ["shell 180 → 200 mm tall · + stand 150 × 190 × 10 mm, cyan"]
    design = snap(app)
    step = design["steps"][-1]
    assert (step["n"], step["who"], step["kind"]) == (2, "owner", "change")
    assert step["title"] == "“make it 200 tall and add a stand”"
    assert step["added"] == [1] and step["changed"] == [0] and step["removed"] == []
    assert step["before"]["0"]["height"] == 180
    assert design["recipe"]["objects"][0]["height"] == 200
    assert step["undoable"] is True


@pytest.mark.asyncio
async def test_change_removes_by_original_index_and_summarises_moves(app):
    await start(app, [shell(), stand(), stand(name="foot", material="amber")])
    await call(
        app,
        "change_live_design",
        {
            "request": "drop the stand, move the foot up and make it ceramic",
            "remove": [1],
            "update": [
                {
                    "object_index": 2,
                    "fields": {"position": [0.0, 0.0, 5.0], "material": "ceramic"},
                }
            ],
        },
    )
    step = snap(app)["steps"][-1]
    assert [p["name"] for p in snap(app)["recipe"]["objects"]] == ["shell", "foot"]
    assert step["changed"] == [1] and step["added"] == []
    assert [p["name"] for p in step["removed"]] == ["stand"]
    assert step["before"]["1"]["material"] == "amber"
    assert step["detail"] == "foot moved to 0, 0, 5 mm, amber → ceramic · − stand"


@pytest.mark.asyncio
async def test_unsupported_request_records_its_own_step_and_keeps_recipe(app):
    await start(app)
    recipe = snap(app)["recipe"]
    await call(
        app,
        "change_live_design",
        {
            "request": "drill four screw holes",
            "unsupported": [{"feature": "holes", "reason": "the offline engine can't cut holes"}],
        },
    )
    step = snap(app)["steps"][-1]
    assert (step["kind"], step["who"]) == ("unsupported", "owner")
    assert step["title"] == "“drill four screw holes”"
    assert step["detail"] == "not possible yet: the offline engine can't cut holes"
    assert snap(app)["recipe"] == recipe and step["undoable"] is False
    # A change plus an unsupported part gives both steps; the change stays the undoable one.
    await call(
        app,
        "change_live_design",
        {
            "request": "wider, with rounded edges",
            "update": [{"object_index": 0, "fields": {"width": 170.0}}],
            "unsupported": [{"feature": "fillets", "reason": "no rounded edges yet"}],
        },
    )
    steps = snap(app)["steps"]
    assert [s["kind"] for s in steps[-2:]] == ["change", "unsupported"]
    assert [s["undoable"] for s in steps[-2:]] == [True, False]


@pytest.mark.asyncio
async def test_long_request_title_is_trimmed_within_eighty_characters(app):
    await start(app)
    words = "please " * 25
    await call(
        app,
        "change_live_design",
        {"request": words, "update": [{"object_index": 0, "fields": {"depth": 210.0}}]},
    )
    title = snap(app)["steps"][-1]["title"]
    assert len(title) <= 80 and title.endswith("…”") and title.startswith("“please")


@pytest.mark.asyncio
async def test_eight_part_limit_and_index_validation_are_atomic(app):
    await start(app, [stand(name=f"p{i}") for i in range(8)])
    before = snap(app)
    with pytest.raises(ServiceError, match=re.escape("A live design holds at most eight parts.")):
        await call(app, "change_live_design", {"request": "one more", "add": [stand()]})
    with pytest.raises(ServiceError, match=re.escape("A live design needs at least one part.")):
        await call(app, "change_live_design", {"request": "x", "remove": list(range(8))})
    assert snap(app) == before
    await start(app, [shell(), stand()])
    before = snap(app)
    with pytest.raises(ServiceError, match=re.escape("There's no part at index 2. Current parts: 0 shell")):
        await call(
            app,
            "change_live_design",
            {
                "request": "taller",
                "update": [
                    {"object_index": 0, "fields": {"height": 300.0}},
                    {"object_index": 2, "fields": {"height": 300.0}},
                ],
            },
        )
    with pytest.raises(ServiceError, match="can't be changed and removed"):
        await call(
            app,
            "change_live_design",
            {
                "request": "x",
                "remove": [1],
                "update": [{"object_index": 1, "fields": {"height": 5.0}}],
            },
        )
    with pytest.raises(ServiceError, match="can't take that change"):
        await call(
            app,
            "change_live_design",
            {"request": "thick walls", "update": [{"object_index": 0, "fields": {"thickness": 90.0}}]},
        )
    with pytest.raises(ValidationError):
        await call(app, "change_live_design", {"request": "x", "remove": [1, 1]})
    with pytest.raises(ValidationError):
        await call(app, "change_live_design", {"request": "x", "script": "import os"})
    assert snap(app) == before


@pytest.mark.asyncio
async def test_change_without_a_design_has_a_plain_error(app):
    with pytest.raises(ServiceError, match=re.escape("There's no live design. Start one first.")):
        await call(app, "change_live_design", {"request": "taller", "add": [stand()]})


# --- undo --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_restores_only_the_newest_recipe_change(app):
    await start(app)
    original = snap(app)["recipe"]
    await call(
        app, "change_live_design",
        {"request": "taller", "update": [{"object_index": 0, "fields": {"height": 200.0}}]},
    )
    taller = snap(app)["recipe"]
    await call(app, "change_live_design", {"request": "add a stand", "add": [stand()]})
    await call(
        app, "change_live_design",
        {"request": "holes", "unsupported": [{"feature": "holes", "reason": "no holes yet"}]},
    )
    result = await call(app, "undo_live_design")
    assert result["undone"] == "“add a stand”"
    design = snap(app)
    assert design["recipe"] == taller
    assert [s["kind"] for s in design["steps"]] == ["add", "change", "unsupported"]
    assert design["steps"][1]["undoable"] is True
    await call(app, "undo_live_design")
    assert snap(app)["recipe"] == original
    with pytest.raises(ServiceError, match=re.escape("There's nothing to undo.")):
        await call(app, "undo_live_design")


@pytest.mark.asyncio
async def test_rpc_undo_requires_the_newest_step_of_this_design(app):
    await start(app)
    await call(app, "change_live_design", {"request": "add a stand", "add": [stand()]})
    design = snap(app)
    stale = await rpc(app, "undo")("ui", {"design_id": design["id"], "step": 1})
    assert stale == {
        "ok": False, "code": "design_stale", "message": "That change is no longer the latest.",
    }
    other = await rpc(app, "undo")("ui", {"design_id": str(uuid.uuid4()), "step": 2})
    assert not other["ok"] and other["message"] == "That design is no longer open."
    done = await rpc(app, "undo")("ui", {"design_id": design["id"], "step": 2})
    assert done["ok"] and len(done["design"]["steps"]) == 1
    assert not (await rpc(app, "undo")("ui", {"design_id": design["id"], "step": "2"}))["ok"]


# --- build -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brain_build_asks_through_generate_cad_and_follows_job_to_saved(app):
    await start(app, [shell(), stand()])
    design = snap(app)
    with pytest.raises(ServiceError) as needs:
        await call(app, "build_live_design")  # no approval channel: generate_cad asks
    assert needs.value.code == "approval_required"
    requests = []

    async def approve(payload):
        requests.append(payload)
        app.dispatcher.resolve(app.owner, payload["id"], True)

    result = await call(app, "build_live_design", approve=approve)
    assert len(requests) == 1
    request = requests[0]
    assert request["tool"] == "build_live_design"
    assert request["args"] == {
        "design_id": design["id"],
        "design_name": "Speaker box",
        "parts": 2,
        "exports": ["stl", "glb"],
        "project": design["project"],
        "summary": "Build “Speaker box”? 2 parts · STL and GLB on this PC",
    }
    assert result["status"] == "building"
    building = snap(app)
    assert building["status"] == "building"
    assert building["job"]["request_id"] == result["job"]["request_id"]
    assert not any(s["undoable"] for s in building["steps"])
    with pytest.raises(ServiceError, match="nothing to undo since the last build"):
        await call(app, "undo_live_design")
    await finish(app)
    done = snap(app)
    assert done["status"] == "saved", done["job"]
    assert done["job"]["state"] == "succeeded" and done["job"]["phase"] == "ready"
    assert done["job"]["error"] is None
    # The build is an ordinary studio revision in the design's project.
    jobs = app.cad.list(app.owner, context(app)["project_path"])
    assert [job["request_id"] for job in jobs] == [done["job"]["request_id"]]
    assert jobs[0]["recipe"]["objects"] == done["recipe"]["objects"]
    assert not any(s["undoable"] for s in done["steps"])
    with pytest.raises(ServiceError, match="already saved"):
        await call(app, "build_live_design", approve=approve)
    # A later change makes a new draft whose newest change (only) is undoable.
    await call(app, "change_live_design", {"request": "add a foot", "add": [stand(name="foot")]})
    assert snap(app)["status"] == "draft" and snap(app)["steps"][-1]["undoable"]
    await call(app, "undo_live_design")
    with pytest.raises(ServiceError, match=re.escape("There's nothing to undo.")):
        await call(app, "undo_live_design")


@pytest.mark.asyncio
async def test_declined_or_changed_approval_builds_nothing(app):
    await start(app)

    async def decline(payload):
        app.dispatcher.resolve(app.owner, payload["id"], False)

    with pytest.raises(ServiceError, match="declined"):
        await call(app, "build_live_design", approve=decline)

    async def change_then_approve(payload):
        await call(app, "change_live_design", {"request": "add a stand", "add": [stand()]})
        app.dispatcher.resolve(app.owner, payload["id"], True)

    with pytest.raises(ServiceError, match="changed while waiting for approval"):
        await call(app, "build_live_design", approve=change_then_approve)
    assert snap(app)["status"] == "draft" and snap(app)["job"] is None and not app.cad.active
    app.settings["tool_permissions"]["generate_cad"] = "deny"
    with pytest.raises(ServiceError, match="disabled"):
        await call(app, "build_live_design")


@pytest.mark.asyncio
async def test_rpc_build_is_consent_without_a_second_prompt_and_follows_to_failed(app):
    await start(app)
    design = snap(app)
    app.cad.process_factory = FailedProcess
    app.sio.emit.reset_mock()
    response = await rpc(app, "build")("ui", {"design_id": design["id"]})
    assert response["ok"] and response["design"]["status"] == "building"
    assert not events(app, "tool_confirmation_request")
    await finish(app)
    failed = snap(app)
    assert failed["status"] == "failed"
    assert failed["job"]["state"] == "failed" and failed["job"]["phase"] == "stopped"
    assert failed["job"]["error"] == "The creative worker stopped before completing validation."
    # The studio's own cad_job delivery still runs alongside the live design events.
    assert events(app, "cad_job")
    assert events(app)[-1].args[1]["design"]["status"] == "failed"
    # Failed may be retried; a deny policy still refuses the panel's build.
    app.settings["tool_permissions"]["generate_cad"] = "deny"
    refused = await rpc(app, "build")("ui", {"design_id": design["id"]})
    assert refused["code"] == "permission_denied" and snap(app)["status"] == "failed"


@pytest.mark.asyncio
async def test_rpc_build_respects_gaming_mode(app):
    await start(app)
    app.resources.select("gaming")
    response = await rpc(app, "build")("ui", {"design_id": snap(app)["id"]})
    assert response == {
        "ok": False,
        "code": "resource_policy",
        "message": "Open Studio and leave gaming mode to use this capability.",
    }
    assert snap(app)["status"] == "draft" and snap(app)["job"] is None


@pytest.mark.asyncio
async def test_change_during_build_keeps_draft_and_end_lets_build_finish(app):
    await start(app)
    await rpc(app, "build")("ui", {"design_id": snap(app)["id"]})
    request_id = snap(app)["job"]["request_id"]
    await call(app, "change_live_design", {"request": "add a stand", "add": [stand()]})
    assert snap(app)["status"] == "draft"
    assert [s["undoable"] for s in snap(app)["steps"]] == [False, True]
    ended = await rpc(app, "end")("ui", {"design_id": snap(app)["id"]})
    assert ended == {"ok": True, "design": None}
    assert events(app)[-1].args[1] == {"design": None}
    await finish(app)
    saved = app.cad.load(app.owner, context(app)["project_path"], request_id)
    assert saved["state"] == "succeeded"
    assert snap(app) is None


# --- events, ownership and visibility ----------------------------------------------


@pytest.mark.asyncio
async def test_events_reach_only_the_owner_renderers_and_hydrate_on_connect(app):
    app.sessions.principals.update({"two": app.owner, "tray": app.owner, "intruder": "other"})
    app.sessions.roles.update({"two": "renderer", "tray": "workspace", "intruder": "renderer"})
    app.sio.emit.reset_mock()
    await start(app)
    assert sorted(c.kwargs["room"] for c in events(app)) == ["two", "ui"]
    assert events(app)[0].args[1] == app.live_design.snapshot(app.owner)
    app.sio.emit.reset_mock()
    await app.connection.hydrate("ui")
    assert [c.kwargs["room"] for c in events(app)] == ["ui"]
    # No snapshot before a design exists, nor while the owner is locked.
    app.sio.emit.reset_mock()
    app.settings["face_auth_enabled"] = True
    await app.connection.hydrate("ui")
    assert not events(app)


@pytest.mark.asyncio
async def test_another_principal_cannot_see_or_change_the_design(app):
    await start(app)
    design = snap(app)
    app.sessions.principals["intruder"] = other = str(uuid.uuid4())
    app.sessions.roles["intruder"] = "renderer"
    for name, data in (
        ("get", None),
        ("undo", {"design_id": design["id"], "step": 1}),
        ("build", {"design_id": design["id"]}),
        ("end", {"design_id": design["id"]}),
    ):
        response = await rpc(app, name)("intruder", data)
        assert response["ok"] is False and response["code"] == "permission_denied"
    # Workspace/overlay sockets are not renderers; unknown sockets are refused.
    app.sessions.roles["tray"], app.sessions.principals["tray"] = "workspace", app.owner
    assert (await rpc(app, "get")("tray"))["code"] == "authentication_required"
    assert (await rpc(app, "get")("unknown"))["code"] == "authentication_required"
    # The tools are owner-only too, and never reach the owner's draft.
    with pytest.raises(ServiceError) as denied:
        await call(app, "undo_live_design", principal=other)
    assert denied.value.code in ("permission_denied", "authentication_required")
    assert snap(app) == design
    assert (await rpc(app, "get")("ui"))["design"] == design


def test_live_tools_are_visible_and_studio_cad_tools_are_not(app):
    import server

    names = {item["name"] for item in app.dispatcher.schemas()}
    assert {
        "start_live_design", "change_live_design", "undo_live_design", "build_live_design"
    } <= names
    assert not {"generate_cad", "plan_cad", "plan_cad_changes"} & names
    tools = app.dispatcher.tools
    assert {tools[n].permission for n in ("start_live_design", "change_live_design",
                                         "undo_live_design")} == {"live_design"}
    assert tools["build_live_design"].permission == "generate_cad"
    assert tools["build_live_design"].review is not None
    assert server.DEFAULT_SETTINGS["tool_permissions"]["live_design"] is False
    assert server.DEFAULT_SETTINGS["tool_permissions"]["generate_cad"] is True
    assert "live_design" in app.settings_service.permission_names
    description = tools["start_live_design"].description
    for phrase in ("millimetres", "at most eight parts", "cyan, titanium, amber or ceramic",
                   "one or two short sentences"):
        assert phrase in description
    assert "unsupported" in tools["change_live_design"].description
    assert "only when the owner asks to build" in tools["build_live_design"].description


@pytest.mark.asyncio
async def test_studio_rpcs_are_unchanged(app):
    for name in ("submit", "cancel", "list", "artifact", "close", "lifetime", "plan",
                 "review_changes", "plan_changes"):
        assert app.sio.handlers["/"][f"cad_{name}"]
    app.sio.emit.reset_mock()
    task = asyncio.create_task(app.sio.handlers["/"]["cad_submit"]("ui", {"shape": "box"}))
    for _ in range(50):
        if events(app, "tool_confirmation_request"):
            break
        await asyncio.sleep(0.01)
    confirmation = events(app, "tool_confirmation_request")[0].args[1]
    assert confirmation["tool"] == "generate_cad"  # the studio's Build still asks as before
    app.dispatcher.resolve(app.owner, confirmation["id"], True)
    response = await task
    assert response["ok"] and response["job"]["state"] in ("queued", "running")
    await finish(app)
    assert snap(app) is None


@pytest.mark.asyncio
async def test_owner_words_are_never_logged(app, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "make it fit my private-word-xyzzy shelf"
    await start(app)
    await call(
        app, "change_live_design",
        {"request": secret, "update": [{"object_index": 0, "fields": {"width": 170.0}}]},
    )
    await call(app, "undo_live_design")
    assert "xyzzy" not in caplog.text


def test_live_designs_wraps_the_existing_job_update(tmp_path):
    from types import SimpleNamespace
    from tests.test_cad_jobs import service
    from services.tools import ToolDispatcher

    instance, _ = service(tmp_path)
    seen = []

    async def previous(owner, job):
        seen.append(job)

    instance.on_update = previous
    designs = LiveDesigns(
        SimpleNamespace(on=lambda *a, **k: None), SimpleNamespace(rooms=lambda *_: ()),
        instance, ToolDispatcher(lambda: {}), None,
    )
    asyncio.run(instance.on_update("owner", {"request_id": "x"}))
    assert seen == [{"request_id": "x"}] and designs.designs == {}
