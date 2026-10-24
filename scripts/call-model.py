"""Explicit text-only developer model lab; no phone, speech devices or tool access."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from calls.local_model import LocalModel, ready, fingerprints, require_evaluation, EVALUATION  # noqa: E402
from services.tools import ServiceError  # noqa: E402


async def main(command):
    if command == "preflight":
        try:
            pins = ready()
            installed = True
        except ServiceError:
            pins, installed = {}, False
        try:
            require_evaluation()
            accepted = True
        except ServiceError:
            accepted = False
        return {"installed": installed, "model": pins.get("model", {}).get("id"),
                "accepted_for_calls": accepted, "loaded": False, "physical_verified": False}
    async with LocalModel() as model:
        pid = model.process.pid
        if command == "evaluate":
            from calls.model_evaluation import evaluate
            value = await evaluate(model)
            value["inputs"] = fingerprints()
            value["model"] = ready()["model"]["id"]
        else:
            text = sys.stdin.read(2001)
            value = {"reply": await model.complete("You are INARA, a concise local assistant. You have no tools, private memory or ability to perform actions. State uncertainty honestly. /no_think", text),
                     "preview_only": True}
    import psutil
    value["server_released"] = not psutil.pid_exists(pid)
    if command == "evaluate":
        value["accepted_for_calls"] = value["accepted_for_calls"] and value["server_released"]
        EVALUATION.write_text(json.dumps(value, indent=2) + "\n")
        output = ROOT / ".runtime/local-model/evaluation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2) + "\n")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "evaluate", "chat"))
    args = parser.parse_args()
    try:
        result = asyncio.run(main(args.command))
        print(json.dumps(result, indent=2))
        if args.command == "evaluate" and result.get("accepted_for_calls") is not True:
            raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({"ok": False, "code": exc.code if isinstance(exc, ServiceError) else "local_model_unavailable",
                          "message": str(exc) if isinstance(exc, ServiceError) else "Inspect pinned local setup and runtime compatibility."}))
        raise SystemExit(2)
