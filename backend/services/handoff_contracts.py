"""Project-local recipe references, never file paths or raw camera/image data."""

import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr


class CreativeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["cad", "image"]
    source_request_id: uuid.UUID
    source_fingerprint: StrictStr = Field(pattern="^[a-f0-9]{64}$")
    source_sha256: StrictStr = Field(pattern="^[a-f0-9]{64}$")


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["cad", "image"]
    source_request_id: uuid.UUID
    source_fingerprint: StrictStr = Field(pattern="^[a-f0-9]{64}$")
    destination: Literal["cad", "image"]


class HandoffDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: StrictStr = Field(min_length=1, max_length=255)
    destination: Literal["cad", "image"]
    reference: CreativeReference
    source_name: StrictStr = Field(min_length=1, max_length=60)
    name: StrictStr = Field(min_length=1, max_length=60)
    prompt: StrictStr = Field(min_length=3, max_length=2000)
    metadata_only: Literal[True] = True
