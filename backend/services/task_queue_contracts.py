"""Finite manually reviewed plans. No scripts, model plans or result interpolation."""

from typing import Annotated, Literal
import uuid
from pydantic import Field, StrictStr, model_validator
from services.settings import EmptyRequest


class ReadStep(EmptyRequest):
    tool: Literal["read_file"]
    path: StrictStr = Field(min_length=1, max_length=1024)


class WriteStep(EmptyRequest):
    tool: Literal["write_file"]
    path: StrictStr = Field(min_length=1, max_length=1024)
    content: StrictStr = Field(max_length=16000)


class LaunchStep(EmptyRequest):
    tool: Literal["launch_app"]
    name: Literal["notepad", "calculator", "paint", "explorer", "vscode"]


Step = Annotated[ReadStep | WriteStep | LaunchStep, Field(discriminator="tool")]


class TaskCreate(EmptyRequest):
    id: uuid.UUID
    title: StrictStr = Field(min_length=1, max_length=100)
    steps: list[Step] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json()) > 40000:
            raise ValueError("Keep the complete plan below 40,000 characters.")
        return self


class TaskReference(EmptyRequest):
    id: uuid.UUID
