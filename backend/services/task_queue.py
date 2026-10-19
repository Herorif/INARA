"""Project-bound durable task receipts. Interrupted effects are never replayed."""

import asyncio
import hashlib
import json
import time
from services.storage import scope_hash
from services.tools import ServiceError, contained_path

KIND = "desktop_tasks_v1"
TERMINAL = {"completed", "stopped", "interrupted"}


class TaskQueue:
    def __init__(self, app):
        self.app, self.active = app, {}

    def key(self, owner, project):
        return scope_hash(owner + "\n" + str(project.resolve()))

    def load(self, db, key):
        return self.app.database.get(db, KIND, key) or {"plans": {}, "seen": {}}

    def recover(self, book, key):
        changed = False
        for identifier, plan in book["plans"].items():
            if plan["state"] == "running" and (key, identifier) not in self.active:
                changed = True
                plan["state"] = "interrupted"
                plan["updated_at"] = time.time()
                for step in plan["steps"]:
                    if step["state"] == "running":
                        step.update(state="uncertain", code="interrupted")
                    elif step["state"] in {"pending", "awaiting_approval"}:
                        step.update(state="cancelled", code="interrupted")

        return changed

    def state(self, owner, project):
        key = self.key(owner, project)
        with self.app.database.transaction() as db:
            book = self.load(db, key)
            if self.recover(book, key):
                self.app.database.put(db, KIND, key, book)
        return {
            "project": project.name,
            "tasks": sorted(
                book["plans"].values(), key=lambda item: item["created_at"], reverse=True
            ),
            "capacity": 24,
            "receipts_used": len(book["seen"]),
            "receipt_limit": 2048,
        }

    def create(self, owner, project, args):
        identifier = str(args.id)
        raw = args.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        for step in args.steps:
            if step.tool in {"read_file", "write_file"}:
                contained_path(project, step.path)
        key = self.key(owner, project)
        with self.app.database.transaction() as db:
            book = self.load(db, key)
            self.recover(book, key)
            if identifier in book["seen"]:
                if book["seen"][identifier] != digest:
                    raise ServiceError(
                        "task_conflict",
                        "This task ID already belongs to a different immutable plan.",
                    )
                if identifier not in book["plans"]:
                    raise ServiceError(
                        "task_retired",
                        "This task receipt is retained, but its plan details have expired. It cannot be replayed.",
                    )
                return
            if len(book["seen"]) >= 2048:
                raise ServiceError(
                    "task_receipt_limit",
                    "This project's durable task receipt limit has been reached. Existing receipts are preserved.",
                )
            if len(book["plans"]) >= 24:
                completed = [item for item in book["plans"].values() if item["state"] in TERMINAL]
                if not completed:
                    raise ServiceError(
                        "task_capacity",
                        "Finish existing drafts before creating another plan (24-plan limit).",
                    )
                oldest = min(completed, key=lambda item: item["created_at"])
                del book["plans"][oldest["id"]]
            now = time.time()
            book["plans"][identifier] = {
                "id": identifier,
                "title": args.title,
                "state": "draft",
                "created_at": now,
                "updated_at": now,
                "steps": [
                    {
                        "tool": step.tool,
                        "args": step.model_dump(exclude={"tool"}),
                        "state": "pending",
                        "code": None,
                        "preview": None,
                    }
                    for step in args.steps
                ],
            }
            book["seen"][identifier] = digest
            self.app.database.put(db, KIND, key, book)

    def change(self, key, identifier, change):
        with self.app.database.transaction() as db:
            book = self.load(db, key)
            plan = book["plans"].get(identifier)
            if plan is None:
                raise ServiceError(
                    "task_missing", "This task is not available in the selected project."
                )
            change(plan)
            plan["updated_at"] = time.time()
            self.app.database.put(db, KIND, key, book)
            return plan

    def authorize(self, sid, owner, project):
        current = self.app.sessions.require_owner(sid, {"renderer"})
        if current != owner or self.app.sessions.context(sid).project_path != project:
            raise ServiceError(
                "task_scope_changed", "Task stopped because the selected project or owner changed."
            )

    async def run(self, sid, owner, project, identifier, approve):
        self.authorize(sid, owner, project)
        if self.active:
            raise ServiceError(
                "task_busy", "A reviewed task is already active. Stop it before starting another."
            )
        key = self.key(owner, project)

        def claim(plan):
            if plan["state"] != "draft":
                raise ServiceError(
                    "task_not_draft",
                    "This task has already been attempted or stopped. It cannot be resumed or replayed.",
                )
            plan["state"] = "running"

        plan = self.change(key, identifier, claim)
        self.active[(key, identifier)] = (asyncio.current_task(), sid)
        index = 0
        try:
            async with asyncio.timeout(720):
                for index, step in enumerate(plan["steps"]):
                    self.authorize(sid, owner, project)
                    self.step(key, identifier, index, state="awaiting_approval")

                    async def review(payload):
                        await approve(
                            {
                                **payload,
                                "project": project.name,
                                "task_queue": {
                                    "id": identifier,
                                    "step": index + 1,
                                    "total": len(plan["steps"]),
                                },
                            }
                        )

                    def before_execute():
                        self.authorize(sid, owner, project)
                        # This transaction must commit before any adapter effect.
                        self.step(key, identifier, index, state="running")

                    result = await self.app.dispatcher.dispatch(
                        owner,
                        step["tool"],
                        step["args"],
                        {"project_path": project, "origin_sid": sid},
                        review,
                        authorize=lambda: self.authorize(sid, owner, project),
                        force_approval=True,
                        before_execute=before_execute,
                    )
                    self.authorize(sid, owner, project)
                    preview = result.get("text", "")[:4000] if step["tool"] == "read_file" else None
                    self.step(key, identifier, index, state="completed", code=None, preview=preview)
            self.change(key, identifier, lambda value: value.update(state="completed"))
        except BaseException as exc:
            code = getattr(
                exc,
                "code",
                "task_cancelled" if isinstance(exc, asyncio.CancelledError) else "task_failed",
            )

            cancelled = isinstance(exc, asyncio.CancelledError)

            def stop(value):
                value["state"] = "stopped"
                for number, item in enumerate(value["steps"]):
                    if item["state"] == "running":
                        item.update(state="uncertain", code=code)
                    elif item["state"] in {"pending", "awaiting_approval"}:
                        item.update(
                            state="failed" if number == index and not cancelled else "cancelled",
                            code=code,
                        )

            self.change(key, identifier, stop)
            if isinstance(exc, asyncio.CancelledError):
                raise
            # Failure is a durable stopped plan, not a request to retry its steps.
        finally:
            self.active.pop((key, identifier), None)

    def step(self, key, identifier, index, **values):
        self.change(key, identifier, lambda plan: plan["steps"][index].update(**values))

    async def cancel(self, sid, owner, project, identifier):
        key = self.key(owner, project)
        active = self.active.get((key, identifier))
        if active is None:
            # A project-switch cleanup still owns the task captured by this SID.
            active = next(
                (
                    value
                    for (_, task_id), value in self.active.items()
                    if task_id == identifier and value[1] == sid
                ),
                None,
            )
        if active:
            if active[1] != sid:
                raise ServiceError(
                    "task_origin", "Stop the active task from its originating workspace."
                )
            active[0].cancel()
            await asyncio.gather(active[0], return_exceptions=True)
            return

        def stop(plan):
            if plan["state"] == "draft":
                plan["state"] = "stopped"
                for step in plan["steps"]:
                    step.update(state="cancelled", code="task_cancelled")

        self.change(key, identifier, stop)

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.active.values())
            if task is not asyncio.current_task() and (sid is None or origin == sid)
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
