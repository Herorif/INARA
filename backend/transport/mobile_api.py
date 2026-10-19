"""Dedicated HTTPS-only phone API. Never mounts desktop Socket.IO or tool routes."""

import asyncio
import json
import time
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from services.mobile_contracts import (
    SignedEnvelope,
    PairClaim,
    MobileEmpty,
    MobileChat,
    MobileHistory,
    MobileReceipt,
    MobilePreview,
)
from services.tools import ServiceError

OPERATIONS = {
    "claim": PairClaim,
    "finish": MobileEmpty,
    "status": MobileEmpty,
    "jobs": MobileEmpty,
    "preview": MobilePreview,
    "chat": MobileChat,
    "history": MobileHistory,
    "receipt": MobileReceipt,
}


class MobileAPI:
    def __init__(self, service):
        self.service = service
        self.calls = deque()
        self.app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        for operation in OPERATIONS:
            self.app.post("/v1/" + operation)(self.handler(operation))

    def handler(self, operation):
        async def handle(request: Request):
            try:
                if request.url.scheme != "https" or request.headers.get("origin"):
                    raise ServiceError("mobile_tls", "Use the paired native client over HTTPS.")
                now = time.monotonic()
                while self.calls and self.calls[0] < now - 60:
                    self.calls.popleft()
                if len(self.calls) >= 120:
                    return JSONResponse(
                        {"ok": False, "code": "mobile_rate", "message": "Wait before retrying."},
                        status_code=429,
                    )
                self.calls.append(now)
                raw = bytearray()
                if int(request.headers.get("content-length", "0")) > 65536:
                    return JSONResponse(
                        {"ok": False, "code": "mobile_size", "message": "Request is too large."},
                        status_code=413,
                    )
                try:
                    async with asyncio.timeout(5):
                        async for chunk in request.stream():
                            if len(raw) + len(chunk) > 65536:
                                return JSONResponse(
                                    {
                                        "ok": False,
                                        "code": "mobile_size",
                                        "message": "Request is too large.",
                                    },
                                    status_code=413,
                                )
                            raw.extend(chunk)
                except TimeoutError:
                    return JSONResponse(
                        {
                            "ok": False,
                            "code": "mobile_timeout",
                            "message": "Request body timed out.",
                        },
                        status_code=408,
                    )
                envelope = SignedEnvelope.model_validate_json(raw)
                args = OPERATIONS[operation].model_validate_json(envelope.payload)
                path = "/v1/" + operation
                if operation == "claim":
                    result = self.service.claim(envelope, args, path)
                else:
                    grant = {
                        "status": "status:read",
                        "jobs": "jobs:read",
                        "preview": "jobs:read",
                        "chat": "chat:ask",
                        "history": "chat:ask",
                        "receipt": "chat:ask",
                    }.get(operation)
                    value = self.service.authenticate(
                        envelope, path, grant, pending=operation == "finish"
                    )
                    if operation == "finish":
                        result = {
                            "state": "pending"
                            if str(envelope.device_id) in self.service.pending
                            else "approved",
                            **self.service.status(value),
                        }
                    elif operation in ("status", "jobs"):
                        result = getattr(self.service, operation)(value)
                    elif operation == "chat":
                        result = await self.ask_connected(request, value, args)
                    else:
                        result = getattr(self.service, operation)(value, args)
                return {"ok": True, **result}
            except ServiceError as exc:
                return JSONResponse(
                    {"ok": False, "code": exc.code, "message": str(exc)}, status_code=403
                )
            except (ValidationError, ValueError, json.JSONDecodeError):
                return JSONResponse(
                    {"ok": False, "code": "mobile_arguments", "message": "Invalid mobile request."},
                    status_code=400,
                )
            except Exception:
                return JSONResponse(
                    {
                        "ok": False,
                        "code": "mobile_failed",
                        "message": "Mobile request could not complete.",
                    },
                    status_code=500,
                )

        return handle

    async def ask_connected(self, request, value, args):
        async def watch():
            while True:
                message = await request.receive()
                if message["type"] == "http.disconnect":
                    return

        work = asyncio.create_task(self.service.ask(value, args))
        watch_task = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait([work, watch_task], return_when=asyncio.FIRST_COMPLETED)
            if watch_task in done:
                watch_task.result()
                raise ServiceError(
                    "mobile_interrupted",
                    "Connection changed. Check the saved receipt before retrying.",
                )
            return await work
        finally:
            for task in (work, watch_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, watch_task, return_exceptions=True)
