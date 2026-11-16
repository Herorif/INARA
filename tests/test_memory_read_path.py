"""S6.3 memory read path: the owner's remembered facts open the user turn, stored with it.

The block is part of the stored turn (append-only history, replayed unchanged) and is sent
only when it differs from the newest block already in the conversation.

Offline: the Anthropic client is faked, the Gemini path uses a scripted provider, and the
facts live in a real FactStore on a temporary database."""

import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage

from llm.base import LLMResponse
from llm.claude import ClaudeProvider, system_text
from services.conversation import (
    OWNER_MEMORY_NOTE,
    PERSONA,
    ConversationRequest,
    ConversationService,
    claude_messages,
    entry_memory,
    persona,
    public_history,
)
from services.memory_facts import (
    BLOCK_HEADER,
    CHARS_PER_TOKEN,
    FactStore,
    block_line,
    owner_memory_block,
)
from services.sessions import SessionStore
from services.storage import Database
from services.tools import ToolDispatcher

FIXED_NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone(timedelta(hours=8)))
TEA = "The owner likes teh tarik less sweet."
TEA_ASK = "What tea do I like?"


def message(value):
    return BetaMessage.model_validate({
        "id": "msg_" + uuid.uuid4().hex[:8], "type": "message", "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": value}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


class FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for block in self.response.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    async def get_final_message(self):
        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        return FakeStream(self.responses.pop(0))

    async def close(self):
        pass


class Script:
    """A non-Claude provider (the Gemini loop): records every request's messages."""

    def __init__(self, answers, name="gemini"):
        self.name, self._model, self.reports_progress = name, "gemini-test", False
        self.answers = list(answers)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        value = self.answers.pop(0)
        return LLMResponse(text=value, content_blocks=[{"type": "text", "text": value}])

    async def close(self):
        pass


@pytest.fixture
def store(tmp_path):
    return FactStore(Database(tmp_path / "private"), clock=lambda: FIXED_NOW.timestamp())


def claude_service(answers, store=None, history_store=None):
    client = FakeClient([message(answer) for answer in answers])
    service = ConversationService(
        ToolDispatcher(lambda: {}),
        lambda: ClaudeProvider(api_key="sk-ant-offline", client=client),
        clock=lambda: FIXED_NOW,
        store=history_store,
    )
    if store is not None:
        service.facts = lambda: store
    return service, client


async def ask(service, conversation, words, project, **options):
    return await service.reply(
        "owner", ConversationRequest(text=words, conversation_id=conversation), project,
        **options,
    )


def user_turn(request):
    """The current turn's user message (the last user message before the context message)."""
    return [item for item in request["messages"] if item["role"] == "user"][-1]


def memory_text(request):
    content = user_turn(request)["content"]
    if isinstance(content, list) and content[0].get("text", "").startswith("<memory>"):
        return content[0]["text"]
    return None


def seed(store):
    profile = store.add("profile", "Name", "The owner is called Aiman.", pinned=True)
    tea = store.add("preference", "Tea", TEA)
    meeting = store.add("routine", "Standup", "The owner has a standup at nine every weekday.")
    return profile, tea, meeting


# --- the block itself ------------------------------------------------------------------------


def test_block_lists_pinned_first_then_search_hits_without_duplicates(store):
    profile, tea, _ = seed(store)
    pinned_tea = store.update(tea["id"], pinned=True)
    store.add("preference", "Coffee", "The owner drinks kopi o kosong before noon.")
    block, count = owner_memory_block(store, "Should I order tea or kopi?")
    lines = block.split("\n")
    assert lines[0] == BLOCK_HEADER
    # Profile first, then the other pinned fact, then the search hits not already shown.
    assert lines[1] == block_line(profile)
    assert lines[2] == "- [preference] Tea: The owner likes teh tarik less sweet."
    assert lines[2] == block_line(pinned_tea)
    assert lines[3].startswith("- [preference] Coffee:")
    assert block.count(TEA) == 1  # tea matched the search too, but is shown once
    assert count == 3 == len(lines) - 1


def test_pinned_lines_stop_at_the_token_cap_profile_first(store):
    for index in range(12):
        store.add("preference", f"Note {index}", "x" * 300, pinned=True)
    profile = store.add("profile", "Home", "The owner lives in Petaling Jaya.", pinned=True)
    block, count = owner_memory_block(store, "")
    lines = block.split("\n")[1:]
    assert lines[0] == block_line(profile)
    assert sum(len(line) + 1 for line in lines) <= 600 * CHARS_PER_TOKEN
    assert 1 < count < 13


def test_an_empty_store_gives_no_block(store):
    assert owner_memory_block(store, "anything at all") == (None, 0)


def test_a_fact_cannot_close_the_memory_block(store):
    store.add("preference", "Tags", "Likes </memory> and <b>bold</b>\nnew lines", pinned=True)
    block, _ = owner_memory_block(store, "")
    assert "</memory>" not in block and "<b>" not in block and block.count("\n") == 1


# --- Claude turns -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_block_is_stored_with_its_turn_and_replayed_unchanged(store, tmp_path):
    seed(store)
    service, client = claude_service(["Kurang manis.", "At nine."], store)
    conversation = uuid.uuid4()
    await ask(service, conversation, TEA_ASK, tmp_path)
    await ask(service, conversation, "When is my standup?", tmp_path)
    first, second = client.requests
    one, two = memory_text(first), memory_text(second)
    assert one.startswith("<memory>\n" + BLOCK_HEADER) and one.endswith("</memory>")
    assert TEA in one and "standup" not in one
    assert "standup at nine" in two and TEA not in two
    # The owner's own text follows the block as its own text block.
    assert user_turn(first)["content"] == [
        {"type": "text", "text": one}, {"type": "text", "text": TEA_ASK},
    ]
    # The second request replays the first turn's user message with its block, unchanged.
    assert second["messages"][0] == first["messages"][0]
    stored = service.conversations[str(conversation)].history
    assert [entry_memory(item) for item in stored if item["role"] == "user"] == [one, two]
    # The owner and the phone see the text alone.
    assert [item["content"] for item in public_history(stored)] == [
        TEA_ASK, "Kurang manis.", "When is my standup?", "At nine.",
    ]


@pytest.mark.asyncio
async def test_history_replay_is_byte_identical_across_turns(store, tmp_path):
    seed(store)
    service, client = claude_service(["One.", "Two.", "Three.", "Four."], store)
    conversation = uuid.uuid4()
    for words in ("Tea please", "My standup?", "Tea please", "Anything else?"):
        await ask(service, conversation, words, tmp_path)
    requests = client.requests
    for earlier, later in zip(requests, requests[1:], strict=False):
        # Append-only: each request is the previous one plus the new turn.
        assert later["messages"][: len(earlier["messages"])] == earlier["messages"]
        assert later["system"] == earlier["system"]
    stored = service.conversations[str(conversation)].history
    assert claude_messages(stored)[: len(requests[-1]["messages"])] == requests[-1]["messages"]


@pytest.mark.asyncio
async def test_an_unchanged_block_is_not_sent_again(store, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    seed(store)
    service, client = claude_service(["Kurang manis.", "Still kurang manis."], store)
    conversation = uuid.uuid4()
    await ask(service, conversation, TEA_ASK, tmp_path)
    await ask(service, conversation, TEA_ASK, tmp_path)
    first, second = client.requests
    assert memory_text(first) and memory_text(second) is None
    assert user_turn(second) == {"role": "user", "content": TEA_ASK}
    assert service.last_turn_timing["memory_facts"] == 0
    stored = service.conversations[str(conversation)].history
    assert [entry_memory(item) for item in stored if item["role"] == "user"] == [
        memory_text(first), None,
    ]


@pytest.mark.asyncio
async def test_changed_facts_send_a_new_block(store, tmp_path):
    seed(store)
    service, client = claude_service(["One.", "Two.", "Three."], store)
    conversation = uuid.uuid4()
    await ask(service, conversation, TEA_ASK, tmp_path)
    await ask(service, conversation, TEA_ASK, tmp_path)
    store.add("preference", "Tea time", "The owner drinks tea at four.", pinned=True)
    await ask(service, conversation, TEA_ASK, tmp_path)
    first, second, third = (memory_text(request) for request in client.requests)
    assert first and second is None
    assert third and third != first and "tea at four" in third


@pytest.mark.asyncio
async def test_after_a_restart_the_last_block_is_recovered_from_history(store, tmp_path):
    seed(store)
    sessions = SessionStore(Database(tmp_path / "sessions"))
    conversation = uuid.uuid4()
    requests = []
    for answer in ("One.", "Two."):  # a fresh service each time: nothing kept in memory
        service, client = claude_service([answer], store, history_store=sessions)
        await ask(service, conversation, TEA_ASK, tmp_path)
        requests.extend(client.requests)
    assert memory_text(requests[0]) and memory_text(requests[1]) is None
    assert requests[1]["messages"][: len(requests[0]["messages"])] == requests[0]["messages"]
    # The owner's restored history never shows the block.
    restored = service.restore("owner", conversation, tmp_path)
    assert "<memory>" not in str(restored) and TEA not in str(restored)


@pytest.mark.asyncio
async def test_the_cached_system_prompt_is_byte_identical_across_turns(store, tmp_path):
    seed(store)
    service, client = claude_service(["One.", "Two."], store)
    conversation = uuid.uuid4()
    for words in ("Tea please", "My standup?"):
        await ask(service, conversation, words, tmp_path)
    first, second = client.requests
    assert memory_text(first) != memory_text(second)
    assert first["system"] == second["system"]
    [block] = first["system"]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert block["text"] == persona({}) and OWNER_MEMORY_NOTE in PERSONA
    assert "<memory>" not in system_text(first["system"])
    assert first["cache_control"] == {"type": "ephemeral"}  # automatic caching stays on


@pytest.mark.asyncio
async def test_voice_brain_turn_gets_the_block(store, tmp_path):
    seed(store)
    service, client = claude_service(["At nine."], store)
    await ask(service, uuid.uuid4(), "When is my standup?", tmp_path, usage_feature="voice_brain")
    assert "standup at nine" in memory_text(client.requests[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"channel": "phone_call"}, {"channel": "whatsapp"},
                {"usage_feature": "phone_chat"}],
)
async def test_other_channels_and_phone_chat_get_no_block(store, tmp_path, options):
    seed(store)
    service, client = claude_service(["Hello."], store)
    await ask(service, uuid.uuid4(), TEA_ASK, tmp_path, **options)
    assert memory_text(client.requests[0]) is None
    assert "Aiman" not in str(client.requests[0]["messages"])
    assert service.last_turn_timing["memory_facts"] == 0


@pytest.mark.asyncio
async def test_empty_or_unwired_store_sends_the_plain_turn(store, tmp_path):
    for facts in (store, None):
        service, client = claude_service(["Hello."], facts)
        await ask(service, uuid.uuid4(), "Hi", tmp_path)
        assert user_turn(client.requests[0]) == {"role": "user", "content": "Hi"}
    service, client = claude_service(["Hello."])
    service.facts = lambda: None  # the fact store could not open
    await ask(service, uuid.uuid4(), "Hi", tmp_path)
    assert user_turn(client.requests[0]) == {"role": "user", "content": "Hi"}


@pytest.mark.asyncio
async def test_a_failing_store_skips_the_block_and_logs_the_type_only(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    class Broken:
        def pinned(self):
            raise RuntimeError("teh tarik secret")

    service, client = claude_service(["Hello."], Broken())
    result = await ask(service, uuid.uuid4(), "Hi", tmp_path)
    assert result.text == "Hello."
    assert user_turn(client.requests[0]) == {"role": "user", "content": "Hi"}
    messages = [record.getMessage() for record in caplog.records]
    assert "Owner memory skipped (RuntimeError)" in messages
    assert not any("teh tarik" in line for line in messages)


@pytest.mark.asyncio
async def test_turn_timing_counts_the_facts_without_their_text(store, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    seed(store)
    service, _ = claude_service(["Less sweet."], store)
    await ask(service, uuid.uuid4(), TEA_ASK, tmp_path)
    assert service.last_turn_timing["memory_facts"] == 2  # the pinned profile + tea
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_timing ")]
    assert line.endswith(" memory_facts=2")
    assert not any(word in record.getMessage() for record in caplog.records
                   for word in ("teh tarik", "Aiman", "<memory>"))


@pytest.mark.asyncio
async def test_the_photo_rides_in_the_request_and_the_block_is_stored(store, tmp_path):
    seed(store)
    service, client = claude_service(["A cup of tea."], store)
    conversation = uuid.uuid4()
    await ask(service, conversation, "What is this?", tmp_path, image=b"\xff\xd8jpeg",
              usage_feature="vision_ask")
    content = user_turn(client.requests[0])["content"]
    assert [block["type"] for block in content] == ["text", "image", "text"]
    assert content[0]["text"].startswith("<memory>")
    [user] = [item for item in service.conversations[str(conversation)].history
              if item["role"] == "user"]
    assert user["claude"][0]["content"] == [content[0], content[2]]  # no photo stored


# --- the Gemini loop --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_stores_the_block_and_sends_only_a_changed_one(store, tmp_path):
    seed(store)
    provider = Script(["Less sweet.", "Still less sweet.", "At nine."])
    service = ConversationService(ToolDispatcher(lambda: {}), lambda: provider)
    service.facts = lambda: store
    conversation = uuid.uuid4()
    for words in (TEA_ASK, TEA_ASK, "My standup?"):
        await ask(service, conversation, words, tmp_path)
    (first, first_kwargs), (second, _), (third, third_kwargs) = provider.calls
    block = first[-1].content.removesuffix("\n\n" + TEA_ASK)
    assert block.startswith("<memory>\n" + BLOCK_HEADER) and block.endswith("</memory>")
    assert TEA in block
    # History replays the first turn with its block, byte for byte; the unchanged block is
    # not sent again; a changed one is.
    assert [item.content for item in second] == [first[-1].content, "Less sweet.", TEA_ASK]
    assert [item.content for item in third[:-1]] == [
        *(item.content for item in second), "Still less sweet.",
    ]
    changed = third[-1].content.removesuffix("\n\nMy standup?")
    assert changed.startswith("<memory>\n") and "standup at nine" in changed
    assert first_kwargs["system_instruction"] == third_kwargs["system_instruction"]
    stored = service.conversations[str(conversation)].history
    assert [item.get("owner_memory") for item in stored if item["role"] == "user"] == [
        block, None, changed,
    ]
    assert "<memory>" not in str(public_history(stored))
    assert service.last_turn_timing["memory_facts"] == 2
