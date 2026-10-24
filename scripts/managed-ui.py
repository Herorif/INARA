"""Private finite management worker. No network, signing, payload dispatch or launch."""

import importlib.util
import json
from pathlib import Path
import secrets
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("managed_ui_backend", ROOT / "scripts/managed-update.py")
managed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(managed)
COMMON = {"operation", "root", "anchor", "expected_state"}
CHANGE = {"action", "expected_head", "policy", "expected_policy", "windows_policy", "expected_windows_policy", "grant", "change"}
OPTIONAL = {"package", "next_policy", "expected_next_policy", "next_windows_policy", "expected_next_windows_policy"}


def path(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("Choose a bounded local absolute path")
    result = Path(value)
    if not result.is_absolute() or result.drive.startswith("\\\\"):
        raise ValueError("Choose a local absolute path")
    return managed.signed.plain(result)


def pin(value, allow_new=False):
    if allow_new and value == "new":
        return value
    managed.trust.digest(value)
    return value


def request(value):
    if not isinstance(value, dict):
        raise ValueError("Expected management request")
    op = value.get("operation")
    extra = CHANGE if op == "change" else {"previous_state"} if op in {"resume", "abort"} else {"change"} if op == "lifecycle" else {"copy_action", "slot", "file"} if op == "copy" else set()
    required = COMMON | extra
    optional = OPTIONAL if op == "change" else {"profile"} if op == "copy" else set()
    if op not in {"status", "change", "resume", "abort", "copy", "lifecycle"} or not required <= set(value) or set(value) - required - optional:
        raise ValueError("Unsupported management operation or fields")
    normalized = dict(value)
    for key in ("root", "anchor"):
        normalized[key] = str(path(value[key]))
    pin(value["expected_state"], allow_new=op == "change")
    if op in {"resume", "abort"}:
        pin(value["previous_state"], True)
    if op == "lifecycle":
        normalized["change"] = str(path(value["change"]))
    if op == "copy":
        if value["copy_action"] not in {"backup", "prepare-profile"}:
            raise ValueError("Unsupported profile copy action")
        managed.signed.manager.identifier(value["slot"])
        normalized["file"] = str(path(value["file"]))
        if value["copy_action"] == "prepare-profile":
            managed.module("managed-lifecycle").recovery.profile_id(value.get("profile"))
        elif "profile" in value:
            raise ValueError("Backup uses the selected profile")
    if op == "change":
        if value["action"] not in {"enroll", "renew", "rotate", "update", "rollback"}:
            raise ValueError("Unsupported signed change")
        for key in ("expected_head", "expected_policy", "expected_windows_policy"):
            pin(value[key])
        for key in ("policy", "windows_policy", "grant", "change"):
            normalized[key] = str(path(value[key]))
        if "package" in value:
            normalized["package"] = str(path(value["package"]))
        for key, digest in (("next_policy", "expected_next_policy"), ("next_windows_policy", "expected_next_windows_policy")):
            if (key in value) != (digest in value):
                raise ValueError("Proposed trust requires both file and independent pin")
            if key in value:
                normalized[key] = str(path(value[key]))
                pin(value[digest])
    return normalized


class Control:
    def __init__(self, clock=time.monotonic):
        self.clock, self.pending = clock, None

    def invoke(self, value, reviewed=None, confirmation=""):
        op = value["operation"]
        common = (Path(value["root"]), Path(value["anchor"]), value["expected_state"])
        if op == "status":
            return managed.status(*common)
        if op == "copy":
            return managed.module("managed-lifecycle").copies(*common, value["copy_action"], value["slot"], Path(value["file"]), value.get("profile"), reviewed)
        if op == "lifecycle":
            return managed.module("managed-lifecycle").apply(*common, Path(value["change"]), reviewed, confirmation)
        if op in {"resume", "abort"}:
            return getattr(managed, op)(*common, value["previous_state"], reviewed, **({"confirmation": confirmation} if confirmation and op == "resume" else {}))
        cfg = managed.inputs(
            *common, value["expected_head"], Path(value["policy"]), value["expected_policy"],
            Path(value["windows_policy"]), value["expected_windows_policy"],
            Path(value["next_policy"]) if "next_policy" in value else None, value.get("expected_next_policy"),
            Path(value["next_windows_policy"]) if "next_windows_policy" in value else None, value.get("expected_next_windows_policy"),
        )
        return managed.change(cfg, value["action"], Path(value["grant"]), Path(value["change"]),
                              Path(value["package"]) if "package" in value else None, reviewed)

    def dispatch(self, message):
        # Every status, replacement review, cancellation or malformed request revokes the old review.
        previous, self.pending = self.pending, None
        if not isinstance(message, dict):
            raise ValueError("Expected management message")
        op = message.get("op")
        if op == "discard" and set(message) == {"op"}:
            return {"discarded": True}
        if op in {"status", "review"} and set(message) == {"op", "request"}:
            value = request(message["request"])
            if (op == "status") != (value["operation"] == "status"):
                raise ValueError("Use a separate status or mutation review")
            result = self.invoke(value)
            if op == "status":
                return result
            managed.review.exact(result, {"plan", "review_sha256"})
            pin(result["review_sha256"])
            token = secrets.token_hex(32)
            self.pending = (token, self.clock() + 300, value, result["review_sha256"])
            return {"token": token, "expires_in_seconds": 300, "operation": value["operation"],
                    "action": value.get("action"), "root": value["root"], "anchor": value["anchor"], **result}
        if op == "apply" and {"op", "token", "request"} <= set(message) <= {"op", "token", "request", "confirmation"}:
            if previous is None or not isinstance(message["token"], str) or not secrets.compare_digest(message["token"], previous[0]):
                raise ValueError("Review is missing or already consumed")
            if self.clock() >= previous[1]:
                raise ValueError("Review expired; review again")
            value = request(message["request"])
            if value != previous[2]:
                raise ValueError("Inputs changed; review again")
            return self.invoke(value, previous[3], **({"confirmation": message["confirmation"]} if "confirmation" in message else {}))
        raise ValueError("Unsupported management message")


def serve(incoming=None, outgoing=None):
    incoming = sys.stdin.buffer if incoming is None else incoming
    outgoing = sys.stdout if outgoing is None else outgoing
    control = Control()

    def emit(value):
        raw = json.dumps(value, ensure_ascii=True)
        if len(raw) > 65536:
            raise ValueError("Management response exceeds limit")
        outgoing.write(raw + "\n")
        outgoing.flush()

    managed.module("managed-lifecycle")  # Resolve trusted typed copy adapters before announcing readiness.
    emit({"ready": True, "kind": "inara-protected-management", "protocol": 1,
          "capabilities": ["backup", "prepare-profile", "signed-lifecycle", "reviewed-recovery"], "launched": False})
    while True:
        raw = incoming.readline(65537)
        if not raw:
            return
        if len(raw) > 65536 or not raw.endswith(b"\n"):
            raise ValueError("Management message exceeds framing limit")
        try:
            result = control.dispatch(json.loads(raw))
            emit({"ok": True, "result": result})
        except Exception:
            control.pending = None
            emit({"ok": False, "error": "Management refused. Recheck external pins, signed inputs and retained evidence; preserve any interrupted transaction and review again."})


if __name__ == "__main__":
    serve()
