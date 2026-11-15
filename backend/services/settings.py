"""Validated settings updates, independently authorized by the desktop transport."""

import copy
from datetime import datetime
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from services.audio_contracts import DeviceSelection
from services.capability_profiles import MODEL_DEFAULTS
from services.live_config import PREBUILT_VOICES, VOICE_DEFAULTS, VOICE_MODES, WAKE_SENSITIVITIES
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
            "a copy was saved to %s. Settings changes will NOT be saved until JARVIS is "
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


class HomePlace(EmptyRequest):
    """``assistant.home_place``: the owner's home town for weather (docs/WEATHER.md)."""

    # Printable text only: the name can reach the brain's and the voice's context.
    name: StrictStr = Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f<>{}\[\]]*$")
    lat: float = Field(ge=-90, le=90, strict=True, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, strict=True, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def trim(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name the home town.")
        return value


def home_place(settings):
    """The saved ``assistant.home_place`` as a dict, or None (unset or stale)."""
    assistant = settings.get("assistant") if isinstance(settings, dict) else None
    saved = assistant.get("home_place") if isinstance(assistant, dict) else None
    if saved is None:
        return None
    try:
        return HomePlace.model_validate(saved).model_dump()
    except ValueError:
        return None


# The Claude brain models and efforts the owner can choose (llm/router.py, S2).
CLAUDE_MODELS = ("claude-sonnet-5-5", "claude-haiku-5-5")
EFFORTS = ("low", "medium", "high")
# Today's Gemini text model, without the JARVIS_TEXT_MODEL override (which wins in the router).
GEMINI_TEXT_DEFAULT = MODEL_DEFAULTS["text"][1]


class AssistantSettings(EmptyRequest):
    """``assistant.*``: which AI is the brain, how JARVIS addresses the owner, the
    owner's home town for weather (``home_place``: {name, lat, lon}, or null to clear),
    whether the Claude brain may search and fetch the web (``web_search``, default on), the
    Claude brain model (``claude_model``), its effort (``effort``: low, medium or high;
    xhigh and max are left out on purpose) and the Gemini text model (``gemini_model``) for
    a Gemini brain (docs/AI_PROVIDERS.md)."""

    brain: Literal["auto", "claude", "gemini"] | None = None
    # Printable text only: the name is placed in the system prompt.
    owner_name: StrictStr | None = Field(
        default=None, max_length=80, pattern=r"^[^\x00-\x1f\x7f<>{}\[\]]*$"
    )
    # How JARVIS addresses the owner (services/conversation.persona); "sir" by default.
    address: Literal["sir", "maam", "name", "none"] | None = None
    # Null is meaningful here: it clears the home town.
    home_place: HomePlace | None = None
    # Claude web search and web fetch (docs/AI_PROVIDERS.md); Gemini never searches.
    web_search: StrictBool | None = None
    claude_model: Literal[CLAUDE_MODELS] | None = None
    effort: Literal[EFFORTS] | None = None
    # A Gemini model id from the brain_models list; printable id characters only.
    gemini_model: StrictStr | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^gemini-[A-Za-z0-9._-]+$"
    )

    @field_validator(
        "brain", "owner_name", "address", "web_search", "claude_model", "effort",
        "gemini_model", mode="before",
    )
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


ASSISTANT_DEFAULTS = {
    "brain": "auto", "owner_name": "", "address": "sir", "home_place": None,
    "web_search": True, "claude_model": CLAUDE_MODELS[0], "effort": "medium",
    "gemini_model": GEMINI_TEXT_DEFAULT,
}


class VoiceSettings(EmptyRequest):
    """``voice.*``: the Live prebuilt voice, the default talk mode and the tray voice devices.

    ``local_microphone`` / ``local_speaker`` (J2) are ``"default"`` (the system default
    device) or ``{"name", "host_api"}``; an absent or stale saved value reads as
    ``"default"`` (services/audio_contracts.local_devices), and a saved device that is
    not connected falls back to the default when tray voice starts.

    ``wake_word`` (listen for "Hey Jarvis" from the tray, on by default) and
    ``wake_sensitivity`` read with their defaults when absent or stale
    (services/audio_contracts.wake_word_settings).

    ``overlay`` (J4, "Show JARVIS while you talk"): the small always-on-top window with the
    live core and captions during a tray voice session; on by default, and an absent or
    stale saved value reads as on (services/audio_contracts.overlay_settings).
    """

    name: Literal[PREBUILT_VOICES] | None = None
    mode: Literal[VOICE_MODES] | None = None
    local_microphone: DeviceSelection | None = None
    local_speaker: DeviceSelection | None = None
    wake_word: StrictBool | None = None
    wake_sensitivity: Literal[WAKE_SENSITIVITIES] | None = None
    overlay: StrictBool | None = None

    @field_validator(
        "name",
        "mode",
        "local_microphone",
        "local_speaker",
        "wake_word",
        "wake_sensitivity",
        "overlay",
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


class CalendarSettings(EmptyRequest):
    """``calendar.*``: what JARVIS may do with Google Calendar (docs/CALENDAR.md). Each
    switch acts only while the calendar is connected; all are on by default."""

    read_events: StrictBool | None = None
    share_free_busy: StrictBool | None = None
    add_events: StrictBool | None = None

    @field_validator("read_events", "share_free_busy", "add_events", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a calendar setting to update.")
        return self


CALENDAR_DEFAULTS = {"read_events": True, "share_free_busy": True, "add_events": True}

HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
BRIEFING_WINDOW_ORDER = "The morning briefing window must start before it ends."


class BriefingSettings(EmptyRequest):
    """``briefing.*``: the morning briefing (services/briefing_service.py). Times are local
    Malaysian HH:MM; the window starts before it ends (checked again on the merged value)."""

    enabled: StrictBool | None = None
    window_start: StrictStr | None = Field(default=None, pattern=HHMM)
    window_end: StrictStr | None = Field(default=None, pattern=HHMM)
    speak: StrictBool | None = None
    phone: StrictBool | None = None
    phone_time: StrictStr | None = Field(default=None, pattern=HHMM)

    @field_validator(
        "enabled", "window_start", "window_end", "speak", "phone", "phone_time", mode="before"
    )
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a morning briefing setting to update.")
        if self.window_start is not None and self.window_end is not None:
            if self.window_start >= self.window_end:
                raise ValueError(BRIEFING_WINDOW_ORDER)
        return self


BRIEFING_DEFAULTS = {
    "enabled": True,
    "window_start": "06:00",
    "window_end": "11:00",
    "speak": True,
    "phone": False,
    "phone_time": "07:30",
}


def briefing_settings(settings):
    """Validated ``briefing.*`` values with defaults: a stale or malformed saved value falls
    back to its default, and a saved window that does not start before it ends falls back to
    the default window."""
    saved = settings.get("briefing") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    values = {}
    for key, default in BRIEFING_DEFAULTS.items():
        value = saved.get(key)
        if isinstance(default, bool):
            values[key] = value if isinstance(value, bool) else default
        else:
            valid = isinstance(value, str) and re.fullmatch(HHMM, value)
            values[key] = value if valid else default
    if values["window_start"] >= values["window_end"]:
        values["window_start"] = BRIEFING_DEFAULTS["window_start"]
        values["window_end"] = BRIEFING_DEFAULTS["window_end"]
    return values


# --- Home Assistant (docs/HOME_ASSISTANT.md) -------------------------------------------------
# ``home_assistant.url`` is the server address; the long-lived access token is never a
# setting (it is the encrypted secret home_assistant_token). An old ``home_assistant.token``
# in settings.json is ignored and dropped the next time this section is saved.
HOME_ENTITY_ID = r"^[a-z0-9_]{1,64}\.[a-z0-9_]{1,190}$"
HomeAccess = Literal["can", "ask", "off"]
HomeEntityId = Annotated[StrictStr, StringConstraints(pattern=HOME_ENTITY_ID, max_length=255)]
HOME_ACCESS_LIMIT = 1000
HOME_URL_EXAMPLE = "http://homeassistant.local:8123"
HOME_URL_MESSAGE = f"Use the full address, for example {HOME_URL_EXAMPLE}."
_HOME_HOST = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_HOME_PATH = re.compile(r"^[A-Za-z0-9._~/-]*$")
# Names that only resolve on a home network (mDNS, router DNS, the RFC 8375 home zone).
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
_SHARED_SPACE = ipaddress.ip_network("100.64.0.0/10")  # carrier-grade NAT / Tailscale


def home_address_is_local(host):
    """True for addresses on the home network: private, loopback or link-local IPs, the
    100.64/10 shared space, single-label names and home-network suffixes such as .local."""
    host = (host or "").strip("[]").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES)
    if address.version == 4 and address in _SHARED_SPACE:
        return True
    return address.is_private or address.is_loopback or address.is_link_local


def home_assistant_url(value):
    """The normalised server address (scheme, host, port and optional path, no trailing
    slash or /api), or "" for blank. Raises ValueError with a plain message otherwise.
    http is accepted only for an address on the home network."""
    if not isinstance(value, str):
        raise ValueError(HOME_URL_MESSAGE)
    text = value.strip()
    if not text:
        return ""
    if len(text) > 300 or any(ord(char) < 33 or ord(char) == 127 for char in text):
        raise ValueError(HOME_URL_MESSAGE)
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise ValueError(HOME_URL_MESSAGE) from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        raise ValueError(
            f"Start the address with http:// or https://, for example {HOME_URL_EXAMPLE}."
        )
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("Use only the server address, without a sign-in name or anything after ?.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is None and not _HOME_HOST.fullmatch(host):
        raise ValueError(HOME_URL_MESSAGE)
    if not _HOME_PATH.fullmatch(parts.path):
        raise ValueError(HOME_URL_MESSAGE)
    if scheme == "http" and not home_address_is_local(host):
        raise ValueError("Use https for an address outside your home network.")
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    shown = f"[{host}]" if literal is not None and literal.version == 6 else host
    return f"{scheme}://{shown}{'' if port is None else ':' + str(port)}{path}"


class HomeAssistantSettings(EmptyRequest):
    """``home_assistant.*``: the server address and the owner's per-device access overrides
    (entity_id -> "can" | "ask" | "off"). ``access`` is replaced whole on each update; only
    overrides are stored (a device at its default has no entry)."""

    url: StrictStr | None = Field(default=None, max_length=300)
    access: dict[HomeEntityId, HomeAccess] | None = Field(
        default=None, max_length=HOME_ACCESS_LIMIT
    )

    @field_validator("url", "access", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @field_validator("url")
    @classmethod
    def address(cls, value):
        return home_assistant_url(value)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a Home Assistant setting to update.")
        return self


HOME_ASSISTANT_DEFAULTS = {"url": "", "access": {}}


def home_assistant_settings(settings):
    """Validated ``home_assistant.*`` with defaults: a stale or malformed URL reads as "",
    and malformed access entries are skipped. Never returns an old ``token`` key."""
    saved = settings.get("home_assistant") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    try:
        url = home_assistant_url(saved.get("url", ""))
    except ValueError:
        url = ""
    access = saved.get("access")
    access = [
        (key, value)
        for key, value in (access.items() if isinstance(access, dict) else ())
        if isinstance(key, str)
        and re.fullmatch(HOME_ENTITY_ID, key)
        and value in ("can", "ask", "off")
    ]
    return {"url": url, "access": dict(access[:HOME_ACCESS_LIMIT])}


def legacy_home_assistant_token(settings):
    """True while settings.json still has the old plaintext ``home_assistant.token``."""
    saved = settings.get("home_assistant") if isinstance(settings, dict) else None
    return isinstance(saved, dict) and "token" in saved


# --- World view (docs/WORLD_VIEW.md) ---------------------------------------------------------
# ``world.*`` runs the God's Eye View globe on this PC (services/world_view.py). ``root`` and
# ``node`` are full paths; a leading %USERPROFILE% is expanded when they are read. The port is
# loopback only and never the core's 8000.
WORLD_ROOT_DEFAULT = r"%USERPROFILE%\tools\gods-eye-view"
WORLD_NODE_DEFAULT = r"%USERPROFILE%\tools\node-v24.22.2-win-x64\node.exe"
WORLD_CORE_PORT = 8000
WORLD_PATH_MESSAGE = r"Use a full path, for example %USERPROFILE%\tools\gods-eye-view."
_USERPROFILE = re.compile(r"^%USERPROFILE%(?=[\\/]|$)", re.IGNORECASE)


def world_path(value):
    """The path with a leading %USERPROFILE% expanded. Raises ValueError unless it is a full
    path without control characters."""
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(WORLD_PATH_MESSAGE)
    text = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(WORLD_PATH_MESSAGE)
    home = os.environ.get("USERPROFILE") or str(Path.home())
    expanded = _USERPROFILE.sub(lambda _match: home, text)
    if "%" in expanded or not Path(expanded).is_absolute():
        raise ValueError(WORLD_PATH_MESSAGE)
    return expanded


def world_port(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise ValueError("Choose a port from 1024 to 65535.")
    if value == WORLD_CORE_PORT:
        raise ValueError("Port 8000 belongs to the JARVIS core. Choose another port.")
    return value


class WorldSettings(EmptyRequest):
    """``world.*``: where God's Eye View and Node 24 are, its loopback port, how long it may
    sit unused before it stops, and whether it may start at all."""

    root: StrictStr | None = Field(default=None, max_length=1024)
    node: StrictStr | None = Field(default=None, max_length=1024)
    port: StrictInt | None = None
    idle_minutes: StrictInt | None = Field(default=None, ge=1, le=1440)
    enabled: StrictBool | None = None

    @field_validator("root", "node", "port", "idle_minutes", "enabled", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @field_validator("root", "node")
    @classmethod
    def full_path(cls, value):
        world_path(value)
        return value.strip()

    @field_validator("node")
    @classmethod
    def program(cls, value):
        # Node runs directly (never a shell): a .cmd or .bat would need cmd.exe.
        if not value.lower().endswith(".exe"):
            raise ValueError("Point to node.exe itself.")
        return value

    @field_validator("port")
    @classmethod
    def loopback_port(cls, value):
        return world_port(value)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a World view setting to update.")
        return self


WORLD_DEFAULTS = {
    "root": WORLD_ROOT_DEFAULT,
    "node": WORLD_NODE_DEFAULT,
    "port": 4173,
    "idle_minutes": 10,
    "enabled": True,
}


def world_settings(settings):
    """Validated ``world.*`` with defaults and the paths expanded: a stale or malformed saved
    value falls back to its default."""
    saved = settings.get("world") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    values = {}
    for key in ("root", "node"):
        try:
            values[key] = world_path(saved.get(key))
        except ValueError:
            values[key] = world_path(WORLD_DEFAULTS[key])
    if not values["node"].lower().endswith(".exe"):
        values["node"] = world_path(WORLD_DEFAULTS["node"])
    try:
        values["port"] = world_port(saved.get("port"))
    except ValueError:
        values["port"] = WORLD_DEFAULTS["port"]
    minutes = saved.get("idle_minutes")
    valid = isinstance(minutes, int) and not isinstance(minutes, bool) and 1 <= minutes <= 1440
    values["idle_minutes"] = minutes if valid else WORLD_DEFAULTS["idle_minutes"]
    enabled = saved.get("enabled")
    values["enabled"] = enabled if isinstance(enabled, bool) else WORLD_DEFAULTS["enabled"]
    return values


# --- MCP servers (docs/MCP.md) -----------------------------------------------------------
# ``mcp.servers`` is the owner's list of local MCP servers (stdio). The command is an argv
# list run without a shell; env values are literals or {"secret": name}, a name in the
# encrypted SecretStore, so a secret value is never stored in settings.json or put in argv.
MCP_SERVER_ID = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
MCP_SECRET_NAME = r"^[a-z][a-z0-9_]{0,63}$"
MCP_ENV_NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"
MCP_SERVER_LIMIT = 32
McpPolicy = Literal["never_ask", "ask", "deny"]
McpServerId = Annotated[StrictStr, StringConstraints(pattern=MCP_SERVER_ID)]
McpEnvName = Annotated[StrictStr, StringConstraints(pattern=MCP_ENV_NAME)]
McpToolName = Annotated[
    StrictStr, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")
]
McpArgument = Annotated[StrictStr, StringConstraints(max_length=4096, pattern=r"^[^\x00\r\n]*$")]


class McpSecretRef(EmptyRequest):
    """An env value taken from the encrypted SecretStore at start (never from settings)."""

    secret: Annotated[StrictStr, StringConstraints(pattern=MCP_SECRET_NAME)]


class McpServerConfig(EmptyRequest):
    """One ``mcp.servers`` entry. ``policy`` maps a server tool name to never_ask, ask or
    deny; tools without an entry use ``default_policy`` ("ask")."""

    id: McpServerId
    name: StrictStr = Field(min_length=1, max_length=60, pattern=r"^[^\x00-\x1f\x7f<>{}]+$")
    command: list[McpArgument] = Field(min_length=1, max_length=64)
    cwd: StrictStr | None = Field(default=None, max_length=1024)
    env: dict[McpEnvName, McpArgument | McpSecretRef] = Field(default_factory=dict, max_length=64)
    enabled: StrictBool = True
    autostart: StrictBool = False
    timeout_s: StrictInt = Field(default=30, ge=1, le=600)
    idle_timeout_s: StrictInt = Field(default=600, ge=0, le=86_400)
    default_policy: McpPolicy = "ask"
    policy: dict[McpToolName, McpPolicy] = Field(default_factory=dict, max_length=500)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the server a name.")
        return value

    @field_validator("command")
    @classmethod
    def program(cls, value):
        if not value[0].strip():
            raise ValueError("Start the command with the program to run.")
        return value

    @field_validator("cwd")
    @classmethod
    def absolute(cls, value):
        if value is None:
            return None
        if "\x00" in value or not Path(value).is_absolute():
            raise ValueError("Use a full folder path for the working directory.")
        return value

    @field_validator("env")
    @classmethod
    def distinct_names(cls, value):
        # Windows environment names ignore case: PATH and Path are the same variable.
        if len({name.casefold() for name in value}) != len(value):
            raise ValueError("Each environment variable can be set only once.")
        return value


class McpSettings(EmptyRequest):
    """``mcp.*``: replaced whole on each save (services/mcp_registry.py)."""

    servers: list[McpServerConfig] = Field(max_length=MCP_SERVER_LIMIT)

    @field_validator("servers")
    @classmethod
    def unique_ids(cls, value):
        if len({server.id for server in value}) != len(value):
            raise ValueError("Each MCP server needs its own id.")
        return value


def mcp_server_configs(settings):
    """The validated ``mcp.servers``; a malformed entry (or a repeated id) is skipped."""
    saved = settings.get("mcp") if isinstance(settings, dict) else None
    servers = saved.get("servers") if isinstance(saved, dict) else None
    result, seen = [], set()
    for item in servers if isinstance(servers, list) else ():
        try:
            config = McpServerConfig.model_validate(item)
        except ValueError:
            # Pydantic details can include env literals: report the position only.
            logger.warning("An MCP server entry in settings is invalid and was skipped")
            continue
        if config.id not in seen and len(result) < MCP_SERVER_LIMIT:
            seen.add(config.id)
            result.append(config)
    return result


class DiagnosticsSettings(EmptyRequest):
    """``diagnostics.*`` (docs/DIAGNOSTICS.md). ``include_text``: the flight recorder
    (services/trace.py) also keeps each turn's request and answer, cut to 500 characters.
    Off by default: traces then hold timings, counts and tool names only."""

    include_text: StrictBool | None = None

    @field_validator("include_text", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged settings instead of sending null.")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a diagnostics setting to update.")
        return self


DIAGNOSTICS_DEFAULTS = {"include_text": False}


def diagnostics_settings(settings):
    """The saved ``diagnostics`` block over its defaults; a non-bool value reads as off."""
    saved = (settings or {}).get("diagnostics")
    saved = saved if isinstance(saved, dict) else {}
    return {
        key: saved[key] if isinstance(saved.get(key), bool) else default
        for key, default in DIAGNOSTICS_DEFAULTS.items()
    }


class SettingsPatch(EmptyRequest):
    tool_permissions: dict[StrictStr, PermissionValue] | None = Field(default=None, max_length=128)
    face_auth_enabled: StrictBool | None = None
    camera_flipped: StrictBool | None = None
    assistant: AssistantSettings | None = None
    voice: VoiceSettings | None = None
    calls: CallsSettings | None = None
    calendar: CalendarSettings | None = None
    briefing: BriefingSettings | None = None
    home_assistant: HomeAssistantSettings | None = None
    world: WorldSettings | None = None
    mcp: McpSettings | None = None
    diagnostics: DiagnosticsSettings | None = None

    @field_validator(
        "tool_permissions",
        "face_auth_enabled",
        "camera_flipped",
        "assistant",
        "voice",
        "calls",
        "calendar",
        "briefing",
        "home_assistant",
        "world",
        "mcp",
        "diagnostics",
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
                + " and restart JARVIS.",
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
            ("calendar", CALENDAR_DEFAULTS),
            ("briefing", BRIEFING_DEFAULTS),
            ("home_assistant", HOME_ASSISTANT_DEFAULTS),
            ("world", WORLD_DEFAULTS),
            ("diagnostics", DIAGNOSTICS_DEFAULTS),
        ):
            if section in patch:
                current = candidate.get(section)
                if section == "home_assistant" and isinstance(current, dict):
                    # The old plaintext token is never carried forward (docs/HOME_ASSISTANT.md).
                    current = {key: value for key, value in current.items() if key != "token"}
                candidate[section] = {
                    **defaults,
                    **(current if isinstance(current, dict) else {}),
                    **patch[section],
                }
        if "briefing" in patch:
            # One end of the window can change alone: check the order on the merged value.
            merged = candidate["briefing"]
            start, end = merged.get("window_start"), merged.get("window_end")
            if isinstance(start, str) and isinstance(end, str) and start >= end:
                raise ServiceError("invalid_arguments", BRIEFING_WINDOW_ORDER)
        sections = (
            "tool_permissions", "assistant", "voice", "calls", "calendar", "briefing",
            "home_assistant", "world", "diagnostics",
        )
        candidate.update({key: value for key, value in patch.items() if key not in sections})
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
