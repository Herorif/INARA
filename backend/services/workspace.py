"""Owned compatibility services for memory and legacy agents.

The retained adapters are optional. This envelope does not make generated CAD
code or autonomous browser actions a sandboxed/transactional tool system.
"""

import asyncio
import base64
import inspect
from pathlib import Path
import uuid

from core.event_bus import event_owner
from services.capability_profiles import provider_key
from services.legacy_cad import LegacyScriptRunner
from services.tools import (
    LEGACY_GENERATED_CAD_PERMISSION,
    ServiceError,
    ToolSpec,
    contained_path,
)
from services.workspace_contracts import PromptRequest, SaveMemory


WORKSPACE_TOOLS = {
    "save_memory": (SaveMemory, "save_memory", 10),
    # Generated-code CAD never shares the safe offline generate_cad policy.
    "legacy_generate_cad": (PromptRequest, LEGACY_GENERATED_CAD_PERMISSION, 300),
    "iterate_cad": (PromptRequest, LEGACY_GENERATED_CAD_PERMISSION, 300),
    "prompt_web_agent": (PromptRequest, "run_web_agent", 180),
}


def provider_ready():
    if not provider_key():
        raise ServiceError(
            "provider_not_configured",
            "AI is not configured yet. Add a Gemini API key in Setup or Preferences.",
        )


async def close_agent(agent):
    """Release adapter-owned browser and provider resources on all exit paths."""
    for value in (getattr(agent, "browser", None), getattr(agent, "client", None)):
        if value:
            close = getattr(value, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result


class WorkspaceService:
    def __init__(self, app):
        self.app, self.sessions, self.dispatcher = app, app.sessions, app.dispatcher
        self.requests = {}
        self.preflight = provider_ready
        self.cad_factory = self.make_cad
        # Injection point for the owned legacy-script process (WorkspaceProcess).
        self.legacy_process_factory = None
        for name, (schema, permission, timeout) in WORKSPACE_TOOLS.items():
            self.dispatcher.register(
                ToolSpec(
                    name,
                    f"Retained desktop compatibility action: {name}.",
                    schema,
                    self.execute(name),
                    permission=permission,
                    execution_timeout=timeout,
                    model_visible=name == "save_memory",
                    # Generated CAD and web agent runs take minutes: they pause the turn budget.
                    long_running=name != "save_memory",
                    # The web agent reads outside pages and can act on them (S15.1 taint rule).
                    **(
                        {"untrusted_output": True, "untrusted_source": "a web page",
                         "outward": True}
                        if name == "prompt_web_agent" else {}
                    ),
                )
            )

    @staticmethod
    def make_cad(**kwargs):
        from cad_agent import CadAgent

        return CadAgent(**kwargs)

    def authorize(self, context):
        self.app.authorize_owner(context)

    async def emit(self, event, owner, payload):
        if self.sessions.is_owner(owner) and self.sessions.authenticated(owner):
            await self.app.delivery.publish_job(event, owner, payload)

    def execute(self, name):
        async def run(args, context):
            self.authorize(context)
            if name not in ("save_memory",):
                self.app.resources.require_heavy()
            task = asyncio.current_task()
            self.requests[task] = context.get("origin_sid")
            token = event_owner.set(context["principal"])
            try:
                if name == "save_memory":
                    root = Path(context["project_path"]).resolve()
                    filename = args.filename or f"memory_{uuid.uuid4().hex}"
                    if not filename.endswith(".txt"):
                        filename += ".txt"
                    path = contained_path(root, "long_term_memory/" + filename)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path = contained_path(root, "long_term_memory/" + filename)
                    try:
                        with path.open("x", encoding="utf-8") as stream:
                            stream.write("".join(f"{m.sender}: {m.text}\n" for m in args.messages))
                    except FileExistsError as exc:
                        raise ServiceError(
                            "memory_exists", "Choose another name; existing memory was preserved."
                        ) from exc
                    return {
                        "message": "Memory Saved Successfully",
                        "path": str(path.relative_to(root)),
                    }
                if name == "prompt_web_agent":
                    return await self.browse(args, context)
                self.preflight()
                return await self.cad(name, args, context)
            finally:
                event_owner.reset(token)
                self.requests.pop(task, None)

        return run

    async def browse(self, args, context):
        raise ServiceError(
            "browser_migrated",
            "Autonomous browser commands are retired. Use the read-only Web inspector with an explicit HTTPS URL.",
        )

    async def cad(self, name, args, context):
        if self.app.resources.creative_active or self.app.resources.creative_lock.locked():
            raise ServiceError("creative_busy", "Another creative job is running.")
        async with self.app.resources.creative_lock:
            root = Path(context["project_path"]).resolve()
            folder = contained_path(root, "cad/legacy")
            folder.mkdir(parents=True, exist_ok=True)
            folder = contained_path(root, "cad/legacy")

            async def publish(event, value):
                self.authorize(context)
                await self.emit(event, context["principal"], value)

            # Adapter callbacks are scoped to this request and invalidated on return.
            live = True
            callbacks = set()

            def callback(event, transform):
                def receive(value):
                    if live:
                        task = asyncio.create_task(publish(event, transform(value)))
                        callbacks.add(task)
                        task.add_done_callback(callbacks.discard)

                return receive

            agent = None
            try:
                # The runner awaits the child's full exit on every path, so the
                # creative lock held here is released only after the tree is gone.
                agent = self.cad_factory(
                    runner=LegacyScriptRunner(
                        self.app.resources, process_factory=self.legacy_process_factory
                    ),
                    on_thought=callback("cad_thought", lambda v: {"text": v}),
                    on_status=callback(
                        "cad_status", lambda v: v if isinstance(v, dict) else {"status": v}
                    ),
                )
                method = (
                    agent.iterate_prototype if name == "iterate_cad" else agent.generate_prototype
                )
                result = await method(args.prompt, output_dir=str(folder))
                if not result or "file_path" not in result:
                    raise ServiceError(
                        "cad_failed", "Legacy CAD did not produce a project artifact."
                    )
                path = Path(result["file_path"]).resolve()
                if (
                    not path.is_relative_to(folder)
                    or not path.is_file()
                    or not 0 < path.stat().st_size <= 16_777_216
                ):
                    raise ServiceError(
                        "artifact_invalid",
                        "Legacy CAD output is outside its bounded project folder.",
                    )
                with path.open("rb") as stream:
                    raw = stream.read(16_777_217)
                if not 0 < len(raw) <= 16_777_216:
                    raise ServiceError("artifact_invalid", "Legacy CAD output changed or exceeded its size limit.")
                data = {
                    "format": "stl",
                    "data": base64.b64encode(raw).decode(),
                    "file_path": str(path),
                }
                await publish("cad_data", data)
                return {
                    "message": "Design updated" if name == "iterate_cad" else "Design generated"
                }
            finally:
                live = False
                for task in callbacks:
                    task.cancel()
                await asyncio.gather(*callbacks, return_exceptions=True)
                await close_agent(agent)

    async def stop_requests(self, sid=None):
        tasks = [
            t
            for t, origin in tuple(self.requests.items())
            if (sid is None or sid == origin) and t is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def disconnect(self, sid):
        await self.stop_requests(sid)

    async def close(self):
        await self.stop_requests()
