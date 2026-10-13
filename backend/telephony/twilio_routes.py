"""
Twilio webhook and Media Stream WebSocket routes.

Registered on the FastAPI app by server.py when the Twilio provider is active.

Routes:
  POST /telephony/incoming         — Twilio inbound call webhook (returns TwiML)
  POST /telephony/outbound-twiml/{call_id} — TwiML for outbound calls
  WS   /telephony/media-stream     — Twilio Media Stream bidirectional audio

Twilio Media Stream protocol (WebSocket):
  Inbound messages (Twilio → us):
    {"event": "connected"}
    {"event": "start",  "start":  {"callSid": ..., "streamSid": ...}}
    {"event": "media",  "media":  {"payload": "<base64 mulaw>", "track": "inbound"}}
    {"event": "stop"}

  Outbound messages (us → Twilio):
    {"event": "media",  "media":  {"payload": "<base64 mulaw>", "streamSid": ...}}
    {"event": "clear",  "streamSid": ...}   ← clears Twilio's audio buffer (barge-in)
"""

import asyncio
import base64
import json
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

if TYPE_CHECKING:
    from telephony.twilio_provider import TwilioProvider


def create_twilio_router(provider: "TwilioProvider", webhook_base_url: str) -> APIRouter:
    """
    Factory that creates the Twilio routes with the provider injected.
    Called from server.py during startup.
    """
    router = APIRouter(prefix="/telephony", tags=["telephony"])

    # -----------------------------------------------------------------------
    # Inbound call webhook — Twilio POSTs here when someone calls our number
    # -----------------------------------------------------------------------

    @router.post("/incoming")
    async def incoming_call(request: Request):
        """
        Twilio calls this when an inbound call arrives.
        We generate a unique call_id, register it with the provider,
        and return TwiML that connects the call to our Media Stream WebSocket.
        """
        form = await request.form()
        from_number = form.get("From", "unknown")
        call_sid = form.get("CallSid", str(uuid.uuid4()))

        # Use Twilio's CallSid as our call_id for inbound calls
        call_id = call_sid
        provider.register_inbound_call(call_id, from_number)

        stream_url = f"{webhook_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/telephony/media-stream"

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_id" value="{call_id}"/>
        </Stream>
    </Connect>
</Response>"""

        return Response(content=twiml, media_type="application/xml")

    # -----------------------------------------------------------------------
    # Outbound TwiML — Twilio fetches this when our outbound call connects
    # -----------------------------------------------------------------------

    @router.post("/outbound-twiml/{call_id}")
    async def outbound_twiml(call_id: str):
        """
        Returns TwiML for an outbound call, connecting it to our Media Stream.
        Twilio fetches this URL when the called party picks up.
        """
        stream_url = f"{webhook_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/telephony/media-stream"

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_id" value="{call_id}"/>
        </Stream>
    </Connect>
</Response>"""

        return Response(content=twiml, media_type="application/xml")

    # -----------------------------------------------------------------------
    # Media Stream WebSocket — bidirectional audio with Twilio
    # -----------------------------------------------------------------------

    @router.websocket("/media-stream")
    async def media_stream(websocket: WebSocket):
        """
        Twilio Media Stream WebSocket handler.

        Receives inbound audio from Twilio, pushes to provider's recv queue.
        Pulls outbound audio from provider's send queue, sends to Twilio.
        """
        await websocket.accept()

        call_id: str | None = None
        stream_sid: str | None = None

        async def _send_loop():
            """Pull audio from the provider and send to Twilio."""
            nonlocal stream_sid
            while True:
                send_q = provider.get_send_queue(call_id) if call_id else None
                if not send_q:
                    await asyncio.sleep(0.05)
                    continue

                try:
                    chunk = await asyncio.wait_for(send_q.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if chunk is None:
                    # Sentinel: hang up
                    await websocket.close()
                    return

                if stream_sid:
                    payload = base64.b64encode(chunk).decode("utf-8")
                    await websocket.send_text(json.dumps({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }))

        send_task = asyncio.create_task(_send_loop())

        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "connected":
                    print("[INARA] [TWILIO] Media Stream connected.")

                elif event == "start":
                    stream_sid = msg.get("streamSid") or msg.get("start", {}).get("streamSid")
                    start_data = msg.get("start", {})
                    # Retrieve call_id from custom parameters
                    params = start_data.get("customParameters", {})
                    call_id = params.get("call_id") or start_data.get("callSid")
                    print(f"[INARA] [TWILIO] Stream started: call_id={call_id}, stream={stream_sid}")
                    if call_id:
                        provider.on_stream_connected(call_id)

                elif event == "media":
                    media = msg.get("media", {})
                    track = media.get("track", "inbound")
                    if track == "inbound" and call_id:
                        payload = media.get("payload", "")
                        if payload:
                            mulaw_bytes = base64.b64decode(payload)
                            provider.on_stream_audio(call_id, mulaw_bytes)

                elif event == "stop":
                    print(f"[INARA] [TWILIO] Stream stopped: call_id={call_id}")
                    if call_id:
                        provider.on_stream_disconnected(call_id)
                    break

        except WebSocketDisconnect:
            print(f"[INARA] [TWILIO] WebSocket disconnected: call_id={call_id}")
            if call_id:
                provider.on_stream_disconnected(call_id)
        except Exception as e:
            print(f"[INARA] [TWILIO] WebSocket error: {e}")
            if call_id:
                provider.on_stream_disconnected(call_id)
        finally:
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass

    return router
