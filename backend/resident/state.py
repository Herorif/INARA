"""Metadata-only identity compatibility and desktop state, independent of Win32."""

import json
import os
import uuid
from pathlib import Path


class Identity:
    def __init__(self, profile):
        self.profile = Path(profile)
        self.path = self.profile / "resident-identity.json"
        self.owner = None
        self.gaming = False
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                self.owner = str(uuid.UUID(value["id"]))
                if type(value.get("gaming", False)) is not bool:
                    raise ValueError("Invalid preference")
                self.gaming = value.get("gaming", False)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(
                    "Resident identity needs recovery; preserve the existing profile."
                ) from exc

    def register(self, owner):
        owner = str(uuid.UUID(owner))
        if self.owner and self.owner != owner:
            raise ValueError("Workspace identity does not match this resident.")
        if not self.owner:
            self.owner = owner
            self.save()
        return owner

    def save(self):
        self.profile.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{uuid.uuid4()}.tmp")
        try:
            temporary.write_text(
                json.dumps({"id": self.owner, "gaming": self.gaming}), encoding="utf-8"
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


VOICE_STATES = {
    "connecting": "Connecting",
    "listening": "Listening",
    "thinking": "Thinking",
    "working": "Working",
    "speaking": "Speaking",
}
MICROPHONE = {"on": "mic on", "paused": "mic paused while JARVIS speaks", "off": "mic off"}
WAKE = {
    "listening": 'Listening for "Hey Jarvis"',
    "paused": '"Hey Jarvis" paused',
    "unavailable": '"Hey Jarvis" unavailable',
}
TOOLTIP_LIMIT = 127  # NOTIFYICONDATA's tip holds 128 characters with the terminator
# The tray's state icons: assets/icons/tray/jarvis-<state>.ico.
TRAY_ICONS = ("ready", "talking", "calls", "attention", "paused")


def tray_icon(phase, error, gaming, talking, calls):
    """The tray icon for the resident's state, highest priority first: "attention" (the core
    failed or an error is shown), "paused" (gaming mode, starting or stopping), "talking"
    (tray voice is active), "calls" (calls.enabled), otherwise "ready"."""
    if phase == "failed" or error:
        return "attention"
    if gaming or phase in ("starting", "stopping"):
        return "paused"
    if talking:
        return "talking"
    if calls:
        return "calls"
    return "ready"


class State:
    def __init__(self, identity):
        self.identity = identity
        self.phase, self.visible, self.error = "starting", False, None
        self.hotkey = False
        self.quitting = False
        # Tray voice, as the core reports it: {"active", "state", "microphone", "notice"}.
        self.voice = None
        # "Hey Jarvis", as the core reports it: {"setting", "state", "message"}.
        self.wake = None
        # calls.enabled, as the core reports it (off until it does).
        self.calls = False

    def tooltip(self):
        """The tray tooltip: resident status (with "Hey Jarvis" while that setting is on),
        or tray voice state with the microphone; at most 127 characters."""
        base = (
            "Core unavailable"
            if self.phase == "failed"
            else "Gaming mode"
            if self.identity.gaming
            else "Workspace open"
            if self.visible
            else "Native resident"
        )
        voice = self.voice or {}
        notice = voice.get("notice")
        if voice.get("active"):
            parts = [
                VOICE_STATES.get(voice.get("state"), "Listening"),
                MICROPHONE.get(voice.get("microphone"), "mic on"),
            ]
        else:
            parts = [base]
            wake = self.wake or {}
            if wake.get("setting") and self.phase != "failed" and wake.get("state") in WAKE:
                parts.append(WAKE[wake["state"]])
        if notice:
            parts.append(notice)
        return ("JARVIS · " + " · ".join(parts))[:TOOLTIP_LIMIT]

    def icon(self):
        """The tray icon name for the current state (see ``tray_icon``)."""
        return tray_icon(
            self.phase,
            self.error,
            self.identity.gaming,
            bool((self.voice or {}).get("active")),
            self.calls,
        )

    def snapshot(self):
        return {
            "phase": self.phase,
            "visible": self.visible,
            "gaming": self.identity.gaming,
            "error": self.error,
            "hotkeyReady": self.hotkey,
            "host": "native-windows",
        }

    def mode(self, value):
        if type(value) is not bool:
            raise ValueError("Gaming preference must be boolean")
        self.identity.gaming = value
        if self.identity.owner:
            self.identity.save()

    def resource_state(self):
        return "gaming" if self.identity.gaming else "chat" if self.visible else "resident"
