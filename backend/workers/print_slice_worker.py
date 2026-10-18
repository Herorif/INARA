"""Fixed owned slicing worker. Imports legacy slicer dependencies only in the child."""

import asyncio
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    data = json.loads(sys.stdin.buffer.read(4097))
    staging = Path(data["staging"]).resolve()
    if not re.fullmatch(r"[0-9a-f]{32}\.gcode", data["output_name"]):
        raise ValueError("Invalid output name")
    profile = data.get("profile")
    if profile not in (None, "profile.ini", "profile.json"):
        raise ValueError("Invalid profile name")
    try:
        from printer_agent import PrinterAgent

        agent = PrinterAgent()
        result = asyncio.run(
            agent.slice_stl(
                str(staging / "input.stl"),
                output_path=str(staging / data["output_name"]),
                profile_path=str(staging / profile) if profile else None,
                root_path=str(staging),
                printer_name=data["printer_name"],
            )
        )
        ok = result is not None and Path(result).resolve() == staging / data["output_name"]
    except Exception:
        ok = False
    (staging / "result.json").write_text(json.dumps({"ok": ok}), encoding="utf-8")


if __name__ == "__main__":
    main()
