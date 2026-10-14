"""CAD-specific contract and optional proposal RPC over the shared creative transport."""

import asyncio
from services.cad import BuildRequest, ArtifactRequest, PlanRequest, plan_recipe, blender_executable
from services.creative_transport import CreativeTransport
from services.tools import ServiceError


class CadTransport(CreativeTransport):
    prefix = "cad"
    tool = "generate_cad"
    request_model = BuildRequest
    artifact_model = ArtifactRequest
    operations = (*CreativeTransport.operations, "plan")

    def capabilities(self):
        return {"blender": bool(blender_executable()), "max_objects": 8}

    async def plan(self, sid, data, context):
        args = PlanRequest.model_validate(data)
        owner = context["principal"]
        if self.planning:
            raise ServiceError("planner_busy", "A blueprint request is already running.")
        self.planning[owner] = asyncio.current_task()
        try:
            return {"recipe": await plan_recipe(args.prompt)}
        finally:
            self.planning.pop(owner, None)

    # Preserve the existing direct test/adapter contract.
    cad_submit = CreativeTransport.submit
    cad_cancel = CreativeTransport.cancel
    cad_list = CreativeTransport.list
    cad_artifact = CreativeTransport.artifact
    cad_close = CreativeTransport.close_panel
    cad_plan = plan
