"""Actual owned Windows workers using synthetic media; no app/UI/phone/provider."""

import asyncio
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from calls.supervisor import CallSupervisor  # noqa: E402
from calls.records import CallRecords  # noqa: E402
from services.storage import Database  # noqa: E402
from resident.win32 import WorkspaceProcess, api, kernel  # noqa: E402

OUTPUT = ROOT / ".runtime/call-lab-qa" / str(uuid.uuid4())
OUTPUT.mkdir(parents=True)


async def main():
    report = {"passed": False, "real_calls": False, "media_opened": False, "provider_used": False}
    path = OUTPUT / "verification.json"
    path.write_text(json.dumps(report))
    handles = []
    observed_pids = set()
    def keep(pid):
        if pid not in observed_pids:
            handle = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(0x100000, False, pid)
            if handle:
                handles.append(handle)
                observed_pids.add(pid)
    class Owned:
        def __init__(self, executable, entrypoint, bootstrap, cwd):
            self.directory = Path(bootstrap["directory"])
            self.process = WorkspaceProcess(executable, entrypoint, bootstrap, cwd)
            keep(self.process.pid)
        def alive(self):
            marker = self.directory / "descendant.json"
            if marker.exists():
                keep(json.loads(marker.read_text())["pid"])
            return self.process.alive()
        def exit_code(self):
            return self.process.exit_code()
        def close(self):
            self.process.close()
    try:
        records = OUTPUT / "records"
        result = await CallSupervisor(Owned).run({"mode": "offline_fixture", "records_directory": str(records)}, asyncio.Event())
        assert result["state"] == "completed" and result["id"]
        saved = CallRecords(Database(records)).recent()[0]
        assert saved["transcript"] and not saved["identity_verified"]
        report["normal_fixture"] = True
        stop = asyncio.Event()
        supervisor = CallSupervisor(Owned)
        task = asyncio.create_task(supervisor.run({"mode": "offline_fixture", "records_directory": str(records)}, stop))
        await asyncio.sleep(1)
        stop.set()
        result = await task
        assert result["state"] == "interrupted" and supervisor.last_record_id
        report["graceful_stop"] = True
        # The fixed verification entrypoint deliberately hangs with a descendant.
        # It reads only its inherited bootstrap and creates no UI or audio devices.
        entry = OUTPUT / "stalled_fixture.py"
        entry.write_text(
            "import json,sys,subprocess,time\nfrom pathlib import Path\n"
            "request=json.loads(sys.stdin.buffer.read(4097))\n"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)\n"
            "Path(request['directory'],'descendant.json').write_text(json.dumps({'pid':child.pid}))\n"
            "time.sleep(60)\n", encoding="utf-8")
        supervisor = CallSupervisor(Owned, entrypoint=entry, heartbeat_timeout=3)
        from services.tools import ServiceError
        try:
            await supervisor.run({"mode": "offline_fixture"}, asyncio.Event())
            raise AssertionError("Stalled worker should time out")
        except ServiceError as exc:
            assert exc.code == "call_worker_stalled"
        assert len(handles) >= 4, "Observe the real descendant as well as worker handles"
        wait = api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)
        assert all(wait(handle, 5000) == 0 for handle in handles)
        report.update(hung_worker_tree_terminated=True, owned_processes_exited=len(handles), passed=True)
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
        path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        print(f"Evidence: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
