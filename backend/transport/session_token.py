"""Per-process desktop session token; the core never runs without one.

Native/production launches pass ``INARA_SESSION_TOKEN`` (the native host generates it and
hands it to the workspace over an inherited pipe). A bare development start
(``python backend/server.py``) generates a fresh token for that process and writes it to a
user-only file under the gitignored ``.runtime/`` folder so the Vite dev client can use it.
The token value is never printed.
"""

import atexit
import os
from pathlib import Path
import secrets

ENV_NAME = "INARA_SESSION_TOKEN"
DEV_TOKEN_FILE = Path(__file__).resolve().parents[2] / ".runtime" / "dev-session-token"


def current_token(environ=None):
    """The token this process requires, or None (which rejects every connection)."""
    value = (os.environ if environ is None else environ).get(ENV_NAME)
    return value if isinstance(value, str) and value else None


def _write_private(path, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    # 0o600 on POSIX; on Windows the file inherits the per-user profile ACLs.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(token)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _remove_if_unchanged(path, token):
    try:
        if Path(path).read_text(encoding="ascii") == token:
            Path(path).unlink()
    except OSError:
        pass  # Expected at exit: the dev token file is already gone or replaced.


def ensure_session_token(path=DEV_TOKEN_FILE, environ=None, report=print, cleanup=True):
    """Return the process token, generating and recording a dev token when none was passed."""
    environ = os.environ if environ is None else environ
    token = current_token(environ)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    _write_private(path, token)
    environ[ENV_NAME] = token
    if cleanup:
        atexit.register(_remove_if_unchanged, path, token)
    report(f"[SERVER] Generated a session token for this launch; dev clients read it from {path}")
    return token
