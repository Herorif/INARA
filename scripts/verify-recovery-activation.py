"""Native recovery activation acceptance: documented synthetic installation only."""

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--control", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repeat-from", type=Path)
args = parser.parse_args()
control = args.control.absolute()
known = json.loads((ROOT / ".runtime/desktop-install-slots.json").read_text())
root, slot = Path(known["root"]), known["b"]
assert root == ROOT / ".runtime/installations/slots-20261021"
package = root / "versions" / slot
assert Path(sys.executable).resolve() == package / "runtime/python/python.exe"
output = args.output.absolute()
assert output.parent == ROOT / ".runtime" and not output.exists()
output.mkdir()
spec = importlib.util.spec_from_file_location(
    "recovery_control", control / "scripts/desktop-recovery.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manager = module.install.Installation(root)
state = manager.load()
assert state["current"] == slot
original = manager.data(state, slot)
if args.repeat_from is None:
    assert not (original / "database").exists() and not (original / "desktop-profile").exists()
else:
    prior = args.repeat_from.absolute()
    assert prior.parent == ROOT / ".runtime" and prior.name.startswith("recovery-activation-qa-")
    assert json.loads((prior / "verification.json").read_text())["passed"]
sys.path.insert(0, str(package / "backend"))
from application import create_application  # noqa: E402
from services.storage import Database, scope_hash  # noqa: E402
from services.memory_contracts import MemoryWrite  # noqa: E402
from services.cad import Recipe  # noqa: E402
from resident.state import Identity  # noqa: E402
from resident.host import NativeHost  # noqa: E402

if args.repeat_from is None:
    owner, conversation, request, job = (str(uuid.uuid4()) for _ in range(4))
    Identity(original / "desktop-profile").register(owner)
    settings = {"face_auth_enabled": False, "tool_permissions": {}, "kasa_devices": []}
    (original / "settings.json").write_text(json.dumps(settings))
    os.environ["GEMINI_API_KEY"] = "changeme"
    os.environ["INARA_IMAGE_MODEL_DIR"] = ""
    with manager.locked():
        database = Database(original / "database")
        app = create_application(
            settings=settings,
            project_root=original / "projects",
            database=database,
            legacy_data_dir=original / "legacy",
        )
        app.sessions.attach_native(owner)
        app.projects.switch_project("temp")
        project = app.projects.get_current_project_path().resolve()
        snapshot = app.memory.snapshot(owner, project)
        literal = "Keep this literal historical path: " + str(project)
        app.memory.write(
            owner,
            project,
            MemoryWrite(
                revision=snapshot["revision"],
                id=uuid.uuid4(),
                title="Recovery fixture",
                text=literal,
            ),
        )
        app.conversation.store.claim(conversation, owner, str(project), request, "fixture")
        app.conversation.store.finish(
            conversation,
            owner,
            str(project),
            request,
            "fixture",
            {"state": "succeeded", "result": {"text": "fixture"}},
            [{"role": "user", "content": literal}],
        )
        relative = "cad/designs/" + str(uuid.uuid4())
        artifact = project / relative / "model.stl"
        artifact.parent.mkdir(parents=True)
        raw = b"solid recovery_fixture\nendsolid recovery_fixture\n"
        artifact.write_bytes(raw)
        with database.transaction() as db:
            database.put(
                db,
                "cad_jobs:" + scope_hash(owner + ":" + str(project)),
                job,
                {
                    "request_id": job,
                    "project": project.name,
                    "recipe": Recipe().model_dump(),
                    "state": "succeeded",
                    "phase": "ready",
                    "created_at": time.time(),
                    "error": None,
                    "reference": None,
                    "directory": relative,
                    "artifacts": {"stl": {"bytes": len(raw), "sha256": module.backup.digest(raw)}},
                },
            )
else:
    database = Database(original / "database")
    owner = json.loads((original / "desktop-profile/resident-identity.json").read_text())["id"]
    with database.connection() as db:
        sessions = db.execute("SELECT id FROM sessions").fetchall()
        jobs = db.execute("SELECT kind,id FROM documents WHERE kind LIKE 'cad_jobs:%'").fetchall()
        assert len(sessions) == 1 and len(jobs) == 1
        conversation = sessions[0]["id"]
        job = jobs[0]["id"]
        value = database.get(db, jobs[0]["kind"], job)
        relative = value["directory"]
    project = (original / "projects/projects/temp").resolve()
    raw = (project / relative / "model.stl").read_bytes()
    literal = "Keep this literal historical path: " + str(project)
    os.environ["GEMINI_API_KEY"] = "changeme"
    os.environ["INARA_IMAGE_MODEL_DIR"] = ""
source_hashes = {
    name: module.backup.digest(path.read_bytes())
    for name, path in module.backup.inventory(original)[0].items()
}
service = module.Activation(manager)
archive = output / "profile.inara"
service.recovery.backup(slot, archive)
pid = uuid.uuid4().hex
review = service.preview(slot, archive, pid)
service.prepare(slot, archive, pid, review["review_sha256"])
assert manager.data(manager.load(), slot) == original
service.activate(slot, pid, review["review_sha256"])
recovered = manager.data(manager.load(), slot)
assert recovered != original
legacy = subprocess.run(
    [
        sys.executable,
        "-I",
        "-B",
        str(package / "scripts/desktop-install.py"),
        "status",
        "--root",
        str(root),
    ],
    capture_output=True,
    text=True,
)
assert legacy.returncode != 0

# A fresh composition root inside the native host must consume the rebound records.
original_init, original_run = NativeHost.__init__, NativeHost.run
result = {"passed": False}


def init(self, *positional, **keywords):
    keywords.update(hide_workspace=True, suppress_notifications=True)
    original_init(self, *positional, **keywords)


def run(self):
    def verify():
        try:
            deadline = time.monotonic() + 60
            while self.state.phase != "ready":
                assert self.state.phase != "failed" and time.monotonic() < deadline
                time.sleep(0.1)
            runtime = self.runtime.runtime
            target = runtime.projects.get_current_project_path().resolve()
            assert target.is_relative_to(recovered)
            assert runtime.memory.snapshot(owner, target)["items"][0]["text"] == literal
            assert (
                runtime.conversation.restore(owner, conversation, target)[0]["content"] == literal
            )
            export = runtime.cad.artifact(
                owner, target, SimpleNamespace(request_id=job, format="stl")
            )
            assert base64.b64decode(export["data"]) == raw
            try:
                manager.deactivate()
            except ValueError:
                pass
            else:
                raise AssertionError("Resident did not retain its lease")
            assert self.workspace is None
            assert all(
                getattr(runtime, name).instance is None
                for name in ("inara", "vision", "desktop", "devices", "kasa", "printer")
            )
            assert not {"torch", "cv2", "mediapipe", "sounddevice", "google.genai"} & set(
                sys.modules
            )
            result.update(
                passed=True,
                restored_memory_accessible=True,
                restored_conversation_accessible=True,
                fixture_cad_artifact_accessible=True,
                literal_message_paths_preserved=True,
                recovered_profile_used_by_native_resident=True,
                resident_lease_retained=True,
                model_device_workers_started=0,
            )
        except BaseException:
            result.update(passed=False, error="Recovered native resident verification failed")
        finally:
            self.tray.post(lambda: self.action("quit"))

    worker = threading.Thread(target=verify, daemon=True)
    worker.start()
    original_run(self)
    worker.join(5)
    result["graceful_core_stop"] = not self.thread.is_alive()


NativeHost.__init__, NativeHost.run = init, run
try:
    manager.launch(resident_only=True)
except SystemExit as exc:
    assert exc.code == 0
finally:
    NativeHost.__init__, NativeHost.run = original_init, original_run
service.rollback(slot)
assert manager.data(manager.load(), slot) == original
assert source_hashes == {
    name: module.backup.digest(path.read_bytes())
    for name, path in module.backup.inventory(original)[0].items()
}
assert recovered.is_dir() and archive.is_file()
manager.check(slot)
result.update(
    rollback_to_original_passed=True,
    original_profile_byte_identical=True,
    recovery_copy_and_encrypted_backup_retained=True,
    installed_package_unchanged=True,
    older_control_refused_upgraded_state=True,
    real_profile_used=False,
    signed=False,
)
result["passed"] = result["passed"] and result["graceful_core_stop"]
(output / "verification.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
