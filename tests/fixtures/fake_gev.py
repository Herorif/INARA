"""A fake God's Eye View for tests/test_world_view.py (stdlib only, loopback only).

The tests copy this file to <root>/node_modules/vite/bin/vite.js and point world.node at the
test interpreter, so WorldView runs it exactly as it runs vite: ``<node> vite.js preview
--host 127.0.0.1 --port N --strictPort`` with cwd = root. It records its argv and
environment in the root, then serves ``/`` (HTML) and ``/api/mapillary/status`` (JSON).
``fake-mode.json`` in the root changes its behaviour: ``delay`` (seconds before it listens),
``never`` (never listens), ``exit`` (exit code, after ``exit_after`` seconds), ``stderr``
(text written to stderr first) and ``broken_api`` (the /api route answers 500).
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = Path.cwd()
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
host = args[args.index("--host") + 1]
mode_file = root / "fake-mode.json"
mode = json.loads(mode_file.read_text(encoding="utf-8")) if mode_file.exists() else {}
(root / "fake-argv.json").write_text(json.dumps(sys.argv), encoding="utf-8")
(root / "fake-env.json").write_text(json.dumps(dict(os.environ)), encoding="utf-8")
(root / "fake-pid.txt").write_text(str(os.getpid()), encoding="utf-8")
if mode.get("stderr"):
    sys.stderr.write(mode["stderr"])
    sys.stderr.flush()
if "exit" in mode:
    time.sleep(mode.get("exit_after", 0))
    sys.exit(mode["exit"])
if mode.get("never"):
    while True:
        time.sleep(1)
time.sleep(mode.get("delay", 0))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body, kind, code = b"<!doctype html><title>God's Eye View</title>", "text/html", 200
        elif self.path == "/api/mapillary/status":
            code = 500 if mode.get("broken_api") else 200
            body, kind = b'{"configured":false}', "application/json; charset=utf-8"
        else:
            body, kind, code = b'{"error":"Unknown API route"}', "application/json", 404
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


ThreadingHTTPServer((host, port), Handler).serve_forever()
