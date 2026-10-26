"""Owner API keys on the DPAPI-protected profile database.

Values never leave the backend: callers outside this process only ever see
``status()`` (label, source, last four characters, check results). A
non-placeholder environment variable overrides the store for development.

Adding a secret is one ``SecretSpec`` entry in ``REGISTRY``.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
import sqlite3
import ssl
from typing import Callable, Optional

from services.storage import StorageError
from services.tools import ServiceError

KIND = "secrets"
MAX_LENGTH = 512
TEST_TIMEOUT = 10.0

# Every placeholder ever shipped in .env.example, docs or verification scripts.
PLACEHOLDERS = frozenset(
    {
        "",
        "changeme",
        "your_api_key_here",
        "your_gemini_key",
        "your_gemini_api_key_here",
        "your_anthropic_api_key_here",
        "your_anthropic_key",
    }
)

CHECK_CODES = ("ok", "invalid_key", "rate_limited", "network_error", "tls_error", "unexpected")
CHECK_MESSAGES = {
    "ok": "{provider} accepted this key.",
    "invalid_key": "This key was rejected by {provider}.",
    "rate_limited": "{provider} is limiting requests right now. Try the test again in a minute.",
    "network_error": "Couldn't reach the service. Check your connection.",
    "tls_error": (
        "Couldn't make a secure connection to the service. "
        "A proxy or antivirus may be intercepting HTTPS."
    ),
    "unexpected": "{provider} gave an unexpected answer. Try again later.",
}


def is_placeholder(value):
    """True for missing, blank or known example values (case-insensitive)."""
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url, headers, timeout):
    """One GET; returns (status, short body). Raises transport/TLS errors."""
    import httpx

    from services.tls import provider_ssl_context

    # Explicit OS-store context (antivirus/proxy roots); nothing global is patched.
    with httpx.Client(
        timeout=timeout, follow_redirects=False, verify=provider_ssl_context()
    ) as client:
        response = client.get(url, headers=headers)
        return response.status_code, response.text[:2048]


def _anthropic_request(value):
    return (
        "https://api.anthropic.com/v1/models",
        {"x-api-key": value, "anthropic-version": "2023-06-01"},
    )


def _gemini_request(value):
    return (
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": value},
    )


def classify_response(status, body=""):
    if 200 <= status < 300:
        return "ok"
    if status in (401, 403):
        return "invalid_key"
    # Google answers an unknown key with 400 INVALID_ARGUMENT / API_KEY_INVALID.
    if status == 400 and ("API_KEY_INVALID" in body or "API key not valid" in body):
        return "invalid_key"
    if status == 429:
        return "rate_limited"
    return "unexpected"


def classify_exception(exc):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(current):
            return "tls_error"
        current = current.__cause__ or current.__context__
    try:
        import httpx

        if isinstance(exc, httpx.TransportError):
            return "network_error"
    except ImportError:
        pass
    if isinstance(exc, (OSError, TimeoutError)):
        return "network_error"
    return "unexpected"


@dataclass(frozen=True)
class SecretSpec:
    name: str
    label: str
    provider: str
    env: str
    pattern: str
    format_message: str
    request: Optional[Callable[[str], tuple]] = None

    def valid(self, value):
        return (
            isinstance(value, str)
            and len(value) <= MAX_LENGTH
            and not is_placeholder(value)
            and re.fullmatch(self.pattern, value) is not None
        )


REGISTRY = {
    spec.name: spec
    for spec in (
        SecretSpec(
            name="anthropic_api_key",
            label="Anthropic API key",
            provider="Anthropic",
            env="ANTHROPIC_API_KEY",
            pattern=r"sk-ant-[A-Za-z0-9_\-]{16,400}",
            format_message="Anthropic keys start with sk-ant-. Copy the whole key from the Anthropic Console.",
            request=_anthropic_request,
        ),
        SecretSpec(
            name="gemini_api_key",
            label="Gemini API key",
            provider="Google",
            env="GEMINI_API_KEY",
            pattern=r"AIza[A-Za-z0-9_\-]{30,60}",
            format_message="Gemini keys start with AIza and are about 39 characters. Copy the whole key from Google AI Studio.",
            request=_gemini_request,
        ),
    )
}


def spec_for(name):
    spec = REGISTRY.get(name) if isinstance(name, str) else None
    if spec is None:
        raise ServiceError("unknown_secret", "Unknown secret name.")
    return spec


def hint(value):
    return value[-4:] if isinstance(value, str) and len(value) >= 12 else None


def check_message(name, code):
    return CHECK_MESSAGES.get(code, CHECK_MESSAGES["unexpected"]).format(
        provider=spec_for(name).provider
    )


class SecretStore:
    def __init__(self, database, *, environ=None, send=None, clock=None):
        self.database = database
        self.environ = os.environ if environ is None else environ
        self.send = send or http_get
        self.clock = clock or now
        # Results for env-sourced keys are not persisted next to a stored value.
        self.env_checks = {}

    # --- storage -----------------------------------------------------------------
    def _document(self, name):
        with self.database.connection() as db:
            value = self.database.get(db, KIND, name)
        return value if isinstance(value, dict) else None

    def _environment(self, spec):
        value = (self.environ.get(spec.env) or "").strip()
        return None if is_placeholder(value) else value

    def resolve(self, name):
        """(value, source) with env override first; (None, None) when unset."""
        spec = spec_for(name)
        value = self._environment(spec)
        if value:
            return value, "env"
        document = self._document(name)
        stored = document.get("value") if document else None
        if isinstance(stored, str) and not is_placeholder(stored):
            return stored, "store"
        return None, None

    def get(self, name):
        return self.resolve(name)[0]

    def status(self, name):
        spec = spec_for(name)
        value, source = self.resolve(name)
        if source == "env":
            check = self.env_checks.get(name)
            verified_at = check["at"] if check and check["ok"] else None
        else:
            document = self._document(name) if source == "store" else None
            check = document.get("last_check") if document else None
            verified_at = document.get("verified_at") if document else None
        return {
            "name": spec.name,
            "label": spec.label,
            "configured": value is not None,
            "source": source,
            "hint": hint(value),
            "verified_at": verified_at,
            "last_check": check,
        }

    def statuses(self):
        return [self.status(name) for name in REGISTRY]

    def validate(self, name, value):
        spec = spec_for(name)
        value = value.strip() if isinstance(value, str) else value
        if not spec.valid(value):
            raise ServiceError("invalid_format", spec.format_message)
        return value

    def set(self, name, value, check=None):
        """Validate and store; an optional prior check for this exact value is kept."""
        value = self.validate(name, value)
        stamp = self.clock()
        document = {
            "value": value,
            "updated_at": stamp,
            "verified_at": check["at"] if check and check.get("ok") else None,
            "last_check": check,
        }
        with self.database.transaction() as db:
            self.database.put(db, KIND, name, document)
        return self.status(name)

    def clear(self, name):
        spec_for(name)
        with self.database.transaction() as db:
            db.execute("DELETE FROM documents WHERE kind=? AND id=?", (KIND, name))
        return self.status(name)

    # --- provider checks -----------------------------------------------------------
    def check_value(self, name, value):
        """One cheap authenticated request; returns {ok, code, at}. Never logs the key."""
        spec = spec_for(name)
        if spec.request is None:
            code = "unexpected"
        else:
            url, headers = spec.request(value)
            try:
                status, body = self.send(url, headers, TEST_TIMEOUT)
                code = classify_response(status, body or "")
            except Exception as exc:  # the exception text is never logged or returned
                code = classify_exception(exc)
        return {"ok": code == "ok", "code": code, "at": self.clock()}

    def test(self, name):
        value, source = self.resolve(name)
        if value is None:
            raise ServiceError("not_configured", "No key is saved for this provider yet.")
        check = self.check_value(name, value)
        if source == "env":
            self.env_checks[name] = check
        else:
            with self.database.transaction() as db:
                document = self.database.get(db, KIND, name)
                if isinstance(document, dict) and document.get("value") == value:
                    document["last_check"] = check
                    if check["ok"]:
                        document["verified_at"] = check["at"]
                    self.database.put(db, KIND, name, document)
        return self.status(name)


# --- process-wide resolution for module-level callers (provider_key etc.) ----------
_active = {"store": None}


def activate(store):
    """The composition root registers the profile's store; returns the previous one."""
    previous, _active["store"] = _active["store"], store
    return previous


def active_store():
    return _active["store"]


def resolve(name, environ=None):
    """Env override, then the active profile store; None when neither has a real key."""
    spec = spec_for(name)
    value = ((os.environ if environ is None else environ).get(spec.env) or "").strip()
    if not is_placeholder(value):
        return value
    store = _active["store"]
    if store is None:
        return None
    try:
        document = store._document(name)
    except (StorageError, sqlite3.Error, OSError):
        return None
    stored = document.get("value") if document else None
    return stored if isinstance(stored, str) and not is_placeholder(stored) else None


def environment_placeholder(name, environ=None):
    """True when the env var is set but only to a known placeholder (startup hint)."""
    spec = spec_for(name)
    raw = (os.environ if environ is None else environ).get(spec.env)
    return raw is not None and raw.strip() != "" and is_placeholder(raw)
