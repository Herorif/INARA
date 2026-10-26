"""
Async event bus for inter-module communication.

Replaces the callback hell in the old server.py with clean pub/sub.
Agents publish events, the server and other modules subscribe.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from services.log import get_logger

logger = get_logger(__name__)

event_owner = ContextVar("event_owner", default=None)
event_guard = ContextVar("event_guard", default=None)


@dataclass
class Event:
    """A typed event flowing through the bus."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # Which agent/module emitted this
    principal: str | None = field(default_factory=event_owner.get)
    authorized: Callable | None = field(default_factory=event_guard.get, repr=False)


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async pub/sub event bus."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []
        # Strong references: the loop keeps only weak ones, so an unreferenced
        # fire-and-forget emit could be garbage-collected mid-flight.
        self._tasks: set[asyncio.Task] = set()

    def on(self, event_type: str, handler: EventHandler):
        """Subscribe to a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def on_all(self, handler: EventHandler):
        """Subscribe to all events (useful for logging/debugging)."""
        if handler not in self._global_handlers:
            self._global_handlers.append(handler)

    def off_all(self, handler: EventHandler):
        """Unsubscribe a global observer when its application stops."""
        self._global_handlers = [h for h in self._global_handlers if h != handler]

    def off(self, event_type: str, handler: EventHandler):
        """Unsubscribe from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

    async def emit(self, event: Event):
        """Publish an event to all subscribers; one failing handler never stops the rest."""
        handlers = list(self._global_handlers)
        if event.type in self._handlers:
            handlers.extend(self._handlers[event.type])

        # Run all handlers concurrently
        if handlers:
            results = await asyncio.gather(
                *(h(event) for h in handlers),
                return_exceptions=True,
            )
            for handler, result in zip(handlers, results):
                if isinstance(result, asyncio.CancelledError):
                    continue  # A handler stopped by its owner is not a delivery failure.
                if isinstance(result, BaseException):
                    logger.error(
                        "Event %s handler %s failed",
                        event.type,
                        _handler_name(handler),
                        exc_info=(type(result), result, result.__traceback__),
                    )

    def emit_nowait(self, event: Event):
        """Fire-and-forget emit (schedules on the running loop)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Event %s dropped: no running loop", event.type)
            return
        task = loop.create_task(self.emit(event), name=f"event:{event.type}")
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            error = task.exception()
            logger.error(
                "Background emit %s failed",
                task.get_name(),
                exc_info=(type(error), error, error.__traceback__),
            )

    @property
    def pending(self):
        return frozenset(self._tasks)

    async def drain(self, timeout=2.0):
        """Let in-flight background emits finish, then cancel any that outlast ``timeout``."""
        tasks = {task for task in self._tasks if task is not asyncio.current_task()}
        if not tasks:
            return
        _, late = await asyncio.wait(tasks, timeout=timeout)
        for task in late:
            task.cancel()
        if late:
            logger.warning("Cancelled %d background event deliveries at shutdown", len(late))
            await asyncio.gather(*late, return_exceptions=True)


def _handler_name(handler):
    owner = getattr(handler, "__self__", None)
    name = getattr(handler, "__qualname__", None) or type(handler).__name__
    if owner is not None and "." not in name:
        name = f"{type(owner).__name__}.{name}"
    return name


# Well-known event types used across INARA
class Events:
    # Voice pipeline
    VOICE_CONNECTED = "voice.connected"
    VOICE_DISCONNECTED = "voice.disconnected"
    VOICE_TRANSCRIPTION = "voice.transcription"
    VOICE_AUDIO_OUT = "voice.audio_out"

    # Tool system
    TOOL_CALL_REQUESTED = "tool.call_requested"
    TOOL_CALL_CONFIRMED = "tool.call_confirmed"
    TOOL_CALL_DENIED = "tool.call_denied"
    TOOL_RESULT = "tool.result"

    # CAD
    CAD_STATUS = "cad.status"
    CAD_THOUGHT = "cad.thought"
    CAD_RESULT = "cad.result"

    # Web agent
    WEB_UPDATE = "web.update"
    WEB_RESULT = "web.result"

    # Printer
    PRINTER_STATUS = "printer.status"
    PRINTER_LIST = "printer.list"

    # Smart home
    KASA_DEVICES = "kasa.devices"
    KASA_CONTROL_RESULT = "kasa.control_result"

    # Auth
    AUTH_STATUS = "auth.status"
    AUTH_FRAME = "auth.frame"

    # Project
    PROJECT_CHANGED = "project.changed"

    # Phone calls
    CALL_INCOMING = "call.incoming"
    CALL_CONNECTED = "call.connected"
    CALL_ENDED = "call.ended"
    CALL_STATUS = "call.status"

    # Reminders & routines
    REMINDER_TRIGGERED = "reminder.triggered"
    REMINDER_CREATED = "reminder.created"
    REMINDER_CANCELLED = "reminder.cancelled"
    ROUTINE_EXECUTED = "routine.executed"

    # Desktop
    DESKTOP_SCREENSHOT = "desktop.screenshot"
    DESKTOP_SYSTEM_INFO = "desktop.system_info"

    # Vision
    VISION_DESCRIPTION = "vision.description"
    VISION_ALERT = "vision.alert"
    VISION_PRESENCE = "vision.presence"

    # Devices (unified Kasa + HA)
    DEVICE_LIST = "device.list"
    DEVICE_STATE = "device.state"
    DEVICE_CONTROL = "device.control"

    # System
    ERROR = "system.error"
    STATUS = "system.status"
