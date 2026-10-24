"""Finite trusted-controller entry. This never dispatches payload-supplied tooling."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(
        "controller_" + name, ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "policy-status",
            "verify",
            "review-install",
            "install",
            "launch-check",
            "windows-probe",
            "windows-check",
            "prepare-grant",
            "review-grant",
            "admit-grant",
            "launch",
            "prepare-managed-grant",
            "prepare-change",
            "review-change",
            "apply-change",
            "review-resume",
            "resume-change",
            "review-abort",
            "abort-change",
            "managed-status",
            "managed-launch",
            "managed-ui-worker",
            "managed-setup",
            "prepare-lifecycle",
            "review-lifecycle",
            "apply-lifecycle",
            "review-profile-copy",
            "apply-profile-copy",
        ),
    )
    parser.add_argument("--package", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--expected-policy")
    parser.add_argument("--windows-policy", type=Path)
    parser.add_argument("--expected-windows-policy")
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--expected-review")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-head")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--resident-only", action="store_true")
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--expected-state")
    parser.add_argument("--previous-state")
    parser.add_argument("--next-policy", type=Path)
    parser.add_argument("--expected-next-policy")
    parser.add_argument("--next-windows-policy", type=Path)
    parser.add_argument("--expected-next-windows-policy")
    parser.add_argument("--action", choices=("enroll", "renew", "rotate", "update", "rollback", "activate-profile", "rollback-profile", "remove-software", "erase-data"))
    parser.add_argument("--profile")
    parser.add_argument("--copy-operation", choices=("backup", "prepare-profile"))
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--slot")
    parser.add_argument("--change", type=Path)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--expected-manifest")
    args = parser.parse_args()
    try:
        signed = load("signed-package")
        if args.command == "managed-ui-worker":
            load("managed-ui").serve()
            return
        elif args.command == "managed-setup":
            if not args.expected_manifest:
                raise ValueError("Independent controller inventory pin required")
            load("controller-package").verify(ROOT, args.expected_manifest)
            result_code = subprocess.run([
                str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
                "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/managed-ui.ps1"),
                "-Directory", str(ROOT), "-ExpectedManifest", args.expected_manifest,
            ], check=False).returncode
            sys.exit(result_code)
        elif args.command in {"prepare-lifecycle", "review-lifecycle", "apply-lifecycle", "review-profile-copy", "apply-profile-copy"}:
            if None in (args.root, args.anchor, args.expected_state):
                raise ValueError("Explicit protected root, anchor and retained checkpoint required")
            lifecycle = load("managed-lifecycle")
            common = (args.root, args.anchor, args.expected_state)
            if args.command == "prepare-lifecycle":
                if None in (args.action, args.slot, args.output):
                    raise ValueError("Lifecycle action, slot and new external request directory required")
                result = lifecycle.prepare(*common, args.action, args.slot, args.profile, args.output, minutes=args.minutes)
            elif args.command in {"review-profile-copy", "apply-profile-copy"}:
                if None in (args.copy_operation, args.slot, args.file) or (args.command == "apply-profile-copy" and not args.expected_review):
                    raise ValueError("Explicit copy operation, version, file and apply review required")
                result = lifecycle.copies(*common, args.copy_operation, args.slot, args.file, args.profile, args.expected_review if args.command == "apply-profile-copy" else None)
            else:
                if args.change is None or (args.command == "apply-lifecycle" and not args.expected_review):
                    raise ValueError("Signed lifecycle envelope and exact apply review required")
                result = lifecycle.apply(*common, args.change, args.expected_review if args.command == "apply-lifecycle" else None, args.confirmation)
        elif args.command == "policy-status":
            release_path = ROOT / "docs/RELEASE_TRUST_POLICY.json"
            windows_path = ROOT / "docs/WINDOWS_SIGNING_POLICY.json"
            release = signed.trust.policy(release_path, signed.digest_file(release_path))
            windows = load("windows-signature").policy(
                windows_path, signed.digest_file(windows_path)
            )
            result = {
                "release_mode": release["mode"],
                "windows_mode": windows["mode"],
                "release_authorized": False,
                "launched": False,
            }
        elif args.command == "windows-probe":
            result = load("windows-signature").probe(args.file)
        elif args.command == "windows-check":
            result = load("windows-signature").check(
                args.directory, args.windows_policy, args.expected_windows_policy
            )
        elif args.command in {
            "prepare-managed-grant",
            "prepare-change",
            "review-change",
            "apply-change",
            "review-resume",
            "resume-change",
            "review-abort",
            "abort-change",
            "managed-status",
            "managed-launch",
        }:
            managed = load("managed-update")
            if None in (args.root, args.anchor, args.expected_state):
                raise ValueError(
                    "Explicit root, external checkpoint directory and retained state pin required"
                )
            if args.command in {"managed-status", "managed-launch"}:
                result = (
                    managed.status(args.root, args.anchor, args.expected_state)
                    if args.command == "managed-status"
                    else managed.launch(
                        args.root, args.anchor, args.expected_state, args.resident_only
                    )
                )
            elif args.command in {"review-resume", "resume-change", "review-abort", "abort-change"}:
                if args.previous_state is None or (
                    args.command in {"resume-change", "abort-change"} and not args.expected_review
                ):
                    raise ValueError("Exact previous checkpoint pin and recovery review required")
                operation = (
                    managed.abort
                    if args.command in {"review-abort", "abort-change"}
                    else managed.resume
                )
                result = operation(
                    args.root,
                    args.anchor,
                    args.expected_state,
                    args.previous_state,
                    args.expected_review
                    if args.command in {"resume-change", "abort-change"}
                    else None,
                    **({"confirmation": args.confirmation} if operation == managed.resume else {}),
                )
            else:
                if None in (
                    args.policy,
                    args.expected_policy,
                    args.windows_policy,
                    args.expected_windows_policy,
                    args.expected_head,
                    args.action,
                ):
                    raise ValueError(
                        "Explicit action, grant head and both current trust pins required"
                    )
                cfg = managed.inputs(
                    args.root,
                    args.anchor,
                    args.expected_state,
                    args.expected_head,
                    args.policy,
                    args.expected_policy,
                    args.windows_policy,
                    args.expected_windows_policy,
                    args.next_policy,
                    args.expected_next_policy,
                    args.next_windows_policy,
                    args.expected_next_windows_policy,
                )
                if args.command == "prepare-managed-grant":
                    if None in (args.slot, args.sequence, args.output):
                        raise ValueError(
                            "Explicit target/sequence and new request directory required"
                        )
                    result = managed.grant_request(
                        cfg,
                        args.action,
                        args.slot,
                        args.sequence,
                        args.output,
                        args.package,
                        args.hours,
                    )
                elif args.command == "prepare-change":
                    if None in (args.grant, args.output):
                        raise ValueError(
                            "External signed target grant and new request directory required"
                        )
                    result = managed.prepare(
                        cfg, args.action, args.grant, args.output, args.package, args.minutes
                    )
                else:
                    if None in (args.grant, args.change) or (
                        args.command == "apply-change" and not args.expected_review
                    ):
                        raise ValueError("Signed grant/change and exact change review required")
                    result = managed.change(
                        cfg,
                        args.action,
                        args.grant,
                        args.change,
                        args.package,
                        args.expected_review if args.command == "apply-change" else None,
                    )
        else:
            if None in (args.policy, args.expected_policy, args.sequence):
                raise ValueError("Explicit external policy/pin and sequence required")
            if args.command in {"prepare-grant", "review-grant", "admit-grant", "launch"}:
                if None in (
                    args.root,
                    args.windows_policy,
                    args.expected_windows_policy,
                    args.expected_head,
                ):
                    raise ValueError(
                        "Explicit root, Windows trust and external grant head required"
                    )
                admission = load("admission")
                common = (
                    args.root,
                    args.policy,
                    args.expected_policy,
                    args.windows_policy,
                    args.expected_windows_policy,
                    args.sequence,
                    args.expected_head,
                )
                if args.command == "prepare-grant":
                    if args.output is None:
                        raise ValueError("New external request directory required")
                    result = admission.prepare(*common, args.output, args.hours)
                elif args.command == "launch":
                    result = admission.launch(*common, resident_only=args.resident_only)
                else:
                    if args.grant is None or (
                        args.command == "admit-grant" and not args.expected_review
                    ):
                        raise ValueError("External signed grant and exact apply review required")
                    result = admission.admit(
                        args.root,
                        args.grant,
                        args.policy,
                        args.expected_policy,
                        args.windows_policy,
                        args.expected_windows_policy,
                        args.sequence,
                        args.expected_head,
                        args.expected_review if args.command == "admit-grant" else None,
                    )
            elif args.command == "launch-check":
                if None in (args.windows_policy, args.expected_windows_policy):
                    raise ValueError("Launch check also requires an external Windows policy/pin")
                windows = load("windows-signature")
                signed.trust.outside(args.windows_policy, [args.root])
                result = signed.launch_check(
                    args.root,
                    args.policy,
                    args.expected_policy,
                    args.sequence,
                    windows_check=lambda target: windows.check(
                        target, args.windows_policy, args.expected_windows_policy
                    ),
                )
            elif args.command == "verify":
                result = signed.verify(
                    args.package, args.policy, args.expected_policy, args.sequence
                )
            elif args.command == "review-install":
                result = signed.install_plan(
                    args.package,
                    args.policy,
                    args.expected_policy,
                    args.sequence,
                    args.root,
                    resume=args.resume,
                )
            else:
                if not args.expected_review:
                    raise ValueError("Exact installation review required")
                result = signed.install(
                    args.package,
                    args.policy,
                    args.expected_policy,
                    args.sequence,
                    args.root,
                    args.expected_review,
                    resume=args.resume,
                )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        parser.exit(
            1,
            "Trusted controller refused. Inspect exact inputs, external pins and retained evidence.\n",
        )
    print(json.dumps(result, indent=2))
    if result.get("launched") and result.get("exit_code"):
        sys.exit(1)


if __name__ == "__main__":
    main()
