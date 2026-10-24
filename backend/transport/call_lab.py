"""Only owner-scoped fixture checks and metadata; there is no live answer route."""

from pydantic import ValidationError
from calls.lab_contracts import LabReference
from services.settings import EmptyRequest
from services.tools import ServiceError


class CallLabTransport:
    def __init__(self, app):
        self.app = app
        for event, method in (("call_lab_state", self.state), ("call_lab_check", self.check),
                              ("call_lab_stop", self.stop), ("call_lab_record", self.record)):
            app.sio.on(event, handler=method)

    async def guarded(self, sid, data, operation, reference=False):
        try:
            self.app.call_lab.context(sid)
            args = LabReference.model_validate(data) if reference else EmptyRequest.model_validate(data)
            result = operation(args)
            if hasattr(result, "__await__"):
                result = await result
            self.app.call_lab.context(sid)
            return {"ok": True, **result}
        except (ServiceError, ValidationError) as exc:
            return {"ok": False, "code": exc.code if isinstance(exc, ServiceError) else "invalid_arguments",
                    "message": str(exc) if isinstance(exc, ServiceError) else "Use the current bridge check request fields."}
        except Exception:
            return {"ok": False, "code": "call_lab_unavailable", "message": "The local call check is unavailable. No live answering was enabled."}

    async def state(self, sid, data=None):
        return await self.guarded(sid, data, lambda args: self.app.call_lab.state(sid))

    async def check(self, sid, data=None):
        return await self.guarded(sid, data, lambda args: self.app.call_lab.start(sid, args.id), True)

    async def stop(self, sid, data=None):
        return await self.guarded(sid, data, lambda args: self.app.call_lab.stop(sid, args.id), True)

    async def record(self, sid, data=None):
        return await self.guarded(sid, data, lambda args: {"record": self.app.call_lab.record(sid, args.id)}, True)
