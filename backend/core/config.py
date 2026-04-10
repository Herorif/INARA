"""
Centralized configuration management.

Single source of truth for all settings. Replaces scattered
settings.json loading and DEFAULT_SETTINGS dicts.
"""

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS = {
    "face_auth_enabled": False,
    "tool_permissions": {
        "generate_cad": True,
        "iterate_cad": True,
        "run_web_agent": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True,
        "list_smart_devices": True,
        "control_light": True,
        "discover_printers": True,
        "print_stl": True,
        "get_print_status": True,
        "make_phone_call": True,
        "end_phone_call": False,
        "get_call_status": False,
    },
    "printers": [],
    "kasa_devices": [],
    "camera_flipped": False,
    "voice": {
        "wake_word_enabled": False,
        "wake_timeout": 30,
        "greetings_enabled": True,
    },
    "telephony": {
        "provider": "none",     # "none" | "twilio" | "pjsip"
        "auto_answer": False,
        "twilio": {
            "account_sid": "",
            "auth_token": "",
            "phone_number": "",
            "webhook_base_url": "",
        },
        "pjsip": {
            "sip_server": "",
            "sip_username": "",
            "sip_password": "",
            "sip_port": 5060,
        },
    },
}


class Config:
    """Manages INARA's persistent configuration."""

    def __init__(self, settings_path: str | Path | None = None):
        if settings_path is None:
            # Default: backend/settings.json
            backend_dir = Path(__file__).parent.parent
            settings_path = backend_dir / "settings.json"
        self._path = Path(settings_path)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load settings from disk, merging with defaults."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
            except (json.JSONDecodeError, IOError):
                saved = {}
        else:
            saved = {}

        # Deep merge: defaults + saved
        self._data = self._deep_merge(DEFAULT_SETTINGS, saved)

    def _save(self):
        """Persist current settings to disk."""
        os.makedirs(self._path.parent, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=4)

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Recursively merge override into base."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value. Supports dotted keys: 'tool_permissions.generate_cad'."""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any, save: bool = True):
        """Set a config value. Supports dotted keys."""
        keys = key.split(".")
        target = self._data
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        if save:
            self._save()

    def update(self, updates: dict[str, Any], save: bool = True):
        """Merge a dict of updates into config."""
        self._data = self._deep_merge(self._data, updates)
        if save:
            self._save()

    @property
    def all(self) -> dict[str, Any]:
        """Return the full config dict (read-only copy)."""
        return dict(self._data)

    @property
    def tool_permissions(self) -> dict[str, bool]:
        return self._data.get("tool_permissions", {})

    @property
    def printers(self) -> list[dict]:
        return self._data.get("printers", [])

    @property
    def kasa_devices(self) -> list[dict]:
        return self._data.get("kasa_devices", [])

    @property
    def face_auth_enabled(self) -> bool:
        return self._data.get("face_auth_enabled", False)

    @property
    def camera_flipped(self) -> bool:
        return self._data.get("camera_flipped", False)

    @property
    def telephony_provider(self) -> str:
        return self._data.get("telephony", {}).get("provider", "none")
