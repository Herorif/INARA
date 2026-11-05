"""Tray voice device contracts (J2): the saved choice and the core's device list.

A device is identified by its name and host API (``Windows WASAPI``), never by an index,
which changes as devices come and go. ``"default"`` follows the system default device.
Pure models: importing this module loads no audio library.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, TypeAdapter
from pydantic import ValidationError

# Printable text only (device names come from the OS and are shown on screen).
PRINTABLE = r"^[^\x00-\x1f\x7f]+$"
NAME_LIMIT = 200
HOST_API_LIMIT = 64
DEVICE_LIMIT = 64
SYSTEM_DEFAULT = "default"
LOCAL_DEVICE_KEYS = {"microphone": "local_microphone", "speaker": "local_speaker"}


class AudioDeviceChoice(BaseModel):
    """A specific microphone or speaker, as saved in ``voice.local_microphone`` / ``local_speaker``."""

    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=NAME_LIMIT, pattern=PRINTABLE)
    host_api: StrictStr = Field(min_length=1, max_length=HOST_API_LIMIT, pattern=PRINTABLE)


DeviceSelection = AudioDeviceChoice | Literal["default"]
_SELECTION = TypeAdapter(DeviceSelection)


class AudioDevicesRequest(BaseModel):
    """``audio_devices`` takes no fields."""

    model_config = ConfigDict(extra="forbid")


class AudioDeviceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=NAME_LIMIT, pattern=PRINTABLE)
    host_api: StrictStr = Field(min_length=1, max_length=HOST_API_LIMIT, pattern=PRINTABLE)
    # The host API's default device (what "System default" uses right now).
    default: StrictBool
    channels: StrictInt = Field(ge=1, le=64)
    sample_rate: StrictInt = Field(ge=8000, le=384000)


class AudioDevicesReport(BaseModel):
    """The core's device list for the tray voice Preferences section."""

    model_config = ConfigDict(extra="forbid")
    # False when the audio library is missing or the audio system could not be read.
    available: StrictBool
    code: StrictStr | None = Field(max_length=64)
    message: StrictStr | None = Field(max_length=500)
    host_api: StrictStr | None = Field(max_length=HOST_API_LIMIT)
    inputs: list[AudioDeviceEntry] = Field(max_length=DEVICE_LIMIT)
    outputs: list[AudioDeviceEntry] = Field(max_length=DEVICE_LIMIT)


def local_devices(settings):
    """Saved tray voice devices, ``{"microphone": ..., "speaker": ...}``.

    Each value is ``"default"`` or ``{"name", "host_api"}``; a missing or stale value on
    disk reads as ``"default"`` (settings files are never migrated on startup).
    """
    voice = (settings or {}).get("voice")
    voice = voice if isinstance(voice, dict) else {}
    result = {}
    for kind, key in LOCAL_DEVICE_KEYS.items():
        try:
            value = _SELECTION.validate_python(voice.get(key, SYSTEM_DEFAULT))
        except ValidationError:
            value = SYSTEM_DEFAULT
        result[kind] = value.model_dump() if isinstance(value, AudioDeviceChoice) else value
    return result
