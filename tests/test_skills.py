"""S5.2 skills (docs/SKILLS.md): the SKILL.md front matter subset and its limits, owner skills
over shipped ones, the cache-stable index after the persona, load_skill, teach_skill (always
asks, shows the file, built-in slugs refused, replace wording, taint line), scripts never
run, and the owner-only skills_* routes.

Offline: skill folders live under tmp_path; the Claude brain is a fake client. Nothing binds
a port and no real API is called."""

import copy
import logging
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage

from llm.claude import ClaudeProvider, system_text
from services.conversation import ConversationRequest, ConversationService, persona
from services.skills import (
    BODY_LIMIT,
    DESCRIPTION_LIMIT,
    INDEX_HEADER,
    NAME_LIMIT,
    SHIPPED_ROOT,
    SkillError,
    SkillLibrary,
    parse_skill,
    render_skill,
    skill_index,
    slugify,
)
from services.tools import ServiceError, ToolDispatcher, taint_line

PLAN = "plan-my-day"
SECRET = "quokka-zebra-instructions"


def write_skill(root, slug, name="A skill", description="Does a thing.", body="Do it.",
                text=None):
    folder = Path(root) / slug
    folder.mkdir(parents=True, exist_ok=True)
    if text is None:
        text = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
    (folder / "SKILL.md").write_text(text, encoding="utf-8", newline="")
    return folder


@pytest.fixture
def app(application_factory, tmp_path):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    import server

    for name in ("load_skill", "teach_skill"):
        app.settings["tool_permissions"][name] = server.DEFAULT_SETTINGS["tool_permissions"][name]
    app.skills.shipped_root = tmp_path / "shipped"
    write_skill(app.skills.shipped_root, PLAN, "plan-my-day", "Plan the owner's day.",
                "Read the calendar first.")
    app.skills.signature = None
    return app


def owner_root(app):
    return app.skills.owner_root


def approver(app, answer=True, cards=None):
    async def approve(payload):
        if cards is not None:
            cards.append(payload)
        app.dispatcher.resolve("owner", payload["id"], answer)

    return approve


def tool_context(app, **extra):
    return {**app.sessions.context("client").tools(), **extra}


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


TEACH = {"name": "Gym bag", "description": "Pack the gym bag the owner's way.",
         "instructions": "1. Towel.\n2. Shoes.\n3. Water bottle."}


# --- the format ------------------------------------------------------------------------------
def test_parse_plain_quoted_and_single_quoted_values():
    fields, body = parse_skill(
        "\ufeff---\r\n"
        "name: plan-my-day\r\n"
        "# a comment line\r\n"
        "description: \"Plan the day: calendar \\\"first\\\" \\u00e9\"\r\n"
        "license: 'it''s MIT'  # trailing comment\r\n"
        "allowed-tools:\r\n"
        "---\r\n\r\n# Steps\r\n\r\nDo it.\r\n"
    )
    assert fields["name"] == "plan-my-day"
    assert fields["description"] == 'Plan the day: calendar "first" \u00e9'
    assert fields["license"] == "it's MIT" and fields["allowed-tools"] == ""
    assert body == "# Steps\n\nDo it."
    assert parse_skill("---\nname: x # note\ndescription: y\n---\nz")[0]["name"] == "x"


@pytest.mark.parametrize("text, message", [
    ("name: x\ndescription: y\n---\nbody", "must start with a ---"),
    ("---\nname: x\ndescription: y\nbody", "no closing ---"),
    ("---\nname: x\n---\nbody", "needs a description"),
    ("---\ndescription: y\n---\nbody", "needs a name"),
    ("---\nname: x\ndescription: y\n---\n\n   \n", "needs instructions"),
    ("---\nname: x\nname: z\ndescription: y\n---\nbody", "name twice"),
    ("---\nname: x\ndescription: y\nmetadata:\n  author: me\n---\nbody", "nested"),
    ("---\nname: x\ndescription: a: b\n---\nbody", "colon"),
    ("---\nname: [x]\ndescription: y\n---\nbody", "starts with a symbol"),
    ("---\nname: \"x\ndescription: y\n---\nbody", "double-quoted"),
    ("---\nname: 'x\ndescription: y\n---\nbody", "single-quoted"),
    ("---\nname: \"x\\q\"\ndescription: y\n---\nbody", "escape"),
    ("---\nname: x\ndescription: \"one\\ntwo\"\n---\nbody", "one line"),
    ("---\nname: x\ndescription: y\nnot a key line\n---\nbody", "key: value"),
    ("---\nname: x\ndescription: y\n---\nbad \x00 byte", "plain text"),
])
def test_invalid_front_matter_is_refused(text, message):
    with pytest.raises(SkillError, match=message):
        parse_skill(text)


def test_limits():
    def text(name="x", description="y", body="z"):
        return f"---\nname: {name}\ndescription: {description}\n---\n{body}"

    parse_skill(text("n" * NAME_LIMIT, "d" * DESCRIPTION_LIMIT, "b" * BODY_LIMIT))
    with pytest.raises(SkillError, match="name is longer than 64"):
        parse_skill(text(name="n" * (NAME_LIMIT + 1)))
    with pytest.raises(SkillError, match="description is longer than 300"):
        parse_skill(text(description="d" * (DESCRIPTION_LIMIT + 1)))
    with pytest.raises(SkillError, match="longer than 20,000"):
        parse_skill(text(body="b" * (BODY_LIMIT + 1)))


def test_rendered_skill_round_trips():
    text = render_skill('Say "hi"', "When the owner says \\ hi: greet.", "\r\nStep one.\r\n\r\n")
    assert text == ('---\nname: "Say \\"hi\\""\ndescription: "When the owner says \\\\ hi: '
                    'greet."\n---\n\nStep one.\n')
    fields, body = parse_skill(text)
    assert fields["name"] == 'Say "hi"' and fields["description"] == "When the owner says \\ hi: greet."
    assert body == "Step one."


def test_slugs():
    assert slugify("Plan my day") == "plan-my-day"
    assert slugify("  Gym bag (Mon/Wed) ") == "gym-bag-mon-wed"
    assert slugify("!!!") == ""
    assert len(slugify("a " * 60)) <= 48 and not slugify("a " * 60).endswith("-")


def test_bad_folders_are_skipped(tmp_path):
    root = tmp_path / "owner"
    write_skill(root, "Upper-Case")  # slug must be lowercase
    write_skill(root, "ok-skill", description="Fine.")
    write_skill(root, "bad-front", text="no front matter")
    folder = root / "latin1"
    folder.mkdir()
    (folder / "SKILL.md").write_bytes(b"---\nname: x\ndescription: caf\xe9\n---\nbody")
    (root / "no-skill-file").mkdir()
    (root / "stray.md").write_text("not a folder", encoding="utf-8")
    library = SkillLibrary(owner_root=root, shipped_root=None)
    assert list(library.refresh()) == ["ok-skill"]
    reasons = [reason for _, reason in library.skipped]
    assert any("lowercase" in reason for reason in reasons)
    assert any("UTF-8" in reason for reason in reasons)
    assert any("must start with" in reason for reason in reasons)


def test_the_shipped_example_skill_is_valid():
    library = SkillLibrary(owner_root=None, shipped_root=SHIPPED_ROOT)
    skills = library.refresh()
    assert PLAN in skills and library.skipped == []
    skill = skills[PLAN]
    assert skill.source == "shipped" and skill.scripts == ()
    assert "calendar_events" in skill.body and "list_reminders" in skill.body
    assert "weather" in skill.body


# --- the library and the index -----------------------------------------------------------------
def test_owner_skills_override_shipped_ones(tmp_path):
    shipped, owner = tmp_path / "shipped", tmp_path / "owner"
    write_skill(shipped, PLAN, "plan-my-day", "Built-in plan.", "Built-in body.")
    write_skill(shipped, "other", "other", "Other.", "Other body.")
    library = SkillLibrary(owner_root=owner, shipped_root=shipped)
    assert library.find(PLAN).source == "shipped"
    write_skill(owner, PLAN, "My plan", "My own plan.", "My body.")
    skill = library.find(PLAN)
    assert (skill.source, skill.body, skill.name) == ("owner", "My body.", "My plan")
    listed = library.list()
    assert [(item["slug"], item["source"]) for item in listed] == [
        ("other", "built-in"), (PLAN, "yours")]
    assert listed[1]["path"] == str(owner / PLAN) and listed[1]["description"] == "My own plan."
    assert library.find("My Plan").slug == PLAN and library.find("Plan my day").slug == PLAN
    assert library.find("nothing") is None


def test_index_is_byte_stable_and_changes_only_with_the_skills(tmp_path):
    shipped, owner = tmp_path / "shipped", tmp_path / "owner"
    library = SkillLibrary(owner_root=owner, shipped_root=shipped)
    assert library.index_text() == ""
    write_skill(shipped, "zeta", description="Last.")
    write_skill(shipped, "alpha", description="First.")
    first = library.index_text()
    assert first == f"{INDEX_HEADER}\n- alpha: First.\n- zeta: Last."
    # Re-reading unchanged folders (or rewriting a file with the same content) keeps the bytes.
    assert library.index_text() == first
    write_skill(shipped, "zeta", description="Last.")
    library.refresh(force=True)
    assert library.index_text() == first
    # A body edit is not in the index.
    write_skill(shipped, "alpha", description="First.", body="New steps.")
    assert library.index_text() == first and library.find("alpha").body == "New steps."
    write_skill(owner, "middle", description="Added.")
    assert library.index_text() == f"{INDEX_HEADER}\n- alpha: First.\n- middle: Added.\n- zeta: Last."
    assert skill_index(library.loaded) == library.index_text()


def test_system_prompt_appends_the_index_only_with_skills(app):
    base = persona(app.settings)
    assert app.conversation.system_prompt() == base + "\n\n" + app.skills.index_text()
    assert app.conversation.system_prompt().endswith(f"- {PLAN}: Plan the owner's day.")
    app.skills.shipped_root = None
    assert app.conversation.system_prompt() == base

    def broken():
        raise RuntimeError("disk")

    app.conversation.skill_index = broken
    assert app.conversation.system_prompt() == base


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


async def test_the_cached_system_block_is_byte_identical_across_turns(tmp_path):
    shipped = tmp_path / "shipped"
    write_skill(shipped, PLAN, description="Plan the owner's day.")
    library = SkillLibrary(owner_root=tmp_path / "owner", shipped_root=shipped)
    client = FakeClient([message("One."), message("Two."), message("Three.")])
    service = ConversationService(
        ToolDispatcher(lambda: {}),
        lambda: ClaudeProvider(api_key="sk-ant-offline", client=client),
    )
    service.skill_index = library.index_text
    conversation = uuid.uuid4()
    for words in ("Plan my day", "And tomorrow?"):
        await service.reply("owner", ConversationRequest(text=words, conversation_id=conversation),
                            tmp_path)
    first, second = client.requests
    assert first["system"] == second["system"]
    [block] = first["system"]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert block["text"] == persona({}) + "\n\n" + library.index_text()
    # Adding a skill changes the cached prefix on the next turn, and only then.
    write_skill(tmp_path / "owner", "gym-bag", description="Pack the gym bag.")
    await service.reply("owner", ConversationRequest(text="Thanks", conversation_id=conversation),
                        tmp_path)
    third = client.requests[2]
    assert third["system"] != first["system"]
    assert system_text(third["system"]).endswith("- gym-bag: Pack the gym bag.\n- plan-my-day: "
                                                 "Plan the owner's day.")


# --- load_skill --------------------------------------------------------------------------------
async def test_load_skill_returns_the_body_and_never_asks(app):
    write_skill(owner_root(app), "gym-bag", "Gym bag", "Pack it.", f"Steps {SECRET}.")
    asked = []
    result = await app.dispatcher.dispatch("owner", "load_skill", {"name": "gym-bag"},
                                           tool_context(app), approver(app, True, asked))
    assert result == {"skill": "gym-bag", "name": "Gym bag", "instructions": f"Steps {SECRET}."}
    assert asked == []
    shipped = await app.dispatcher.dispatch("owner", "load_skill", {"name": "Plan my day"},
                                            tool_context(app))
    assert shipped["instructions"] == "Read the calendar first."
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch("owner", "load_skill", {"name": "nope"}, tool_context(app))
    assert caught.value.code == "skill_not_found"
    spec = app.dispatcher.tools["load_skill"]
    assert spec.untrusted_output is False and spec.always_ask is False and spec.outward is False


async def test_scripts_are_listed_and_never_executed(app, monkeypatch):
    folder = write_skill(owner_root(app), "with-script", body="Use the helper if asked.")
    (folder / "scripts").mkdir()
    marker = folder / "ran.txt"
    (folder / "scripts" / "helper.py").write_text(
        f"open(r'{marker}', 'w').write('ran')\n", encoding="utf-8")
    (folder / "scripts" / "run.cmd").write_text(f"echo ran > \"{marker}\"\n", encoding="utf-8")

    def refuse(*args, **kwargs):
        raise AssertionError("a skill must never start a process")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", refuse)
    result = await app.dispatcher.dispatch("owner", "load_skill", {"name": "with-script"},
                                           tool_context(app))
    assert result["scripts"] == ["helper.py", "run.cmd"]
    assert "never runs" in result["scripts_note"]
    listed = next(item for item in app.skills.list() if item["slug"] == "with-script")
    assert listed["scripts"] == ["helper.py", "run.cmd"]
    app.conversation.system_prompt()
    assert not marker.exists()


async def test_skill_tools_are_owner_only(app):
    for name, args in (("load_skill", {"name": PLAN}), ("teach_skill", TEACH)):
        with pytest.raises(ServiceError) as caught:
            await app.dispatcher.dispatch("intruder", name, args, {"principal": "intruder"},
                                          approver(app))
        assert caught.value.code == "permission_denied"
    assert not (owner_root(app) / "gym-bag").exists()


# --- teach_skill -------------------------------------------------------------------------------
async def test_teach_skill_always_asks_shows_the_file_and_saves_on_approve(app):
    app.settings["tool_permissions"]["teach_skill"] = False  # always_ask wins anyway
    cards = []
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch("owner", "teach_skill", TEACH, tool_context(app),
                                      approver(app, False, cards))
    assert caught.value.code == "permission_denied"
    assert not (owner_root(app) / "gym-bag").exists()
    [card] = cards
    expected = render_skill(TEACH["name"], TEACH["description"], TEACH["instructions"])
    assert card["tool"] == "teach_skill"
    assert card["args"]["skill_md"] == expected and card["args"]["slug"] == "gym-bag"
    assert card["args"]["replaces"] is None and "taint_line" not in card

    cards.clear()
    result = await app.dispatcher.dispatch("owner", "teach_skill", TEACH, tool_context(app),
                                           approver(app, True, cards))
    assert result == {"saved": True, "skill": "gym-bag", "name": "Gym bag", "replaced": False}
    path = owner_root(app) / "gym-bag" / "SKILL.md"
    assert path.read_bytes().decode("utf-8") == cards[0]["args"]["skill_md"]
    assert not (owner_root(app) / "gym-bag" / "SKILL.md.partial").exists()
    assert "- gym-bag: Pack the gym bag the owner's way." in app.conversation.system_prompt()
    loaded = await app.dispatcher.dispatch("owner", "load_skill", {"name": "gym-bag"},
                                           tool_context(app))
    assert loaded["instructions"] == TEACH["instructions"]


async def test_teach_skill_replace_wording_for_an_owner_skill(app):
    write_skill(owner_root(app), "gym-bag", "Gym bag", "Old.", "Old steps.")
    cards = []
    result = await app.dispatcher.dispatch("owner", "teach_skill", TEACH, tool_context(app),
                                           approver(app, True, cards))
    assert cards[0]["args"]["replaces"] == "Replaces your existing skill gym-bag."
    assert result["replaced"] is True
    assert app.skills.find("gym-bag").body == TEACH["instructions"]


async def test_teach_skill_refuses_a_built_in_slug_before_any_card(app):
    cards = []
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch(
            "owner", "teach_skill", {**TEACH, "name": "Plan my day"}, tool_context(app),
            approver(app, True, cards))
    assert caught.value.code == "skill_built_in" and "Pick another name" in str(caught.value)
    assert cards == [] and not (owner_root(app) / PLAN).exists()
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch(
            "owner", "teach_skill", {**TEACH, "name": "!!!"}, tool_context(app),
            approver(app, True, cards))
    assert caught.value.code == "invalid_arguments" and cards == []
    with pytest.raises(ServiceError) as caught:
        await app.dispatcher.dispatch(
            "owner", "teach_skill", {**TEACH, "description": "two\nlines"}, tool_context(app),
            approver(app, True, cards))
    assert caught.value.code == "invalid_arguments" and cards == []


async def test_a_tainted_turn_shows_the_taint_line(app):
    spec = app.dispatcher.tools["teach_skill"]
    assert spec.always_ask is True and spec.outward is True
    cards = []
    await app.dispatcher.dispatch("owner", "teach_skill", TEACH,
                                  tool_context(app, taint={"a web page"}),
                                  approver(app, True, cards))
    [card] = cards
    assert card["taint"] == ["a web page"]
    assert card["taint_line"] == taint_line(["a web page"])
    assert card["args"]["caution"] == card["taint_line"]


async def test_nothing_private_is_logged(app, caplog):
    write_skill(owner_root(app), "broken", text=f"---\nname: {SECRET}\n---\n{SECRET}")
    with caplog.at_level(logging.DEBUG):
        app.conversation.system_prompt()
        await app.dispatcher.dispatch("owner", "teach_skill",
                                      {**TEACH, "instructions": SECRET}, tool_context(app),
                                      approver(app))
        await rpc(app, "skills_list")
    assert SECRET not in caplog.text and "Gym bag" not in caplog.text


# --- owner-only routes -------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["skills_list", "skills_delete"])
@pytest.mark.parametrize("sid", ["other", "tray", "unknown", "locked"])
async def test_routes_are_owner_renderer_only(app, name, sid):
    write_skill(owner_root(app), "gym-bag")
    payload = {"skills_list": {}, "skills_delete": {"slug": "gym-bag"}}[name]
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
        app.sessions.face_authenticated = lambda: False
    reply = await rpc(app, name, payload, sid=sid)
    assert reply["ok"] is False
    assert reply["code"] in ("authentication_required", "permission_denied")
    assert (owner_root(app) / "gym-bag" / "SKILL.md").exists()


async def test_routes_list_and_delete(app):
    folder = write_skill(owner_root(app), "gym-bag", "Gym bag", "Pack it.", "Steps.")
    (folder / "scripts").mkdir()
    (folder / "scripts" / "pack.ps1").write_text("Write-Output hi", encoding="utf-8")
    listed = await rpc(app, "skills_list")
    assert listed == {"ok": True, "skills": [
        {"slug": "gym-bag", "name": "Gym bag", "description": "Pack it.", "source": "yours",
         "path": str(folder), "scripts": ["pack.ps1"]},
        {"slug": PLAN, "name": "plan-my-day", "description": "Plan the owner's day.",
         "source": "built-in", "path": str(app.skills.shipped_root / PLAN), "scripts": []},
    ]}
    built_in = await rpc(app, "skills_delete", {"slug": PLAN})
    assert built_in["ok"] is False and built_in["code"] == "skill_built_in"
    assert (app.skills.shipped_root / PLAN / "SKILL.md").exists()
    assert await rpc(app, "skills_delete", {"slug": "gym-bag"}) == {"ok": True,
                                                                     "deleted": "gym-bag"}
    assert not folder.exists()
    gone = await rpc(app, "skills_delete", {"slug": "gym-bag"})
    assert gone["ok"] is False and gone["code"] == "skill_not_found"
    assert "gym-bag" not in app.conversation.system_prompt()


@pytest.mark.parametrize("name, payload", [
    ("skills_list", {"extra": True}),
    ("skills_delete", {"slug": "Not A Slug"}),
    ("skills_delete", {"slug": "../escape"}),
    ("skills_delete", {}),
])
async def test_routes_validate_their_arguments(app, name, payload):
    assert await rpc(app, name, payload) == {"ok": False, "code": "invalid_arguments",
                                             "message": "That skill request isn't valid."}
