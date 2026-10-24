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


class StopWatching(NoArguments):
    watch_id: StrictStr = Field(min_length=1, max_length=100)


ACTION_MODELS = {
    "launch_app": LaunchApp,
    "take_screenshot": Screenshot,
    "read_clipboard": NoArguments,
    "get_system_info": NoArguments,
    "list_all_devices": NoArguments,
    "control_device": ControlDevice,
    "stop_watching": StopWatching,
}


class LocalActions:
    def __init__(self, dispatcher, desktop, devices, vision, vision_loop):
        self.desktop, self.devices, self.vision, self.vision_loop = (
            desktop,
            devices,
            vision,
            vision_loop,
        )
        for name, model in ACTION_MODELS.items():

            async def execute(args, context, action=name):
                # Stamp even emit_nowait events at creation, before any delayed delivery.
                token = event_owner.set(context["principal"])
                try:
                    agent = (
                        self.devices
                        if action in ("list_all_devices", "control_device")
                        else (self.vision if action == "stop_watching" else self.desktop)
                    )
                    payload = args.model_dump(exclude_none=True)
                    result = await agent.handle_tool_call(action, payload)
                    if not result.success:
                        raise ServiceError(
                            "action_failed",
                            "The local action could not complete. Check capability setup.",
                        )
                    value = {
                        "success": True,
                        "message": result.message,
                        "data": getattr(result, "data", {}),
                    }
                    if action == "stop_watching":
                        value["watches"] = self.vision_loop.list_watches()
                    return value
                finally:
                    event_owner.reset(token)

            dispatcher.register(
                ToolSpec(
                    name,
                    f"Local {name.replace('_', ' ')} action.",
                    model,
                    execute,
                    execution_timeout=30,
                )
            )
