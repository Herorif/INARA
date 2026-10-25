"""Run one AI-written legacy build123d script inside the parent's owned job.

The parent (services/legacy_cad.py) owns the deadline and kills this whole
process tree on timeout, cancellation, gaming mode or shutdown. This wrapper
only scrubs provider secrets, pins the working directory to the project's CAD
output folder and records a bounded failure trace for the retry prompt.
It is not a sandbox: the script still runs with the user's file access.
"""

import json
import os
from pathlib import Path
import runpy
import sys
import traceback


def scrub_environment():
    for key in tuple(os.environ):
        upper = key.upper()
        if upper.endswith("_API_KEY") or upper.endswith("_TOKEN"):
            os.environ.pop(key, None)
    # Blank rather than absent, matching call_bridge_worker, so a later
    # load_dotenv() in generated code cannot silently refill these names.
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""


def record(error_path, text):
    try:
        Path(error_path).write_text(text[-8000:], encoding="utf-8")
    except OSError:
        pass


def main():
    data = json.loads(sys.stdin.buffer.read(4097))
    scrub_environment()
    work_dir, script, error_path = Path(data["work_dir"]), Path(data["script"]), data["error"]
    os.chdir(work_dir)
    # Mirror `python script.py`: the script's folder, not this worker's, leads sys.path.
    sys.path[0] = str(script.parent)
    sys.argv = [str(script)]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        record(error_path, f"Generated script exited with status {exc.code!r}.")
        return exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        record(error_path, traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
