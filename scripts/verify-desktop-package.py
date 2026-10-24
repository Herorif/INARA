"""Actual staged core/Electron UI with external Python and isolated pilot data."""

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", required=True, type=Path)
args = parser.parse_args()
package = args.directory.resolve()
spec = importlib.util.spec_from_file_location(
    "desktop_package", ROOT / "scripts/desktop-package.py"
)
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)
packaging.verify(package)
output = ROOT / ".runtime/desktop-package-qa" / str(uuid.uuid4())
output.mkdir(parents=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(package / "backend"))
for key, name in [
    ("INARA_DATA_DIR", "database"),
    ("INARA_SETTINGS_FILE", "settings.json"),
    ("INARA_PROJECT_ROOT", "projects"),
    ("INARA_LEGACY_DATA_DIR", "legacy"),
]:
    os.environ[key] = str(output / name)
os.environ["GEMINI_API_KEY"] = "changeme"
os.environ["INARA_IMAGE_MODEL_DIR"] = ""
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ.pop("ELECTRON_RUN_AS_NODE", None)
(output / "settings.json").write_text(json.dumps({"face_auth_enabled": False}))
from resident.host import NativeHost  # noqa: E402
from resident.state import Identity  # noqa: E402
from resident.win32 import WorkspaceProcess, api, kernel, W  # noqa: E402

Identity(output / "profile").register(str(uuid.uuid4()))
launches = []


def workspace(executable, entrypoint, bootstrap, cwd):
    assert executable == package / "runtime/electron/electron.exe"
    assert entrypoint == package / "electron/native-main.cjs"
    launches.append(True)
    bootstrap.update(packagedMain=str(entrypoint), qaOutput=str(output))
    return WorkspaceProcess(executable, ROOT / "scripts/verify-desktop-package.cjs", bootstrap, cwd)


host = NativeHost(
    package,
    output / "profile",
    process_factory=workspace,
    resident_only=True,
    hide_workspace=True,
    suppress_notifications=True,
)
bundled = (package / "runtime/python/python.exe").is_file()
if bundled:
    assert Path(sys.executable).resolve() == package / "runtime/python/python.exe"
    assert all(
        Path(path).resolve().is_relative_to(package / "runtime/python")
        for path in sys.path
        if path != str(package / "backend")
    )
result = {"self_contained": bundled, "signed": False, "external_python_used": not bundled}


def until(predicate):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if predicate():
            return
        if host.state.phase == "failed":
            raise AssertionError(host.state.error)
        time.sleep(0.1)
    raise AssertionError("Staged core/UI acceptance timed out")


def verify():
    try:
        until(lambda: host.state.phase == "ready")
        import application

        assert Path(application.__file__).is_relative_to(package)
        if bundled:
            import fastapi

            assert Path(fastapi.__file__).is_relative_to(package / "runtime/python")
            handles = []
            app = host.runtime.runtime

            def owned_cad(*args):
                assert Path(args[0]).resolve() == package / "runtime/python/python.exe"
                process = WorkspaceProcess(*args)
                handle = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
                    0x100000, False, process.pid
                )
                assert handle
                handles.append(handle)
                return process

            app.cad.process_factory = owned_cad

            async def offline_build():
                from services.cad import BuildRequest

                previous = app.resources.state
                app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
                app.resources.select("studio")
                context = {
                    "principal": host.state.identity.owner,
                    "project_path": app.projects.get_current_project_path(),
                }
                request = BuildRequest(name="Portable core fixture")
                await app.cad.start(request, context)
                await asyncio.gather(*(run["task"] for run in tuple(app.cad.active.values())))
                assert (
                    app.cad.load(context["principal"], context["project_path"], request.request_id)[
                        "state"
                    ]
                    == "succeeded"
                )
                app.resources.select(previous)

            try:
                asyncio.run_coroutine_threadsafe(offline_build(), host.loop).result(40)
                assert len(handles) == 1
                assert (
                    api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)(
                        handles[0], 5000
                    )
                    == 0
                )
            finally:
                for handle in handles:
                    kernel.CloseHandle(handle)
            result.update(
                bundled_binary_dependencies_used=True,
                offline_cad_worker_exited=True,
                offline_creative_workers=1,
            )
        host.tray.post(host.open_workspace)
        until(lambda: (output / "ui-verification.json").exists())
        result["ui"] = json.loads((output / "ui-verification.json").read_text())
        assert result["ui"]["passed"]
        until(lambda: host.workspace is None)
        app = host.runtime.runtime
        assert not app.cad.active and not app.images.active and app.call_lab.active is None
        assert all(
            getattr(app, name).instance is None
            for name in ("inara", "vision", "desktop", "devices", "kasa", "printer")
        )
        assert not {"google.genai", "torch", "cv2", "mediapipe", "sounddevice"} & set(sys.modules)
        assert len(launches) == 1
        result.update(
            passed=True,
            staged_core_used=True,
            staged_electron_used=True,
            node_npm_required=False,
            model_device_workers_started=0,
        )
    except BaseException as error:
        trace = traceback.extract_tb(error.__traceback__)
        result.update(
            passed=False, error="Staged workspace verification failed; inspect local UI evidence.",
            error_type=type(error).__name__, error_file=Path(trace[-1].filename).name,
            error_line=trace[-1].lineno,
        )
    finally:
        host.tray.post(lambda: host.action("quit"))


host.start_core()
worker = threading.Thread(target=verify)
worker.start()
try:
    host.tray.run()
finally:
    host.state.quitting = True
    if host.workspace:
        host.workspace.close()
    if host.server:
        host.server.should_exit = True
    host.thread.join(5)
    worker.join(5)
    host.tray.close()
    result["graceful_core_stop"] = not host.thread.is_alive()
    try:
        packaging.verify(package)
        result["package_unchanged_after_run"] = True
    except ValueError:
        result["package_unchanged_after_run"] = False
    result["passed"] = (
        result.get("passed", False)
        and result["graceful_core_stop"]
        and result["package_unchanged_after_run"]
    )
    (output / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"Evidence: {output}")
sys.exit(0 if result["passed"] else 1)
