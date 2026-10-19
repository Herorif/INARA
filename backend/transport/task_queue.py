"""Explicit desktop-only task review. No model/mobile queue management tools."""

import asyncio
from pydantic import ValidationError
from services.settings import EmptyRequest
from services.task_queue_contracts import TaskCreate, TaskReference
from services.tools import ServiceError
from services.storage import StorageError


class TaskQueueTransport:
    models = {
        "task_queue_state": EmptyRequest,
        "task_queue_create": TaskCreate,
        "task_queue_run": TaskReference,
        "task_queue_cancel": TaskReference,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def handle(sid, data=None):
            identifier = None
            reviewed = False
            try:
                owner = self.app.sessions.require_owner(
                    sid, {"renderer"}, allow_locked=name == "task_queue_cancel"
                )
                project = self.app.sessions.context(sid).project_path
                args = model.model_validate(data)
                if name == "task_queue_create":
                    self.app.task_queue.create(owner, project, args)
                elif name == "task_queue_run":
                    identifier = str(args.id)

                    async def approve(payload):
                        nonlocal reviewed
                        reviewed = True
                        await self.app.sio.emit("tool_confirmation_request", payload, room=sid)

                    await self.app.task_queue.run(sid, owner, project, identifier, approve)
                    self.app.sessions.require_owner(sid, {"renderer"})
                elif name == "task_queue_cancel":
                    await self.app.task_queue.cancel(sid, owner, project, str(args.id))
                    return {"ok": True}  # Safety stop never hydrates private receipts while locked.
                return {"ok": True, **self.app.task_queue.state(owner, project)}
            except asyncio.CancelledError:
                return {
                    "ok": False,
                    "code": "task_cancelled",
                    "message": "Task stopped. Inspect receipts before creating another plan.",
                }
            except (ValidationError, ServiceError, StorageError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "task_arguments"),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Task data could not be validated or unlocked. Existing receipts are preserved.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "task_failed",
                    "message": "Task could not complete. Refresh receipts before continuing.",
                }
            finally:
                if identifier and reviewed:
                    await self.app.sio.emit(
                        "task_queue_approval_closed", {"id": identifier}, room=sid
                    )

        return handle
