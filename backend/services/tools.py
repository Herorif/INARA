"""One validated dispatch boundary for model and direct-client tools."""

from contextlib import nullcontext
import asyncio
import base64
import inspect
import re
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from services.log import get_logger

logger = get_logger(__name__)

# The taint rule (S15.1, docs/handover/9NovWork-specs.md S15). A brain turn's dispatch
# context carries ``taint``: the plain source labels of the untrusted content the turn has
# read (a web page, an email, a message from someone else, an MCP server's result). While
# it is non-empty, every ``ToolSpec.outward`` tool asks the owner on screen whatever its
# stored policy, and the approval card says where the untrusted content came from.
UNTRUSTED_SOURCE_DEFAULT = "an outside source"
TAINT_FACT = "caution"  # the review fact the approval card shows the taint line under
_UNTRUSTED_TAG = re.compile(r"<(\s*/?\s*)(untrusted_content)", re.IGNORECASE)


def untrusted_source(spec):
    """The source label a ``ToolSpec.untrusted_output`` tool adds to the turn's taint, or
    None for a tool whose output is JARVIS's own data."""
    if spec is None or getattr(spec, "untrusted_output", False) is not True:
        return None
    label = getattr(spec, "untrusted_source", None)
    return label if isinstance(label, str) and label.strip() else UNTRUSTED_SOURCE_DEFAULT


def taint_sources(taint):
    """The turn's taint labels, sorted so the card and the trace are deterministic."""
    return sorted({item for item in taint or () if isinstance(item, str) and item})


def taint_line(sources):
    """'This came after reading untrusted content from an email and a web page.'"""
    sources = list(sources)
    if not sources:
        return None
    joined = sources[0] if len(sources) == 1 else ", ".join(sources[:-1]) + " and " + sources[-1]
    return f"This came after reading untrusted content from {joined}."


def wrap_untrusted(text, source):
    """Untrusted tool output as labelled data for the model. Any tag inside that opens or
    closes an untrusted_content block is neutralised, so the content can't end its own
    wrapper or pose as another source."""
    label = (source or UNTRUSTED_SOURCE_DEFAULT)
    label = (
        label.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )
    body = _UNTRUSTED_TAG.sub(lambda match: "&lt;" + match.group(1) + match.group(2), text)
    return f'<untrusted_content source="{label}">{body}</untrusted_content>'


def is_outward(spec, validated, context):
    """Whether this call has an outward or physical effect (``ToolSpec.outward``)."""
    outward = getattr(spec, "outward", False)
    if callable(outward):
        return outward(validated, context) is True
    return outward is True


class ServiceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Permission keys whose absence from settings means "deny" rather than "ask".
# Generated-code execution must be enabled explicitly; it never inherits a
# relaxed policy from the safe offline tools.
LEGACY_GENERATED_CAD_PERMISSION = "legacy_generated_cad"
DEFAULT_DENY_PERMISSIONS = frozenset({LEGACY_GENERATED_CAD_PERMISSION})


def permission_policy(permissions, key):
    """Resolve one stored policy; missing keys ask, except default-deny keys."""
    return permissions.get(key, "deny" if key in DEFAULT_DENY_PERMISSIONS else True)


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
    # Optional (validated, context) -> dict of extra review facts (e.g. the
    # resolved command) shown with the approval request. May raise ServiceError.
    review: Callable | None = None
    # Always asks the owner, whatever the stored policy says (True, False or
    # "allow_within_scope"); "deny" still disables it. Enforced in dispatch().
    always_ask: bool = False
    # Optional (validated, context) -> bool. True forces the owner's approval for this
    # call whatever the stored policy says, like always_ask but per call (e.g. a Home
    # Assistant device set to "ask"); False leaves the stored policy in charge. "deny" is
    # checked first and still disables the tool. May raise ServiceError to refuse the call
    # before any approval card. Enforced in dispatch().
    ask_when: Callable | None = None
    # True for tools the owner expects to take a while (CAD builds, image generation,
    # world_tour, call placement, web agent runs): a brain turn's time budget is paused
    # while one runs, so only its own execution_timeout bounds it. Every other tool is
    # cut at the time left in the turn's budget (services/conversation.py).
    long_running: bool = False
    # True for tools whose output carries text from outside JARVIS and the owner (a web
    # page, an email, someone else's message, a non-built-in MCP server). Their results are
    # wrapped as <untrusted_content source="..."> data for the model, and a call that ran
    # adds ``untrusted_source`` (a short plain phrase, e.g. "a web page") to the turn's taint.
    untrusted_output: bool = False
    untrusted_source: str | None = None
    # True (or a (validated, context) -> bool, per call) for tools with an outward or
    # physical effect: send, call, purchase, unlock, disarm or open, delete files, computer
    # use, web agent actions, calendar writes, printing. While the turn is tainted such a
    # call always asks the owner, whatever the stored policy; "deny" still disables it.
    outward: bool | Callable = False


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
        # Observers of approval cards (the channels' remote approval bridge, S8.1): each has
        # ``approval_offered(principal, payload, timeout)`` and ``approval_settled(request_id)``,
        # both sync and never allowed to break a dispatch.
        self.approval_observers = []

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

    def _observe(self, method, *args):
        for observer in tuple(self.approval_observers):
            try:
                getattr(observer, method)(*args)
            except Exception as exc:
                logger.warning("An approval observer failed (%s)", type(exc).__name__)

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
        policy = permission_policy(self.permissions(), permission)
        if (
            policy == "deny"
            or self.permissions().get(name) == "deny"
            or self.permissions().get(spec.alias_for) == "deny"
        ):
            raise ServiceError("permission_denied", "This action is disabled.")
        # ask_when runs on every call, so a refusal it raises comes before any approval card.
        asks = spec.ask_when is not None and (
            spec.ask_when(validated, {**context, "principal": principal}) is True
        )
        # The taint rule: after untrusted content in this turn, an outward call always asks.
        sources = taint_sources(context.get("taint"))
        tainted = bool(sources) and is_outward(
            spec, validated, {**context, "principal": principal}
        )
        if tainted:
            # Content-free: the tool's name and how many sources, never what they said.
            logger.info("taint tool=%s sources=%d", name, len(sources))
        if (
            force_approval or spec.always_ask or asks or tainted
            or policy not in (False, "allow_within_scope")
        ):
            if request_approval is None:
                raise ServiceError("approval_required", "This action requires owner approval.")
            review_args = approval_arguments(validated.model_dump())
            if spec.review is not None:
                review_args = {
                    **review_args,
                    **approval_arguments(
                        spec.review(validated, {**context, "principal": principal})
                    ),
                }
            payload = {"id": str(uuid.uuid4()), "tool": name, "args": review_args}
            if tainted:
                line = taint_line(sources)
                # The generic card lists review facts; the line rides there and on its own.
                payload["args"] = {**review_args, TAINT_FACT: line}
                payload.update(taint=sources, taint_line=line)
            request_id = payload["id"]
            future = asyncio.get_running_loop().create_future()
            self.pending[request_id] = (principal, future)
            self._observe("approval_offered", principal, payload, self.timeout)
            try:
                await request_approval(payload)
                approved = await asyncio.wait_for(future, self.timeout)
            except TimeoutError as exc:
                raise ServiceError("approval_expired", "The approval request expired.") from exc
            finally:
                self.pending.pop(request_id, None)
                self._observe("approval_settled", request_id)
            if not approved:
                raise ServiceError("permission_denied", "The action was declined.")
        # Recheck authentication and disablement after waiting, before side effects.
        if authorize:
            authorize()
        if (
            not self.authenticated(principal)
            or permission_policy(self.permissions(), permission) == "deny"
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
