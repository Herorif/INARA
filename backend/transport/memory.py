"""Origin-only owner/renderer controls. No model write tools or mobile routes."""

from pydantic import ValidationError
from services.settings import EmptyRequest
from services.memory_contracts import (
    MemoryQuery,
    MemoryWrite,
    MemoryForget,
    MemoryRetention,
    MemoryRestore,
    MemoryRestoreApply,
)
from services.storage import StorageError
from services.tools import ServiceError


class MemoryTransport:
    models = {
        "memory_list": MemoryQuery,
        "memory_write": MemoryWrite,
        "memory_forget": MemoryForget,
        "memory_retention": MemoryRetention,
        "memory_export": EmptyRequest,
        "memory_restore_preview": MemoryRestore,
        "memory_restore_apply": MemoryRestoreApply,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def handle(sid, data=None):
            try:
                owner = self.app.sessions.require_owner(sid, {"renderer"})
                project = self.app.sessions.context(sid).project_path
                args = model.model_validate(data)
                service = self.app.memory
                if name == "memory_list":
                    result = service.snapshot(owner, project, args.query, args.include_archived)
                elif name == "memory_export":
                    result = service.export(owner, project)
                else:
                    method = {
                        "memory_write": "write",
                        "memory_forget": "forget",
                        "memory_retention": "retention",
                        "memory_restore_preview": "preview",
                        "memory_restore_apply": "restore",
                    }[name]
                    result = getattr(service, method)(owner, project, args)
                return {"ok": True, **result}
            except (ServiceError, ValidationError, StorageError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "memory_arguments"),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Memory could not be validated or unlocked. Existing data is preserved.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "memory_failed",
                    "message": "Memory action could not complete. Refresh before trying again.",
                }

        return handle
