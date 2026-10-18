"""Lean composition root and lifecycle for the supported desktop runtime.

All services below have one owner. Importing this module creates no runtime and
never imports server.py or an optional model implementation.
"""

import asyncio
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import socketio
from fastapi import FastAPI

from agents.scheduler_agent import SchedulerAgent
from core.event_bus import EventBus
from core.reminder_store import ReminderStore
from project_manager import ProjectManager
from services.cad import CadService, register_cad_tools
from services.cad_transport import CadTransport
from services.conversation import ConversationService
from services.image_transport import ImageTransport
from services.images import ImageService, register_image_tool
from services.lazy import LazyService
from services.local_actions import LocalActions
from services.device_printers import DevicePrinterService
from services.printing import PrintService
from transport.compatibility import CompatibilityTransport
from services.settings import SettingsService, SettingsStore
from transport.settings import SettingsTransport
from transport.lifecycle import LifecycleTransport
from transport.local_actions import LocalActionTransport
from services.resources import ResourceGovernor
from services.scheduler_tools import register_scheduler_tools
from services.sessions import SessionStore
from services.storage import Database
from services.tools import ToolDispatcher, register_project_tools
from transport.conversation import ConversationTransport
from transport.delivery import EventDelivery
from transport.reminders import ReminderTransport
from transport.sessions import DesktopSessions
from vision.vision_loop import VisionLoop


class Application:
    def __init__(
        self,
        *,
        sio,
        database,
        projects,
        settings,
        reminders,
        bus,
        resources,
        face_authenticated,
        stop_legacy=None,
        startup_summary=None,
        status_summary=None,
        instance_id=None,
        settings_path=None,
        permission_names=(),
        settings_changed=None,
        stop_resource_media=None,
        request_exit=lambda: None,
    ):
        self.sio, self.database, self.projects, self.settings = sio, database, projects, settings
        self.reminders, self.bus, self.resources = reminders, bus, resources
        self.stop_legacy, self.startup_summary = stop_legacy, startup_summary
        self.sessions = DesktopSessions(projects, settings, face_authenticated)
        self.scheduler = SchedulerAgent(event_bus=bus, reminder_store=reminders)
        self.dispatcher = ToolDispatcher(
            lambda: settings["tool_permissions"], authenticated=self.sessions.authenticated
        )
        register_project_tools(self.dispatcher)
        register_scheduler_tools(
            self.dispatcher, self.scheduler, reminders, authorize=self.authorize_owner
        )
        self.delivery = EventDelivery(sio, self.sessions, reminders, self.dispatcher, resources)
        self.cad = CadService(database, resources, partial(self.delivery.publish_job, "cad_job"))
        self.images = ImageService(
            database, resources, partial(self.delivery.publish_job, "image_job")
        )
        register_cad_tools(self.dispatcher, self.cad)
        register_image_tool(self.dispatcher, self.images)
        self.cad_transport = CadTransport(
            sio, self.cad, self.dispatcher, self.studio_context, authorize=self.authorize_owner
        )
        self.image_transport = ImageTransport(
            sio, self.images, self.dispatcher, self.studio_context
        )
        self.conversation = ConversationService(self.dispatcher, store=SessionStore(database))
        self.conversation_transport = ConversationTransport(
            sio, self.conversation, self.dispatcher, self.sessions
        )
        self.reminder_transport = ReminderTransport(sio, self.dispatcher, reminders, self.sessions)
        # Legacy integrations retain their existing contracts and load only on demand.
        self.inara = LazyService("inara")
        self.printer = LazyService("printer_agent", "PrinterAgent")
        self.desktop = LazyService("agents.desktop_agent", "DesktopAgent", event_bus=bus)
        self.vision_loop = VisionLoop(event_bus=bus, interval=5)
        self.vision = LazyService(
            "agents.vision_agent", "VisionAgent", event_bus=bus, vision_loop=self.vision_loop
        )
        self.kasa = LazyService(
            "kasa_agent", "KasaAgent", known_devices=settings.get("kasa_devices")
        )
        self.devices = LazyService(
            "agents.device_agent", "DeviceAgent", event_bus=bus, kasa_agent=self.kasa
        )
        self.local_actions = LocalActions(
            self.dispatcher, self.desktop, self.devices, self.vision, self.vision_loop
        )
        self.local_transport = LocalActionTransport(sio, self.dispatcher, self.sessions)
        self.stop_resource_media = stop_resource_media
        self.settings_service = SettingsService(
            settings,
            SettingsStore(settings_path),
            set(permission_names) | set(self.dispatcher.tools),
            settings_changed,
        )
        self.compat_service = DevicePrinterService(
            self.dispatcher,
            self.sessions,
            self.settings_service,
            self.kasa,
            self.printer,
            self.delivery.publish_job,
        )
        self.printing = PrintService(
            database, resources, self.dispatcher, self.compat_service, self.delivery.publish_job
        )
        self.compat_transport = CompatibilityTransport(sio, self.dispatcher, self.sessions)
        self.settings_service.permission_names |= frozenset(self.dispatcher.tools)
        self.settings_transport = SettingsTransport(sio, self.sessions, self.settings_service)
        self.lifecycle = LifecycleTransport(
            sio, self.sessions, resources, self.restrict_resources, self.close, request_exit
        )
        self.tasks = []
        self.started = False

        @asynccontextmanager
        async def lifespan(_app):
            await self.start()
            try:
                yield
            finally:
                await self.close()

        self.app = FastAPI(lifespan=lifespan)
        self.asgi = socketio.ASGIApp(sio, self.app)

        @self.app.get("/status")
        async def status():
            summary = (
                status_summary() if status_summary else {"status": "running", "text_ready": True}
            )
            return {**summary, "instance_id": instance_id, "resources": resources.snapshot()}

    def authorize_owner(self, context):
        from services.tools import ServiceError

        principal = context["principal"]
        if not self.sessions.is_owner(principal) or not self.sessions.authenticated(principal):
            raise ServiceError(
                "permission_denied", "Use the authenticated desktop owner for this action."
            )

    async def restrict_resources(self):
        operations = [
            self.cad_transport.close(),
            self.image_transport.close(),
            self.local_transport.stop_sid(),
            self.compat_transport.stop_sid(),
            self.compat_service.close(),
            self.printing.close(),
        ]
        if self.stop_resource_media:
            operations.append(self.stop_resource_media())
        results = await asyncio.gather(*operations, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def studio_context(self, sid):
        return self.sessions.context(sid, renderer=True).tools()

    async def disconnect(self, sid):
        await self.local_transport.stop_sid(sid)
        await self.compat_transport.stop_sid(sid)
        await self.reminder_transport.stop_sid(sid)
        principal, role = self.sessions.remove(sid)
        if role == "renderer" and not self.sessions.rooms(principal, "renderer"):
            await self.cad_transport.stop_owner(principal)
            await self.image_transport.stop_owner(principal)
        # Preserve another connected channel's approval; history stays durable.
        if not self.sessions.rooms(principal):
            self.conversation.release_owner(principal)

    async def start(self):
        if self.started:
            return
        self.started = True
        self.bus.on_all(self.delivery.bridge_legacy)
        self.tasks.append(
            asyncio.create_task(self.delivery.poll_reminders(), name="reminder-delivery")
        )
        try:
            if self.startup_summary:
                self.startup_summary()
        except BaseException:
            await self.close()
            raise

    async def close(self):
        try:
            results = await asyncio.gather(
                self.cad_transport.close(),
                self.image_transport.close(),
                self.local_transport.stop_sid(),
                self.compat_transport.stop_sid(),
                self.compat_service.close(),
                self.reminder_transport.stop_sid(),
                self.printing.close(),
                return_exceptions=True,
            )
            if self.stop_legacy:
                await self.stop_legacy()
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            self.bus.off_all(self.delivery.bridge_legacy)
            tasks = tuple(self.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.tasks.clear()
            self.started = False


def create_application(
    *,
    settings,
    project_root,
    legacy_data_dir=None,
    database=None,
    projects=None,
    sio=None,
    face_authenticated=lambda: False,
    stop_legacy=None,
    startup_summary=None,
    status_summary=None,
    instance_id=None,
    settings_path=None,
    permission_names=(),
    settings_changed=None,
    stop_resource_media=None,
    request_exit=lambda: None,
):
    """Explicit production/test injection boundary; no private profile opened until called."""
    database = database if database is not None else Database()
    projects = (
        projects
        if projects is not None
        else ProjectManager(str(Path(project_root)), state_store=database)
    )
    sio = (
        sio
        if sio is not None
        else socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "file://",
                "null",
            ],
        )
    )
    bus = EventBus()
    reminders = ReminderStore(backend_dir=legacy_data_dir, database=database)
    return Application(
        sio=sio,
        database=database,
        projects=projects,
        settings=settings,
        reminders=reminders,
        bus=bus,
        resources=ResourceGovernor(),
        face_authenticated=face_authenticated,
        stop_legacy=stop_legacy,
        startup_summary=startup_summary,
        status_summary=status_summary,
        instance_id=instance_id,
        settings_path=settings_path,
        permission_names=permission_names,
        settings_changed=settings_changed,
        stop_resource_media=stop_resource_media,
        request_exit=request_exit,
    )
