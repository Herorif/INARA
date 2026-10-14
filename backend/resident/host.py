"""Own the lean core and native tray; Electron exists only for an open workspace."""

import asyncio
import concurrent.futures
import hashlib
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from resident.state import Identity, State


class NativeHost:
    def __init__(
        self,
        root,
        profile,
        tray_factory=None,
        process_factory=None,
        resident_only=False,
        suppress_notifications=False,
        hide_workspace=False,
    ):
        from resident.win32 import Tray, WorkspaceProcess

        self.root, self.profile = Path(root), Path(profile)
        self.state = State(Identity(profile))
        self.token, self.instance_id = secrets.token_hex(32), str(uuid.uuid4())
        self.workspace = None
        self.pending_open = not resident_only
        self.hide_workspace = hide_workspace
        self.loop = self.thread = self.server = self.runtime = None
        self.process_factory = process_factory or WorkspaceProcess
        self.seen = set()
        self.tray = (tray_factory or Tray)(
            hashlib.sha256(str(self.profile.resolve()).encode()).hexdigest()[:24],
            self.root / "assets/icons/inara.ico",
            self.action,
            self.tick,
            suppress_notifications=suppress_notifications,
        )
        self.state.hotkey = getattr(self.tray, "hotkey", False)

    def start_core(self):
        if self.thread and self.thread.is_alive():
            return
        os.environ["INARA_SESSION_TOKEN"] = self.token
        os.environ["INARA_INSTANCE_ID"] = self.instance_id
        self.state.phase, self.state.error = "starting", None
        self.started_at = time.monotonic()
        self.server = None
        # Load the supported facade before starting its application loop.
        import signal

        try:
            import server
        except Exception:
            self.state.phase, self.state.error = (
                "failed",
                "Core setup or storage needs recovery. Preserve your data and retry after repairing setup.",
            )
            self.publish()
            return
        self.runtime = server
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.tray.post(lambda: self.action("quit")))
        self.thread = threading.Thread(target=self._core, daemon=True, name="INARA core")
        self.thread.start()

    def _core(self):
        try:
            import server

            self.runtime = server
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            server.runtime.sessions.native_desktop = self
            server.ACTIVE_RUNTIME = "native-resident-core"
            server.ACTIVE_ENTRYPOINT = "backend/resident_main.py"
            self.server = server.uvicorn.Server(
                server.uvicorn.Config(
                    server.app_socketio,
                    host="127.0.0.1",
                    port=8000,
                    loop="asyncio",
                    log_level="warning",
                    timeout_graceful_shutdown=3,
                )
            )
            server.uvicorn_server = self.server
            self._attach_identity()
            self.loop.run_until_complete(self.server.serve())
        except BaseException:
            if not self.state.quitting:
                self.state.phase, self.state.error = (
                    "failed",
                    "The core could not start. Check setup, storage and port 8000, then retry from the tray.",
                )
        finally:
            if self.loop:

                async def cleanup():
                    await self.runtime.close_services()
                    for sid in tuple(self.runtime.client_roles):
                        if sid != "native-resident":
                            await self.runtime.sio.disconnect(sid)
                    # Pinned Engine.IO owns its monitor; shut it down before loop disposal.
                    engine = self.runtime.sio.eio
                    if engine.service_task_handle:
                        await engine.shutdown()
                    engine.start_service_task = True

                try:
                    self.loop.run_until_complete(cleanup())
                except Exception:
                    self.state.error = (
                        "Core cleanup could not finish. Restart INARA before continuing."
                    )
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.close()
            if not self.state.quitting and self.state.phase != "failed":
                self.state.phase, self.state.error = (
                    "failed",
                    "The core stopped. Retry from the tray.",
                )

    def _attach_identity(self):
        if self.runtime and self.state.identity.owner:

            def attach():
                self.runtime.runtime.sessions.attach_native(self.state.identity.owner)

            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(attach)
            else:
                attach()

    async def control(self, principal, data):
        """Only the token-authenticated workspace control channel invokes this bridge."""
        result = concurrent.futures.Future()

        def execute():
            if result.cancelled():
                return
            try:
                action = data.get("action")
                if action == "register":
                    self.state.identity.register(principal)
                    self._attach_identity()
                elif principal != self.state.identity.owner:
                    raise ValueError("Workspace identity does not match this resident.")
                elif action == "gaming":
                    self.state.mode(data.get("gaming"))
                elif action == "close":
                    self.state.visible = False
                elif action == "quit":
                    # Let the RPC acknowledge before stopping its transport.
                    self.tray.post(lambda: self.action("quit"))
                elif action != "state":
                    raise ValueError("Unknown desktop action")
                result.set_result(self.state.snapshot())
                self.publish()
            except Exception as exc:
                result.set_exception(ValueError(str(exc)))

        self.tray.post(execute)
        return await asyncio.wait_for(asyncio.wrap_future(result), 5)

    def publish(self):
        if self.tray.window:
            self.tray.tooltip(
                "INARA · "
                + (
                    "Core unavailable"
                    if self.state.phase == "failed"
                    else "Gaming mode"
                    if self.state.identity.gaming
                    else "Workspace open"
                    if self.state.visible
                    else "Native resident"
                )
            )
        if not self.loop or not self.loop.is_running():
            return

        async def announce():
            self.runtime.resource_governor.select(self.state.resource_state())
            await self.runtime.set_resource_state(
                "native-resident", {"state": self.state.resource_state()}
            )
            for sid, owner in tuple(self.runtime.client_principals.items()):
                if owner == self.state.identity.owner and sid != "native-resident":
                    await self.runtime.sio.emit("resident_state", self.state.snapshot(), room=sid)

        asyncio.run_coroutine_threadsafe(announce(), self.loop)

    def open_workspace(self):
        if self.state.phase != "ready":
            self.pending_open = True
            return
        if self.workspace and self.workspace.alive():
            if not self.state.visible:
                self.pending_open = True
                return
            if self.loop and self.state.identity.owner:

                async def focus():
                    for sid, owner in tuple(self.runtime.client_principals.items()):
                        if (
                            owner == self.state.identity.owner
                            and self.runtime.client_roles.get(sid) == "workspace"
                        ):
                            await self.runtime.sio.emit("workspace_focus", {}, room=sid)

                asyncio.run_coroutine_threadsafe(focus(), self.loop)
            return
        executable = self.root / "node_modules/electron/dist/electron.exe"
        if not executable.exists() or not (self.root / "dist/index.html").exists():
            self.state.error = (
                "Build/install the workspace with scripts/bootstrap.ps1, then reopen it."
            )
            self.publish()
            return
        try:
            self.workspace = self.process_factory(
                executable,
                self.root / "electron/native-main.cjs",
                {
                    "token": self.token,
                    "instanceId": self.instance_id,
                    "clientId": self.state.identity.owner or "",
                    "profile": str(self.profile.resolve()),
                    "state": self.state.snapshot(),
                    "hide": self.hide_workspace,
                    "dev": os.getenv("INARA_DEV_SERVER") == "1",
                },
                self.root,
            )
            self.state.visible, self.state.error = True, None
            self.workspace_started = time.monotonic()
        except Exception:
            self.state.error = "The workspace could not start. Check its installation and retry."
        self.publish()

    async def notify(self, delivery):
        result = concurrent.futures.Future()

        def enqueue():
            if result.cancelled():
                return
            try:
                if self.state.visible or self.state.identity.gaming or self.state.quitting:
                    result.set_result(False)
                    return
                key = delivery["delivery_id"]
                queued = key in self.seen or self.tray.notify()
                if queued:
                    self.seen.add(key)
                    if len(self.seen) > 512:
                        self.seen.pop()
                result.set_result(queued)
            except Exception:
                result.set_result(False)

        self.tray.post(enqueue)
        return await asyncio.wait_for(asyncio.wrap_future(result), 5)

    def tick(self):
        if self.state.quitting:
            return
        if self.server and self.server.started and self.state.phase == "starting":
            self.state.phase = "ready"
            self.publish()
        elif self.state.phase == "starting" and time.monotonic() - self.started_at > 20:
            self.state.phase, self.state.error = (
                "failed",
                "Core startup timed out. Retry from the tray.",
            )
            if self.server:
                self.server.should_exit = True
            self.publish()
        if self.workspace and (not self.workspace.alive() or self.state.phase == "failed"):
            self.release_workspace()
        if self.pending_open and self.state.phase == "ready":
            self.pending_open = False
            self.open_workspace()
        if self.workspace and self.state.visible and time.monotonic() - self.workspace_started > 20:
            if not any(role == "workspace" for role in tuple(self.runtime.client_roles.values())):
                self.release_workspace()
                self.state.error = "Workspace startup timed out. Rebuild and reopen from the tray."
                self.publish()

    def release_workspace(self):
        """Drop a crashed/closed tree and its stale transports before reminder handoff."""
        old_rooms = [
            sid
            for sid, role in tuple(self.runtime.client_roles.items())
            if role in ("renderer", "workspace")
        ]
        self.workspace.close()
        self.workspace = None
        self.state.visible = False
        if self.loop and self.loop.is_running():

            async def disconnect():
                for sid in old_rooms:
                    await self.runtime.sio.disconnect(sid)

            asyncio.run_coroutine_threadsafe(disconnect(), self.loop)
        self.publish()

    def action(self, action):
        if action == "open":
            self.open_workspace()
        elif action == "gaming":
            self.state.mode(not self.state.identity.gaming)
            self.publish()
        elif action == "retry":
            self.start_core()
        elif action == "quit":
            self.state.quitting = True
            self.state.phase = "stopping"
            if self.server:
                self.server.should_exit = True
            self.tray.close()
        elif action == "failed":
            self.state.error = "A native desktop action failed. Retry from the tray."

    def run(self):
        if self.tray.secondary:
            self.tray.close()
            return
        self.start_core()
        try:
            self.tray.run()
        finally:
            self.state.quitting = True
            if self.workspace:
                self.workspace.close()
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(5)
            self.tray.close()
