"""
Phone Agent — manages phone calls via the configured telephony provider.

Follows the BaseAgent pattern (same as KasaSmartHomeAgent).
Handles 3 LLM-callable tools: make_phone_call, end_phone_call, get_call_status.

Inbound calls:
  Provider fires on_incoming_call → agent emits CALL_INCOMING event →
  frontend shows notification → user accepts/rejects via answer_call/reject_call
  socket events → agent calls provider.answer_call() or provider.hang_up().

Outbound calls:
  LLM calls make_phone_call → agent calls provider.make_call() →
  CallSession spins up to bridge audio → CALL_CONNECTED emitted.
"""

import asyncio
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING

from agents.base import AgentResult, BaseAgent
from core.event_bus import EventBus, Event, Events
from llm.tools import Tool, ToolParameter, ToolParameterType
from telephony.base import BaseTelephonyProvider, CallInfo, CallState
from telephony.call_session import CallSession

if TYPE_CHECKING:
    from voice.pipeline import VoicePipeline


class PhoneAgent(BaseAgent):
    """
    INARA agent for phone call management.

    One PhoneAgent instance lives for the server's lifetime.
    Each active call gets its own CallSession running as an asyncio task.
    """

    def __init__(
        self,
        event_bus: EventBus,
        provider: BaseTelephonyProvider,
        tools: Optional[list] = None,
    ):
        self._bus = event_bus
        self._provider = provider
        self._tools_for_gemini = tools or []

        # call_id → CallSession
        self._sessions: dict[str, CallSession] = {}
        # call_id → asyncio.Task
        self._session_tasks: dict[str, asyncio.Task] = {}

        # Reference to local voice pipeline for audio ducking
        self._local_pipeline: Optional["VoicePipeline"] = None

        # Wire inbound call callback
        self._provider.on_incoming_call = self._on_incoming_call
        self._provider.on_call_state_changed = self._on_call_state_changed

    def set_local_pipeline(self, pipeline: "VoicePipeline"):
        """Set reference to voice pipeline for audio ducking."""
        self._local_pipeline = pipeline

    # -----------------------------------------------------------------------
    # BaseAgent interface
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "phone"

    @property
    def description(self) -> str:
        return "Places and manages phone calls via the configured telephony provider"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="make_phone_call",
                description="Places an outbound phone call. INARA will converse on the call.",
                parameters=[
                    ToolParameter("number", ToolParameterType.STRING, "Phone number in E.164 format (e.g. +15551234567)."),
                    ToolParameter("purpose", ToolParameterType.STRING, "Optional context for the call.", required=False),
                ],
                non_blocking=True,
            ),
            Tool(
                name="end_phone_call",
                description="Hangs up an active phone call.",
                parameters=[
                    ToolParameter("call_id", ToolParameterType.STRING, "The ID of the call to end."),
                ],
            ),
            Tool(
                name="get_call_status",
                description="Gets the current status of a phone call.",
                parameters=[
                    ToolParameter("call_id", ToolParameterType.STRING, "The ID of the call to check."),
                ],
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name == "make_phone_call":
            return await self._make_call(args)
        elif tool_name == "end_phone_call":
            return await self._end_call(args)
        elif tool_name == "get_call_status":
            return self._get_status(args)
        return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

    async def initialize(self):
        """Initialize the telephony provider."""
        from core.config import Config
        cfg = Config()
        telephony_config = cfg.get("telephony", {})
        await self._provider.initialize(telephony_config)
        print(f"[INARA] [PHONE] Provider '{self._provider.name}' initialized.")

    async def shutdown(self):
        """Stop all active calls and shut down the provider."""
        for call_id in list(self._sessions.keys()):
            await self._teardown_session(call_id)
        await self._provider.shutdown()

    # -----------------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------------

    async def _make_call(self, args: dict) -> AgentResult:
        number = args.get("number", "")
        purpose = args.get("purpose", "")

        if not number:
            return AgentResult(success=False, message="No phone number provided.")

        try:
            call_info = await self._provider.make_call(number, purpose)
        except Exception as e:
            return AgentResult(success=False, message=f"Failed to place call: {e}")

        # Spin up a CallSession for this call
        self._start_session(call_info)

        self._bus.emit_nowait(Event(
            type=Events.CALL_STATUS,
            data={**call_info.to_dict(), "message": f"Calling {number}..."},
            source=self.name,
        ))

        msg = f"Calling {number}"
        if purpose:
            msg += f" ({purpose})"
        msg += f". Call ID: {call_info.call_id}"
        return AgentResult(success=True, data=call_info.to_dict(), message=msg, is_async=True)

    async def _end_call(self, args: dict) -> AgentResult:
        call_id = args.get("call_id", "")

        call_info = self._provider.get_call_state(call_id)
        if not call_info:
            return AgentResult(success=False, message=f"Call {call_id} not found.")

        try:
            await self._provider.hang_up(call_id)
        except Exception as e:
            return AgentResult(success=False, message=f"Failed to hang up: {e}")

        await self._teardown_session(call_id)
        return AgentResult(success=True, message=f"Call {call_id} ended.")

    def _get_status(self, args: dict) -> AgentResult:
        call_id = args.get("call_id", "")
        call_info = self._provider.get_call_state(call_id)

        if not call_info:
            return AgentResult(success=False, message=f"Call {call_id} not found.")

        return AgentResult(
            success=True,
            data=call_info.to_dict(),
            message=f"Call {call_id}: {call_info.state.value}, remote: {call_info.remote_number}",
        )

    # -----------------------------------------------------------------------
    # Inbound call handling (from provider callbacks)
    # -----------------------------------------------------------------------

    def _on_incoming_call(self, call_info: CallInfo):
        """Called by the provider when an inbound call arrives."""
        print(f"[INARA] [PHONE] Incoming call from {call_info.remote_number} ({call_info.call_id})")
        self._bus.emit_nowait(Event(
            type=Events.CALL_INCOMING,
            data=call_info.to_dict(),
            source=self.name,
        ))

    def _on_call_state_changed(self, call_info: CallInfo):
        """Called by the provider when a call's state changes."""
        print(f"[INARA] [PHONE] Call {call_info.call_id} state: {call_info.state.value}")

        if call_info.state == CallState.CONNECTED:
            # If session doesn't exist yet (inbound call answered), create it now
            if call_info.call_id not in self._sessions:
                self._start_session(call_info)
            self._bus.emit_nowait(Event(
                type=Events.CALL_CONNECTED,
                data=call_info.to_dict(),
                source=self.name,
            ))

        elif call_info.state == CallState.ENDED:
            self._bus.emit_nowait(Event(
                type=Events.CALL_ENDED,
                data=call_info.to_dict(),
                source=self.name,
            ))
            # Teardown session async
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._teardown_session(call_info.call_id))
            except RuntimeError:
                pass

        else:
            self._bus.emit_nowait(Event(
                type=Events.CALL_STATUS,
                data=call_info.to_dict(),
                source=self.name,
            ))

    async def answer_call(self, call_id: str):
        """Answer an incoming call (called from server socket event)."""
        call_info = self._provider.get_call_state(call_id)
        if not call_info:
            print(f"[INARA] [PHONE] answer_call: call {call_id} not found.")
            return
        await self._provider.answer_call(call_id)

    async def reject_call(self, call_id: str):
        """Reject an incoming call (called from server socket event)."""
        await self._provider.hang_up(call_id)

    # -----------------------------------------------------------------------
    # Session lifecycle
    # -----------------------------------------------------------------------

    def _start_session(self, call_info: CallInfo):
        """Create and start a CallSession for a call."""
        session = CallSession(
            call_info=call_info,
            provider=self._provider,
            event_bus=self._bus,
            tools=self._tools_for_gemini,
            local_pipeline=self._local_pipeline,
        )
        self._sessions[call_info.call_id] = session

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(session.run())
            self._session_tasks[call_info.call_id] = task
        except RuntimeError:
            print(f"[INARA] [PHONE] No running event loop to start session for {call_info.call_id}.")

    async def _teardown_session(self, call_id: str):
        """Stop and clean up a CallSession."""
        session = self._sessions.pop(call_id, None)
        if session:
            session.stop()

        task = self._session_tasks.pop(call_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
