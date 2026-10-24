"""Native resident acceptance for an explicitly selected isolated installation slot."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--slot", required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
slot = args.root.absolute() / "versions" / args.slot
if Path(sys.executable).resolve() != slot / "runtime/python/python.exe":
    parser.error("Use the selected installed Python")
spec = importlib.util.spec_from_file_location(
    "installed_manager", slot / "scripts/desktop-install.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manager = module.Installation(args.root)
state = manager.load()
assert state["current"] == args.slot
manager.check(args.slot)
data = manager.data(state, args.slot)
assert not (data / "settings.json").exists(), "Acceptance requires fresh test data"
assert not (data / "desktop-profile").exists(), "Acceptance never adopts a real profile"
(data / "settings.json").write_text(json.dumps({"face_auth_enabled": False}))
sys.path.insert(0, str(slot / "backend"))
from resident.host import NativeHost  # noqa: E402
from resident.state import Identity  # noqa: E402

Identity(data / "desktop-profile").register(str(uuid.uuid4()))
os.environ["GEMINI_API_KEY"] = "changeme"
os.environ["INARA_IMAGE_MODEL_DIR"] = ""
original_init = NativeHost.__init__
original_run = NativeHost.run
result = {"passed": False}
threads = []


def init(self, *positional, **keywords):
    keywords.update(hide_workspace=True, suppress_notifications=True)
    original_init(self, *positional, **keywords)


def run(self):
    def verify():
        try:
            deadline = time.monotonic() + 60
            while self.state.phase != "ready":
                assert self.state.phase != "failed"
                assert time.monotonic() < deadline
                time.sleep(0.1)
            import application

            assert Path(application.__file__).resolve().is_relative_to(slot)
            assert Path(os.environ["INARA_DATA_DIR"]) == data / "database"
            assert Path(os.environ["INARA_DESKTOP_DATA_DIR"]) == data / "desktop-profile"
            try:
                manager.deactivate()
            except ValueError as exc:
                assert "busy" in str(exc)
            else:
                raise AssertionError("Resident did not retain the manager lock")
            assert self.workspace is None
            app = self.runtime.runtime
            assert all(
                getattr(app, name).instance is None
                for name in ("inara", "vision", "desktop", "devices", "kasa", "printer")
            )
            assert not {"torch", "cv2", "mediapipe", "sounddevice", "google.genai"} & set(
                sys.modules
            )
            result.update(
                passed=True,
                installed_core_used=True,
                bundled_python_used=True,
                isolated_data_used=True,
                resident_lease_blocks_switch=True,
                workspace_started=False,
                model_device_workers_started=0,
            )
        except BaseException:
            result.update(passed=False, error="Installed resident acceptance failed")
        finally:
            self.tray.post(lambda: self.action("quit"))

    worker = threading.Thread(target=verify, daemon=True)
    threads.append(worker)
    worker.start()
    original_run(self)
    worker.join(5)
    result["graceful_core_stop"] = not self.thread.is_alive()


NativeHost.__init__ = init
NativeHost.run = run
try:
    manager.launch(resident_only=True)
except SystemExit as exc:
    assert exc.code == 0
finally:
    NativeHost.__init__ = original_init
    NativeHost.run = original_run
manager.check(args.slot)
assert manager.status()["selected"] == args.slot
result.update(
    package_unchanged_after_run=True,
    lock_released_after_stop=True,
    signed=False,
    clean_machine_acceptance=False,
)
result["passed"] = result["passed"] and result["graceful_core_stop"]
args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
