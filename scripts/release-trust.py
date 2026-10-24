"""Externally pinned, detached whole-payload attestation. No private-key/signing CLI."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "trust_review", ROOT / "scripts/distribution-review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
DOMAIN = b"INARA:distribution-statement:v1\n"
POLICY_FIELDS = {
    "format",
    "kind",
    "mode",
    "policy_sequence",
    "publisher",
    "channel",
    "minimum_sequence",
    "thresholds",
    "keys",
}
STATEMENT_FIELDS = {
    "format",
    "kind",
    "usage",
    "policy_sha256",
    "publisher",
    "channel",
    "sequence",
    "issued_at",
    "expires_at",
    "candidate_manifest_sha256",
    "candidate_inventory_sha256",
    "audit_report_sha256",
    "ledger_sha256",
    "ledger_head_sha256",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate trust metadata field")
        result[key] = value
    return result


def read_json(path, limit):
    path = Path(path).absolute()
    if path.drive.startswith("\\\\"):
        raise ValueError("Choose local trust metadata")
    raw = review.audit.read(path.parent, path.name, limit)
    return json.loads(raw, object_pairs_hook=pairs), raw


def integer(value, minimum=1, maximum=2_147_483_647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid trust sequence/threshold")


def digest(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Invalid trust digest")


def stamp(value):
    if not isinstance(value, str) or len(value) != 20:
        raise ValueError("Use an exact UTC timestamp")
    result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if result.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("Invalid UTC timestamp")
    return result


def utc(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Verification requires an aware UTC clock")
    return value.replace(microsecond=0)


def b64(value, length):
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("Invalid key/signature encoding")
    raw = base64.b64decode(value, validate=True)
    if len(raw) != length or base64.b64encode(raw).decode() != value:
        raise ValueError("Noncanonical key/signature encoding")
    return raw


def policy(path, expected_digest):
    digest(expected_digest)
    value, raw = read_json(path, 65_536)
    if sha(raw) != expected_digest:
        raise ValueError("Policy differs from the independently supplied pin")
    review.exact(value, POLICY_FIELDS)
    if (
        type(value["format"]) is not int
        or value["format"] != 1
        or value["kind"] != "inara-release-trust-policy"
        or value["mode"] not in {"disabled", "fixture", "production"}
        or value["channel"] not in {"pilot", "stable"}
    ):
        raise ValueError("Unsupported release trust policy")
    integer(value["policy_sequence"])
    integer(value["minimum_sequence"])
    review.exact(value["thresholds"], {"publisher", "reviewer"})
    for threshold in value["thresholds"].values():
        integer(threshold, 1, 8)
    if not isinstance(value["keys"], list) or len(value["keys"]) > 32:
        raise ValueError("Excessive trust keys")
    if value["mode"] == "disabled":
        if value["keys"] or value["publisher"] is not None:
            raise ValueError("Disabled policy cannot enroll an identity")
        return value
    review.text(value["publisher"], 160)
    identities, active = set(), {"publisher": 0, "reviewer": 0}
    for key in value["keys"]:
        review.exact(
            key, {"key_id", "public_key", "identity", "role", "state", "not_before", "not_after"}
        )
        public = b64(key["public_key"], 32)
        if (
            key["key_id"] != sha(public)
            or key["key_id"] in identities
            or key["role"] not in active
            or key["state"] not in {"active", "revoked"}
        ):
            raise ValueError("Duplicate, mismatched or invalid trust identity")
        review.text(key["identity"], 160)
        if stamp(key["not_before"]) >= stamp(key["not_after"]):
            raise ValueError("Invalid trusted-key window")
        identities.add(key["key_id"])
        if key["state"] == "active":
            active[key["role"]] += 1
    if any(active[role] < value["thresholds"][role] for role in active):
        raise ValueError("Insufficient independent publisher/reviewer trust keys")
    return value


def outside(path, roots):
    path = Path(path).absolute()
    if (
        path.drive.startswith("\\\\")
        or path.resolve() != path
        or any(path.is_relative_to(review.audit.local(root)) for root in roots)
    ):
        raise ValueError("Keep trust inputs/outputs outside candidate, audit and ledger")
    return path


def material(candidate, audited, ledger):
    value, statuses = review.inspect(candidate, audited, ledger)
    audit_raw = review.audit.read(review.audit.local(audited), "distribution-audit.json", 8_388_608)
    report = json.loads(audit_raw)
    return {
        "candidate_manifest_sha256": report["candidate_manifest_sha256"],
        "candidate_inventory_sha256": report["candidate_inventory_sha256"],
        "audit_report_sha256": sha(audit_raw),
        "ledger_sha256": sha(
            review.audit.read(review.audit.local(ledger), "ledger.json", 8_388_608)
        ),
        "ledger_head_sha256": value["head_sha256"],
    }, all(status == "approved" for status in statuses.values())


def message(statement):
    return DOMAIN + review.encoded(statement)


def prepare(
    candidate,
    audited,
    ledger,
    policy_path,
    expected_policy,
    sequence,
    output,
    minutes=60,
    now=None,
    allow_fixture=False,
):
    roots = [candidate, audited, ledger]
    policy_path = outside(policy_path, roots)
    trusted = policy(policy_path, expected_policy)
    if trusted["mode"] == "disabled":
        raise ValueError("Release identity is unconfigured; signing preparation is disabled")
    if trusted["mode"] == "fixture" and not allow_fixture:
        raise ValueError("Fixture trust requires the explicit fixture option")
    integer(sequence, trusted["minimum_sequence"])
    integer(minutes, 1, 1440)
    output = outside(output, roots)
    if output.exists():
        raise ValueError("Choose a NEW detached request directory")
    bindings, complete = material(candidate, audited, ledger)
    if trusted["mode"] == "production" and not complete:
        raise ValueError("Real distribution reviews are incomplete")
    issued = utc(now)
    expires = issued + timedelta(minutes=minutes)
    available = {
        role: sum(
            key["role"] == role
            and key["state"] == "active"
            and stamp(key["not_before"]) <= issued
            and expires <= stamp(key["not_after"])
            for key in trusted["keys"]
        )
        for role in trusted["thresholds"]
    }
    if any(available[role] < trusted["thresholds"][role] for role in available):
        raise ValueError("No sufficient enrolled keys cover the signing window")
    statement = {
        "format": 1,
        "kind": "inara-distribution-statement",
        "usage": trusted["mode"],
        "policy_sha256": expected_policy,
        "publisher": trusted["publisher"],
        "channel": trusted["channel"],
        "sequence": sequence,
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **bindings,
    }
    output.mkdir(parents=True)
    with (output / "statement.json").open("xb") as stream:
        stream.write(review.encoded(statement))
    with (output / "signing-message.bin").open("xb") as stream:
        stream.write(message(statement))
    return {
        "prepared": True,
        "usage": trusted["mode"],
        "signing_message_sha256": sha(message(statement)),
        "private_keys_accessed": False,
        "signed": False,
        "release_authorized": False,
    }


def verify(
    candidate,
    audited,
    ledger,
    policy_path,
    expected_policy,
    envelope_path,
    expected_sequence,
    now=None,
    allow_fixture=False,
):
    roots = [candidate, audited, ledger]
    trusted = policy(outside(policy_path, roots), expected_policy)
    if trusted["mode"] == "disabled":
        raise ValueError("No release trust identity is enrolled")
    if trusted["mode"] == "fixture" and not allow_fixture:
        raise ValueError("Fixture trust requires the explicit fixture option")
    integer(expected_sequence, trusted["minimum_sequence"])
    envelope, _ = read_json(outside(envelope_path, roots), 262_144)
    review.exact(envelope, {"format", "kind", "statement", "signatures"})
    if (
        type(envelope["format"]) is not int
        or envelope["format"] != 1
        or envelope["kind"] != "inara-detached-attestation"
    ):
        raise ValueError("Unsupported detached attestation")
    statement = envelope["statement"]
    review.exact(statement, STATEMENT_FIELDS)
    if (
        type(statement["format"]) is not int
        or statement["format"] != 1
        or statement["kind"] != "inara-distribution-statement"
        or statement["usage"] != trusted["mode"]
        or statement["publisher"] != trusted["publisher"]
        or statement["channel"] != trusted["channel"]
        or statement["policy_sha256"] != expected_policy
    ):
        raise ValueError("Wrong identity, policy, channel or usage")
    integer(statement["sequence"], trusted["minimum_sequence"])
    if statement["sequence"] != expected_sequence:
        raise ValueError("Unexpected release sequence; no replay/downgrade acceptance")
    issued, expires, current = (
        stamp(statement["issued_at"]),
        stamp(statement["expires_at"]),
        utc(now),
    )
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(days=1):
        raise ValueError("Future, expired or excessive signing window")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 32:
        raise ValueError("Missing or excessive attestation signatures")
    keys = {key["key_id"]: key for key in trusted["keys"]}
    seen, counts = set(), {"publisher": 0, "reviewer": 0}
    for signature in signatures:
        review.exact(signature, {"key_id", "signature"})
        key = keys.get(signature["key_id"])
        if key is None or signature["key_id"] in seen or key["state"] != "active":
            raise ValueError("Unknown, duplicate or revoked attestation key")
        if not stamp(key["not_before"]) <= issued <= current < stamp(
            key["not_after"]
        ) or expires > stamp(key["not_after"]):
            raise ValueError("Attestation lies outside trusted-key validity")
        try:
            Ed25519PublicKey.from_public_bytes(b64(key["public_key"], 32)).verify(
                b64(signature["signature"], 64), message(statement)
            )
        except InvalidSignature as error:
            raise ValueError("Detached signature does not match the exact statement") from error
        seen.add(signature["key_id"])
        counts[key["role"]] += 1
    if any(counts[role] < trusted["thresholds"][role] for role in counts):
        raise ValueError("Independent publisher/reviewer thresholds were not met")
    bindings, complete = material(candidate, audited, ledger)
    if any(statement[key] != value for key, value in bindings.items()):
        raise ValueError("Candidate, inventory, audit or reviewed ledger changed")
    if trusted["mode"] == "production" and not complete:
        raise ValueError("Production review records are incomplete")
    return {
        "integrity": "passed",
        "fixture_only": trusted["mode"] == "fixture",
        "publisher_key_verified": True,
        "reviewer_key_verified": True,
        "signatures": counts,
        "sequence": expected_sequence,
        "whole_payload_binding_verified": True,
        "review_records_complete": complete,
        "legal_identity_established": False,
        "authenticode_verified": False,
        "clean_machine_acceptance": False,
        "release_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("policy", "prepare", "verify"))
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--expected-policy", required=True)
    for name in ("candidate", "audit", "ledger", "output", "envelope"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--valid-minutes", type=int, default=60)
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    if args.command != "policy" and (
        any(getattr(args, name) is None for name in ("candidate", "audit", "ledger", "sequence"))
        or (args.command == "prepare" and args.output is None)
        or (args.command == "verify" and args.envelope is None)
    ):
        parser.error("Provide exact candidate/audit/ledger/sequence and request output or envelope")
    try:
        if args.command == "policy":
            value = policy(args.policy, args.expected_policy)
            result = {
                "policy_valid": True,
                "mode": value["mode"],
                "production_configured": value["mode"] == "production",
                "trusted_public_keys": len(value["keys"]),
                "release_authorized": False,
            }
        elif args.command == "prepare":
            result = prepare(
                args.candidate,
                args.audit,
                args.ledger,
                args.policy,
                args.expected_policy,
                args.sequence,
                args.output,
                args.valid_minutes,
                allow_fixture=args.fixture,
            )
        else:
            result = verify(
                args.candidate,
                args.audit,
                args.ledger,
                args.policy,
                args.expected_policy,
                args.envelope,
                args.sequence,
                allow_fixture=args.fixture,
            )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Release trust check refused. Preserve prior evidence; verify the external policy pin, identity, exact payload and review state.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
