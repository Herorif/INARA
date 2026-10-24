"""Private bootstrap only. Parent job/watchdog owns audio and all helper descendants."""

import asyncio
import json
import os
from pathlib import Path
import sys
from functools import partial

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from calls.contracts import BridgeProfile  # noqa: E402
from calls.lab_contracts import WorkerResult  # noqa: E402
from calls.records import CallRecords  # noqa: E402
from calls.session import CallSession  # noqa: E402
from services.storage import Database  # noqa: E402


def atomic(directory, name, value):
    temporary = directory / (name + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(directory / name)


async def main(request):
    directory = Path(request["directory"]).resolve()
    base = ROOT / ".runtime/call-bridge-runs"
    if directory.parent != base or directory.is_symlink() or directory.is_junction():
        raise ValueError("Invalid worker staging")
    mode = request["mode"]
    if mode not in {"offline_fixture", "live"}:
        raise ValueError("Unknown mode")
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["INARA_CALL_MODEL"] = ""
    if mode == "offline_fixture":
        from calls.fixture import fixture_profile, FixtureAudio, FixtureControl, FixtureVoice
        profile, control, audio, voice = fixture_profile(), FixtureControl(), FixtureAudio(), FixtureVoice().connection
    else:
        from calls.audio import DedicatedAudio
        from calls.control import DesktopControl
        if request.get("voice_mode") != "local":
            raise ValueError("This live lab requires explicit local-only voice; no cloud fallback")
        from calls.local_voice import connect_voice
        dialogue_mode = request.get("dialogue_mode", "structured")
        if dialogue_mode not in {"structured", "model"}:
            raise ValueError("Unknown local dialogue mode")
        profile = BridgeProfile.model_validate(request["profile"])
        control = DesktopControl(ROOT / ".runtime/call-bridge/bin/CallControl.exe", profile)
        audio, voice = DedicatedAudio(profile), partial(connect_voice, conversational=dialogue_mode == "model")
    class WorkerRecords(CallRecords):
        def claim(self, channel, observation):
            key, value = super().claim(channel, observation)
            atomic(directory, "record.json", {"id": value["id"]})
            return key, value
    records = WorkerRecords(Database(Path(request["records_directory"])))
    session = CallSession(profile, control, audio, voice, records)
    async def heartbeat():
        sequence = 0
        while True:
            atomic(directory, "heartbeat.json", {"sequence": sequence})
            sequence += 1
            await asyncio.sleep(0.25)
    async def stop_watch(task):
        while not (directory / "stop").exists():
            await asyncio.sleep(0.05)
        task.cancel()
    pulse = asyncio.create_task(heartbeat())
    task = asyncio.create_task(session.run(request.get("arm_seconds", 30)))
    stopper = asyncio.create_task(stop_watch(task))
    result = None
    try:
        result = await task
    except asyncio.CancelledError:
        result = session.record
    except Exception:
        result = session.record
    finally:
        for owned in (pulse, stopper):
            owned.cancel()
        await asyncio.gather(pulse, stopper, return_exceptions=True)
    value = WorkerResult(ok=True, mode=mode, id=result.get("id") if result else None,
                         state=result.get("state", "uncertain") if result else "failed",
                         code=result.get("code") if result else "call_worker_preparation_failed")
    atomic(directory, "result.json", value.model_dump(mode="json"))


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.stdin.buffer.read(4097))))
