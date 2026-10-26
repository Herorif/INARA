"""Validated local desktop/device adapters shared by text and direct routes."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from core.event_bus import event_owner
from services.tools import ServiceError, ToolSpec


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LaunchApp(NoArguments):
    name: StrictStr = Field(min_length=1, max_length=200)


class Screenshot(NoArguments):
    prompt: StrictStr | None = Field(default=None, min_length=1, max_length=2000)


class ControlDevice(NoArguments):
    device_id: StrictStr = Field(min_length=1, max_length=200)
    action: Literal["turn_on", "turn_off", "toggle", "set"]
    brightness: StrictInt | None = Field(default=None, ge=0, le=100)
    color: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    temperature: float | None = Field(
        default=None, ge=-50, le=100, allow_inf_nan=False, strict=True
    )


ACTION_MODELS = {
    "launch_app": LaunchApp,
    "take_screenshot": Screenshot,
    "read_clipboard": NoArguments,
    "get_system_info": NoArguments,
    "list_all_devices": NoArguments,
    "control_device": ControlDevice,
}


class LocalActions:
    def __init__(self, dispatcher, desktop, devices):
        self.desktop, self.devices = desktop, devices
        for name, model in ACTION_MODELS.items():

            async def execute(args, context, action=name):
                # Stamp even emit_nowait events at creation, before any delayed delivery.
                token = event_owner.set(context["principal"])
                try:
                    agent = (
                        self.devices
                        if action in ("list_all_devices", "control_device")
                        else self.desktop
                    )
                    payload = args.model_dump(exclude_none=True)
                    result = await agent.handle_tool_call(action, payload)
                    if not result.success:
                        data = getattr(result, "data", None) or {}
                        if action == "launch_app" and "suggestions" in data:
                            raise ServiceError("app_not_found", result.message)
                        raise ServiceError(
                            "action_failed",
                            "The local action could not complete. Check capability setup.",
                        )
                    return {
                        "success": True,
                        "message": result.message,
                        "data": getattr(result, "data", {}),
                    }
                finally:
                    event_owner.reset(token)

            dispatcher.register(
                ToolSpec(
                    name,
                    f"Local {name.replace('_', ' ')} action.",
                    model,
                    execute,
                    execution_timeout=30,
                    review=self.review_launch if name == "launch_app" else None,
                )
            )

    def resolved_launch(self, name):
        from desktop.app_registry import AppResolutionError

        try:
            return self.desktop.describe_launch(name)
        except AppResolutionError as exc:
            raise ServiceError("app_not_found", str(exc)) from exc

    def review_launch(self, args, context):
        # The approval shows exactly what will run, not only the requested name.
        return {"will_run": self.resolved_launch(args.name)}
