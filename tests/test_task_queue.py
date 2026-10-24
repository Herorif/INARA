"""Reviewed local steps, durable non-replay receipts and failure recovery; no hardware."""

import asyncio
import uuid
from unittest.mock import AsyncMock, Mock
import pytest
from pydantic import ValidationError
from services.task_queue_contracts import TaskCreate, TaskReference
from services.task_queue import TaskQueue
from services.tools import ServiceError
from services.storage import StorageError
from tests.test_workspace_policy import workspace as workspace_fixture


@pytest.fixture
def app(application_factory):
    value = workspace_fixture.__wrapped__(application_factory)
    for name in ("write_file", "read_file", "launch_app"):
        value.settings["tool_permissions"][name] = False
    return value


def project(app):
    return app.projects.get_current_project_path().resolve()


def plan(**changes):
    return TaskCreate(
        id=uuid.uuid4(),
        title="Fixture task",
        steps=[{"tool": "write_file", "path": "notes/task.txt", "content": "fixture"}],
        **changes,
    )


def create(app, value=None):
    value = value or plan()
    app.task_queue.create("owner", project(app), value)
    return str(value.id)


def state(app):
    return app.task_queue.state("owner", project(app))


def approve(app):
    async def review(payload):
        assert app.dispatcher.resolve("owner", payload["id"], True)

    return review


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"tool": "delete_file", "path": "x"}],
        [{"tool": "launch_app", "name": "cmd"}],
        [{"tool": "launch_app", "name": "notepad & evil"}],
        [{"tool": "read_file", "path": 1}],
        [{"tool": "write_file", "path": "x", "content": "x" * 16001}],
        [{"tool": "read_file", "path": "x", "script": "evil"}],
        [{"tool": "read_file", "path": "x"}] * 9,
    ],
)
def test_strict_bounded_plan_schema(steps):
    with pytest.raises(ValidationError):
        TaskCreate(id=uuid.uuid4(), title="Fixture", steps=steps)


def test_total_plan_limit_and_strict_reference():
    with pytest.raises(ValidationError):
        TaskCreate(
            id=uuid.uuid4(),
            title="Fixture",
            steps=[{"tool": "write_file", "path": "x", "content": "x" * 16000}] * 3,
        )
    with pytest.raises(ValidationError):
        TaskReference(id=uuid.uuid4(), resume=True)


@pytest.mark.parametrize("path", ["../escape", "C:\\outside", "/outside", "notes/file:stream"])
def test_create_rejects_escape_before_persistence(app, path):
    args = TaskCreate(id=uuid.uuid4(), title="Fixture", steps=[{"tool": "read_file", "path": path}])
    with pytest.raises(ServiceError):
        create(app, args)
    assert state(app)["receipts_used"] == 0


def test_idempotent_create_immutable_plan_and_no_side_effects(app):
    value = plan()
    identifier = create(app, value)
    create(app, value)
    assert len(state(app)["tasks"]) == 1 and state(app)["receipts_used"] == 1
    assert not (project(app) / "notes/task.txt").exists()
    changed = value.model_copy(update={"title": "different"})
    with pytest.raises(ServiceError) as exc:
        create(app, changed)
    assert exc.value.code == "task_conflict"
    assert state(app)["tasks"][0]["id"] == identifier


@pytest.mark.asyncio
async def test_every_step_requires_review_and_receipt_before_effect(app):
    value = TaskCreate(
        id=uuid.uuid4(),
        title="Write then read",
        steps=[
            {"tool": "write_file", "path": "notes/task.txt", "content": "fixture"},
            {"tool": "read_file", "path": "notes/task.txt"},
        ],
    )
    identifier = create(app, value)
    reviews = []

    async def review(payload):
        reviews.append(payload)
        task = state(app)["tasks"][0]
        index = payload["task_queue"]["step"] - 1
        assert task["steps"][index]["state"] == "awaiting_approval"
        assert payload["project"] == project(app).name
        app.dispatcher.resolve("owner", payload["id"], True)

    original = app.dispatcher.tools["write_file"].execute

    def effect(args, context):
        assert state(app)["tasks"][0]["steps"][0]["state"] == "running"
        return original(args, context)

    app.dispatcher.tools["write_file"].execute = effect
    await app.task_queue.run("client", "owner", project(app), identifier, review)
    report = state(app)["tasks"][0]
    assert report["state"] == "completed" and len(reviews) == 2
    assert report["steps"][1]["preview"] == "fixture"
    assert all(item["state"] == "completed" for item in report["steps"])
    with pytest.raises(ServiceError) as exc:
        await app.task_queue.run("client", "owner", project(app), identifier, review)
    assert exc.value.code == "task_not_draft" and len(reviews) == 2


@pytest.mark.asyncio
async def test_denial_stops_later_steps_without_execution(app):
    identifier = create(app)
    app.settings["tool_permissions"]["write_file"] = "deny"
    review = AsyncMock()
    await app.task_queue.run("client", "owner", project(app), identifier, review)
    result = state(app)["tasks"][0]
    assert result["state"] == "stopped" and result["steps"][0]["state"] == "failed"
    review.assert_not_called()
    assert not (project(app) / "notes/task.txt").exists()


@pytest.mark.asyncio
async def test_decline_and_permission_change_after_approval_fail_closed(app):
    for deny_after in (False, True):
        app.settings["tool_permissions"]["write_file"] = False
        identifier = create(app)

        async def review(payload):
            if deny_after:
                app.settings["tool_permissions"]["write_file"] = "deny"
            app.dispatcher.resolve("owner", payload["id"], deny_after)

        await app.task_queue.run("client", "owner", project(app), identifier, review)
    assert not (project(app) / "notes/task.txt").exists()
    assert all(task["state"] == "stopped" for task in state(app)["tasks"])


@pytest.mark.asyncio
async def test_global_busy_origin_cancel_and_pending_approval_cleanup(app):
    first, second = create(app), create(app)
    entered = asyncio.Event()

    async def review(payload):
        entered.set()

    task = asyncio.create_task(app.task_queue.run("client", "owner", project(app), first, review))
    await entered.wait()
    with pytest.raises(ServiceError) as exc:
        await app.task_queue.run("sibling", "owner", project(app), second, review)
    assert exc.value.code == "task_busy"
    with pytest.raises(ServiceError) as exc:
        await app.task_queue.cancel("sibling", "owner", project(app), first)
    assert exc.value.code == "task_origin"
    await app.task_queue.cancel("client", "owner", project(app), first)
    await asyncio.gather(task, return_exceptions=True)
    assert not app.dispatcher.pending and not app.task_queue.active
    first_plan = next(item for item in state(app)["tasks"] if item["id"] == first)
    assert first_plan["steps"][0]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_partial_failure_retains_completed_steps_and_marks_effect_uncertain(app):
    value = TaskCreate(
        id=uuid.uuid4(),
        title="Partial",
        steps=[
            {"tool": "write_file", "path": "notes/task.txt", "content": "fixture"},
            {"tool": "launch_app", "name": "notepad"},
            {"tool": "read_file", "path": "notes/task.txt"},
        ],
    )
    identifier = create(app, value)

    async def fails(args, context):
        raise RuntimeError("private error")

    app.dispatcher.tools["launch_app"].execute = fails
    await app.task_queue.run("client", "owner", project(app), identifier, approve(app))
    result = state(app)["tasks"][0]
    assert [item["state"] for item in result["steps"]] == ["completed", "uncertain", "cancelled"]
    assert (project(app) / "notes/task.txt").read_text() == "fixture"
    assert "private error" not in str(result)


@pytest.mark.asyncio
async def test_running_adapter_cancel_is_uncertain_and_never_replayed(app):
    identifier = create(
        app,
        TaskCreate(
            id=uuid.uuid4(), title="Fixture", steps=[{"tool": "launch_app", "name": "notepad"}]
        ),
    )
    entered, closed = asyncio.Event(), asyncio.Event()

    async def effect(args, context):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    adapter = AsyncMock(side_effect=effect)
    app.dispatcher.tools["launch_app"].execute = adapter
    task = asyncio.create_task(
        app.task_queue.run("client", "owner", project(app), identifier, approve(app))
    )
    await entered.wait()
    await app.disconnect("client")
    await asyncio.gather(task, return_exceptions=True)
    assert closed.is_set() and not app.task_queue.active
    assert state(app)["tasks"][0]["steps"][0]["state"] == "uncertain"
    assert adapter.await_count == 1
    restored = TaskQueue(app)
    assert restored.state("owner", project(app))["tasks"][0]["state"] == "stopped"
    assert adapter.await_count == 1


@pytest.mark.asyncio
async def test_project_change_during_review_stops_before_effect(app):
    original = project(app)
    identifier = create(app)

    async def review(payload):
        app.projects.create_project("DifferentProject")
        app.projects.switch_project("DifferentProject")
        app.dispatcher.resolve("owner", payload["id"], True)

    await app.task_queue.run("client", "owner", original, identifier, review)
    result = app.task_queue.state("owner", original)["tasks"][0]
    assert result["state"] == "stopped" and result["steps"][0]["code"] == "task_scope_changed"
    assert not (original / "notes/task.txt").exists()
    assert state(app)["tasks"] == []


def test_recovery_marks_only_unfinished_steps_and_never_dispatches(app):
    identifier = create(app)
    key = app.task_queue.key("owner", project(app))

    def incomplete(task):
        task.update(state="running")
        task["steps"][0]["state"] = "running"

    app.task_queue.change(key, identifier, incomplete)
    restored = TaskQueue(app)
    assert restored.state("owner", project(app))["tasks"][0]["state"] == "interrupted"
    assert restored.state("owner", project(app))["tasks"][0]["steps"][0]["state"] == "uncertain"
    assert app.task_queue.state("intruder", project(app))["tasks"] == []
    assert not (project(app) / "notes/task.txt").exists()


@pytest.mark.asyncio
async def test_receipt_commit_failure_prevents_effect(app, monkeypatch):
    identifier = create(app)
    original = app.task_queue.step

    def fail(key, id, index, **values):
        if values.get("state") == "running":
            raise StorageError("fixture")
        return original(key, id, index, **values)

    monkeypatch.setattr(app.task_queue, "step", fail)
    await app.task_queue.run("client", "owner", project(app), identifier, approve(app))
    assert not (project(app) / "notes/task.txt").exists()
    assert state(app)["tasks"][0]["steps"][0]["state"] == "failed"


@pytest.mark.asyncio
async def test_encrypted_details_and_bounded_read_preview(app):
    text = "PRIVATE QUEUE FIXTURE" + "x" * 6000
    (project(app) / "fixture.txt").write_text(text)
    identifier = create(
        app,
        TaskCreate(
            id=uuid.uuid4(),
            title="PRIVATE QUEUE TITLE",
            steps=[{"tool": "read_file", "path": "fixture.txt"}],
        ),
    )
    await app.task_queue.run("client", "owner", project(app), identifier, approve(app))
    assert len(state(app)["tasks"][0]["steps"][0]["preview"]) == 4000
    for file in app.database.directory.glob("assistant.sqlite3*"):
        raw = file.read_bytes()
        assert b"PRIVATE QUEUE FIXTURE" not in raw and b"PRIVATE QUEUE TITLE" not in raw


@pytest.mark.asyncio
async def test_capacity_prunes_details_but_id_remains_reserved(app):
    values = []
    for _ in range(25):
        value = plan()
        identifier = create(app, value)
        values.append(value)
        await app.task_queue.cancel("client", "owner", project(app), identifier)
    snapshot = state(app)
    assert snapshot["receipts_used"] == 25 and len(snapshot["tasks"]) == 24
    with pytest.raises(ServiceError) as exc:
        create(app, values[0])
    assert exc.value.code == "task_retired"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["task_queue_state", "task_queue_create", "task_queue_run", "task_queue_cancel"]
)
@pytest.mark.parametrize("sid", ["unknown", "other", "tray", "control"])
async def test_all_routes_require_owner_renderer(app, name, sid):
    result = await app.sio.handlers["/"][name](sid, {})
    assert not result["ok"]
    assert state(app)["receipts_used"] == 0


@pytest.mark.asyncio
async def test_cancel_draft_is_terminal_and_safety_control_works_locked(app):
    identifier = create(app)
    app.settings["face_auth_enabled"] = True
    result = await app.sio.handlers["/"]["task_queue_cancel"]("client", {"id": identifier})
    assert result == {"ok": True}
    assert state(app)["tasks"][0]["state"] == "stopped"
    result = await app.sio.handlers["/"]["task_queue_run"]("client", {"id": identifier})
    assert not result["ok"]


@pytest.mark.asyncio
async def test_transport_closes_only_its_task_approval_and_uses_no_provider(app):
    value = plan()
    create(app, value)
    app.usage.begin = Mock(side_effect=AssertionError("No provider admission expected"))

    async def emit(event, data, room=None):
        if event == "tool_confirmation_request":
            assert room == "client"
            app.dispatcher.resolve("owner", data["id"], True)

    app.sio.emit = AsyncMock(side_effect=emit)
    result = await app.sio.handlers["/"]["task_queue_run"]("client", {"id": str(value.id)})
    assert result["ok"] and result["tasks"][0]["state"] == "completed"
    assert app.sio.emit.await_args.args[0] == "task_queue_approval_closed"
    assert app.sio.emit.await_args.kwargs["room"] == "client"
    app.usage.begin.assert_not_called()


@pytest.mark.asyncio
async def test_approval_timeout_is_failed_before_any_effect(app):
    identifier = create(app)
    app.dispatcher.timeout = 0.001
    await app.task_queue.run("client", "owner", project(app), identifier, AsyncMock())
    step = state(app)["tasks"][0]["steps"][0]
    assert step["state"] == "failed" and step["code"] == "approval_expired"
    assert not app.dispatcher.pending and not (project(app) / "notes/task.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["resources", "quit"])
async def test_resource_and_shutdown_stop_pending_review(app, stop):
    identifier = create(app)
    entered = asyncio.Event()

    async def review(payload):
        entered.set()

    task = asyncio.create_task(
        app.task_queue.run("client", "owner", project(app), identifier, review)
    )
    await entered.wait()
    if stop == "resources":
        await app.restrict_resources()
    else:
        await app.close()
    await asyncio.gather(task, return_exceptions=True)
    assert not app.task_queue.active and not app.dispatcher.pending
    assert state(app)["tasks"][0]["state"] == "stopped"


@pytest.mark.asyncio
async def test_adapter_timeout_stops_later_steps_and_retains_uncertainty(app):
    value = TaskCreate(
        id=uuid.uuid4(),
        title="Timeout",
        steps=[
            {"tool": "launch_app", "name": "notepad"},
            {"tool": "write_file", "path": "never.txt", "content": "never"},
        ],
    )
    identifier = create(app, value)
    closed = asyncio.Event()

    async def slow(args, context):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    app.dispatcher.tools["launch_app"].execute = slow
    app.dispatcher.tools["launch_app"].execution_timeout = 0.001
    await app.task_queue.run("client", "owner", project(app), identifier, approve(app))
    result = state(app)["tasks"][0]
    assert closed.is_set() and [step["state"] for step in result["steps"]] == [
        "uncertain",
        "cancelled",
    ]
    assert result["steps"][0]["code"] == "action_timeout"
    assert not (project(app) / "never.txt").exists()


def test_receipt_limit_refuses_new_ids_without_resetting_existing_history(app):
    key = app.task_queue.key("owner", project(app))
    with app.database.transaction() as db:
        app.database.put(
            db,
            "desktop_tasks_v1",
            key,
            {"plans": {}, "seen": {str(uuid.uuid4()): "fixture" for _ in range(2048)}},
        )
    with pytest.raises(ServiceError) as exc:
        create(app)
    assert exc.value.code == "task_receipt_limit" and state(app)["receipts_used"] == 2048


def test_full_drafts_remain_intact_and_can_be_discarded(app):
    for _ in range(24):
        create(app)
    with pytest.raises(ServiceError) as exc:
        create(app)
    assert exc.value.code == "task_capacity" and len(state(app)["tasks"]) == 24


@pytest.mark.asyncio
async def test_project_switch_cleanup_stops_origin_task_without_private_receipts(app):
    identifier = create(app)
    entered = asyncio.Event()

    async def review(payload):
        entered.set()

    task = asyncio.create_task(
        app.task_queue.run("client", "owner", project(app), identifier, review)
    )
    await entered.wait()
    app.projects.create_project("NextProject")
    app.projects.switch_project("NextProject")
    result = await app.sio.handlers["/"]["task_queue_cancel"]("client", {"id": identifier})
    await asyncio.gather(task, return_exceptions=True)
    assert result == {"ok": True} and not app.task_queue.active and not app.dispatcher.pending


@pytest.mark.asyncio
async def test_rejected_duplicate_run_does_not_close_live_approval(app):
    identifier = create(app)
    route = app.sio.handlers["/"]["task_queue_run"]
    task = asyncio.create_task(route("client", {"id": identifier}))
    for _ in range(30):
        if app.dispatcher.pending:
            break
        await asyncio.sleep(0.01)
    assert app.dispatcher.pending
    result = await route("client", {"id": identifier})
    assert result["code"] == "task_busy"
    assert not [
        call
        for call in app.sio.emit.await_args_list
        if call.args[0] == "task_queue_approval_closed"
    ]
    await app.sio.handlers["/"]["task_queue_cancel"]("client", {"id": identifier})
    await task
    closed = [
        call
        for call in app.sio.emit.await_args_list
        if call.args[0] == "task_queue_approval_closed"
    ]
    assert len(closed) == 1
