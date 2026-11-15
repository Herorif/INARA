"""The JARVIS CAD kernel: feature trees built into real geometry by an isolated worker.

``CadKernel(app)`` owns one worker process, ``backend/workers/cad_kernel_worker.py`` run by
``.venv-cad``'s own interpreter (build123d) with ``-I`` and a temp job folder as its working
directory. It speaks JSON lines over stdin/stdout (the protocol is in the worker's docstring).
The worker starts on the first build and is reused; it stops after 5 idle minutes, on
``stop()``/``close()``, and is killed with its whole process tree (a kill-on-close Job Object
on Windows, as for MCP servers) when a build times out (draft 20 s, final 120 s) or the
awaiting caller is cancelled. A worker that crashed is replaced on the next build.

``available()`` is False, with ``reason``, when the venv or the worker is missing or the
worker couldn't start (retried after a few minutes): callers keep today's box engine then.

``build(tree, export, quality)`` returns facts and file paths. Draft builds are GLB only and
cached by the hash of the tree with its export forced to ["glb"], so export choices never
bust the preview cache. Kernel failures become plain messages in ``CadKernelError``.

Logs carry codes and timings only: never trees, text or paths.
"""

import asyncio
import collections
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from services.cad_features import FeatureTreeError, canonical, describe, parse_tree, tree_hash
from services.log import get_logger
from services.mcp_client import McpLaunch, base_environment, spawn
from services.tools import ServiceError

logger = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "backend" / "workers" / "cad_kernel_worker.py"
VENV = REPO / ".venv-cad"
TIMEOUTS = {"draft": 20.0, "final": 120.0}
START_TIMEOUT = 90.0  # the first build123d import can take a while on a cold disk
IDLE_SECONDS = 300.0
IDLE_TICK = 15.0
RETRY_AFTER = 300.0
STOP_TIMEOUT = 5.0
CACHE_LIMIT = 64
STDERR_LINES = 50
READ_LIMIT = 1024 * 1024
QUALITIES = ("draft", "final")
EXPORTS = ("glb", "stl", "step")
EDGE_WORDS = {"all": "", "vertical": "vertical corner ", "top": "top ", "bottom": "bottom "}
# What the owner hears when a feature needs the kernel and it isn't installed.
SETUP_HINT = (
    "Holes, fillets and cut-outs need the CAD engine. Run scripts/setup-cad-engine.ps1."
)


def venv_python(venv):
    venv = Path(venv)
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


class CadKernelError(ServiceError):
    """A plain, owner-readable failure; ``feature``/``index`` name the step when known."""

    def __init__(self, code, message, *, kernel_code=None, feature=None, index=None):
        super().__init__(code, message)
        self.kernel_code, self.feature, self.index = kernel_code, feature, index


def mm(value):
    return f"{round(float(value), 2):g}"


def a_mm(value):
    """'A 3 mm' / 'An 8 mm' / 'An 11 mm'."""
    text = mm(value)
    vowel = text.startswith("8") or text.split(".")[0] in ("11", "18")
    return f"{'An' if vowel else 'A'} {text} mm"


def plain_error(reply, tree):
    """CadKernelError for a failed build reply, worded from the feature tree."""
    code = reply.get("code") or "kernel_failed"
    index = reply.get("index")
    detail = reply.get("detail") if isinstance(reply.get("detail"), dict) else {}
    features = tree.features
    feature = features[index] if isinstance(index, int) and 0 <= index < len(features) else None
    step = ""
    if feature is not None:
        line = describe(tree)[index]
        step = f"Step {index + 1} ({line[:1].lower()}{line[1:]})"
    target = None
    if feature is not None:
        target = getattr(feature, "target", None) or getattr(feature, "of", None)
    target = target or "the design"
    op = detail.get("op")
    if code == "kernel_failed" and op in ("fillet", "chamfer") and detail.get("size"):
        room = detail.get("room") or 0
        if room > 0:
            message = f"{a_mm(detail['size'])} {op} doesn't fit the {mm(room)} mm edge on {target}."
        else:
            message = f"{a_mm(detail['size'])} {op} doesn't fit the edges of {target}."
    elif code == "kernel_failed" and op == "shell" and detail.get("size"):
        message = (
            f"JARVIS couldn't shell {target} to {mm(detail['size'])} mm walls. Try thinner walls"
            + (" or shell before rounding the edges." if any(
                item.op in ("fillet", "chamfer") for item in features[:index]
            ) else ".")
        )
    elif code == "no_edges":
        words = EDGE_WORDS.get(detail.get("edges"), "")
        verb = "round" if feature is not None and feature.op == "fillet" else "chamfer"
        message = f"There are no {words}edges on {target} to {verb}."
    elif code == "empty_result":
        message = f"{step or 'The design'} leaves nothing of {target}."
    elif code == "export_failed":
        message = "JARVIS built the design but couldn't save its files. Try again."
    elif code == "bad_request":
        message = "The CAD engine couldn't read that design."
    elif step:
        message = f"{step} couldn't be built. Try smaller sizes or a different order."
    else:
        message = "The CAD engine couldn't build that design."
    return CadKernelError(
        "cad_kernel_failed", message, kernel_code=code,
        feature=feature.id if feature is not None else None, index=index,
    )


class CadKernel:
    def __init__(
        self,
        app=None,
        *,
        venv=None,
        python=None,
        worker=WORKER,
        root=None,
        timeouts=None,
        start_timeout=START_TIMEOUT,
        idle_seconds=IDLE_SECONDS,
        idle_tick=IDLE_TICK,
        retry_after=RETRY_AFTER,
        clock=time.monotonic,
    ):
        self.app = app
        self.venv = Path(venv) if venv is not None else VENV
        self.python = Path(python) if python is not None else venv_python(self.venv)
        self.worker = Path(worker)
        self.root = Path(root) if root is not None else None
        self.own_root = root is None
        self.timeouts = {**TIMEOUTS, **(timeouts or {})}
        self.start_timeout, self.idle_seconds, self.idle_tick = (
            start_timeout, idle_seconds, idle_tick,
        )
        self.retry_after, self.clock = retry_after, clock
        self.process = self.job = None
        self.version = None
        self.failed_at = None
        self.start_reason = None
        self.last_used = clock()
        self.next_id = 0
        self.lock = None
        self.tasks = set()
        self.stderr = collections.deque(maxlen=STDERR_LINES)
        self.cache = collections.OrderedDict()
        self.starts = 0

    # --- availability ---------------------------------------------------------------------

    @property
    def reason(self):
        """Why the kernel isn't available (None when it is)."""
        if not self.python.is_file():
            return "The CAD engine isn't installed (.venv-cad is missing)."
        if not self.worker.is_file():
            return "The CAD engine's worker is missing."
        if self.failed_at is not None and self.clock() - self.failed_at < self.retry_after:
            return self.start_reason or "The CAD engine couldn't start."
        return None

    def available(self):
        return self.reason is None

    def running(self):
        return self.process is not None and self.process.returncode is None

    def status(self):
        return {"available": self.available(), "reason": self.reason,
                "running": self.running(), "version": self.version}

    # --- process --------------------------------------------------------------------------

    def folder(self):
        if self.root is None:
            self.root = Path(tempfile.mkdtemp(prefix="jarvis-cad-kernel-"))
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def spawn_task(self, coroutine, name):
        task = asyncio.get_running_loop().create_task(coroutine, name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self):
        reason = self.reason
        if reason is not None:
            raise CadKernelError("cad_kernel_unavailable", reason)
        started = time.perf_counter()
        argv = [str(self.python), "-I", str(self.worker)]
        try:
            self.process, self.job = await spawn(
                McpLaunch(argv, str(self.folder()), base_environment())
            )
        except (OSError, ValueError) as exc:
            self.mark_failed("spawn", type(exc).__name__)
            raise CadKernelError("cad_kernel_unavailable", self.start_reason) from None
        self.starts += 1
        self.stderr.clear()
        process = self.process
        self.spawn_task(self.drain(process), "cad-kernel-stderr")
        try:
            reply = await asyncio.wait_for(
                self.exchange({"cmd": "ping"}), self.start_timeout
            )
        except (TimeoutError, CadKernelError, OSError, ValueError) as exc:
            await self.kill()
            self.mark_failed("ping", getattr(exc, "code", type(exc).__name__))
            raise CadKernelError("cad_kernel_unavailable", self.start_reason) from None
        except BaseException:
            await self.kill()
            raise
        if not reply.get("ok"):
            await self.kill()
            self.mark_failed("ping", str(reply.get("code"))[:40])
            raise CadKernelError("cad_kernel_unavailable", self.start_reason)
        self.version = reply.get("version")
        self.failed_at = self.start_reason = None
        self.last_used = self.clock()
        self.spawn_task(self.watch_idle(process), "cad-kernel-idle")
        logger.info("CAD kernel started in %.2fs", time.perf_counter() - started)

    def mark_failed(self, stage, code):
        self.failed_at = self.clock()
        self.start_reason = "The CAD engine couldn't start, so JARVIS is using the simple box engine."
        logger.warning("CAD kernel failed to start (%s: %s)", stage, code)

    async def drain(self, process):
        stream = process.stderr
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                self.stderr.append(line[:500].decode("utf-8", "replace").rstrip())
        except (OSError, ValueError, asyncio.CancelledError):
            return

    async def watch_idle(self, process):
        while self.process is process and process.returncode is None:
            await asyncio.sleep(self.idle_tick)
            if self.process is not process:
                return
            busy = self.lock is not None and self.lock.locked()
            if not busy and self.clock() - self.last_used >= self.idle_seconds:
                logger.info("CAD kernel stopped after being idle")
                await self.stop()
                return

    def terminate(self):
        """Kill the worker and everything it started, right now (synchronous)."""
        job, process = self.job, self.process
        if job is not None:
            try:
                job.terminate()
            except OSError:
                pass
        if process is not None and process.returncode is None:
            try:
                if os.name != "nt":
                    import signal

                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

    async def kill(self):
        process, job = self.process, self.job
        self.terminate()
        self.process = self.job = None
        try:
            if process is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(process.wait()), STOP_TIMEOUT)
                except TimeoutError:
                    logger.warning("CAD kernel process did not exit after being stopped")
        finally:
            if job is not None:
                job.close()  # kill-on-close: anything left in the job ends here

    async def stop(self):
        """Stop the worker (it starts again on the next build); the cache stays."""
        process = self.process
        if process is None:
            return
        if process.returncode is None and self.lock is not None and not self.lock.locked():
            try:
                process.stdin.write(b'{"cmd": "exit"}\n')
                await process.stdin.drain()
                await asyncio.wait_for(asyncio.shield(process.wait()), 2.0)
            except (OSError, TimeoutError, ValueError):
                pass
        await self.kill()

    async def close(self):
        await self.stop()
        current = asyncio.current_task()
        tasks = [task for task in self.tasks if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.cache.clear()
        if self.own_root and self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None

    # --- requests -------------------------------------------------------------------------

    async def exchange(self, message):
        """Send one request and read lines until its reply (no timeout here)."""
        process = self.process
        if process is None or process.returncode is not None:
            raise CadKernelError("cad_kernel_crashed", "The CAD engine stopped unexpectedly.")
        self.next_id += 1
        ident = self.next_id
        data = json.dumps({**message, "id": ident}, allow_nan=False).encode("utf-8") + b"\n"
        process.stdin.write(data)
        await process.stdin.drain()
        while True:
            line = await process.stdout.readline()
            if not line:
                raise CadKernelError(
                    "cad_kernel_crashed", "The CAD engine stopped unexpectedly."
                )
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if not isinstance(reply, dict):
                continue
            if reply.get("id") == ident:
                return reply
            if reply.get("id") is None and reply.get("ok") is False:
                return reply  # the worker couldn't read the request or start at all

    async def request(self, message, timeout):
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            for attempt in (1, 2):
                if not self.running():
                    if self.process is not None:
                        await self.kill()  # it died while idle
                    await self.start()
                try:
                    reply = await asyncio.wait_for(self.exchange(message), timeout)
                except TimeoutError:
                    await self.kill()
                    raise CadKernelError(
                        "cad_kernel_timeout",
                        f"The design took longer than {timeout:g} s to build, so JARVIS stopped "
                        "it. Try fewer features or simpler text.",
                    ) from None
                except (BrokenPipeError, ConnectionResetError):
                    await self.kill()
                    if attempt == 1:
                        continue  # the request never reached a worker: start a new one
                    raise CadKernelError(
                        "cad_kernel_crashed",
                        "The CAD engine stopped unexpectedly. JARVIS will restart it on the next "
                        "build.",
                    ) from None
                except CadKernelError as exc:
                    await self.kill()
                    if exc.code == "cad_kernel_crashed":
                        raise CadKernelError(
                            "cad_kernel_crashed",
                            "The CAD engine stopped unexpectedly. JARVIS will restart it on the "
                            "next build.",
                        ) from None
                    raise
                except (OSError, ValueError):
                    await self.kill()
                    raise CadKernelError(
                        "cad_kernel_crashed",
                        "The CAD engine stopped unexpectedly. JARVIS will restart it on the next "
                        "build.",
                    ) from None
                except BaseException:
                    # Cancelled mid-build: the worker is busy, so its tree goes now.
                    self.terminate()
                    await asyncio.shield(self.kill())
                    raise
                finally:
                    self.last_used = self.clock()
                return reply
        raise AssertionError("unreachable")

    async def ping(self):
        reply = await self.request({"cmd": "ping"}, self.start_timeout)
        return reply.get("version")

    # --- builds ---------------------------------------------------------------------------

    def keyed(self, tree, export):
        data = json.loads(canonical(tree))
        data["export"] = list(export)
        return data, tree_hash(data)

    def contained(self, path):
        root = self.folder().resolve()
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise CadKernelError("cad_kernel_failed", "The CAD engine's files went missing.")
        return resolved

    async def build(self, tree, export=None, quality="draft"):
        """Facts and files for ``tree``: {facts, files: {ext: Path}, warnings, hash, quality,
        seconds, cached}. Draft builds make a GLB only (cached by tree hash)."""
        try:
            parsed = parse_tree(tree)
        except FeatureTreeError as exc:
            raise CadKernelError(exc.code, str(exc)) from None
        if quality not in QUALITIES:
            raise CadKernelError("cad_kernel_failed", "Build quality must be draft or final.")
        if quality == "draft":
            formats = ["glb"]
        else:
            chosen = parsed.export if export is None else list(export)
            if not chosen or any(name not in EXPORTS for name in chosen):
                raise CadKernelError(
                    "cad_kernel_failed", "Export formats must be glb, stl or step."
                )
            formats = [name for name in EXPORTS if name in chosen]
        data, digest = self.keyed(parsed, formats)
        key = (digest, quality)
        cached = self.cache.get(key)
        if cached is not None:
            if all(Path(path).is_file() for path in cached["files"].values()):
                self.cache.move_to_end(key)
                logger.info("CAD kernel %s build cached", quality)
                return {**cached, "files": dict(cached["files"]), "cached": True}
            del self.cache[key]
        started = time.perf_counter()
        message = {
            "cmd": "build", "tree": data, "export": formats, "quality": quality,
            "folder": f"{digest[:24]}-{quality}",
        }
        try:
            reply = await self.request(message, self.timeouts[quality])
        except CadKernelError as exc:
            logger.info("CAD kernel %s build failed (%s) after %.2fs", quality, exc.code,
                        time.perf_counter() - started)
            raise
        seconds = time.perf_counter() - started
        if not reply.get("ok"):
            error = plain_error(reply, parsed)
            logger.info("CAD kernel %s build failed (%s) after %.2fs", quality,
                        error.kernel_code, seconds)
            raise error
        files = reply.get("files") if isinstance(reply.get("files"), dict) else {}
        result = {
            "facts": reply.get("facts") or {},
            "files": {name: self.contained(files[name]) for name in formats if name in files},
            "warnings": list(reply.get("warnings") or []),
            "hash": digest,
            "quality": quality,
            "seconds": round(seconds, 3),
            "cached": False,
        }
        if set(result["files"]) != set(formats):
            raise CadKernelError("cad_kernel_failed", "The CAD engine didn't save every file.")
        logger.info("CAD kernel %s build ok in %.2fs (kernel %.2fs)", quality, seconds,
                    float(reply.get("seconds") or 0))
        if quality == "draft":
            self.cache[key] = {**result, "files": dict(result["files"])}
            while len(self.cache) > CACHE_LIMIT:
                self.evict()
        return result

    def evict(self):
        (digest, quality), _ = self.cache.popitem(last=False)
        if self.root is not None:
            shutil.rmtree(self.root / f"{digest[:24]}-{quality}", ignore_errors=True)
