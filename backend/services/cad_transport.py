"""Narrow acknowledged CAD RPCs; all build authorization uses the common dispatcher."""

import asyncio
from pydantic import ValidationError
from services.cad import BuildRequest, JobRequest, ArtifactRequest, PlanRequest, plan_recipe
from services.storage import StorageError
from services.tools import ServiceError


class CadTransport:
    def __init__(self, sio, service, dispatcher, context):
        self.sio, self.service, self.dispatcher, self.context = sio, service, dispatcher, context
        self.approvals, self.planning = {}, {}
        for name in (
            "cad_submit",
            "cad_cancel",
            "cad_list",
            "cad_artifact",
            "cad_plan",
            "cad_close",
        ):
            sio.on(name, handler=self.guard(getattr(self, name)))

    def guard(self, operation):
        async def handle(sid, data=None):
            try:
                context = self.context(sid)
                if not self.dispatcher.authenticated(context["principal"]):
                    raise ServiceError("authentication_required", "Authentication is required.")
                return {"ok": True, **await operation(sid, data, context)}
            except (ServiceError, StorageError, ValidationError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "invalid_arguments"),
                    "message": str(exc)
                    if isinstance(exc, (ServiceError, StorageError))
                    else "Check dimensions, wall thickness and request ID.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "cad_failed",
                    "message": "The Studio action could not complete. Existing artifacts were preserved.",
                }

        return handle

    async def cad_submit(self, sid, data, context):
        args = BuildRequest.model_validate(data)
        key = (context["principal"], str(args.request_id))
        if key in self.approvals:
            raise ServiceError("request_uncertain", "This build is already awaiting approval.")
        confirmation_id = None

        async def approve(payload):
            nonlocal confirmation_id
            if key in self.approvals:
                raise ServiceError("request_uncertain", "This build is already awaiting approval.")
            self.approvals[key] = payload["id"]
            confirmation_id = payload["id"]
            await self.sio.emit(
                "cad_job",
                {
                    "request_id": str(args.request_id),
                    "project": context["project_path"].name,
                    "recipe": args.model_dump(mode="json", exclude={"request_id"}),
                    "state": "approval",
                    "phase": "awaiting_approval",
                },
                room=sid,
            )
            await self.sio.emit(
                "tool_confirmation_request",
                {**payload, "project": context["project_path"].name},
                room=sid,
            )

        try:
            result = await self.dispatcher.dispatch(
                context["principal"], "generate_cad", args.model_dump(mode="json"), context, approve
            )
            return {"job": result}
        finally:
            if confirmation_id and self.approvals.get(key) == confirmation_id:
                self.approvals.pop(key, None)

    async def cad_cancel(self, sid, data, context):
        args = JobRequest.model_validate(data)
        key = (context["principal"], str(args.request_id))
        confirmation = self.approvals.get(key)
        if confirmation:
            self.dispatcher.resolve(context["principal"], confirmation, False)
            return {
                "job": {
                    "request_id": str(args.request_id),
                    "state": "cancelled",
                    "phase": "cancelled",
                    "project": context["project_path"].name,
                }
            }
        return {
            "job": await self.service.cancel(
                context["principal"], context["project_path"], args.request_id
            )
        }

    async def cad_list(self, sid, data, context):
        return {"jobs": self.service.list(context["principal"], context["project_path"])}

    async def cad_close(self, sid, data, context):
        await self.stop_owner(context["principal"])
        return {}

    async def cad_artifact(self, sid, data, context):
        return {
            "artifact": self.service.artifact(
                context["principal"], context["project_path"], ArtifactRequest.model_validate(data)
            )
        }

    async def cad_plan(self, sid, data, context):
        args = PlanRequest.model_validate(data)
        owner = context["principal"]
        if self.planning:
            raise ServiceError("planner_busy", "A blueprint request is already running.")
        self.planning[owner] = asyncio.current_task()
        try:
            return {"recipe": await plan_recipe(args.prompt)}
        finally:
            self.planning.pop(owner, None)

    async def stop_owner(self, owner):
        for (principal, _), confirmation in tuple(self.approvals.items()):
            if owner == principal:
                self.dispatcher.resolve(owner, confirmation, False)
        task = self.planning.get(owner)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.service.cancel_owner(owner)

    async def close(self):
        for (principal, _), confirmation in tuple(self.approvals.items()):
            self.dispatcher.resolve(principal, confirmation, False)
        for task in tuple(self.planning.values()):
            task.cancel()
        await asyncio.gather(*tuple(self.planning.values()), return_exceptions=True)
        await self.service.close()
