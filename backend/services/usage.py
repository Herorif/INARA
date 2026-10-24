"""Durable owner-wide admission budgets and private, content-free invocation receipts.

Allowances are retained even when provider billing is unknown. These limits govern
INARA authorizations; they cannot guarantee a provider-side invoice ceiling.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import math
from pathlib import Path
import time
import uuid
from services.storage import scope_hash
from services.tools import ServiceError

CURRENT_USAGE = ContextVar("inara_usage", default=None)
UNMETERED_TOOLS = frozenset(
    {
        "prompt_web_agent",
        "run_web_agent",
        "legacy_generate_cad",
        "generate_cad_prototype",
        "iterate_cad",
        "start_audio",
        "resume_audio",
        "upload_memory",
        "video_frame",
        "take_screenshot",
        "describe_camera",
        "detect_presence",
        "watch_for",
    }
)


def usage_counts(response):
    """Whitelist raw SDK counters, including cached/thinking/tool prompt counters."""
    raw = getattr(response, "raw", response)
    value = getattr(raw, "usage_metadata", None)
    if value is None:
        return None
    fields = {
        "input_tokens": "prompt_token_count",
        "output_tokens": "candidates_token_count",
        "thinking_tokens": "thoughts_token_count",
        "cached_tokens": "cached_content_token_count",
        "tool_prompt_tokens": "tool_use_prompt_token_count",
        "total_tokens": "total_token_count",
    }
    result = {}
    for target, source in fields.items():
        count = value.get(source) if isinstance(value, dict) else getattr(value, source, None)
        if type(count) is int and 0 <= count <= 10_000_000_000:
            result[target] = count
    return result or None


class UsageOperation:
    def __init__(self, service, owner, project, feature, operation):
        self.service, self.owner, self.project = service, owner, project
        self.feature, self.operation, self.step = feature, str(operation), 0

    def begin(self, model):
        step = self.step
        self.step += 1
        return self.service.begin(
            self.owner, self.project, self.feature, self.operation, step, model
        )

    async def generate(self, provider, messages, **kwargs):
        ticket = self.begin(getattr(provider, "_model", "unreported"))
        if ticket["capped"]:
            kwargs["max_output_tokens"] = ticket["max_output_tokens"]
        started = time.monotonic()
        try:
            response = await provider.generate(messages, **kwargs)
        except BaseException:
            self.service.finish(ticket, "uncertain", None, time.monotonic() - started)
            raise
        self.service.finish(ticket, "completed", usage_counts(response), time.monotonic() - started)
        return response


async def metered_generate(provider, messages, **kwargs):
    operation = CURRENT_USAGE.get()
    if operation:
        return await operation.generate(provider, messages, **kwargs)
    return await provider.generate(messages, **kwargs)


class UsageService:
    policy_kind = "usage_policy_v1"

    def __init__(self, app, clock=time.time):
        self.app, self.database, self.clock = app, app.database, clock
        self.instance = str(uuid.uuid4())
        self.active = set()
        self.legacy_active = set()

    def periods(self, stamp=None):
        now = datetime.fromtimestamp(self.clock() if stamp is None else stamp, timezone.utc)
        return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")

    def load(self, db, owner):
        key = scope_hash(owner)
        value = self.database.get(db, self.policy_kind, key) or {
            "revision": str(uuid.uuid4()),
            "enabled": False,
            "daily_microusd": 0,
            "monthly_microusd": 0,
            "per_call_microusd": 0,
            "max_output_tokens": 4096,
            "clock": self.clock(),
            "days": {},
            "months": {},
        }
        if self.clock() < value["clock"] - 30:
            raise ServiceError(
                "usage_clock", "Laptop clock moved backwards. Correct it before cloud use."
            )
        value["clock"] = max(value["clock"], self.clock())
        self.database.put(db, self.policy_kind, key, value)
        return key, value

    def owner(self, owner):
        if not self.app.sessions.is_owner(owner) or not self.app.sessions.authenticated(owner):
            raise ServiceError(
                "usage_owner", "Unlock the desktop owner to inspect or change budgets."
            )

    def configure(self, owner, args):
        self.owner(owner)
        # Existing unmetered adapters cannot be made retroactively bounded mid-task.
        workspace = getattr(self.app, "workspace", None)
        local = getattr(self.app, "local_transport", None)
        extended = getattr(self.app, "extended_actions", None)
        if args.enabled and (
            self.legacy_active
            or getattr(workspace, "audio", None)
            or getattr(workspace, "requests", None)
            or getattr(local, "running", None)
            or getattr(extended, "running", None)
            or self.app.vision_loop.list_watches()
        ):
            raise ServiceError(
                "usage_busy",
                "Stop legacy media/browser/device tasks and scene watches before enabling caps.",
            )
        with self.database.transaction() as db:
            key, value = self.load(db, owner)
            if value["revision"] != str(args.revision):
                raise ServiceError(
                    "usage_stale", "Budget changed. Refresh and review before applying."
                )
            value.update(args.model_dump(mode="json", exclude={"revision"}))
            value["revision"] = str(uuid.uuid4())
            self.database.put(db, self.policy_kind, key, value)
        return self.snapshot(owner)

    @contextmanager
    def scope(self, owner, project, feature, operation):
        scope = UsageOperation(self, owner, project, feature, operation)
        token = CURRENT_USAGE.set(scope)
        try:
            yield scope
        finally:
            CURRENT_USAGE.reset(token)

    def operation(self, owner, project, feature, identifier):
        return UsageOperation(self, owner, project, feature, identifier)

    def call_kind(self, owner, month):
        return "usage_calls_v1:" + scope_hash(owner) + ":" + month

    def begin(self, owner, project, feature, operation, step, model):
        identifier = scope_hash(
            f"{owner}\n{Path(project).resolve()}\n{feature}\n{operation}\n{step}"
        )
        try:
            reference = str(
                uuid.UUID(str(operation).split(":")[1] if ":" in str(operation) else str(operation))
            )
        except ValueError:
            reference = None
        if len(self.active) >= 16:
            raise ServiceError(
                "usage_busy", "Too many cloud requests are active. Wait before trying again."
            )
        with self.database.transaction() as db:
            key, policy = self.load(db, owner)
            day, month = self.periods(policy["clock"])
            kind = self.call_kind(owner, month)
            if self.database.get(db, kind, identifier):
                raise ServiceError(
                    "usage_duplicate",
                    "This provider step was already admitted. It will not be replayed.",
                )
            count = db.execute("SELECT count(*) FROM documents WHERE kind=?", (kind,)).fetchone()[0]
            if count >= 4096:
                raise ServiceError(
                    "usage_capacity",
                    "Monthly usage receipt capacity reached. No cloud request was started.",
                )
            amount = policy["per_call_microusd"] if policy["enabled"] else 0
            if policy["enabled"]:
                if policy["days"].get(day, 0) + amount > policy["daily_microusd"]:
                    raise ServiceError(
                        "usage_daily_limit",
                        "Daily cloud authorization budget reached. No provider call was started.",
                    )
                if policy["months"].get(month, 0) + amount > policy["monthly_microusd"]:
                    raise ServiceError(
                        "usage_monthly_limit",
                        "Monthly cloud authorization budget reached. No provider call was started.",
                    )
            policy["days"][day] = policy["days"].get(day, 0) + amount
            policy["months"][month] = policy["months"].get(month, 0) + amount
            policy["days"] = dict(sorted(policy["days"].items())[-62:])
            policy["months"] = dict(sorted(policy["months"].items())[-24:])
            ticket = {
                "id": identifier,
                "request_id": reference,
                "provider_step": step,
                "kind": kind,
                "owner": owner,
                "project": Path(project).name,
                "project_scope": scope_hash(Path(project).resolve()),
                "feature": feature,
                "model": str(model)[:120],
                "state": "reserved",
                "created_at": self.clock(),
                "allowance_microusd": amount,
                "capped": policy["enabled"],
                "max_output_tokens": policy["max_output_tokens"],
                "instance": self.instance,
                "tokens": None,
                "duration_seconds": None,
                "cloud": True,
            }
            self.database.put(db, kind, identifier, ticket)
            self.database.put(db, self.policy_kind, key, policy)
        self.active.add(identifier)
        return ticket

    def finish(self, ticket, state, counts, duration):
        try:
            with self.database.transaction() as db:
                value = self.database.get(db, ticket["kind"], ticket["id"])
                if value and value["state"] == "reserved":
                    value.update(
                        state=state, tokens=counts, duration_seconds=round(max(0, duration), 3)
                    )
                    self.database.put(db, ticket["kind"], ticket["id"], value)
        finally:
            self.active.discard(ticket["id"])

    def begin_local_call(self, owner, project, request_id, *, model="local_structured_english"):
        """Content-free local admission, never a cloud authorization or invoice."""
        self.owner(owner)
        _, month = self.periods()
        identifier = scope_hash(f"local-call\n{owner}\n{Path(project).resolve()}\n{request_id}")
        kind = "usage_local_v1:" + scope_hash(owner) + ":" + month
        with self.database.transaction() as db:
            if self.database.get(db, kind, identifier):
                raise ServiceError("usage_duplicate", "This local call was already admitted; it will not replay.")
            count = db.execute("SELECT count(*) FROM documents WHERE kind=?", (kind,)).fetchone()[0]
            if count >= 4096:
                raise ServiceError("usage_capacity", "Monthly local receipt capacity reached.")
            ticket = {
                "id": identifier, "kind": kind, "request_id": str(request_id),
                "provider_step": None, "project": Path(project).name,
                "project_scope": scope_hash(Path(project).resolve()), "feature": "local_call",
                "model": str(model)[:120], "state": "reserved",
                "created_at": self.clock(), "allowance_microusd": 0, "cloud": False,
                "tokens": None, "duration_seconds": None,
            }
            self.database.put(db, kind, identifier, ticket)
        self.active.add(identifier)
        return ticket

    def local_job(self, owner, project, feature, value):
        _, month = self.periods()
        identifier = scope_hash(
            f"local\n{owner}\n{Path(project).resolve()}\n{feature}\n{value['request_id']}"
        )
        duration = value.get("duration_seconds", 0)
        if not isinstance(duration, (int, float)) or not math.isfinite(duration):
            duration = 0
        with self.database.transaction() as db:
            self.database.put(
                db,
                "usage_local_v1:" + scope_hash(owner) + ":" + month,
                identifier,
                {
                    "id": identifier,
                    "request_id": value["request_id"],
                    "provider_step": None,
                    "project": Path(project).name,
                    "project_scope": scope_hash(Path(project).resolve()),
                    "feature": feature,
                    "model": "local_worker",
                    "state": value["state"],
                    "created_at": value["created_at"],
                    "allowance_microusd": 0,
                    "cloud": False,
                    "tokens": None,
                    "duration_seconds": round(max(0, duration), 3),
                },
            )

    def snapshot(self, owner, project=None):
        self.owner(owner)
        with self.database.transaction() as db:
            _, value = self.load(db, owner)
            day, month = self.periods(value["clock"])
            calls = self.database.all(db, self.call_kind(owner, month))
            local = self.database.all(db, "usage_local_v1:" + scope_hash(owner) + ":" + month)
        if project is not None:
            target = scope_hash(Path(project).resolve())
            recent = [item for item in [*calls, *local] if item["project_scope"] == target]
        else:
            recent = [*calls, *local]
        records = []
        for item in sorted(recent, key=lambda item: item["created_at"], reverse=True)[:50]:
            public = {
                key: item[key]
                for key in (
                    "id",
                    "project",
                    "feature",
                    "model",
                    "state",
                    "created_at",
                    "allowance_microusd",
                    "cloud",
                    "tokens",
                    "duration_seconds",
                )
            }
            public["request_id"] = item.get("request_id")
            public["provider_step"] = item.get("provider_step")
            if public["state"] == "reserved" and item["id"] not in self.active:
                public["state"] = "uncertain"
            records.append(public)
        return {
            "project": Path(project).name if project is not None else None,
            "policy": {
                key: value[key]
                for key in (
                    "revision",
                    "enabled",
                    "daily_microusd",
                    "monthly_microusd",
                    "per_call_microusd",
                    "max_output_tokens",
                )
            },
            "day_utc": day,
            "month_utc": month,
            "daily_authorized_microusd": value["days"].get(day, 0),
            "monthly_authorized_microusd": value["months"].get(month, 0),
            "cloud_calls_this_month": len(calls),
            "records": records,
            "scope": "owner_wide_limits_project_filtered_records",
            "invoice_cost_known": False,
            "coverage": ["desktop_chat", "phone_chat", "cad_plan", "cad_changes", "transcription"],
            "unmetered_legacy_blocked_when_enabled": True,
        }

    @contextmanager
    def tool_scope(self, name, context):
        feature = {"plan_cad": "cad_plan", "plan_cad_changes": "cad_changes"}.get(name)
        if not feature and name not in UNMETERED_TOOLS:
            yield
            return
        owner = context["principal"]
        with self.database.transaction() as db:
            _, value = self.load(db, owner)
        if value["enabled"] and name in UNMETERED_TOOLS:
            raise ServiceError(
                "usage_unmetered",
                "This legacy cloud adapter is unavailable while caps are enabled. Use the metered chat, reviewed speech or typed CAD proposal instead.",
            )
        if feature:
            with self.scope(
                owner,
                context["project_path"],
                feature,
                context.get("usage_operation") or str(uuid.uuid4()),
            ):
                yield
        else:
            marker = object()
            if name in UNMETERED_TOOLS:
                self.legacy_active.add(marker)
            try:
                yield
            finally:
                self.legacy_active.discard(marker)
