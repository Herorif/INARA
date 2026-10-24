"""Explicit Windows bridge diagnostics. Standalone live execution is disabled."""

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from calls.contracts import BridgeProfile  # noqa: E402
from calls.control import DesktopControl  # noqa: E402
from calls.records import CallRecords  # noqa: E402
from calls.local_voice import ready  # noqa: E402
from services.storage import Database, user_data_directory  # noqa: E402
from services.tools import ServiceError  # noqa: E402

HELPER = ROOT / ".runtime/call-bridge/bin/CallControl.exe"


def native(payload):
    if not HELPER.is_file():
        raise ServiceError("call_helper_missing", "Run scripts/build-call-bridge.py first.")
    result = subprocess.run([str(HELPER)], input=json.dumps(payload), text=True,
                            capture_output=True, timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode or len(result.stdout) > 65536:
        raise ServiceError("call_native_unavailable", "The native helper could not inspect this target.")
    return json.loads(result.stdout)


def profile(path):
    raw = Path(path).read_bytes()
    if len(raw) > 16384:
        raise ServiceError("call_profile_invalid", "The enrollment profile is too large.")
    return BridgeProfile.model_validate_json(raw)


async def run(args):
    if os.name != "nt":
        raise ServiceError("call_platform", "The experimental desktop bridge requires Windows.")
    if args.command == "schema":
        return BridgeProfile.model_json_schema()
    if args.command == "preflight":
        try:
            ready()
            voice_ready = True
        except ServiceError:
            voice_ready = False
        return {"mode": "experimental_one_call_lab", "helper_built": HELPER.is_file(),
                "audio_adapter_installed": importlib.util.find_spec("sounddevice") is not None,
                "voice_configured": voice_ready, "voice_mode": "local_structured_english", "cloud_fallback": False, "live_routes_verified": False,
                "resident_auto_start": False, "android_standalone_supported": False}
    if args.command == "inventory":
        return native({"operation": "inventory"})
    if args.command == "inspect":
        return native({"operation": "inspect", "pid": args.pid})
    if args.command == "devices":
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ServiceError("call_audio_missing", "Install the optional requirements-call-bridge.txt adapter when configuring the lab.") from exc
        hosts = sd.query_hostapis()
        return {"devices": [{"name": item["name"], "input_channels": item["max_input_channels"],
                             "output_channels": item["max_output_channels"]}
                            for item in sd.query_devices() if hosts[item["hostapi"]]["name"] == "Windows WASAPI"],
                "audio_opened": False}
    if args.command == "records":
        store = CallRecords(Database(user_data_directory() / "call-bridge-lab"))
        records = store.recent()
        if not args.content:
            records = [{key: item.get(key) for key in ("id", "source", "state", "code", "started_at", "finished_at")} for item in records]
        return {"records": records, "raw_audio_retained": False}
    if args.command == "run":
        raise ServiceError("call_core_required", "Live calls require core-owned admission and controlled physical acceptance. Standalone live execution is disabled; phone tests remain pending.")
    enrolled = profile(args.profile)
    if args.command == "observe":
        observation = await DesktopControl(HELPER, enrolled).observe()
        return {"observation": observation.model_dump(), "action_performed": False}


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "inventory", "devices", "schema"):
        commands.add_parser(name)
    inspect = commands.add_parser("inspect", help="Read control IDs for one explicitly selected process; no clicks")
    inspect.add_argument("--pid", required=True, type=int)
    for name in ("observe", "run"):
        command = commands.add_parser(name)
        command.add_argument("--profile", required=True)
        if name == "run":
            command.add_argument("--live", action="store_true")
            command.add_argument("--arm-seconds", type=int, choices=range(1, 121), default=30, metavar="1..120")
    records = commands.add_parser("records")
    records.add_argument("--content", action="store_true", help="Show your protected caller/assistant transcript locally")
    try:
        result = asyncio.run(run(parser.parse_args()))
        print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        print('{"stopped":true,"note":"Check the call client if termination was uncertain."}')
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "code": exc.code if isinstance(exc, ServiceError) else "call_lab_unavailable",
                          "message": str(exc) if isinstance(exc, ServiceError) else "The call lab could not proceed; inspect enrollment and setup."}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
