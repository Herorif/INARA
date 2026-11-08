"""World view (W1, docs/WORLD_VIEW.md): the God's Eye View sidecar, its settings, the
owner-only world_* routes, the view push contract and the tour events.

A fake GEV only (tests/fixtures/fake_gev.py, run as vite.js by the test interpreter) on a
random free loopback port: never 4173 or 8000, no network, no real Node.
"""

import asyncio
import json
import shutil
import socket
import sys
from pathlib import Path

import psutil
import pytest
from pydantic import ValidationError

import services.world_view as world_view
from services.settings import SettingsPatch, WorldSettings, world_settings
from services.tools import ServiceError
from services.world_view import FRAME_ANCESTORS, WorldView, check_view, redact_stderr

FAKE = Path(__file__).parent / "fixtures" / "fake_gev.py"
VIEW = {
    "camera": {"lat": 3.139, "lon": 101.6869, "altitude_m": 60000, "heading_deg": 0, "pitch_deg": -90},
    "layers": ["flights"],
}
ROUTES = ("world_status", "world_start", "world_stop", "world_view_result", "world_tour_stop")


def free_port():
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in (4173, 8000):
            return port


def make_root(path, *, dist=True, vite=True):
    path.mkdir(parents=True, exist_ok=True)
    if dist:
        (path / "dist").mkdir(exist_ok=True)
        (path / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    if vite:
        script = path / "node_modules" / "vite" / "bin" / "vite.js"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FAKE, script)
    return path


def mode(app, **values):
    (Path(app.settings["world"]["root"]) / "fake-mode.json").write_text(
        json.dumps(values), encoding="utf-8"
    )


@pytest.fixture
async def world_app(application_factory, tmp_path):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "other": "intruder", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer", "tray": "resident"})
    app.sessions.local_owner = "owner"
    app.settings["world"] = {
        "root": str(make_root(tmp_path / "gev")),
        "node": sys.executable,
        "port": free_port(),
        "idle_minutes": 10,
        "enabled": True,
    }
    app.world.poll = 0.05
    yield app
    await app.world.close()


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


def emitted(app, event, room=None):
    return [
        call.args[1]
        for call in app.sio.emit.await_args_list
        if call.args[0] == event and (room is None or call.kwargs.get("room") == room)
    ]


async def until(check, timeout=20.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition timed out")


async def ready(app):
    reply = await rpc(app, "world_start")
    assert reply["ok"] is True, reply
    await until(lambda: app.world.state in ("ready", "error"))
    assert app.world.state == "ready", app.world.status()
    return reply


def fake_pid(app):
    return int((Path(app.settings["world"]["root"]) / "fake-pid.txt").read_text())


# --- settings ---------------------------------------------------------------------------------
def test_world_settings_defaults_and_expansion(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\fixture")
    values = world_settings({})
    assert values == {
        "root": r"C:\Users\fixture\tools\gods-eye-view",
        "node": r"C:\Users\fixture\tools\node-v24.22.2-win-x64\node.exe",
        "port": 4173,
        "idle_minutes": 10,
        "enabled": True,
    }
    stale = world_settings({"world": {"root": "relative", "node": r"C:\x\node.cmd", "port": 8000,
                                      "idle_minutes": 0, "enabled": "yes"}})
    assert stale == values
    custom = world_settings({"world": {"root": r"%USERPROFILE%\gev", "port": 4180, "idle_minutes": 3}})
    assert custom["root"] == r"C:\Users\fixture\gev" and custom["port"] == 4180
    assert custom["idle_minutes"] == 3


@pytest.mark.parametrize(
    "patch",
    [
        {"port": 8000}, {"port": 80}, {"port": 70000}, {"port": True}, {"port": "4173"},
        {"node": r"C:\tools\node\npm.cmd"}, {"node": "node.exe"}, {"root": "gods-eye-view"},
        {"root": "C:\\gev\x00"}, {"idle_minutes": 0}, {"idle_minutes": 1441}, {"enabled": None},
        {"shell": True}, {},
    ],
)
def test_world_settings_patch_is_validated(patch):
    with pytest.raises(ValidationError):
        WorldSettings.model_validate(patch)


async def test_world_settings_save_through_the_settings_service(world_app):
    world_app.settings.pop("world")
    result = world_app.settings_service.apply(SettingsPatch.model_validate({"world": {"port": 4180}}))
    assert result["world"]["port"] == 4180
    assert result["world"]["root"] == r"%USERPROFILE%\tools\gods-eye-view"
    assert world_settings(result)["port"] == 4180


# --- status reasons ---------------------------------------------------------------------------
async def test_status_reasons(world_app, tmp_path):
    world = world_app.world
    settings = world_app.settings["world"]
    status = world.status()
    assert status["state"] == "stopped" and status["reason"] is None
    assert status["url"] == f"http://127.0.0.1:{settings['port']}"
    assert status["tour"] == {"active": False, "title": None, "caption": None}

    settings["node"] = str(tmp_path / "missing" / "node.exe")
    assert (world.status()["state"], world.status()["reason"]) == ("not_installed", "node_missing")
    settings["node"] = sys.executable
    settings["root"] = str(tmp_path / "nowhere")
    assert world.status()["reason"] == "root_missing"
    settings["root"] = str(make_root(tmp_path / "unbuilt", dist=False))
    assert world.status()["reason"] == "dist_missing"
    settings["root"] = str(make_root(tmp_path / "no-vite", vite=False))
    assert world.status()["reason"] == "dist_missing"
    assert world.status()["message"] == "God's Eye View isn't built yet."

    reply = await rpc(world_app, "world_start")
    assert reply == {"ok": False, "code": "world_not_installed", "message": "God's Eye View isn't built yet."}
    assert world.process is None


async def test_disabled_world_never_starts(world_app):
    world_app.settings["world"]["enabled"] = False
    status = (await rpc(world_app, "world_status"))["world"]
    assert status["state"] == "stopped" and status["enabled"] is False
    assert status["message"] == "World view is turned off in settings."
    reply = await rpc(world_app, "world_start")
    assert reply["code"] == "world_disabled" and world_app.world.process is None


# --- start, health, stop -----------------------------------------------------------------------
async def test_start_health_and_stop_kill_the_whole_tree(world_app):
    port = world_app.settings["world"]["port"]
    reply = await rpc(world_app, "world_start")
    assert reply["ok"] is True and reply["world"]["state"] in ("starting", "ready")
    await until(lambda: world_app.world.state == "ready")
    states = [item["state"] for item in emitted(world_app, "world_status", room="client")]
    assert states[0] == "starting" and states[-1] == "ready"
    assert emitted(world_app, "world_status", room="other") == []
    pid = fake_pid(world_app)
    assert psutil.pid_exists(pid) and world_view.port_answers(port)

    again = await rpc(world_app, "world_start")
    assert again["world"]["state"] == "ready" and fake_pid(world_app) == pid

    stopped = await rpc(world_app, "world_stop")
    assert stopped == {"ok": True, "world": world_app.world.status()}
    assert stopped["world"]["state"] == "stopped" and stopped["world"]["diagnostics"] is None
    await until(lambda: not psutil.pid_exists(pid), timeout=5)
    assert not world_view.port_answers(port)
    assert world_app.world.process is None and world_app.world.job is None
    assert emitted(world_app, "world_status")[-1]["state"] == "stopped"


async def test_busy_port_is_an_error_and_spawns_nothing(world_app):
    spawned = []

    async def spawner(*args):
        spawned.append(args)
        raise AssertionError("must not spawn")

    world_app.world.spawner = spawner
    port = world_app.settings["world"]["port"]
    with socket.socket() as other:
        other.bind(("127.0.0.1", port))
        other.listen()
        reply = await rpc(world_app, "world_start")
        with pytest.raises(ServiceError) as error:
            await world_app.world.ensure_ready()
    assert reply["ok"] is True
    assert reply["world"]["state"] == "error"
    assert reply["world"]["message"] == f"Port {port} is in use by another program."
    assert spawned == []
    assert str(error.value) == f"Port {port} is in use by another program."


async def test_a_globe_that_never_answers_times_out(world_app):
    mode(world_app, never=True)
    world_app.world.start_timeout = 0.5
    await rpc(world_app, "world_start")
    pid = None
    await until(lambda: (Path(world_app.settings["world"]["root"]) / "fake-pid.txt").exists())
    pid = fake_pid(world_app)
    await until(lambda: world_app.world.state == "error")
    assert world_app.world.status()["message"] == "The globe didn't start within 60 seconds."
    await until(lambda: not psutil.pid_exists(pid), timeout=5)


async def test_a_broken_api_route_is_not_ready(world_app):
    mode(world_app, broken_api=True)
    world_app.world.start_timeout = 0.8
    await rpc(world_app, "world_start")
    await until(lambda: world_app.world.state != "starting")
    assert world_app.world.state == "error"


async def test_exit_while_starting_keeps_a_redacted_stderr_tail(world_app, monkeypatch):
    home = str(Path.home())
    secret = "sk-ant-api03-" + "Q" * 40
    mode(world_app, exit=3, stderr=f"Error at {home}\\tools\\x.js\nOPENAI_API_KEY={secret}\n\x1b[31mboom\x1b[0m\n")
    await rpc(world_app, "world_start")
    await until(lambda: world_app.world.state == "error")
    status = world_app.world.status()
    assert status["message"] == "The globe stopped while starting."
    assert status["diagnostics"]["exit_code"] == 3
    tail = status["diagnostics"]["stderr"]
    assert "%USERPROFILE%" in tail and home not in tail and secret not in tail
    assert "boom" in tail and "\x1b" not in tail
    assert world_app.world.process is None


async def test_port_taken_while_starting_reads_as_busy(world_app):
    mode(world_app, exit=1, stderr="Error: Port 4173 is already in use\n")
    await rpc(world_app, "world_start")
    await until(lambda: world_app.world.state == "error")
    port = world_app.settings["world"]["port"]
    assert world_app.world.message == f"Port {port} is in use by another program."


def test_redact_stderr_is_bounded():
    text = redact_stderr(("line\n" * 2000).encode())
    assert len(text) <= world_view.STDERR_SHOWN


# --- idle, gaming, shutdown --------------------------------------------------------------------
async def test_idle_stop_counts_from_the_last_page_or_brain_use(world_app):
    now = [1000.0]
    world_app.world.clock = lambda: now[0]
    world_app.world.tick = 0.02
    world_app.settings["world"]["idle_minutes"] = 1
    await rpc(world_app, "world_status", {"page": True})
    await ready(world_app)
    pid = fake_pid(world_app)
    # The page is open and reporting in: never idle.
    now[0] += 100
    await rpc(world_app, "world_status", {"page": True})
    now[0] += 100
    await rpc(world_app, "world_status", {"page": True})
    await asyncio.sleep(0.15)
    assert world_app.world.state == "ready"
    # Closed: idle after world.idle_minutes.
    await rpc(world_app, "world_status", {"page": False})
    now[0] += 30
    await asyncio.sleep(0.15)
    assert world_app.world.state == "ready"
    world_app.world.touch()  # brain use restarts the countdown
    now[0] += 59
    await asyncio.sleep(0.15)
    assert world_app.world.state == "ready"
    now[0] += 2
    await until(lambda: world_app.world.state == "stopped", timeout=5)
    await until(lambda: not psutil.pid_exists(pid), timeout=5)


async def test_a_page_that_stops_reporting_counts_as_closed(world_app):
    now = [1000.0]
    world_app.world.clock = lambda: now[0]
    world_app.world.tick = 0.02
    world_app.settings["world"]["idle_minutes"] = 1
    await ready(world_app)
    now[0] += world_view.PAGE_TTL + 61
    await until(lambda: world_app.world.state == "stopped", timeout=5)


async def test_gaming_mode_stops_at_once_and_refuses_start(world_app):
    await ready(world_app)
    pid = fake_pid(world_app)
    world_app.resources.select("gaming")
    await world_app.restrict_resources()
    assert world_app.world.state == "stopped" and world_app.world.process is None
    await until(lambda: not psutil.pid_exists(pid), timeout=5)
    reply = await rpc(world_app, "world_start")
    assert reply["ok"] is False and reply["code"] == "resource_policy"
    world_app.resources.select("chat")


async def test_turning_world_view_off_stops_it(world_app):
    world_app.world.tick = 0.02
    await ready(world_app)
    world_app.settings["world"]["enabled"] = False
    await until(lambda: world_app.world.state == "stopped", timeout=5)


async def test_core_shutdown_stops_it(world_app):
    await ready(world_app)
    pid = fake_pid(world_app)
    await world_app.close()
    assert world_app.world.state == "stopped"
    await until(lambda: not psutil.pid_exists(pid), timeout=5)


# --- the launch: argv and environment ----------------------------------------------------------
async def test_argv_is_node_on_vite_preview_without_a_shell(world_app, monkeypatch):
    calls = []
    real = asyncio.create_subprocess_exec

    async def record(*args, **kwargs):
        calls.append((args, kwargs))
        return await real(*args, **kwargs)

    async def no_shell(*_args, **_kwargs):
        raise AssertionError("World view must not use a shell")

    monkeypatch.setattr(world_view.asyncio, "create_subprocess_exec", record)
    monkeypatch.setattr(world_view.asyncio, "create_subprocess_shell", no_shell)
    await ready(world_app)
    settings = world_app.settings["world"]
    script = str(Path(settings["root"]) / "node_modules" / "vite" / "bin" / "vite.js")
    expected = [sys.executable, script, "preview", "--host", "127.0.0.1", "--port",
                str(settings["port"]), "--strictPort"]
    (args, kwargs), = calls
    assert list(args) == expected
    assert "shell" not in kwargs and kwargs["cwd"] == settings["root"]
    assert not any(part.lower().endswith((".cmd", ".bat")) or "npm" in part.lower() for part in args)
    recorded = json.loads((Path(settings["root"]) / "fake-argv.json").read_text())
    assert recorded[1:] == expected[2:]


async def test_environment_has_no_ai_keys_and_the_gev_variables(world_app, monkeypatch):
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
                 "JARVIS_SESSION_TOKEN", "GEV_EMBED_FRAME_ANCESTORS", "NODE_OPTIONS"):
        monkeypatch.setenv(name, "parent-secret-" + "x" * 30)
    await ready(world_app)
    env = json.loads((Path(world_app.settings["world"]["root"]) / "fake-env.json").read_text())
    upper = {key.upper(): value for key, value in env.items()}
    assert upper["OPENAI_API_KEY"] == "" and upper["GEMINI_API_KEY"] == ""
    assert upper["GEV_ALLOWED_HOSTS"] == "127.0.0.1,localhost"
    assert upper["GEV_EMBED_FRAME_ANCESTORS"] == "file: http://localhost:5173"
    assert not any("parent-secret" in value for value in env.values())
    for name in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "JARVIS_SESSION_TOKEN", "NODE_OPTIONS"):
        assert name not in upper
    built = WorldView.environment(world_settings(world_app.settings))
    allowed = set(world_view.ENV_PASSTHROUGH) | set(world_view.AI_KEYS) | {
        "PATH", "GEV_ALLOWED_HOSTS", "GEV_EMBED_FRAME_ANCESTORS", "NO_COLOR"}
    assert set(built) <= allowed


def test_frame_ancestors_are_the_renderer_origins():
    from application import RENDERER_ORIGINS

    assert {"file:" if origin == "file://" else origin for origin in RENDERER_ORIGINS} == set(
        FRAME_ANCESTORS
    )


# --- the view push contract ---------------------------------------------------------------------
async def test_show_view_goes_to_the_open_world_page_and_returns_its_answer(world_app):
    world_app.sessions.principals["second"] = "owner"
    world_app.sessions.roles["second"] = "renderer"
    await rpc(world_app, "world_status", {"page": True}, sid="second")
    task = asyncio.create_task(world_app.world.show_view(VIEW, title="Kuala Lumpur\nflights"))
    await until(lambda: emitted(world_app, "world_view"))
    (call,) = [c for c in world_app.sio.emit.await_args_list if c.args[0] == "world_view"]
    assert call.kwargs["room"] == "second"
    payload = call.args[1]
    assert payload["view"] == VIEW and payload["title"] == "Kuala Lumpur flights"
    assert len(payload["id"]) == 32
    # Only the renderer it went to can answer.
    wrong = await rpc(world_app, "world_view_result", {"id": payload["id"], "ok": True}, sid="client")
    assert wrong["code"] == "world_view_unknown"
    intruder = await rpc(world_app, "world_view_result", {"id": payload["id"], "ok": True}, sid="other")
    assert intruder["code"] == "permission_denied"
    steps = [{"step": "set_layer_visibility", "ok": True}, {"step": "camera", "ok": True}]
    reply = await rpc(world_app, "world_view_result", {"id": payload["id"], "ok": True, "steps": steps},
                      sid="second")
    assert reply == {"ok": True}
    assert await task == {"ok": True, "steps": steps}
    assert world_app.world.pending == {}
    late = await rpc(world_app, "world_view_result", {"id": payload["id"], "ok": True}, sid="second")
    assert late["code"] == "world_view_unknown"


async def test_show_view_opens_the_page_in_a_renderer_when_none_shows_it(world_app):
    task = asyncio.create_task(world_app.world.show_view(VIEW))
    await until(lambda: emitted(world_app, "world_view"))
    (call,) = [c for c in world_app.sio.emit.await_args_list if c.args[0] == "world_view"]
    assert call.kwargs["room"] == "client" and call.args[1]["title"] is None
    # The sidecar was started first.
    assert world_app.world.state == "ready"
    await rpc(world_app, "world_view_result", {"id": call.args[1]["id"], "ok": False,
                                               "steps": [{"step": "camera", "ok": False, "error": "x"}]})
    assert await task == {"ok": False, "steps": [{"step": "camera", "ok": False, "error": "x"}]}


async def test_show_view_times_out(world_app):
    await ready(world_app)
    world_app.world.view_timeout = 0.1
    with pytest.raises(ServiceError) as error:
        await world_app.world.show_view(VIEW)
    assert error.value.code == "world_view_timeout" and world_app.world.pending == {}


async def test_stop_fails_a_pending_view(world_app):
    await ready(world_app)
    task = asyncio.create_task(world_app.world.show_view(VIEW))
    await until(lambda: world_app.world.pending)
    await rpc(world_app, "world_stop")
    with pytest.raises(ServiceError) as error:
        await task
    assert error.value.code == "world_stopped"


@pytest.mark.parametrize(
    "view, code",
    [
        ([], "world_view_invalid"),
        ({"layers": "flights"}, "world_view_invalid"),
        ({"camera": {"lat": float("nan")}}, "world_view_invalid"),
        ({"annotations": [{"label": "x" * 20000}]}, "world_view_invalid"),
        ({"layers": ["flights", "cctv"]}, "world_view_private"),
        ({"layers": ["alpr-cameras"]}, "world_view_private"),
    ],
)
async def test_show_view_refuses_bad_and_private_views_before_anything_starts(world_app, view, code):
    with pytest.raises(ServiceError) as error:
        await world_app.world.show_view(view)
    assert error.value.code == code
    assert world_app.world.process is None and emitted(world_app, "world_view") == []


def test_check_view_copies_plain_json():
    copy = check_view(VIEW)
    assert copy == VIEW and copy is not VIEW


async def test_show_view_needs_the_unlocked_owner(world_app):
    world_app.settings["face_auth_enabled"] = True
    with pytest.raises(ServiceError) as error:
        await world_app.world.show_view(VIEW)
    assert error.value.code == "world_locked" and world_app.world.process is None


async def test_show_view_in_gaming_mode_is_refused(world_app):
    world_app.resources.select("gaming")
    with pytest.raises(ServiceError) as error:
        await world_app.world.show_view(VIEW)
    assert error.value.code == "resource_policy"
    world_app.resources.select("chat")


# --- the tour events ----------------------------------------------------------------------------
async def test_tour_events_and_stop_tour(world_app):
    stopped = []

    async def on_stop():
        stopped.append(True)

    world_app.world.on_tour_stop = on_stop
    tour = await world_app.world.set_tour(True, title="Flights over KL", caption="Here is the airport.\x07")
    assert tour == {"active": True, "title": "Flights over KL", "caption": "Here is the airport."}
    assert emitted(world_app, "world_tour", room="client") == [tour]
    assert emitted(world_app, "world_tour", room="other") == []
    assert (await rpc(world_app, "world_status"))["world"]["tour"] == tour
    reply = await rpc(world_app, "world_tour_stop")
    assert reply == {"ok": True, "tour": {"active": False, "title": None, "caption": None}}
    assert stopped == [True]
    assert emitted(world_app, "world_tour")[-1]["active"] is False
    # Nothing to stop: the handler is not called again.
    await rpc(world_app, "world_tour_stop")
    assert stopped == [True]


async def test_stopping_the_globe_ends_the_tour(world_app):
    await ready(world_app)
    await world_app.world.set_tour(True, title="Tour", caption="Look")
    await rpc(world_app, "world_stop")
    assert world_app.world.tour["active"] is False
    assert emitted(world_app, "world_tour")[-1] == {"active": False, "title": None, "caption": None}


# --- route ownership ----------------------------------------------------------------------------
@pytest.mark.parametrize("sid", ["other", "tray", "unknown", "locked"])
@pytest.mark.parametrize(
    "name, data",
    [
        ("world_status", {}), ("world_status", {"page": True}), ("world_start", {}), ("world_stop", {}),
        ("world_view_result", {"id": "0" * 32, "ok": True}), ("world_tour_stop", {}),
    ],
)
async def test_routes_are_owner_renderer_only(world_app, sid, name, data):
    if sid == "locked":
        world_app.settings["face_auth_enabled"] = True
        sid = "client"
    reply = await rpc(world_app, name, data, sid=sid)
    assert reply["ok"] is False
    assert reply["code"] in ("permission_denied", "authentication_required")
    assert world_app.world.process is None and world_app.world.pages == {}


@pytest.mark.parametrize(
    "name, data",
    [
        ("world_status", {"page": "yes"}), ("world_status", {"extra": 1}), ("world_start", {"port": 1}),
        ("world_stop", []), ("world_view_result", {"id": "x", "ok": True}),
        ("world_view_result", {"id": "0" * 32, "ok": "true"}),
        ("world_view_result", {"id": "0" * 32, "ok": True, "steps": [{"step": "a", "ok": True, "x": 1}]}),
        ("world_tour_stop", {"now": True}),
    ],
)
async def test_routes_validate_strictly(world_app, name, data):
    reply = await rpc(world_app, name, data)
    assert reply == {"ok": False, "code": "invalid_arguments", "message": "Invalid World view request."}
    assert world_app.world.process is None


def test_routes_are_registered_and_in_the_policy_matrix(application_factory):
    app = application_factory()
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "ROUTE_POLICY_MATRIX.json").read_text(encoding="utf-8")
    )
    for name in ROUTES:
        assert name in app.sio.handlers["/"]
        assert matrix["socket_routes"][name]["replacement"].startswith("WorldView")
