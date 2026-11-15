"""The environment every JARVIS child process starts with (docs/SECURITY.md, Child processes).

``minimal_env()`` never copies the core's environment wholesale. It starts from an
allow-list of what Windows programs need to start (system folders, temp and profile
folders, PATH, processor facts, locale), adds the parent variables a caller names in
``keep``, then the caller's ``extra``. Names that look like credentials (``*KEY*``,
``*TOKEN*``, ``*SECRET*``, ``*PASSWORD*``, ``*AUTH*``) and the provider and JARVIS
prefixes (``ANTHROPIC_``, ``GEMINI_``, ``GOOGLE_``, ``TWILIO_``, ``JARVIS_``) are never
copied from the parent, even when named in ``keep``: a secret a child genuinely needs
goes through ``extra`` only, explicitly, at its spawn site.

Names compare case-insensitively (Windows); an ``extra`` name replaces any spelling of
the same name. Values are never logged.
"""

import os
import re
from collections.abc import Iterable, Mapping

# What Windows programs need to start, upper case. Includes the 64-bit program-folder
# twins (ProgramW6432 and friends) and the profile names Chromium and Node read.
WINDOWS_ESSENTIALS = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PATH",
    "TEMP", "TMP",
    "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "ALLUSERSPROFILE", "PUBLIC",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    "PYTHONDONTWRITEBYTECODE",
)
# Locale: LANG, LANGUAGE and every LC_* variable.
LOCALE = re.compile(r"^(LANG|LANGUAGE|LC_[A-Z_]+)$")
# Credential-looking names and the provider/JARVIS prefixes: never inherited.
SECRET_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
SECRET_PREFIXES = ("ANTHROPIC_", "GEMINI_", "GOOGLE_", "TWILIO_", "JARVIS_")
PYTHON_EXTRA = {"PYTHONIOENCODING": "utf-8"}

_ESSENTIAL = frozenset(WINDOWS_ESSENTIALS)


def is_secret_name(name):
    """True for a name the parent's value must never reach a child through."""
    upper = str(name).upper()
    return any(part in upper for part in SECRET_PARTS) or upper.startswith(SECRET_PREFIXES)


def is_allowed(name):
    """True for a name ``minimal_env`` copies from the parent without being asked."""
    upper = str(name).upper()
    return (upper in _ESSENTIAL or bool(LOCALE.match(upper))) and not is_secret_name(upper)


def _put(env, key, value):
    for existing in [name for name in env if name.casefold() == key.casefold()]:
        del env[existing]
    env[key] = value


def minimal_env(
    extra: Mapping[str, str] | None = None,
    *,
    keep: Iterable[str] = (),
    python: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict:
    """A fresh environment for one child process.

    ``keep``: further parent variable names the child needs (never a secret-looking one).
    ``extra``: values set as given, after everything else (the only way a secret reaches a
    child). ``python``: the child is a Python interpreter (adds PYTHONIOENCODING=utf-8).
    ``environ``: the parent environment to read (default ``os.environ``).
    """
    source = os.environ if environ is None else environ
    wanted = {str(name).upper() for name in keep if not is_secret_name(name)}
    env = {}
    for key, value in source.items():
        upper = key.upper()
        if (is_allowed(upper) or upper in wanted) and not is_secret_name(upper):
            _put(env, key, value)
    if python:
        for key, value in PYTHON_EXTRA.items():
            _put(env, key, value)
    for key, value in (extra or {}).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("Child environment names and values must be strings")
        if "\x00" in key or "\x00" in value or "=" in key[1:] or not key:
            raise ValueError("Child environment entry is invalid")
        _put(env, key, value)
    return env
