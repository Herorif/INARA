"""Optional face adapter process; no model downloads or credentials in argv/env."""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    data = json.loads(sys.stdin.buffer.read(4097))
    folder = Path(data["output"])
    state = {"authenticated": False}

    async def publish():
        raw = json.dumps(state)
        if len(raw.encode()) > 600000:
            return
        temporary = folder / "state.tmp"
        for _ in range(10):
            try:
                temporary.write_text(raw, encoding="utf-8")
                temporary.replace(folder / "state.json")
                return
            except PermissionError:
                await asyncio.sleep(0.02)

    async def status(value):
        state.clear()
        state["authenticated"] = value is True
        await publish()

    async def frame(value):
        if len(value) <= 550000:
            state["frame"] = value
            await publish()

    adapter = None
    try:
        model = Path(__file__).resolve().parents[1] / "face_landmarker.task"
        if not model.is_file() or not Path(data["reference"]).is_file():
            raise RuntimeError("Face setup missing")
        from authenticator import FaceAuthenticator

        adapter = FaceAuthenticator(data["reference"], on_status_change=status, on_frame=frame)
        await adapter.start_authentication_loop()
        # Give thread-origin callbacks time to commit the final result.
        for _ in range(10):
            if state.get("authenticated"):
                return
            await asyncio.sleep(0.02)
        if not state.get("authenticated"):
            raise RuntimeError("Face verification incomplete")
    except Exception:
        state.clear()
        state["error"] = "face_unavailable"
        await publish()
    finally:
        if adapter:
            adapter.stop()


if __name__ == "__main__":
    asyncio.run(main())
