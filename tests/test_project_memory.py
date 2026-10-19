"""Synthetic notes, isolated protected profiles and fixture providers only."""

import asyncio
import base64
import json
import time
import uuid
import pytest
from services.memory_contracts import (
    MemoryWrite,
    MemoryForget,
    MemoryRetention,
    MemoryRestore,
    MemoryRestoreApply,
)
from services.project_memory import ProjectMemory
from services.conversation import ConversationRequest
from services.tools import ServiceError
from llm.base import LLMResponse, ToolCall, MessageRole


@pytest.fixture
def memory_app(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update(
        {"desktop": "owner", "other": "other", "tray": "owner", "control": "owner"}
    )
    app.sessions.roles.update(
        {"desktop": "renderer", "other": "renderer", "tray": "resident", "control": "workspace"}
    )
    return app


def project(app):
    return app.projects.get_current_project_path()


def snapshot(app):
    return app.memory.snapshot("owner", project(app), include_archived=True)


def write(app, **changes):
    request = MemoryWrite(
        revision=snapshot(app)["revision"],
        id=uuid.uuid4(),
        title="Enclosure dimensions",
        text="The enclosure needs a 42 mm clearance.",
        **changes,
    )
    return app.memory.write("owner", project(app), request)


def request(app, **changes):
    return {
        "revision": snapshot(app)["revision"],
        "id": str(uuid.uuid4()),
        "title": "Fixture title",
        "text": "Fixture private fact",
        **changes,
    }


def test_protected_storage_restart_search_and_no_plaintext_index(memory_app):
    app = memory_app
    saved = write(app, tags=["fabrication"], source="Owner design review")
    app.memory = ProjectMemory(app)
    found = app.memory.snapshot("owner", project(app), "fabrication")
    assert found["items"] == saved["items"] and found["provider_used"] is False
    assert not app.memory.snapshot("owner", project(app), "doesnotexist")["items"]
    with app.database.connection() as db:
        encrypted = db.execute(
            "SELECT payload FROM documents WHERE kind=?", (app.memory.kind,)
        ).fetchone()[0]
        assert b"42 mm" not in encrypted and b"Enclosure dimensions" not in encrypted
    assert not list(project(app).glob("*memory*"))


def test_revision_conflicts_and_forget_do_not_replay_saved_notes(memory_app):
    app = memory_app
    args = MemoryWrite(**request(app))
    saved = app.memory.write("owner", project(app), args)
    with pytest.raises(ServiceError, match="changed"):
        app.memory.write("owner", project(app), args)
    note = saved["items"][0]
    edit = MemoryWrite(
        **{**args.model_dump(), "revision": saved["revision"], "text": "Corrected fixture"}
    )
    updated = app.memory.write("owner", project(app), edit)
    assert updated["items"][0]["version"] == 2
    assert updated["items"][0]["created_at"] == note["created_at"]
    app.memory.forget("owner", project(app), MemoryForget(revision=updated["revision"], id=args.id))
    with pytest.raises(ServiceError):
        app.memory.write("owner", project(app), edit)
    assert not snapshot(app)["items"]


@pytest.mark.parametrize("sid", ["other", "tray", "control", "unknown", "locked"])
@pytest.mark.parametrize(
    "route",
    [
        "memory_list",
        "memory_write",
        "memory_forget",
        "memory_retention",
        "memory_export",
        "memory_restore_preview",
        "memory_restore_apply",
    ],
)
@pytest.mark.asyncio
async def test_every_route_requires_unlocked_owner_renderer(memory_app, sid, route):
    if sid == "locked":
        memory_app.settings["face_auth_enabled"] = True
        sid = "desktop"
    response = await memory_app.sio.handlers["/"][route](sid, {})
    assert not response["ok"]
    assert response["code"] in ("authentication_required", "permission_denied")


def test_owner_project_isolation_and_outside_project_rejected(memory_app, tmp_path):
    app = memory_app
    write(app)
    second = app.projects.projects_dir / "second"
    second.mkdir()
    assert not app.memory.snapshot("owner", second)["items"]
    for owner, path in (("other", project(app)), ("owner", tmp_path)):
        with pytest.raises(ServiceError):
            app.memory.snapshot(owner, path)


def test_expiry_reduction_archive_and_backward_clock(memory_app):
    app = memory_app
    now = time.time()
    app.memory.clock = lambda: now
    saved = write(app, assistant_enabled=True, archived=True)
    assert not app.memory.snapshot("owner", project(app))["items"]
    assert not app.memory.context("owner", project(app), "enclosure", "desktop")["items"]
    shorter = app.memory.retention(
        "owner", project(app), MemoryRetention(revision=saved["revision"], days=1)
    )
    longer = app.memory.retention(
        "owner", project(app), MemoryRetention(revision=shorter["revision"], days=365)
    )
    assert longer["items"][0]["expires_at"] == now + 86400
    app.memory.clock = lambda: now - 100
    with pytest.raises(ServiceError, match="clock"):
        snapshot(app)
    app.memory.clock = lambda: now + 86401
    assert not snapshot(app)["items"]


@pytest.mark.asyncio
async def test_background_expiry_and_shutdown_clear_preview(memory_app):
    app = memory_app
    now = time.time()
    app.memory.clock = lambda: now
    write(app, retention_days=1)
    app.memory.clock = lambda: now + 86401
    task = asyncio.create_task(app.memory.maintain())
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    key, _ = app.memory.scope("owner", project(app))
    with app.database.connection() as db:
        assert not app.database.get(db, app.memory.kind, key)["items"]
    app.memory.previews["fixture"] = {}
    await app.close()
    assert not app.memory.previews


def test_export_preview_restore_is_encrypted_scoped_non_overwriting_and_sharing_off(memory_app):
    app = memory_app
    first = write(app, assistant_enabled=True)
    backup = app.memory.export("owner", project(app))
    assert backup["portable"] is False and backup["protection"] == "windows_user_bound"
    assert b"42 mm" not in base64.b64decode(backup["backup"])
    same = app.memory.preview("owner", project(app), MemoryRestore(backup=backup["backup"]))
    assert not same["items"] and same["skipped"] == 1
    app.memory.forget(
        "owner", project(app), MemoryForget(revision=first["revision"], id=first["items"][0]["id"])
    )
    preview = app.memory.preview("owner", project(app), MemoryRestore(backup=backup["backup"]))
    assert len(preview["items"]) == 1 and not preview["items"][0]["assistant_enabled"]
    restored = app.memory.restore(
        "owner",
        project(app),
        MemoryRestoreApply(revision=preview["revision"], preview_id=preview["preview_id"]),
    )
    assert len(restored["items"]) == 1 and restored["items"][0]["text"] == first["items"][0]["text"]
    with pytest.raises(ServiceError):
        app.memory.restore(
            "owner",
            project(app),
            MemoryRestoreApply(revision=preview["revision"], preview_id=preview["preview_id"]),
        )
    other = app.projects.projects_dir / "other_project"
    other.mkdir()
    with pytest.raises(ServiceError, match="another owner or project"):
        app.memory.preview("owner", other, MemoryRestore(backup=backup["backup"]))


def test_recovery_preview_expiry_stale_change_and_expired_backup(memory_app):
    app = memory_app
    now = time.time()
    app.memory.clock = lambda: now
    saved = write(app, retention_days=1)
    backup = app.memory.export("owner", project(app))
    app.memory.forget(
        "owner", project(app), MemoryForget(revision=saved["revision"], id=saved["items"][0]["id"])
    )
    preview = app.memory.preview("owner", project(app), MemoryRestore(backup=backup["backup"]))
    write(app)
    with pytest.raises(ServiceError, match="changed"):
        app.memory.restore(
            "owner",
            project(app),
            MemoryRestoreApply(revision=preview["revision"], preview_id=preview["preview_id"]),
        )
    app.memory.clock = lambda: now + 121
    with pytest.raises(ServiceError, match="expired"):
        app.memory.restore(
            "owner",
            project(app),
            MemoryRestoreApply(revision=preview["revision"], preview_id=preview["preview_id"]),
        )
    app.memory.clock = lambda: now + 86401
    assert not app.memory.preview("owner", project(app), MemoryRestore(backup=backup["backup"]))[
        "items"
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"text": "x" * 4001},
        {"assistant_enabled": 1},
        {"retention_days": 366},
        {"tags": ["x"] * 9},
        {"source": ""},
        {"category": "system_instruction"},
        {"unexpected": True},
    ],
)
def test_write_contract_is_strict_and_bounded(memory_app, changes):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryWrite(**request(memory_app, **changes))


def test_collection_count_and_byte_capacity_are_atomic(memory_app):
    app = memory_app
    value = write(app)
    key, _ = app.memory.scope("owner", project(app))
    with app.database.transaction() as db:
        saved = app.database.get(db, app.memory.kind, key)
        item = value["items"][0]
        saved["items"] = {str(uuid.uuid4()): item for _ in range(200)}
        app.database.put(db, app.memory.kind, key, saved)
    with pytest.raises(ServiceError, match="200"):
        write(app)
    with app.database.transaction() as db:
        saved["items"] = {item["id"]: item}
        saved["items"][item["id"]]["text"] = "x" * 750000
        app.database.put(db, app.memory.kind, key, saved)
    with pytest.raises(ServiceError, match="size limit"):
        write(app)
    with app.database.connection() as db:
        assert len(app.database.get(db, app.memory.kind, key)["items"]) == 1


@pytest.mark.asyncio
async def test_only_opted_in_relevant_notes_reach_desktop_provider_and_sources_are_preserved(
    memory_app,
):
    app = memory_app
    write(app, assistant_enabled=False)
    captured = []
    app.settings["tool_permissions"]["read_file"] = "deny"

    class Provider:
        async def generate(self, messages, **kwargs):
            captured.append(messages)
            if len(captured) == 2:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id="fixture", name="read_file", args={"path": "not-opened.txt"})
                    ]
                )
            return LLMResponse(text="Fixture answer")

        async def close(self):
            pass

    app.conversation.provider_factory = Provider
    first = await app.conversation.reply(
        "owner", ConversationRequest(text="enclosure clearance"), project(app), origin_sid="desktop"
    )
    assert not first.memory_sources
    assert not any("42 mm" in message.content for message in captured[-1])
    opted = write(app, assistant_enabled=True)
    req = ConversationRequest(text="enclosure clearance")
    reply = await app.conversation.reply("owner", req, project(app), origin_sid="desktop")
    assert len(captured[-2]) == 1
    assert captured[-1][-1].role == MessageRole.TOOL
    assert captured[-1][0].content.startswith("enclosure clearance\n\nUNTRUSTED")
    assert reply.memory_sources and any(
        "UNTRUSTED PROJECT MEMORY DATA" in message.content and "42 mm" in message.content
        for message in captured[-1]
    )
    restored = app.conversation.restore("owner", req.conversation_id, project(app))
    assert restored[-1]["memory_sources"][0]["title"] == "Enclosure dimensions"
    assert not any("UNTRUSTED PROJECT MEMORY DATA" in item["content"] for item in restored)
    assert not app.memory.context("owner", project(app), "enclosure", "tray")["items"]
    assert not app.memory.context("other", project(app), "enclosure", "other")["items"]
    assert app.mobile.chat.memory is None
    assert len(opted["items"]) == 2


@pytest.mark.asyncio
async def test_forget_during_provider_request_rejects_stale_answer(memory_app):
    app = memory_app
    saved = write(app, assistant_enabled=True)

    class Provider:
        async def generate(self, messages, **kwargs):
            app.memory.forget(
                "owner",
                project(app),
                MemoryForget(revision=saved["revision"], id=saved["items"][0]["id"]),
            )
            return LLMResponse(text="Stale fixture answer")

        async def close(self):
            pass

    app.conversation.provider_factory = Provider
    with pytest.raises(ServiceError, match="changed"):
        await app.conversation.reply(
            "owner",
            ConversationRequest(text="enclosure clearance"),
            project(app),
            origin_sid="desktop",
        )
    assert not snapshot(app)["items"]


def test_retrieval_never_executes_memory_and_has_small_context(memory_app):
    app = memory_app
    for _ in range(8):
        write(app, assistant_enabled=True)
    context = app.memory.context("owner", project(app), "enclosure clearance", "desktop")
    assert 0 < len(context["items"]) <= 4
    assert len(json.dumps(context["items"])) < 7000
    assert not any(name.startswith("memory_") for name in app.dispatcher.tools)
    assert not {"torch", "sentence_transformers", "faiss"} & set(__import__("sys").modules)
