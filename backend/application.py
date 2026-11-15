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
from services.capabilities import CapabilityCenter
from services.cad import CadService, register_cad_tools
from services.cad_transport import CadTransport
from services.cad_design import LiveDesigns
from services.cad_kernel import CadKernel
from services.creative_handoffs import CreativeHandoffs
from transport.creative_handoffs import HandoffTransport
from services.mobile import MobileService
from transport.mobile import MobileTransport
from services.conversation import ConversationService
from services.project_memory import ProjectMemory
from services.quality import QualityService
from services.log import get_logger
from services.usage import UsageService
from transport.usage import UsageTransport
from services.browser import BrowserService
from transport.browser import BrowserTransport
from services.task_queue import TaskQueue
from transport.task_queue import TaskQueueTransport
from services.connections import ConnectionsReadiness
from calls.lab import CallLab
from calls.admission import CallAdmission
from calls.testing import ControlledCalls
from transport.call_testing import CallTestingTransport
from transport.call_lab import CallLabTransport
from transport.connections import ConnectionsTransport
from transport.memory import MemoryTransport
from services.image_transport import ImageTransport
from services.images import ImageService, register_image_tool
from services.lazy import LazyService
from services.local_actions import LocalActions
from services.device_printers import DevicePrinterService
from services.printing import PrintService
from services.workspace import WorkspaceService
from services.extended_actions import ExtendedActions
from transport.connection import ConnectionTransport
from transport.workspace import WorkspaceTransport
from transport.compatibility import CompatibilityTransport
from services.settings import SettingsService, SettingsStore
from transport.settings import SettingsTransport
from transport.lifecycle import LifecycleTransport
from transport.contracts import UI_CONTRACT_VERSION
from transport.confirmations import ConfirmationTransport
from transport.local_actions import LocalActionTransport
from services.resources import ResourceGovernor
from services.audio_devices import AudioDevices
from transport.audio_devices import AudioDevicesTransport
from services.speech import SpeechService, SpeechTransport
from services.voice import VoiceService, VoiceTransport
from services.voice_overlay import VoiceOverlay
from services.wake_listening import WakeWordService
from transport.voice_overlay import VoiceOverlayTransport
from transport.wake_word import WakeWordTransport
from services.voice_preview import VoicePreviewService
from transport.voice_preview import VoicePreviewTransport
from services.scheduler_tools import register_scheduler_tools
from services.sessions import SessionStore
from services.storage import Database
from services.secrets import SecretStore, activate as activate_secrets
from transport.secrets import SecretsTransport
from telephony.agent import CallAgent
from telephony.orchestrator import CallOrchestrator, migrate_briefing_pin
from telephony.service import TelephonyService
from telephony.task_calls import register_task_call_tool
from transport.telephony import CallsTransport
from services.tools import ToolDispatcher, register_project_tools
from transport.conversation import ConversationTransport
from transport.delivery import EventDelivery
from transport.reminders import ReminderTransport
from transport.sessions import DesktopSessions

logger = get_logger(__name__)

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
        startup_summary=None,
        status_summary=None,
        instance_id=None,
        settings_path=None,
        permission_names=(),
        request_exit=lambda: None,
    ):
        self.sio, self.database, self.projects, self.settings = sio, database, projects, settings
        self.reminders, self.bus, self.resources = reminders, bus, resources
        self.startup_summary = startup_summary
        # Provider keys live in this profile's protected database; module-level
        # resolvers (capability_profiles.provider_key) read the active store.
        self.secrets = SecretStore(database)
        activate_secrets(self.secrets)
        self.sessions = DesktopSessions(projects, settings, face_authenticated)
        self.scheduler = SchedulerAgent(event_bus=bus, reminder_store=reminders)
        self.dispatcher = ToolDispatcher(
            lambda: settings["tool_permissions"], authenticated=self.sessions.authenticated
        )
        self.usage = UsageService(self)
        self.call_admission = CallAdmission(self)
        self.call_testing = ControlledCalls(self)
        self.call_testing_transport = CallTestingTransport(self)
        self.call_lab = CallLab(self)
        self.call_lab_transport = CallLabTransport(self)
        self.dispatcher.tool_scope = self.usage.tool_scope
        register_project_tools(self.dispatcher)
        register_scheduler_tools(
            self.dispatcher, self.scheduler, reminders, authorize=self.authorize_owner
        )
        # C4: the brain's task calls (always ask; placed by self.call_orchestrator below).
        register_task_call_tool(self.dispatcher, self)
        # P3 Google Calendar (docs/CALENDAR.md): the Connections card's owner-only routes and
        # the brain's calendar_events (never asks) and calendar_add_event (always asks).
        from services.calendar import CalendarService
        from services.calendar_tools import register_calendar_tools
        from services.calendar_transport import CalendarTransport

        self.calendar = CalendarService(self)
        self.calendar_transport = CalendarTransport(self)
        register_calendar_tools(self.dispatcher, self.calendar)
        # H1 Home Assistant (docs/HOME_ASSISTANT.md): the owner-only home_* routes for the
        # Connections card and Home view, and the brain's home_devices and home_control.
        from services.home_assistant import HomeAssistantService
        from services.home_assistant_tools import register_home_tools
        from services.home_assistant_transport import HomeAssistantTransport

        self.home = HomeAssistantService(self)
        self.home_transport = HomeAssistantTransport(self)
        register_home_tools(self.dispatcher, self.home)
        # S1 weather (docs/WEATHER.md): Open-Meteo, no key; the brain's weather tool (never
        # asks) and the owner-only weather_home_set route for Preferences.
        from services.weather import WeatherService
        from transport.weather import WeatherTransport

        self.weather = WeatherService(self)
        self.weather_transport = WeatherTransport(self)
        # S13a.5 Systems rail (docs/SYSTEMS_RAIL.md): PC vitals while a rail watches, and the
        # owner-only vitals_watch, weather_now, agenda_next and home_summary routes.
        from services.vitals import VitalsService
        from transport.vitals import VitalsTransport

        self.vitals = VitalsService(self)
        self.vitals_transport = VitalsTransport(self)
        # W3a MCP servers (docs/MCP.md): owner-only mcp_* routes, mcp_status, and each
        # enabled server's tools for the brain as mcp__<server>__<tool>.
        from services.mcp_registry import McpRegistry

        self.mcp = McpRegistry(self)
        self.delivery = EventDelivery(sio, self.sessions, reminders, self.dispatcher, resources)
        self.cad = CadService(database, resources, partial(self.delivery.publish_job, "cad_job"))
        self.images = ImageService(
            database, resources, partial(self.delivery.publish_job, "image_job")
        )
        self.cad.usage = self.images.usage = self.usage
        self.handoffs = CreativeHandoffs(self)
        self.handoff_transport = HandoffTransport(self)
        self.cad.reference_validator = self.images.reference_validator = self.handoffs.validate
        # Owned here (not by its transport): disconnect/close stop it directly.
        self.quality = QualityService(self)
        self.usage_transport = UsageTransport(self)
        self.browser = BrowserService(self)
        self.browser_transport = BrowserTransport(self)
        self.task_queue = TaskQueue(self)
        self.task_queue_transport = TaskQueueTransport(self)
        self.capabilities = CapabilityCenter(self)
        # The owner's live CAD design (docs/LIVE_DESIGN.md): the brain's only CAD path.
        self.cad_kernel = CadKernel(self)
        self.live_design = LiveDesigns(
            sio, self.sessions, self.cad, self.dispatcher, self.studio_context,
            authorize=self.authorize_owner, kernel=self.cad_kernel,
        )
        register_cad_tools(self.dispatcher, self.cad, self.live_design)
        register_image_tool(self.dispatcher, self.images)
        self.cad_transport = CadTransport(
            sio, self.cad, self.dispatcher, self.studio_context, authorize=self.authorize_owner
        )
        self.image_transport = ImageTransport(
            sio, self.images, self.dispatcher, self.studio_context
        )
        self.memory = ProjectMemory(self)
        self.memory_transport = MemoryTransport(self)
        self.conversation = ConversationService(
            self.dispatcher,
            store=SessionStore(database),
            memory=self.memory,
            usage=self.usage,
            settings=lambda: self.settings,
        )
        self.conversation_transport = ConversationTransport(
            sio, self.conversation, self.dispatcher, self.sessions
        )
        # S4.1 flight recorder (docs/DIAGNOSTICS.md): the last 200 turns, in memory only.
        from services.trace import TraceService
        from transport.trace import TraceTransport

        self.trace = TraceService(self)
        self.conversation.tracer = self.trace
        self.trace_transport = TraceTransport(self)
        # S4.2 diagnostics export (docs/DIAGNOSTICS.md): one redacted zip, tray or Preferences.
        from services.diagnostics import DiagnosticsService
        from transport.diagnostics import DiagnosticsTransport

        self.diagnostics = DiagnosticsService(self)
        self.diagnostics_transport = DiagnosticsTransport(self)
        # V2 Show JARVIS (docs/VISION_STUDIO.md): vision_ask, vision_capture_result and the
        # brain's look_through_camera (always asks). Photos are never stored.
        from services.vision_ask import ShowJarvis

        self.show_jarvis = ShowJarvis(self)
        self.mobile = MobileService(self)
        self.mobile_transport = MobileTransport(self)
        self.mobile.chat.tracer = self.trace  # phone chat turns are traced too
        self.speech = SpeechService(self)
        self.speech_transport = SpeechTransport(self)
        # This PC's microphone/speaker for tray voice; the audio library loads on first use.
        self.audio_devices = AudioDevices()
        self.audio_devices_transport = AudioDevicesTransport(self)
        self.voice = VoiceService(self)
        self.voice_transport = VoiceTransport(self)
        # The talking overlay during tray voice; the native host runs its window.
        self.voice_overlay = VoiceOverlay(self)
        # While JARVIS designs, the talking overlay offers "Open JARVIS" (design flag).
        self.live_design.observer = self.voice_overlay.design_changed
        self.voice_overlay_transport = VoiceOverlayTransport(self)
        # "Hey Jarvis": listens only once the native resident host activates it.
        self.wake = WakeWordService(self)
        self.wake_transport = WakeWordTransport(self)
        self.voice_preview = VoicePreviewService(self)
        self.voice_preview_transport = VoicePreviewTransport(self)
        self.reminder_transport = ReminderTransport(sio, self.dispatcher, reminders, self.sessions)
        # Legacy integrations retain their existing contracts and load only on demand.
        self.printer = LazyService("printer_agent", "PrinterAgent")
        self.desktop = LazyService("agents.desktop_agent", "DesktopAgent", event_bus=bus)
        self.kasa = LazyService(
            "kasa_agent", "KasaAgent", known_devices=settings.get("kasa_devices")
        )
        self.devices = LazyService(
            "agents.device_agent", "DeviceAgent", event_bus=bus, kasa_agent=self.kasa
        )
        self.local_actions = LocalActions(self.dispatcher, self.desktop, self.devices)
        self.local_transport = LocalActionTransport(sio, self.dispatcher, self.sessions)
        self.confirmation_transport = ConfirmationTransport(sio, self.dispatcher, self.sessions)
        self.settings_service = SettingsService(
            settings,
            SettingsStore(settings_path),
            set(permission_names) | set(self.dispatcher.tools),
        )
        self.compat_service = DevicePrinterService(
            self.dispatcher,
            self.sessions,
            self.settings_service,
            self.kasa,
            self.printer,
            self.delivery.publish_job,
        )
        self.connections = ConnectionsReadiness(self)
        self.connections_transport = ConnectionsTransport(self)
        self.printing = PrintService(
            database, resources, self.dispatcher, self.compat_service, self.delivery.publish_job
        )
        self.compat_transport = CompatibilityTransport(sio, self.dispatcher, self.sessions)
        self.workspace = WorkspaceService(self)
        self.workspace_transport = WorkspaceTransport(
            sio, self.dispatcher, self.sessions, self.workspace
        )
        self.extended_actions = ExtendedActions(self)
        self.connection = ConnectionTransport(self)
        self.sessions.face_authenticated = lambda: (
            self.connection.authenticated or face_authenticated()
        )
        # Tool names plus the shared permission keys they use (e.g. speech_capture's start_audio).
        self.settings_service.permission_names |= frozenset(self.dispatcher.tools) | {
            spec.permission for spec in self.dispatcher.tools.values() if spec.permission
        }
        from services.brain_check import BrainCheck

        self.settings_transport = SettingsTransport(
            sio,
            self.sessions,
            self.settings_service,
            self.settings_changed,
            self.connection.validate_settings,
            checker=BrainCheck(
                self.conversation.router,
                self.weather,
                usage=self.usage,
                project=lambda: self.projects.get_current_project_path().resolve(),
            ),
        )
        self.secrets_transport = SecretsTransport(self)
        # Telephony gateway (docs/CALL_ROUTING.md): its own loopback listener, idle
        # unless calls.enabled; calls_status reports readiness to the owner.
        self.telephony = TelephonyService(self)
        # C2 call agent (Gemini Live). JARVIS_TELEPHONY_STUB_AGENT=1 keeps the developer stub.
        self.call_agent = CallAgent(self)
        if self.telephony.agent is None:
            self.telephony.set_agent(self.call_agent, input_rate=16000)
        # C3: owner briefings, callbacks, call progress and the Calls view routes.
        self.call_orchestrator = CallOrchestrator(self)
        self.calls_transport = CallsTransport(self)
        # P1 people (VIP, known, blocked) for call screening; owner-only contacts_* routes.
        from telephony.contacts import Contacts, ContactsTransport

        self.contacts = Contacts(self)
        self.contacts_transport = ContactsTransport(self)
        # P2 morning briefing: the card, speech through tray voice and the optional owner call.
        from services.briefing_service import MorningBriefing

        self.briefing = MorningBriefing(self)
        # W1 World view (docs/WORLD_VIEW.md): the God's Eye View sidecar on 127.0.0.1, the
        # owner-only world_* routes, and show_view for the brain. Stops in gaming mode.
        from services.world_view import WorldTransport, WorldView

        self.world = WorldView(self)
        self.world_transport = WorldTransport(self)
        # W3b/W4 (docs/WORLD_VIEW.md "Tools and tours"): the built-in gev MCP server and the
        # brain's world_show and world_tour (both never ask by default).
        from services.world_tools import WorldTools

        self.world_tools = WorldTools(self)
        self.conversation.on_request = self.world_tools.new_request
        self.conversation.world_page_open = self.world_tools.page_open
        self.settings_service.permission_names |= {"world_show", "world_tour"}
        self.lifecycle = LifecycleTransport(
            sio,
            self.sessions,
            resources,
            self.restrict_resources,
            self.close,
            request_exit,
            after_resource=self.resource_changed,
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
            return {
                **summary,
                "instance_id": instance_id,
                "resources": resources.snapshot(),
                "ui_contract_version": UI_CONTRACT_VERSION,
            }

    def authorize_owner(self, context):
        from services.tools import ServiceError

        principal = context["principal"]
        if not self.sessions.is_owner(principal) or not self.sessions.authenticated(principal):
            raise ServiceError(
                "permission_denied", "Use the authenticated desktop owner for this action."
            )

    async def restrict_resources(self):
        # Phone calls (telephony / call_agent) are deliberately not restricted: gaming and
        # resident mode never end a call in progress (telephony/agent.py).
        self.call_testing.invalidate()
        operations = [
            self.call_admission.stop_sid(),
            self.call_lab.stop_sid(),
            self.task_queue.stop_sid(),
            self.browser_transport.stop_sid(),
            self.speech_transport.stop_sid(),
            self.voice.restrict(),
            self.cad_transport.close(),
            self.cad_kernel.stop(),
            self.image_transport.close(),
            self.local_transport.stop_sid(),
            self.compat_transport.stop_sid(),
            self.compat_service.close(),
            self.printing.close(),
            self.workspace_transport.stop_sid(),
            self.workspace.close(),
            self.connection.close(),
            self.world.restrict(),
        ]
        results = await asyncio.gather(*operations, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def studio_context(self, sid):
        return self.sessions.context(sid, renderer=True).tools()

    async def disconnect(self, sid):
        """Release everything the socket owned; each cleanup is isolated so one failure
        never leaves a dead session registered or skips the cleanups after it."""
        try:
            await _isolated("call_testing", self.call_testing.invalidate, sid)
            for name, cleanup in (
                ("call_admission", self.call_admission.stop_sid),
                ("call_lab", self.call_lab.stop_sid),
                ("task_queue", self.task_queue.stop_sid),
                ("browser", self.browser_transport.stop_sid),
                ("quality", self.quality.stop_sid),
                ("mobile", self.mobile_transport.stop_sid),
                ("speech", self.speech_transport.stop_sid),
                ("voice", self.voice_transport.stop_sid),
                ("voice_overlay", self.voice_overlay.detached),
                ("conversation", self.conversation_transport.stop_sid),
                ("local_actions", self.local_transport.stop_sid),
                ("compatibility", self.compat_transport.stop_sid),
                ("reminders", self.reminder_transport.stop_sid),
                ("vitals", self.vitals.stop_sid),
                ("workspace_transport", self.workspace_transport.stop_sid),
                ("workspace", self.workspace.disconnect),
            ):
                await _isolated(name, cleanup, sid)
        finally:
            principal, role = self.sessions.remove(sid)
        await _isolated("connection", self.connection.detached)
        if role == "renderer" and not self.sessions.rooms(principal, "renderer"):
            if self.sessions.is_owner(principal):
                await _isolated("compat_service", self.compat_service.close)
            await _isolated("cad", self.cad_transport.stop_owner, principal)
            await _isolated("images", self.image_transport.stop_owner, principal)
        # Preserve another connected channel's approval; history stays durable.
        if not self.sessions.rooms(principal):
            await _isolated("conversation_owner", self.conversation.release_owner, principal)

    async def settings_changed(self, patch):
        await self.connection.settings_changed(patch)
        if "calls" in patch:
            self.telephony.settings_changed()
            await self.telephony.reconcile()
        if "calendar" in patch:
            await self.calendar.publish()
        if "voice" in patch:
            self.voice_overlay.settings_changed()
        if "voice" in patch or "tool_permissions" in patch:
            await self.wake.reconcile(fresh=True)
        if "world" in patch:
            await self.world_tools.settings_changed()

    async def resource_changed(self, state):
        await self.connection.resource_changed(state)
        await self.wake.reconcile()

    async def start(self):
        if self.started:
            return
        self.started = True
        self.bus.on_all(self.delivery.bridge_legacy)
        self.tasks.append(
            asyncio.create_task(self.delivery.poll_reminders(), name="reminder-delivery")
        )
        self.tasks.append(
            asyncio.create_task(self.mobile.notifications.maintain(), name="notification-retention")
        )
        self.tasks.append(
            asyncio.create_task(self.memory.maintain(), name="project-memory-retention")
        )
        self.tasks.append(self.briefing.start())
        self.mcp.start()  # autostart servers in the background; mcp.close() owns the task
        # A legacy calls.briefing_pin moves into the encrypted secret store (never raises).
        migrate_briefing_pin(self)
        await self.wake.begin()  # no-op outside the native resident
        if self.telephony.calls_settings()["enabled"]:
            await self.telephony.reconcile()  # never raises; failures show in calls_status
        try:
            if self.startup_summary:
                self.startup_summary()
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self.call_testing.invalidate()
        self.memory.previews.clear()
        try:
            results = await asyncio.gather(
                self.call_admission.stop_sid(),
                self.call_lab.stop_sid(),
                self.task_queue.stop_sid(),
                self.browser_transport.stop_sid(),
                self.quality.stop_sid(),
                self.mobile_transport.stop_sid(),
                self.mobile.close(),
                self.conversation_transport.stop_sid(),
                self.speech_transport.stop_sid(),
                self.voice_transport.stop_sid(),
                self.cad_transport.close(),
                self.image_transport.close(),
                self.local_transport.stop_sid(),
                self.compat_transport.stop_sid(),
                self.compat_service.close(),
                self.reminder_transport.stop_sid(),
                self.printing.close(),
                self.workspace_transport.stop_sid(),
                self.workspace.close(),
                self.connection.close(),
                self.telephony.close(),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            await _isolated("briefing", self.briefing.close)
            await _isolated("mcp", self.mcp.close)
            await _isolated("call_orchestrator", self.call_orchestrator.close)
            await _isolated("call_agent", self.call_agent.close)
            await _isolated("wake", self.wake.close)
            await _isolated("voice_overlay", self.voice_overlay.close)
            await _isolated("audio_devices", self.audio_devices.close)
            await _isolated("vitals", self.vitals.close)
            await _isolated("world_tools", self.world_tools.close)
            await _isolated("world", self.world.close)
            await _isolated("cad_kernel", self.cad_kernel.close)
            self.bus.off_all(self.delivery.bridge_legacy)
            try:
                await self.bus.drain()
            except Exception:
                logger.exception("Background event deliveries could not drain at shutdown")
            tasks = tuple(self.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.tasks.clear()
            self.started = False


async def _isolated(name, cleanup, *args):
    """Run one cleanup step; log and continue on failure (cancellation still propagates)."""
    try:
        result = cleanup(*args)
        if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
            await result
    except Exception:
        logger.exception("Disconnect cleanup %s failed", name)


# Defense in depth behind the required session token. Origins the real renderers send:
# the Vite dev server (native-main/desktop load http://localhost:5173), and the packaged
# renderer loaded with loadFile(dist/index.html), whose WebSocket upgrade carries
# "file://" (its polling requests carry no Origin). Requests without Origin (Node/Python
# control clients) are not origin-checked; "null" (opaque origins) is not accepted.
RENDERER_ORIGINS = ("http://localhost:5173", "file://")


def create_application(
    *,
    settings,
    project_root,
    legacy_data_dir=None,
    database=None,
    projects=None,
    sio=None,
    face_authenticated=lambda: False,
    startup_summary=None,
    status_summary=None,
    instance_id=None,
    settings_path=None,
    permission_names=(),
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
            cors_allowed_origins=list(RENDERER_ORIGINS),
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
        startup_summary=startup_summary,
        status_summary=status_summary,
        instance_id=instance_id,
        settings_path=settings_path,
        permission_names=permission_names,
        request_exit=request_exit,
    )
