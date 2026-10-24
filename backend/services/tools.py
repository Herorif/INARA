"""One validated dispatch boundary for model and direct-client tools."""

from contextlib import nullcontext
import asyncio
import base64
import inspect
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class ServiceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def contained_path(root: Path, path: str, allow_root: bool = False) -> Path:
    """Resolve symlinks/junctions, reject Windows drive/ADS and traversal paths."""
    root = root.resolve()
    windows = PureWindowsPath(path)
    if not path or windows.drive or windows.root or ":" in path:
        raise ServiceError("path_denied", "Use a relative path inside the current project.")
    candidate = (root / path.replace("\\", "/")).resolve()
    if (candidate == root and not allow_root) or not candidate.is_relative_to(root):
        raise ServiceError("path_denied", "The path is outside the current project.")
    return candidate


class PathArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: StrictStr = Field(min_length=1, max_length=1024)


class WriteArguments(PathArguments):
    content: StrictStr = Field(max_length=200_000)


@dataclass
class ToolSpec:
    name: str
    description: str
    arguments: type[BaseModel]
    execute: Callable
    execution_timeout: float | None = None
    permission: str | None = None
    model_visible: bool = True
    alias_for: str | None = None


def inline_tool_schema(model):
    """Expand local schema references for providers whose tool format rejects $defs.

    Runtime validation still uses the original Pydantic model. Recursive tool
    contracts are intentionally unsupported rather than silently truncating them.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value, trail=()):
        if isinstance(value, list):
            return [expand(item, trail) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            reference = value["$ref"]
            if not reference.startswith("#/$defs/") or reference in trail:
                raise ValueError("Tool schemas require finite local references")
            target = definitions[reference.removeprefix("#/$defs/")]
            return expand(
                {**target, **{key: item for key, item in value.items() if key != "$ref"}},
                (*trail, reference),
            )
        return {key: expand(item, trail) for key, item in value.items()}

    return expand(schema)


class ToolDispatcher:
    def __init__(self, permissions, authenticated=lambda principal: True, timeout=60):
        self.permissions = permissions
        self.authenticated = authenticated
        self.timeout = timeout
        self.tools = {}
        self.pending = {}

    def register(self, spec: ToolSpec):
        self.tools[spec.name] = spec

    def schemas(self):
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": inline_tool_schema(spec.arguments),
            }
            for spec in self.tools.values()
            if spec.model_visible
        ]

    def resolve(self, principal, request_id, confirmed):
        pending = self.pending.get(request_id)
        if not pending or pending[0] != principal or type(confirmed) is not bool:
            return False
        future = pending[1]
        if future.done():
            return False
        future.set_result(confirmed)
        return True

    def disconnect(self, principal):
        for owner, future in list(self.pending.values()):
            if owner == principal and not future.done():
                future.set_result(False)

    async def dispatch(
        self, principal, name, arguments, context, request_approval=None, *, authorize=None,
        force_approval=False, before_execute=None
    ):
        if authorize:
            authorize()
        if not self.authenticated(principal):
            raise ServiceError("authentication_required", "Authentication is required.")
        spec = self.tools.get(name)
        if spec is None:
            raise ServiceError("tool_unavailable", "This tool is not available in text mode.")
        validated = spec.arguments.model_validate(arguments)
        permission = spec.permission or name
        policy = self.permissions().get(permission, True)
        if (
            policy == "deny"
            or self.permissions().get(name) == "deny"
            or self.permissions().get(spec.alias_for) == "deny"
        ):
            raise ServiceError("permission_denied", "This action is disabled.")
        if force_approval or policy not in (False, "allow_within_scope"):
            if request_approval is None:
                raise ServiceError("approval_required", "This action requires owner approval.")
            request_id = str(uuid.uuid4())
            future = asyncio.get_running_loop().create_future()
            self.pending[request_id] = (principal, future)
            try:
                await request_approval(
                    {
                        "id": request_id,
                        "tool": name,
                        "args": approval_arguments(validated.model_dump()),
                    }
                )
                approved = await asyncio.wait_for(future, self.timeout)
            except TimeoutError as exc:
                raise ServiceError("approval_expired", "The approval request expired.") from exc
            finally:
                self.pending.pop(request_id, None)
            if not approved:
                raise ServiceError("permission_denied", "The action was declined.")
        # Recheck authentication and disablement after waiting, before side effects.
        if authorize:
            authorize()
        if (
            not self.authenticated(principal)
            or self.permissions().get(permission) == "deny"
            or self.permissions().get(name) == "deny"
            or self.permissions().get(spec.alias_for) == "deny"
        ):
            raise ServiceError("permission_denied", "This action is no longer authorized.")

        async def execute():
            scope = getattr(self, "tool_scope", None)
            with scope(name, {**context, "principal": principal}) if scope else nullcontext():
                if before_execute:
                    before_execute()
                result = spec.execute(
                    validated,
                    {**context, "principal": principal, "request_approval": request_approval},
                )
                return await result if inspect.isawaitable(result) else result

        if spec.execution_timeout is None:
            return await execute()
        try:
            async with asyncio.timeout(spec.execution_timeout):
                return await execute()
        except TimeoutError as exc:
            raise ServiceError(
                "action_timeout", "The local action timed out; check its state before retrying."
            ) from exc


def approval_arguments(value):
    """Socket-safe review data; execution retains the validated typed arguments."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {key: approval_arguments(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [approval_arguments(item) for item in value]
    return value


def register_project_tools(dispatcher):
    def read_file(args, context):
        path = contained_path(context["project_path"], args.path)
        if path.stat().st_size > 200_000:
            raise ServiceError("file_too_large", "This file is too large for text mode.")
        return {"text": path.read_text(encoding="utf-8")}

    def write_file(args, context):
        path = contained_path(context["project_path"], args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = contained_path(context["project_path"], args.path)
        path.write_text(args.content, encoding="utf-8")
        return {"path": args.path, "message": "File saved inside the current project."}

    dispatcher.register(
        ToolSpec("read_file", "Read a UTF-8 file in the current project.", PathArguments, read_file)
    )
    dispatcher.register(
        ToolSpec(
            "write_file", "Save a UTF-8 file in the current project.", WriteArguments, write_file
        )
    )
