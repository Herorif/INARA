"""
Async event bus for inter-module communication.

Replaces the callback hell in the old server.py with clean pub/sub.
Agents publish events, the server and other modules subscribe.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class Event:
    """A typed event flowing through the bus."""
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # Which agent/module emitted this


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async pub/sub event bus."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: str, handler: EventHandler):
        """Subscribe to a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def on_all(self, handler: EventHandler):
        """Subscribe to all events (useful for logging/debugging)."""
        self._global_handlers.append(handler)

    def off(self, event_type: str, handler: EventHandler):
        """Unsubscribe from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    async def emit(self, event: Event):
        """Publish an event to all subscribers."""
        handlers = list(self._global_handlers)
        if event.type in self._handlers:
            handlers.extend(self._handlers[event.type])

        # Run all handlers concurrently
        if handlers:
            await asyncio.gather(
                *(h(event) for h in handlers),
                return_exceptions=True,
            )

    def emit_nowait(self, event: Event):
        """Fire-and-forget emit (schedules on the running loop)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            # No running loop  - silently drop
            pass


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
    REMINDER_CREATED   = "reminder.created"
    REMINDER_CANCELLED = "reminder.cancelled"
    ROUTINE_EXECUTED   = "routine.executed"

    # Desktop
    DESKTOP_SCREENSHOT  = "desktop.screenshot"
    DESKTOP_SYSTEM_INFO = "desktop.system_info"

    # System
    ERROR = "system.error"
    STATUS = "system.status"
