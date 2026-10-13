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


class State:
    def __init__(self, identity):
        self.identity = identity
        self.phase, self.visible, self.error = "starting", False, None
        self.hotkey = False
        self.quitting = False

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
