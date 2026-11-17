"""Owner-only routes for the Routines page (S7.4, docs/ROUTINES.md).

- ``routines_list``: every routine (name, trigger, steps, enabled, last run and outcome).
- ``routines_tools``: the tools a step may use (name, description, argument schema).
- ``routines_save`` {id?, name, trigger, steps, enabled?}: creates or updates one routine.
- ``routines_delete`` {id}: deletes one routine.
- ``routines_toggle`` {id, enabled}: turns its trigger on or off.
- ``routines_run`` {id}: starts it now; its approvals come to this window.

Every route needs the authenticated, unlocked desktop owner renderer. Answers are
``{ok: true, ...}`` or ``{ok: false, code, message}``. Names, phrases and step arguments
are never logged. Changes also send content-free ``routines_changed`` {id}.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError

from services.log import get_logger
from services.routines import MAX_STEPS, NAME_LIMIT
from services.settings import EmptyRequest
from services.tools import ServiceError

logger = get_logger(__name__)

ROUTINE_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class RoutineIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = Field(pattern=ROUTINE_ID)


class RoutineToggleRequest(RoutineIdRequest):
    enabled: StrictBool


class RoutineSaveRequest(BaseModel):
    """Shape only; ``RoutineStore.validate`` checks the trigger and every step."""

    model_config = ConfigDict(extra="forbid")
    id: StrictStr | None = Field(default=None, pattern=ROUTINE_ID)
    name: StrictStr = Field(min_length=1, max_length=NAME_LIMIT + 20)
    trigger: dict[str, Any]
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_STEPS)
    enabled: StrictBool | None = None


class RoutinesTransport:
    models = {
        "routines_list": EmptyRequest,
        "routines_tools": EmptyRequest,
        "routines_save": RoutineSaveRequest,
        "routines_delete": RoutineIdRequest,
        "routines_toggle": RoutineToggleRequest,
        "routines_run": RoutineIdRequest,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    @property
    def service(self):
        return self.app.routines

    def handler(self, name, model):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                principal = self.app.sessions.require_owner(sid, {"renderer"})
                request = model.model_validate({} if data is None else data)
                return await method(sid, principal, request)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {
                    "ok": False,
                    "code": "invalid_arguments",
                    "message": "That routine change isn't valid.",
                }
            except Exception as exc:
                logger.warning("Routine request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "routines_unavailable",
                    "message": "Routines couldn't be read or saved. Try again.",
                }

        return handle

    async def _routines_list(self, sid, principal, request):
        return {"ok": True, "routines": self.service.require().list()}

    async def _routines_tools(self, sid, principal, request):
        return {"ok": True, "tools": self.service.tool_list()}

    async def _routines_save(self, sid, principal, request):
        routine = await self.service.save(
            request.name, request.trigger, request.steps, routine_id=request.id,
            enabled=request.enabled,
        )
        return {"ok": True, "routine": routine}

    async def _routines_delete(self, sid, principal, request):
        return {"ok": True, "deleted": await self.service.delete(request.id)}

    async def _routines_toggle(self, sid, principal, request):
        return {"ok": True, "routine": await self.service.set_enabled(request.id, request.enabled)}

    async def _routines_run(self, sid, principal, request):
        routine = self.service.require().get(request.id)
        if routine is None:
            raise ServiceError("routine_not_found", "That routine is gone.")

        async def approve(payload):
            await self.app.sio.emit("tool_confirmation_request", payload, room=sid)

        self.service.start(routine, origin="manual", principal=principal,
                           request_approval=approve, origin_sid=sid)
        return {"ok": True, "started": routine["id"]}
