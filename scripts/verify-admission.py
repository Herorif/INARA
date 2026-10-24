"""Owned finite process/lease acceptance, not production grant or resident acceptance."""

import argparse
import ctypes as c
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        "acceptance_" + name, ROOT / "scripts" / (name + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    admission = load("admission")
    signed, launcher = admission.signed, admission.launcher
    runtime = signed.plain(args.runtime, True)
    signed.audit.package.runtime_tool().verify(runtime, ROOT / "requirements-core.lock")
    output = signed.plain(args.output)
    if output.exists() or output.is_relative_to(runtime) or runtime.is_relative_to(output):
        parser.error("Choose a NEW separate acceptance directory")
    output.mkdir(parents=True)
    executable = runtime / "python.exe"
    script, marker = output / "finite.py", output / "finite-result.txt"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('completed')\n")
    with launcher.file_leases([script]):
        try:
            script.write_text("MUST NOT WRITE")
        except PermissionError:
            blocked = True
        else:
            raise AssertionError("Launch input remained writable")
        finite = launcher.run(
            executable,
            ["-I", "-B", str(script)],
            output,
            dict(os.environ),
            datetime.now(timezone.utc) + timedelta(seconds=20),
        )
    assert finite["exit_code"] == 0 and marker.read_text() == "completed"
    expiry = launcher.run(
        executable,
        ["-I", "-c", "import time;time.sleep(30)"],
        output,
        dict(os.environ),
        datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    assert expiry["authorization_expired"] and expiry["exit_code"] != 0
    markers = [output / "child.pid", output / "grandchild.pid"]
    grandchild = (
        "import os,time;from pathlib import Path;"
        f"Path({str(markers[1])!r}).write_text(str(os.getpid()));time.sleep(60)"
    )
    child = (
        "import os,subprocess,sys,time;from pathlib import Path;"
        f"Path({str(markers[0])!r}).write_text(str(os.getpid()));"
        f"subprocess.Popen([sys.executable,'-I','-c',{grandchild!r}]);time.sleep(60)"
    )
    worker = output / "controller-fixture.py"
    worker.write_text(
        "import importlib.util,os,sys\nfrom pathlib import Path\n"
        "from datetime import datetime,timedelta,timezone\n"
        f"spec=importlib.util.spec_from_file_location('guard',{str(Path(launcher.__file__))!r})\n"
        "guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)\n"
        f"code={child!r}\n"
        "guard.run(Path(sys.executable),['-I','-c',code],Path.cwd(),dict(os.environ),"
        "datetime.now(timezone.utc)+timedelta(seconds=60))\n"
    )
    process = subprocess.Popen(
        [str(executable), "-I", "-B", str(worker)],
        cwd=output,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    handles, dll = [], launcher.api()
    dll.OpenProcess.argtypes, dll.OpenProcess.restype = [c.c_ulong, c.c_int, c.c_ulong], c.c_void_p
    try:
        deadline = time.monotonic() + 15
        while (
            not all(p.exists() and p.stat().st_size for p in markers)
            and time.monotonic() < deadline
            and process.poll() is None
        ):
            time.sleep(0.05)
        if not all(p.exists() for p in markers):
            raise ValueError("Owned process tree did not start")
        for path in markers:
            handle = dll.OpenProcess(0x100000, False, int(path.read_text()))
            if not handle:
                raise ValueError("Owned process wait handle unavailable")
            handles.append(handle)
        process.kill()  # This fixture's Popen handle, never an arbitrary process.
        process.wait(timeout=5)
        if not all(dll.WaitForSingleObject(handle, 5000) == 0 for handle in handles):
            raise ValueError("Owned process tree survived controller death")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stderr.close()
        for handle in handles:
            dll.CloseHandle(handle)
    value = {
        "format": 1,
        "kind": "inara-guarded-process-development-acceptance",
        "portable_python": True,
        "finite_process": finite,
        "expired_process": expiry,
        "write_lease_enforced": blocked,
        "controller_death_killed_child_and_grandchild": True,
        "windows_launch_sha256": signed.digest_file(Path(launcher.__file__)),
        "production_grant_signed": False,
        "production_installation_created": False,
        "resident_launched": False,
        "release_authorized": False,
    }
    (output / "result.json").write_bytes(signed.review.encoded(value))
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
