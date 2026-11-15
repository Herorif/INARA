"""Diagnostics export (S4.2, docs/DIAGNOSTICS.md): one zip the owner can hand to the
builder instead of copying logs out of a private AppData.

``DiagnosticsService(app).export(owner=None)`` writes
``diagnostics-<YYYYMMDD-HHMMSS>.zip`` to ``diagnostics.folder`` (empty: ``<repo>\\.runtime\\
live-logs`` in a dev checkout, else ``%USERPROFILE%\\Documents\\JARVIS diagnostics``) and
answers ``{ok: True, path}``. Files in the zip::

    log.txt          the last 2,000 log lines (current log file, then the previous one)
    turn_timing.txt  every turn_timing and brain_check line in those files
    settings.json    the settings with secret-like values, phone numbers, the owner's name
                     and the home place replaced by "[removed]"
    keys.json        [{name, configured}] for every secret; never a value or a hint
    versions.json    app, Python, OS, Electron (Node when known), key packages
    sidecars.json    world view, MCP servers, CAD kernel, wake word, voice: states only
    audio.json       microphone and speaker names and the chosen ones
    traces.json      the last 20 flight-recorder traces (text only while include_text is on)

A last pass over every file removes anything shaped like a key or token and every email
address, and the owner's name and home place wherever they appear. Only the number of
replacements is logged.
"""

import asyncio
import copy
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import zipfile

from services.log import get_logger
from services.settings import diagnostics_settings

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LOG_LINES = 2000
TRACE_COUNT = 20
AUDIO_SECONDS = 5.0
REMOVED = "[removed]"
PACKAGES = ("anthropic", "google-genai", "httpx", "websockets")
EXPORT_FAILED = "Diagnostics couldn't be saved. Check that the folder can be written to."

# --- redaction ---------------------------------------------------------------------------

# Settings keys whose values are never exported (snake_case, kebab-case or camelCase parts).
SECRET_WORDS = ("token", "key", "secret", "password", "auth", "cookie", "pin")
_PARTS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
# Nine or more digits with phone punctuation: dates (8 digits), times, versions and IP
# addresses (dotted, so never matched) stay readable.
_PHONE = re.compile(r"(?<![\w+.])\+?\d[\d\s()\-]{6,}\d(?![\w.])")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_TOKENS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), REMOVED),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), REMOVED),
    (re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{16,}"), REMOVED),
    (re.compile(r"(?i)\b(bearer)\s+(?!\[removed\])[^\s,;\"']+"), r"\1 " + REMOVED),
    (_EMAIL, REMOVED),
)
# Long base64/base64url/hex runs: keys and tokens of any provider.
_OPAQUE = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")


def secret_key(name):
    """Whether a settings key names something secret-like (``api_key``, ``authToken``)."""
    if not isinstance(name, str):
        return False
    for part in _PARTS.findall(name):
        part = part.lower()
        if any(part.startswith(word) or part.endswith(word) for word in SECRET_WORDS):
            return True
    return False


def phone_numbers(text):
    """``text`` with every phone-number-shaped run replaced, and the count."""
    count = 0

    def replace(match):
        nonlocal count
        if sum(char.isdigit() for char in match.group(0)) < 9:
            return match.group(0)
        count += 1
        return REMOVED

    return _PHONE.sub(replace, text), count


def personal_terms(settings):
    """The owner's name and home place (and their words of 3+ letters) to remove anywhere."""
    assistant = (settings or {}).get("assistant") if isinstance(settings, dict) else None
    assistant = assistant if isinstance(assistant, dict) else {}
    terms = []
    name = assistant.get("owner_name")
    if isinstance(name, str) and name.strip():
        terms.append(name.strip())
        terms.extend(name.split())
    place = assistant.get("home_place")
    place = place.get("name") if isinstance(place, dict) else None
    if isinstance(place, str) and place.strip():
        terms.append(place.strip())
        terms.extend(item.strip() for item in place.split(","))
    unique = []
    for term in sorted(terms, key=len, reverse=True):
        if len(term) >= 3 and term.lower() not in (item.lower() for item in unique):
            unique.append(term)
    return unique


def scrub(text, terms=()):
    """(``text`` with keys, tokens, emails and ``terms`` removed, number of replacements)."""
    total = 0
    for pattern, replacement in _TOKENS:
        text, count = pattern.subn(replacement, text)
        total += count
    for term in terms:
        text, count = re.subn(r"(?i)(?<!\w)" + re.escape(term) + r"(?!\w)", REMOVED, text)
        total += count

    def opaque(match):
        nonlocal total
        value = match.group(0)
        if _UUID.fullmatch(value) or not (
            any(char.isdigit() for char in value) and any(char.isalpha() for char in value)
        ):
            return value
        total += 1
        return REMOVED

    text = _OPAQUE.sub(opaque, text)
    return text, total


def redact_settings(settings):
    """A copy of the settings snapshot that is safe to export."""
    terms = personal_terms(settings)

    def walk(value, key=None):
        if key is not None and secret_key(key) and not isinstance(value, (bool, type(None))):
            return REMOVED
        if isinstance(value, dict):
            return {name: walk(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            value, _ = phone_numbers(value)
            return scrub(value, terms)[0]
        return value

    result = walk(copy.deepcopy(settings) if isinstance(settings, dict) else {})
    assistant = result.get("assistant")
    if isinstance(assistant, dict):
        for name in ("owner_name", "home_place"):
            if assistant.get(name):
                assistant[name] = REMOVED
    calls = result.get("calls")
    if isinstance(calls, dict) and calls.get("facts"):
        calls["facts"] = REMOVED  # free text the owner wrote for callers
    return result


# --- where the zip goes ------------------------------------------------------------------


def dev_checkout(root=ROOT):
    """A source checkout, not a staged desktop pilot (the marker resident/layout.py reads)."""
    return not (Path(root) / "desktop-pilot.json").exists()


def default_folder(root=ROOT, home=None):
    root = Path(root)
    if dev_checkout(root):
        return root / ".runtime" / "live-logs"
    home = Path(home) if home else Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Documents" / "JARVIS diagnostics"


def export_folder(settings, root=ROOT, home=None):
    saved = diagnostics_settings(settings)["folder"]
    return Path(saved) if saved else default_folder(root, home)


# --- the parts ---------------------------------------------------------------------------


def log_files(directory):
    """Existing log files, oldest first: the previous rotation, then the current file."""
    directory = Path(directory)
    return [path for path in (directory / "jarvis.log.1", directory / "jarvis.log") if path.is_file()]


def read_logs(directory, limit=LOG_LINES):
    """(last ``limit`` lines, every turn_timing/brain_check line) of the current log and,
    when it holds fewer than ``limit`` lines, the previous one."""
    files = log_files(directory)
    chunks = []
    for path in reversed(files):
        try:
            chunks.insert(0, path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if sum(len(chunk) for chunk in chunks) >= limit:
            break
    lines = [line for chunk in chunks for line in chunk]
    timing = [line for line in lines if re.search(r":\s(turn_timing|brain_check)\b", line)]
    return lines[-limit:], timing


def _version(package):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _json_value(path, key):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8")).get(key)
        return value if isinstance(value, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def versions(root=ROOT):
    root = Path(root)
    electron = _json_value(root / "node_modules/electron/package.json", "version")
    if electron is None:
        try:
            electron = (root / "runtime/electron/version").read_text(encoding="utf-8").strip() or None
        except OSError:
            electron = None
    build = None
    if hasattr(sys, "getwindowsversion"):
        info = sys.getwindowsversion()
        build = f"{info.major}.{info.minor}.{info.build}"
    return {
        "app": _json_value(root / "package.json", "version"),
        "python": platform.python_version(),
        "os": platform.platform(),
        "os_build": build,
        "electron": electron,
        "node": None,  # the core runs no Node; Electron's own is not reported to it
        "dev_checkout": dev_checkout(root),
        "packages": {name: _version(name) for name in PACKAGES},
    }


def _state(read, default="unknown"):
    try:
        value = read()
    except Exception:
        return default
    return value if isinstance(value, str) else default


def sidecars(app):
    def cad():
        kernel = app.cad_kernel
        if kernel.running():
            return "running"
        return "available" if kernel.available() else "unavailable"

    def mcp():
        return [
            {"id": str(item.get("id")), "state": str(item.get("state"))}
            for item in app.mcp.statuses()
        ]

    def voice():
        status = getattr(app.voice, "local_published", None)
        return status.get("state") if isinstance(status, dict) else "off"

    try:
        servers = mcp()
    except Exception:
        servers = "unknown"
    return {
        "world_view": _state(lambda: app.world.status()["state"]),
        "mcp_servers": servers,
        "cad_kernel": _state(cad),
        "wake_word": _state(lambda: app.wake.status()["state"]),
        "voice": _state(voice),
    }


def _choice(value):
    if value == "default":
        return "default"
    return value.get("name") if isinstance(value, dict) and isinstance(value.get("name"), str) else None


async def audio(app):
    voice = (app.settings or {}).get("voice")
    voice = voice if isinstance(voice, dict) else {}
    result = {
        "available": False,
        "host_api": None,
        "inputs": [],
        "outputs": [],
        "chosen_input": _choice(voice.get("local_microphone", "default")),
        "chosen_output": _choice(voice.get("local_speaker", "default")),
    }
    try:
        report = await asyncio.wait_for(app.audio_devices.report(), AUDIO_SECONDS)
    except Exception as exc:
        result["error"] = type(exc).__name__
        return result
    result.update(
        available=bool(report.get("available")),
        host_api=report.get("host_api"),
        inputs=[item.get("name") for item in report.get("inputs") or []],
        outputs=[item.get("name") for item in report.get("outputs") or []],
    )
    return result


def traces(app, owner=None, include_text=False):
    """The last 20 traces; text fields only while include_text is on now."""
    found = app.trace.recent(TRACE_COUNT, owner=owner)
    if not include_text:
        for trace in found:
            trace.pop("request_text", None)
            trace.pop("answer_text", None)
    return found


def key_status(store):
    from services.secrets import REGISTRY

    result = []
    for name in REGISTRY:
        try:
            configured = store.resolve(name)[0] is not None
        except Exception:
            configured = False
        result.append({"name": name, "configured": configured})
    return result


def _dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n"


def write_zip(folder, files, now=None):
    """Write ``files`` ({name: text}) to a new zip in ``folder``; returns its path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target, index = folder / f"diagnostics-{stamp}.zip", 1
    while target.exists():
        target, index = folder / f"diagnostics-{stamp}-{index}.zip", index + 1
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=".diagnostics-", suffix=".tmp")
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


class DiagnosticsService:
    def __init__(self, app, *, root=ROOT, home=None, log_dir=None, clock=None):
        self.app = app
        self.root, self.home = Path(root), home
        self._log_dir = log_dir
        self.clock = clock or datetime.now
        self.lock = asyncio.Lock()

    def folder(self):
        return export_folder(self.app.settings, self.root, self.home)

    def log_dir(self):
        if self._log_dir is not None:
            return Path(self._log_dir)
        from services.log import log_directory

        return log_directory()

    async def collect(self, owner=None):
        """{name: text} for the zip, before the last redaction pass."""
        settings = self.app.settings
        include_text = diagnostics_settings(settings)["include_text"]
        lines, timing = await asyncio.to_thread(read_logs, self.log_dir())
        return {
            "log.txt": "\n".join(lines) + "\n",
            "turn_timing.txt": "\n".join(timing) + "\n",
            "settings.json": _dump(redact_settings(settings)),
            "keys.json": _dump(key_status(self.app.secrets)),
            "versions.json": _dump(await asyncio.to_thread(versions, self.root)),
            "sidecars.json": _dump(sidecars(self.app)),
            "audio.json": _dump(await audio(self.app)),
            "traces.json": _dump(traces(self.app, owner, include_text)),
        }

    async def export(self, owner=None):
        """Write the zip; ``{ok: True, path}`` or ``{ok: False, code, message}``."""
        async with self.lock:
            try:
                files = await self.collect(owner)
                terms = personal_terms(self.app.settings)
                removed = 0
                for name, text in files.items():
                    files[name], count = scrub(text, terms)
                    removed += count
                path = await asyncio.to_thread(write_zip, self.folder(), files, self.clock())
            except Exception as exc:
                logger.warning("Diagnostics export failed (%s)", type(exc).__name__)
                return {"ok": False, "code": "diagnostics_failed", "message": EXPORT_FAILED}
            logger.info("Diagnostics export saved (%d redactions)", removed)
            return {"ok": True, "path": str(path)}
