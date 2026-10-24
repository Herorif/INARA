"""Offline native protocol and synthetic call acceptance; never inspects or controls apps."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".runtime/call-bridge/bin/CallControl.exe"


def helper(payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run([str(HELPER)], input=data, capture_output=True, text=True,
                            timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return result.returncode, json.loads(result.stdout)


def main():
    output = ROOT / ".runtime/call-bridge/verification.json"
    report = {"passed": False, "live_call_activated": False, "physical_audio_opened": False,
              "app_ui_inspected": False, "real_api_used": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    subprocess.run([sys.executable, str(ROOT / "scripts/build-call-bridge.py")], check=True, cwd=ROOT)
    code, result = helper({"operation": "selftest"})
    assert code == 0 and result == {"ok": True, "ui_activated": False}
    for invalid in ({"operation": "unknown"}, {"operation": "inspect", "pid": 0}, "x" * 65537):
        code, result = helper(invalid)
        assert code == 2 and result == {"ok": False, "code": "call_binding_unavailable"}
    suite = subprocess.run([sys.executable, "-m", "pytest", "tests/test_call_bridge.py", "-q"], cwd=ROOT, check=True)
    assert suite.returncode == 0
    result = subprocess.run([sys.executable, "scripts/call-bridge.py", "preflight"], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    report.update(passed=True, native_compiled=True, native_invalid_requests_rejected=True,
                  synthetic_suite_passed=True, preflight=json.loads(result.stdout))
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
