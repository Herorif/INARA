"""Integer micro-USD authorization allowances, never floating point invoice claims."""

import uuid
from typing import Annotated
from pydantic import Field, StrictBool, StrictInt, model_validator
from services.settings import EmptyRequest

Money = Annotated[StrictInt, Field(ge=0, le=1_000_000_000_000)]


class UsagePolicy(EmptyRequest):
    revision: uuid.UUID
    enabled: StrictBool = False
    daily_microusd: Money = 0
    monthly_microusd: Money = 0
    per_call_microusd: Money = 0
    max_output_tokens: Annotated[StrictInt, Field(ge=256, le=16384)] = 4096

    @model_validator(mode="after")
    def nonzero_allowance(self):
        if self.enabled and self.per_call_microusd == 0:
            raise ValueError("Set a positive per-call allowance before enabling caps.")
        return self
