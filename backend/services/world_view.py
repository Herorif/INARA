"""World view (docs/WORLD_VIEW.md): the open-source God's Eye View globe, run on this PC.

``WorldView`` owns one sidecar: Node 24 running God's Eye View's ``vite preview`` on
127.0.0.1:<world.port>. It starts on demand (the World page, later the brain), and stops
when nothing uses it for ``world.idle_minutes``, on the page's Stop, in gaming or resident
mode and at core shutdown. Node runs directly from an explicit argv (never a shell, never
npm.cmd), in a kill-on-close Job Object so it dies with the core, with a minimal
environment: no AI keys (JARVIS is the only voice), GEV_ALLOWED_HOSTS loopback only and
GEV_EMBED_FRAME_ANCESTORS naming JARVIS's renderer origins.

Status (``world_status``): not_installed (reason node_missing, root_missing or dist_missing),
stopped, starting, ready or error (a plain message). Logs carry only the state and the exit
code; the last stderr lines, bounded and redacted, are in the status's diagnostics.

The view push contract (for the brain): ``show_view(view, title=None)`` sends
``world_view {id, view, title}`` to the owner's renderer showing the World page (it opens the
page when none does), and awaits its ``world_view_result {id, ok, steps}`` for 15 s. With no
JARVIS window open it fails at once (``require_window``), before the globe is started. A
``world_tour {active, title, caption}`` event drives the page's tour bar; ``world_tour_stop``
is its Stop tour.

Routes (owner renderer only, unlocked): ``world_status`` {page?}, ``world_start``,
``world_stop``, ``world_view_result`` and ``world_tour_stop``.
"""

import asyncio
import inspect
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Annotated

import httpx
from pydantic import Field, StrictBool, StrictStr, StringConstraints, ValidationError

from services import job_object
from services.child_env import minimal_env
from services.log import get_logger, redact
from services.settings import EmptyRequest, world_settings
from services.tools import ServiceError

logger = get_logger(__name__)

# JARVIS's renderer origins (application.RENDERER_ORIGINS): the packaged page loaded from
# dist/index.html over file://, and the Vite dev server. CSP has no source expression for a
# single file URL, so the packaged renderer is named by its scheme, "file:".
FRAME_ANCESTORS = ("file:", "http://localhost:5173")
ALLOWED_HOSTS = "127.0.0.1,localhost"
# GEV's own voice and chat agent stays unconfigured: these are set empty, so a .env in the
# GEV folder can't fill them in either (its loader never overrides a variable that is set).
AI_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY")
# GEV's feeds are HTTPS fetched by Node: trust the Windows certificate store, as Chromium and
# the setup script's Git (schannel) do, so a PC whose antivirus inspects HTTPS still works.
SYSTEM_CA = {"NODE_USE_SYSTEM_CA": "1"}
# Ready once the app page and one /api route (local, no network) both answer.
HEALTH_PATHS = ("/", "/api/mapillary/status")
# Layers JARVIS never turns on: public CCTV and licence-plate reader cameras.
PRIVATE_LAYERS = frozenset({"cctv", "alpr-cameras"})
START_TIMEOUT = 60.0
VIEW_TIMEOUT = 15.0
STOP_TIMEOUT = 5.0
TICK = 5.0
POLL = 0.25
# A World page reports in every 30 s; one that stops reporting counts as closed after this.
PAGE_TTL = 120.0
STDERR_BYTES = 8192
STDERR_SHOWN = 1500
VIEW_BYTES = 16_384
TITLE_CHARS = 80
CAPTION_CHARS = 400

NOT_INSTALLED = {
    "node_missing": "Node 24 for World view isn't on this PC.",
    "root_missing": "God's Eye View isn't on this PC.",
    "dist_missing": "God's Eye View isn't built yet.",
}
NO_WINDOW = "Open JARVIS on the World page to see the globe."
MESSAGES = {
    "busy": "Port {port} is in use by another program.",
    "spawn": "The globe couldn't start on this PC.",
    "start_timeout": "The globe didn't start within 60 seconds.",
    "exit_starting": "The globe stopped while starting.",
    "exit": "The globe stopped unexpectedly.",
}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(value, limit):
    """One line of plain text, at most ``limit`` characters, or None when blank."""
    if not isinstance(value, str):
        return None
    text = " ".join(_CONTROL.sub(" ", value).split())
    return text[:limit] or None


def redact_stderr(raw):
    """The last lines of Node's stderr: no colour codes, the profile folder as %USERPROFILE%,
    secret shapes masked, at most STDERR_SHOWN characters."""
    text = _ANSI.sub("", raw.decode("utf-8", errors="replace"))
    home = os.environ.get("USERPROFILE") or str(Path.home())
    if home:
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.IGNORECASE)
    text = redact(_CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n")))
    return text[-STDERR_SHOWN:].lstrip("\n")


def port_answers(port, timeout=0.3):
    """True when something on this PC accepts connections on 127.0.0.1:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


async def spawn(argv, cwd, env):
    """Start Node from an explicit argv (no shell) in a kill-on-close job (services.job_object):
    stdout discarded, stderr piped."""
    return await job_object.spawn(
        argv, cwd=cwd, env=env, label="The World view globe",
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )


def check_view(view):
    """The view as plain JSON (God's Eye View validates its fields): an object of at most
    VIEW_BYTES, without the CCTV or licence-plate camera layers."""
    if not isinstance(view, dict):
        raise ServiceError("world_view_invalid", "A view must be an object.")
    try:
        text = json.dumps(view, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ServiceError("world_view_invalid", "A view must be plain JSON.") from None
    if len(text.encode()) > VIEW_BYTES:
        raise ServiceError("world_view_invalid", "That view is too large to show.")
    layers = view.get("layers", [])
    if not isinstance(layers, list) or any(not isinstance(item, str) for item in layers):
        raise ServiceError("world_view_invalid", "A view's layers must be a list of names.")
    if PRIVATE_LAYERS & set(layers):
        raise ServiceError(
            "world_view_private",
            "World view keeps the CCTV and licence-plate camera layers off.",
        )
    return json.loads(text)


class WorldView:
    def __init__(self, app, *, spawner=spawn, clock=time.monotonic):
        self.app, self.spawner, self.clock = app, spawner, clock
        self.start_timeout, self.view_timeout, self.tick, self.poll = (
            START_TIMEOUT, VIEW_TIMEOUT, TICK, POLL
        )
        self.lock = asyncio.Lock()
        self.state = "stopped"
        self.message = None
        self.exit_code = None
        self.stderr = bytearray()
        self.process = self.job = None
        self.port = None
        self.generation = 0
        self.stopping = False
        self.tasks = set()
        self.settled = asyncio.Event()
        self.settled.set()
        self.last_used = clock()
        self.pages = {}  # renderer sid -> when its World page last reported in
        self.pending = {}  # view id -> (sid, future)
        self.tour = {"active": False, "title": None, "caption": None}
        # W4 sets this to end its tour when the owner presses Stop tour.
        self.on_tour_stop = None

    # --- settings, install check, launch ---------------------------------------------------
    def settings(self):
        return world_settings(self.app.settings)

    @staticmethod
    def install_problem(values):
        """not_installed's reason, or None when Node 24 and a built God's Eye View are there."""
        if not Path(values["node"]).is_file():
            return "node_missing"
        root = Path(values["root"])
        if not root.is_dir():
            return "root_missing"
        if not (root / "dist" / "index.html").is_file() or not (
            root / "node_modules" / "vite" / "bin" / "vite.js"
        ).is_file():
            return "dist_missing"
        return None

    @staticmethod
    def command(values):
        """Node 24 straight on vite's preview script: loopback, fixed port."""
        script = Path(values["root"]) / "node_modules" / "vite" / "bin" / "vite.js"
        return [
            str(values["node"]), str(script), "preview", "--host", "127.0.0.1",
            "--port", str(values["port"]), "--strictPort",
        ]

    @staticmethod
    def environment(values, extra=None):
        """The minimal child environment (services.child_env) and GEV's own variables.

        PATH is only Node's folder and System32. ``extra`` is where a GEV provider key
        from the encrypted store would go (none is configured today); a parent key never
        reaches Node.
        """
        system = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32"
        gev = {
            "PATH": os.pathsep.join((str(Path(values["node"]).parent), str(system))),
            **{key: "" for key in AI_KEYS},
            "GEV_ALLOWED_HOSTS": ALLOWED_HOSTS,
            "GEV_EMBED_FRAME_ANCESTORS": " ".join(FRAME_ANCESTORS),
            "NO_COLOR": "1",
            **SYSTEM_CA,
            **(extra or {}),
        }
        return minimal_env(gev)

    # --- status -----------------------------------------------------------------------------
    def status(self):
        values = self.settings()
        state, reason, message = self.state, None, self.message
        if state in ("stopped", "error"):
            reason = self.install_problem(values)
            if reason:
                state, message = "not_installed", NOT_INSTALLED[reason]
            elif state == "stopped" and not values["enabled"]:
                message = "World view is turned off in settings."
        port = self.port if self.state in ("starting", "ready") else values["port"]
        diagnostics = None
        if self.exit_code is not None or (state == "error" and self.stderr):
            diagnostics = {"exit_code": self.exit_code, "stderr": redact_stderr(bytes(self.stderr))}
        return {
            "state": state,
            "reason": reason,
            "message": message,
            "port": port,
            "url": f"http://127.0.0.1:{port}",
            "enabled": values["enabled"],
            "tour": dict(self.tour),
            "diagnostics": diagnostics,
        }

    def owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def owner_rooms(self):
        owner = self.owner()
        if owner is None or not self.app.sessions.authenticated(owner):
            return ()
        return self.app.sessions.rooms(owner, "renderer")

    async def emit_owner(self, event, payload):
        for sid in self.owner_rooms():
            try:
                await self.app.sio.emit(event, payload, room=sid)
            except Exception:
                logger.warning("World view event %s could not be delivered", event)

    async def publish(self):
        await self.emit_owner("world_status", self.status())

    def set_state(self, state, message=None):
        if state != self.state:
            logger.info("World view %s", state)
        self.state, self.message = state, message

    # --- use --------------------------------------------------------------------------------
    def touch(self):
        """Brain or page use: restarts the idle countdown."""
        self.last_used = self.clock()

    def page(self, sid, open_):
        """The World page in renderer ``sid`` opened (and reports in) or closed."""
        if open_:
            self.pages[sid] = self.clock()
        else:
            self.pages.pop(sid, None)
        self.touch()

    def open_pages(self):
        rooms, now = set(self.owner_rooms()), self.clock()
        for sid in [sid for sid in self.pages if sid not in rooms]:
            self.pages.pop(sid, None)
        return sorted(
            (sid for sid, seen in self.pages.items() if now - seen <= PAGE_TTL),
            key=lambda sid: self.pages[sid], reverse=True,
        )

    # --- start / stop -----------------------------------------------------------------------
    async def start(self):
        """Start the globe if it isn't running. Returns the status at once; the health check
        runs in the background and pushes world_status. Policy refusals raise ServiceError."""
        values = self.settings()
        if not values["enabled"]:
            raise ServiceError("world_disabled", "World view is turned off in settings.")
        reason = self.install_problem(values)
        if reason:
            raise ServiceError("world_not_installed", NOT_INSTALLED[reason])
        self.app.resources.require_heavy()
        self.touch()
        async with self.lock:
            if self.state in ("starting", "ready"):
                return self.status()
            self.exit_code, self.stderr = None, bytearray()
            port = values["port"]
            if await asyncio.to_thread(port_answers, port):
                self.set_state("error", MESSAGES["busy"].format(port=port))
                await self.publish()
                return self.status()
            argv, env = self.command(values), self.environment(values)
            try:
                process, job = await self.spawner(argv, values["root"], env)
            except Exception as exc:
                logger.warning("World view could not start (%s)", type(exc).__name__)
                self.set_state("error", MESSAGES["spawn"])
                await self.publish()
                return self.status()
            self.generation += 1
            self.process, self.job, self.port, self.stopping = process, job, port, False
            self.settled.clear()
            self.set_state("starting")
            generation = self.generation
            self.spawn_task(self.read_stderr(process), f"world-stderr-{generation}")
            self.spawn_task(self.watch(process, generation), f"world-exit-{generation}")
            self.spawn_task(self.boot(generation), f"world-boot-{generation}")
            self.spawn_task(self.idle(generation), f"world-idle-{generation}")
        await self.publish()
        return self.status()

    def spawn_task(self, coroutine, name):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def read_stderr(self, process):
        stream = process.stderr
        if stream is None:
            return
        try:
            while chunk := await stream.read(4096):
                self.stderr.extend(chunk)
                del self.stderr[:-STDERR_BYTES]
        except (OSError, ValueError, asyncio.CancelledError):
            pass

    async def boot(self, generation):
        """Poll the app page and one /api route until both answer, for start_timeout."""
        deadline = self.clock() + self.start_timeout
        async with httpx.AsyncClient(trust_env=False, timeout=2.0, follow_redirects=False) as client:
            while self.generation == generation and self.state == "starting":
                if await self.healthy(client, self.port):
                    async with self.lock:
                        if self.generation == generation and self.state == "starting":
                            self.set_state("ready")
                            self.settled.set()
                    await self.publish()
                    return
                if self.clock() >= deadline:
                    await self.fail(generation, MESSAGES["start_timeout"])
                    return
                await asyncio.sleep(self.poll)

    @staticmethod
    async def healthy(client, port):
        try:
            for path in HEALTH_PATHS:
                response = await client.get(f"http://127.0.0.1:{port}{path}")
                kind = response.headers.get("content-type", "")
                expected = "json" if path.startswith("/api/") else "text/html"
                if response.status_code != 200 or expected not in kind:
                    return False
            return True
        except httpx.HTTPError:
            return False

    async def watch(self, process, generation):
        code = await process.wait()
        if self.stopping or self.generation != generation:
            return
        await asyncio.sleep(0.05)  # let the stderr reader take the last lines
        stderr = bytes(self.stderr).decode("utf-8", errors="replace")
        message = MESSAGES["exit_starting" if self.state == "starting" else "exit"]
        if "EADDRINUSE" in stderr or "already in use" in stderr:
            message = MESSAGES["busy"].format(port=self.port)
        await self.fail(generation, message, exit_code=code)

    async def fail(self, generation, message, *, exit_code=None):
        async with self.lock:
            if self.generation != generation or self.process is None:
                return
            code = await self.terminate()
            self.exit_code = exit_code if exit_code is not None else code
            logger.warning("World view error (exit code %s)", self.exit_code)
            self.set_state("error", message)
            self.end_views("world_error", message)
            self.end_tour()
        await self.publish()
        await self.emit_owner("world_tour", dict(self.tour))

    async def terminate(self):
        """Kill the job (the whole tree) and wait for Node to exit. Returns its exit code."""
        process, job = self.process, self.job
        self.process = self.job = None
        self.stopping = True
        self.settled.set()
        current = asyncio.current_task()
        for task in [task for task in self.tasks if task is not current]:
            if task.get_name().startswith(("world-boot", "world-idle", "world-exit")):
                task.cancel()
        code = None
        if process is not None:
            try:
                if job is not None:
                    job.terminate()
                elif process.returncode is None:
                    process.kill()
            except (OSError, ProcessLookupError):
                pass
            try:
                async with asyncio.timeout(STOP_TIMEOUT):
                    code = await process.wait()
            except TimeoutError:
                logger.warning("World view did not exit within %s s", STOP_TIMEOUT)
        if job is not None:
            job.close()
        return code

    async def stop(self, reason="stop"):
        """Stop the globe (Stop, idle, gaming or shutdown). Returns the status."""
        async with self.lock:
            if self.process is None and self.state not in ("starting", "ready"):
                if self.state == "error":
                    self.set_state("stopped")
                return self.status()
            code = await self.terminate()
            self.exit_code = None
            logger.info("World view stopped (%s, exit code %s)", reason, code)
            self.set_state("stopped")
            self.end_views("world_stopped", "World view stopped.")
            had_tour = self.end_tour()
        await self.publish()
        if had_tour:
            await self.emit_owner("world_tour", dict(self.tour))
        return self.status()

    async def restrict(self):
        """Gaming or resident mode: stop at once."""
        await self.stop("gaming or resident mode")

    async def close(self):
        await self.stop("shutdown")
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def idle(self, generation):
        while self.generation == generation and self.state in ("starting", "ready"):
            await asyncio.sleep(self.tick)
            if self.generation != generation:
                return
            values = self.settings()
            if not values["enabled"]:
                await self.stop("turned off")
                return
            if self.open_pages() or self.pending:
                self.touch()
            elif self.clock() - self.last_used > values["idle_minutes"] * 60:
                await self.stop("idle")
                return

    async def ensure_ready(self):
        """Start the globe if needed and wait until it is ready; raises ServiceError otherwise."""
        await self.start()
        if self.state == "starting":
            await self.settled.wait()
        if self.state != "ready":
            raise ServiceError("world_unavailable", self.message or "World view isn't running.")

    # --- the view push contract -------------------------------------------------------------
    def window(self):
        """The renderer a view goes to: the newest open World page, else the first owner
        renderer (it opens the page), else None."""
        pages = self.open_pages()
        rooms = self.owner_rooms()
        return pages[0] if pages else (rooms[0] if rooms else None)

    def require_window(self):
        """Refuse at once, before anything starts, when the globe has nowhere to show: the
        owner is locked, or no JARVIS window is open."""
        owner = self.owner()
        if owner is None or not self.app.sessions.authenticated(owner):
            raise ServiceError("world_locked", "Unlock JARVIS to show the globe.")
        if self.window() is None:
            raise ServiceError("world_no_window", NO_WINDOW)

    async def show_view(self, view, *, title=None):
        """Show ``view`` on the owner's World page; returns {ok, steps} from God's Eye View."""
        view, title = check_view(view), clean_text(title, TITLE_CHARS)
        # The window check comes first, so a request with nowhere to show never starts the globe.
        self.require_window()
        self.touch()
        await self.ensure_ready()
        sid = self.window()
        if sid is None:
            raise ServiceError("world_no_window", NO_WINDOW)
        view_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[view_id] = (sid, future)
        try:
            await self.app.sio.emit(
                "world_view", {"id": view_id, "view": view, "title": title}, room=sid
            )
            async with asyncio.timeout(self.view_timeout):
                result = await future
        except TimeoutError:
            raise ServiceError(
                "world_view_timeout", "The globe didn't show the view in time."
            ) from None
        finally:
            self.pending.pop(view_id, None)
        self.touch()
        return result

    def view_result(self, sid, view_id, ok, steps):
        entry = self.pending.get(view_id)
        if entry is None or entry[0] != sid:
            raise ServiceError("world_view_unknown", "That view isn't waiting for an answer.")
        if not entry[1].done():
            entry[1].set_result({"ok": ok, "steps": steps})

    def end_views(self, code, message):
        for _sid, future in self.pending.values():
            if not future.done():
                future.set_exception(ServiceError(code, message))

    # --- the tour bar -----------------------------------------------------------------------
    async def set_tour(self, active, *, title=None, caption=None):
        """Show (or hide) the World page's tour bar: the tour's title and what JARVIS says."""
        self.tour = {
            "active": bool(active),
            "title": clean_text(title, TITLE_CHARS) if active else None,
            "caption": clean_text(caption, CAPTION_CHARS) if active else None,
        }
        if active:
            self.touch()
        await self.emit_owner("world_tour", dict(self.tour))
        return dict(self.tour)

    def end_tour(self):
        active = self.tour["active"]
        self.tour = {"active": False, "title": None, "caption": None}
        return active

    async def tour_stop(self):
        """The owner's Stop tour: ends the tour and tells its driver."""
        if self.tour["active"] and self.on_tour_stop is not None:
            try:
                result = self.on_tour_stop()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("World tour stop handler failed")
        return await self.set_tour(False)


ViewId = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class WorldStatusRequest(EmptyRequest):
    page: StrictBool | None = None


class ViewStep(EmptyRequest):
    step: StrictStr = Field(min_length=1, max_length=64)
    ok: StrictBool
    error: StrictStr | None = Field(default=None, max_length=300)


class WorldViewResult(EmptyRequest):
    id: ViewId
    ok: StrictBool
    steps: list[ViewStep] = Field(default_factory=list, max_length=64)


class WorldTransport:
    events = ("world_status", "world_start", "world_stop", "world_view_result", "world_tour_stop")

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    @property
    def world(self):
        return self.app.world

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                return await method(sid, {} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments", "message": "Invalid World view request."}
            except Exception as exc:
                logger.warning("World view request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False, "code": "world_failed",
                    "message": "World view couldn't do that. Try again.",
                }

        return handle

    async def _world_status(self, sid, data):
        request = WorldStatusRequest.model_validate(data)
        if request.page is not None:
            self.world.page(sid, request.page)
        return {"ok": True, "world": self.world.status()}

    async def _world_start(self, sid, data):
        EmptyRequest.model_validate(data)
        self.world.page(sid, True)
        return {"ok": True, "world": await self.world.start()}

    async def _world_stop(self, _sid, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "world": await self.world.stop()}

    async def _world_view_result(self, sid, data):
        request = WorldViewResult.model_validate(data)
        steps = [step.model_dump(exclude_none=True) for step in request.steps]
        self.world.view_result(sid, request.id, request.ok, steps)
        return {"ok": True}

    async def _world_tour_stop(self, _sid, data):
        EmptyRequest.model_validate(data)
        return {"ok": True, "tour": await self.world.tour_stop()}
