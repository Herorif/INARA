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


def mask_display(value):
    """Owner-facing masked number: ``+60 12-•••• 6789`` (Malaysia), ``+44 •••• 1234``
    elsewhere, ``withheld`` when there is no usable number."""
    number = normalize(value) if isinstance(value, str) else None
    if number is None or number in WITHHELD_NUMBERS:
        return "withheld"
    digits = number[1:]
    if digits.startswith("60") and len(digits) >= 9:
        national = digits[2:]
        prefix = national[:2] if national[:1] in ("1", "8") else national[:1]
        return f"+60 {prefix}-•••• {digits[-4:]}"
    return f"+{digits[:2]} •••• {digits[-4:]}"


def number_key(value):
    """Stable non-reversible key for per-number ledgers (no raw numbers stored)."""
    return hashlib.sha256(("inara-telephony-number:" + value).encode("utf-8")).hexdigest()[:32]


def mask_sid(value):
    return f"{value[:2]}...{value[-4:]}" if isinstance(value, str) and len(value) > 8 else "-"
