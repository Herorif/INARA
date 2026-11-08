"""A fake MCP server on stdio for tests/test_mcp.py (no network, standard library only).

Tools, listed on two pages (cursor "page-2"):
- page 1: echo (text back), fail (isError), slow (sleeps, honours notifications/cancelled),
  picture (an image plus text);
- page 2: environment (the FAKE_* variables it was given, and its argv), crash (exits 7),
  grow (adds the tool "late" and sends notifications/tools/list_changed), whoami (pid),
  huge (writes a line over 1 MB, then answers "after").

initialize answers with ``instructions``: the client's clientInfo and capabilities as JSON.

Behaviour switches (environment variables):
- FAKE_MCP_VERSION: the protocolVersion to answer (default: the client's offer);
- FAKE_MCP_MODE: "exit_at_start" exits 3 before answering; "silent" never answers
  initialize; "noisy" writes junk lines and an unrelated notification first; "stubborn"
  keeps running after stdin closes (so only a kill stops it);
- FAKE_TOKEN: written to stderr at start, so tests can check redaction.
"""

import json
import os
import sys
import threading
import time

VERSION = os.environ.get("FAKE_MCP_VERSION")
MODE = os.environ.get("FAKE_MCP_MODE", "")
lock = threading.Lock()
cancelled = set()
grown = False


def send(message):
    with lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def log(text):
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def tool(name, description, properties=None, required=()):
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties or {}, "required": list(required)},
    }


PAGE_ONE = [
    tool("echo", "Repeat the text.", {"text": {"type": "string"}}, ["text"]),
    tool("fail", "Always fails."),
    tool("slow", "Wait a while.", {"seconds": {"type": "number"}}),
    tool("picture", "Return a picture."),
]
PAGE_TWO = [
    tool("environment", "Show the environment."),
    tool("crash", "Exit at once."),
    tool("grow", "Add a tool."),
    tool("whoami", "Show the process id."),
    tool("huge", "Send an oversized message first."),
]
LATE = tool("late", "Added later.")


def text(value):
    return {"content": [{"type": "text", "text": value}], "isError": False}


def call(request_id, name, arguments):
    global grown
    if name == "echo":
        return text(str(arguments.get("text", "")))
    if name == "fail":
        return {"content": [{"type": "text", "text": "Something went wrong."}], "isError": True}
    if name == "slow":
        deadline = time.monotonic() + float(arguments.get("seconds", 5))
        while time.monotonic() < deadline:
            if request_id in cancelled:
                log(f"cancelled request {request_id}")
                return None
            time.sleep(0.02)
        return text("done")
    if name == "picture":
        return {"content": [
            {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
            {"type": "text", "text": "A small picture."},
        ]}
    if name == "environment":
        values = {key: value for key, value in os.environ.items() if key.startswith("FAKE_")}
        return text(json.dumps({"env": values, "argv": sys.argv[1:],
                                "names": sorted(key.upper() for key in os.environ)}))
    if name == "crash":
        log("crashing now")
        os._exit(7)
    if name == "grow":
        grown = True
        send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        return text("grown")
    if name == "whoami":
        return text(str(os.getpid()))
    if name == "late":
        return text("late")
    if name == "huge":
        with lock:
            sys.stdout.write("x" * (1024 * 1024 + 10) + "\n")
            sys.stdout.flush()
        return text("after")
    return None


def handle(message):
    method, request_id = message.get("method"), message.get("id")
    if method == "initialize":
        if MODE == "silent":
            return
        offered = message["params"]["protocolVersion"]
        result = {
            "protocolVersion": VERSION or offered,
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "fake", "version": "0.1"},
            "instructions": json.dumps({"clientInfo": message["params"]["clientInfo"],
                                        "capabilities": message["params"]["capabilities"]}),
        }
        send({"jsonrpc": "2.0", "id": request_id, "result": result})
    elif method == "notifications/initialized":
        # A server-to-client request the client must answer.
        send({"jsonrpc": "2.0", "id": "server-ping", "method": "ping"})
    elif method == "notifications/cancelled":
        cancelled.add(message["params"]["requestId"])
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "tools/list":
        cursor = (message.get("params") or {}).get("cursor")
        if cursor == "page-2":
            tools = PAGE_TWO + ([LATE] if grown else [])
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})
        else:
            send({"jsonrpc": "2.0", "id": request_id,
                  "result": {"tools": PAGE_ONE, "nextCursor": "page-2"}})
    elif method == "tools/call":
        params = message["params"]
        if params["name"] not in {item["name"] for item in PAGE_ONE + PAGE_TWO + [LATE]}:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32602, "message": f"Unknown tool {params['name']}"}})
            return

        def run():
            result = call(request_id, params["name"], params.get("arguments") or {})
            if result is not None:
                send({"jsonrpc": "2.0", "id": request_id, "result": result})

        threading.Thread(target=run, daemon=True).start()
    elif request_id is not None and method is not None:
        send({"jsonrpc": "2.0", "id": request_id,
              "error": {"code": -32601, "message": "Method not found"}})


def main():
    token = os.environ.get("FAKE_TOKEN")
    log("fake server starting" + (f" with token {token}" if token else ""))
    if MODE == "exit_at_start":
        log("cannot start")
        sys.exit(3)
    if MODE == "noisy":
        sys.stdout.write("this is not json\n")
        send({"jsonrpc": "2.0", "method": "notifications/message",
              "params": {"level": "info", "data": "hello"}})
        send({"jsonrpc": "2.0", "id": 999, "result": {}})  # an id nobody asked for
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle(json.loads(line))
    log("stdin closed")
    if MODE == "stubborn":
        time.sleep(120)


if __name__ == "__main__":
    main()
