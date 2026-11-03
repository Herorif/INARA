"""Validated settings updates, independently authorized by the desktop transport."""

import copy
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from services.live_config import PREBUILT_VOICES, VOICE_DEFAULTS, VOICE_MODES
from services.tools import DEFAULT_DENY_PERMISSIONS, ServiceError

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
        "get_device_state",
        "generate_cad_prototype",
    }
)
PermissionValue = StrictBool | Literal["deny", "allow_within_scope"]

logger = logging.getLogger(__name__)
RECOVERY_ERROR_CODE = "settings_recovery_required"
_recovery_lock = threading.Lock()
# Resolved settings paths whose on-disk content failed to load this process.
# Saves to them stay refused until restart so the user's file is never clobbered.
_recovery_paths: dict[str, Path | None] = {}


def _path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def recovery_backup(path):
    """Return (blocked, backup_path) for a settings file in recovery mode."""
    with _recovery_lock:
        key = _path_key(path)
        return key in _recovery_paths, _recovery_paths.get(key)


def _backup_corrupt_file(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = path.with_name(f"{path.name}.corrupt-{stamp}")
    candidate, index = base, 1
    while True:
        try:
            # Exclusive create: never overwrite an existing backup.
            with open(candidate, "xb") as target, open(path, "rb") as source:
                shutil.copyfileobj(source, target)
            return candidate
        except FileExistsError:
            candidate = base.with_name(f"{base.name}-{index}")
            index += 1


def load_settings_file(path, settings):
    """Merge a settings file into ``settings`` in place.

    Returns True when the file was loaded (or does not exist). On a read or
    parse failure the defaults in ``settings`` are left untouched, the bad
    file is copied to ``settings.json.corrupt-<timestamp>``, and saves to the
    path are blocked for the rest of the process.
    """
    path = Path(path)
    if not path.exists():
        return True
    try:
        with open(path, "r", encoding="utf-8") as stream:
            loaded = json.load(stream)
        if not isinstance(loaded, dict):
            raise ValueError("settings file must contain a JSON object")
    except Exception as exc:
        backup = None
        try:
            backup = _backup_corrupt_file(path)
        except Exception as backup_exc:  # Still block writes; the original stays put.
            logger.error("Could not back up unreadable settings file %s: %s", path, backup_exc)
        with _recovery_lock:
            _recovery_paths[_path_key(path)] = backup
        logger.warning(
            "Settings file %s could not be loaded (%s). Running with default settings; "
            "a copy was saved to %s. Settings changes will NOT be saved until INARA is "
            "restarted with a repaired settings file.",
            path, exc, backup or "(backup failed)",
        )
        print(
            f"[SERVER] WARNING: settings file {path} is unreadable ({exc}). Using defaults; "
            f"backup: {backup or 'failed'}. Settings saves are disabled until restart."
        )
        return False
    for key, value in loaded.items():
        if key == "tool_permissions" and isinstance(value, dict):
            settings.setdefault("tool_permissions", {}).update(value)
        else:
            settings[key] = value
    return True


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssistantSettings(EmptyRequest):
    """``assistant.*``: which AI is the brain, and how INARA addresses the owner."""

    brain: Literal["auto", "claude", "gemini"] | None = None
    # Printable text only: the name is placed in the system prompt.
    owner_name: StrictStr | None = Field(
        default=None, max_length=80, pattern=r"^[^\x00-\x1f\x7f<>{}\[\]]*$"
    )

    @field_validator("brain", "owner_name", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @field_validator("owner_name")
    @classmethod
    def trim(cls, value):
        return " ".join(value.split())

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose an assistant setting to update.")
        return self


ASSISTANT_DEFAULTS = {"brain": "auto", "owner_name": ""}


class VoiceSettings(EmptyRequest):
    """``voice.*``: the Live prebuilt voice and the default talk mode."""

    name: Literal[PREBUILT_VOICES] | None = None
    mode: Literal[VOICE_MODES] | None = None

    @field_validator("name", "mode", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a voice setting to update.")
        return self


class QuietHours(EmptyRequest):
    """Local time window (Asia/Kuala_Lumpur) with no calls to third parties."""

    start: StrictStr = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    end: StrictStr = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class CallsSettings(EmptyRequest):
    """``calls.*``: the telephony gateway (docs/CALL_ROUTING.md). Off by default."""

    enabled: StrictBool | None = None
    # The Cloudflare tunnel hostname Twilio calls, e.g. https://calls.example.com.
    public_base_url: StrictStr | None = Field(
        default=None,
        max_length=253,
        pattern=r"^(|https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+)$",
    )
    quiet_hours: QuietHours | None = None
    daily_outbound_cap: StrictInt | None = Field(default=None, ge=0, le=100)
    number_cooldown_minutes: StrictInt | None = Field(default=None, ge=0, le=10080)
    when_disabled: Literal["voicemail", "hangup"] | None = None
    # Owner-approved facts the call agent may share with callers (C2). Printable text and
    # line breaks only: it is placed in the call agent's system instruction.
    facts: StrictStr | None = Field(
        default=None, max_length=1000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"
    )
    # The optional owner-briefing PIN is not a setting: it lives in the encrypted secret
    # store as call_briefing_pin (C3), so a briefing_pin key here is rejected (extra field).
    max_call_minutes: StrictInt | None = Field(default=None, ge=2, le=30)
    # C3: when to phone the owner about a screened call (only while away from the PC).
    brief_by_phone: Literal["off", "urgent", "needs_owner"] | None = None

    @field_validator(
        "enabled",
        "public_base_url",
        "quiet_hours",
        "daily_outbound_cap",
        "number_cooldown_minutes",
        "when_disabled",
        "facts",
        "max_call_minutes",
        "brief_by_phone",
        mode="before",
    )
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a calls setting to update.")
        return self


CALLS_DEFAULTS = {
    "enabled": False,
    "public_base_url": "",
    "quiet_hours": {"start": "21:00", "end": "09:00"},
    "daily_outbound_cap": 10,
    "number_cooldown_minutes": 60,
    "when_disabled": "voicemail",
    "facts": "",
    "max_call_minutes": 10,
    "brief_by_phone": "urgent",
}


class SettingsPatch(EmptyRequest):
    tool_permissions: dict[StrictStr, PermissionValue] | None = Field(default=None, max_length=128)
    face_auth_enabled: StrictBool | None = None
    camera_flipped: StrictBool | None = None
    assistant: AssistantSettings | None = None
    voice: VoiceSettings | None = None
    calls: CallsSettings | None = None

    @field_validator(
        "tool_permissions",
        "face_auth_enabled",
        "camera_flipped",
        "assistant",
        "voice",
        "calls",
        mode="before",
    )
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
        blocked, backup = recovery_backup(self.path)
        if blocked:
            raise ServiceError(
                RECOVERY_ERROR_CODE,
                "Settings file could not be loaded at startup, so changes are not saved "
                "to protect it. Repair or restore it"
                + (f" (a copy is at {backup.name})" if backup else "")
                + " and restart INARA.",
            )
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
        self.permission_names = (
            frozenset(permission_names) | LEGACY_PERMISSION_NAMES | DEFAULT_DENY_PERMISSIONS
        )

    def snapshot(self):
        return copy.deepcopy(self.settings)

    def apply(self, request):
        patch = request.model_dump(exclude_unset=True)
        permissions = patch.get("tool_permissions", {})
        if set(permissions) - self.permission_names:
            raise ServiceError("invalid_arguments", "Unknown tool permission name.")
        candidate = self.snapshot()
        candidate.setdefault("tool_permissions", {}).update(permissions)
        for section, defaults in (
            ("assistant", ASSISTANT_DEFAULTS),
            ("voice", VOICE_DEFAULTS),
            ("calls", CALLS_DEFAULTS),
        ):
            if section in patch:
                current = candidate.get(section)
                candidate[section] = {
                    **defaults,
                    **(current if isinstance(current, dict) else {}),
                    **patch[section],
                }
        candidate.update(
            {
                key: value
                for key, value in patch.items()
                if key not in ("tool_permissions", "assistant", "voice", "calls")
            }
        )
        try:
            self.store.save(candidate)
        except ServiceError:
            raise
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
