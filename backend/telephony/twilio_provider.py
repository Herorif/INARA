"""
Twilio telephony provider for INARA.

Uses Twilio Media Streams for real-time bidirectional audio:
  - Outbound: Twilio REST API creates a call, TwiML points to our WebSocket
  - Inbound:  Twilio webhook POST → TwiML → connects to our WebSocket
  - Audio:    WebSocket exchanges base64 mulaw 8kHz in both directions

The WebSocket endpoint lives in twilio_routes.py and is registered
on the FastAPI app when this provider is active.

Config keys (from settings.json telephony.twilio):
  account_sid     — Twilio Account SID
  auth_token      — Twilio Auth Token
  phone_number    — Your Twilio phone number (E.164, e.g. +15551234567)
  webhook_base_url — Public URL Twilio can reach (e.g. https://yourserver.ngrok.io)
                     Required for inbound calls and outbound TwiML callback.
"""

import asyncio
import base64
import time
import uuid
from typing import Optional, AsyncIterator

from telephony.base import BaseTelephonyProvider, CallInfo, CallState


class TwilioProvider(BaseTelephonyProvider):
    """
    Twilio Media Streams telephony provider.

    Audio queues: each call_id maps to an asyncio.Queue of raw mulaw bytes.
    The WebSocket handler (twilio_routes.py) pushes inbound audio onto the queue
    and pulls outbound audio from a separate send queue.
    """

    def __init__(self):
        self._config: dict = {}
        self._client = None  # twilio.rest.Client

        # call_id → CallInfo
        self._calls: dict[str, CallInfo] = {}
        # call_id → Queue of inbound mulaw bytes (phone → INARA)
        self._recv_queues: dict[str, asyncio.Queue] = {}
        # call_id → Queue of outbound mulaw bytes (INARA → phone)
        self._send_queues: dict[str, asyncio.Queue] = {}

        self.on_incoming_call = None
        self.on_call_state_changed = None

    @property
    def name(self) -> str:
        return "twilio"

    async def initialize(self, config: dict) -> None:
        twilio_cfg = config.get("twilio", {})
        self._config = twilio_cfg

        account_sid = twilio_cfg.get("account_sid", "")
        auth_token = twilio_cfg.get("auth_token", "")

        if not account_sid or not auth_token:
            print("[INARA] [TWILIO] WARNING: account_sid/auth_token not set. Calls will fail.")
            return

        try:
            from twilio.rest import Client
            self._client = Client(account_sid, auth_token)
            print(f"[INARA] [TWILIO] Client initialized for {account_sid[:8]}...")
        except ImportError:
            raise RuntimeError("twilio package not installed. Run: pip install twilio")

    async def make_call(self, number: str, purpose: Optional[str] = None) -> CallInfo:
        if not self._client:
            raise RuntimeError("Twilio client not initialized. Check credentials in settings.")

        call_id = str(uuid.uuid4())
        webhook_base = self._config.get("webhook_base_url", "").rstrip("/")
        from_number = self._config.get("phone_number", "")

        if not webhook_base:
            raise RuntimeError("webhook_base_url not set in telephony.twilio config.")
        if not from_number:
            raise RuntimeError("phone_number not set in telephony.twilio config.")

        # TwiML that connects the call to our Media Stream WebSocket
        twiml_url = f"{webhook_base}/telephony/outbound-twiml/{call_id}"

        call_info = CallInfo(
            call_id=call_id,
            direction="outbound",
            remote_number=number,
            state=CallState.RINGING,
            started_at=time.time(),
        )
        self._calls[call_id] = call_info
        self._recv_queues[call_id] = asyncio.Queue()
        self._send_queues[call_id] = asyncio.Queue()

        # Place the call via Twilio REST API
        try:
            twilio_call = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.calls.create(
                    to=number,
                    from_=from_number,
                    url=twiml_url,
                )
            )
            # Store Twilio's SID for reference
            call_info.call_id = call_id  # We use our own ID, not Twilio's
            print(f"[INARA] [TWILIO] Outbound call placed: {twilio_call.sid} → {number}")
        except Exception as e:
            self._calls.pop(call_id, None)
            self._recv_queues.pop(call_id, None)
            self._send_queues.pop(call_id, None)
            raise RuntimeError(f"Twilio call failed: {e}")

        return call_info

    async def answer_call(self, call_id: str) -> None:
        # Twilio inbound calls are answered by the TwiML webhook response.
        # By the time answer_call is called, the call is already connected
        # (the webhook returned TwiML with <Connect><Stream>).
        # This is a no-op — state is managed by the WebSocket lifecycle.
        pass

    async def hang_up(self, call_id: str) -> None:
        call_info = self._calls.get(call_id)
        if not call_info:
            return

        # Signal the WebSocket handler to close
        send_q = self._send_queues.get(call_id)
        if send_q:
            try:
                send_q.put_nowait(None)  # None = sentinel to close
            except asyncio.QueueFull:
                pass

        call_info.state = CallState.ENDED
        call_info.ended_at = time.time()
        if self.on_call_state_changed:
            self.on_call_state_changed(call_info)

        self._cleanup_call(call_id)

    async def hold(self, call_id: str) -> None:
        # Twilio hold via Modify Call API (update to hold TwiML)
        # Simplified: just pause audio
        call_info = self._calls.get(call_id)
        if call_info:
            call_info.state = CallState.ON_HOLD
            if self.on_call_state_changed:
                self.on_call_state_changed(call_info)

    async def unhold(self, call_id: str) -> None:
        call_info = self._calls.get(call_id)
        if call_info and call_info.state == CallState.ON_HOLD:
            call_info.state = CallState.CONNECTED
            if self.on_call_state_changed:
                self.on_call_state_changed(call_info)

    async def send_audio(self, call_id: str, audio_data: bytes) -> None:
        """Queue mulaw audio to be sent to the caller via WebSocket."""
        send_q = self._send_queues.get(call_id)
        if send_q:
            try:
                send_q.put_nowait(audio_data)
            except asyncio.QueueFull:
                pass  # Drop rather than block

    async def receive_audio(self, call_id: str) -> AsyncIterator[bytes]:
        """Yield mulaw audio chunks received from the caller."""
        recv_q = self._recv_queues.get(call_id)
        if not recv_q:
            return

        while True:
            chunk = await recv_q.get()
            if chunk is None:  # Sentinel: call ended
                break
            yield chunk

    def get_call_state(self, call_id: str) -> Optional[CallInfo]:
        return self._calls.get(call_id)

    async def shutdown(self) -> None:
        for call_id in list(self._calls.keys()):
            await self.hang_up(call_id)
        self._client = None

    # -----------------------------------------------------------------------
    # Internal: called by twilio_routes.py WebSocket handler
    # -----------------------------------------------------------------------

    def register_inbound_call(self, call_id: str, from_number: str) -> CallInfo:
        """Called by the webhook when an inbound call arrives."""
        call_info = CallInfo(
            call_id=call_id,
            direction="inbound",
            remote_number=from_number,
            state=CallState.RINGING,
            started_at=time.time(),
        )
        self._calls[call_id] = call_info
        self._recv_queues[call_id] = asyncio.Queue()
        self._send_queues[call_id] = asyncio.Queue()

        if self.on_incoming_call:
            self.on_incoming_call(call_info)

        return call_info

    def on_stream_connected(self, call_id: str):
        """Called when the Media Stream WebSocket connects."""
        call_info = self._calls.get(call_id)
        if call_info:
            call_info.state = CallState.CONNECTED
            if self.on_call_state_changed:
                self.on_call_state_changed(call_info)

    def on_stream_audio(self, call_id: str, mulaw_bytes: bytes):
        """Push inbound audio from the WebSocket into the receive queue."""
        recv_q = self._recv_queues.get(call_id)
        if recv_q:
            try:
                recv_q.put_nowait(mulaw_bytes)
            except asyncio.QueueFull:
                pass

    def on_stream_disconnected(self, call_id: str):
        """Called when the Media Stream WebSocket closes."""
        call_info = self._calls.get(call_id)
        if call_info and call_info.state != CallState.ENDED:
            call_info.state = CallState.ENDED
            call_info.ended_at = time.time()
            if self.on_call_state_changed:
                self.on_call_state_changed(call_info)

        # Signal receive_audio iterator to stop
        recv_q = self._recv_queues.get(call_id)
        if recv_q:
            try:
                recv_q.put_nowait(None)
            except asyncio.QueueFull:
                pass

        self._cleanup_call(call_id)

    def get_send_queue(self, call_id: str) -> Optional[asyncio.Queue]:
        """Returns the outbound audio queue for a call (used by WebSocket handler)."""
        return self._send_queues.get(call_id)

    def _cleanup_call(self, call_id: str):
        self._calls.pop(call_id, None)
        self._recv_queues.pop(call_id, None)
        self._send_queues.pop(call_id, None)
