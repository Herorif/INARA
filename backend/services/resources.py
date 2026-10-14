"""Explicit desktop resource policy; heavy adapters remain on-demand."""

import asyncio
from typing import Literal
from pydantic import BaseModel, ConfigDict
from services.tools import ServiceError


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["resident", "chat", "studio", "gaming"]


class ResourceGovernor:
    def __init__(self):
        self.state = "chat"
        self.creative_active = {}
        self.creative_lock = asyncio.Lock()

    def select(self, state):
        self.state = state
        return self.snapshot()

    def require_heavy(self):
        if self.state in ("resident", "gaming"):
            raise ServiceError(
                "resource_policy", "Open Studio and leave gaming mode to use this capability."
            )
        self.state = "studio"

    def snapshot(self):
        return {
            "state": self.state,
            "heavy_allowed": self.state in ("chat", "studio"),
            "camera_frame_interval_ms": 500,
            "automatic_game_detection": False,
        }
