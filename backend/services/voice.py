"""Live voice declarations and execution from the shared tool authority."""

import copy
import asyncio
from pathlib import Path
from pydantic import ValidationError
from core.event_bus import event_owner, event_guard
from services.tools import ServiceError, inline_tool_schema
from transport.workspace import approval_summary


VOICE_TARGETS = {
    name: name
    for name in (
        "generate_cad_prototype",
        "run_web_agent",
        "create_project",
        "switch_project",
        "list_projects",
        "list_smart_devices",
        "control_light",
        "discover_printers",
        "print_stl",
        "get_print_status",
        "iterate_cad",
        "write_file",
        "read_directory",
        "read_file",
        "create_reminder",
        "list_reminders",
        "cancel_reminder",
        "snooze_reminder",
        "create_routine",
        "list_routines",
        "get_system_info",
        "launch_app",
        "list_running_apps",
        "focus_window",
        "take_screenshot",
        "search_files",
        "read_clipboard",
        "write_clipboard",
        "describe_camera",
        "detect_presence",
        "watch_for",
        "stop_watching",
        "list_watches",
        "list_all_devices",
        "control_device",
        "get_device_state",
    )
}
VOICE_TARGETS["generate_cad"] = "legacy_generate_cad"


class VoiceBridge:
    def __init__(self, app, binding):
        self.app, self.binding = app, binding
        self.running = set()
        # Reuse protected history methods without consulting mutable global selection.
        self.projects = copy.copy(app.projects)
        self.projects.current_project = Path(binding["project_path"]).name
        self.projects.get_current_project_path = lambda: Path(binding["project_path"])

    def authorize(self):
        if self.app.workspace.binding is not self.binding:
            raise ServiceError("voice_session_stopped", "This voice session has stopped.")
        sid = self.binding["sid"]
        if sid is None or self.app.sessions.principals.get(sid) != self.binding["owner"]:
            raise ServiceError("voice_session_stopped", "The voice origin disconnected.")
        self.app.sessions.require_owner(sid, {"renderer"})
        self.app.resources.require_heavy()

    def active(self):
        sid, owner = self.binding["sid"], self.binding["owner"]
        return (
            self.app.workspace.binding is self.binding
            and self.app.sessions.principals.get(sid) == owner
            and self.app.sessions.roles.get(sid) == "renderer"
            and self.app.sessions.is_owner(owner)
            and self.app.sessions.authenticated(owner)
            and self.app.resources.state not in ("resident", "gaming")
        )

    def schemas(self):
        return [
            {
                "name": name,
                "description": self.app.dispatcher.tools[target].description,
                "parameters": inline_tool_schema(self.app.dispatcher.tools[target].arguments),
            }
            for name, target in VOICE_TARGETS.items()
        ]

    async def call(self, name, arguments):
        task = asyncio.current_task()
        self.running.add(task)
        marker = event_owner.set(self.binding["owner"])
        guard = event_guard.set(self.active)
        try:
            self.authorize()
            target = VOICE_TARGETS.get(name)
            if target is None:
                raise ServiceError("tool_unavailable", "This capability is not supported in voice.")
            # Context is captured before approval; switch_project only updates the
            # binding for subsequent requests after its own authorized completion.
            context = {
                "principal": self.binding["owner"],
                "origin_sid": self.binding["sid"],
                "project_path": Path(self.binding["project_path"]).resolve(),
            }

            async def approve(payload):
                self.authorize()
                await self.app.sio.emit(
                    "tool_confirmation_request", approval_summary(payload), room=self.binding["sid"]
                )

            result = await self.app.dispatcher.dispatch(
                self.binding["owner"],
                target,
                arguments,
                context,
                approve,
                authorize=self.authorize,
            )
            if name == "switch_project":
                self.binding["project_path"] = (
                    self.app.projects.get_current_project_path().resolve()
                )
                self.projects.current_project = self.app.projects.current_project
            return result
        except (ServiceError, ValidationError) as exc:
            return {
                "error": getattr(exc, "code", "invalid_arguments"),
                "message": str(exc) if isinstance(exc, ServiceError) else "Invalid tool arguments.",
            }
        except Exception:
            return {"error": "action_failed", "message": "The voice action could not complete."}
        finally:
            event_owner.reset(marker)
            event_guard.reset(guard)
            self.running.discard(task)

    async def close(self):
        tasks = tuple(task for task in self.running if task is not asyncio.current_task())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
