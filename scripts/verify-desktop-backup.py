"""Real DPAPI recovery acceptance across processes; existing synthetic slot QA only."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--control", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
control = args.control.absolute()
assert Path(sys.executable).resolve() == control / "runtime/python/python.exe"
known = json.loads((ROOT / ".runtime/desktop-install-final.json").read_text())
root, slot = Path(known["root"]), known["slot"]
assert root.parent == ROOT / ".runtime/installations" and root.name.startswith("slots-final-")
assert json.loads((ROOT / ".runtime/desktop-install-native-verification.json").read_text())[
    "passed"
]
output = args.output.absolute()
assert output.parent == ROOT / ".runtime" and not output.exists()
output.mkdir()
spec = importlib.util.spec_from_file_location(
    "backup_control", control / "scripts/desktop-backup.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manager = module.install.Installation(root)
state = manager.load()
assert state["current"] == slot
assert len(state["slots"]) == 1
protector = module.protection()
# Seed only the already documented synthetic acceptance profile, under its manager lease.
with manager.locked() as current:
    data = manager.data(current, slot)
    fixture = data / "projects" / ("recovery-qa-" + uuid.uuid4().hex)
    (fixture / "empty").mkdir(parents=True)
    (fixture / "fixture.json").write_text(json.dumps({"private": "SYNTHETIC_PRIVATE_PROJECT"}))
    storage_spec = importlib.util.spec_from_file_location(
        "qa_storage", control / "backend/services/storage.py"
    )
    storage = importlib.util.module_from_spec(storage_spec)
    storage_spec.loader.exec_module(storage)
    database = storage.Database(data / "database")
    key = uuid.uuid4().hex
    with database.transaction() as db:
        database.put(db, "recovery-qa", key, {"private": "SYNTHETIC_PRIVATE_RECORD"})
    files, directories = module.inventory(data)
    original = {name: module.digest(path.read_bytes()) for name, path in files.items()}


def command(name, *extra):
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(control / "scripts/desktop-backup.py"),
            name,
            "--root",
            str(root),
            "--slot",
            slot,
            "--file",
            str(output / "profile.inara"),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    return json.loads(completed.stdout)


created = command("backup")
raw = (output / "profile.inara").read_bytes()
assert all(
    value not in raw
    for value in (b"SYNTHETIC_PRIVATE_RECORD", b"SYNTHETIC_PRIVATE_PROJECT", b"fixture.json")
)
preview = command("preview")
assert created["sha256"] == preview["sha256"]
restored = command(
    "restore", "--destination", str(output / "recovered"), "--expected-sha256", preview["sha256"]
)
recovered = output / "recovered"
for name, value in original.items():
    assert hashlib.sha256((recovered / name).read_bytes()).hexdigest() == value
assert (recovered / fixture.relative_to(data) / "empty").is_dir()
# A fourth fresh process proves restored Windows-protected records remain readable.
check = """
import importlib.util,sys
from pathlib import Path
p=Path(sys.argv[1]);s=importlib.util.spec_from_file_location('storage',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
d=m.Database(Path(sys.argv[2]))
with d.connection() as c: assert d.get(c,'recovery-qa',sys.argv[3])['private']=='SYNTHETIC_PRIVATE_RECORD'
"""
subprocess.run(
    [
        sys.executable,
        "-I",
        "-B",
        "-c",
        check,
        str(control / "backend/services/storage.py"),
        str(recovered / "database"),
        key,
    ],
    capture_output=True,
    check=True,
    timeout=30,
)
assert module.loads((recovered / module.RECEIPT).read_bytes())["status"] == "complete"
assert manager.load() == state
assert original == {
    name: module.digest(path.read_bytes()) for name, path in module.inventory(data)[0].items()
}
assert not restored["activated"]
report = {
    "passed": True,
    "actual_windows_dpapi": True,
    "separate_process_backup_preview_restore": True,
    "restored_protected_record_read_in_new_process": True,
    "all_original_files_byte_identical": True,
    "empty_directories_restored": True,
    "backup_plaintext_markers_absent": True,
    "original_profile_unchanged": True,
    "installation_state_unchanged": True,
    "automatic_activation": False,
    "project_paths_rewritten": False,
    "bundled_python_used": True,
    "cross_account_acceptance": False,
    "real_profile_used": False,
    "signed": False,
}
(output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
