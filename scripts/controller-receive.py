"""Independently trusted, source-neutral receiving verifier and reviewed delivery copy.

Run this tool from a separately trusted checkout, never from received evidence.
Producer provenance is endorsed by external signatures, not regenerated here.
"""

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("receive_delivery", ROOT / "scripts/controller-delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
reviews, signed, trust, old = delivery.reviews, delivery.signed, delivery.trust, delivery.old
SECTIONS = ("controller", "evidence", "ledger", "enrollment")
CHECKS = (
    "independent-verifier-policy-pins-and-current-sequence",
    "clean-windows-account-and-machine-inventory",
    "offline-invalid-signature-expiry-replay-and-tamper-refusal",
    "signed-install-and-native-window-launch",
    "authorization-expiry-and-controller-death-cleanup",
    "signed-update-rollback-and-policy-rotation",
    "interrupted-copy-commit-and-checkpoint-recovery",
    "original-account-backup-and-typed-recovery",
    "software-removal-retains-profile",
    "separate-explicit-profile-erasure-and-resume",
    "no-unrequested-startup-network-download-or-whatsapp-action",
)


def attested_base(evidence, ledger, pin, inventory):
    """Check inert queue identities; signature-bound evidence is not source rederivation."""
    report, raw = signed.read(Path(evidence) / "controller-provenance.json")
    queue, _ = signed.read(Path(evidence) / "controller-review-queue.json")
    old.exact(queue, {"format", "kind", "controller_manifest_sha256", "report_sha256", "subjects", "decisions_recorded", "release_authorized", "note"})
    if type(queue["format"]) is not int or queue["format"] != 1 or queue["kind"] != "inara-controller-review-queue" or queue["controller_manifest_sha256"] != pin or queue["report_sha256"] != trust.sha(raw) or queue["decisions_recorded"] != 0 or queue["release_authorized"] is not False:
        raise ValueError("Unsupported attested review queue")
    if type(report["format"]) is not int or report["format"] != 1 or report["kind"] != "inara-controller-provenance" or report["controller_manifest_sha256"] != pin:
        raise ValueError("Unsupported attested provenance")
    expected = []

    def subject(category, label, target, required):
        body = {"category": category, "label": label, "target": target, "required_evidence": sorted(required)}
        expected.append({"id": old.hashed(body), **body, "status": "pending"})

    for item in report["components"]:
        subject("component", item["ecosystem"] + ":" + item["name"] + "@" + item["version"], item, ["origin", "license", "obligations"])
        if item["ecosystem"] == "runtime":
            subject("runtime-baseline", item["name"], item, ["origin", "security", "support"])
    for item in report["missing_notice_components"]:
        subject("missing-notice", item["name"], item, ["origin", "notice"])
    subject("vendored-native", "Controller native/vendor subcomponent coverage", report["native_files"], ["inventory", "origin", "license", "obligations"])
    for item in report["external_delivery_inputs"]:
        subject("delivery-input", item["path"], item, ["origin", "license", "obligations", "delivery"])
    if not 1 <= len(expected) <= 4096 or queue["subjects"] != expected or len({s["id"] for s in expected}) != len(expected):
        raise ValueError("Attested subject coverage differs")
    value, _ = signed.read(Path(ledger) / "ledger.json")
    # The producer's review tool is an authenticated digest, never imported/executed.
    tool_pin = value["base"]["review_tool_sha256"]
    trust.digest(tool_pin)
    tool = next((e for e in report["external_delivery_inputs"] if e["path"] == "scripts/controller-review.py"), None)
    if tool is None or tool["sha256"] != tool_pin:
        raise ValueError("Producer review tool not covered by provenance")
    return {"format": 1, "kind": "inara-controller-review", "controller_manifest_sha256": pin,
            "provenance_inventory_sha256": inventory, "review_tool_sha256": tool_pin,
            "subjects": [{k: v for k, v in s.items() if k != "status"} for s in expected]}


def verify(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope, now=None, *, _native_check=None):
    common = (controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope)
    authenticated, _, envelope_pin = delivery.authenticate(*common, now=now)
    statement = authenticated["statement"]

    def snapshots():
        for key, directory in (("provenance_inventory_sha256", evidence), ("ledger_inventory_sha256", ledger), ("enrollment_inventory_sha256", enrollment)):
            if old.hashed(reviews.snapshot(directory)) != statement[key]:
                raise ValueError("Received evidence differs from signed inventory")

    snapshots()
    reviews.provenance.controller.verify(controller, pin)
    if signed.digest_file(Path(controller) / "scripts/open-trusted-controller.ps1") != statement["bootstrap_sha256"]:
        raise ValueError("Received bootstrap differs")
    base = attested_base(evidence, ledger, pin, statement["provenance_inventory_sha256"])
    value, statuses = reviews.inspect_history(ledger, base)
    if value["head_sha256"] != statement["ledger_head_sha256"] or not reviews.summary(value, statuses)["recorded_reviews_complete"]:
        raise ValueError("Received controller reviews incomplete")
    assessment = delivery.custody.assess(enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, now)
    if assessment["blockers"]:
        raise ValueError("Received public custody prerequisites incomplete")
    native = (delivery.windows.check if _native_check is None else _native_check)(controller, windows, windows_pin)
    if native.get("authenticode_verified") is not True or native.get("cache_only") is not True:
        raise ValueError("Received native signatures not accepted")
    snapshots()
    reviews.provenance.controller.verify(controller, pin)
    if signed.digest_file(Path(controller) / "scripts/open-trusted-controller.ps1") != statement["bootstrap_sha256"] or signed.digest_file(envelope) != envelope_pin:
        raise ValueError("Receiving inputs changed during verification")
    delivery.authenticate(*common, now=now)
    return {"receiving_verified": True, "statement_sha256": old.hashed(statement), "envelope_sha256": envelope_pin,
            "controller_manifest_sha256": pin, "sequence": sequence, "producer_source_rederived": False,
            "native_acceptance": native, "release_authorized": False, "installed": False, "launched": False,
            "clean_machine_accepted": False, "freshness_requires_external_sequence": True}


def inventory(controller, evidence, ledger, enrollment, envelope):
    records, total = [], 0
    for section, directory in zip(SECTIONS, (controller, evidence, ledger, enrollment)):
        for file in delivery.audit.package.files_in(Path(directory)):
            size = file.stat().st_size
            total += size
            if size > 536_870_912 or total > 2_684_354_560 or len(records) >= 40000:
                raise ValueError("Excessive receiving package")
            records.append({"path": section + "/" + file.relative_to(directory).as_posix(), "bytes": size, "sha256": signed.digest_file(file)})
    records.append({"path": "envelope.json", "bytes": Path(envelope).stat().st_size, "sha256": signed.digest_file(envelope)})
    return sorted(records, key=lambda x: x["path"])


def acceptance(statement_pin):
    return {"format": 1, "kind": "inara-clean-machine-acceptance-plan", "statement_sha256": statement_pin,
            "clean_machine_accepted": False, "checks": [{"id": key, "status": "pending", "evidence": []} for key in CHECKS],
            "instructions": "Run only after independently trusted verification and explicit real signing/device setup. Record actual machine, operator, UTC times, commands, expected/observed outcomes and redacted evidence hashes separately. This plan grants no execution or release authority."}


def plan(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope, output, now=None, *, _native_check=None):
    output = delivery.custody.destination(output, (controller, evidence, ledger, enrollment, envelope, policy, windows))
    result = verify(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope, now, _native_check=_native_check)
    body = {"format": 1, "kind": "inara-receiving-copy-plan", "output": str(output),
            "statement_sha256": result["statement_sha256"], "files": inventory(controller, evidence, ledger, enrollment, envelope),
            "acceptance": acceptance(result["statement_sha256"])}
    return {"plan_sha256": old.hashed(body), "plan": body, "copied": False}


def assemble(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope, output, expected_plan, now=None, *, _native_check=None):
    common = (controller, pin, evidence, ledger, enrollment, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, envelope)
    planned = plan(*common, output, now, _native_check=_native_check)
    if planned["plan_sha256"] != expected_plan:
        raise ValueError("Receiving copy plan changed; review again")
    output = Path(planned["plan"]["output"])
    output.mkdir(parents=True)
    roots = dict(zip(SECTIONS, map(Path, (controller, evidence, ledger, enrollment))))
    for entry in planned["plan"]["files"]:
        section, _, relative = entry["path"].partition("/")
        source = Path(envelope) if section == "envelope.json" else roots[section] / relative
        target = output / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stream bounded copies; retain partial output on any interruption/refusal.
        with source.open("rb") as src, target.open("xb") as dst:
            remaining = entry["bytes"]
            while remaining:
                data = src.read(min(1_048_576, remaining))
                if not data:
                    raise ValueError("Receiving source truncated")
                dst.write(data)
                remaining -= len(data)
            if src.read(1):
                raise ValueError("Receiving source grew")
        if signed.digest_file(target) != entry["sha256"]:
            raise ValueError("Receiving copy bytes changed")
    verify(*common, now=now, _native_check=_native_check)
    verify(output / "controller", pin, output / "evidence", output / "ledger", output / "enrollment", enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, output / "envelope.json", now, _native_check=_native_check)
    (output / "acceptance.json").write_bytes(old.encoded(planned["plan"]["acceptance"]))
    # Receipt is a completion marker, not an authority, signature or acceptance result.
    (output / "receipt.json").write_bytes(old.encoded(planned))
    verify_package(output, pin, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, now, _native_check=_native_check)
    return {"copied": True, "plan_sha256": expected_plan, "clean_machine_accepted": False, "installed": False, "launched": False}


def verify_package(package, pin, enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, now=None, *, _native_check=None):
    package = delivery.audit.local(package)
    trust.outside(policy, [package])
    trust.outside(windows, [package])
    result = verify(package / "controller", pin, package / "evidence", package / "ledger", package / "enrollment", enrollment_pin, policy, policy_pin, windows, windows_pin, sequence, package / "envelope.json", now, _native_check=_native_check)
    receipt, _ = signed.read(package / "receipt.json", 16_777_216)
    old.exact(receipt, {"plan_sha256", "plan", "copied"})
    body = receipt["plan"]
    old.exact(body, {"format", "kind", "output", "statement_sha256", "files", "acceptance"})
    if type(body["format"]) is not int or body["format"] != 1 or body["kind"] != "inara-receiving-copy-plan" or receipt["copied"] is not False or receipt["plan_sha256"] != old.hashed(body) or body["statement_sha256"] != result["statement_sha256"]:
        raise ValueError("Receiving completion marker differs")
    actual = inventory(*(package / s for s in SECTIONS), package / "envelope.json")
    if body["files"] != actual or body["acceptance"] != acceptance(result["statement_sha256"]) or delivery.audit.read(package, "acceptance.json", 65536) != old.encoded(body["acceptance"]):
        raise ValueError("Receiving inventory or acceptance plan changed")
    expected = {e["path"] for e in actual} | {"receipt.json", "acceptance.json"}
    if {p.relative_to(package).as_posix() for p in delivery.audit.package.files_in(package)} != expected:
        raise ValueError("Unexpected receiving package files")
    return {**result, "package_complete": True, "plan_sha256": receipt["plan_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "plan", "apply", "package-verify"))
    for name in ("controller", "evidence", "ledger", "enrollment", "envelope", "output", "package", "policy", "windows-policy"):
        parser.add_argument("--" + name, type=Path, required=name in {"policy", "windows-policy"})
    for name in ("expected-manifest", "expected-enrollment", "expected-policy", "expected-windows-policy"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--expected-plan")
    args = parser.parse_args()
    if args.command == "package-verify":
        if args.package is None:
            parser.error("Supply --package")
    elif any(getattr(args, s) is None for s in (*SECTIONS, "envelope")) or (args.command != "verify" and args.output is None) or (args.command == "apply" and args.expected_plan is None):
        parser.error("Supply receiving inputs and the new output/exact plan required")
    try:
        if args.command == "package-verify":
            result = verify_package(args.package, args.expected_manifest, args.expected_enrollment, args.policy, args.expected_policy, args.windows_policy, args.expected_windows_policy, args.sequence)
        else:
            common = (args.controller, args.expected_manifest, args.evidence, args.ledger, args.enrollment, args.expected_enrollment, args.policy, args.expected_policy, args.windows_policy, args.expected_windows_policy, args.sequence, args.envelope)
            if args.command == "verify":
                result = verify(*common)
            elif args.command == "plan":
                result = plan(*common, args.output)
            else:
                result = assemble(*common, args.output, args.expected_plan)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(1, "Receiving refused. Preserve independent trust and partial evidence. Nothing was installed or launched.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
