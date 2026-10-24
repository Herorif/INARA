"""Detached controller delivery preparation/verification. No signing, install or launch."""

import argparse
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("delivery_" + name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


custody, managed = load("signing-readiness"), load("managed-update")
reviews, signed, trust, windows = custody.reviews, custody.signed, custody.trust, custody.windows
old, audit = signed.review, signed.audit
DOMAIN = b"INARA:controller-delivery:v1\n"
DIGESTS = {"controller_manifest_sha256", "bootstrap_sha256", "provenance_inventory_sha256", "ledger_inventory_sha256", "ledger_head_sha256", "enrollment_inventory_sha256", "enrollment_sha256", "policy_sha256", "windows_policy_sha256"}
FIELDS = {"format", "kind", "purpose", "publisher", "channel", "sequence", "issued_at", "expires_at"} | DIGESTS


def inputs(controller, evidence, ledger, enrollment, policy, windows_policy):
    roots = [audit.local(path) for path in (controller, evidence, ledger, enrollment)]
    for index, left in enumerate(roots):
        if any(left.is_relative_to(right) or right.is_relative_to(left) for right in roots[index + 1:]):
            raise ValueError("Keep controller, provenance, ledger and custody bundle separate")
    for path in (policy, windows_policy):
        trust.outside(path, roots)
    return roots


def readiness(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, source=ROOT, now=None, *, _native_check=None):
    inputs(controller, evidence, ledger, enrollment, policy_path, windows_path)
    before = {key: old.hashed(reviews.snapshot(directory)) for key, directory in (("provenance_inventory_sha256", evidence), ("ledger_inventory_sha256", ledger), ("enrollment_inventory_sha256", enrollment))}
    assessment = custody.assess(enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, now)
    value, statuses = reviews.inspect(controller, pin, evidence, ledger, source)
    review_status = reviews.summary(value, statuses)
    blockers = list(assessment["blockers"])
    if not review_status["recorded_reviews_complete"]:
        blockers.append("controller_review_decisions_incomplete")
    native = None
    if not blockers:
        try:
            native = (windows.check if _native_check is None else _native_check)(controller, windows_path, windows_pin)
            if native.get("authenticode_verified") is not True or native.get("cache_only") is not True:
                raise ValueError("Native signature acceptance missing")
        except (OSError, ValueError):
            blockers.append("native_windows_signatures_not_accepted")
    reviews.provenance.controller.verify(controller, pin)
    for key, directory in (("provenance_inventory_sha256", evidence), ("ledger_inventory_sha256", ledger), ("enrollment_inventory_sha256", enrollment)):
        if old.hashed(reviews.snapshot(directory)) != before[key]:
            raise ValueError("Delivery prerequisites changed during assessment")
    if before["provenance_inventory_sha256"] != value["base"]["provenance_inventory_sha256"] or before["enrollment_inventory_sha256"] != assessment["enrollment_inventory_sha256"]:
        raise ValueError("Validated custody/provenance snapshots differ")
    return {"ready_for_signing_request": not blockers, "blockers": sorted(set(blockers)),
            "custody": assessment, "controller_review": review_status, "native_acceptance": native,
            "controller_manifest_sha256": pin, "bootstrap_sha256": signed.digest_file(Path(controller) / "scripts/open-trusted-controller.ps1"),
            "provenance_inventory_sha256": before["provenance_inventory_sha256"],
            "ledger_inventory_sha256": before["ledger_inventory_sha256"], "ledger_head_sha256": value["head_sha256"],
            "enrollment_inventory_sha256": assessment["enrollment_inventory_sha256"],
            "release_authorized": False, "launched": False, "legal_identity_established": False}


def prepare(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, sequence, output, source=ROOT, now=None, minutes=30, *, _native_check=None):
    roots = inputs(controller, evidence, ledger, enrollment, policy_path, windows_path)
    output = custody.destination(output, roots)
    trust.integer(sequence)
    trust.integer(minutes, 1, 60)
    result = readiness(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, source, now, _native_check=_native_check)
    if not result["ready_for_signing_request"]:
        raise ValueError("Controller delivery prerequisites remain pending")
    policy = trust.policy(policy_path, policy_pin)
    if sequence < policy["minimum_sequence"]:
        raise ValueError("Delivery sequence below external policy floor")
    current = trust.utc(now)
    expires = current + timedelta(minutes=minutes)
    for role, threshold in policy["thresholds"].items():
        if sum(k["state"] == "active" and k["role"] == role and trust.stamp(k["not_before"]) <= current and expires <= trust.stamp(k["not_after"]) for k in policy["keys"]) < threshold:
            raise ValueError("Enrolled keys do not cover the full delivery window")
    value = {"format": 1, "kind": "inara-controller-delivery", "purpose": "production",
             "publisher": policy["publisher"], "channel": policy["channel"], "sequence": sequence,
             "issued_at": current.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "enrollment_sha256": enrollment_pin, "policy_sha256": policy_pin, "windows_policy_sha256": windows_pin,
             **{key: result[key] for key in DIGESTS - {"enrollment_sha256", "policy_sha256", "windows_policy_sha256"}}}
    output.mkdir(parents=True)
    (output / "statement.json").write_bytes(old.encoded(value))
    (output / "signing-message.bin").write_bytes(DOMAIN + old.encoded(value))
    return {"prepared": True, "signed": False, "statement_sha256": old.hashed(value), "controller_manifest_sha256": pin,
            "release_authorized": False, "launched": False}


def authenticate(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, sequence, envelope_path, now=None):
    roots = inputs(controller, evidence, ledger, enrollment, policy_path, windows_path)
    envelope_path = trust.outside(envelope_path, roots)
    policy = trust.policy(policy_path, policy_pin)
    if policy["mode"] != "production":
        raise ValueError("Production-purpose external delivery trust required")
    envelope, raw = signed.read(envelope_path, 262144)
    old.exact(envelope, {"statement", "signatures"})
    value = envelope["statement"]
    old.exact(value, FIELDS)
    if type(value["format"]) is not int or value["format"] != 1 or value["kind"] != "inara-controller-delivery" or value["purpose"] != "production":
        raise ValueError("Unsupported controller delivery statement")
    for key in DIGESTS:
        trust.digest(value[key])
    trust.integer(sequence)
    trust.integer(value["sequence"])
    current = trust.utc(now)
    issued, expires = trust.stamp(value["issued_at"]), trust.stamp(value["expires_at"])
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(hours=1):
        raise ValueError("Delivery window expired or invalid")
    if value["sequence"] != sequence or sequence < policy["minimum_sequence"] or value["publisher"] != policy["publisher"] or value["channel"] != policy["channel"]:
        raise ValueError("External delivery sequence/publisher/channel differs")
    for key, expected in (("policy_sha256", policy_pin), ("windows_policy_sha256", windows_pin), ("enrollment_sha256", enrollment_pin), ("controller_manifest_sha256", pin)):
        if value[key] != expected:
            raise ValueError("Delivery differs from independent external expectations")
    # Authenticate before controller inventory traversal, provenance validation or native checks.
    managed.roles(envelope["signatures"], policy, value, current, DOMAIN)
    return envelope, policy, trust.sha(raw)


def verify(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, sequence, envelope_path, source=ROOT, now=None, *, _native_check=None):
    envelope, policy, envelope_pin = authenticate(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, sequence, envelope_path, now)
    value = envelope["statement"]
    result = readiness(controller, pin, evidence, ledger, enrollment, enrollment_pin, policy_path, policy_pin, windows_path, windows_pin, source, now, _native_check=_native_check)
    if not result["ready_for_signing_request"] or any(value[key] != result[key] for key in DIGESTS - {"enrollment_sha256", "policy_sha256", "windows_policy_sha256"}):
        raise ValueError("Delivery bytes/reviews/custody differ or prerequisites are incomplete")
    managed.roles(envelope["signatures"], policy, value, trust.utc(now), DOMAIN)
    if signed.digest_file(envelope_path) != envelope_pin:
        raise ValueError("Delivery envelope changed during verification")
    # Recheck immutable evidence snapshots after native verification, not just before it.
    reviews.provenance.controller.verify(controller, pin)
    for key, directory in (("provenance_inventory_sha256", evidence), ("ledger_inventory_sha256", ledger), ("enrollment_inventory_sha256", enrollment)):
        if old.hashed(reviews.snapshot(directory)) != value[key]:
            raise ValueError("Delivery evidence changed during verification")
    return {"delivery_signatures_verified": True, "bootstrap_detached_binding_verified": True,
            "native_acceptance": result["native_acceptance"], "controller_manifest_sha256": pin,
            "sequence": sequence, "publisher": policy["publisher"], "controller_review": result["controller_review"],
            "release_authorized": False, "legal_identity_established": False, "launched": False,
            "installed": False, "policy_enrolled": False, "freshness_requires_external_sequence": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "prepare", "verify"))
    for name in ("controller", "evidence", "ledger", "enrollment", "policy", "windows-policy", "output", "envelope"):
        parser.add_argument("--" + name, type=Path, required=name not in {"output", "envelope"})
    for name in ("expected-manifest", "expected-enrollment", "expected-policy", "expected-windows-policy"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    if (args.command == "prepare" and args.output is None) or (args.command == "verify" and args.envelope is None) or (args.command != "readiness" and args.sequence is None):
        parser.error("Supply an explicit sequence and new output or detached envelope")
    common = (args.controller, args.expected_manifest, args.evidence, args.ledger, args.enrollment, args.expected_enrollment, args.policy, args.expected_policy, args.windows_policy, args.expected_windows_policy)
    try:
        if args.command == "readiness":
            result = readiness(*common, source=args.source)
        elif args.command == "prepare":
            result = prepare(*common, args.sequence, args.output, source=args.source, minutes=args.minutes)
        else:
            result = verify(*common, args.sequence, args.envelope, source=args.source)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(1, "Controller delivery refused. Preserve independent trust, source and public evidence; nothing was signed, enrolled or launched.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
