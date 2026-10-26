"""The telephony gateway: a separate loopback listener for Twilio, reached only
through the Cloudflare tunnel. It is never mounted on the core's port.

Exactly four paths exist; anything else (including other methods) is 404:

* ``POST /telephony/voice/inbound``  - TwiML for calls to INARA's number
* ``POST /telephony/voice/outbound`` - TwiML for calls INARA placed
* ``POST /telephony/status``         - call status callbacks
* ``WS   /telephony/media``          - bidirectional Media Streams

Every HTTP request and the WebSocket upgrade must carry a valid
``X-Twilio-Signature`` computed over the public URL (``calls.public_base_url``
plus the exact path and query) because the local URL differs from the one
Twilio signed. Failures are 403 and logged without values.
"""

import asyncio
from contextlib import contextmanager
import os
import socket
from urllib.parse import parse_qsl

from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute

from services.log import get_logger
from services.tools import ServiceError
from telephony import twiml
from telephony.media import MediaStreamHandler

logger = get_logger("telephony.gateway")

HOST = "127.0.0.1"
DEFAULT_PORT = 8790
CORE_PORT = 8000
MAX_BODY = 64 * 1024
MAX_FIELDS = 100
INBOUND, OUTBOUND, STATUS, MEDIA = (
    "/telephony/voice/inbound",
    "/telephony/voice/outbound",
    "/telephony/status",
    "/telephony/media",
)
PATHS = (INBOUND, OUTBOUND, STATUS, MEDIA)


def configured_port(environ=None):
    environ = os.environ if environ is None else environ
    raw = (environ.get("INARA_TELEPHONY_PORT") or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1024 <= port <= 65535 and port != CORE_PORT else DEFAULT_PORT


def not_found():
    return Response(status_code=404)


def forbidden():
    return Response(status_code=403)


def _path(scope):
    raw = scope.get("raw_path")
    return raw.decode("latin-1") if raw else scope["path"]


def public_url(base, scope, scheme=None):
    url = base + _path(scope)
    if scheme is not None:
        url = scheme + url[url.index("://") :]
    query = scope.get("query_string") or b""
    return url + ("?" + query.decode("latin-1") if query else "")


async def read_form(request):
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        return None
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY):
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return None
    try:
        return parse_qsl(
            body.decode("utf-8"), keep_blank_values=True, strict_parsing=False,
            max_num_fields=MAX_FIELDS,
        )
    except (UnicodeDecodeError, ValueError):
        return None


def build_app(service):
    """Starlette app bound to a TelephonyService (see telephony.service)."""

    def webhook(handler):
        async def endpoint(request):
            if request.method != "POST":
                return not_found()
            path = request.url.path
            form = await read_form(request)
            if form is None:
                logger.warning("Telephony request refused: bad_body path=%s", path)
                return forbidden()
            verdict = service.verify_http(request.scope, request.headers, form)
            if verdict != "ok":
                logger.warning("Telephony request refused: %s path=%s", verdict, path)
                return forbidden()
            params = {}
            for name, value in form:
                params.setdefault(name, value)
            try:
                return await handler(request, params)
            except ServiceError as exc:
                logger.warning("Telephony request failed: %s path=%s", exc.code, path)
                return forbidden()

        return endpoint

    async def inbound(request, params):
        return Response(service.inbound_twiml(params), media_type=twiml.CONTENT_TYPE)

    async def outbound(request, params):
        ticket = request.query_params.get("ticket")
        return Response(service.outbound_twiml(ticket, params), media_type=twiml.CONTENT_TYPE)

    async def status(request, params):
        await service.status_callback(params)
        return Response(status_code=204)

    async def media(websocket):
        verdict = service.verify_websocket(websocket.scope, websocket.headers)
        if verdict != "ok":
            logger.warning("Media Stream upgrade refused: %s", verdict)
            await websocket.close(code=1008)  # before accept -> HTTP 403
            return
        await websocket.accept()
        handler = MediaStreamHandler(
            websocket, service.authorize_stream,
            on_open=service.session_opened, on_close=service.session_closed,
        )
        await handler.run()

    async def missing(request, exc):
        return not_found()

    methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    routes = [
        Route(INBOUND, webhook(inbound), methods=methods),
        Route(OUTBOUND, webhook(outbound), methods=methods),
        Route(STATUS, webhook(status), methods=methods),
        WebSocketRoute(MEDIA, media),
    ]
    app = Starlette(routes=routes)
    app.add_exception_handler(404, missing)
    app.add_exception_handler(405, missing)
    return app


class GatewayServer:
    """Embedded uvicorn on 127.0.0.1 only, sharing the core's event loop."""

    def __init__(self, service, port=None):
        self.service = service
        self.port = configured_port() if port is None else port
        self.server = self.task = self.socket = None
        self.bound_port = None
        self.lock = asyncio.Lock()

    @property
    def listening(self):
        return bool(self.server and self.server.started and self.task and not self.task.done())

    def status(self):
        return {"listening": self.listening, "host": HOST, "port": self.bound_port or self.port}

    async def start(self):
        async with self.lock:
            if self.task is not None:
                return self.status()
            if self.port == CORE_PORT:
                raise ServiceError("telephony_port", "The gateway never shares the core's port.")
            import uvicorn

            config = uvicorn.Config(
                build_app(self.service),
                host=HOST,
                port=self.port,
                http="h11",
                ws="websockets-sansio",
                ws_max_size=64 * 1024,
                ws_per_message_deflate=False,
                proxy_headers=False,
                server_header=False,
                date_header=False,
                access_log=False,
                log_level="warning",
                lifespan="off",
                limit_concurrency=32,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=3,
            )
            config.load()
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no port hijacking
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                self.socket.bind((HOST, self.port))
                self.socket.listen(32)
                self.socket.setblocking(False)
                self.bound_port = self.socket.getsockname()[1]
            except OSError as exc:
                if self.socket:
                    self.socket.close()
                self.socket = None
                raise ServiceError("telephony_listener", "The gateway port is unavailable.") from exc

            class EmbeddedServer(uvicorn.Server):
                @contextmanager
                def capture_signals(self):
                    yield  # The core owns process signals.

            self.server = EmbeddedServer(config)
            self.task = asyncio.create_task(
                self.server.serve(sockets=[self.socket]), name="telephony-gateway"
            )
            try:
                for _ in range(100):
                    if self.listening:
                        return self.status()
                    if self.task.done():
                        break
                    await asyncio.sleep(0.05)
                raise ServiceError("telephony_listener", "The gateway could not start.")
            except BaseException:
                await self._stop()
                raise

    async def stop(self):
        async with self.lock:
            await self._stop()
            return self.status()

    async def _stop(self):
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 5)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.socket:
            self.socket.close()
        self.server = self.task = self.socket = None
        self.bound_port = None
