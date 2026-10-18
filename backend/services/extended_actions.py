"""Strict shared actions replacing the remaining ad-hoc voice branches."""

import fnmatch
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictStr, field_validator
from core.event_bus import event_owner
from services.local_actions import NoArguments, LaunchApp, ControlDevice
from services.tools import ServiceError, ToolSpec, contained_path


class DirectoryRequest(NoArguments):
    path: StrictStr = Field(default=".", min_length=1, max_length=1024)


class SearchRequest(NoArguments):
    query: StrictStr = Field(min_length=1, max_length=200)
    directory: StrictStr = Field(default=".", min_length=1, max_length=1024)

    @field_validator("query")
    @classmethod
    def filename_pattern(cls, value):
        if any(c in value for c in "/\\:") or any(ord(c) < 32 for c in value):
            raise ValueError("Use a filename pattern in the selected project.")
        return value


class ProjectRequest(NoArguments):
    name: StrictStr = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def plain_name(cls, value):
        if (
            not value.strip()
            or value != value.strip()
            or any(not (c.isalnum() or c in " -_") for c in value)
            or value.upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(10)],
                *[f"LPT{i}" for i in range(10)],
            }
        ):
            raise ValueError("Use a plain project name.")
        return value


class ClipboardRequest(NoArguments):
    text: StrictStr = Field(max_length=200000)


class CameraQuestion(NoArguments):
    question: StrictStr | None = Field(default=None, min_length=1, max_length=2000)


class WatchRequest(NoArguments):
    description: StrictStr = Field(min_length=1, max_length=2000)
    watch_id: StrictStr | None = Field(default=None, min_length=1, max_length=100)


class DeviceRequest(NoArguments):
    device_id: StrictStr = Field(min_length=1, max_length=200)


class PrinterStatusRequest(NoArguments):
    printer: StrictStr = Field(min_length=1, max_length=200)


class RoutineRequest(NoArguments):
    name: StrictStr = Field(min_length=1, max_length=100)
    trigger: Literal[
        "greeting:good_morning",
        "greeting:im_home",
        "greeting:goodnight",
        "greeting:leaving",
        "manual",
    ]
    actions: StrictStr = Field(min_length=1, max_length=2000)


class ControlLight(ControlDevice):
    device_id: StrictStr = Field(alias="target", min_length=1, max_length=200)


EXTENDED_MODELS = {
    "read_directory": DirectoryRequest,
    "search_files": SearchRequest,
    "create_project": ProjectRequest,
    "switch_project": ProjectRequest,
    "list_projects": NoArguments,
    "create_routine": RoutineRequest,
    "list_routines": NoArguments,
    "list_running_apps": NoArguments,
    "focus_window": LaunchApp,
    "write_clipboard": ClipboardRequest,
    "describe_camera": CameraQuestion,
    "detect_presence": NoArguments,
    "watch_for": WatchRequest,
    "list_watches": NoArguments,
    "get_device_state": DeviceRequest,
    "get_print_status": PrinterStatusRequest,
}


class ExtendedActions:
    def __init__(self, app):
        self.app = app
        for name, model in EXTENDED_MODELS.items():
            app.dispatcher.register(
                ToolSpec(
                    name,
                    f"Owner-scoped {name.replace('_', ' ')}.",
                    model,
                    self.execute(name),
                    execution_timeout=30,
                )
            )
        for name, target, model in (
            (
                "generate_cad_prototype",
                "legacy_generate_cad",
                app.dispatcher.tools["legacy_generate_cad"].arguments,
            ),
            (
                "run_web_agent",
                "prompt_web_agent",
                app.dispatcher.tools["prompt_web_agent"].arguments,
            ),
            ("list_smart_devices", "list_all_devices", NoArguments),
            ("control_light", "control_device", ControlLight),
        ):
            spec = app.dispatcher.tools[target]

            async def alias(args, context, target_spec=spec):
                app.authorize_owner(context)
                validated = target_spec.arguments.model_validate(args.model_dump(exclude_none=True))
                return await target_spec.execute(validated, context)

            app.dispatcher.register(
                ToolSpec(
                    name,
                    f"Compatibility alias for {target}.",
                    model,
                    alias,
                    permission=spec.permission or target,
                    execution_timeout=spec.execution_timeout,
                    model_visible=False,
                    alias_for=target,
                )
            )

    def execute(self, name):
        async def run(args, context):
            self.app.authorize_owner(context)
            token = event_owner.set(context["principal"])
            try:
                if name in ("read_directory", "search_files"):
                    root = Path(context["project_path"]).resolve()
                    folder = contained_path(
                        root,
                        args.path if name == "read_directory" else args.directory,
                        allow_root=True,
                    )
                    if not folder.is_dir():
                        raise ServiceError(
                            "directory_missing", "Select a directory inside this project."
                        )
                    found, stack, inspected, seen = [], [folder], 0, {folder.resolve()}
                    while (
                        stack
                        and inspected < 2000
                        and len(found) < (200 if name == "read_directory" else 20)
                    ):
                        for item in stack.pop().iterdir():
                            inspected += 1
                            if inspected > 2000:
                                break
                            resolved = item.resolve()
                            if not resolved.is_relative_to(root) or item.is_symlink():
                                continue
                            if name == "read_directory" or fnmatch.fnmatch(
                                item.name.casefold(), args.query.casefold()
                            ):
                                found.append(str(item.relative_to(root)))
                            if name == "search_files" and item.is_dir() and resolved not in seen:
                                seen.add(resolved)
                                stack.append(item)
                            if len(found) >= (200 if name == "read_directory" else 20):
                                break
                    return {"paths": found, "bounded": True}
                if name in ("create_project", "switch_project", "list_projects"):
                    projects = self.app.projects
                    if name == "list_projects":
                        return {"projects": projects.list_projects()}
                    contained_path(projects.projects_dir, args.name)
                    if name == "create_project":
                        ok, message = projects.create_project(args.name)
                    else:
                        ok, message = projects.switch_project(args.name)
                    if not ok:
                        raise ServiceError(
                            "project_failed", "The project action could not complete."
                        )
                    if name == "switch_project":
                        await self.app.delivery.publish_job(
                            "project_update",
                            context["principal"],
                            {"project": projects.current_project},
                        )
                    return {"message": message, "project": projects.current_project}
                if name == "get_print_status":
                    printer = self.app.compat_service.activate_printer()
                    target = printer._resolve_printer(args.printer)
                    if not target:
                        raise ServiceError("printer_missing", "Select a configured printer.")
                    result = await printer.get_print_status(target.host)
                    if result is None:
                        raise ServiceError(
                            "printer_unavailable", "The printer did not return status."
                        )
                    return result.to_dict()
                if name in ("create_routine", "list_routines"):
                    agent = self.app.scheduler
                elif name in ("describe_camera", "detect_presence", "watch_for", "list_watches"):
                    self.app.resources.require_heavy()
                    agent = self.app.vision
                elif name == "get_device_state":
                    agent = self.app.devices
                else:
                    agent = self.app.desktop
                result = await agent.handle_tool_call(name, args.model_dump(exclude_none=True))
                if not result.success:
                    raise ServiceError(
                        "action_failed", "The capability could not complete. Check its setup."
                    )
                return {"success": True, "message": result.message, "data": result.data}
            finally:
                event_owner.reset(token)

        return run
