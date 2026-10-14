"""Restart, concurrency, migration and privacy checks without paid or device actions."""

import asyncio
import datetime as dt
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock

import pytest

from core.durable_reminders import local_instant
from core.reminder_store import ReminderStore
from llm.base import LLMResponse, ToolCall
from project_manager import ProjectManager
from services.conversation import ConversationRequest, ConversationService
from services.sessions import SessionStore
from services.storage import Database, StorageError
from services.tools import ServiceError, ToolDispatcher, register_project_tools


def make_store(tmp_path):
    return ReminderStore(tmp_path, database=Database(tmp_path / "private"))


def test_private_payloads_and_backups_are_protected(tmp_path):
    source = tmp_path / "reminders.jsonl"
    private = "unique secret appointment task"
    record = {
        "id": str(uuid.uuid4()),
        "task": private,
        "trigger_at": 100,
        "created_at": 1,
        "recurring": None,
        "status": "pending",
    }
    raw = (json.dumps(record) + "\n").encode()
    source.write_bytes(raw)
    store = make_store(tmp_path)
    assert source.read_bytes() == raw
    assert store.get(record["id"]).task == private
    for path in (tmp_path / "private").rglob("*"):
        if path.is_file():
            assert private.encode() not in path.read_bytes()
    backup = next((tmp_path / "private" / "migration-backups").glob("*.dpapi"))
    restored = store.database.decode(f"backup:{backup.stem}", backup.read_bytes())
    assert bytes.fromhex(restored["bytes_hex"]) == raw
    assert len(make_store(tmp_path).list_reminders()) == 1


def test_database_rejects_foreign_schema_and_swapped_payload(tmp_path):
    database = Database(tmp_path)
    with database.transaction() as db:
        database.put(db, "test", "first", {"secret": "private"})
        payload = db.execute("SELECT payload FROM documents").fetchone()[0]
        with pytest.raises(StorageError):
            database.decode("test:other", payload)
        db.execute("PRAGMA user_version=99")
    with pytest.raises(StorageError, match="Unsupported"):
        Database(tmp_path)


def test_failed_migration_is_atomic_and_repairable(tmp_path):
    first = {"id": str(uuid.uuid4()), "task": "legacy", "trigger_at": 100, "created_at": 1}
    source = tmp_path / "reminders.jsonl"
    raw = json.dumps(first) + "\ninvalid-json\n"
    source.write_text(raw)
    with pytest.raises(StorageError, match="validation"):
        make_store(tmp_path)
    assert source.read_text() == raw
    database = Database(tmp_path / "private")
    with database.connection() as db:
        assert database.all(db, "reminder") == []
        assert db.execute("SELECT * FROM migrations").fetchall() == []
    source.write_text(json.dumps(first) + "\n")
    assert len(make_store(tmp_path).list_reminders()) == 1


def test_migration_transaction_rollback(tmp_path, monkeypatch):
    source = tmp_path / "reminders.jsonl"
    records = [
        {"id": str(uuid.uuid4()), "task": f"item {i}", "trigger_at": 100, "created_at": 1}
        for i in range(2)
    ]
    source.write_text("\n".join(json.dumps(value) for value in records))
    database = Database(tmp_path / "private")
    original = database.put
    count = 0

    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected disk failure")
        original(*args)

    monkeypatch.setattr(database, "put", fail_second)
    with pytest.raises(OSError):
        ReminderStore(tmp_path, database=database)
    with database.connection() as db:
        assert database.all(db, "reminder") == []
        assert db.execute("SELECT * FROM migrations").fetchall() == []
    assert len(make_store(tmp_path).list_reminders()) == 2


def test_simultaneous_polls_claim_one_delivery(tmp_path):
    store = make_store(tmp_path)
    reminder = store.add_reminder("due", 50)
    other = make_store(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(
            pool.map(lambda value: value.claim_deliveries("owner", now=100), [store, other])
        )
    assert sum(map(len, batches)) == 1
    assert make_store(tmp_path).get(reminder.id).status == "triggered"


def test_restart_retries_same_delivery_and_ack_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    store.add_reminder("due", 50)
    first = store.claim_deliveries("owner", now=100)[0]
    restarted = make_store(tmp_path)
    assert restarted.claim_deliveries("owner", now=110) == []
    retry = restarted.claim_deliveries("owner", now=131)[0]
    assert retry["delivery_id"] == first["delivery_id"]
    assert retry["attempts"] == 2
    assert not restarted.acknowledge(first["delivery_id"], "other")
    assert restarted.acknowledge(first["delivery_id"], "owner")
    assert restarted.acknowledge(first["delivery_id"], "owner")
    assert restarted.claim_deliveries("owner", now=200) == []
    assert len(make_store(tmp_path).open_deliveries("owner")) == 1
    assert restarted.acknowledge(first["delivery_id"], "owner", complete=True)
    assert restarted.acknowledge(first["delivery_id"], "owner", complete=True)
    assert make_store(tmp_path).open_deliveries("owner") == []


@pytest.mark.parametrize("action", ["cancel", "snooze"])
def test_edit_retires_old_delivery_and_stale_ack_cannot_finish_new_reminder(
    tmp_path, monkeypatch, action
):
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: 100)
    store = make_store(tmp_path)
    reminder = store.add_reminder("due", 50)
    first = store.claim_deliveries("owner", now=100)[0]
    if action == "cancel":
        assert store.cancel(reminder.id)
    else:
        assert store.snooze(reminder.id, 5).trigger_at == 400
    assert not store.acknowledge(first["delivery_id"], "owner", complete=True)
    assert store.open_deliveries("owner") == []
    later = store.claim_deliveries("owner", now=401)
    if action == "snooze":
        assert len(later) == 1 and later[0]["delivery_id"] != first["delivery_id"]
    else:
        assert later == []


def test_stale_and_foreign_alert_actions_are_rejected(tmp_path):
    store = make_store(tmp_path)
    reminder = store.add_reminder("due", 50)
    delivery = store.claim_deliveries("owner", now=100)[0]
    assert not store.edit_delivery(delivery["delivery_id"], "other", 5)
    assert not store.edit_delivery(delivery["delivery_id"], "owner", -1)
    assert store.edit_delivery(delivery["delivery_id"], "owner", 5)
    assert not store.edit_delivery(delivery["delivery_id"], "owner", 5)
    assert store.get(reminder.id).status == "pending"


@pytest.mark.parametrize("recurrence", ["daily", "weekly", "weekdays"])
def test_missed_recurrences_coalesce_and_keep_local_clock(tmp_path, recurrence):
    store = make_store(tmp_path)
    start = local_instant(dt.datetime(2026, 10, 2, 9), "Asia/Kuala_Lumpur")
    now = local_instant(dt.datetime(2026, 10, 12, 10), "Asia/Kuala_Lumpur")
    reminder = store.add_reminder("daily task", start, recurrence)
    assert len(store.claim_deliveries("owner", now=now)) == 1
    scheduled = store.get(reminder.id)
    assert scheduled.trigger_at > now
    assert dt.datetime.fromtimestamp(scheduled.trigger_at, ZoneInfo(scheduled.timezone)).hour == 9
    assert store.claim_deliveries("owner", now=now) == []
    delivery = store.open_deliveries("owner")[0]
    assert store.acknowledge(delivery["delivery_id"], "owner", complete=True)
    assert store.get(reminder.id).status == "pending"


def test_dst_gap_and_overlap_policy(tmp_path):

    gap = local_instant(dt.datetime(2026, 3, 8, 2, 30), "America/New_York")
    assert dt.datetime.fromtimestamp(gap, ZoneInfo("America/New_York")).hour == 3
    overlap = local_instant(dt.datetime(2026, 11, 1, 1, 30), "America/New_York")
    assert dt.datetime.fromtimestamp(overlap, ZoneInfo("America/New_York")).fold == 0
    store = make_store(tmp_path)
    start = local_instant(dt.datetime(2026, 3, 7, 9), "America/New_York")
    reminder = store.add_reminder("DST daily", start, "daily", timezone="America/New_York")
    store.claim_deliveries("owner", now=start)
    assert store.get(reminder.id).trigger_at - start == 23 * 3600


def test_today_uses_reminder_timezone_not_utc(tmp_path, monkeypatch):
    now = local_instant(dt.datetime(2026, 10, 13, 1), "Asia/Kuala_Lumpur")
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: now)
    store = make_store(tmp_path)
    reminder = store.add_reminder(
        "tonight", local_instant(dt.datetime(2026, 10, 13, 22), "Asia/Kuala_Lumpur")
    )
    assert [record.id for record in store.list_reminders("today")] == [reminder.id]


def provider(responses):
    items = iter(responses)
    result = type("FakeProvider", (), {})()

    async def generate(*args, **kwargs):
        return next(items)

    result.generate = AsyncMock(side_effect=generate)
    result.close = AsyncMock()
    return result


@pytest.mark.asyncio
async def test_session_restart_restores_history_and_does_not_replay_tools(tmp_path):
    dispatcher = ToolDispatcher(lambda: {"write_file": False})
    register_project_tools(dispatcher)
    first = provider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall("call", "write_file", {"path": "result.txt", "content": "created"})
                ]
            ),
            LLMResponse(text="Saved the file."),
        ]
    )
    database = Database(tmp_path / "private")
    service = ConversationService(dispatcher, lambda: first, store=SessionStore(database))
    request = ConversationRequest(text="create a file")
    result = await service.reply("owner", request, tmp_path)
    (tmp_path / "result.txt").write_text("user edited")
    never = provider([])
    restarted = ConversationService(
        dispatcher, lambda: never, store=SessionStore(Database(tmp_path / "private"))
    )
    assert await restarted.reply("owner", request, tmp_path) == result
    assert (tmp_path / "result.txt").read_text() == "user edited"
    never.generate.assert_not_called()
    history = restarted.restore("owner", request.conversation_id, tmp_path)
    assert [value["role"] for value in history] == ["user", "assistant"]
    assert history[-1]["content"] == "Saved the file."
    with pytest.raises(ServiceError, match="new conversation"):
        restarted.restore("other", request.conversation_id, tmp_path)
    with pytest.raises(ServiceError, match="new conversation"):
        restarted.restore("owner", request.conversation_id, tmp_path / "other")


@pytest.mark.asyncio
async def test_uncertain_request_never_replays_and_conflicting_identity_rejected(tmp_path):
    ledger = SessionStore(Database(tmp_path / "private"))
    request = ConversationRequest(text="perform an action")
    key, rid = str(request.conversation_id), str(request.request_id)
    ledger.claim(key, "owner", str(tmp_path.resolve()), rid, request.text)
    fake = provider([])
    service = ConversationService(ToolDispatcher(lambda: {}), lambda: fake, store=ledger)
    with pytest.raises(ServiceError) as raised:
        await service.reply("owner", request, tmp_path)
    assert raised.value.code == "request_uncertain"
    changed = request.model_copy(update={"text": "different action"})
    with pytest.raises(ServiceError) as raised:
        await service.reply("owner", changed, tmp_path)
    assert raised.value.code == "request_conflict"
    fake.generate.assert_not_called()


@pytest.mark.asyncio
async def test_failed_request_survives_restart_without_provider_retry(tmp_path):
    def fail():
        raise ServiceError("provider_not_configured", "Configure later.")

    request = ConversationRequest(text="hello")
    service = ConversationService(
        ToolDispatcher(lambda: {}), fail, store=SessionStore(Database(tmp_path))
    )
    with pytest.raises(ServiceError, match="Configure later"):
        await service.reply("owner", request, tmp_path)
    fake = provider([])
    restarted = ConversationService(
        service.dispatcher, lambda: fake, store=SessionStore(Database(tmp_path))
    )
    with pytest.raises(ServiceError, match="Configure later"):
        await restarted.reply("owner", request, tmp_path)
    fake.generate.assert_not_called()


def test_legacy_chat_migration_is_private_non_destructive_and_once(tmp_path):
    source = tmp_path / "chat_history.jsonl"
    source.write_text(json.dumps({"sender": "You", "text": "old chat"}) + "\n")
    raw = source.read_bytes()
    ledger = SessionStore(Database(tmp_path / "private"))
    key = str(uuid.uuid4())
    ledger.migrate_history(key, "owner", str(tmp_path.resolve()), source)
    assert ledger.restore(key, "owner", str(tmp_path.resolve())) == [
        {"role": "user", "content": "old chat"}
    ]
    ledger.migrate_history(key, "owner", str(tmp_path.resolve()), source)
    assert source.read_bytes() == raw
    assert len(ledger.restore(key, "owner", str(tmp_path.resolve()))) == 1


def test_workspace_restores_selected_project_without_touching_artifacts(tmp_path):
    database = Database(tmp_path / "private")
    manager = ProjectManager(str(tmp_path), state_store=database)
    manager.create_project("Design")
    manager.switch_project("Design")
    artifact = manager.get_current_project_path() / "cad" / "part.stl"
    artifact.write_text("existing artifact")
    restarted = ProjectManager(str(tmp_path), state_store=Database(tmp_path / "private"))
    assert restarted.current_project == "Design"
    assert artifact.read_text() == "existing artifact"
    manager.log_chat("You", "protected voice history")
    assert not (manager.get_current_project_path() / "chat_history.jsonl").exists()
    assert restarted.get_recent_chat_history()[-1]["text"] == "protected voice history"


@pytest.mark.asyncio
async def test_transport_failure_retries_persistent_delivery(tmp_path, monkeypatch, application_factory):
    runtime = application_factory()

    store = make_store(tmp_path)
    store.add_reminder("offline reminder", 1)
    runtime.delivery.reminders = runtime.reminder_transport.store = store
    runtime.sessions.principals["socket"] = "owner"
    monkeypatch.setattr(runtime.dispatcher, "authenticated", lambda _: True)
    emit = AsyncMock(side_effect=OSError("fake disconnected transport"))
    monkeypatch.setattr(runtime.sio, "emit", emit)
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: 100)
    with pytest.raises(OSError):
        await runtime.delivery.deliver_reminders_once()
    first = emit.call_args.args[1]
    monkeypatch.setattr(runtime.sio, "emit", AsyncMock())
    monkeypatch.setattr("core.durable_reminders.time.time", lambda: 131)
    await runtime.delivery.deliver_reminders_once()
    second = runtime.sio.emit.call_args.args[1]
    assert first["delivery_id"] == second["delivery_id"]
    await runtime.reminder_transport.acknowledge_reminder("socket", {"delivery_id": second["delivery_id"]})
    await runtime.reminder_transport.dismiss_reminder("socket", {"delivery_id": second["delivery_id"]})
    assert store.open_deliveries("owner") == []


@pytest.mark.asyncio
async def test_concurrent_session_services_reject_second_running_request(tmp_path):
    database = Database(tmp_path / "private")
    ledger = SessionStore(database)
    entered, release = asyncio.Event(), asyncio.Event()
    fake = provider([])

    async def blocked(*args, **kwargs):
        entered.set()
        await release.wait()
        return LLMResponse(text="complete")

    fake.generate = AsyncMock(side_effect=blocked)
    dispatcher = ToolDispatcher(lambda: {})
    first = ConversationService(dispatcher, lambda: fake, store=ledger)
    second = ConversationService(
        dispatcher, lambda: provider([]), store=SessionStore(Database(tmp_path / "private"))
    )
    request = ConversationRequest(text="first")
    task = asyncio.create_task(first.reply("owner", request, tmp_path))
    await entered.wait()
    try:
        with pytest.raises(ServiceError) as raised:
            await second.reply(
                "owner",
                ConversationRequest(text="second", conversation_id=request.conversation_id),
                tmp_path,
            )
        assert raised.value.code == "conversation_busy"
    finally:
        release.set()
        await task


def test_dst_gap_does_not_shift_subsequent_daily_wall_time(tmp_path):
    store = make_store(tmp_path)
    start = local_instant(dt.datetime(2026, 3, 7, 2, 30), "America/New_York")
    reminder = store.add_reminder("early daily", start, "daily", timezone="America/New_York")
    store.claim_deliveries("owner", now=start)
    gap = store.get(reminder.id).trigger_at
    assert dt.datetime.fromtimestamp(gap, ZoneInfo(reminder.timezone)).hour == 3
    store.claim_deliveries("owner", now=gap)
    normal = dt.datetime.fromtimestamp(
        store.get(reminder.id).trigger_at, ZoneInfo(reminder.timezone)
    )
    assert (normal.hour, normal.minute) == (2, 30)


def test_invalid_chat_migration_keeps_original_and_creates_no_partial_session(tmp_path):
    source = tmp_path / "chat_history.jsonl"
    raw = b'{"sender":"You","text":"valid"}\n{"text":123}\n'
    source.write_bytes(raw)
    ledger = SessionStore(Database(tmp_path / "private"))
    with pytest.raises(StorageError, match="validation"):
        ledger.migrate_history(str(uuid.uuid4()), "owner", str(tmp_path.resolve()), source)
    assert source.read_bytes() == raw
    with ledger.database.connection() as db:
        assert db.execute("SELECT * FROM sessions").fetchall() == []
        assert db.execute("SELECT * FROM migrations").fetchall() == []


@pytest.mark.asyncio
async def test_typed_reminder_tools_use_selected_timezone_and_durable_store(tmp_path):
    from agents.scheduler_agent import SchedulerAgent
    from core.event_bus import EventBus
    from services.scheduler_tools import register_scheduler_tools

    store = make_store(tmp_path)
    dispatcher = ToolDispatcher(lambda: {"create_reminder": False, "list_reminders": False})
    register_scheduler_tools(dispatcher, SchedulerAgent(EventBus(), store), store)
    fake = provider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "reminder",
                        "create_reminder",
                        {
                            "task": "offline scheduled task",
                            "when": "2099-01-02T09:00:00",
                            "timezone": "Asia/Kuala_Lumpur",
                        },
                    )
                ]
            ),
            LLMResponse(text="Reminder created."),
        ]
    )
    service = ConversationService(dispatcher, lambda: fake)
    await service.reply("owner", ConversationRequest(text="remind me"), tmp_path)
    reminder = make_store(tmp_path).list_reminders()[0]
    assert reminder.task == "offline scheduled task"
    assert reminder.trigger_at == local_instant(dt.datetime(2099, 1, 2, 9), "Asia/Kuala_Lumpur")


@pytest.mark.asyncio
async def test_direct_reminder_edit_enforces_shared_denial(tmp_path, monkeypatch, application_factory):
    runtime = application_factory()
    from agents.scheduler_agent import SchedulerAgent
    from core.event_bus import EventBus
    from services.scheduler_tools import register_scheduler_tools

    store = make_store(tmp_path)
    reminder = store.add_reminder("protected reminder", 100)
    dispatcher = ToolDispatcher(lambda: {"cancel_reminder": "deny"})
    register_scheduler_tools(dispatcher, SchedulerAgent(EventBus(), store), store)
    runtime.reminder_transport.dispatcher = dispatcher
    runtime.sessions.principals["socket"] = "owner"
    runtime.delivery.reminders = runtime.reminder_transport.store = store
    emit = AsyncMock()
    monkeypatch.setattr(runtime.sio, "emit", emit)
    await runtime.reminder_transport.cancel_reminder("socket", {"reminder_id": reminder.id})
    assert store.get(reminder.id).status == "pending"
    assert emit.call_args.args[0] == "error"
    assert emit.call_args.args[1]["code"] == "permission_denied"
