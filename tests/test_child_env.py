"""S15.2: child processes start with a minimal environment, inside a kill-on-close job."""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import child_env, job_object, mcp_client, world_view
from services.cad_kernel import CadKernel, CadKernelError
from services.child_env import WINDOWS_ESSENTIALS, is_secret_name, minimal_env
from services.mcp_client import build_launch
from services.settings import McpServerConfig

WINDOWS = os.name == "nt"
SECRET = "parent-secret-" + "x" * 24
# Names that must never travel from the core to a child.
PARENT_SECRETS = (
    "ANTHROPIC_API_KEY", "JARVIS_TOKEN", "FOO_SECRET", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "OPENAI_API_KEY", "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID", "JARVIS_SESSION_TOKEN",
    "JARVIS_DATA_DIR", "JARVIS_CLOUDFLARE_TUNNEL_TOKEN", "GITHUB_TOKEN", "DB_PASSWORD",
    "OAUTH_CLIENT", "AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_BASE_URL", "MY_KEYRING",
)
# The Windows essentials the brief names (S15.2).
REQUIRED = (
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
    "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "PATH",
)


@pytest.fixture
def secrets_in_parent(monkeypatch):
    for name in PARENT_SECRETS:
        monkeypatch.setenv(name, SECRET)
    for name in ("NODE_OPTIONS", "PYTHONPATH", "HTTP_PROXY", "ELECTRON_RUN_AS_NODE"):
        monkeypatch.setenv(name, "parent-other")
    monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or r"C:\Windows")
    monkeypatch.setenv("PATH", os.environ.get("PATH") or r"C:\Windows\System32")
    return SECRET


def leaks(env):
    upper = {key.upper() for key in env}
    named = [name for name in PARENT_SECRETS if name in upper]
    valued = [key for key, value in env.items() if SECRET in value]
    return named + valued


# --- the allow-list -----------------------------------------------------------------------------
def test_allow_list_has_the_windows_essentials_and_nothing_secret():
    assert set(REQUIRED) <= set(WINDOWS_ESSENTIALS)
    assert not [name for name in WINDOWS_ESSENTIALS if is_secret_name(name)]
    fake = {name: f"value-{index}" for index, name in enumerate(WINDOWS_ESSENTIALS)}
    fake.update({"LANG": "en_MY.UTF-8", "LC_ALL": "C.UTF-8", "LC_CTYPE": "UTF-8",
                 "NODE_OPTIONS": "--require evil", "PYTHONPATH": "x", "HTTP_PROXY": "p",
                 "USERDOMAIN_ROAMINGPROFILE": "d", "ELECTRON_RUN_AS_NODE": "1"})
    env = minimal_env(environ=fake)
    assert set(env) == set(WINDOWS_ESSENTIALS) | {"LANG", "LC_ALL", "LC_CTYPE"}
    assert all(env[name] == fake[name] for name in env)
    assert "PYTHONIOENCODING" not in env


def test_python_children_get_utf8_io():
    env = minimal_env(python=True, environ={"PYTHONIOENCODING": "cp1252", "SYSTEMROOT": "S"})
    assert env == {"SYSTEMROOT": "S", "PYTHONIOENCODING": "utf-8"}


def test_secret_looking_names_are_never_copied_even_when_kept(secrets_in_parent):
    env = minimal_env(keep=[*PARENT_SECRETS, "NODE_OPTIONS"])
    assert leaks(env) == []
    assert env["NODE_OPTIONS"] == "parent-other"  # keep works for an ordinary name
    assert "PYTHONPATH" not in env and "HTTP_PROXY" not in env
    assert {"SYSTEMROOT", "PATH"} <= {key.upper() for key in env}


@pytest.mark.parametrize("name", ["anthropic_api_key", "Jarvis_Instance_Id", "x_auth", "MyKey",
                                  "google_cloud_project", "twilio_sid", "gemini_model"])
def test_secret_names_match_case_insensitively(name):
    assert is_secret_name(name)
    assert minimal_env(keep=[name], environ={name: SECRET}) == {}


def test_extra_passes_through_and_replaces_any_spelling():
    env = minimal_env(
        {"Path": r"C:\node", "GEV_PROVIDER_KEY": "from-the-store"},
        environ={"PATH": r"C:\parent", "SystemRoot": r"C:\Windows"},
    )
    assert env == {"SystemRoot": r"C:\Windows", "Path": r"C:\node",
                   "GEV_PROVIDER_KEY": "from-the-store"}


@pytest.mark.parametrize("extra", [{"A": 1}, {"A": "x\x00y"}, {"": "x"}, {"A=B": "x"}])
def test_extra_must_be_plain_strings(extra):
    with pytest.raises((TypeError, ValueError)):
        minimal_env(extra, environ={})


# --- per spawn site -----------------------------------------------------------------------------
def world_values(tmp_path, port=4173):
    return {"node": sys.executable, "root": str(tmp_path), "port": port, "idle_minutes": 10,
            "enabled": True}


def test_world_view_globe_gets_gev_variables_and_no_parent_keys(secrets_in_parent, tmp_path):
    values = world_values(tmp_path)
    env = world_view.WorldView.environment(values)
    upper = {key.upper(): value for key, value in env.items()}
    assert leaks({k: v for k, v in env.items() if k not in world_view.AI_KEYS}) == []
    assert all(upper[name] == "" for name in world_view.AI_KEYS)  # blanked, never inherited
    assert upper["NODE_USE_SYSTEM_CA"] == "1"
    assert upper["GEV_ALLOWED_HOSTS"] == "127.0.0.1,localhost"
    assert upper["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)
    assert all(child_env.is_allowed(name) or name in {
        "PATH", "GEV_ALLOWED_HOSTS", "GEV_EMBED_FRAME_ANCESTORS", "NO_COLOR",
        "NODE_USE_SYSTEM_CA", *world_view.AI_KEYS} for name in upper)
    # A GEV provider key from the encrypted store goes through extra only.
    keyed = world_view.WorldView.environment(values, {"GEV_SOME_PROVIDER_KEY": "stored-key"})
    assert keyed["GEV_SOME_PROVIDER_KEY"] == "stored-key"


def test_world_view_globe_binds_loopback_only(tmp_path):
    argv = world_view.WorldView.command(world_values(tmp_path, port=4999))
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in argv and "--strictPort" in argv
    hosts = world_view.ALLOWED_HOSTS.split(",")
    assert set(hosts) == {"127.0.0.1", "localhost"}


async def test_world_view_spawn_runs_in_a_job(monkeypatch):
    calls = []

    async def fake_spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return "process", "job"

    monkeypatch.setattr(job_object, "spawn", fake_spawn)
    assert await world_view.spawn(["node"], "cwd", {"A": "1"}) == ("process", "job")
    (argv, kwargs), = calls
    assert argv == ["node"] and kwargs["env"] == {"A": "1"} and kwargs["cwd"] == "cwd"
    assert kwargs["label"] == "The World view globe"


def test_gev_mcp_server_gets_only_its_configured_env_and_loopback_api(secrets_in_parent,
                                                                     tmp_path):
    from services.world_tools import GevServer

    values = world_values(tmp_path, port=4321)
    tools = SimpleNamespace(app=SimpleNamespace(world=SimpleNamespace(settings=lambda: values)))
    config = GevServer(tools).config()
    launch = build_launch(config, lambda _name: None)
    assert leaks(launch.env) == []
    assert launch.env["NODE_USE_SYSTEM_CA"] == "1"
    assert {name for name in launch.env if not child_env.is_allowed(name)} == {
        "NODE_USE_SYSTEM_CA"}
    api = launch.argv[launch.argv.index("--api-base") + 1]
    assert api == "http://127.0.0.1:4321"


def test_mcp_server_env_is_the_minimal_base_plus_its_configured_env(secrets_in_parent):
    config = McpServerConfig.model_validate({
        "id": "fake", "name": "Fake", "command": [sys.executable, "server.py"],
        "cwd": str(Path(__file__).parent), "default_policy": "never_ask",
        "env": {"FAKE_TOKEN": {"secret": "fake_token"}, "FAKE_PLAIN": "visible"},
    })
    launch = build_launch(config, lambda name: "store-value" if name == "fake_token" else None)
    extras = {name: value for name, value in launch.env.items() if not child_env.is_allowed(name)}
    assert extras == {"FAKE_TOKEN": "store-value", "FAKE_PLAIN": "visible"}
    assert leaks(launch.env) == []
    assert mcp_client.base_environment() == minimal_env()


async def test_mcp_spawn_runs_in_a_job(monkeypatch):
    calls = []

    async def fake_spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return "process", "job"

    monkeypatch.setattr(job_object, "spawn", fake_spawn)
    launch = mcp_client.McpLaunch(["server"], "cwd", {"A": "1"})
    assert await mcp_client.spawn(launch) == ("process", "job")
    (_argv, kwargs), = calls
    assert kwargs["env"] == {"A": "1"} and kwargs["label"] == "An MCP server"
    assert kwargs["stdin"] == asyncio.subprocess.PIPE


async def test_cad_kernel_gets_no_keys_at_all(secrets_in_parent, monkeypatch, tmp_path):
    seen = []

    async def fake_spawn(launch, label=None):
        seen.append((launch, label))
        raise OSError("not started in tests")

    monkeypatch.setattr("services.cad_kernel.spawn", fake_spawn)
    worker = tmp_path / "worker.py"
    worker.write_text("", encoding="utf-8")
    kernel = CadKernel(python=sys.executable, worker=worker, root=tmp_path / "jobs")
    with pytest.raises(CadKernelError):
        await kernel.start()
    (launch, label), = seen
    assert label == "The CAD kernel"
    assert leaks(launch.env) == []
    assert all(child_env.is_allowed(name) or name == "PYTHONIOENCODING" for name in launch.env)


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
def test_workspace_process_gives_the_minimal_env_plus_its_extra(secrets_in_parent, tmp_path):
    """Workers, cloudflared and the Electron windows: a real (Python) child, no sidecar."""
    from resident.win32 import WorkspaceProcess

    script = tmp_path / "child.py"
    report = tmp_path / "env.json"
    script.write_text(
        "import json, os, sys\n"
        "data = json.load(sys.stdin)\n"
        "open(data['report'] + '.tmp', 'w').write(json.dumps(dict(os.environ)))\n"
        "os.replace(data['report'] + '.tmp', data['report'])\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    process = WorkspaceProcess(executable, script, {"report": str(report)}, tmp_path,
                               environment={"TUNNEL_TOKEN": "explicit-extra"})
    try:
        deadline = time.monotonic() + 15
        while not report.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        env = json.loads(report.read_text(encoding="utf-8"))
    finally:
        process.terminate()
    assert leaks(env) == []
    assert env["TUNNEL_TOKEN"] == "explicit-extra"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert "NODE_OPTIONS" not in env and "PYTHONPATH" not in env
    assert all(child_env.is_allowed(name) or name in {"TUNNEL_TOKEN", "PYTHONIOENCODING"}
               for name in env)


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
def test_electron_launch_env_is_minimal_and_not_python(monkeypatch, tmp_path):
    """The overlay and workspace windows: the env is built before anything starts."""
    from resident import win32

    calls = []

    class Stop(Exception):
        pass

    def spy(extra=None, **kwargs):
        calls.append((extra, kwargs))
        raise Stop

    monkeypatch.setattr(win32, "minimal_env", spy)
    with pytest.raises(Stop):
        win32.WorkspaceProcess(tmp_path / "JARVIS.exe", tmp_path / "native-main.cjs",
                               {"token": "bootstrap-only"}, tmp_path)
    assert calls == [(None, {"python": False})]  # the token stays on stdin


# --- the job object -----------------------------------------------------------------------------
class FakeJobs:
    def __init__(self, fail=None):
        self.fail, self.calls, self.next = fail or set(), [], 100

    def step(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise OSError(name)

    def create(self):
        self.next += 1
        self.step("create")
        return self.next

    def assign(self, job, pid):
        self.step("assign", job, pid)

    def resume(self, pid):
        self.step("resume", pid)

    def terminate(self, job):
        self.step("terminate", job)

    def close(self, job):
        self.step("close", job)


@pytest.fixture
def fake_jobs(monkeypatch):
    def install(fail=None):
        layer = FakeJobs(fail)
        monkeypatch.setattr(job_object, "_native", layer)
        monkeypatch.setattr(job_object, "_warned", set())
        return layer
    return install


def test_contain_assigns_then_resumes(fake_jobs):
    layer = fake_jobs()
    job = job_object.contain(42, "A worker")
    assert layer.calls == [("create",), ("assign", 101, 42), ("resume", 42)]
    job.terminate()
    job.close()
    job.close()
    assert layer.calls[3:] == [("terminate", 101), ("close", 101)]


def test_contain_falls_back_and_logs_once(fake_jobs, caplog):
    caplog.set_level(logging.WARNING)
    layer = fake_jobs(fail={"assign"})
    assert job_object.contain(7, "A worker") is None
    assert job_object.contain(8, "A worker") is None
    assert ("resume", 7) in layer.calls and ("resume", 8) in layer.calls
    assert ("close", 101) in layer.calls and ("close", 102) in layer.calls
    warnings = [r for r in caplog.records if "kill-on-close" in r.getMessage()]
    assert len(warnings) == 1 and "OSError" in warnings[0].getMessage()


def test_contain_raises_when_the_process_cannot_resume(fake_jobs):
    layer = fake_jobs(fail={"resume"})
    with pytest.raises(OSError):
        job_object.contain(9)
    assert layer.calls[-1] == ("close", 101)


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
async def test_spawn_starts_suspended_and_assigns_the_job(fake_jobs, monkeypatch):
    layer = fake_jobs()
    seen = {}

    async def fake_exec(*argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(pid=555)

    monkeypatch.setattr(job_object.asyncio, "create_subprocess_exec", fake_exec)
    process, job = await job_object.spawn(["prog", "arg"], cwd="c", env={"A": "1"},
                                          stdout=asyncio.subprocess.PIPE)
    assert process.pid == 555 and job.job == 101
    assert seen["argv"] == ("prog", "arg") and seen["env"] == {"A": "1"}
    assert seen["creationflags"] & job_object.CREATE_SUSPENDED
    assert "shell" not in seen
    assert layer.calls == [("create",), ("assign", 101, 555), ("resume", 555)]


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
async def test_spawn_kills_a_child_it_cannot_resume(fake_jobs, monkeypatch):
    fake_jobs(fail={"resume"})
    killed = []

    class Child:
        pid = 556

        def kill(self):
            killed.append(True)

        async def wait(self):
            return 1

    async def fake_exec(*_argv, **_kwargs):
        return Child()

    monkeypatch.setattr(job_object.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(OSError):
        await job_object.spawn(["prog"], cwd="c", env={})
    assert killed == [True]


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
def test_workspace_process_creates_its_job_through_the_shared_helper(monkeypatch, tmp_path):
    from resident import win32

    made = []

    def fake_create():
        made.append(True)
        raise OSError("no job in this test")

    monkeypatch.setattr(win32, "create_job", fake_create)
    with pytest.raises(OSError):
        win32.WorkspaceProcess(sys.executable, tmp_path / "x.py", None, tmp_path)
    assert made == [True]


@pytest.mark.skipif(not WINDOWS, reason="Windows job objects")
def test_the_real_job_layer_makes_a_kill_on_close_job():
    job = job_object.KillOnCloseJob(job_object.Win32Jobs())
    try:
        assert job.job
    finally:
        job.close()
    assert job.job is None
