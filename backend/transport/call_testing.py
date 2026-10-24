"""Owner renderer controlled-test routes; no remote proof upload or policy toggle."""

from pydantic import ValidationError
from calls.test_contracts import TestPrepare, TestRevision, TestArm, TestStop
from services.settings import EmptyRequest
from services.tools import ServiceError


class CallTestingTransport:
    def __init__(self, app):
        self.app = app
        for event, model, method in (("call_test_state", EmptyRequest, "state"),
                                     ("call_test_prepare", TestPrepare, "prepare"),
                                     ("call_test_review", TestRevision, "review"),
                                     ("call_test_arm", TestArm, "arm"),
                                     ("call_test_stop", TestStop, "stop")):
            app.sio.on(event, handler=self.handler(model, method))

    def handler(self, model, method):
        async def handle(sid, data=None):
            try:
                self.app.call_testing.context(sid)
                args = model.model_validate(data)
                operation = getattr(self.app.call_testing, method)
                result = operation(sid) if method == "state" else operation(sid, args)
                if hasattr(result, "__await__"):
                    result = await result
                self.app.call_testing.context(sid)
                return {"ok": True, **result}
            except (ServiceError, ValidationError) as exc:
                return {"ok": False, "code": exc.code if isinstance(exc, ServiceError) else "invalid_arguments",
                        "message": str(exc) if isinstance(exc, ServiceError) else "Use the current controlled-test fields. Imported proof or live-mode flags are not accepted."}
            except Exception:
                return {"ok": False, "code": "call_test_unavailable", "message": "The controlled-test workflow could not complete. Refresh; never replay an uncertain arm request."}
        return handle
