"""Real-candidate fixture attestation. Ephemeral in-memory test keys; never release signing."""

import argparse
import base64
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_trust", ROOT / "scripts/release-trust.py")
trust = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trust)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "audit", "ledger", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    if (
        output.parent != ROOT / ".runtime/release-trust-qa"
        or output.resolve() != output
        or output.exists()
    ):
        raise ValueError("Choose a NEW direct child of workspace .runtime/release-trust-qa")
    output.mkdir(parents=True)
    now = trust.utc()
    keys = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    records = []
    for role, key in zip(("publisher", "reviewer"), keys):
        public = key.public_key().public_bytes_raw()
        records.append(
            {
                "key_id": trust.sha(public),
                "public_key": base64.b64encode(public).decode(),
                "identity": "EPHEMERAL FIXTURE " + role,
                "role": role,
                "state": "active",
                "not_before": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "not_after": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    policy = {
        "format": 1,
        "kind": "inara-release-trust-policy",
        "mode": "fixture",
        "policy_sequence": 1,
        "publisher": "EPHEMERAL TEST ONLY - NOT INARA RELEASE IDENTITY",
        "channel": "pilot",
        "minimum_sequence": 1,
        "thresholds": {"publisher": 1, "reviewer": 1},
        "keys": records,
    }
    policy_path = output / "fixture-policy.json"
    policy_path.write_bytes(trust.review.encoded(policy))
    pin = trust.sha(policy_path.read_bytes())
    ledger_file = trust.review.audit.local(args.ledger) / "ledger.json"
    before = ledger_file.read_bytes()
    prepared = trust.prepare(
        args.candidate,
        args.audit,
        args.ledger,
        policy_path,
        pin,
        1,
        output / "unsigned-request",
        allow_fixture=True,
    )
    request = json.loads((output / "unsigned-request/statement.json").read_text())
    envelope = {
        "format": 1,
        "kind": "inara-detached-attestation",
        "statement": request,
        "signatures": [
            {
                "key_id": record["key_id"],
                "signature": base64.b64encode(key.sign(trust.message(request))).decode(),
            }
            for record, key in zip(records, keys)
        ],
    }
    envelope_path = output / "fixture-attestation.json"
    envelope_path.write_bytes(trust.review.encoded(envelope))
    verified = trust.verify(
        args.candidate,
        args.audit,
        args.ledger,
        policy_path,
        pin,
        envelope_path,
        1,
        allow_fixture=True,
    )
    assert verified["fixture_only"] and not verified["release_authorized"]
    refused = {}
    for kind in ("missing-reviewer", "modified-signature", "fixture-without-option"):
        changed = json.loads(json.dumps(envelope))
        if kind == "missing-reviewer":
            changed["signatures"].pop()
        elif kind == "modified-signature":
            changed["signatures"][0]["signature"] = base64.b64encode(b"x" * 64).decode()
        path = output / (kind + ".json")
        path.write_bytes(trust.review.encoded(changed))
        try:
            trust.verify(
                args.candidate,
                args.audit,
                args.ledger,
                policy_path,
                pin,
                path,
                1,
                allow_fixture=kind != "fixture-without-option",
            )
        except ValueError:
            refused[kind] = True
        else:
            raise AssertionError("Invalid fixture unexpectedly accepted")
    disabled = ROOT / "docs/RELEASE_TRUST_POLICY.json"
    disabled_pin = trust.sha(disabled.read_bytes())
    assert trust.policy(disabled, disabled_pin)["mode"] == "disabled"
    try:
        trust.prepare(
            args.candidate,
            args.audit,
            args.ledger,
            disabled,
            disabled_pin,
            1,
            output / "production-request",
        )
    except ValueError:
        refused["unconfigured-production"] = True
    else:
        raise AssertionError("Unconfigured production identity accepted")
    assert before == ledger_file.read_bytes()
    assert not (output / "production-request").exists()
    report = {
        "format": 1,
        "passed": True,
        "fixture_only": True,
        "real_candidate_audit_ledger_revalidated": True,
        "unsigned_preparation": prepared,
        "detached_fixture_verification": verified,
        "refusals": refused,
        "private_keys_persisted": False,
        "ledger_unchanged": True,
        "production_policy_disabled": True,
        "real_release_signed": False,
        "authenticode_verified": False,
        "release_authorized": False,
    }
    (output / "verification.json").write_bytes(trust.review.encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
