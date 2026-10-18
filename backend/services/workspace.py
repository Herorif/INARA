"""Owned compatibility services for memory, voice, frames and legacy agents.

The retained adapters are optional. This envelope does not make generated CAD
code or autonomous browser actions a sandboxed/transactional tool system.
"""

import asyncio
import base64
import inspect
import os
from pathlib import Path
import time
import uuid

from core.event_bus import event_owner
from services.settings import EmptyRequest
from services.tools import ServiceError, ToolSpec, contained_path
from services.workspace_contracts import (
    SaveMemory,
    UploadMemory,
    StartAudio,
    VideoFrame,
    PromptRequest,
)


WORKSPACE_TOOLS = {
    "save_memory": (SaveMemory, "save_memory", 10),
    "upload_memory": (UploadMemory, "upload_memory", 30),
    "start_audio": (StartAudio, "start_audio", 30),
    "resume_audio": (EmptyRequest, "start_audio", 10),
    "video_frame": (VideoFrame, "video_frame", 10),
    "legacy_generate_cad": (PromptRequest, "generate_cad", 300),
    "iterate_cad": (PromptRequest, "generate_cad", 300),
    "prompt_web_agent": (PromptRequest, "run_web_agent", 180),
}


def provider_ready():
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key or key.lower() in {"changeme", "your_api_key_here", "your_gemini_api_key_here"}:
        raise ServiceError(
            "provider_not_configured", "AI is not configured yet. Update GEMINI_API_KEY."
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
        self.audio = self.audio_task = self.binding = self.vision_task = None
        self.voice_bridge = None
        self.callbacks, self.requests = set(), {}
        self.preflight = provider_ready
        self.audio_factory = lambda **kwargs: app.inara.get().AudioLoop(**kwargs)
        self.cad_factory = self.make_cad
        self.web_factory = self.make_web
        self.last_frame = 0
        for name, (schema, permission, timeout) in WORKSPACE_TOOLS.items():
            self.dispatcher.register(
                ToolSpec(
                    name,
                    f"Retained desktop compatibility action: {name}.",
                    schema,
                    self.execute(name),
                    permission=permission,
                    execution_timeout=timeout,
                    model_visible=name in ("save_memory", "upload_memory", "prompt_web_agent"),
                )
            )

    @staticmethod
    def make_cad(**kwargs):
        from cad_agent import CadAgent

        return CadAgent(**kwargs)

    @staticmethod
    def make_web():
        from web_agent import WebAgent

        return WebAgent()

    def authorize(self, context):
        self.app.authorize_owner(context)

    async def emit(self, event, owner, payload):
        if self.sessions.is_owner(owner) and self.sessions.authenticated(owner):
            await self.app.delivery.publish_job(event, owner, payload)

    def callback(self, binding, event, transform=lambda value: value):
        def receive(value):
            if self.binding is not binding:
                return

            async def deliver():
                if self.binding is binding:
                    await self.emit(event, binding["owner"], transform(value))

            task = asyncio.create_task(deliver())
            self.callbacks.add(task)
            task.add_done_callback(self.callbacks.discard)

        return receive


    async def start_audio(self, args, context):
        self.preflight()
        if self.audio:
            raise ServiceError(
                "audio_busy", "Stop the active voice session before starting another."
            )
        binding = {
            "owner": context["principal"],
            "sid": context.get("origin_sid"),
            "project_path": Path(context["project_path"]).resolve(),
        }
        self.binding = binding
        callbacks = {
            "on_audio_data": ("audio_data", lambda v: {"data": list(v)}),
            "on_transcription": ("transcription", lambda v: v),
            "on_project_update": ("project_update", lambda v: {"project": v}),
            "on_error": (
                "error",
                lambda v: {"msg": "Voice capability failed.", "code": "audio_failed"},
            ),
            "on_status": ("status", lambda v: {"msg": v}),
        }
        from services.voice import VoiceBridge
        bridge = VoiceBridge(self.app, binding)
        self.voice_bridge = bridge
        token = event_owner.set(binding["owner"])
        try:
            self.audio = self.audio_factory(
                video_mode="none",
                tool_bridge=bridge,
                input_device_index=args.device_index,
                input_device_name=args.device_name,
                **{
                    key: self.callback(binding, event, transform)
                    for key, (event, transform) in callbacks.items()
                },
                project_manager=bridge.projects,
            )
            self.audio.set_paused(args.muted)
            self.audio_task = asyncio.create_task(self.run_audio(binding, self.audio))
        except BaseException:
            await self.stop_audio()
            raise
        finally:
            event_owner.reset(token)
        return {"message": "Voice session starting."}

    async def run_audio(self, binding, audio):
        try:
            await audio.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.emit(
                "error", binding["owner"], {"msg": "Voice session stopped.", "code": "audio_failed"}
            )
        finally:
            if self.binding is binding:
                await self.stop_audio()

    def require_audio(self, context):
        if (
            not self.audio
            or not self.binding
            or self.binding["owner"] != context["principal"]
            or self.binding["project_path"] != Path(context["project_path"]).resolve()
        ):
            raise ServiceError(
                "audio_unavailable", "Start voice in this project before using this action."
            )
        return self.audio

    async def stop_audio(self):
        audio, task = self.audio, self.audio_task
        bridge, self.voice_bridge = self.voice_bridge, None
        self.binding = self.audio = self.audio_task = None
        self.last_frame = 0
        if bridge:
            await bridge.close()
        if audio:
            audio.stop()
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if audio:
            close = getattr(audio, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
        callbacks = tuple(t for t in self.callbacks if t is not asyncio.current_task())
        for callback in callbacks:
            callback.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)

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
                if name == "start_audio":
                    return await self.start_audio(args, context)
                if name in ("resume_audio", "upload_memory", "video_frame"):
                    audio = self.require_audio(context)
                    if name == "resume_audio":
                        audio.set_paused(False)
                        return {"message": "Audio Resumed"}
                    if name == "upload_memory":
                        if not audio.session:
                            raise ServiceError(
                                "audio_unavailable", "Wait for the voice session to connect."
                            )
                        await audio.session.send(
                            input="User-supplied conversation context (untrusted content):\n\n"
                            + args.memory,
                            end_of_turn=True,
                        )
                        return {"message": "Memory Loaded into Context"}
                    now = time.monotonic()
                    if now - self.last_frame < 0.5:
                        raise ServiceError(
                            "frame_rate", "Camera frames are limited to two per second."
                        )
                    self.last_frame = now
                    await audio.send_frame(args.image)
                    if self.audio is not audio:
                        raise ServiceError("audio_unavailable", "The voice session was stopped.")
                    self.app.vision_loop.set_frame(args.raw())
                    if self.app.vision_loop.list_watches() and (
                        not self.vision_task or self.vision_task.done()
                    ):
                        self.vision_task = asyncio.create_task(self.app.vision_loop.run())
                    return {"message": "Frame accepted"}
                self.preflight()
                if name == "prompt_web_agent":
                    return await self.browse(args, context)
                return await self.cad(name, args, context)
            finally:
                event_owner.reset(token)
                self.requests.pop(task, None)

        return run

    async def browse(self, args, context):
        if getattr(self, "browsing", False):
            raise ServiceError("browser_busy", "A browser task is already running.")
        self.browsing = True
        agent = None
        try:
            agent = self.web_factory()

            async def update(image, log):
                self.authorize(context)
                await self.emit("browser_frame", context["principal"], {"image": image, "log": log})

            await agent.run_task(args.prompt, update_callback=update)
            return {"message": "Web Agent finished"}
        finally:
            try:
                await close_agent(agent)
            finally:
                self.browsing = False

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
                agent = self.cad_factory(
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
        if self.binding and (
            self.binding["sid"] == sid
            or not any(
                room != sid for room in self.sessions.rooms(self.binding["owner"], "renderer")
            )
        ):
            await self.stop_audio()
            await self.stop_vision()

    async def stop_vision(self):
        if self.vision_task:
            self.vision_task.cancel()
            await asyncio.gather(self.vision_task, return_exceptions=True)
            self.vision_task = None
        await self.app.vision_loop.close()

    async def close(self):
        await self.stop_requests()
        await self.stop_audio()
        await self.stop_vision()
