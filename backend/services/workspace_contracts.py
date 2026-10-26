"""Bounded contracts for retained desktop memory and creative events."""

from pathlib import PureWindowsPath
from pydantic import Field, StrictStr, field_validator, model_validator
from services.settings import EmptyRequest


class PromptRequest(EmptyRequest):
    prompt: StrictStr = Field(min_length=1, max_length=8000)

    @field_validator("prompt")
    @classmethod
    def readable(cls, value):
        if not value.strip():
            raise ValueError("Enter a prompt.")
        return value.strip()


class TranscriptMessage(EmptyRequest):
    sender: StrictStr = Field(min_length=1, max_length=80)
    text: StrictStr = Field(max_length=20000)


class SaveMemory(EmptyRequest):
    filename: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    messages: list[TranscriptMessage] = Field(min_length=1, max_length=200)

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value):
        if value is None:
            return value
        path = PureWindowsPath(value)
        if (
            path.name != value
            or path.drive
            or path.root
            or any(c in value for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in value)
            or value.endswith((".", " "))
            or value.split(".", 1)[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(10)],
                *[f"LPT{i}" for i in range(10)],
            }
        ):
            raise ValueError("Use a plain memory filename.")
        return value

    @model_validator(mode="after")
    def bounded_transcript(self):
        if sum(len(m.text) + len(m.sender) for m in self.messages) > 200000:
            raise ValueError("Transcript exceeds the memory limit.")
        return self
