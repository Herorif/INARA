"""One request, one fixed read-only operation; parent owns the process tree."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from services.browser_contracts import BrowserInspect  # noqa: E402
from services.browser_fetch import inspect_page  # noqa: E402


def main():
    request = json.loads(sys.stdin.buffer.read(8193))
    directory = Path(request["directory"]).resolve()
    base = ROOT / ".runtime/browser-tasks"
    if directory.parent != base or directory.is_symlink() or directory.is_junction():
        raise ValueError("Invalid browser task directory")
    args = BrowserInspect.model_validate({"url": request["url"]})
    try:
        report = {"ok": True, "report": inspect_page(args.url)}
    except Exception:
        report = {"ok": False}
    (directory / "result.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()
