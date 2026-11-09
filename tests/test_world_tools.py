"""World tools and tours (W3b, W4; docs/WORLD_VIEW.md "Tools and tours"): the built-in gev MCP
server, its policies and automatic views, world_show, world_tour and the tour's stops.

Fakes only: tests/fixtures/fake_gev.py as the globe sidecar (vite.js) and
tests/fixtures/fake_gev_mcp.py as GEV's MCP server (server/mcp/stdio.js), both run by the test
interpreter on a random free loopback port. Tour waits use a fake clock.
"""

import asyncio
import json
import logging
import shutil
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.mcp_registry import POLICY_VALUES
from services.tools import ServiceError
from services.world_tools import DEFAULT_POLICY, SHOW_PROPERTY, WorldShow
FAKE_GEV = Path(__file__).parent / "fixtures" / "fake_gev.py"
FAKE_MCP = Path(__file__).parent / "fixtures" / "fake_gev_mcp.py"
GEV_TOOLS = 30


def free_port():
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in (4173, 8000):
            return port


def make_root(path):
    (path / "dist").mkdir(parents=True)
    (path / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    script = path / "node_modules" / "vite" / "bin" / "vite.js"
    script.parent.mkdir(parents=True)
    shutil.copyfile(FAKE_GEV, script)
    return path


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


def emitted(app, event):
    return [call.args[1] for call in app.sio.emit.await_args_list if call.args[0] == event]


async def until(check, timeout=20.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition timed out")


def install(root):
    script = root / "server" / "mcp" / "stdio.js"
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FAKE_MCP, script)
    return root


class FakeSleep:
    """The tour's clock: records each wait and lets the test end it."""

    def __init__(self):
        self.waits = []
        self.events = []

    async def __call__(self, seconds):
        event = asyncio.Event()
        self.waits.append(seconds)
        self.events.append(event)
        await event.wait()

    def release(self):
        self.events[-1].set()


@pytest.fixture
async def gev_app(application_factory, tmp_path):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    root = install(make_root(tmp_path / "gev"))
    app.settings["world"] = {
        "root": str(root), "node": sys.executable, "port": free_port(), "idle_minutes": 10,
        "enabled": True,
    }
    # As server.DEFAULT_SETTINGS: showing and touring never ask.
    app.settings["tool_permissions"].update({"world_show": False, "world_tour": False})
    app.world.poll = 0.05
    app.world_tools.sleep = FakeSleep()
    app.answers = {"ok": True}

    async def emit(event, payload=None, room=None):
        # The World page: every view gets an answer from the renderer it went to.
        if event == "world_view" and app.answers is not None:
            asyncio.get_running_loop().call_soon(
                app.world.view_result, room, payload["id"], app.answers["ok"], []
            )

    app.sio.emit.side_effect = emit
    yield app
    await app.world_tools.close()
    await app.mcp.close()
    await app.world.close()


def context(app):
    return app.sessions.context("client").tools()


async def brain(app, name, arguments, approvals=None):
    return await app.dispatcher.dispatch("owner", name, arguments, context(app), approvals)


async def listed(app):
    return await app.mcp.tools("gev")


def calls(app):
    path = Path(app.settings["world"]["root"]) / "fake-mcp-calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def views(app):
    return [payload for payload in emitted(app, "world_view")]


def tours(app):
    return emitted(app, "world_tour")


class Approvals:
    def __init__(self, app, answer=True):
        self.app, self.answer, self.requests = app, answer, []

    async def __call__(self, request):
        self.requests.append(request)
        asyncio.get_running_loop().call_soon(
            self.app.dispatcher.resolve, "owner", request["id"], self.answer
        )


# --- the built-in entry -----------------------------------------------------------------------
async def test_the_gev_entry_is_built_from_the_world_settings(gev_app):
    values = gev_app.settings["world"]
    config = next(item for item in gev_app.mcp.configs() if item.id == "gev")
    root = Path(values["root"])
    assert config.name == "God's Eye View" and config.enabled is True and config.autostart is True
    assert config.command == [
        sys.executable, str(root / "server" / "mcp" / "stdio.js"),
        "--api-base", f"http://127.0.0.1:{values['port']}",
    ]
    assert config.cwd == str(root) and config.idle_timeout_s == 600
    assert config.env == {"NODE_USE_SYSTEM_CA": "1"}  # GEV's HTTPS feeds trust the Windows store
    assert config.default_policy == "never_ask" and config.policy == DEFAULT_POLICY
    await listed(gev_app)
    argv = json.loads((root / "fake-mcp-argv.json").read_text(encoding="utf-8"))
    assert argv[1:] == ["--api-base", f"http://127.0.0.1:{values['port']}"]
    # A new port is a new command: the next use restarts the server with it.
    gev_app.settings["world"]["port"] = free_port()
    config = next(item for item in gev_app.mcp.configs() if item.id == "gev")
    assert config.command[-1] == f"http://127.0.0.1:{gev_app.settings['world']['port']}"
    # Not owner-editable: never saved to mcp.servers, refused by the owner RPCs.
    assert gev_app.settings.get("mcp") is None
    listing = await rpc(gev_app, "mcp_servers_list", {})
    (entry,) = [item for item in listing["servers"] if item["id"] == "gev"]
    assert entry["status"]["builtin"] == "world"
    for name, data in (
        ("mcp_server_save", {"server": {"id": "gev", "name": "Mine", "command": ["x.exe"]}}),
        ("mcp_server_remove", {"id": "gev"}),
        ("mcp_tool_policy_set", {"id": "gev", "tool": "get_cctv_snapshot", "policy": "never_ask"}),
    ):
        reply = await rpc(gev_app, name, data)
        assert reply["ok"] is False and reply["code"] == "mcp_builtin", (name, reply)
    assert gev_app.settings.get("mcp") is None
    # An owner entry reusing the id is ignored.
    gev_app.settings["mcp"] = {"servers": [{"id": "gev", "name": "Mine", "command": ["x.exe"]}]}
    assert [item.name for item in gev_app.mcp.configs() if item.id == "gev"] == ["God's Eye View"]


@pytest.mark.parametrize("broken", ["root", "stdio", "node", "disabled"])
async def test_gev_is_off_when_world_view_isnt_installed_or_is_turned_off(gev_app, broken):
    world = gev_app.settings["world"]
    if broken == "root":
        world["root"] = str(Path(world["root"]).parent / "missing")
    elif broken == "stdio":
        (Path(world["root"]) / "server" / "mcp" / "stdio.js").unlink()
    elif broken == "node":
        world["node"] = str(Path(world["root"]) / "node.exe")
    else:
        world["enabled"] = False
    config = next(item for item in gev_app.mcp.configs() if item.id == "gev")
    assert config.enabled is False and config.autostart is False
    expected = "World view is turned off in settings." if broken == "disabled" else "Set it up from Studio > World."
    with pytest.raises(ServiceError) as raised:
        await listed(gev_app)
    assert expected in str(raised.value)
    assert not any(name.startswith("mcp__gev__") for name in gev_app.dispatcher.tools)
    for name, arguments in ((("world_show", {"area": {"place": "Penang"}})),
                            ("world_tour", {"title": "T", "steps": [{"area": {"place": "Penang"},
                                                                     "caption": "Hi", "seconds": 3}]})):
        with pytest.raises(ServiceError) as raised:
            await brain(gev_app, name, arguments)
        assert raised.value.code == ("world_disabled" if broken == "disabled" else "world_not_installed")
        assert expected in str(raised.value)
    assert gev_app.world.state == "stopped" and calls(gev_app) == []


async def test_turning_world_view_off_removes_the_gev_tools_and_on_lists_them(gev_app):
    await gev_app.world_tools.settings_changed()
    await until(lambda: "mcp__gev__get_earthquakes" in gev_app.dispatcher.tools)
    gev_app.settings["world"]["enabled"] = False
    await gev_app.settings_changed({"world": {"enabled": False}})
    assert not any(name.startswith("mcp__gev__") for name in gev_app.dispatcher.tools)
    assert gev_app.mcp.runtimes["gev"].client is None
    gev_app.settings["world"]["enabled"] = True
    await gev_app.settings_changed({"world": {"enabled": True}})
    await until(lambda: "mcp__gev__get_earthquakes" in gev_app.dispatcher.tools)
    # Startup lists the tools too (autostart), without starting the globe.
    assert gev_app.world.state == "stopped"


# --- policies ---------------------------------------------------------------------------------
async def test_the_default_policies(gev_app):
    tools = await listed(gev_app)
    assert len(tools) == GEV_TOOLS
    registered = {name.removeprefix("mcp__gev__") for name in gev_app.dispatcher.tools
                  if name.startswith("mcp__gev__")}
    denied = {"get_cctv_snapshot", "find_cctv_cameras", "find_alpr_cameras", "panel_request",
              "show_in_gods_eye_view", "get_bhote_koshi_flood"}
    assert registered == {item["name"] for item in tools} - denied and len(registered) == 24
    assert {name for name, policy in DEFAULT_POLICY.items() if policy == "ask"} == {
        "military_awareness", "find_military_installations"}
    permissions = gev_app.dispatcher.permissions()
    assert permissions["mcp__gev__military_awareness"] is POLICY_VALUES["ask"]
    assert permissions["mcp__gev__get_earthquakes"] is POLICY_VALUES["never_ask"]
    # A denied tool is refused (it isn't registered at all).
    with pytest.raises(ServiceError) as raised:
        await brain(gev_app, "mcp__gev__get_cctv_snapshot", {})
    assert raised.value.code == "tool_unavailable"
    # never_ask runs without a card; ask shows it, with God's Eye View on it.
    approvals = Approvals(gev_app)
    await brain(gev_app, "mcp__gev__get_terrain_height", {}, approvals)
    assert approvals.requests == []
    result = await brain(gev_app, "mcp__gev__military_awareness", {"area": {"place": "Penang"}},
                         approvals)
    (card,) = approvals.requests
    assert card["tool"] == "mcp__gev__military_awareness"
    assert card["args"]["server"] == "God's Eye View" and card["args"]["mcp_tool"] == "military_awareness"
    assert result["untrusted_content"] is True and result["server"] == "God's Eye View"
    declined = Approvals(gev_app, answer=False)
    with pytest.raises(ServiceError) as raised:
        await brain(gev_app, "mcp__gev__find_military_installations", {}, declined)
    assert raised.value.code == "permission_denied"
    assert "find_military_installations" not in [item["name"] for item in calls(gev_app)]


async def test_each_gev_tool_has_the_show_argument_and_both_providers_take_it(gev_app):
    from llm.claude import anthropic_tools
    from llm.gemini import gemini_tools

    await listed(gev_app)
    spec = gev_app.dispatcher.tools["mcp__gev__aircraft_in_area"]
    schema = spec.arguments.model_json_schema()
    assert schema["properties"]["show"] == SHOW_PROPERTY and "area" in schema["properties"]
    assert spec.description.startswith("[God's Eye View] ") and "show: false" in spec.description
    claude = {item["name"]: item for item in anthropic_tools(gev_app.dispatcher.schemas())}
    assert claude["mcp__gev__aircraft_in_area"]["input_schema"]["properties"]["show"]["type"] == "boolean"
    assert gemini_tools(gev_app.dispatcher.schemas())
    for name in ("world_show", "world_tour"):
        assert name in claude


# --- the globe comes first --------------------------------------------------------------------
async def test_the_sidecar_is_started_and_ready_before_each_gev_call(gev_app):
    await listed(gev_app)
    assert gev_app.world.state == "stopped"  # listing tools doesn't start the globe
    await brain(gev_app, "mcp__gev__get_terrain_height", {})
    assert gev_app.world.state == "ready"
    assert calls(gev_app)[-1] == {"name": "get_terrain_height", "arguments": {}, "globe": True}
    # A core caller gets the same: the globe stopped, the next call starts it again.
    await gev_app.world.stop()
    raw = await gev_app.mcp.call_tool("gev", "get_cyclones", {})
    assert raw["isError"] is False and calls(gev_app)[-1]["globe"] is True
    # In gaming mode the globe can't start, so the call is refused before reaching GEV.
    await gev_app.world.stop()
    count = len(calls(gev_app))
    gev_app.resources.state = "gaming"
    with pytest.raises(ServiceError):
        await brain(gev_app, "mcp__gev__get_terrain_height", {})
    assert len(calls(gev_app)) == count


# --- automatic views --------------------------------------------------------------------------
async def test_an_answer_with_a_view_shows_on_the_globe_and_show_false_skips_it(gev_app):
    await listed(gev_app)
    result = await brain(gev_app, "mcp__gev__aircraft_in_area", {"area": {"place": "Kuala Lumpur"}})
    assert result["world_view"] == "JARVIS is showing this on the World globe."
    assert calls(gev_app)[-1]["arguments"] == {"area": {"place": "Kuala Lumpur"}}  # no show
    await until(lambda: views(gev_app))
    (shown,) = views(gev_app)
    assert shown["title"] == "Aircraft in area"
    assert shown["view"]["layers"] == ["flights"] and "url" not in shown["view"]
    assert shown["view"]["camera"]["lat"] == 3.139
    await until(lambda: not gev_app.world_tools.shows)
    # show: false keeps the answer off the globe.
    result = await brain(gev_app, "mcp__gev__get_earthquakes", {"show": False})
    assert "world_view" not in result and calls(gev_app)[-1]["arguments"] == {}
    await asyncio.sleep(0.2)
    assert len(views(gev_app)) == 1
    # No view in the answer: nothing to show.
    result = await brain(gev_app, "mcp__gev__get_terrain_height", {})
    assert "world_view" not in result
    with pytest.raises(ServiceError) as raised:
        await brain(gev_app, "mcp__gev__get_earthquakes", {"show": "yes"})
    assert raised.value.code == "invalid_arguments"


async def test_a_view_with_camera_layers_is_never_shown(gev_app):
    await listed(gev_app)
    result = await brain(gev_app, "mcp__gev__find_infrastructure", {})
    assert result["world_view"] == (
        "Not shown on the globe: World view keeps the CCTV and licence-plate camera layers off."
    )
    await asyncio.sleep(0.2)
    assert views(gev_app) == []
    count = len(calls(gev_app))
    for name, arguments in (
        ("world_show", {"area": {"place": "Penang"}, "layers": ["flights", "cctv"]}),
        ("world_show", {"area": {"place": "Penang"}, "layers": ["alpr-cameras"]}),
        ("world_tour", {"title": "T", "steps": [
            {"area": {"place": "Penang"}, "caption": "One", "seconds": 3},
            {"view": {"camera": {"lat": 1, "lon": 2}, "layers": ["cctv"]}, "caption": "Two",
             "seconds": 3}]}),
    ):
        with pytest.raises(ServiceError) as raised:
            await brain(gev_app, name, arguments)
        assert raised.value.code == "world_view_private", name
    # Refused before GEV was asked anything for those steps.
    assert [item["name"] for item in calls(gev_app)[count:]] in ([], ["show_in_gods_eye_view"])
    assert views(gev_app) == [] and tours(gev_app) == []


# --- world_show -------------------------------------------------------------------------------
async def test_world_show_places_an_area_and_shows_it(gev_app):
    result = await brain(gev_app, "world_show", {"area": {"place": "Penang"}, "layers": ["flights"],
                                                 "title": "Penang\nnow"})
    assert result == {
        "shown": True, "camera": {"lat": 5.4141, "lon": 100.3288, "altitude_m": 60000,
                                  "heading_deg": 0, "pitch_deg": -90},
        "layers": ["flights"],
    }
    assert calls(gev_app)[-1]["name"] == "show_in_gods_eye_view"
    assert calls(gev_app)[-1]["arguments"] == {"area": {"place": "Penang"}, "layers": ["flights"]}
    (shown,) = views(gev_app)
    assert shown["title"] == "Penang now" and shown["view"]["camera"]["lat"] == 5.4141
    # The brain itself can't call GEV's show tool (deny), only the core does.
    assert "mcp__gev__show_in_gods_eye_view" not in gev_app.dispatcher.tools
    camera = await brain(gev_app, "world_show", {"camera": {"lat": 1.29, "lon": 103.85, "altitude_m": 5000}})
    assert camera["camera"]["altitude_m"] == 5000
    with pytest.raises(ServiceError) as raised:
        await brain(gev_app, "world_show", {"area": {"place": "Atlantis"}})
    assert raised.value.code == "world_view_unresolved"
    assert str(raised.value).startswith("God's Eye View couldn't place that: No place matched")
    gev_app.answers = {"ok": False}
    failed = await brain(gev_app, "world_show", {"area": {"place": "Penang"}})
    assert failed["shown"] is False


@pytest.mark.parametrize("arguments", [
    {},
    {"title": "Nothing"},
    {"area": {"place": "Penang"}, "camera": {"lat": 1, "lon": 2}},
    {"area": {"place": "Penang", "lat": 1, "lon": 2, "radius_km": 5}},
    {"area": {"lat": 1, "lon": 2}},
    {"area": {"bbox": [1, 2, 3]}},
    {"area": {"bbox": [100, 6, 101, 5]}},
    {"area": {"place": ""}},
    {"area": {"place": "x" * 201}},
    {"area": {"lat": 1, "lon": 2, "radius_km": 5000}},
    {"camera": {"lat": 91, "lon": 2}},
    {"camera": {"lat": 1, "lon": 2, "altitude_m": 10}},
    {"camera": {"lat": 1, "lon": 2, "pitch_deg": 10}},
    {"camera": {"lat": float("nan"), "lon": 2}},
    {"camera": {"lat": "1", "lon": 2}},
    {"area": {"place": "Penang"}, "layers": ["flights", "no-such-layer"]},
    {"area": {"place": "Penang"}, "style": "sepia"},
    {"follow": {"kind": "person", "id": "abc"}},
    {"follow": {"kind": "aircraft", "id": "a b"}},
    {"follow": {"kind": "satellite", "id": "25544", "cockpit": True}},
    {"area": {"place": "Penang"}, "annotations": [{"type": "pin"}]},
    {"area": {"place": "Penang"}, "annotations": [{"type": "pin", "latitude": 1}]},
    {"area": {"place": "Penang"}, "annotations": [{"type": "pin", "target": "x"}] * 25},
    {"area": {"place": "Penang"}, "title": "t" * 81},
    {"area": {"place": "Penang"}, "map": "osm"},
])
async def test_world_show_arguments_are_bounded_to_gevs_view_shape(gev_app, arguments):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await brain(gev_app, "world_show", arguments)
    assert calls(gev_app) == [] and gev_app.world.state == "stopped"


def test_world_show_schema_offers_no_camera_layers():
    schema = WorldShow.model_json_schema()
    items = schema["properties"]["layers"]["anyOf"][0]["items"]
    assert "flights" in items["enum"] and "cctv" not in items["enum"]
    assert "alpr-cameras" not in items["enum"]


# --- world_tour -------------------------------------------------------------------------------
TOUR = {
    "title": "Kuala Lumpur tonight",
    "steps": [
        {"area": {"place": "Kuala Lumpur"}, "layers": ["flights"],
         "caption": "Over 140 aircraft within 50 kilometres, sir.", "seconds": 5},
        {"camera": {"lat": 2.7456, "lon": 101.7072, "altitude_m": 20000},
         "caption": "Most are bound for KLIA.", "seconds": 4},
        {"view": {"camera": {"lat": 0, "lon": 120, "altitude_m": 15000000}, "layers": ["earthquakes"]},
         "caption": "And the region is quiet tonight.", "seconds": 30},
    ],
}


async def step_shown(app, count):
    await until(lambda: len(views(app)) >= count and len(app.world_tools.sleep.waits) >= count)


async def test_a_tour_plays_its_steps_in_order_with_their_timing(gev_app):
    clock = gev_app.world_tools.sleep
    result = await brain(gev_app, "world_tour", TOUR)
    assert result["started"] is True and result["steps"] == 3 and result["seconds"] == 39
    assert "speak" not in result  # typed: the tour bar shows the captions
    # Step 1 is on screen before the tool returns.
    assert [item["view"]["camera"]["lat"] for item in views(gev_app)] == [3.139]
    assert tours(gev_app)[-1] == {"active": True, "title": "Kuala Lumpur tonight",
                                  "caption": "Over 140 aircraft within 50 kilometres, sir."}
    await until(lambda: clock.waits == [5])
    assert len(views(gev_app)) == 1  # nothing moves until step 1's time is up
    clock.release()
    await step_shown(gev_app, 2)
    assert views(gev_app)[-1]["view"]["camera"]["lat"] == 2.7456
    assert views(gev_app)[-1]["title"] == "Kuala Lumpur tonight"
    assert tours(gev_app)[-1]["caption"] == "Most are bound for KLIA."
    assert clock.waits == [5, 4]
    clock.release()
    await step_shown(gev_app, 3)
    assert tours(gev_app)[-1]["caption"] == "And the region is quiet tonight."
    assert clock.waits == [5, 4, 30]
    clock.release()
    await until(lambda: gev_app.world_tools.current is None)
    assert tours(gev_app)[-1] == {"active": False, "title": None, "caption": None}
    # Every step was placed by GEV first; the tour bar showed each caption once.
    assert [item["name"] for item in calls(gev_app)] == ["show_in_gods_eye_view"] * 3
    assert [item["caption"] for item in tours(gev_app) if item["active"]] == [
        step["caption"] for step in TOUR["steps"]]


async def test_in_a_voice_session_the_tour_returns_its_captions_to_speak(gev_app):
    gev_app.voice.sessions["owner"] = SimpleNamespace(closed=False)
    try:
        result = await brain(gev_app, "world_tour", TOUR)
    finally:
        gev_app.voice.sessions.pop("owner")
    assert result["speak"] == [step["caption"] for step in TOUR["steps"]]
    assert "say these captions in order" in result["note"]
    assert tours(gev_app)[-1]["caption"] == TOUR["steps"][0]["caption"]


@pytest.mark.parametrize("stop", ["stop_tour", "barge_in", "new_request", "globe_stopped"])
async def test_stop_tour_barge_in_a_new_request_or_the_globe_stopping_ends_it(gev_app, stop):
    clock = gev_app.world_tools.sleep
    await brain(gev_app, "world_tour", TOUR)
    await until(lambda: clock.waits == [5])
    if stop == "stop_tour":
        reply = await rpc(gev_app, "world_tour_stop", {})
        assert reply["ok"] is True and reply["tour"]["active"] is False
    elif stop == "barge_in":
        gev_app.voice.end_world_tour()  # Live's interrupted, or "Hey Jarvis" while speaking
    elif stop == "new_request":
        assert gev_app.conversation.on_request == gev_app.world_tools.new_request
        gev_app.conversation.on_request("owner")
    else:
        await gev_app.world.stop()
        clock.release()  # the step's time runs out with the globe stopped
    await until(lambda: gev_app.world_tools.current is None)
    await asyncio.sleep(0.1)
    assert len(views(gev_app)) == 1 and gev_app.world.tour["active"] is False
    assert tours(gev_app)[-1]["active"] is False
    if stop == "globe_stopped":
        assert gev_app.world.state == "stopped"  # the tour didn't start it again


async def test_a_new_request_reaching_the_conversation_ends_the_tour(gev_app):
    from services.conversation import ConversationRequest

    clock = gev_app.world_tools.sleep
    await brain(gev_app, "world_tour", TOUR)
    await until(lambda: clock.waits == [5])
    turn = ConversationRequest(text="Thanks", conversation_id="5" * 32)

    def no_provider():
        raise ServiceError("provider_unavailable", "No AI provider in tests.")

    gev_app.conversation.provider_factory = no_provider
    with pytest.raises(ServiceError):  # the tour ends before the turn runs
        await gev_app.conversation.reply("owner", turn, gev_app.projects.get_current_project_path())
    await until(lambda: gev_app.world_tools.current is None)


async def test_only_one_tour_plays_at_a_time(gev_app):
    clock = gev_app.world_tools.sleep
    await brain(gev_app, "world_tour", TOUR)
    await until(lambda: clock.waits == [5])
    first = gev_app.world_tools.current
    second = {"title": "Penang", "steps": [{"area": {"place": "Penang"}, "caption": "Penang, sir.",
                                             "seconds": 3}]}
    await brain(gev_app, "world_tour", second)
    assert first.task.done() and gev_app.world_tools.current is not first
    assert tours(gev_app)[-1] == {"active": True, "title": "Penang", "caption": "Penang, sir."}
    await until(lambda: clock.waits == [5, 3])
    clock.release()
    await until(lambda: gev_app.world_tools.current is None)
    # The first tour never reached its step 2.
    assert [item["view"]["camera"]["lat"] for item in views(gev_app)] == [3.139, 5.4141]


@pytest.mark.parametrize("tour", [
    {"title": "T", "steps": []},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "x", "seconds": 3}] * 9},
    {"title": "", "steps": [{"area": {"place": "Penang"}, "caption": "x", "seconds": 3}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "x" * 201, "seconds": 3}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "\x07", "seconds": 3}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "x", "seconds": 2}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "x", "seconds": 31}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "caption": "x", "seconds": 3.5}]},
    {"title": "T", "steps": [{"caption": "x", "seconds": 3}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "seconds": 3}]},
    {"title": "T", "steps": [{"area": {"place": "Penang"}, "camera": {"lat": 1, "lon": 2},
                              "caption": "x", "seconds": 3}]},
])
async def test_tour_arguments_are_bounded(gev_app, tour):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await brain(gev_app, "world_tour", tour)
    assert calls(gev_app) == [] and tours(gev_app) == []


async def test_a_step_god_s_eye_view_cant_place_refuses_the_whole_tour(gev_app):
    tour = {"title": "T", "steps": [
        {"area": {"place": "Penang"}, "caption": "One", "seconds": 3},
        {"area": {"place": "Atlantis"}, "caption": "Two", "seconds": 3},
    ]}
    with pytest.raises(ServiceError) as raised:
        await brain(gev_app, "world_tour", tour)
    assert raised.value.code == "world_view_unresolved" and str(raised.value).startswith("Step 2: ")
    assert views(gev_app) == [] and tours(gev_app) == [] and gev_app.world_tools.current is None


# --- logs ---------------------------------------------------------------------------------------
async def test_no_results_arguments_or_captions_reach_the_logs(gev_app, caplog):
    caplog.set_level(logging.DEBUG)
    await listed(gev_app)
    await brain(gev_app, "mcp__gev__get_earthquakes", {"area": {"place": "ARGUMENT-MARKER"}})
    await until(lambda: views(gev_app))
    tour = {"title": "TITLE-MARKER", "steps": [
        {"area": {"place": "Penang"}, "caption": "CAPTION-MARKER", "seconds": 3}]}
    await brain(gev_app, "world_tour", tour)
    await until(lambda: gev_app.world_tools.sleep.waits)
    gev_app.world_tools.sleep.release()
    await until(lambda: gev_app.world_tools.current is None)
    text = "\n".join(record.getMessage() for record in caplog.records)
    for marker in ("RESULT-MARKER", "ARGUMENT-MARKER", "CAPTION-MARKER", "TITLE-MARKER", "Penang"):
        assert marker not in text
    assert "World tour started (1 steps)" in text


def test_world_show_and_world_tour_never_ask_by_default():
    import server

    defaults = server.DEFAULT_SETTINGS["tool_permissions"]
    assert defaults["world_show"] is False and defaults["world_tour"] is False
    assert {"world_show", "world_tour"} <= set(server.dispatcher.tools)
