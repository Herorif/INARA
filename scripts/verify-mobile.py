"""Native Companion verification: real loopback TLS and generated fixture identity; no Android APK or device."""

import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
output = ROOT / ".runtime/mobile-qa" / f"run-{uuid.uuid4()}"
output.mkdir(parents=True)
for key, name in [
    ("INARA_DATA_DIR", "database"),
    ("INARA_SETTINGS_FILE", "settings.json"),
    ("INARA_PROJECT_ROOT", "workspace"),
    ("INARA_LEGACY_DATA_DIR", "legacy"),
]:
    os.environ[key] = str(output / name)
os.environ["GEMINI_API_KEY"] = "changeme"  # Never use a real key in this verification.
os.environ.pop("ELECTRON_RUN_AS_NODE", None)
(output / "settings.json").write_text(json.dumps({"tool_permissions": {"start_audio": False}}))
from resident.host import NativeHost  # noqa: E402
from resident.state import Identity  # noqa: E402
from resident.win32 import WorkspaceProcess, api, kernel  # noqa: E402

Identity(output / "profile").register(str(uuid.uuid4()))


def workspace(executable, entrypoint, bootstrap, cwd):
    bootstrap["qaOutput"] = str(output)
    return WorkspaceProcess(
        executable, ROOT / "scripts/verify-mobile-workspace.cjs", bootstrap, cwd
    )


host = NativeHost(
    ROOT,
    output / "profile",
    process_factory=workspace,
    resident_only=True,
    hide_workspace=True,
    suppress_notifications=True,
)
result = {}


class Memory(C.Structure):
    _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [
        (name, C.c_size_t)
        for name in (
            "peak_ws",
            "ws",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
            "private",
        )
    ]


def memory(handle):
    value = Memory()
    value.cb = C.sizeof(value)
    if not api(C.WinDLL("psapi"), "GetProcessMemoryInfo", [W.HANDLE, W.LPVOID, W.DWORD], W.BOOL)(
        handle, C.byref(value), value.cb
    ):
        raise C.WinError()
    return {"working_set_mb": value.ws / 1048576, "private_mb": value.private / 1048576}


def sample():
    handles = [api(kernel, "GetCurrentProcess", [], W.HANDLE)()]
    parent = api(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)(
        0x410, False, os.getppid()
    )
    if parent:
        image = C.create_unicode_buffer(32768)
        length = W.DWORD(len(image))
        ok = api(
            kernel,
            "QueryFullProcessImageNameW",
            [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)],
            W.BOOL,
        )(parent, 0, image, C.byref(length))
        if ok and Path(image.value).parent.resolve() == (ROOT / ".venv/Scripts").resolve():
            handles.append(parent)
    try:
        values = [memory(handle) for handle in handles]
        return {key: round(sum(value[key] for value in values), 2) for key in values[0]}
    finally:
        if parent:
            kernel.CloseHandle(parent)


def until(condition, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = output / "ui-verification.json"
        if report.exists() and not json.loads(report.read_text()).get("passed", False):
            raise AssertionError(report.read_text())
        if condition():
            return
        if host.state.phase == "failed":
            raise AssertionError(host.state.error)
        time.sleep(0.1)
    raise AssertionError("Mobile integration condition timed out")


def verify():
    try:
        until(lambda: host.state.phase == "ready")

        result["before_workspace"] = sample()
        app = host.runtime.runtime

        assert not app.mobile.listener.running
        host.tray.post(host.open_workspace)
        until(lambda: (output / "invitation.json").exists())
        import base64
        import ssl
        import httpx
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from services.mobile_identity import signing_bytes

        invitation = json.loads((output / "invitation.json").read_text(encoding="utf-8"))
        cert = x509.load_der_x509_certificate(base64.b64decode(invitation["certificate"]))
        context = ssl.create_default_context(
            cadata=cert.public_bytes(serialization.Encoding.PEM).decode()
        )
        key = ec.generate_private_key(ec.SECP256R1())
        identifier = str(uuid.uuid4())

        def envelope(operation, payload):
            request_id, timestamp = str(uuid.uuid4()), int(time.time())
            body = json.dumps(payload, separators=(",", ":"))
            signature = key.sign(
                signing_bytes("/v1/" + operation, identifier, request_id, timestamp, body),
                ec.ECDSA(hashes.SHA256()),
            )
            return {
                "device_id": identifier,
                "request_id": request_id,
                "timestamp": timestamp,
                "payload": body,
                "signature": base64.b64encode(signature).decode(),
            }

        with httpx.Client(verify=context, trust_env=False) as client:

            def call(operation, payload=None, signed=None):
                return client.post(
                    invitation["endpoint"] + "/v1/" + operation,
                    json=signed or envelope(operation, payload or {}),
                ).json()

            public = base64.b64encode(
                key.public_key().public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            ).decode()
            claimed = call(
                "claim",
                {
                    "challenge_id": invitation["challenge_id"],
                    "secret": invitation["secret"],
                    "name": "Fixture Android companion",
                    "public_key": public,
                },
            )
            assert claimed["state"] == "pending", claimed
            (output / "claim-checked.json").write_text(
                json.dumps({"fingerprint": claimed["fingerprint"]})
            )
            until(lambda: (output / "approval-checked.json").exists())
            signed = envelope("status", {})
            assert call("status", signed=signed)["tools_enabled"] is False
            assert call("status", signed=signed)["code"] == "mobile_replay"
            assert call("jobs")["jobs"] == []
            assert (
                call(
                    "chat",
                    {
                        "conversation_id": str(uuid.uuid4()),
                        "request_id": str(uuid.uuid4()),
                        "text": "No provider should run",
                    },
                )["code"]
                == "mobile_grant"
            )
            (output / "phone-checked.json").write_text("{}")
            assert call("notification_policy")["policy"]["enabled"] is False
            until(lambda: (output / "notification-permission.json").exists())
            policy = call("notification_policy")["policy"]
            assert policy["enabled"] and policy["include_text"]
            batch = {"revision": policy["revision"], "events": [{
                "event_id": str(uuid.uuid4()), "source_id": "b" * 64, "conversation": "a" * 64,
                "package": "com.example.chat", "timestamp": int(time.time()), "kind": "posted",
                "title": "Synthetic selected notification", "text": "Fixture sample@example.com code 123456",
            }]}
            assert call("notification_sync", batch)["accepted"] == [batch["events"][0]["event_id"]]
            assert call("notification_sync", batch)["accepted"] == [batch["events"][0]["event_id"]]
            (output / "notification-uploaded.json").write_text("{}")
            until(lambda: (output / "notification-cleared.json").exists())
            assert call("notification_sync", batch)["code"] == "notification_grant"
            (output / "notification-stale-rejected.json").write_text("{}")
            until(lambda: (output / "revoke-checked.json").exists())
            assert call("status")["code"] == "mobile_auth"
            (output / "revocation-confirmed.json").write_text("{}")
        until(lambda: (output / "ui-verification.json").exists())
        result["ui"] = json.loads((output / "ui-verification.json").read_text())
        assert result["ui"]["passed"], result["ui"]
        until(lambda: host.workspace is None and not host.runtime.resource_governor.creative_active)
        assert not {"torch", "diffusers", "cv2", "mediapipe"} & set(sys.modules)
        result["model_modules_in_resident"] = False
        assert not app.mobile.listener.running and not app.mobile.running
        result["workspace_and_mobile_listener_released"] = True
        result["resident_after_worker_and_workspace_exit"] = [sample()]
        for _ in range(5):
            time.sleep(2)
            result["resident_after_worker_and_workspace_exit"].append(sample())
        result["passed"] = True
    except BaseException as exc:
        result["passed"], result["error"] = False, repr(exc)
    finally:
        print(json.dumps(result, indent=2), flush=True)
        host.tray.post(lambda: host.action("quit"))


host.start_core()
worker = threading.Thread(target=verify)
worker.start()
try:
    host.tray.run()
finally:
    host.state.quitting = True
    if host.workspace:
        host.workspace.close()
    if host.server:
        host.server.should_exit = True
    host.thread.join(5)
    worker.join(5)
    host.tray.close()
    result["graceful_core_stop"] = not host.thread.is_alive()
    result["passed"] = result.get("passed", False) and result["graceful_core_stop"]
    (output / "verification.json").write_text(json.dumps(result, indent=2))
    print(f"Evidence: {output}", flush=True)
sys.exit(0 if result["passed"] else 1)
