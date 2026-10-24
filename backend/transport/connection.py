"""Owner-only startup hydration and one generation of optional face work."""

from services.capability_profiles import model_id
import asyncio
import os
from services.face_worker import FaceWorker


class ConnectionTransport:
    events = ("connect", "disconnect")

    def __init__(self, app):
        self.app, self.sessions, self.sio = app, app.sessions, app.sio
        self.authenticated = False
        self.task = self.worker = self.generation = None
        self.lock = asyncio.Lock()
        self.worker_factory = lambda: FaceWorker(app)
        self.check_setup = lambda: FaceWorker.check_setup(app)
        for name in self.events:
            self.sio.on(name, handler=getattr(self, name))

    def renderers(self):
        return tuple(
            sid
            for sid in self.sessions.principals
            if self.sessions.roles.get(sid) == "renderer"
            and self.sessions.is_owner(self.sessions.principals[sid])
        )

    async def hydrate(self, sid):
        owner = self.sessions.principals.get(sid)
        if sid not in self.renderers() or not self.sessions.authenticated(owner):
            return
        await self.sio.emit("printer_list", self.app.settings.get("printers", []), room=sid)
        await self.sio.emit(
            "project_update", {"project": self.app.projects.current_project}, room=sid
        )
        await self.sio.emit("settings", self.app.settings_service.snapshot(), room=sid)
        await self.sio.emit(
            "reminder_list",
            [
                r.to_dict()
                for r in self.app.reminders.list_reminders(filter="all")
                if r.status == "pending"
            ],
            room=sid,
        )
        await self.sio.emit(
            "reminder_deliveries", self.app.reminders.open_deliveries(owner), room=sid
        )
        await self.sio.emit(
            "vision_watches", {"watches": self.app.vision_loop.list_watches()}, room=sid
        )

    async def connect(self, sid, environ, auth=None):
        if not self.sessions.accept(sid, auth, os.getenv("INARA_SESSION_TOKEN")):
            return False
        owner = self.sessions.principals[sid]
        native = self.sessions.native_desktop
        registering = (
            native
            and native.state.identity.owner is None
            and self.sessions.roles[sid] == "workspace"
        )
        if not self.sessions.is_owner(owner) and not registering:
            self.sessions.remove(sid)
            return False
        try:
            await self.sio.emit("status", {"msg": "Connected to INARA Backend"}, room=sid)
            if self.sessions.roles[sid] != "renderer":
                return
            await self.sio.emit(
                "text_ready", {"model": model_id("text")}, room=sid
            )
            await self.sio.emit("resource_state", self.app.resources.snapshot(), room=sid)
            await self.sio.emit(
                "auth_status", {"authenticated": self.sessions.authenticated(owner)}, room=sid
            )
            await self.hydrate(sid)
            await self.ensure_face()
        except BaseException:
            self.sessions.remove(sid)
            if not self.renderers():
                await self.close()
            raise

    async def ensure_face(self):
        async with self.lock:
            if (
                not self.app.settings.get("face_auth_enabled")
                or self.authenticated
                or not self.renderers()
                or self.app.resources.state == "gaming"
                or self.task
            ):
                return
            generation = object()
            self.generation = generation
            self.worker = self.worker_factory()
            self.task = asyncio.create_task(self.run_face(generation, self.worker))

    def active(self, generation):
        return (
            self.generation is generation
            and bool(self.renderers())
            and self.app.settings.get("face_auth_enabled")
        )

    async def run_face(self, generation, worker):
        async def status(value):
            if self.active(generation) and value is True:
                self.authenticated = True
                for sid in self.renderers():
                    if not self.active(generation):
                        return
                    await self.sio.emit("auth_status", {"authenticated": True}, room=sid)
                    await self.hydrate(sid)

        async def frame(value):
            if self.active(generation) and not self.authenticated:
                for sid in self.renderers():
                    if not self.active(generation):
                        return
                    await self.sio.emit("auth_frame", {"image": value}, room=sid)

        try:
            await worker.run(status, frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.active(generation) and not self.authenticated:
                for sid in self.renderers():
                    await self.sio.emit(
                        "error",
                        {
                            "msg": "Face verification is unavailable. Check local face setup.",
                            "code": "face_unavailable",
                        },
                        room=sid,
                    )
        finally:
            await worker.close()
            # Keep a completed generation until explicit reconnect/settings change
            # so repeated renderer connects cannot silently retry camera acquisition.

    async def settings_changed(self, patch):
        if "face_auth_enabled" in patch:
            await self.close()
            if patch["face_auth_enabled"]:
                await self.app.workspace_transport.stop_sid()
                await self.app.workspace.close()
            for sid in self.renderers():
                await self.sio.emit(
                    "auth_status",
                    {"authenticated": self.sessions.authenticated(self.sessions.principals[sid])},
                    room=sid,
                )
                await self.hydrate(sid)
            await self.ensure_face()

    def validate_settings(self, patch):
        if patch.get("face_auth_enabled") is True:
            self.check_setup()

    async def resource_changed(self, state):
        if state in ("resident", "gaming"):
            if self.app.settings.get("face_auth_enabled"):
                for sid in self.renderers():
                    await self.sio.emit("auth_status", {"authenticated": False}, room=sid)
        else:
            await self.ensure_face()

    async def disconnect(self, sid):
        await self.app.disconnect(sid)

    async def detached(self):
        if not self.renderers():
            await self.close()

    async def close(self):
        async with self.lock:
            task, worker = self.task, self.worker
            self.generation = self.task = self.worker = None
            self.authenticated = False
            if task and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if worker:
                await worker.close()
