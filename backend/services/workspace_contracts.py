"""Bounded contracts for retained desktop memory, media and creative events."""

import base64
import binascii
from pathlib import PureWindowsPath
from pydantic import (
    Field,
    StrictBool,
    StrictBytes,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
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


class UploadMemory(EmptyRequest):
    memory: StrictStr = Field(min_length=1, max_length=200000)


class StartAudio(EmptyRequest):
    device_index: StrictInt | None = Field(default=None, ge=0, le=1024)
    device_name: StrictStr | None = Field(default=None, max_length=256)
    muted: StrictBool = False


class VideoFrame(EmptyRequest):
    image: StrictStr | StrictBytes = Field(min_length=1, max_length=1400000)

    @field_validator("image")
    @classmethod
    def bounded_image(cls, value):
        try:
            raw = base64.b64decode(value, validate=True) if isinstance(value, str) else value
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Use a base64 encoded or binary image.") from exc
        if not 0 < len(raw) <= 1000000 or not raw.startswith(
            (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
        ):
            raise ValueError("Use a bounded JPEG or PNG frame.")
        return value

    def raw(self):
        return (
            base64.b64decode(self.image, validate=True)
            if isinstance(self.image, str)
            else self.image
        )
