"""Development-host controller acceptance; never installs, launches a resident or enrolls identity."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("qa_" + name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(directory, pin, arguments, expected):
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/open-trusted-controller.ps1"),
            "-Directory",
            str(directory),
            "-ExpectedManifest",
            pin,
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != expected:
        raise ValueError(
            "Unexpected bootstrap/controller acceptance result: " + result.stderr[:400]
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--expected-manifest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package, windows = load("controller-package"), load("windows-signature")
    signed = package.signed
    output = signed.plain(args.output)
    if output.exists():
        parser.error("Choose a NEW acceptance directory")
    directory = signed.plain(args.controller, True)
    verified = package.verify(directory, args.expected_manifest)
    status = json.loads(run(directory, args.expected_manifest, ["policy-status"], 0).stdout)
    assert status["release_mode"] == status["windows_mode"] == "disabled"
    wrong_pin = ("0" if args.expected_manifest[0] != "0" else "1") + args.expected_manifest[1:]
    refused = run(directory, wrong_pin, ["policy-status"], 1)
    assert "inventory pin differs" in refused.stderr
    missing = run(directory, args.expected_manifest, ["launch-check"], 1)
    assert "controller refused" in missing.stderr
    missing_grant = run(directory, args.expected_manifest, ["launch"], 1)
    assert "controller refused" in missing_grant.stderr
    missing_managed = run(directory, args.expected_manifest, ["managed-launch"], 1)
    assert "controller refused" in missing_managed.stderr
    missing_ui = run(directory, args.expected_manifest, ["managed-setup"], 1)
    assert "controller refused" in missing_ui.stderr
    missing_lifecycle = run(directory, args.expected_manifest, ["apply-lifecycle"], 1)
    assert "controller refused" in missing_lifecycle.stderr
    missing_copy = run(directory, args.expected_manifest, ["apply-profile-copy"], 1)
    assert "controller refused" in missing_copy.stderr
    unsigned = windows.probe(ROOT / "scripts/controller.py")
    assert unsigned["status"] != "0x00000000"
    upstream = windows.probe(directory / "runtime/python.exe")
    try:
        windows.check(
            directory,
            ROOT / "docs/WINDOWS_SIGNING_POLICY.json",
            signed.digest_file(ROOT / "docs/WINDOWS_SIGNING_POLICY.json"),
        )
    except ValueError:
        disabled_refused = True
    else:
        raise AssertionError("Unconfigured Windows identity accepted")
    value = {
        "format": 1,
        "kind": "inara-controller-development-acceptance",
        "controller": verified,
        "bootstrap_policy_status": status,
        "refusals": {
            "wrong_bootstrap_pin_before_python": True,
            "missing_launch_configuration": True,
            "missing_guarded_launch_configuration": True,
            "missing_managed_state_configuration": True,
            "missing_native_ui_manifest_pin_before_window": True,
            "missing_lifecycle_authorization": True,
            "missing_profile_copy_configuration": True,
            "disabled_windows_policy": disabled_refused,
        },
        "unsigned_source_probe": unsigned,
        "upstream_python_probe": {**upstream, "inara_identity_enrolled": False},
        "resident_launched": False,
        "production_installation_created": False,
        "certificate_store_configured": False,
        "network_acceptance_measured": False,
        "clean_machine_verified": False,
        "release_authorized": False,
    }
    output.mkdir(parents=True)
    (output / "result.json").write_bytes(signed.review.encoded(value))
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
