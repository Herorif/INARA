"""Development-host account-protection/refusal proof. Never configures production trust."""

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("qa_managed", ROOT / "scripts/managed-update.py")
    managed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(managed)
    output = managed.signed.plain(args.output)
    if output.exists():
        parser.error("Choose a NEW acceptance directory")
    output.mkdir(parents=True)
    root, anchor = output / "never-created-installation", output / "probe-anchor"
    raw = managed.review.encoded(
        {"format": 1, "kind": "synthetic-unsigned-state", "root": str(root)}
    )
    sealed = managed.protection.seal(raw)
    assert sealed != raw and managed.protection.open_sealed(sealed) == raw
    digest = managed.trust.sha(raw)
    path = anchor / "checkpoints" / (digest + ".bin")
    managed.retain(path, sealed)
    try:
        managed.read_node(root, anchor, digest)
    except ValueError:
        unsigned_refused = True
    else:
        raise AssertionError("Account encryption was incorrectly treated as signed authorization")
    corrupted = sealed[:-1] + bytes([sealed[-1] ^ 1])
    try:
        managed.protection.open_sealed(corrupted)
    except ValueError:
        corruption_refused = True
    else:
        raise AssertionError("Corrupted checkpoint accepted")
    for name in ("RELEASE_TRUST_POLICY.json", "WINDOWS_SIGNING_POLICY.json"):
        assert json.loads((ROOT / "docs" / name).read_text())["mode"] == "disabled"
    assert not root.exists()
    value = {
        "format": 1,
        "kind": "inara-managed-state-development-acceptance",
        "account_protection_round_trip": True,
        "corrupted_ciphertext_refused": corruption_refused,
        "unsigned_encrypted_metadata_refused": unsigned_refused,
        "protected_state_sha256": managed.signed.digest_file(ROOT / "scripts/protected-state.py"),
        "managed_update_sha256": managed.signed.digest_file(ROOT / "scripts/managed-update.py"),
        "production_policies_disabled": True,
        "production_identity_configured": False,
        "production_installation_created": False,
        "real_release_signed": False,
        "resident_launched": False,
        "cross_account_acceptance_verified": False,
        "hardware_monotonic_counter": False,
        "release_authorized": False,
    }
    (output / "result.json").write_bytes(managed.review.encoded(value))
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
