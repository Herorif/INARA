"""Provider key store, checks, owner-only routes and the jarvis-secrets CLI. No network."""

import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import uuid

import httpx
import pytest

from services import secrets
from services.secrets import SecretStore, classify_exception, classify_response, is_placeholder
from services.storage import Database

ROOT = Path(__file__).resolve().parents[1]
ANTHROPIC = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8" * 4 + "wxyz"
GEMINI = "AIzaSy" + "Q" * 31 + "k9"  # 39 characters

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DPAPI store requires Windows")


@pytest.fixture(autouse=True)
def restore_active_store():
    previous = secrets.active_store()
    yield
    secrets.activate(previous)


class Sender:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture
def store(tmp_path):
    return SecretStore(Database(tmp_path / "db"), environ={}, send=Sender((200, "{}")))


def raw_bytes(directory):
    return b"".join(path.read_bytes() for path in Path(directory).iterdir() if path.is_file())


def test_round_trip_is_encrypted_on_disk(tmp_path):
    store = SecretStore(Database(tmp_path / "db"), environ={})
    store.set("anthropic_api_key", "  " + ANTHROPIC + "\n")
    assert store.get("anthropic_api_key") == ANTHROPIC
    data = raw_bytes(tmp_path / "db")
    assert ANTHROPIC.encode() not in data and ANTHROPIC.encode("utf-16-le") not in data
    assert b"sk-ant-" not in data
    # A second store on the same profile (e.g. the CLI) reads the same value.
    assert SecretStore(Database(tmp_path / "db"), environ={}).get("anthropic_api_key") == ANTHROPIC


def test_environment_overrides_store_unless_placeholder(tmp_path):
    environ = {}
    store = SecretStore(Database(tmp_path / "db"), environ=environ)
    store.set("gemini_api_key", GEMINI)
    assert store.resolve("gemini_api_key") == (GEMINI, "store")
    environ["GEMINI_API_KEY"] = "dev-override-value"
    assert store.resolve("gemini_api_key") == ("dev-override-value", "env")
    for placeholder in ("your_api_key_here", "CHANGEME", "  ", "your_gemini_api_key_here"):
        environ["GEMINI_API_KEY"] = placeholder
        assert store.resolve("gemini_api_key") == (GEMINI, "store")
    store.clear("gemini_api_key")
    assert store.resolve("gemini_api_key") == (None, None)


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, "changeme", "ChangeMe", "your_api_key_here", "your_gemini_key",
     "your_gemini_api_key_here", "your_anthropic_api_key_here"],
)
def test_placeholders_are_rejected(store, value):
    assert is_placeholder(value)
    with pytest.raises(secrets.ServiceError) as error:
        store.set("gemini_api_key", value)
    assert error.value.code == "invalid_format"


@pytest.mark.parametrize(
    "name,value,valid",
    [
        ("anthropic_api_key", ANTHROPIC, True),
        ("anthropic_api_key", "sk-ant-short", False),
        ("anthropic_api_key", GEMINI, False),
        ("anthropic_api_key", ANTHROPIC + " extra", False),
        ("anthropic_api_key", ANTHROPIC + "x" * 600, False),
        ("gemini_api_key", GEMINI, True),
        ("gemini_api_key", "AIza" + "x" * 10, False),
        ("gemini_api_key", ANTHROPIC, False),
        ("gemini_api_key", "AIza" + "x" * 30 + "é" * 5, False),
    ],
)
def test_format_validation(store, name, value, valid):
    if valid:
        assert store.set(name, value)["configured"]
    else:
        with pytest.raises(secrets.ServiceError) as error:
            store.set(name, value)
        assert error.value.code == "invalid_format" and value not in str(error.value)
        assert not store.status(name)["configured"]


def test_unknown_secret_name(store):
    with pytest.raises(secrets.ServiceError) as error:
        store.set("twilio_api_secret", "x" * 40)
    assert error.value.code == "unknown_secret"


def test_status_never_contains_the_value(store):
    store.set("anthropic_api_key", ANTHROPIC)
    store.environ["GEMINI_API_KEY"] = GEMINI
    store.test("anthropic_api_key")
    store.test("gemini_api_key")
    statuses = store.statuses()
    text = json.dumps(statuses)
    assert ANTHROPIC not in text and GEMINI not in text
    by_name = {item["name"]: item for item in statuses}
    assert set(by_name["anthropic_api_key"]) == {
        "name", "label", "configured", "source", "hint", "verified_at", "last_check"
    }
    assert by_name["anthropic_api_key"]["hint"] == "wxyz"
    assert by_name["anthropic_api_key"]["source"] == "store"
    assert by_name["gemini_api_key"]["source"] == "env"
    assert by_name["gemini_api_key"]["hint"] == GEMINI[-4:]


def test_requests_are_cheap_authenticated_and_bounded(store):
    store.set("anthropic_api_key", ANTHROPIC)
    store.set("gemini_api_key", GEMINI)
    store.test("anthropic_api_key")
    store.test("gemini_api_key")
    (a_url, a_headers, a_timeout), (g_url, g_headers, g_timeout) = store.send.calls
    assert a_url == "https://api.anthropic.com/v1/models"
    assert a_headers == {"x-api-key": ANTHROPIC, "anthropic-version": "2023-06-01"}
    assert g_url == "https://generativelanguage.googleapis.com/v1beta/models"
    assert g_headers == {"x-goog-api-key": GEMINI}
    assert a_timeout == g_timeout == 10.0
    assert ANTHROPIC not in a_url and GEMINI not in g_url


@pytest.mark.parametrize(
    "status,body,code",
    [
        (200, "{}", "ok"),
        (401, "", "invalid_key"),
        (403, "", "invalid_key"),
        (400, '{"error":{"status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}', "invalid_key"),
        (400, "bad request", "unexpected"),
        (429, "", "rate_limited"),
        (500, "", "unexpected"),
        (302, "", "unexpected"),
    ],
)
def test_response_code_mapping(status, body, code):
    assert classify_response(status, body) == code


def tls_wrapped():
    try:
        raise ssl.SSLCertVerificationError("certificate verify failed")
    except ssl.SSLError as inner:
        try:
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]") from inner
        except httpx.ConnectError as outer:
            return outer


@pytest.mark.parametrize(
    "error,code",
    [
        (ssl.SSLCertVerificationError("verify failed"), "tls_error"),
        (tls_wrapped(), "tls_error"),
        (httpx.ConnectError("Name or service not known"), "network_error"),
        (httpx.ConnectTimeout("timed out"), "network_error"),
        (httpx.ReadTimeout("timed out"), "network_error"),
        (ConnectionResetError(), "network_error"),
        (ValueError("boom"), "unexpected"),
    ],
)
def test_exception_code_mapping(tmp_path, error, code):
    assert classify_exception(error) == code
    store = SecretStore(Database(tmp_path / "db"), environ={}, send=Sender(error))
    store.set("anthropic_api_key", ANTHROPIC)
    status = store.test("anthropic_api_key")
    assert status["last_check"]["code"] == code and status["verified_at"] is None


def test_check_results_persist_and_reset_on_new_value(store):
    store.set("gemini_api_key", GEMINI)
    status = store.test("gemini_api_key")
    assert status["last_check"]["ok"] and status["verified_at"] == status["last_check"]["at"]
    replacement = "AIzaSy" + "R" * 33
    assert store.set("gemini_api_key", replacement)["verified_at"] is None
    store.send.result = (401, "")
    status = store.test("gemini_api_key")
    assert status["last_check"]["code"] == "invalid_key" and status["verified_at"] is None


def test_test_without_key_is_refused(store):
    with pytest.raises(secrets.ServiceError) as error:
        store.test("anthropic_api_key")
    assert error.value.code == "not_configured"
    assert store.send.calls == []


def test_provider_key_resolves_env_then_active_store(tmp_path, monkeypatch):
    from services.capability_profiles import anthropic_key, provider_key

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    secrets.activate(None)
    assert provider_key() is None and anthropic_key() is None
    store = SecretStore(Database(tmp_path / "db"))
    secrets.activate(store)
    store.set("gemini_api_key", GEMINI)
    store.set("anthropic_api_key", ANTHROPIC)
    assert provider_key() == GEMINI and anthropic_key() == ANTHROPIC
    monkeypatch.setenv("GEMINI_API_KEY", "changeme")
    assert provider_key() == GEMINI
    monkeypatch.setenv("GEMINI_API_KEY", "developer-override")
    assert provider_key() == "developer-override"


def test_workspace_preflight_uses_shared_check(tmp_path, monkeypatch):
    from services.workspace import provider_ready

    monkeypatch.setenv("GEMINI_API_KEY", "your_api_key_here")
    secrets.activate(SecretStore(Database(tmp_path / "db")))
    with pytest.raises(secrets.ServiceError) as error:
        provider_ready()
    assert error.value.code == "provider_not_configured"
    secrets.active_store().set("gemini_api_key", GEMINI)
    provider_ready()


# --- owner-only transport ---------------------------------------------------------


@pytest.fixture
def owner_app(application_factory, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = application_factory()
    owner, other = str(uuid.uuid4()), str(uuid.uuid4())
    for sid, principal, role in (
        ("renderer", owner, "renderer"),
        ("tray", owner, "resident"),
        ("control", owner, "workspace"),
        ("foreign", other, "renderer"),
    ):
        assert app.sessions.accept(
            sid, {"token": "t", "client_id": principal, "role": role}, "t"
        )
    app.secrets.environ = {}
    app.secrets.send = Sender((200, "{}"))
    return app


ROUTES = {
    "secrets_status": {},
    "secrets_set": {"name": "anthropic_api_key", "value": ANTHROPIC},
    "secrets_test": {"name": "anthropic_api_key"},
    "secrets_clear": {"name": "anthropic_api_key"},
}


def test_routes_are_registered_and_store_is_active(owner_app):
    assert set(ROUTES) <= set(owner_app.sio.handlers["/"])
    assert secrets.active_store() is owner_app.secrets


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ROUTES)
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign", "locked"])
async def test_routes_are_owner_renderer_only(owner_app, name, sid):
    app = owner_app
    app.secrets.set("anthropic_api_key", ANTHROPIC)
    if sid == "locked":
        sid = "renderer"
        app.settings["face_auth_enabled"] = True
    result = await app.sio.handlers["/"][name](sid, ROUTES[name])
    assert result["ok"] is False and result["code"] in {"authentication_required", "permission_denied"}
    assert app.secrets.get("anthropic_api_key") == ANTHROPIC
    assert app.secrets.send.calls == []
    assert ANTHROPIC not in json.dumps(result)


@pytest.mark.asyncio
async def test_owner_set_test_status_clear_never_echo_value(owner_app):
    handlers = owner_app.sio.handlers["/"]
    results = [await handlers[name]("renderer", payload) for name, payload in ROUTES.items()]
    assert all(result["ok"] for result in results)
    status, saved, tested, cleared = results
    assert [item["name"] for item in status["secrets"]][:2] == ["anthropic_api_key", "gemini_api_key"]
    assert not any(item["configured"] for item in status["secrets"])
    assert saved["secret"]["configured"] and saved["secret"]["hint"] == "wxyz"
    assert tested["secret"]["last_check"]["code"] == "ok" and tested["secret"]["verified_at"]
    assert not cleared["secret"]["configured"]
    assert ANTHROPIC not in json.dumps(results)
    owner_app.sio.emit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "anthropic_api_key", "value": "sk-ant-oops"},
        {"name": "anthropic_api_key", "value": GEMINI},
        {"name": "unknown", "value": ANTHROPIC},
        {"name": "anthropic_api_key", "value": ANTHROPIC, "owner": "x"},
        {"name": "anthropic_api_key", "value": 12345},
        {"name": "anthropic_api_key", "value": ANTHROPIC * 20},
        [],
        None,
    ],
)
async def test_invalid_set_requests_store_nothing_and_echo_nothing(owner_app, payload):
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", payload)
    assert result["ok"] is False and result["code"] in {"invalid_format", "invalid_arguments"}
    text = json.dumps(result)
    assert "sk-ant-oops" not in text and GEMINI not in text and ANTHROPIC not in text
    assert owner_app.secrets.get("anthropic_api_key") is None


VERIFIED_SET = {"name": "anthropic_api_key", "value": ANTHROPIC, "verify": True}
PREVIOUS = "sk-ant-api03-" + "Z9y8X7w6V5u4T3s2" * 4 + "prev"


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, PREVIOUS])
async def test_verified_set_rejected_key_stores_nothing(owner_app, previous):
    if previous:
        owner_app.secrets.set("anthropic_api_key", previous)
    owner_app.secrets.send = Sender((401, "{}"))
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", VERIFIED_SET)
    assert result["ok"] is False and result["code"] == "key_rejected"
    assert result["message"] == "This key was rejected by Anthropic."
    assert result["check"]["code"] == "invalid_key" and result["check"]["ok"] is False
    assert owner_app.secrets.get("anthropic_api_key") == previous
    assert len(owner_app.secrets.send.calls) == 1
    assert ANTHROPIC not in json.dumps(result)


@pytest.mark.asyncio
async def test_verified_set_ok_marks_verified(owner_app):
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", VERIFIED_SET)
    assert result["ok"] is True and result["check"]["code"] == "ok"
    assert result["secret"]["verified_at"] and result["secret"]["last_check"]["ok"] is True
    assert owner_app.secrets.get("anthropic_api_key") == ANTHROPIC
    assert owner_app.secrets.send.calls[0][1]["x-api-key"] == ANTHROPIC
    assert ANTHROPIC not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome, code",
    [(httpx.ConnectError("offline"), "network_error"), ((429, ""), "rate_limited"), ((500, ""), "unexpected")],
)
async def test_verified_set_unreachable_saves_unverified(owner_app, outcome, code):
    owner_app.secrets.set("anthropic_api_key", PREVIOUS)
    owner_app.secrets.send = Sender(outcome)
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", VERIFIED_SET)
    assert result["ok"] is True and result["check"]["code"] == code
    assert result["secret"]["verified_at"] is None and result["secret"]["last_check"]["code"] == code
    assert owner_app.secrets.get("anthropic_api_key") == ANTHROPIC
    assert ANTHROPIC not in json.dumps(result)


@pytest.mark.asyncio
async def test_verified_set_checks_format_before_any_request(owner_app):
    payload = {**VERIFIED_SET, "value": "sk-ant-oops"}
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", payload)
    assert result["ok"] is False and result["code"] == "invalid_format"
    assert owner_app.secrets.send.calls == [] and "sk-ant-oops" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["unknown", "tray", "control", "foreign"])
async def test_verified_set_is_owner_renderer_only(owner_app, sid):
    result = await owner_app.sio.handlers["/"]["secrets_set"](sid, VERIFIED_SET)
    assert result["ok"] is False and result["code"] in {"authentication_required", "permission_denied"}
    assert owner_app.secrets.send.calls == [] and owner_app.secrets.get("anthropic_api_key") is None


@pytest.mark.asyncio
async def test_verify_flag_must_be_boolean(owner_app):
    result = await owner_app.sio.handlers["/"]["secrets_set"]("renderer", {**VERIFIED_SET, "verify": "yes"})
    assert result == {"ok": False, "code": "invalid_arguments", "message": "Invalid key request."}
    assert owner_app.secrets.get("anthropic_api_key") is None


# --- CLI ---------------------------------------------------------------------------


def load_cli():
    spec = importlib.util.spec_from_file_location("jarvis_secrets_cli", ROOT / "scripts/jarvis-secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(monkeypatch, capsys, argv, stdin=b""):
    cli = load_cli()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8"))
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, json.loads(out.out), out


@pytest.fixture
def cli_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_cli_reads_stdin_and_never_prints_value(tmp_path, monkeypatch, capsys, cli_env):
    data = str(tmp_path / "db")
    code, result, out = run_cli(
        monkeypatch, capsys, ["--data-dir", data, "set", "anthropic_api_key"], ANTHROPIC.encode() + b"\r\n"
    )
    assert code == 0 and result["saved"] and result["secret"]["hint"] == "wxyz"
    code, result, out = run_cli(monkeypatch, capsys, ["--data-dir", data, "status"])
    assert code == 0 and ANTHROPIC not in out.out + out.err
    assert SecretStore(Database(tmp_path / "db"), environ={}).get("anthropic_api_key") == ANTHROPIC
    code, result, _ = run_cli(monkeypatch, capsys, ["--data-dir", data, "clear", "anthropic_api_key"])
    assert code == 0 and not result["secret"]["configured"]


@pytest.mark.parametrize(
    "argv",
    [
        ["set", "anthropic_api_key", ANTHROPIC],
        ["set", "anthropic_api_key", "--value=" + ANTHROPIC],
        ["set", "anthropic_api_key", "something-else"],
        ["set", GEMINI],
    ],
)
def test_cli_refuses_values_on_argv(tmp_path, monkeypatch, capsys, cli_env, argv):
    cli = load_cli()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(GEMINI.encode()), encoding="utf-8"))
    try:
        code = cli.main(["--data-dir", str(tmp_path / "db"), *argv])
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    assert code == 2
    assert ANTHROPIC not in out.out + out.err and GEMINI not in out.out + out.err
    assert not (tmp_path / "db").exists() or not SecretStore(
        Database(tmp_path / "db"), environ={}
    ).get("anthropic_api_key")


@pytest.mark.parametrize(
    "stdin", [b"", b"\n\n", b"sk-ant-short\n", (ANTHROPIC + "\n" + ANTHROPIC).encode(), b"x" * 5000]
)
def test_cli_invalid_input_exit_code(tmp_path, monkeypatch, capsys, cli_env, stdin):
    code, result, out = run_cli(
        monkeypatch, capsys, ["--data-dir", str(tmp_path / "db"), "set", "anthropic_api_key"], stdin
    )
    assert code == 2 and result["ok"] is False and ANTHROPIC not in out.out


def test_cli_test_and_verify_exit_codes(tmp_path, monkeypatch, capsys, cli_env):
    data = ["--data-dir", str(tmp_path / "db")]
    sender = Sender((401, ""))
    monkeypatch.setattr(secrets, "http_get", sender)
    code, result, _ = run_cli(monkeypatch, capsys, [*data, "test", "anthropic_api_key"])
    assert code == 2 and result["code"] == "not_configured"
    code, result, _ = run_cli(
        monkeypatch, capsys, [*data, "set", "anthropic_api_key", "--verify"], ANTHROPIC.encode()
    )
    assert code == 3 and result["code"] == "invalid_key" and not result["saved"]
    assert "rejected by Anthropic" in result["message"]
    sender.result = httpx.ConnectError("offline")
    code, result, _ = run_cli(
        monkeypatch, capsys, [*data, "set", "anthropic_api_key", "--verify"], ANTHROPIC.encode()
    )
    assert code == 0 and result["saved"] and result["code"] == "network_error"
    assert "Couldn't reach the service" in result["message"]
    sender.result = (200, "{}")
    code, result, _ = run_cli(monkeypatch, capsys, [*data, "test", "anthropic_api_key"])
    assert code == 0 and result["secret"]["verified_at"]
    code, result, _ = run_cli(
        monkeypatch, capsys, [*data, "test", "gemini_api_key", "--stdin"], GEMINI.encode()
    )
    assert code == 0 and result["saved"] is False
    assert not SecretStore(Database(tmp_path / "db"), environ={}).get("gemini_api_key")
    sender.result = (429, "")
    code, result, _ = run_cli(monkeypatch, capsys, [*data, "test", "anthropic_api_key"])
    assert code == 3 and result["code"] == "rate_limited"


def installation(tmp_path, select=True):
    root = tmp_path / "JARVIS Pilot"
    for name in ("versions", "transactions", "data"):
        (root / name).mkdir(parents=True)
    slot, ident = "a" * 64, uuid.uuid4().hex
    (root / "installation.json").write_text(json.dumps({
        "format": 1, "kind": "unsigned-pilot-slots", "id": ident, "generation": 1,
        "current": slot if select else None, "previous": None,
        "slots": {slot: {"manifest_sha256": slot}},
    }))
    (root / "data" / slot).mkdir()
    (root / "data" / slot / ".jarvis-data.json").write_text(
        json.dumps({"format": 1, "installation": ident, "slot": slot})
    )
    return root, slot


def test_cli_installation_root_uses_selected_version_profile(tmp_path, monkeypatch, capsys, cli_env):
    root, slot = installation(tmp_path)
    code, result, _ = run_cli(
        monkeypatch, capsys, ["--installation-root", str(root), "set", "gemini_api_key"], GEMINI.encode()
    )
    assert code == 0, result
    # Same directory the launcher passes as JARVIS_DATA_DIR (data/<slot>/database).
    assert SecretStore(Database(root / "data" / slot / "database"), environ={}).get("gemini_api_key") == GEMINI
    code, result, _ = run_cli(
        monkeypatch, capsys, ["--installation-root", str(root), "--slot", slot, "status"]
    )
    assert code == 0 and result["secrets"][1]["configured"]
    code, result, _ = run_cli(
        monkeypatch, capsys, ["--installation-root", str(root), "--slot", "b" * 64, "status"]
    )
    assert code == 4 and result["code"] == "storage_error"


def test_cli_installation_without_selected_version(tmp_path, monkeypatch, capsys, cli_env):
    root, _ = installation(tmp_path, select=False)
    code, result, _ = run_cli(monkeypatch, capsys, ["--installation-root", str(root), "status"])
    assert code == 4 and "No version is selected" in result["message"]
    code, result, _ = run_cli(monkeypatch, capsys, ["--installation-root", str(tmp_path / "missing"), "status"])
    assert code == 4


def test_cli_default_data_directory_follows_jarvis_data_dir(tmp_path, monkeypatch, capsys, cli_env):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "profile"))
    code, _, _ = run_cli(monkeypatch, capsys, ["set", "gemini_api_key"], GEMINI.encode())
    assert code == 0
    assert SecretStore(Database(tmp_path / "profile"), environ={}).get("gemini_api_key") == GEMINI


def test_cli_subprocess_stdin_end_to_end(tmp_path, cli_env):
    environment = {k: v for k, v in os.environ.items() if k not in {"GEMINI_API_KEY", "ANTHROPIC_API_KEY"}}
    command = [sys.executable, "-I", "-B", str(ROOT / "scripts/jarvis-secrets.py"), "--data-dir", str(tmp_path / "db")]
    done = subprocess.run(
        [*command, "set", "anthropic_api_key"], input=ANTHROPIC.encode(), capture_output=True,
        env=environment, timeout=60,
    )
    assert done.returncode == 0, done.stdout
    assert ANTHROPIC.encode() not in done.stdout + done.stderr
    done = subprocess.run([*command, "status"], capture_output=True, env=environment, timeout=60)
    assert json.loads(done.stdout)["secrets"][0]["hint"] == "wxyz"


# --- TLS scope: provider context only, nothing global ------------------------------


def self_signed_identity(directory):
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jarvis-pinned-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    (directory / "cert.pem").write_text(pem)
    (directory / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    return pem


def memory_handshake(client_context, server_context, hostname):
    """Full TLS handshake over memory BIOs: no sockets, so no local interception."""
    c_in, c_out, s_in, s_out = (ssl.MemoryBIO() for _ in range(4))
    client = client_context.wrap_bio(c_in, c_out, server_hostname=hostname)
    server = server_context.wrap_bio(s_in, s_out, server_side=True)
    done = {"client": False, "server": False}
    for _ in range(50):
        for side, obj in (("client", client), ("server", server)):
            if not done[side]:
                try:
                    obj.do_handshake()
                    done[side] = True
                except ssl.SSLWantReadError:
                    pass
        if c_out.pending:
            s_in.write(c_out.read())
        if s_out.pending:
            c_in.write(s_out.read())
        if all(done.values()):
            return client.version()
    raise AssertionError("handshake did not finish")


def test_pinned_contexts_are_unaffected_by_provider_tls(tmp_path, application_factory):
    pytest.importorskip("cryptography")
    original = ssl.SSLContext
    import services.tls as tls
    import server  # noqa: F401 - full startup imports must not patch ssl either

    application_factory()
    provider = tls.provider_ssl_context()
    assert provider is tls.provider_ssl_context()
    assert ssl.SSLContext is original and ssl.SSLContext.__module__ == "ssl"
    if tls.uses_system_store():
        assert type(provider).__module__.startswith("truststore")
    pem = self_signed_identity(tmp_path)
    pinned = ssl.create_default_context(cadata=pem)
    assert type(pinned) is original
    listener = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    listener.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    assert memory_handshake(pinned, listener, "127.0.0.1")
    # An unrelated, unpinned default context still refuses the self-signed listener.
    with pytest.raises(ssl.SSLCertVerificationError):
        memory_handshake(ssl.create_default_context(), listener, "127.0.0.1")


def test_genai_options_carry_provider_context():
    import services.tls as tls

    options = tls.genai_http_options(api_version="v1beta", client_args={"timeout": 5})
    context = tls.provider_ssl_context()
    assert options["api_version"] == "v1beta" and options["client_args"]["timeout"] == 5
    assert options["client_args"]["verify"] is context
    assert options["async_client_args"]["verify"] is context and options["async_client_args"]["ssl"] is context
