"""Public-only custody preparation and externally pinned readiness. Never enrolls or signs."""

import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("readiness_controller_review", ROOT / "scripts/controller-review.py")
reviews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviews)
signed, trust, audit, old = reviews.signed, reviews.trust, reviews.audit, reviews.old
spec = importlib.util.spec_from_file_location("readiness_windows", ROOT / "scripts/windows-signature.py")
windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows)
INSTRUCTIONS = b"INARA PUBLIC SIGNING PREPARATION\nOwner configuration is deferred. This draft grants no authority.\nUse only public labels, opaque custody references and public text evidence.\nNever include passwords, access tokens, private keys, certificates with keys or profiles.\nReview independent operators, recovery drills, revocation and bootstrap delivery before marking reviewed.\nPolicies remain separate and independently pinned; this tool never writes or enables them.\n"
FIELDS = {"format", "kind", "state", "publisher", "release_policy_sha256", "windows_policy_sha256", "independence_reviewed", "custody", "windows_custody", "bootstrap_delivery"}
CUSTODY = {"key_id", "operator", "custody_ref", "recovery_ref", "revocation_ref", "recovery_drill_verified", "checked_on", "evidence_sha256"}
WINDOWS = {"operator", "signing_ref", "timestamp_ref", "recovery_ref", "revocation_ref", "recovery_drill_verified", "checked_on", "evidence_sha256"}
BOOTSTRAP = {"operator", "independent_channel_ref", "verification_ref", "checked_on", "evidence_sha256"}


def destination(output, roots=()):
    output = signed.plain(output)
    if output.exists() or any(output.is_relative_to(signed.plain(root)) or signed.plain(root).is_relative_to(output) for root in roots):
        raise ValueError("Choose a NEW output separate from protected inputs")
    return output


def draft(output):
    output = destination(output)
    value = {"format": 1, "kind": "inara-signing-custody-plan", "state": "draft", "publisher": None,
             "release_policy_sha256": None, "windows_policy_sha256": None, "independence_reviewed": False,
             "custody": [], "windows_custody": None, "bootstrap_delivery": None}
    output.mkdir(parents=True)
    (output / "enrollment.json").write_bytes(old.encoded(value))
    (output / "INSTRUCTIONS.txt").write_bytes(INSTRUCTIONS)
    return {"draft_created": True, "enrollment_sha256": signed.digest_file(output / "enrollment.json"), "ready": False, "production_configured": False, "release_authorized": False}


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}", value) or "-----" in value:
        raise ValueError("Use a bounded opaque public custody/channel reference")


def enrollment(directory, expected, now=None):
    directory = audit.local(directory)
    value, raw = signed.read(directory / "enrollment.json", 262144)
    trust.digest(expected)
    if trust.sha(raw) != expected:
        raise ValueError("Custody plan differs from independently retained pin")
    old.exact(value, FIELDS)
    if type(value["format"]) is not int or value["format"] != 1 or value["kind"] != "inara-signing-custody-plan" or value["state"] not in {"draft", "reviewed"} or type(value["independence_reviewed"]) is not bool:
        raise ValueError("Unsupported public custody plan")
    if value["publisher"] is not None:
        old.text(value["publisher"], 160)
    for name in ("release_policy_sha256", "windows_policy_sha256"):
        if value[name] is not None:
            trust.digest(value[name])
    if not isinstance(value["custody"], list) or len(value["custody"]) > 32:
        raise ValueError("Excessive custody records")
    expected_files = {"enrollment.json", "INSTRUCTIONS.txt"}
    if audit.read(directory, "INSTRUCTIONS.txt") != INSTRUCTIONS:
        raise ValueError("Custody preparation instructions changed")
    total, seen = 0, set()

    def record(item, fields):
        nonlocal total
        old.exact(item, fields)
        for key in fields - {"key_id", "recovery_drill_verified", "checked_on", "evidence_sha256"}:
            reference(item[key])
        if "recovery_drill_verified" in item and type(item["recovery_drill_verified"]) is not bool:
            raise ValueError("Recovery drill must be an explicit assertion")
        day = date.fromisoformat(item["checked_on"])
        if day.isoformat() != item["checked_on"] or day > trust.utc(now).date():
            raise ValueError("Use an actual nonfuture custody-review date")
        trust.digest(item["evidence_sha256"])
        name = "evidence/" + item["evidence_sha256"] + ".txt"
        content = old.read_evidence(directory, name)
        if b"-----BEGIN" in content or trust.sha(content) != item["evidence_sha256"]:
            raise ValueError("Changed or key-bearing custody evidence")
        if name not in expected_files:
            total += len(content)
        expected_files.add(name)

    for item in value["custody"]:
        record(item, CUSTODY)
        trust.digest(item["key_id"])
        if item["key_id"] in seen:
            raise ValueError("Duplicate key custody record")
        seen.add(item["key_id"])
    for key, fields in (("windows_custody", WINDOWS), ("bootstrap_delivery", BOOTSTRAP)):
        if value[key] is not None:
            record(value[key], fields)
    if total > old.MAX_TOTAL or {p.relative_to(directory).as_posix() for p in audit.package.files_in(directory)} != expected_files:
        raise ValueError("Custody bundle has excessive, missing or unregistered files")
    return value


def assess(directory, expected, release_path, release_pin, windows_path, windows_pin, now=None):
    directory = audit.local(directory)
    for path in (release_path, windows_path):
        trust.outside(path, [directory])
    plan = enrollment(directory, expected, now)
    policy, native = trust.policy(release_path, release_pin), windows.policy(windows_path, windows_pin)
    blockers = []
    if plan["state"] != "reviewed":
        blockers.append("custody_plan_is_draft")
    if policy["mode"] != "production":
        blockers.append("release_identity_not_configured")
    if native["mode"] != "production":
        blockers.append("windows_signing_not_configured")
    if plan["release_policy_sha256"] != release_pin or plan["windows_policy_sha256"] != windows_pin:
        blockers.append("custody_policy_bindings_missing_or_different")
    if plan["publisher"] is None or plan["publisher"] != policy["publisher"]:
        blockers.append("publisher_assertion_missing_or_different")
    active = {key["key_id"]: key for key in policy["keys"] if key["state"] == "active"}
    if {item["key_id"] for item in plan["custody"]} != set(active) or not active:
        blockers.append("active_key_custody_coverage_incomplete")
    operators = {role: set() for role in ("publisher", "reviewer")}
    for item in plan["custody"]:
        if item["key_id"] in active:
            key = active[item["key_id"]]
            operators[key["role"]].add(item["operator"])
            if not trust.stamp(key["not_before"]) <= trust.utc(now) < trust.stamp(key["not_after"]):
                blockers.append("enrolled_key_not_currently_valid")
        if not item["recovery_drill_verified"]:
            blockers.append("key_recovery_drill_not_recorded")
    if not plan["independence_reviewed"] or not all(operators.values()) or operators["publisher"] & operators["reviewer"]:
        blockers.append("independent_role_operators_not_recorded")
    if plan["windows_custody"] is None or not plan["windows_custody"]["recovery_drill_verified"]:
        blockers.append("windows_custody_or_recovery_drill_missing")
    if plan["bootstrap_delivery"] is None:
        blockers.append("independent_bootstrap_delivery_missing")
    return {"ready": not blockers, "blockers": sorted(set(blockers)), "enrollment_sha256": expected,
            "enrollment_inventory_sha256": old.hashed(reviews.snapshot(directory)), "release_policy_sha256": release_pin,
            "windows_policy_sha256": windows_pin, "identity_assertions_authenticated": False,
            "hardware_key_custody_verified": False, "certificate_store_changed": False,
            "production_configured": False, "release_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("draft", "assess"))
    for name in ("directory", "output", "policy", "windows-policy"):
        parser.add_argument("--" + name, type=Path)
    for name in ("expected-enrollment", "expected-policy", "expected-windows-policy"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.command == "draft" and args.output is None:
        parser.error("Provide a new draft output")
    if args.command == "assess" and None in (args.directory, args.expected_enrollment, args.policy, args.expected_policy, args.windows_policy, args.expected_windows_policy):
        parser.error("Provide the explicit enrollment directory, external policies and independent pins")
    try:
        result = draft(args.output) if args.command == "draft" else assess(args.directory, args.expected_enrollment, args.policy, args.expected_policy, args.windows_policy, args.expected_windows_policy)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(1, "Signing preparation refused. Keep public evidence separate from private keys and profiles.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
