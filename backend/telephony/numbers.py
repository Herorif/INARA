"""Phone-number helpers: E.164 normalisation, withheld caller IDs and log masking."""

import hashlib
import re

E164 = re.compile(r"\+[1-9][0-9]{6,14}")
_SEPARATORS = re.compile(r"[\s\-().]")

# Twilio presents withheld/unavailable caller IDs as these keypad spellings
# (ANONYMOUS, RESTRICTED, BLOCKED, UNKNOWN, UNAVAILABLE) or as plain words.
WITHHELD_NUMBERS = frozenset(
    {"+266696687", "+7378742833", "+2562533", "+8656696", "+86282452253"}
)
WITHHELD_WORDS = frozenset(
    {"", "anonymous", "restricted", "blocked", "unknown", "unavailable", "private", "withheld"}
)


def normalize(value):
    """E.164 string, or None when ``value`` is not a plausible E.164 number."""
    if not isinstance(value, str):
        return None
    candidate = _SEPARATORS.sub("", value.strip())
    return candidate if E164.fullmatch(candidate) else None


def withheld(value):
    """True when Twilio's From/Caller value carries no usable caller ID."""
    if not isinstance(value, str):
        return True
    text = value.strip()
    if text.lower().lstrip("+") in WITHHELD_WORDS:
        return True
    number = normalize(text)
    return number is None or number in WITHHELD_NUMBERS


def same_number(left, right):
    a, b = normalize(left), normalize(right)
    return a is not None and a == b


def mask(value):
    """Last four digits only, for logs and status."""
    number = normalize(value) if isinstance(value, str) else None
    return f"***{number[-4:]}" if number else "withheld"


def number_key(value):
    """Stable non-reversible key for per-number ledgers (no raw numbers stored)."""
    return hashlib.sha256(("inara-telephony-number:" + value).encode("utf-8")).hexdigest()[:32]


def mask_sid(value):
    return f"{value[:2]}...{value[-4:]}" if isinstance(value, str) and len(value) > 8 else "-"
