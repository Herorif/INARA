"""Immutable creative revision references shared by CAD and images."""

import hashlib
import json
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator


def recipe_fingerprint(recipe):
    def canonical(value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return value

    raw = json.dumps(
        canonical(recipe), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


class RevisionParent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_request_id: uuid.UUID | None = None
    base_fingerprint: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def paired_reference(self):
        if (self.base_request_id is None) != (self.base_fingerprint is None):
            raise ValueError("Supply both base revision ID and fingerprint, or neither")
        return self
