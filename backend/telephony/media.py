"""Twilio bidirectional Media Streams: protocol handling and the CallAudioSession.

Twilio -> INARA JSON text frames: ``connected``, ``start`` (streamSid, callSid,
mediaFormat audio/x-mulaw 8000 Hz mono, customParameters), ``media`` (base64
mu-law, track inbound), ``mark`` (playback reached a mark INARA sent), ``dtmf``
and ``stop``. INARA -> Twilio: ``media`` (base64 mu-law), ``mark`` and ``clear``.

The call agent (C2) only sees ``CallAudioSession``:

* ``async for frame in session`` (or ``await session.read()``): inbound PCM16 LE
  mono at ``session.input_rate`` (16 kHz by default), about 20 ms per frame.
* ``await session.send(pcm16, rate)``: queue agent speech (8/16/24/48 kHz).
* ``await session.mark()``: returns a future that resolves True when Twilio has
  played everything sent before it, False when cleared or the call ends.
* ``await session.clear()``: barge-in; drops audio Twilio has not played yet.
* ``session.playing``, ``session.digits`` (DTMF queue), ``session.info``.
* ``await session.hangup()``: ends the stream, which ends the call.
"""

import asyncio
import base64
import binascii
import json
import re

from starlette.websockets import WebSocketDisconnect

from services.log import get_logger
from telephony.audio import PHONE_RATE, Resampler, mulaw_decode, mulaw_encode
from telephony.numbers import mask_sid

logger = get_logger("telephony.media")

SEND_RATES = frozenset({8000, 16000, 24000, 48000})
INPUT_RATES = frozenset({8000, 16000})
CHUNK_BYTES = 160  # 20 ms of 8 kHz mu-law
MAX_MESSAGE_CHARS = 16384
MAX_PAYLOAD_BYTES = 4096
INBOUND_QUEUE_FRAMES = 100  # about two seconds
START_TIMEOUT = 10.0
IDLE_TIMEOUT = 30.0  # Twilio sends media every 20 ms while a call is up
MAX_CALL_SECONDS = 3600.0
AGENT_GRACE = 1.0
AGENT_STOP_TIMEOUT = 3.0
CALL_SID = re.compile(r"CA[0-9a-f]{32}")
STREAM_SID = re.compile(r"MZ[0-9a-f]{32}")
DIGITS = frozenset("0123456789*#ABCD")
DISCONNECTED = (WebSocketDisconnect, ConnectionError, RuntimeError)


class StreamClosed(Exception):
    """The Media Stream has ended; nothing more can be sent."""


class ProtocolError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CallAudioSession:
    def __init__(self, send_json, close, *, call_sid, stream_sid, direction, info=None,
                 input_rate=16000, queue_frames=INBOUND_QUEUE_FRAMES):
        if input_rate not in INPUT_RATES:
            raise ValueError("Unsupported input rate.")
        self._send_json, self._close = send_json, close
        self.call_sid, self.stream_sid, self.direction = call_sid, stream_sid, direction
        self.info = dict(info or {})
        self.input_rate = input_rate
        self._inbound = asyncio.Queue(maxsize=queue_frames)
        self._upsampler = Resampler(PHONE_RATE, input_rate)
        self._downsamplers = {}
        self._marks = {}
        self._mark_counter = 0
        self._send_lock = asyncio.Lock()
        self.digits = asyncio.Queue(maxsize=32)
        self.closed = asyncio.Event()
        self.end_reason = None
        self.dropped_frames = 0
        self.sent_bytes = 0

    # --- inbound -----------------------------------------------------------------
    def __aiter__(self):
        return self.frames()

    async def frames(self):
        while True:
            frame = await self._inbound.get()
            if frame is None:
                self._inbound.put_nowait(None)  # later readers also stop
                return
            yield frame

    async def read(self, timeout=None):
        """Next inbound frame, or None when the call has ended (or on timeout)."""
        try:
            frame = await asyncio.wait_for(self._inbound.get(), timeout)
        except TimeoutError:
            return None
        if frame is None:
            self._inbound.put_nowait(None)
        return frame

    def _offer(self, item):
        if self._inbound.full():
            self._inbound.get_nowait()
            if item is not None:
                self.dropped_frames += 1
        self._inbound.put_nowait(item)

    def _receive_media(self, mulaw):
        if not self.closed.is_set():
            self._offer(self._upsampler.process(mulaw_decode(mulaw)))

    def _receive_mark(self, name):
        future = self._marks.pop(name, None)
        if future is not None and not future.done():
            future.set_result(True)

    def _receive_dtmf(self, digit):
        if self.digits.full():
            self.digits.get_nowait()
        self.digits.put_nowait(digit)

    # --- outbound ----------------------------------------------------------------
    @property
    def playing(self):
        return any(not future.done() for future in self._marks.values())

    async def send(self, pcm16, rate):
        if rate not in SEND_RATES:
            raise ValueError("Unsupported sample rate for call audio.")
        if self.closed.is_set():
            raise StreamClosed()
        resampler = self._downsamplers.get(rate)
        if resampler is None:
            resampler = self._downsamplers[rate] = Resampler(rate, PHONE_RATE)
        payload = mulaw_encode(resampler.process(pcm16))
        async with self._send_lock:
            for offset in range(0, len(payload), CHUNK_BYTES):
                chunk = payload[offset : offset + CHUNK_BYTES]
                await self._emit(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                    }
                )
                self.sent_bytes += len(chunk)

    async def mark(self, name=None):
        if self.closed.is_set():
            raise StreamClosed()
        if name is None:
            self._mark_counter += 1
            name = f"inara-{self._mark_counter}"
        if not isinstance(name, str) or not 0 < len(name) <= 64 or name in self._marks:
            raise ValueError("Mark names must be unique non-empty strings.")
        future = asyncio.get_running_loop().create_future()
        self._marks[name] = future
        async with self._send_lock:
            await self._emit({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
        return future

    async def clear(self):
        """Barge-in: Twilio drops unplayed audio; pending marks resolve False."""
        if self.closed.is_set():
            return
        async with self._send_lock:
            await self._emit({"event": "clear", "streamSid": self.stream_sid})
        self._resolve_marks(False)
        for resampler in self._downsamplers.values():
            resampler.reset()

    async def hangup(self):
        if not self.closed.is_set():
            self._finish("agent_hangup")
            await self._close()

    async def _emit(self, message):
        try:
            await self._send_json(message)
        except DISCONNECTED as exc:
            self._finish("disconnected")
            raise StreamClosed() from exc

    # --- teardown ------------------------------------------------------------------
    def _resolve_marks(self, value):
        marks, self._marks = self._marks, {}
        for future in marks.values():
            if not future.done():
                future.set_result(value)

    def _finish(self, reason):
        if self.closed.is_set():
            return
        self.end_reason = reason
        self.closed.set()
        self._resolve_marks(False)
        self._offer(None)
        self._downsamplers.clear()


def _parse(text):
    if not isinstance(text, str) or len(text) > MAX_MESSAGE_CHARS:
        raise ProtocolError("message_too_large")
    try:
        message = json.loads(text)
    except ValueError:
        raise ProtocolError("malformed_message") from None
    if not isinstance(message, dict) or not isinstance(message.get("event"), str):
        raise ProtocolError("malformed_message")
    return message


def _start_fields(message):
    start = message.get("start")
    if not isinstance(start, dict):
        raise ProtocolError("malformed_start")
    stream_sid = start.get("streamSid") or message.get("streamSid")
    call_sid, account_sid = start.get("callSid"), start.get("accountSid")
    if not (isinstance(stream_sid, str) and STREAM_SID.fullmatch(stream_sid)):
        raise ProtocolError("malformed_start")
    if not (isinstance(call_sid, str) and CALL_SID.fullmatch(call_sid)):
        raise ProtocolError("malformed_start")
    if not isinstance(account_sid, str):
        raise ProtocolError("malformed_start")
    media_format = start.get("mediaFormat")
    if not (
        isinstance(media_format, dict)
        and media_format.get("encoding") == "audio/x-mulaw"
        and media_format.get("sampleRate") == PHONE_RATE
        and media_format.get("channels") == 1
    ):
        raise ProtocolError("unsupported_media_format")
    parameters = start.get("customParameters")
    if not isinstance(parameters, dict):
        parameters = {}
    return {
        "stream_sid": stream_sid,
        "call_sid": call_sid,
        "account_sid": account_sid,
        "token": parameters.get("token"),
        "direction": parameters.get("direction"),
    }


class MediaStreamHandler:
    """Runs one accepted Media Stream WebSocket from ``start`` to teardown.

    ``authorize(fields)`` validates the start message (account, stream token)
    and returns ``(info, agent, input_rate)``; it raises to refuse the stream.
    """

    def __init__(self, websocket, authorize, *, on_open=None, on_close=None,
                 start_timeout=START_TIMEOUT, idle_timeout=IDLE_TIMEOUT,
                 max_seconds=MAX_CALL_SECONDS):
        self.websocket, self.authorize = websocket, authorize
        self.on_open, self.on_close = on_open, on_close
        self.start_timeout, self.idle_timeout, self.max_seconds = (
            start_timeout, idle_timeout, max_seconds
        )
        self.session = None
        self.closing = False

    async def _send_json(self, message):
        await self.websocket.send_text(json.dumps(message, separators=(",", ":")))

    async def _close(self, code=1000):
        if self.closing:
            return
        self.closing = True
        try:
            await self.websocket.close(code)
        except DISCONNECTED:
            pass  # Expected: Twilio already closed its side.
        except Exception:
            logger.warning("Media Stream close failed", exc_info=True)

    async def _receive(self, timeout):
        return _parse(await asyncio.wait_for(self.websocket.receive_text(), timeout))

    async def run(self):
        reason = "ended"
        agent_task = None
        try:
            fields = await self._await_start()
            info, agent, input_rate = self.authorize(fields)
            self.session = CallAudioSession(
                self._send_json, self._close, call_sid=fields["call_sid"],
                stream_sid=fields["stream_sid"], direction=fields["direction"], info=info,
                input_rate=input_rate,
            )
            if self.on_open:
                self.on_open(self.session)
            logger.info(
                "Media Stream started call=%s direction=%s",
                mask_sid(fields["call_sid"]), fields["direction"],
            )
            if agent is None:
                raise ProtocolError("no_agent")
            agent_task = asyncio.create_task(agent(self.session), name="telephony-call-agent")
            reader = asyncio.create_task(self._read_loop(), name="telephony-media-reader")
            done, _ = await asyncio.wait(
                {agent_task, reader}, timeout=self.max_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reader in done:
                reason = reader.result()
            elif agent_task in done:
                reason = self.session.end_reason or "agent_finished"
                if not agent_task.cancelled() and agent_task.exception() is not None:
                    reason = "agent_failed"
                    self.session._finish(reason)
            else:
                reason = "max_duration"
            if not reader.done():
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
        except ProtocolError as exc:
            reason = exc.code
            logger.warning("Media Stream refused: %s", exc.code)
        except TimeoutError:
            reason = "start_timeout"
            logger.warning("Media Stream refused: start_timeout")
        except DISCONNECTED:
            reason = "disconnected"
        except Exception as exc:  # TokenError and authorization failures
            reason = getattr(exc, "code", None) or type(exc).__name__
            logger.warning("Media Stream refused: %s", reason)
        finally:
            if self.session is not None:
                self.session._finish(reason)
                reason = self.session.end_reason
            if agent_task is not None and not agent_task.done():
                # The agent sees end-of-stream; give it a moment to finish on its own.
                await asyncio.wait({agent_task}, timeout=AGENT_GRACE)
                if not agent_task.done():
                    agent_task.cancel()
                    await asyncio.wait({agent_task}, timeout=AGENT_STOP_TIMEOUT)
                    if not agent_task.done():
                        logger.error("Call agent did not stop within %ss", AGENT_STOP_TIMEOUT)
            if agent_task is not None and agent_task.done() and not agent_task.cancelled():
                error = agent_task.exception()
                if error is not None:
                    logger.error(
                        "Call agent failed", exc_info=(type(error), error, error.__traceback__)
                    )
            await self._close(1000 if reason in ("stopped", "agent_hangup", "agent_finished") else 1008)
            if self.on_close and self.session is not None:
                self.on_close(self.session)
        return reason

    async def _await_start(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.start_timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError()
            message = await self._receive(remaining)
            event = message["event"]
            if event == "connected":
                continue
            if event == "start":
                return _start_fields(message)
            raise ProtocolError("expected_start")

    async def _read_loop(self):
        session = self.session
        while True:
            try:
                message = await self._receive(self.idle_timeout)
            except TimeoutError:
                return "idle_timeout"
            except DISCONNECTED:
                return "disconnected"
            except ProtocolError as exc:
                logger.warning("Media Stream closed: %s", exc.code)
                return exc.code
            event = message["event"]
            sid = message.get("streamSid")
            if sid is not None and sid != session.stream_sid:
                logger.warning("Media Stream closed: stream_mismatch")
                return "stream_mismatch"
            if event == "media":
                media = message.get("media")
                if not isinstance(media, dict):
                    return "malformed_media"
                if media.get("track", "inbound") not in ("inbound", "inbound_track"):
                    continue
                payload = media.get("payload")
                if not isinstance(payload, str) or len(payload) > MAX_PAYLOAD_BYTES * 4 // 3 + 4:
                    return "malformed_media"
                try:
                    data = base64.b64decode(payload, validate=True)
                except (binascii.Error, ValueError):
                    return "malformed_media"
                session._receive_media(data)
            elif event == "mark":
                mark = message.get("mark")
                if isinstance(mark, dict) and isinstance(mark.get("name"), str):
                    session._receive_mark(mark["name"])
            elif event == "dtmf":
                dtmf = message.get("dtmf")
                digit = dtmf.get("digit") if isinstance(dtmf, dict) else None
                if isinstance(digit, str) and digit in DIGITS:
                    session._receive_dtmf(digit)
            elif event == "stop":
                return "stopped"
            elif event in ("start", "connected"):
                return "unexpected_start"
            # Unknown future event types are ignored.
