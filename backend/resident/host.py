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
from services import env
from services.log import get_logger

NOTICES = {
    "call": ("JARVIS call", "A call record is ready. Open the command deck to view it."),
    # "Hey Jarvis" heard while face lock is on (at most once per LOCKED_NOTICE_SECONDS).
    "voice_locked": ("JARVIS voice", "Unlock JARVIS in the workspace to talk."),
}
LOCKED_NOTICE_SECONDS = 600
VIP_NOTICE = "call_vip"  # P1: "<name> called · VIP" with a one-line summary; a click opens it
STARTING = "JARVIS is still starting. Try again in a moment."
# The talking overlay normally quits after its fade-out; this closes one that did not.
OVERLAY_CLOSE_SECONDS = 30.0
CORE_URL = "http://127.0.0.1:8000"
DIAGNOSTICS_TITLE = "JARVIS diagnostics"
DIAGNOSTICS_FAILED = "Diagnostics couldn't be saved. Try again from the tray."

logger = get_logger(__name__)


def vip_notice(delivery):
    """(title, text) for a VIP call balloon, or None for any other delivery. Bounded to what
    a balloon shows; never logged."""
    if delivery.get("notice") != VIP_NOTICE or not isinstance(delivery.get("record_id"), str):
        return None
    title, text = delivery.get("title"), delivery.get("text")
    if not isinstance(title, str) or not isinstance(text, str):
        return None
    title, text = _balloon_line(title, 63), _balloon_line(text, 255)
    return (title, text) if title and text else None


def _balloon_line(value, limit):
    """One printable line: control characters and runs of spaces become one space."""
    printable = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value)
    return " ".join(printable.split())[:limit]


def _log_failure(label):
    def done(future):
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            logger.error(
                "Resident core call %s failed", label,
                exc_info=(type(error), error, error.__traceback__),
            )

    return done


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
        # The talking overlay's process during tray voice (J4), and when its session ended.
        self.overlay = None
        self.overlay_ended = None
        self.pending_open = not resident_only
        self.pending_quick = False
        self.hide_workspace = hide_workspace
        self.loop = self.thread = self.server = self.runtime = None
        self.process_factory = process_factory or WorkspaceProcess
        self.seen = set()
        self.notice_shown = {}  # notice kind -> monotonic time last shown
        self.balloon_record = None  # P1: the call record the last balloon shown is about
        self.tray = (tray_factory or Tray)(
            hashlib.sha256(str(self.profile.resolve()).encode()).hexdigest()[:24],
            self.root / "assets/icons",
            self.action,
            self.tick,
            suppress_notifications=suppress_notifications,
            icon_state=self.state.icon(),
        )
        self.state.hotkey = getattr(self.tray, "hotkey", False)

    def _submit(self, coroutine, label):
        """Run ``coroutine`` on the core loop from the tray thread; failures are logged."""
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        future.add_done_callback(_log_failure(label))
        return future

    def start_core(self):
        if self.thread and self.thread.is_alive():
            return
        os.environ["JARVIS_SESSION_TOKEN"] = self.token
        os.environ["JARVIS_INSTANCE_ID"] = self.instance_id
        self.state.phase, self.state.error = "starting", None
        self.show_tooltip()
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
        from services.log import configure_logging

        configure_logging()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.tray.post(lambda: self.action("quit")))
        self.thread = threading.Thread(target=self._core, daemon=True, name="JARVIS core")
        self.thread.start()

    def _core(self):
        try:
            import server

            self.runtime = server
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            server.runtime.sessions.native_desktop = self
            # Tray voice reports its state here (called on the core loop).
            server.runtime.voice.local_observer = self.voice_changed
            # The talking overlay's process follows tray voice sessions (core loop -> tray).
            server.runtime.voice_overlay.observer = self.overlay_changed
            # "Hey Jarvis" listens only here, in the native resident.
            server.runtime.wake.activate(observer=self.wake_changed, notice=self.voice_notice)
            # calls.enabled picks the tray icon: its value now, then on each settings change.
            server.runtime.telephony.observer = self.calls_changed
            server.runtime.telephony.settings_changed()
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
                        "Core cleanup could not finish. Restart JARVIS before continuing."
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
            if not self.state.quitting:
                try:
                    self.tray.post(self.show_tooltip)  # core thread -> tray: attention icon
                except Exception:
                    pass

    def _attach_identity(self):
        if self.runtime and self.state.identity.owner:

            def attach():
                self.runtime.runtime.sessions.attach_native(self.state.identity.owner)
                wake = getattr(self.runtime.runtime, "wake", None)
                if wake is not None:
                    wake.poke(fresh=True)  # an owner is registered: listening may start

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

    def show_tooltip(self):
        """Tray thread: the tooltip and the state icon (switched only when it changes)."""
        if self.tray.window:
            self.tray.tooltip(self.state.tooltip())
            self.tray.show_icon(self.state.icon())

    def publish(self):
        self.show_tooltip()
        if not self.loop or not self.loop.is_running():
            return

        async def announce():
            await self.runtime.set_resource_state(
                "native-resident", {"state": self.state.resource_state()}
            )
            roles = self.runtime.client_roles
            for sid, owner in tuple(self.runtime.client_principals.items()):
                if (
                    owner == self.state.identity.owner
                    and sid != "native-resident"
                    and roles.get(sid) != "overlay"
                ):
                    await self.runtime.sio.emit("resident_state", self.state.snapshot(), room=sid)

        self._submit(announce(), "announce resident state")

    def open_workspace(self, quick=False):
        self.pending_quick = quick
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
                            await self.runtime.sio.emit(
                                "workspace_focus", {"quick": quick}, room=sid
                            )

                self._submit(focus(), "focus workspace")
            return
        from resident.layout import workspace_executable
        try:
            executable = workspace_executable(self.root)
        except (OSError, ValueError):
            executable = None
        if executable is None or not (self.root / "dist/index.html").exists():
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
                    "quick": quick,
                    "dev": not (self.root / "desktop-pilot.json").exists() and env.getenv("DEV_SERVER") == "1",
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
                # Fixed, content-free notices: reminders by default, calls (C2) by kind. A VIP
                # call (P1) names the caller and its summary, and a click opens that record.
                vip = vip_notice(delivery)
                notice = vip or NOTICES.get(delivery.get("notice"))
                queued = key in self.seen or (
                    self.tray.notify(*notice) if notice else self.tray.notify()
                )
                if queued and key not in self.seen:
                    self.balloon_record = delivery["record_id"] if vip else None
                if queued:
                    self.seen.add(key)
                    if len(self.seen) > 512:
                        self.seen.pop()
                result.set_result(queued)
            except Exception:
                result.set_result(False)

        self.tray.post(enqueue)
        return await asyncio.wait_for(asyncio.wrap_future(result), 5)

    async def proactive_notice(self, notice):
        """S7.2 (services/proactive.py): a proactive card outside the workspace. ``notice`` is
        ``{id, overlay, title, text}``: the talking overlay runs for the card when
        ``overlay`` is set and it can start, else a balloon with ``title`` and ``text``.
        Returns ``"overlay"``, ``"balloon"`` or None (gaming, quitting or nothing shown).
        Never logged."""
        result = concurrent.futures.Future()

        def enqueue():
            if result.cancelled():
                return
            try:
                if self.state.identity.gaming or self.state.quitting:
                    result.set_result(None)
                    return
                if notice.get("overlay"):
                    voice = bool(self.state.voice and self.state.voice.get("active"))
                    self.open_overlay()
                    if self.overlay is not None:
                        if not voice:
                            # The card's overlay quits after its fade; this is the backstop.
                            self.overlay_ended = time.monotonic()
                        result.set_result("overlay")
                        return
                title, text = notice.get("title"), notice.get("text")
                title = _balloon_line(title, 63) if isinstance(title, str) else ""
                text = _balloon_line(text, 255) if isinstance(text, str) else ""
                shown = bool(title and text and self.tray.notify(title, text))
                if shown:
                    self.balloon_record = None  # a click opens the workspace
                result.set_result("balloon" if shown else None)
            except Exception:
                result.set_result(None)

        self.tray.post(enqueue)
        return await asyncio.wait_for(asyncio.wrap_future(result), 5)

    def tick(self):
        if self.state.quitting:
            return
        self.check_overlay()
        if self.server and self.server.started and self.state.phase == "starting":
            self.state.phase = "ready"
            if self.state.voice and not self.state.voice.get("active"):
                self.state.voice = None  # e.g. "still starting" from an early Talk click
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
            self.open_workspace(self.pending_quick)
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

            self._submit(disconnect(), "disconnect stale workspace")
        self.publish()

    # --- tray voice (J2) -------------------------------------------------------------------

    def voice_changed(self, status):
        """Core loop -> tray thread: the local voice session's state for the tooltip/menu."""
        self.tray.post(lambda: self.show_voice(status))

    def show_voice(self, status):
        self.state.voice = status
        self.tray.talking = bool(status.get("active"))
        self.show_tooltip()

    def talk(self, start):
        """Tray "Talk to JARVIS" / "Stop talking": the core decides and reports back."""
        application = getattr(self.runtime, "runtime", None)
        voice = getattr(application, "voice", None)
        if self.state.phase != "ready" or voice is None or not self.loop or not self.loop.is_running():
            if start:
                self.show_voice(
                    {
                        "active": False,
                        "state": "off",
                        "microphone": "off",
                        "notice": STARTING,
                    }
                )
            return None
        return self._submit(
            voice.start_local() if start else voice.stop_local(),
            "start tray voice" if start else "stop tray voice",
        )

    # --- the talking overlay (J4) ----------------------------------------------------------

    def overlay_changed(self, event, data=None):
        """Core loop -> tray thread: a tray session started or ended, or the setting is off."""
        self.tray.post(lambda: self.follow_overlay(event, data or {}))

    def follow_overlay(self, event, data):
        if event == "started":
            self.open_overlay()
        elif event == "ended":
            if data.get("now"):
                self.close_overlay()  # gaming, face lock or permission: nothing stays up
            elif self.overlay is not None:
                self.overlay_ended = time.monotonic()
        elif event == "disabled":
            self.close_overlay()

    def open_overlay(self):
        """Run the overlay for a starting tray session; reuse one still alive (fading out).

        Any failure is logged in one line and voice carries on without it."""
        self.overlay_ended = None
        if self.state.quitting:
            return
        if self.overlay is not None:
            if self.overlay.alive():
                return
            self.close_overlay()
        if not (self.root / "dist/overlay.html").exists():
            return
        from resident.layout import workspace_executable

        try:
            executable = workspace_executable(self.root)
            profile = (self.profile / "overlay").resolve()
            profile.mkdir(parents=True, exist_ok=True)
            self.overlay = self.process_factory(
                executable,
                self.root / "electron/overlay-main.cjs",
                {
                    "token": self.token,
                    "clientId": self.state.identity.owner or "",
                    "profile": str(profile),
                    "core": CORE_URL,
                    "dev": not (self.root / "desktop-pilot.json").exists()
                    and env.getenv("DEV_SERVER") == "1",
                },
                self.root,
            )
        except Exception as exc:
            self.overlay = None
            logger.warning("The voice overlay could not start (%s)", type(exc).__name__)

    def close_overlay(self):
        overlay, self.overlay, self.overlay_ended = self.overlay, None, None
        if overlay is None:
            return
        try:
            overlay.close()
        except Exception as exc:
            logger.warning("The voice overlay did not close cleanly (%s)", type(exc).__name__)

    def check_overlay(self, now=None):
        """Tray tick: forget an overlay that quit; close one still up 30 s after its session."""
        overlay = self.overlay
        if overlay is None:
            return
        if not overlay.alive():
            self.close_overlay()
            return
        now = time.monotonic() if now is None else now
        if self.overlay_ended is not None and now - self.overlay_ended >= OVERLAY_CLOSE_SECONDS:
            self.close_overlay()

    # --- calls -----------------------------------------------------------------------------

    def calls_changed(self, enabled):
        """Core loop -> tray thread: calls.enabled, for the tray's calls icon."""
        self.tray.post(lambda: self.show_calls(enabled))

    def show_calls(self, enabled):
        self.state.calls = enabled is True
        self.show_tooltip()

    # --- "Hey Jarvis" ----------------------------------------------------------------------

    def wake_changed(self, status):
        """Core loop -> tray thread: {"setting", "state", "message"} for the tooltip/menu."""
        self.tray.post(lambda: self.show_wake(status))

    def show_wake(self, status):
        self.state.wake = status
        self.tray.wake_word = bool(status.get("setting"))
        self.show_tooltip()

    def voice_notice(self, kind):
        """Core loop -> tray thread: a fixed, content-free balloon (rate-limited)."""
        self.tray.post(lambda: self.show_notice(kind))

    def show_notice(self, kind, now=None):
        notice = NOTICES.get(kind)
        if notice is None or self.state.quitting:
            return False
        now = time.monotonic() if now is None else now
        last = self.notice_shown.get(kind)
        if last is not None and now - last < LOCKED_NOTICE_SECONDS:
            return False
        try:
            shown = bool(self.tray.notify(*notice))
        except Exception:
            return False
        if shown:
            self.notice_shown[kind] = now
        return shown

    def toggle_wake(self):
        """Tray "Listen for "Hey Jarvis"": the core saves voice.wake_word and reports back."""
        application = getattr(self.runtime, "runtime", None)
        wake = getattr(application, "wake", None)
        if self.state.phase != "ready" or wake is None or not self.loop or not self.loop.is_running():
            self.show_voice({"active": False, "state": "off", "microphone": "off", "notice": STARTING})
            return None
        return self._submit(wake.toggle(), 'toggle "Hey Jarvis"')

    def export_diagnostics(self):
        """Tray "Export diagnostics" (S4.2): the core writes the zip; a balloon names the folder."""
        application = getattr(self.runtime, "runtime", None)
        diagnostics = getattr(application, "diagnostics", None)
        if self.state.phase != "ready" or diagnostics is None or not self.loop or not self.loop.is_running():
            self.show_diagnostics({"ok": False, "message": STARTING})
            return None
        future = self._submit(diagnostics.export(self.state.identity.owner), "export diagnostics")
        future.add_done_callback(lambda done: self.tray.post(lambda: self.diagnostics_done(done)))
        return future

    def diagnostics_done(self, future):
        try:
            result = future.result()
        except Exception:
            result = None
        self.show_diagnostics(result if isinstance(result, dict) else {"ok": False})

    def show_diagnostics(self, result):
        if result.get("ok") and isinstance(result.get("path"), str):
            text = f"Saved to {Path(result['path']).parent}"
        else:
            text = result.get("message") if isinstance(result.get("message"), str) else DIAGNOSTICS_FAILED
        try:
            return bool(self.tray.notify(DIAGNOSTICS_TITLE, _balloon_line(text, 255)))
        except Exception:
            return False

    def open_call(self, record_id):
        """A VIP balloon was clicked (P1): open the workspace on Calls with that record."""
        application = getattr(self.runtime, "runtime", None)
        calls = getattr(application, "call_orchestrator", None)
        if calls is not None and self.loop and self.loop.is_running():
            self._submit(calls.open_record(record_id), "open call record")
        self.open_workspace()

    def action(self, action):
        if action == "balloon":
            record, self.balloon_record = self.balloon_record, None
            if record:
                self.open_call(record)
            else:
                self.open_workspace()
        elif action in {"open", "quick"}:
            self.open_workspace(quick=action == "quick")
        elif action in {"talk", "stop_talking"}:
            self.talk(action == "talk")
        elif action == "wake_word":
            self.toggle_wake()
        elif action == "gaming":
            self.state.mode(not self.state.identity.gaming)
            self.publish()
        elif action == "diagnostics":
            self.export_diagnostics()
        elif action == "retry":
            self.start_core()
        elif action == "quit":
            self.state.quitting = True
            self.state.phase = "stopping"
            self.close_overlay()
            if self.server:
                self.server.should_exit = True
            self.tray.close()
        elif action == "failed":
            self.state.error = "A native desktop action failed. Retry from the tray."
            try:
                self.show_tooltip()
            except Exception:
                pass  # called from the window procedure's error path: never raise again

    def run(self):
        if self.tray.secondary:
            self.tray.close()
            return
        self.start_core()
        try:
            self.tray.run()
        finally:
            self.state.quitting = True
            self.close_overlay()
            if self.workspace:
                self.workspace.close()
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(5)
            self.tray.close()
