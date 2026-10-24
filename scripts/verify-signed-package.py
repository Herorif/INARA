"""Assemble/verify a real-candidate fixture container; prove installation stays blocked."""

import argparse
import base64
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_signed", ROOT / "scripts/signed-package.py")
signed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "audit", "ledger", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    if (
        output.parent != ROOT / ".runtime/signed-package-qa"
        or output.resolve() != output
        or output.exists()
    ):
        raise ValueError("Choose a NEW direct child of workspace .runtime/signed-package-qa")
    output.mkdir(parents=True)
    now = signed.trust.utc()
    private = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    keys = []
    for role, key in zip(("publisher", "reviewer"), private):
        public = key.public_key().public_bytes_raw()
        keys.append(
            {
                "key_id": signed.trust.sha(public),
                "public_key": base64.b64encode(public).decode(),
                "identity": "EPHEMERAL PACKAGE FIXTURE " + role,
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
        "publisher": "EPHEMERAL TEST ONLY - NOT A RELEASE IDENTITY",
        "channel": "pilot",
        "minimum_sequence": 1,
        "thresholds": {"publisher": 1, "reviewer": 1},
        "keys": keys,
    }
    policy_path = output / "fixture-policy.json"
    policy_path.write_bytes(signed.review.encoded(policy))
    pin = signed.digest_file(policy_path)
    before = signed.digest_file(args.ledger / "ledger.json")
    package = output / "fixture-package"
    prepared = signed.prepare(
        args.candidate,
        args.audit,
        args.ledger,
        policy_path,
        pin,
        1,
        package,
        output / "request",
        fixture=True,
    )
    # A prepared, unsigned container must refuse even explicit fixture verification.
    refusals = {}
    try:
        signed.verify(package, policy_path, pin, 1, fixture=True)
    except (ValueError, OSError):
        refusals["unsigned-package"] = True
    else:
        raise AssertionError("Missing attestation accepted")
    statement = json.loads((output / "request/statement.json").read_text())
    envelope = {
        "format": 1,
        "kind": "inara-package-attestation",
        "statement": statement,
        "signatures": [
            {
                "key_id": record["key_id"],
                "signature": base64.b64encode(key.sign(signed.signing_message(statement))).decode(),
            }
            for record, key in zip(keys, private)
        ],
    }
    (package / signed.ENVELOPE).write_bytes(signed.review.encoded(envelope))
    verified = signed.verify(package, policy_path, pin, 1, fixture=True)
    assert verified["fixture_only"] and not verified["reviews_complete"]
    root = output / "must-not-create-installation"
    try:
        signed.install_plan(package, policy_path, pin, 1, root)
    except ValueError:
        refusals["fixture-installation"] = True
    else:
        raise AssertionError("Fixture authorized installation")
    assert not root.exists()
    disabled = ROOT / "docs/RELEASE_TRUST_POLICY.json"
    try:
        signed.install_plan(package, disabled, signed.digest_file(disabled), 1, root)
    except ValueError:
        refusals["disabled-production-policy"] = True
    else:
        raise AssertionError("Unconfigured trust authorized installation")
    assert not root.exists() and signed.digest_file(args.ledger / "ledger.json") == before
    report = {
        "format": 1,
        "passed": True,
        "fixture_only": True,
        "prepared": prepared,
        "verified": verified,
        "refusals": refusals,
        "installation_root_created": False,
        "candidate_code_executed": False,
        "real_ledger_unchanged": True,
        "private_keys_persisted": False,
        "production_identity_configured": False,
        "real_release_signed": False,
        "release_authorized": False,
    }
    (output / "verification.json").write_bytes(signed.review.encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
