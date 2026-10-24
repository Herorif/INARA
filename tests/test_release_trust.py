"""Ephemeral test-only signing keys. No certificate store, real reviewer or release."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

spec = importlib.util.spec_from_file_location(
    "trust", Path(__file__).resolve().parents[1] / "scripts/release-trust.py"
)
trust = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trust)
NOW = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)


def save(path, value):
    path.write_bytes(trust.review.encoded(value))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    roots = []
    for name in ["candidate", "audit", "ledger"]:
        root = tmp_path / name
        root.mkdir()
        roots.append(root)
    private = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    keys = []
    for role, key in zip(["publisher", "reviewer"], private):
        public = key.public_key().public_bytes_raw()
        keys.append(
            {
                "key_id": trust.sha(public),
                "public_key": base64.b64encode(public).decode(),
                "identity": "Synthetic " + role,
                "role": role,
                "state": "active",
                "not_before": "2026-10-21T00:00:00Z",
                "not_after": "2026-10-24T00:00:00Z",
            }
        )
    policy = {
        "format": 1,
        "kind": "inara-release-trust-policy",
        "mode": "fixture",
        "policy_sequence": 1,
        "publisher": "TEST ONLY",
        "channel": "pilot",
        "minimum_sequence": 3,
        "thresholds": {"publisher": 1, "reviewer": 1},
        "keys": keys,
    }
    policy_path = tmp_path / "fixture-policy.json"
    save(policy_path, policy)
    bindings = {
        key: str(index) * 64
        for index, key in enumerate(
            [
                "candidate_manifest_sha256",
                "candidate_inventory_sha256",
                "audit_report_sha256",
                "ledger_sha256",
                "ledger_head_sha256",
            ],
            1,
        )
    }
    monkeypatch.setattr(trust, "material", lambda *_: (bindings, False))
    output = tmp_path / "request"
    pin = trust.sha(policy_path.read_bytes())
    result = trust.prepare(*roots, policy_path, pin, 3, output, now=NOW, allow_fixture=True)
    assert not result["signed"] and not result["private_keys_accessed"]
    statement = json.loads((output / "statement.json").read_text())
    envelope_path = tmp_path / "fixture-envelope.json"

    def signed(statement=statement):
        return {
            "format": 1,
            "kind": "inara-detached-attestation",
            "statement": deepcopy(statement),
            "signatures": [
                {
                    "key_id": key["key_id"],
                    "signature": base64.b64encode(priv.sign(trust.message(statement))).decode(),
                }
                for key, priv in zip(keys, private)
            ],
        }

    save(envelope_path, signed())
    return {
        "roots": roots,
        "root": tmp_path,
        "policy": policy,
        "policy_path": policy_path,
        "pin": pin,
        "envelope": envelope_path,
        "signed": signed,
        "bindings": bindings,
        "private": private,
    }


def check(s, **kwargs):
    return trust.verify(
        *s["roots"],
        s["policy_path"],
        s["pin"],
        s["envelope"],
        3,
        now=NOW,
        allow_fixture=True,
        **kwargs,
    )


def test_distinct_role_signatures_bind_every_payload_and_never_authorize_release(setup):
    result = check(setup)
    assert result["fixture_only"] and result["whole_payload_binding_verified"]
    assert result["signatures"] == {"publisher": 1, "reviewer": 1}
    assert not result["release_authorized"] and not result["authenticode_verified"]
    assert not result["legal_identity_established"] and not result["review_records_complete"]


@pytest.mark.parametrize(
    "kind",
    [
        "signature",
        "unknown_key",
        "duplicate",
        "missing_reviewer",
        "embedded_key",
        "payload",
        "publisher",
        "channel",
        "usage",
        "sequence",
        "policy_digest",
        "future",
        "expired",
        "excessive_window",
        "extra_field",
    ],
)
def test_modified_untrusted_or_stale_attestations_refuse(setup, kind):
    envelope = setup["signed"]()
    if kind == "signature":
        envelope["signatures"][0]["signature"] = base64.b64encode(b"x" * 64).decode()
    elif kind == "unknown_key":
        envelope["signatures"][0]["key_id"] = "0" * 64
    elif kind == "duplicate":
        envelope["signatures"].append(envelope["signatures"][0])
    elif kind == "missing_reviewer":
        envelope["signatures"].pop()
    elif kind == "embedded_key":
        envelope["signatures"][0]["public_key"] = setup["policy"]["keys"][0]["public_key"]
    elif kind == "extra_field":
        envelope["release_authorized"] = True
    else:
        field, value = {
            "payload": ("ledger_sha256", "0" * 64),
            "publisher": ("publisher", "Other"),
            "channel": ("channel", "stable"),
            "usage": ("usage", "production"),
            "sequence": ("sequence", 2),
            "policy_digest": ("policy_sha256", "0" * 64),
            "future": ("issued_at", "2026-10-23T00:00:00Z"),
            "expired": ("expires_at", "2026-10-21T23:59:59Z"),
            "excessive_window": ("expires_at", "2026-10-24T00:00:00Z"),
        }[kind]
        statement = envelope["statement"]
        statement[field] = value
        envelope = setup["signed"](statement)  # Even correctly signed mismatched bindings refuse.
    save(setup["envelope"], envelope)
    with pytest.raises(ValueError):
        check(setup)


@pytest.mark.parametrize(
    "kind",
    [
        "pin",
        "duplicate_key",
        "wrong_fingerprint",
        "revoked",
        "key_expired",
        "key_future",
        "missing_role",
        "false_threshold",
        "credential_field",
        "disabled",
        "duplicate_json",
    ],
)
def test_external_policy_errors_fail_closed(setup, kind):
    policy = deepcopy(setup["policy"])
    if kind == "pin":
        setup["pin"] = "0" * 64
    elif kind == "duplicate_key":
        policy["keys"].append(policy["keys"][0])
    elif kind == "wrong_fingerprint":
        policy["keys"][0]["key_id"] = "0" * 64
    elif kind == "revoked":
        policy["keys"][0]["state"] = "revoked"
    elif kind == "key_expired":
        policy["keys"][0]["not_after"] = "2026-10-21T12:00:00Z"
    elif kind == "key_future":
        policy["keys"][0]["not_before"] = "2026-10-22T12:00:00Z"
    elif kind == "missing_role":
        policy["keys"][1]["role"] = "publisher"
    elif kind == "false_threshold":
        policy["thresholds"]["reviewer"] = True
    elif kind == "credential_field":
        policy["private_key"] = "NEVER_ACCEPTED"
    elif kind == "disabled":
        policy.update(mode="disabled", publisher=None, keys=[])
    else:
        setup["policy_path"].write_text('{"format":1,"format":1}')
    if kind != "duplicate_json":
        save(setup["policy_path"], policy)
    if kind != "pin":
        setup["pin"] = trust.sha(setup["policy_path"].read_bytes())
        envelope = setup["signed"]()
        envelope["statement"]["policy_sha256"] = setup["pin"]
        save(setup["envelope"], setup["signed"](envelope["statement"]))
    with pytest.raises(ValueError):
        check(setup)


@pytest.mark.parametrize(
    "field",
    [
        "candidate_manifest_sha256",
        "candidate_inventory_sha256",
        "audit_report_sha256",
        "ledger_sha256",
        "ledger_head_sha256",
    ],
)
def test_source_drift_after_signing_refuses(setup, field):
    setup["bindings"][field] = "0" * 64
    with pytest.raises(ValueError):
        check(setup)


def test_fixture_policy_requires_explicit_option(setup):
    with pytest.raises(ValueError, match="explicit fixture"):
        trust.verify(
            *setup["roots"], setup["policy_path"], setup["pin"], setup["envelope"], 3, now=NOW
        )


def test_production_preparation_refuses_incomplete_real_reviews(setup):
    policy = setup["policy"]
    policy["mode"] = "production"
    save(setup["policy_path"], policy)
    output = setup["root"] / "production-request"
    with pytest.raises(ValueError, match="incomplete"):
        trust.prepare(
            *setup["roots"],
            setup["policy_path"],
            trust.sha(setup["policy_path"].read_bytes()),
            3,
            output,
            now=NOW,
        )
    assert not output.exists()


def test_policy_inside_candidate_is_not_a_trust_anchor(setup):
    path = setup["roots"][0] / "policy.json"
    save(path, setup["policy"])
    with pytest.raises(ValueError, match="outside"):
        trust.verify(
            *setup["roots"],
            path,
            trust.sha(path.read_bytes()),
            setup["envelope"],
            3,
            now=NOW,
            allow_fixture=True,
        )


def test_existing_request_is_not_overwritten(setup):
    request = setup["root"] / "request"
    before = (request / "signing-message.bin").read_bytes()
    with pytest.raises(ValueError):
        trust.prepare(
            *setup["roots"],
            setup["policy_path"],
            setup["pin"],
            3,
            request,
            now=NOW,
            allow_fixture=True,
        )
    assert (request / "signing-message.bin").read_bytes() == before


@pytest.mark.parametrize("target", ["policy", "envelope", "statement"])
def test_boolean_format_numbers_are_not_accepted(setup, target):
    if target == "policy":
        setup["policy"]["format"] = True
        save(setup["policy_path"], setup["policy"])
        setup["pin"] = trust.sha(setup["policy_path"].read_bytes())
    else:
        value = setup["signed"]()
        if target == "envelope":
            value["format"] = True
        else:
            value["statement"]["format"] = True
            value = setup["signed"](value["statement"])
        save(setup["envelope"], value)
    with pytest.raises(ValueError):
        check(setup)


def test_prepare_refuses_keys_expiring_before_request_window(setup):
    setup["policy"]["keys"][0]["not_after"] = "2026-10-22T00:05:00Z"
    save(setup["policy_path"], setup["policy"])
    output = setup["root"] / "expired-request"
    with pytest.raises(ValueError, match="cover the signing window"):
        trust.prepare(
            *setup["roots"],
            setup["policy_path"],
            trust.sha(setup["policy_path"].read_bytes()),
            3,
            output,
            now=NOW,
            allow_fixture=True,
        )
    assert not output.exists()
