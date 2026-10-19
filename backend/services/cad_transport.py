"""CAD-specific contract and optional proposal RPC over the shared creative transport."""

import asyncio
from services.cad import BuildRequest, ArtifactRequest, PlanRequest, plan_recipe, blender_executable
from services.cad_changes import ChangeSet, ChangePrompt, apply_changes, propose_changes
from services.creative_transport import CreativeTransport
from services.tools import ServiceError, ToolSpec


class CadTransport(CreativeTransport):
    prefix = "cad"
    tool = "generate_cad"
    request_model = BuildRequest
    artifact_model = ArtifactRequest
    operations = (*CreativeTransport.operations, "plan", "review_changes", "plan_changes")

    def capabilities(self):
        return {
            "blender": bool(blender_executable()),
            "max_objects": 8,
            "engineering_kernel": False,
            "kernel_reason": "Holes, fillets, booleans and STEP require a separately validated engineering adapter. No kernel is enabled.",
        }

    def __init__(
        self, *args, planner=plan_recipe, change_planner=propose_changes, authorize=None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.planner, self.authorize = planner, authorize
        self.change_planner = change_planner
        self.dispatcher.register(
            ToolSpec(
                "plan_cad_changes",
                "Propose a bounded change set against an explicit saved revision for review.",
                ChangePrompt,
                self.execute_change_plan,
                execution_timeout=40,
                permission="generate_cad",
                model_visible=False,
            )
        )
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

    def review(self, args, context):
        base = self.service.require_revision(
            context["principal"],
            context["project_path"],
            args.base_request_id,
            args.base_fingerprint,
        )
        recipe = apply_changes(base, args.edits)
        return {"proposal": {**args.model_dump(mode="json"), "recipe": recipe}}

    async def review_changes(self, sid, data, context):
        return self.review(ChangeSet.model_validate(data), context)

    async def execute_change_plan(self, args, context):
        if self.authorize:
            self.authorize(context)
        self.service.governor.require_heavy()
        owner, task = context["principal"], asyncio.current_task()
        if self.planning and task not in self.planning.values():
            raise ServiceError("planner_busy", "A proposal request is already running.")
        owns = owner not in self.planning
        if owns:
            self.planning[owner] = task
        try:
            base = self.service.require_revision(
                owner, context["project_path"], args.base_request_id, args.base_fingerprint
            )
            edits = await self.change_planner(args.prompt, base)
            if self.authorize:
                self.authorize(context)
            return self.review(
                ChangeSet(
                    base_request_id=args.base_request_id,
                    base_fingerprint=args.base_fingerprint,
                    edits=edits.edits,
                ),
                context,
            )
        finally:
            if owns:
                self.planning.pop(owner, None)

    async def plan_changes(self, sid, data, context):
        args = ChangePrompt.model_validate(data)
        if self.planning:
            raise ServiceError("planner_busy", "A proposal request is already running.")
        owner = context["principal"]
        self.planning[owner] = asyncio.current_task()

        async def approve(payload):
            await self.sio.emit("tool_confirmation_request", payload, room=sid)

        try:
            return await self.dispatcher.dispatch(
                owner, "plan_cad_changes", args.model_dump(mode="json"), context, approve
            )
        finally:
            self.planning.pop(owner, None)

    # Preserve the existing direct test/adapter contract.
    cad_submit = CreativeTransport.submit
    cad_cancel = CreativeTransport.cancel
    cad_list = CreativeTransport.list
    cad_artifact = CreativeTransport.artifact
    cad_close = CreativeTransport.close_panel
    cad_plan = plan
