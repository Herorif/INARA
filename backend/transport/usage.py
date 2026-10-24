"""Owner-only budgets and explicit fixture-quality execution; never model tools."""

import asyncio
from pydantic import ValidationError
from services.settings import EmptyRequest
from services.usage_contracts import UsagePolicy
from services.quality import QualityService
from services.storage import StorageError
from services.tools import ServiceError


class UsageTransport:
    models = {
        "usage_state": EmptyRequest,
        "usage_policy": UsagePolicy,
        "quality_state": EmptyRequest,
        "quality_run": EmptyRequest,
        "quality_cancel": EmptyRequest,
    }

    def __init__(self, app):
        self.app = app
        app.quality = QualityService(app)
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def handle(sid, data=None):
            try:
                owner = self.app.sessions.require_owner(
                    sid, {"renderer"}, allow_locked=name == "quality_cancel"
                )
                project = self.app.sessions.context(sid).project_path
                args = model.model_validate(data)
                if name == "usage_policy":
                    self.app.usage.configure(owner, args)
                    result = self.app.usage.snapshot(owner, project)
                elif name == "usage_state":
                    result = self.app.usage.snapshot(owner, project)
                elif name == "quality_run":
                    result = await self.app.quality.run(sid, owner, project)
                elif name == "quality_cancel":
                    await self.app.quality.stop_sid(sid)
                    result = self.app.quality.snapshot(owner, project)
                else:
                    result = self.app.quality.snapshot(owner, project)
                return {"ok": True, **result}
            except asyncio.CancelledError:
                return {
                    "ok": False,
                    "code": "quality_cancelled",
                    "message": "Offline checks stopped. Nothing will be replayed.",
                }
            except (ValidationError, ServiceError, StorageError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "usage_arguments"),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Budget or report could not be validated/unlocked. Existing records are preserved.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "usage_failed",
                    "message": "Usage action could not complete. Refresh before continuing.",
                }

        return handle
