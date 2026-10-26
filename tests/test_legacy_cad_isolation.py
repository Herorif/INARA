"""Legacy AI-written CAD code: separate default-deny permission and owned execution.

No network and no model calls: the code generator is faked and the "generated"
scripts are tiny Python programs that sleep, spawn a grandchild or write files.
Process tests use the real WorkspaceProcess (Windows Job Object) machinery.
"""

import asyncio
import ctypes
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock

import pytest

from services.tools import (
    DEFAULT_DENY_PERMISSIONS,
    LEGACY_GENERATED_CAD_PERMISSION,
    ServiceError,
    permission_policy,
)
from services.workspace import WORKSPACE_TOOLS

windows_only = pytest.mark.skipif(os.name != "nt", reason="Owned workers require Windows")
LEGACY_TOOLS = ("legacy_generate_cad", "iterate_cad", "generate_cad_prototype")


def process_alive(pid):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        kernel.CloseHandle(handle)


def owner_app(application_factory, **overrides):
    app = application_factory(**overrides)
    app.sessions.principals["client"] = "owner"
    app.sessions.roles["client"] = "renderer"
    app.sessions.local_owner = "owner"
    app.workspace.preflight = lambda: None
    return app


def context(app):
    return {**app.sessions.context("client").tools(), "origin_sid": "client"}


def legacy_folder(app):
    return app.projects.get_current_project_path().resolve() / "cad" / "legacy"


class RecordingLock(asyncio.Lock):
    """Records, at the moment the creative lock is released, which child pids still run."""

    def __init__(self, folder):
        super().__init__()
        self.folder, self.observed = folder, []

    def release(self):
        self.observed.append(
            {p.name: process_alive(int(p.read_text())) for p in self.folder.glob("*.pid")}
        )
        super().release()


def fake_agent(code, timeout=None):
    """Real CadAgent with a faked generator, using the workspace-provided runner."""
    from cad_agent import CadAgent

    def factory(runner, **kwargs):
        if timeout is not None:
            runner.timeout = timeout
        agent = CadAgent(client=object(), runner=runner, **kwargs)
        agent.request_code = AsyncMock(return_value=f"```python\n{code}\n```")
        return agent

    return factory


PID_AND_SLEEP = """
import os, subprocess, sys, time
open("root.pid", "w").write(str(os.getpid()))
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open("grandchild.pid", "w").write(str(child.pid))
time.sleep(120)
"""


# --- Permission split -------------------------------------------------------


def test_legacy_tools_use_their_own_default_deny_permission():
    import server

    assert LEGACY_GENERATED_CAD_PERMISSION == "legacy_generated_cad"
    assert LEGACY_GENERATED_CAD_PERMISSION in DEFAULT_DENY_PERMISSIONS
    for name in ("legacy_generate_cad", "iterate_cad"):
        assert WORKSPACE_TOOLS[name][1] == "legacy_generated_cad"
    assert server.DEFAULT_SETTINGS["tool_permissions"]["legacy_generated_cad"] == "deny"
    assert permission_policy({}, "legacy_generated_cad") == "deny"
    assert permission_policy({}, "generate_cad") is True  # other keys still default to ask
    for name in LEGACY_TOOLS:
        assert server.dispatcher.tools[name].permission == "legacy_generated_cad"
    assert server.dispatcher.tools["generate_cad"].permission is None


@pytest.mark.asyncio
@pytest.mark.parametrize("relaxed", [False, "allow_within_scope"])
@pytest.mark.parametrize("name", LEGACY_TOOLS)
async def test_allowing_safe_generate_cad_does_not_allow_generated_code(
    application_factory, name, relaxed
):
    app = owner_app(application_factory)
    app.settings["tool_permissions"]["generate_cad"] = relaxed
    app.workspace.cad_factory = lambda **kwargs: pytest.fail("Generated code must not run")
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch("owner", name, {"prompt": "box"}, context(app))
    assert error.value.code == "permission_denied"


@pytest.mark.asyncio
async def test_settings_file_without_the_key_resolves_to_deny(application_factory, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "face_auth_enabled": False,
                "kasa_devices": [],
                "tool_permissions": {"generate_cad": False, "iterate_cad": False},
            }
        ),
        encoding="utf-8",
    )
    app = owner_app(application_factory, settings=json.loads(path.read_text(encoding="utf-8")))
    app.workspace.cad_factory = lambda **kwargs: pytest.fail("Generated code must not run")
    for name in LEGACY_TOOLS:
        with pytest.raises(ServiceError) as error:
            await app.dispatcher.dispatch("owner", name, {"prompt": "box"}, context(app))
        assert error.value.code == "permission_denied"


@pytest.mark.asyncio
async def test_settings_patch_accepts_the_new_key_and_its_three_policies(application_factory):
    from services.settings import SettingsPatch

    app = owner_app(application_factory)
    for value in ("deny", True, "allow_within_scope"):
        snapshot = app.settings_service.apply(
            SettingsPatch(tool_permissions={"legacy_generated_cad": value})
        )
        assert snapshot["tool_permissions"]["legacy_generated_cad"] == value
    reached = []

    async def generate(prompt, output_dir):
        reached.append(prompt)
        return None

    app.workspace.cad_factory = lambda **kwargs: type(
        "Agent", (), {"generate_prototype": staticmethod(generate)}
    )()
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", "legacy_generate_cad", {"prompt": "box"}, context(app)
        )
    assert error.value.code == "cad_failed" and reached == ["box"]


# --- Owned execution --------------------------------------------------------


@windows_only
@pytest.mark.asyncio
async def test_timeout_kills_tree_and_lock_released_only_after_exit(application_factory):
    app = owner_app(application_factory)
    app.settings["tool_permissions"]["legacy_generated_cad"] = "allow_within_scope"
    folder = legacy_folder(app)
    folder.mkdir(parents=True, exist_ok=True)
    lock = app.resources.creative_lock = RecordingLock(folder)
    app.workspace.cad_factory = fake_agent(PID_AND_SLEEP, timeout=6)
    with pytest.raises(ServiceError) as error:
        await app.dispatcher.dispatch(
            "owner", "legacy_generate_cad", {"prompt": "box"}, context(app)
        )
    assert error.value.code == "legacy_cad_timeout"
    assert "6s limit" in str(error.value) and "terminated" in str(error.value)
    pids = {p.name: int(p.read_text()) for p in folder.glob("*.pid")}
    assert set(pids) == {"root.pid", "grandchild.pid"}
    assert lock.observed == [{"root.pid": False, "grandchild.pid": False}]
    assert not lock.locked() and not any(process_alive(pid) for pid in pids.values())


@windows_only
@pytest.mark.asyncio
async def test_cancellation_kills_the_child_tree(application_factory):
    app = owner_app(application_factory)
    app.settings["tool_permissions"]["legacy_generated_cad"] = "allow_within_scope"
    folder = legacy_folder(app)
    folder.mkdir(parents=True, exist_ok=True)
    lock = app.resources.creative_lock = RecordingLock(folder)
    app.workspace.cad_factory = fake_agent(PID_AND_SLEEP)
    task = asyncio.create_task(
        app.dispatcher.dispatch("owner", "legacy_generate_cad", {"prompt": "box"}, context(app))
    )
    for _ in range(600):
        if (folder / "grandchild.pid").is_file() and (folder / "grandchild.pid").read_text():
            break
        await asyncio.sleep(0.05)
    pids = [int((folder / name).read_text()) for name in ("root.pid", "grandchild.pid")]
    assert all(process_alive(pid) for pid in pids)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert lock.observed == [{"root.pid": False, "grandchild.pid": False}]
    assert not any(process_alive(pid) for pid in pids) and not lock.locked()


@windows_only
@pytest.mark.asyncio
async def test_gaming_mode_stops_the_child(application_factory):
    app = owner_app(application_factory)
    app.settings["tool_permissions"]["legacy_generated_cad"] = "allow_within_scope"
    folder = legacy_folder(app)
    folder.mkdir(parents=True, exist_ok=True)
    app.workspace.cad_factory = fake_agent(PID_AND_SLEEP)
    task = asyncio.create_task(
        app.dispatcher.dispatch("owner", "legacy_generate_cad", {"prompt": "box"}, context(app))
    )
    for _ in range(600):
        if (folder / "grandchild.pid").is_file() and (folder / "grandchild.pid").read_text():
            break
        await asyncio.sleep(0.05)
    pids = [int((folder / name).read_text()) for name in ("root.pid", "grandchild.pid")]
    app.resources.select("gaming")
    with pytest.raises(ServiceError) as error:
        await task
    assert error.value.code == "job_cancelled"
    assert not any(process_alive(pid) for pid in pids)


@windows_only
@pytest.mark.asyncio
async def test_output_and_cwd_are_the_project_cad_folder(application_factory, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-fixture")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret-fixture")
    monkeypatch.setenv("EXTRA_SERVICE_API_KEY", "extra-secret-fixture")
    app = owner_app(application_factory)
    app.settings["tool_permissions"]["legacy_generated_cad"] = "allow_within_scope"
    folder = legacy_folder(app)
    code = """
import json, os
open("cwd.txt", "w").write(os.getcwd())
open("env.json", "w").write(json.dumps(dict(os.environ)))
open('output.stl', "w").write("solid fixture\\nendsolid fixture\\n")
"""
    app.workspace.cad_factory = fake_agent(code)
    result = await app.dispatcher.dispatch(
        "owner", "legacy_generate_cad", {"prompt": "box"}, context(app)
    )
    assert result["message"] == "Design generated"
    stls = list(folder.glob("output_*.stl"))
    assert len(stls) == 1 and stls[0].read_text().startswith("solid fixture")
    assert Path((folder / "cwd.txt").read_text()).resolve() == folder
    assert (folder / "current_design.py").is_file()
    assert folder != Path(tempfile.gettempdir()).resolve()
    assert not (folder / ".legacy_cad_error.txt").exists()
    raw = (folder / "env.json").read_text()
    environment = json.loads(raw)
    assert "secret-fixture" not in raw
    assert environment.get("GEMINI_API_KEY", "") == ""
    assert environment.get("ANTHROPIC_API_KEY", "") == ""
    assert "EXTRA_SERVICE_API_KEY" not in environment
    assert not app.resources.creative_lock.locked()


@windows_only
@pytest.mark.asyncio
async def test_iterate_fallback_keeps_project_output_dir(tmp_path):
    from cad_agent import CadAgent
    from services.legacy_cad import LegacyScriptRunner

    folder = (tmp_path / "project" / "cad" / "legacy").resolve()
    agent = CadAgent(client=object(), runner=LegacyScriptRunner())
    agent.request_code = AsyncMock(
        return_value="```python\nopen('output.stl', 'w').write('solid x')\n```"
    )
    result = await agent.iterate_prototype("wider", output_dir=str(folder))  # no script yet
    assert Path(result["file_path"]).parent == folder
    with pytest.raises(ServiceError) as error:
        await agent.generate_prototype("box")
    assert error.value.code == "cad_output_required"


@windows_only
@pytest.mark.asyncio
async def test_failing_script_reports_traceback_for_retry(tmp_path):
    from services.legacy_cad import LegacyScriptRunner

    script = tmp_path / "current_design.py"
    script.write_text("raise ValueError('fixture failure')\n", encoding="utf-8")
    code, text = await LegacyScriptRunner().run(script, tmp_path)
    assert code == 1 and "ValueError: fixture failure" in text
    assert not (tmp_path / ".legacy_cad_error.txt").exists()
