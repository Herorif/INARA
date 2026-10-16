"""Validated settings updates, independently authorized by the desktop transport."""

import copy
import json
import os
from pathlib import Path
import tempfile
from typing import Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)
from services.tools import ServiceError

# Retained legacy panel/declaration names, until the R2c declaration migration.
LEGACY_PERMISSION_NAMES = frozenset(
    {
        "create_directory",
        "read_directory",
        "create_project",
        "switch_project",
        "list_projects",
        "list_smart_devices",
        "control_light",
        "discover_printers",
        "print_stl",
        "iterate_cad",
        "get_print_status",
        "run_web_agent",
        "create_routine",
        "list_routines",
        "list_running_apps",
        "focus_window",
        "search_files",
        "write_clipboard",
        "describe_camera",
        "detect_presence",
        "watch_for",
        "list_watches",
        "get_device_state",
        "generate_cad_prototype",
    }
)
PermissionValue = StrictBool | Literal["deny", "allow_within_scope"]


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsPatch(EmptyRequest):
    tool_permissions: dict[StrictStr, PermissionValue] | None = Field(default=None, max_length=128)
    face_auth_enabled: StrictBool | None = None
    camera_flipped: StrictBool | None = None

    @field_validator("tool_permissions", "face_auth_enabled", "camera_flipped", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a setting to update.")
        return self


class PermissionPatch(EmptyRequest):
    values: dict[StrictStr, PermissionValue] = Field(max_length=128)


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path) if path is not None else None

    def save(self, snapshot):
        if self.path is None:
            return  # Explicit in-memory dependency for isolated application roots.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(snapshot, stream, indent=4)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class SettingsService:
    def __init__(self, settings, store, permission_names, on_change=None):
        self.settings, self.store, self.on_change = settings, store, on_change
        self.permission_names = frozenset(permission_names) | LEGACY_PERMISSION_NAMES

    def snapshot(self):
        return copy.deepcopy(self.settings)

    def apply(self, request):
        patch = request.model_dump(exclude_unset=True)
        permissions = patch.get("tool_permissions", {})
        if set(permissions) - self.permission_names:
            raise ServiceError("invalid_arguments", "Unknown tool permission name.")
        candidate = self.snapshot()
        candidate.setdefault("tool_permissions", {}).update(permissions)
        candidate.update({key: value for key, value in patch.items() if key != "tool_permissions"})
        try:
            self.store.save(candidate)
        except Exception as exc:
            raise ServiceError(
                "settings_unavailable",
                "Settings could not be saved; previous settings were preserved.",
            ) from exc
        self.settings.clear()
        self.settings.update(candidate)
        if self.on_change:
            try:
                self.on_change(patch)
            except Exception as exc:
                raise ServiceError(
                    "settings_refresh_failed",
                    "Settings were saved, but an active integration needs restarting.",
                ) from exc
        return self.snapshot()
