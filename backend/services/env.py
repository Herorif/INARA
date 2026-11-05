"""Product environment variables: ``JARVIS_<X>``, with a one-release ``INARA_<X>`` fallback.

The product was renamed from INARA to JARVIS. Every reader goes through ``getenv``: the
``JARVIS_`` name wins whenever it is set (even to an empty string, which callers use to
blank a value); otherwise the legacy ``INARA_`` name is used and one deprecation warning
is logged per variable for the life of the process. Only the variable *name* is ever
logged, never its value. Remove the fallback (``LEGACY_PREFIX``) after one release.
"""

import logging
import os
import threading

PREFIX = "JARVIS_"
LEGACY_PREFIX = "INARA_"  # Rename fallback: remove one release after the JARVIS rename.

_warned = set()
_lock = threading.Lock()
_logger = logging.getLogger("jarvis.env")


def _suffix(name):
    for prefix in (PREFIX, LEGACY_PREFIX):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def name(suffix):
    """The current variable name for ``suffix`` (``"DATA_DIR"`` -> ``"JARVIS_DATA_DIR"``)."""
    return PREFIX + _suffix(suffix)


def names(suffix):
    """Both the current and the legacy name, e.g. for scrubbing a child's environment."""
    suffix = _suffix(suffix)
    return (PREFIX + suffix, LEGACY_PREFIX + suffix)


def getenv(suffix, default=None, environ=None):
    """``JARVIS_<suffix>``, else the deprecated ``INARA_<suffix>`` (warned once), else default.

    ``suffix`` may also be given as a full ``JARVIS_``/``INARA_`` name.
    """
    environ = os.environ if environ is None else environ
    current, legacy = names(suffix)
    value = environ.get(current)
    if value is not None:
        return value
    value = environ.get(legacy)
    if value is None:
        return default
    with _lock:
        first = legacy not in _warned
        _warned.add(legacy)
    if first:
        _logger.warning("%s is deprecated; rename it to %s.", legacy, current)
    return value


def lookup(variable, environ=None):
    """Any variable by full name: ``JARVIS_`` names get the legacy fallback, others are read as is."""
    if variable.startswith(PREFIX):
        return getenv(variable, environ=environ)
    return (os.environ if environ is None else environ).get(variable)


def _reset_warnings_for_tests():
    with _lock:
        _warned.clear()
