"""CAD-specific contract and optional proposal RPC over the shared creative transport."""

import asyncio
from services.cad import BuildRequest, ArtifactRequest, PlanRequest, plan_recipe, blender_executable
from services.creative_transport import CreativeTransport
from services.tools import ServiceError, ToolSpec


class CadTransport(CreativeTransport):
    prefix = "cad"
    tool = "generate_cad"
    request_model = BuildRequest
    artifact_model = ArtifactRequest
    operations = (*CreativeTransport.operations, "plan")

    def capabilities(self):
        return {"blender": bool(blender_executable()), "max_objects": 8}

    def __init__(self, *args, planner=plan_recipe, authorize=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner, self.authorize = planner, authorize
        self.dispatcher.register(
            ToolSpec(
                "plan_cad",
                "Propose validated CAD dimensions for owner review; requires configured provider.",
                PlanRequest,
                self.execute_plan,
                execution_timeout=40,
                permission="generate_cad",
            )
        )

    async def execute_plan(self, args, context):
        if self.authorize:
            self.authorize(context)
        self.service.governor.require_heavy()
        owner, task = context["principal"], asyncio.current_task()
        if self.planning and task not in self.planning.values():
            raise ServiceError("planner_busy", "A blueprint request is already running.")
        owns = owner not in self.planning
        if owns:
            self.planning[owner] = task
        try:
            return await self.planner(args.prompt)
        finally:
            if owns:
                self.planning.pop(owner, None)

    async def plan(self, sid, data, context):
        args = PlanRequest.model_validate(data)
        owner = context["principal"]
        if self.authorize:
            self.authorize(context)
        if self.planning:
            raise ServiceError("planner_busy", "A blueprint request is already running.")
        self.planning[owner] = asyncio.current_task()

        async def approve(payload):
            await self.sio.emit("tool_confirmation_request", payload, room=sid)

        try:
            return {
                "recipe": await self.dispatcher.dispatch(
                    owner, "plan_cad", args.model_dump(), context, approve
                )
            }
        finally:
            self.planning.pop(owner, None)

    # Preserve the existing direct test/adapter contract.
    cad_submit = CreativeTransport.submit
    cad_cancel = CreativeTransport.cancel
    cad_list = CreativeTransport.list
    cad_artifact = CreativeTransport.artifact
    cad_close = CreativeTransport.close_panel
    cad_plan = plan
