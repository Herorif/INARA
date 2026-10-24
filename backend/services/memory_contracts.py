"""Strict owner-reviewed project memory contracts; no automatic extraction."""

import uuid
from typing import Annotated, Literal
from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator
from services.settings import EmptyRequest


class MemoryQuery(EmptyRequest):
    query: StrictStr = Field(default="", max_length=500)
    include_archived: StrictBool = False


class MemoryWrite(EmptyRequest):
    revision: uuid.UUID
    id: uuid.UUID
    title: StrictStr = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=4000)
    category: Literal["preference", "fact", "decision"] = "fact"
    source: StrictStr = Field(default="Owner entered", min_length=1, max_length=200)
    tags: list[Annotated[StrictStr, Field(min_length=1, max_length=32)]] = Field(
        default_factory=list, max_length=8
    )
    retention_days: Annotated[StrictInt, Field(ge=1, le=365)] = 90
    assistant_enabled: StrictBool = False
    archived: StrictBool = False

    @field_validator("title", "text", "source")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Enter readable text.")
        return value.strip()


class MemoryRevision(EmptyRequest):
    revision: uuid.UUID


class MemoryForget(MemoryRevision):
    id: uuid.UUID


class MemoryRetention(MemoryRevision):
    days: Annotated[StrictInt, Field(ge=1, le=365)]


class MemoryRestore(EmptyRequest):
    backup: StrictStr = Field(min_length=1, max_length=3_000_000)


class MemoryRestoreApply(MemoryRevision):
    preview_id: uuid.UUID


class MemorySource(EmptyRequest):
    id: uuid.UUID
    title: str
    source: str
    version: int
