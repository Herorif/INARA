"""Redacted diagnostic logging for the core.

``get_logger(name)`` returns a logger under the ``jarvis`` namespace whose records are
redacted before any handler sees them. ``configure_logging()`` runs once per process from
the real entry points (``server.py`` and the native resident host); it attaches a
size-capped rotating file under ``<user data>/logs/jarvis.log`` plus stderr. Callers log
codes, event names and exception types: never key values, prompts or transcripts. The
filter below is defense in depth for secrets that slip into messages or tracebacks.
"""

import logging
import logging.handlers
import re
import sys
import threading

ROOT = "jarvis"
MASK = "[REDACTED]"
FILE_BYTES = 2 * 1024 * 1024
FILE_BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_KEYED = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key|x-goog-api-key|api[_-]?key|"
    r"session[_-]?token|access[_-]?token|refresh[_-]?token|token|secret|password)"
    r"([\"']?\s*[:=]\s*[\"']?)"
    r"(?:(?:bearer|basic|token)\s+)?"
    r"([^\s,;\"'&}\]]+)"
)
_PATTERNS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), MASK),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), MASK),
    (re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{16,}"), MASK),  # Google's newer Gemini auth keys
    (re.compile(r"(?i)\b(bearer)\s+[^\s,;\"']+"), r"\1 " + MASK),
    (_KEYED, r"\1\2" + MASK),
)
# Long base64/base64url/hex-like runs: tokens, signatures, keys of unknown providers.
_OPAQUE = re.compile(r"[A-Za-z0-9+/_\-]{40,}={0,2}")


def _opaque(match):
    text = match.group(0)
    # Require mixed letters and digits so ordinary long words and paths survive.
    if any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
        return MASK
    return text


def redact(text):
    """Mask every known secret shape in ``text``."""
    if not isinstance(text, str) or not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return _OPAQUE.sub(_opaque, text)


class RedactingFilter(logging.Filter):
    """Render each record once, redacted, so no handler formats the raw arguments."""

    def filter(self, record):
        if getattr(record, "_jarvis_redacted", False):
            return True
        try:
            message = record.getMessage()
        except Exception:  # A malformed call must not drop the record or leak its args.
            message = f"{record.msg!s} (unformattable arguments)"
        record.msg, record.args = redact(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        record._jarvis_redacted = True
        return True


_FILTER = RedactingFilter()
_lock = threading.Lock()
_configured = None


def get_logger(name=None):
    """A redacting logger under ``jarvis`` (``name`` may be a module ``__name__``)."""
    name = ROOT if not name or name == ROOT else name
    if name != ROOT and not name.startswith(ROOT + "."):
        name = f"{ROOT}.{name}"
    logger = logging.getLogger(name)
    if _FILTER not in logger.filters:
        logger.addFilter(_FILTER)
    return logger


def log_directory():
    from services.storage import user_data_directory

    return user_data_directory() / "logs"


def configure_logging(directory=None, level=logging.INFO, stream=None):
    """Attach the rotating file and stderr handlers once; returns the log file path or None."""
    global _configured
    with _lock:
        if _configured is not None:
            return _configured["path"]
        logger = get_logger(ROOT)
        logger.setLevel(level)
        formatter = logging.Formatter(FORMAT)
        handlers, path = [], None
        try:
            directory = log_directory() if directory is None else directory
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "jarvis.log"
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    path,
                    maxBytes=FILE_BYTES,
                    backupCount=FILE_BACKUPS,
                    encoding="utf-8",
                    delay=True,
                )
            )
        except Exception:  # No writable profile: keep stderr diagnostics only.
            path = None
        handlers.append(logging.StreamHandler(stream if stream is not None else sys.stderr))
        for handler in handlers:
            handler.setFormatter(formatter)
            handler.addFilter(_FILTER)
            logger.addHandler(handler)
        _configured = {"path": path, "handlers": handlers}
        if path is None:
            logger.warning("Diagnostic log file unavailable; logging to stderr only.")
        # The INARA -> JARVIS folder move runs while the log directory is resolved, before
        # these handlers existed: replay what it reported so it reaches the log file.
        from services.data_migration import drain_pending

        migration = get_logger("migration")
        for level, message in drain_pending():
            migration.log(level, message)
        return path


def reset_logging():
    """Detach and close configured handlers (tests and orderly process exit)."""
    global _configured
    with _lock:
        if _configured is None:
            return
        logger = logging.getLogger(ROOT)
        for handler in _configured["handlers"]:
            logger.removeHandler(handler)
            handler.close()
        _configured = None
