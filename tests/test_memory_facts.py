"""S6.1 long-term memory: the encrypted fact store, its keyed-hash FTS5 index, the brain's
memory tools and the owner-only facts_* routes (docs/MEMORY.md)."""

import asyncio
import json
import re

import pytest
from pydantic import ValidationError

from services import memory_facts
from services.memory_facts import (
    FactForget,
    FactRemember,
    FactSearch,
    FactStore,
    looks_secret,
    luhn_valid,
    migrate,
    score,
)
from services.storage import Database, StorageError
from services.tools import ServiceError

DAY = 86400.0
START = 1_790_000_000.0  # 21 September 2026


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def database(tmp_path):
    return Database(tmp_path / "private")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(database, clock):
    return FactStore(database, clock=clock)


def fts_rows(database):
    with database.connection() as db:
        return db.execute("SELECT fact_id, subject, text FROM memory_facts_fts").fetchall()


# --- schema and migration -------------------------------------------------------------------
def test_schema_and_migration_are_idempotent(database, clock):
    FactStore(database, clock=clock)
    FactStore(database, clock=clock)
    migrate(database)
    with database.connection() as db:
        markers = db.execute(
            "SELECT id FROM migrations WHERE id LIKE 'memory_facts:%'"
        ).fetchall()
        columns = [row["name"] for row in db.execute("PRAGMA table_info(memory_facts)")]
        tables = {
            row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert [row["id"] for row in markers] == ["memory_facts:v1"]
    assert columns == [
        "id", "kind", "subject", "text", "confidence", "pinned", "sensitivity",
        "source_conversation_id", "source_turn", "created_at", "updated_at", "valid_from",
        "valid_to", "superseded_by",
    ]
    assert {"memory_facts", "memory_facts_fts"} <= tables


def test_a_changed_migration_record_fails_clearly(database, clock):
    FactStore(database, clock=clock)
    with database.transaction() as db:
        db.execute("UPDATE migrations SET digest='x' WHERE id='memory_facts:v1'")
    with pytest.raises(StorageError, match="memory schema"):
        FactStore(database, clock=clock)


def test_missing_fts5_fails_clearly(database, monkeypatch):
    monkeypatch.setattr(memory_facts, "fts5_available", lambda: False)
    with pytest.raises(StorageError, match="FTS5"):
        FactStore(database)


def test_fts5_is_available_in_this_build():
    assert memory_facts.fts5_available() is True


def test_check_constraints_reject_unknown_kind_and_sensitivity(store, database):
    with pytest.raises(ServiceError):
        store.add("secret", "x", "y")
    with pytest.raises(ServiceError):
        store.add("profile", "x", "y", sensitivity="public")
    import sqlite3

    with database.connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO memory_facts(id, kind, subject, text, created_at) "
            "VALUES('a', 'nonsense', x'00', x'00', '2026')"
        )


def test_text_is_encrypted_and_the_index_holds_only_hashes(store, database):
    fact = store.add("preference", "Coffee", "Likes kopi o kosong in the morning")
    with database.connection() as db:
        row = db.execute("SELECT subject, text FROM memory_facts").fetchone()
    assert isinstance(row["text"], bytes) and b"kopi" not in row["text"]
    assert b"Coffee" not in row["subject"]
    [(fact_id, subject, text)] = fts_rows(database)
    assert fact_id == fact["id"]
    assert "kopi" not in text and "coffee" not in subject.lower()
    assert re.fullmatch(r"([0-9a-f]{20} ?)+", text)
    raw = (database.path).read_bytes()
    assert b"kopi" not in raw and b"kosong" not in raw


# --- writes and FTS sync --------------------------------------------------------------------
def test_add_update_supersede_forget_keep_the_index_in_sync(store, database, clock):
    fact = store.add("place", "Office", "Works at Menara KL on level 12",
                     source_conversation_id="c-1", source_turn=3)
    assert fact["kind"] == "place" and fact["source_conversation_id"] == "c-1"
    assert fact["source_turn"] == 3 and fact["pinned"] is False
    assert fact["created_at"].startswith("2026-09")
    assert [f["id"] for f in store.search("Menara")] == [fact["id"]]

    clock.now += DAY
    edited = store.update(fact["id"], text="Works at Exchange 106 on level 30")
    assert edited["id"] == fact["id"] and edited["updated_at"] > edited["created_at"]
    assert store.search("Menara") == []
    assert [f["id"] for f in store.search("Exchange")] == [fact["id"]]
    assert len(fts_rows(database)) == 1

    clock.now += DAY
    newer = store.supersede(fact["id"], "Works from home in Bangsar")
    old = store.get(fact["id"])
    assert old["superseded_by"] == newer["id"] and old["valid_to"] == newer["valid_from"]
    assert old["text"] == "Works at Exchange 106 on level 30"  # never overwritten
    assert newer["subject"] == "Office" and newer["kind"] == "place"
    assert [f["id"] for f in store.search("works")] == [newer["id"]]
    assert {f["id"] for f in store.search("works", include_superseded=True)} == {
        fact["id"], newer["id"],
    }
    with pytest.raises(ServiceError) as again:
        store.supersede(fact["id"], "Something else")
    assert again.value.code == "memory_superseded"

    assert store.forget(newer["id"]) is True
    assert store.get(newer["id"]) is None and store.forget(newer["id"]) is False
    assert [row["fact_id"] for row in fts_rows(database)] == [fact["id"]]
    assert store.search("Bangsar", include_superseded=True) == []


def test_update_of_a_missing_fact_is_not_found(store):
    with pytest.raises(ServiceError) as error:
        store.update("00000000-0000-4000-8000-000000000000", text="x")
    assert error.value.code == "memory_not_found"


def test_subject_defaults_to_the_first_words(store):
    fact = store.add("preference", None, "Prefers window seats on long flights abroad")
    assert fact["subject"] == "Prefers window seats on long flights"


def test_list_get_and_kinds(store, clock):
    a = store.add("person", "Aisyah", "Sister, lives in Penang")
    clock.now += 10
    b = store.add("routine", "Gym", "Gym on Tuesday and Thursday evenings")
    assert [f["id"] for f in store.list()] == [b["id"], a["id"]]
    assert [f["id"] for f in store.list("person")] == [a["id"]]
    assert store.get(a["id"])["text"] == "Sister, lives in Penang"
    assert store.get("missing") is None
    with pytest.raises(ServiceError):
        store.list("unknown")


def test_expired_facts_are_not_current(store, clock):
    fact = store.add("episode", "Trip", "In Tokyo this week", valid_to="2026-09-30")
    assert store.search("Tokyo")
    clock.now += 30 * DAY
    assert store.search("Tokyo") == [] and store.list() == []
    assert store.get(fact["id"]) is not None


# --- ranking --------------------------------------------------------------------------------
def test_bm25_ranks_the_better_match_first(store, clock):
    for index in range(6):
        store.add("preference", f"Filler {index}", f"Unrelated note number {index}")
    weak = store.add("preference", "Drinks", "Likes tea")
    clock.now += 100 * DAY  # the strong match is older, yet still wins
    strong = store.add("preference", "Tea", "Likes teh tarik, tea with milk")
    clock.now += 200 * DAY
    store.update(weak["id"], text="Likes tea sometimes")  # freshly edited
    ids = [f["id"] for f in store.search("tea")]
    assert ids[:2] == [strong["id"], weak["id"]]


def test_recency_breaks_ties(store, clock):
    for index in range(6):
        store.add("preference", f"Filler {index}", f"Unrelated note number {index}")
    old = store.add("routine", "Swim", "Swims on Sunday")
    clock.now += 365 * DAY
    new = store.add("routine", "Swim", "Swims on Sunday")
    assert [f["id"] for f in store.search("swims sunday")][:2] == [new["id"], old["id"]]


def test_score_formula():
    assert score(2.0, 0) == pytest.approx(3.0)
    assert score(2.0, 90) == pytest.approx(2.5)
    assert score(2.0, 100_000) == pytest.approx(2.0, rel=1e-6)


def test_search_limit_and_empty_queries(store):
    for index in range(12):
        store.add("preference", "Music", f"Likes song {index} by the band")
    assert len(store.search("band")) == 8
    assert len(store.search("band", limit=3)) == 3
    assert store.search("") == [] and store.search("the and of") == []


# --- query sanitising -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        '"', 'tea"', '"tea" OR "*"', "tea*", "*", "-tea", "tea - coffee", "NEAR(tea coffee, 2)",
        "tea AND coffee", "NOT tea", "subject:tea", "{subject text}: tea", "(tea", "^tea",
        "tea + coffee", "'; DROP TABLE memory_facts; --", "\x00tea", "teh\u200b tarik",
    ],
)
def test_fts_queries_are_sanitised(store, query):
    store.add("preference", "Tea", "Likes teh tarik and coffee")
    expression = store.match_expression(query)
    assert expression is None or re.fullmatch(
        r'"[0-9a-f]{20}"( OR "[0-9a-f]{20}")*', expression
    )
    store.search(query)  # never raises an FTS5 syntax error
    assert store.list()  # nothing dropped


def test_operator_words_are_plain_terms(store):
    fact = store.add("episode", "Book club", "Read NEAR Dark and NOT the sequel")
    assert [f["id"] for f in store.search("NEAR")] == [fact["id"]]
    assert store.search("tea*") == []  # no prefix queries


# --- pinned and pause -----------------------------------------------------------------------
def test_pinned_lists_current_pinned_facts_profile_first(store):
    place = store.add("place", "Home", "Lives in Shah Alam", pinned=True)
    name = store.add("profile", "Name", "Goes by Hiro", pinned=True)
    store.add("preference", "Tea", "Likes teh tarik")
    assert [f["id"] for f in store.pinned()] == [name["id"], place["id"]]
    newer = store.supersede(place["id"], "Lives in Subang Jaya")
    assert newer["pinned"] is True
    assert [f["id"] for f in store.pinned()] == [name["id"], newer["id"]]
    store.update(name["id"], pinned=False)
    assert [f["id"] for f in store.pinned()] == [newer["id"]]


def test_pause_blocks_extractor_and_assistant_writes_but_not_the_owner(store):
    fact = store.add("preference", "Tea", "Likes teh tarik", origin="extractor")
    assert store.is_paused() is False
    store.set_paused(True)
    assert store.is_paused() is True
    for origin in ("extractor", "assistant"):
        with pytest.raises(ServiceError) as error:
            store.add("preference", "Coffee", "Likes coffee", origin=origin)
        assert error.value.code == "memory_paused"
        with pytest.raises(ServiceError):
            store.update(fact["id"], text="Likes tea", origin=origin)
        with pytest.raises(ServiceError):
            store.supersede(fact["id"], "Likes tea", origin=origin)
    owner = store.add("preference", "Coffee", "Likes coffee")
    store.update(owner["id"], pinned=True)
    assert store.forget(fact["id"]) is True
    store.set_paused(False)
    store.add("preference", "Juice", "Likes juice", origin="extractor")
    with pytest.raises(ServiceError):
        store.set_paused("yes")


def test_pause_is_stored_in_the_database(database, clock):
    FactStore(database, clock=clock).set_paused(True)
    assert FactStore(database, clock=clock).is_paused() is True


# --- secrets --------------------------------------------------------------------------------
SECRETS = [
    "My card is 4111 1111 1111 1111",
    "card 4111-1111-1111-1111 expires soon",
    "5500005555555559",
    "Key: sk-ant-api03-abcdefghijklmnop",
    "the maps key AIzaSyA1234567890abcdefghijklmnopq",
    "token AQ.Ab8RN6abcdefghijklmnopqrstuv",
    "My password is hunter2",
    "wifi PASSWORD: Sunny-Day-42",
    "kata laluan ialah rahsia123",
    "my bank PIN is 4821",
    "IC number 900101-14-5678",
]
NOT_SECRETS = [
    "Likes teh tarik",
    "Phone is 012-345 6789",
    "4111 1111 1111 1112 is a nearby number",
    "Changed the password last week",
    "AQ. is an abbreviation",
    "Order 1234567890123 shipped",  # not Luhn-valid
    "Born in 1990, lives at No. 12",
]


@pytest.mark.parametrize("text", SECRETS)
def test_secret_like_text_is_detected(text):
    assert looks_secret(text)


@pytest.mark.parametrize("text", NOT_SECRETS)
def test_ordinary_text_is_not_secret(text):
    assert not looks_secret(text)


def test_luhn():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")


def test_store_refuses_secrets_for_every_origin(store):
    for origin in ("owner", "assistant", "extractor"):
        with pytest.raises(ServiceError) as error:
            store.add("profile", "Login", "My password is hunter2", origin=origin)
        assert error.value.code == "memory_secret"
    fact = store.add("profile", "Card", "Uses a Visa card")
    with pytest.raises(ServiceError):
        store.update(fact["id"], text="Visa 4111 1111 1111 1111")
    assert store.get(fact["id"])["text"] == "Uses a Visa card"


# --- export ---------------------------------------------------------------------------------
def test_export_has_every_fact_and_the_pause_switch(store):
    fact = store.add("preference", "Tea", "Likes teh tarik", source_conversation_id="c-9")
    newer = store.supersede(fact["id"], "Likes teh o ais")
    store.set_paused(True)
    data = json.loads(store.export())
    assert data["format"] == "jarvis-memory" and data["version"] == 1
    assert data["paused"] is True
    assert {f["id"] for f in data["facts"]} == {fact["id"], newer["id"]}
    assert {f["text"] for f in data["facts"]} == {"Likes teh tarik", "Likes teh o ais"}


# --- the brain's tools ----------------------------------------------------------------------
@pytest.fixture
def app(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    for name in ("memory_search", "memory_remember", "memory_forget"):
        app.settings["tool_permissions"].pop(name, None)
    import server

    app.settings["tool_permissions"].update({
        name: server.DEFAULT_SETTINGS["tool_permissions"][name]
        for name in ("memory_search", "memory_remember", "memory_forget")
    })
    return app


def tool_context(app, **extra):
    return {**app.sessions.context("client").tools(), **extra}


def emitted(app, event):
    return [
        (call.args[1], call.kwargs.get("room"))
        for call in app.sio.emit.await_args_list
        if call.args[0] == event
    ]


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


def test_tools_are_registered_with_their_defaults(app):
    import server

    tools = app.dispatcher.tools
    assert tools["memory_search"].arguments is FactSearch
    assert tools["memory_remember"].arguments is FactRemember
    assert tools["memory_forget"].arguments is FactForget
    assert tools["memory_search"].always_ask is False
    assert tools["memory_remember"].always_ask is False
    assert tools["memory_forget"].always_ask is True
    assert tools["memory_forget"].review is not None
    assert all(tools[name].model_visible for name in tools if name.startswith("memory_"))
    defaults = server.DEFAULT_SETTINGS["tool_permissions"]
    assert defaults["memory_search"] is False and defaults["memory_remember"] is False
    assert app.facts.store is not app.memory  # separate from project memory


async def test_search_never_asks(app):
    app.facts.store.add("preference", "Tea", "Likes teh tarik")
    result = await app.dispatcher.dispatch(
        "owner", "memory_search", {"query": "teh tarik"}, tool_context(app),
        request_approval=None,
    )
    [fact] = result["facts"]
    assert set(fact) == {"id", "kind", "subject", "text", "when"}
    assert fact["text"] == "Likes teh tarik" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact["when"])


async def test_remember_stores_with_source_and_shows_a_toast(app):
    long_text = "Prefers the aisle seat on every flight, " * 4
    result = await app.dispatcher.dispatch(
        "owner", "memory_remember", {"text": long_text.strip(), "kind": "preference"},
        tool_context(app, conversation_id="5f3c4a2e-0000-4000-8000-000000000001"),
        request_approval=None,
    )
    assert result["remembered"] is True
    fact = app.facts.store.get(result["id"])
    assert fact["source_conversation_id"] == "5f3c4a2e-0000-4000-8000-000000000001"
    assert fact["kind"] == "preference"
    [(payload, room)] = emitted(app, "memory_remembered")
    assert room == "client"  # renderer rooms only, not the tray
    assert len(payload["text"]) <= 80 and payload["text"].endswith("…")
    assert long_text.startswith(payload["text"][:-1])


async def test_remember_defaults_kind_and_works_without_a_conversation(app):
    result = await app.dispatcher.dispatch(
        "owner", "memory_remember", {"text": "Likes durian"}, tool_context(app),
    )
    fact = app.facts.store.get(result["id"])
    assert fact["kind"] == "preference" and fact["source_conversation_id"] is None
    assert emitted(app, "memory_remembered")[0][0] == {"text": "Likes durian"}


@pytest.mark.parametrize("text", SECRETS)
async def test_remember_refuses_secret_like_text(app, text):
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", "memory_remember", {"text": text}, tool_context(app)
        )
    assert error.value.code == "memory_secret" and "password manager" in str(error.value)
    assert app.facts.store.list() == [] and not emitted(app, "memory_remembered")


async def test_remember_refuses_while_paused(app):
    app.facts.store.set_paused(True)
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", "memory_remember", {"text": "Likes durian"}, tool_context(app)
        )
    assert error.value.code == "memory_paused"


async def test_tools_are_owner_only(app):
    app.sessions.principals["phone"] = "mobile:owner:device"
    for name, args in (
        ("memory_search", {"query": "tea"}),
        ("memory_remember", {"text": "Likes tea"}),
    ):
        with pytest.raises(ServiceError) as error:
            await app.dispatcher.dispatch(
                "mobile:owner:device", name, args,
                {"principal": "mobile:owner:device", "project_path": None},
            )
        assert error.value.code == "permission_denied"


def test_tool_arguments_are_checked():
    for bad in ({}, {"query": ""}, {"query": "x" * 301}, {"query": "a", "x": 1}):
        with pytest.raises(ValidationError):
            FactSearch.model_validate(bad)
    for bad in ({}, {"text": "x", "kind": "secret"}, {"text": "x" * 1001}):
        with pytest.raises(ValidationError):
            FactRemember.model_validate(bad)
    for bad in ({}, {"query": "a", "id": "00000000-0000-4000-8000-000000000000"},
                {"id": "not-a-uuid"}):
        with pytest.raises(ValidationError):
            FactForget.model_validate(bad)


async def forget(app, args, approve=True):
    cards = []

    async def request_approval(card):
        cards.append(card)
        asyncio.get_running_loop().call_soon(app.dispatcher.resolve, "owner", card["id"], approve)

    try:
        result = await app.dispatcher.dispatch(
            "owner", "memory_forget", args, tool_context(app), request_approval
        )
    except ServiceError as exc:
        return cards, exc
    return cards, result


async def test_forget_asks_and_its_review_lists_the_facts(app):
    store = app.facts.store
    tea = store.add("preference", "Tea", "Likes teh tarik")
    iced = store.add("preference", "Iced tea", "Likes teh o ais when it's hot")
    keep = store.add("person", "Aisyah", "Sister, lives in Penang")
    cards, result = await forget(app, {"query": "teh"})
    [card] = cards
    assert card["tool"] == "memory_forget" and card["args"]["count"] == 2
    assert {f["subject"] for f in card["args"]["facts"]} == {"Tea", "Iced tea"}
    assert result == {"forgotten": 2}
    assert store.get(tea["id"]) is None and store.get(iced["id"]) is None
    assert store.get(keep["id"]) is not None


async def test_forget_by_id_and_decline(app):
    store = app.facts.store
    fact = store.add("person", "Aisyah", "Sister, lives in Penang")
    cards, error = await forget(app, {"id": fact["id"]}, approve=False)
    assert cards[0]["args"]["facts"] == [{"subject": "Aisyah", "text": "Sister, lives in Penang"}]
    assert error.code == "permission_denied" and store.get(fact["id"]) is not None
    cards, result = await forget(app, {"id": fact["id"]})
    assert result == {"forgotten": 1} and store.get(fact["id"]) is None


async def test_forget_deletes_only_what_was_reviewed(app):
    store = app.facts.store
    tea = store.add("preference", "Tea", "Likes teh tarik")
    cards = []

    async def request_approval(card):
        cards.append(card)
        # A matching fact arrives while the card is open: it is not deleted.
        store.add("preference", "More tea", "Likes teh halia too")
        asyncio.get_running_loop().call_soon(app.dispatcher.resolve, "owner", card["id"], True)

    result = await app.dispatcher.dispatch(
        "owner", "memory_forget", {"query": "teh"}, tool_context(app), request_approval
    )
    assert result == {"forgotten": 1} and store.get(tea["id"]) is None
    assert [f["subject"] for f in store.list()] == ["More tea"]


async def test_forget_with_no_match_is_refused_before_any_card(app):
    cards, error = await forget(app, {"query": "nothing like this"})
    assert cards == [] and error.code == "memory_not_found"


# --- owner-only routes ----------------------------------------------------------------------
FACT_ROUTES = ("facts_list", "facts_update", "facts_delete", "facts_pause", "facts_export")


@pytest.mark.parametrize("name", FACT_ROUTES)
@pytest.mark.parametrize("sid", ["other", "tray", "unknown", "locked"])
async def test_routes_are_owner_renderer_only(app, name, sid):
    fact = app.facts.store.add("preference", "Tea", "Likes teh tarik")
    payload = {
        "facts_list": {},
        "facts_update": {"id": fact["id"], "text": "Likes kopi"},
        "facts_delete": {"id": fact["id"]},
        "facts_pause": {"paused": True},
        "facts_export": {},
    }[name]
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    reply = await rpc(app, name, payload, sid=sid)
    assert reply["ok"] is False
    assert reply["code"] in ("authentication_required", "permission_denied")
    assert app.facts.store.get(fact["id"])["text"] == "Likes teh tarik"
    assert app.facts.store.is_paused() is False


async def test_routes_list_update_delete_pause_export(app):
    store = app.facts.store
    tea = store.add("preference", "Tea", "Likes teh tarik")
    aisyah = store.add("person", "Aisyah", "Sister, lives in Penang")
    reply = await rpc(app, "facts_list")
    assert reply["ok"] is True and reply["paused"] is False
    assert {f["id"] for f in reply["facts"]} == {tea["id"], aisyah["id"]}
    assert [f["id"] for f in (await rpc(app, "facts_list", {"kind": "person"}))["facts"]] == [
        aisyah["id"]
    ]

    reply = await rpc(app, "facts_update", {"id": tea["id"], "text": "Likes kopi", "pinned": True})
    assert reply["ok"] is True and reply["fact"]["text"] == "Likes kopi"
    assert reply["fact"]["pinned"] is True and reply["fact"]["id"] == tea["id"]

    reply = await rpc(app, "facts_pause", {"paused": True})
    assert reply == {"ok": True, "paused": True} and store.is_paused()
    # The owner still edits while paused.
    reply = await rpc(app, "facts_update", {"id": aisyah["id"], "kind": "place"})
    assert reply["ok"] is True and reply["fact"]["kind"] == "place"

    reply = await rpc(app, "facts_export")
    assert reply["ok"] is True and reply["count"] == 2
    assert json.loads(reply["json"])["paused"] is True

    reply = await rpc(app, "facts_delete", {"id": tea["id"]})
    assert reply == {"ok": True, "deleted": tea["id"]} and store.get(tea["id"]) is None
    reply = await rpc(app, "facts_delete", {"id": tea["id"]})
    assert reply["ok"] is False and reply["code"] == "memory_not_found"


@pytest.mark.parametrize(
    "name,payload",
    [
        ("facts_list", {"kind": "secret"}),
        ("facts_list", {"extra": 1}),
        ("facts_update", {"id": "00000000-0000-4000-8000-000000000000"}),
        ("facts_update", {"id": "nope", "text": "x"}),
        ("facts_update", {"id": "00000000-0000-4000-8000-000000000000", "pinned": "yes"}),
        ("facts_delete", {}),
        ("facts_pause", {"paused": "true"}),
        ("facts_pause", {"paused": 1}),
        ("facts_export", {"x": 1}),
    ],
)
async def test_routes_validate_their_arguments(app, name, payload):
    reply = await rpc(app, name, payload)
    assert reply["ok"] is False and reply["code"] == "invalid_arguments"


async def test_route_update_refuses_secrets(app):
    fact = app.facts.store.add("profile", "Card", "Uses a Visa card")
    reply = await rpc(app, "facts_update", {"id": fact["id"], "text": "My password is hunter2"})
    assert reply["ok"] is False and reply["code"] == "memory_secret"


async def test_unavailable_store_answers_plainly(app):
    app.facts.store, app.facts.error = None, memory_facts.NO_FTS5
    reply = await rpc(app, "facts_list")
    assert reply["ok"] is False and reply["code"] == "memory_unavailable"
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", "memory_search", {"query": "tea"}, tool_context(app)
        )
    assert error.value.code == "memory_unavailable"


async def test_nothing_is_logged_about_fact_text(app, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        await app.dispatcher.dispatch(
            "owner", "memory_remember", {"text": "Likes rambutan"}, tool_context(app)
        )
        await app.dispatcher.dispatch(
            "owner", "memory_search", {"query": "rambutan"}, tool_context(app)
        )
        await rpc(app, "facts_list")
    assert "rambutan" not in caplog.text
