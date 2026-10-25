"""Fail-closed desktop session token: required handshake, dev token file, renderer origins."""

import uuid

import pytest

from transport import session_token
from transport.session_token import ENV_NAME, current_token, ensure_session_token

TOKEN = "test-session-token"


def owner_auth(**extra):
    return {"client_id": str(uuid.uuid4()), **extra}


@pytest.mark.parametrize("configured", [None, ""])
def test_unconfigured_core_rejects_every_handshake(application_factory, configured):
    sessions = application_factory().sessions
    for auth in (owner_auth(), owner_auth(token=""), owner_auth(token=TOKEN)):
        assert sessions.accept("sid", auth, configured) is False
    assert sessions.local_owner is None and not sessions.principals and not sessions.roles


@pytest.mark.parametrize(
    "presented", [None, "", "wrong", TOKEN + "x", TOKEN.upper(), 12345, [TOKEN], {"t": TOKEN}]
)
def test_missing_wrong_or_malformed_token_is_rejected(application_factory, presented):
    sessions = application_factory().sessions
    auth = owner_auth() if presented is None else owner_auth(token=presented)
    assert sessions.accept("sid", auth, TOKEN) is False
    assert sessions.local_owner is None and not sessions.principals


def test_no_first_client_owner_fallback(application_factory):
    sessions = application_factory().sessions
    squatter, owner = str(uuid.uuid4()), str(uuid.uuid4())
    # A tokenless first client gains nothing, with or without a configured token.
    assert not sessions.accept("first", {"client_id": squatter}, None)
    assert not sessions.accept("first", {"client_id": squatter}, TOKEN)
    assert sessions.local_owner is None
    assert sessions.accept("owner", {"client_id": owner, "token": TOKEN}, TOKEN)
    assert sessions.local_owner == owner and sessions.is_owner(owner)
    assert not sessions.is_owner(squatter)


@pytest.mark.asyncio
async def test_connection_transport_fails_closed_without_process_token(
    application_factory, monkeypatch
):
    app = application_factory()
    monkeypatch.delenv(ENV_NAME, raising=False)
    assert await app.connection.connect("first", {}, owner_auth()) is False
    assert await app.connection.connect("second", {}, owner_auth(token=TOKEN)) is False
    assert app.sessions.local_owner is None and not app.sessions.principals
    monkeypatch.setenv(ENV_NAME, TOKEN)
    assert await app.connection.connect("wrong", {}, owner_auth(token="wrong")) is False
    assert await app.connection.connect("missing", {}, owner_auth()) is False
    assert not app.sessions.principals
    owner = str(uuid.uuid4())
    assert await app.connection.connect("ok", {}, {"client_id": owner, "token": TOKEN}) is not False
    assert app.sessions.principals == {"ok": owner} and app.sessions.local_owner == owner
    await app.close()


def test_token_generated_and_written_when_env_unset(tmp_path):
    environ, messages = {}, []
    path = tmp_path / ".runtime" / "dev-session-token"
    token = ensure_session_token(path, environ, messages.append, cleanup=False)
    assert len(token) >= 40 and environ[ENV_NAME] == token == current_token(environ)
    assert path.read_text(encoding="ascii") == token
    assert [p.name for p in path.parent.iterdir()] == ["dev-session-token"]
    assert len(messages) == 1 and str(path) in messages[0] and token not in messages[0]
    # Each launch gets a fresh token; the file follows the running core.
    second = ensure_session_token(path, {}, messages.append, cleanup=False)
    assert second != token and path.read_text(encoding="ascii") == second


def test_passed_token_is_used_and_no_file_is_written(tmp_path):
    environ, messages = {ENV_NAME: "launcher-token"}, []
    path = tmp_path / "dev-session-token"
    assert ensure_session_token(path, environ, messages.append) == "launcher-token"
    assert not path.exists() and not messages


def test_dev_token_file_is_removed_only_while_it_is_ours(tmp_path):
    path = tmp_path / "dev-session-token"
    path.write_text("ours", encoding="ascii")
    session_token._remove_if_unchanged(path, "other")
    assert path.exists()
    session_token._remove_if_unchanged(path, "ours")
    assert not path.exists()
    session_token._remove_if_unchanged(path, "ours")  # already gone: no error


def test_default_dev_token_file_is_in_gitignored_runtime_folder():
    root = session_token.DEV_TOKEN_FILE.parents[1]
    assert session_token.DEV_TOKEN_FILE == root / ".runtime" / "dev-session-token"
    assert ".runtime/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


def polling_handshake(app, origin):
    from starlette.testclient import TestClient

    headers = {} if origin is None else {"Origin": origin}
    with TestClient(app.asgi) as client:
        return client.get("/socket.io/?EIO=4&transport=polling", headers=headers)


@pytest.mark.parametrize("origin", ["http://localhost:5173", "file://", None])
def test_renderer_origins_are_allowed(application_factory, origin):
    app = application_factory()
    response = polling_handshake(app, origin)
    assert response.status_code == 200
    if origin:
        assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://localhost:8000",
        "https://localhost:5173",
        "http://evil.example",
        "file:///C:/Users/someone/attack.html",
    ],
)
def test_other_origins_are_rejected(application_factory, origin):
    app = application_factory()
    response = polling_handshake(app, origin)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
