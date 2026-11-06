"""Fake JARVIS core for the talking-overlay harness (scripts/verify-overlay.cjs). Test only.

Binds 127.0.0.1 on a free port (never 8000) and speaks the overlay socket contract
(docs/VOICE_OVERLAY.md). The expected token and client id come from the environment
(FAKE_OVERLAY_TOKEN, FAKE_OVERLAY_CLIENT_ID) and must be presented with role "overlay".

stdin, one JSON command per line:
  {"op": "snapshot", "data": {...}}   remember and push a voice_overlay snapshot
  {"op": "raw", "event": str, "data": any}  push any payload as-is (validation checks)
  {"op": "level", "level": number}    push one voice_level
  {"op": "silent", "value": bool}     do not send the snapshot on connect
  {"op": "disconnect"}                close every overlay socket from the server side
  {"op": "quit"}
stdout, one JSON event per line: ready (with port), connect (accepted or refused),
overlay_stop, overlay_open, disconnect. Payload text is never printed.
"""

import asyncio
import json
import os
import socket
import sys
import threading

import socketio
import uvicorn

TOKEN = os.environ.get("FAKE_OVERLAY_TOKEN", "")
CLIENT_ID = os.environ.get("FAKE_OVERLAY_CLIENT_ID", "")
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
app = socketio.ASGIApp(sio)
clients = set()
current = {"snapshot": None, "silent": False}


def say(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


@sio.event
async def connect(sid, environ, auth):
    auth = auth if isinstance(auth, dict) else {}
    checks = {
        "token": auth.get("token") == TOKEN and len(TOKEN) == 64,
        "client_id": auth.get("client_id") == CLIENT_ID and bool(CLIENT_ID),
        "role": auth.get("role") == "overlay",
    }
    if not all(checks.values()):
        say("connect", accepted=False, failed=sorted(name for name, ok in checks.items() if not ok))
        return False
    clients.add(sid)
    say("connect", accepted=True)
    if current["snapshot"] is not None and not current["silent"]:
        await sio.emit("voice_overlay", current["snapshot"], to=sid)
    return True


@sio.event
async def disconnect(sid, *args):
    clients.discard(sid)
    say("disconnect")


@sio.on("overlay_stop")
async def overlay_stop(sid, *args):
    say("overlay_stop", payload=len(args) > 0)
    return {"ok": True}


@sio.on("overlay_open")
async def overlay_open(sid, *args):
    say("overlay_open", payload=len(args) > 0)
    return {"ok": True}


async def command(value, server):
    op = value.get("op")
    if op == "snapshot":
        current["snapshot"] = value["data"]
        for sid in tuple(clients):
            await sio.emit("voice_overlay", value["data"], to=sid)
    elif op == "raw":
        for sid in tuple(clients):
            await sio.emit(value["event"], value.get("data"), to=sid)
    elif op == "level":
        for sid in tuple(clients):
            await sio.emit("voice_level", {"level": value["level"]}, to=sid)
    elif op == "silent":
        current["silent"] = bool(value.get("value"))
    elif op == "disconnect":
        for sid in tuple(clients):
            await sio.disconnect(sid)
    elif op == "quit":
        server.should_exit = True
    say("ack", op=op)


def read_stdin(loop, server):
    # The harness writes UTF-8 whatever the console code page is.
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8").strip()
        if line:
            asyncio.run_coroutine_threadsafe(command(json.loads(line), server), loop)
    loop.call_soon_threadsafe(setattr, server, "should_exit", True)


async def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    if port == 8000:
        raise SystemExit("refusing port 8000")
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    loop = asyncio.get_running_loop()
    threading.Thread(target=read_stdin, args=(loop, server), daemon=True).start()
    say("ready", port=port)
    await server.serve(sockets=[sock])


if __name__ == "__main__":
    asyncio.run(main())
