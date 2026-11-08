"""A minimal MCP client over the stdio transport (docs/MCP.md), standard library only.

One ``McpClient`` is one server process: JSON-RPC 2.0 as newline-delimited UTF-8 JSON on
the child's stdin and stdout, with the 2025 lifecycle (initialize, then
notifications/initialized), tools/list with cursor pagination, tools/call, ping,
notifications/tools/list_changed and notifications/cancelled when a request times out.

Process rules:
- the server runs from an explicit argv list, never through a shell; batch files are
  refused because Windows runs them through cmd.exe;
- the working directory and environment are explicit: a minimal safe base plus the
  configured variables, with secrets resolved from the encrypted SecretStore by name;
- on Windows the child starts suspended, joins a kill-on-close Job Object and only then
  runs, so it and every process it starts die with the core or on ``close()``;
- each message is at most 1 MB, each request has a deadline, and stderr is kept in a
  bounded ring buffer that is redacted and never logged.
"""

import asyncio
import collections
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)

# Newest first: the version offered in initialize, then the older ones JARVIS accepts.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = PROTOCOL_VERSIONS[0]
CLIENT_INFO = {"name": "JARVIS", "version": "1.0.0"}
MAX_MESSAGE = 1024 * 1024
READ_CHUNK = 64 * 1024
DEFAULT_TIMEOUT = 30.0
STDERR_LINES = 200
STDERR_LINE_CHARS = 2000
CLOSE_GRACE = 2.0
LIST_PAGE_LIMIT = 50
TOOL_LIMIT = 1000
REDACTED = "[redacted]"
# Programs Windows runs through cmd.exe: their arguments would be shell-parsed.
BATCH_SUFFIXES = (".bat", ".cmd")
# The inherited environment is limited to what Windows programs need to start.
SAFE_ENV = frozenset(
    {
        "systemroot", "systemdrive", "windir", "comspec", "pathext", "path", "temp", "tmp",
        "programdata", "programfiles", "programfiles(x86)", "programw6432",
        "commonprogramfiles", "commonprogramfiles(x86)", "commonprogramw6432", "public",
        "allusersprofile", "appdata", "localappdata", "userprofile", "username",
        "homedrive", "homepath", "os", "processor_architecture", "number_of_processors",
    }
)
CREATE_SUSPENDED, CREATE_NO_WINDOW = 0x4, 0x08000000
# JSON-RPC errors JARVIS sends for server-to-client requests it doesn't serve.
METHOD_NOT_FOUND = -32601


class McpError(ServiceError):
    """A plain, owner-safe failure; never contains a secret value or raw stderr."""


class Redactor:
    """Replaces configured secret values in diagnostic text (longest first)."""

    def __init__(self, secrets=()):
        self.values = sorted({value for value in secrets if isinstance(value, str) and value},
                             key=len, reverse=True)

    def __call__(self, text):
        if not isinstance(text, str):
            return text
        for value in self.values:
            if value in text:
                text = text.replace(value, REDACTED)
        return text


@dataclass
class McpLaunch:
    """What to start: never contains a shell string; ``secrets`` are for redaction only."""

    argv: list
    cwd: str
    env: dict
    secrets: tuple = ()
    timeout: float = DEFAULT_TIMEOUT
    redact: Redactor = field(default=None)

    def __post_init__(self):
        if self.redact is None:
            self.redact = Redactor(self.secrets)


def base_environment(environ=None):
    environ = os.environ if environ is None else environ
    return {key: value for key, value in environ.items() if key.lower() in SAFE_ENV}


def build_launch(config, secret_lookup, *, environ=None, default_cwd=None):
    """McpLaunch for one validated McpServerConfig.

    ``secret_lookup(name)`` returns the secret's value or None. Raises McpError with a
    plain message when a secret is missing, the program can't be found, it is a batch
    file, the folder doesn't exist or a secret value appears in the command.
    """
    env = base_environment(environ)
    secrets = []
    for key, value in config.env.items():
        if not isinstance(value, str):
            name = value.secret
            resolved = secret_lookup(name)
            if not isinstance(resolved, str) or not resolved:
                raise McpError(
                    "mcp_secret_missing",
                    f"The secret {name} isn't saved yet. Save it in Connections, then try again.",
                )
            if "\x00" in resolved:
                raise McpError("mcp_secret_invalid", f"The secret {name} can't be used here.")
            value = resolved
            secrets.append(resolved)
        for existing in [item for item in env if item.casefold() == key.casefold()]:
            del env[existing]
        env[key] = value
    argv = [str(item) for item in config.command]
    if any(secret in item for secret in secrets for item in argv):
        raise McpError(
            "mcp_secret_in_command",
            "A secret value appears in the command. Pass secrets through env instead.",
        )
    program = argv[0]
    path = Path(program)
    if not path.is_absolute():
        found = shutil.which(program, path=next(
            (value for key, value in env.items() if key.casefold() == "path"), None
        ))
        if found is None:
            raise McpError(
                "mcp_program_missing",
                f"JARVIS couldn't find {program[:80]}. Use the program's full path.",
            )
        path = Path(found)
    if path.suffix.lower() in BATCH_SUFFIXES:
        raise McpError(
            "mcp_batch_file",
            "Batch files (.cmd, .bat) run through the Windows shell. Point the command at "
            "the program itself, for example node and the server's script.",
        )
    if not path.is_file():
        raise McpError(
            "mcp_program_missing", f"JARVIS couldn't find {program[:80]}. Use the program's full path."
        )
    argv[0] = str(path)
    cwd = config.cwd or default_cwd or str(Path.home())
    if not Path(cwd).is_dir():
        raise McpError("mcp_cwd_missing", "The server's working folder doesn't exist.")
    return McpLaunch(argv, str(cwd), env, tuple(secrets), float(config.timeout_s))


class _KillJob:
    """A kill-on-close Windows Job Object holding the server and everything it starts.

    Uses the core's own Win32 boundary (resident.win32): the structures and the
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE limit the workspace workers run under.
    """

    def __init__(self, pid):
        import ctypes as C
        from ctypes import wintypes as W

        from resident.win32 import ExtendedLimit, api, checked, close_handle, kernel

        self._api, self._kernel, self._close, self._W = api, kernel, close_handle, W
        self.job = checked(
            api(kernel, "CreateJobObjectW", [W.LPVOID, W.LPCWSTR], W.HANDLE)(None, None)
        )
        try:
            limits = ExtendedLimit()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            checked(
                api(kernel, "SetInformationJobObject",
                    [W.HANDLE, C.c_int, W.LPVOID, W.DWORD], W.BOOL)(
                    self.job, 9, C.byref(limits), C.sizeof(limits)
                )
            )
            # PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME
            process = checked(
                api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                    0x0001 | 0x0100 | 0x0800, False, pid
                )
            )
            try:
                checked(
                    api(kernel, "AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL)(
                        self.job, process
                    )
                )
                ntdll = C.WinDLL("ntdll")
                resume = ntdll.NtResumeProcess
                resume.argtypes, resume.restype = [W.HANDLE], C.c_long
                if resume(process) != 0:
                    raise OSError("The server process could not be resumed")
            finally:
                close_handle(process)
        except BaseException:
            self.close()
            raise

    def terminate(self):
        if self.job:
            W = self._W
            self._api(self._kernel, "TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL)(self.job, 1)

    def close(self):
        if self.job:
            self._close(self.job)
            self.job = None


async def spawn(launch):
    """Start the process suspended, put it in its job, then let it run (Windows)."""
    if os.name != "nt":
        process = await asyncio.create_subprocess_exec(
            *launch.argv, cwd=launch.cwd, env=launch.env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        return process, None
    process = await asyncio.create_subprocess_exec(
        *launch.argv, cwd=launch.cwd, env=launch.env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW,
    )
    try:
        job = _KillJob(process.pid)
    except BaseException:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise
    return process, job


def _key(value):
    return json.dumps(value) if isinstance(value, (int, str)) and not isinstance(value, bool) else None


class McpClient:
    """One MCP server process. States: new, starting, ready, closing, closed, failed.

    ``on_notification(method, params)`` gets server notifications the client doesn't
    handle itself (``notifications/tools/list_changed`` first of all); ``on_exit(client)``
    runs once when the process ends without ``close()``.
    """

    def __init__(self, launch, *, on_notification=None, on_exit=None, spawner=None):
        self.launch = launch
        self.on_notification = on_notification
        self.on_exit = on_exit
        self.spawner = spawner or spawn
        self.state = "new"
        self.process = self.job = None
        self.protocol_version = None
        self.server_info = {}
        self.capabilities = {}
        self.instructions = None
        self.exit_code = None
        self.stderr = collections.deque(maxlen=STDERR_LINES)
        self.dropped_messages = 0
        self.pending = {}
        self.next_id = 0
        self.tasks = []
        self.write_lock = asyncio.Lock()
        self.started_at = None

    # --- lifecycle --------------------------------------------------------------------------
    async def start(self):
        """Spawn, initialize and send notifications/initialized. Raises McpError."""
        if self.state != "new":
            raise McpError("mcp_state", "This server connection was already used.")
        self.state = "starting"
        try:
            self.process, self.job = await self.spawner(self.launch)
        except OSError as exc:
            self.state = "failed"
            logger.warning("MCP server could not start (%s)", type(exc).__name__)
            raise McpError("mcp_start_failed", "The server program could not be started.") from None
        self.started_at = time.monotonic()
        self.tasks = [
            asyncio.create_task(self._read_stdout(), name="mcp-stdout"),
            asyncio.create_task(self._read_stderr(), name="mcp-stderr"),
            asyncio.create_task(self._watch_exit(), name="mcp-exit"),
        ]
        try:
            result = await self.request(
                "initialize",
                {
                    "protocolVersion": LATEST_PROTOCOL,
                    "capabilities": {},
                    "clientInfo": dict(CLIENT_INFO),
                },
                cancel_on_timeout=False,  # the spec forbids cancelling initialize
            )
            if not isinstance(result, dict):
                raise McpError("mcp_protocol", "The server answered initialize incorrectly.")
            version = result.get("protocolVersion")
            if version not in PROTOCOL_VERSIONS:
                shown = version if isinstance(version, str) else "unknown"
                raise McpError(
                    "mcp_version",
                    f"The server uses MCP version {shown[:20]}, which JARVIS doesn't support. "
                    f"JARVIS supports {', '.join(PROTOCOL_VERSIONS)}.",
                )
            capabilities = result.get("capabilities")
            self.protocol_version = version
            self.capabilities = capabilities if isinstance(capabilities, dict) else {}
            info = result.get("serverInfo")
            info = info if isinstance(info, dict) else {}
            self.server_info = {
                key: _clip(self.launch.redact(info[key]), 120)
                for key in ("name", "title", "version")
                if isinstance(info.get(key), str)
            }
            instructions = result.get("instructions")
            self.instructions = (
                _clip(self.launch.redact(instructions), 2000)
                if isinstance(instructions, str) else None
            )
            await self.notify("notifications/initialized")
        except BaseException:
            await self.close()
            if self.state != "failed":
                self.state = "failed"
            raise
        self.state = "ready"
        return result

    async def close(self, grace=CLOSE_GRACE):
        """Close stdin, wait up to ``grace`` seconds, then kill the whole process tree."""
        if self.state in ("closing", "closed"):
            return
        failed = self.state == "failed"
        self.state = "closing"
        process = self.process
        try:
            if process is not None and process.returncode is None:
                try:
                    if process.stdin is not None:
                        process.stdin.close()
                except (OSError, RuntimeError):
                    pass
                try:
                    await asyncio.wait_for(asyncio.shield(process.wait()), grace)
                except TimeoutError:
                    pass
            self._kill()
            if process is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(process.wait()), 5)
                except TimeoutError:
                    logger.warning("MCP server process did not exit after being stopped")
                self.exit_code = process.returncode
        finally:
            if self.job is not None:
                self.job.close()  # kill-on-close: anything left in the job ends here
                self.job = None
            self._fail_pending(McpError("mcp_stopped", "The server was stopped."))
            current = asyncio.current_task()
            for task in self.tasks:
                if task is not current:
                    task.cancel()
            await asyncio.gather(
                *(task for task in self.tasks if task is not current), return_exceptions=True
            )
            self.state = "failed" if failed else "closed"

    def _kill(self):
        if self.job is not None:
            try:
                self.job.terminate()
            except OSError:
                pass
        process = self.process
        if process is not None and process.returncode is None:
            try:
                if os.name != "nt":
                    import signal

                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

    async def _watch_exit(self):
        code = await self.process.wait()
        self.exit_code = code
        # Let the readers drain what the server wrote before it exited (bounded: a
        # grandchild can hold the pipes open).
        readers = [task for task in self.tasks[:2] if not task.done()]
        if readers:
            await asyncio.wait(readers, timeout=1.0)
        if self.state in ("starting", "ready"):
            self.state = "failed"
            logger.warning("MCP server exited unexpectedly (exit code %s)", code)
            self._fail_pending(
                McpError("mcp_crashed", f"The server stopped unexpectedly (exit code {code}).")
            )
            if self.job is not None:
                try:
                    self.job.terminate()
                except OSError:
                    pass
            if self.on_exit is not None:
                try:
                    self.on_exit(self)
                except Exception:
                    logger.exception("MCP exit handler failed")

    def _fail_pending(self, error):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        self.pending.clear()

    @property
    def alive(self):
        return self.state == "ready" and self.process is not None and self.process.returncode is None

    def stderr_tail(self, lines=20):
        """The last stderr lines, redacted. For diagnostics only: never logged."""
        return [self.launch.redact(line) for line in list(self.stderr)[-lines:]]

    # --- reading ----------------------------------------------------------------------------
    async def _lines(self, stream, on_oversize):
        buffer, discarding = bytearray(), False
        while True:
            chunk = await stream.read(READ_CHUNK)
            if not chunk:
                if buffer and not discarding:
                    yield bytes(buffer)
                return
            buffer.extend(chunk)
            while True:
                index = buffer.find(b"\n")
                if index < 0:
                    break
                line = bytes(buffer[:index])
                del buffer[: index + 1]
                if discarding:
                    discarding = False
                    continue
                if len(line) > MAX_MESSAGE:
                    on_oversize()
                    continue
                yield line
            if len(buffer) > MAX_MESSAGE:
                buffer.clear()
                if not discarding:
                    on_oversize()
                discarding = True

    async def _read_stdout(self):
        def oversize():
            self.dropped_messages += 1
            logger.warning("An MCP server message over 1 MB was dropped")

        async for line in self._lines(self.process.stdout, oversize):
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                self.dropped_messages += 1  # stray output on stdout; never logged
                continue
            for item in message if isinstance(message, list) else (message,):
                if isinstance(item, dict):
                    await self._handle(item)

    async def _read_stderr(self):
        def oversize():
            self.stderr.append("[a stderr line over 1 MB was dropped]")

        async for line in self._lines(self.process.stderr, oversize):
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            if text.strip():
                self.stderr.append(_clip(text, STDERR_LINE_CHARS))

    async def _handle(self, message):
        if message.get("jsonrpc") != "2.0":
            return
        method = message.get("method")
        if isinstance(method, str):
            if "id" in message:
                await self._serve(message)
            elif self.on_notification is not None and method == "notifications/tools/list_changed":
                try:
                    self.on_notification(method, message.get("params"))
                except Exception:
                    logger.exception("MCP notification handler failed")
            # Every other notification (logging, progress, resources) is ignored.
            return
        key = _key(message.get("id"))
        future = self.pending.pop(key, None) if key is not None else None
        if future is None or future.done():
            return  # a late answer to a cancelled request, or an unrelated id
        if isinstance(message.get("error"), dict):
            error = message["error"]
            text = error.get("message") if isinstance(error.get("message"), str) else ""
            code = error.get("code") if isinstance(error.get("code"), int) else None
            future.set_exception(McpError(
                "mcp_server_error",
                "The server returned an error"
                + (f" ({code})" if code is not None else "")
                + (f" (untrusted text): {_clip(self.launch.redact(text), 300)}" if text else "."),
            ))
        elif "result" in message:
            future.set_result(message["result"])
        else:
            future.set_exception(McpError("mcp_protocol", "The server sent an invalid answer."))

    async def _serve(self, message):
        """Server-to-client requests: answer ping; refuse the rest (no client features)."""
        if message["method"] == "ping":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": METHOD_NOT_FOUND, "message": "JARVIS doesn't offer this."},
            }
        try:
            await self._send(reply)
        except McpError:
            pass

    # --- writing ----------------------------------------------------------------------------
    async def _send(self, message):
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_MESSAGE:
            raise McpError("mcp_too_large", "The request is over 1 MB.")
        process = self.process
        if process is None or process.returncode is not None or process.stdin is None:
            raise McpError("mcp_stopped", "The server isn't running.")
        async with self.write_lock:
            try:
                process.stdin.write(data + b"\n")
                await process.stdin.drain()
            except (OSError, RuntimeError, ConnectionError) as exc:
                raise McpError("mcp_stopped", "The server isn't running.") from exc

    async def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    async def request(self, method, params=None, timeout=None, *, cancel_on_timeout=True):
        """Send one request and wait for its answer; raises McpError on error or timeout.

        On a timeout (or if the caller is cancelled) the server gets
        notifications/cancelled for this request id and a late answer is ignored."""
        if self.state not in ("starting", "ready"):
            raise McpError("mcp_stopped", "The server isn't running.")
        self.next_id += 1
        request_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[_key(request_id)] = future
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        timeout = self.launch.timeout if timeout is None else timeout
        try:
            await self._send(message)
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            if cancel_on_timeout:
                await self._cancel(request_id, f"JARVIS stopped waiting after {timeout:g} seconds.")
            raise McpError(
                "mcp_timeout", f"The server didn't answer within {timeout:g} seconds."
            ) from None
        except asyncio.CancelledError:
            if cancel_on_timeout and self.alive:
                # Best effort and bounded: the caller is going away.
                task = asyncio.ensure_future(self._cancel(request_id, "JARVIS cancelled the request."))
                self.tasks.append(task)
            raise
        finally:
            self.pending.pop(_key(request_id), None)

    async def _cancel(self, request_id, reason):
        try:
            await asyncio.wait_for(
                self.notify("notifications/cancelled", {"requestId": request_id, "reason": reason}),
                2,
            )
        except (McpError, TimeoutError):
            pass

    # --- MCP methods ------------------------------------------------------------------------
    async def ping(self, timeout=None):
        await self.request("ping", None, timeout)

    async def list_tools(self):
        """Every tool, following nextCursor (at most 50 pages and 1000 tools)."""
        if "tools" not in self.capabilities:
            return []
        tools, cursor, seen = [], None, set()
        for _ in range(LIST_PAGE_LIMIT):
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("mcp_protocol", "The server listed its tools incorrectly.")
            for item in result["tools"]:
                tool = parse_tool(item)
                if tool is not None and len(tools) < TOOL_LIMIT:
                    tools.append(tool)
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                break
            seen.add(cursor)
        return tools

    async def call_tool(self, name, arguments, timeout=None):
        """The raw tools/call result: {content: [...], isError, structuredContent?}."""
        result = await self.request("tools/call", {"name": name, "arguments": arguments}, timeout)
        if not isinstance(result, dict):
            raise McpError("mcp_protocol", "The server answered the tool call incorrectly.")
        content = result.get("content")
        return {
            "content": content if isinstance(content, list) else [],
            "isError": result.get("isError") is True,
            **(
                {"structuredContent": result["structuredContent"]}
                if "structuredContent" in result else {}
            ),
        }


def parse_tool(item):
    """A listed tool as {name, title, description, input_schema}, or None if unusable."""
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 128 or any(
        ord(char) < 32 or ord(char) == 127 for char in name
    ):
        return None
    annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
    title = item.get("title") if isinstance(item.get("title"), str) else annotations.get("title")
    schema = item.get("inputSchema")
    return {
        "name": name,
        "title": _clip(title, 80) if isinstance(title, str) and title.strip() else None,
        "description": (
            _clip(item["description"], 4000) if isinstance(item.get("description"), str) else ""
        ),
        "input_schema": schema if isinstance(schema, dict) else {"type": "object"},
    }


def _clip(text, limit):
    text = "".join(char if char >= " " or char in "\t\n" else " " for char in text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
