"""Synthetic policies/packages, real account protection, no production identity or resident."""

import base64
from datetime import timedelta
import json
from pathlib import Path
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests import test_admission as grants
from tests.test_controller_trust import load
from tests.test_signed_package import NOW, save, setup_package, signed

managed = load("managed-update")
managed.admission, managed.signed = grants.admission, signed
managed.trust, managed.review = signed.trust, signed.review


def NATIVE(*_):
    return {"authenticode_verified": True}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    value = grants.fixture.__wrapped__(tmp_path, monkeypatch)
    value["head"] = grants.commit(value, grants.grant(value))
    value.update(checkpoint="new", anchor=tmp_path / "anchor", current=value.copy())
    return value


def cfg(fixture, next_signer=None):
    current = fixture["current"]
    return managed.inputs(
        fixture["root"],
        fixture["anchor"],
        fixture["checkpoint"],
        fixture["head"],
        current["policy_path"],
        current["pin"],
        current["windows"],
        current["windows_pin"],
        None if next_signer is None else next_signer["policy_path"],
        None if next_signer is None else next_signer["pin"],
        None if next_signer is None else next_signer["windows"],
        None if next_signer is None else next_signer["windows_pin"],
    )


def signatures(signer, statement):
    return [
        {
            "key_id": key["key_id"],
            "signature": base64.b64encode(private.sign(managed.message(statement))).decode(),
        }
        for key, private in zip(signer["policy"]["keys"], signer["private"])
    ]


def proposal(
    fixture, action="enroll", target=None, sequence=1, package=None, next_signer=None, now=NOW
):
    context = cfg(fixture, next_signer)
    directory = fixture["tmp"] / ("proposal-" + uuid.uuid4().hex)
    directory.mkdir()
    target = target or fixture["slot"]
    managed.grant_request(
        context, action, target, sequence, directory / "grant-request", package, hours=12, now=now
    )
    statement = json.loads((directory / "grant-request/statement.json").read_text())
    grant_path = grants.sign(next_signer or fixture["current"], statement, directory / "grant.json")
    managed.prepare(
        context,
        action,
        grant_path,
        directory / "change-request",
        package,
        now=now,
        _native_check=NATIVE,
    )
    statement = json.loads((directory / "change-request/statement.json").read_text())
    envelope = {
        "statement": statement,
        "signatures_before": signatures(fixture["current"], statement),
        "signatures_after": signatures(next_signer or fixture["current"], statement),
    }
    change_path = directory / "change.json"
    save(change_path, envelope)
    return {
        "cfg": context,
        "action": action,
        "grant": grant_path,
        "change": change_path,
        "package": package,
        "next": next_signer,
        "now": now,
    }


def reviewed(proposed):
    return managed.change(
        proposed["cfg"],
        proposed["action"],
        proposed["grant"],
        proposed["change"],
        proposed["package"],
        now=proposed["now"],
        _native_check=NATIVE,
    )


def apply(fixture, proposed, review=None):
    review = review or reviewed(proposed)
    result = managed.change(
        proposed["cfg"],
        proposed["action"],
        proposed["grant"],
        proposed["change"],
        proposed["package"],
        review["review_sha256"],
        proposed["now"],
        _native_check=NATIVE,
    )
    fixture["checkpoint"] = result["checkpoint"]
    fixture["head"] = signed.read(fixture["root"] / "authorizations/state.json")[0]["grant_sha256"]
    if proposed["next"] is not None:
        fixture["current"] = proposed["next"]
    fixture["slot"] = result["selected"]
    return result


def new_package(fixture, monkeypatch, sequence=2):
    directory = fixture["tmp"] / ("package-" + uuid.uuid4().hex)
    directory.mkdir()
    other = setup_package(directory, monkeypatch, "production", variant=uuid.uuid4().hex)
    manifest, _ = signed.read(other["package"] / signed.MANIFEST)
    signer = fixture["current"]
    manifest.update(policy_sha256=signer["pin"], sequence=sequence)
    save(other["package"] / signed.MANIFEST, manifest)
    raw = (other["package"] / signed.MANIFEST).read_bytes()
    statement = signed.statement_for(manifest, raw)
    envelope = {
        "format": 1,
        "kind": "inara-package-attestation",
        "statement": statement,
        "signatures": [
            {
                "key_id": key["key_id"],
                "signature": base64.b64encode(
                    private.sign(signed.signing_message(statement))
                ).decode(),
            }
            for key, private in zip(signer["policy"]["keys"], signer["private"])
        ],
    }
    save(other["package"] / signed.ENVELOPE, envelope)
    return other["package"], manifest["candidate_manifest_sha256"]


def rotated(fixture):
    old = fixture["current"]
    policy = json.loads(json.dumps(old["policy"]))
    private = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    for key, secret in zip(policy["keys"], private):
        public = secret.public_key().public_bytes_raw()
        key.update(key_id=signed.trust.sha(public), public_key=base64.b64encode(public).decode())
    policy["policy_sequence"] += 1
    directory = fixture["tmp"] / ("keys-" + uuid.uuid4().hex)
    directory.mkdir()
    path = directory / "policy.json"
    save(path, policy)
    return {
        **old,
        "policy": policy,
        "private": private,
        "policy_path": path,
        "pin": signed.digest_file(path),
    }


def test_enrollment_blocks_legacy_controls_and_pins_managed_launch(fixture):
    original_profile = fixture["root"] / "data" / fixture["slot"] / ".inara-data.json"
    before = original_profile.read_bytes()
    result = apply(fixture, proposal(fixture))
    assert result["previous_versions_retained"] and not result["launched"]
    state = signed.read(fixture["root"] / "installation.json")[0]
    assert state["format"] == 3 and state["kind"] == "authenticated-pilot-slots"
    with pytest.raises(ValueError):
        fixture["service"].load()
    assert original_profile.read_bytes() == before
    status = managed.status(fixture["root"], fixture["anchor"], fixture["checkpoint"])
    assert status["sequence_floor"] == 1 and status["selected"] == fixture["slot"]
    calls = []

    def run(executable, args, directory, env, expires):
        calls.append(True)
        assert args[:2] == ["-I", "-B"] and executable == directory / "runtime/python/python.exe"
        with pytest.raises(PermissionError):
            executable.write_text("MUST NOT WRITE")
        with pytest.raises(ValueError, match="busy"):
            managed.status(fixture["root"], fixture["anchor"], fixture["checkpoint"])
        return {"exit_code": 0}

    result = managed.launch(
        fixture["root"],
        fixture["anchor"],
        fixture["checkpoint"],
        now=NOW,
        _native_check=NATIVE,
        _run=run,
    )
    assert result["launched"] and calls == [True]


def test_renewal_and_rotation_retain_source_policy(fixture):
    apply(fixture, proposal(fixture))
    original_checkpoint = fixture["checkpoint"]
    apply(fixture, proposal(fixture, "renew", now=NOW + timedelta(hours=2)))
    with pytest.raises(ValueError):
        managed.status(fixture["root"], fixture["anchor"], original_checkpoint)
    next_signer = rotated(fixture)
    apply(
        fixture, proposal(fixture, "rotate", next_signer=next_signer, now=NOW + timedelta(hours=3))
    )
    apply(fixture, proposal(fixture, "renew", now=NOW + timedelta(hours=4)))
    node = managed.read_node(fixture["root"], fixture["anchor"], fixture["checkpoint"])
    assert fixture["pin"] in node["archives"]["release"] and next_signer["pin"] == node["policy"]
    result = managed.launch(
        fixture["root"],
        fixture["anchor"],
        fixture["checkpoint"],
        now=NOW + timedelta(hours=4),
        _native_check=NATIVE,
        _run=lambda *_: {"exit_code": 0},
    )
    assert result["launched"]


def test_update_and_explicit_rollback_preserve_floor_and_data(fixture, monkeypatch):
    original = fixture["slot"]
    apply(fixture, proposal(fixture))
    package, target = new_package(fixture, monkeypatch)
    apply(fixture, proposal(fixture, "update", target, 2, package))
    assert fixture["slot"] == target
    assert (fixture["root"] / "versions" / original).exists()
    assert (fixture["root"] / "data" / original / ".inara-data.json").exists()
    assert (
        managed.status(fixture["root"], fixture["anchor"], fixture["checkpoint"])["sequence_floor"]
        == 2
    )
    with pytest.raises(ValueError):
        proposal(fixture, "update", original, 1)
    apply(fixture, proposal(fixture, "rollback", original, 1))
    status = managed.status(fixture["root"], fixture["anchor"], fixture["checkpoint"])
    assert status["selected"] == original and status["sequence_floor"] == 2
    assert (fixture["root"] / "versions" / target).exists()


@pytest.mark.parametrize("boundary", ["installation.json", "state.json", "head.json", "after-head"])
def test_interrupted_transaction_requires_reviewed_recovery(fixture, monkeypatch, boundary):
    proposed = proposal(fixture)
    review = reviewed(proposed)
    original = managed.atomic

    def interrupted(path, raw):
        if path.name == boundary:
            raise OSError("Simulated commit interruption")
        original(path, raw)
        if boundary == "after-head" and path.name == "head.json":
            raise OSError("Simulated commit interruption after pointer")

    monkeypatch.setattr(managed, "atomic", interrupted)
    with pytest.raises(OSError):
        apply(fixture, proposed, review)
    with pytest.raises(ValueError):
        fixture["service"].load()
    monkeypatch.setattr(managed, "atomic", original)
    checkpoint = review["plan"]["checkpoint"]
    reviewed_resume = managed.resume(
        fixture["root"], fixture["anchor"], checkpoint, "new", now=NOW, _native_check=NATIVE
    )
    result = managed.resume(
        fixture["root"],
        fixture["anchor"],
        checkpoint,
        "new",
        reviewed_resume["review_sha256"],
        NOW,
        _native_check=NATIVE,
    )
    assert result["resumed"] and not (fixture["root"] / "update-pending.json").exists()
    assert managed.status(fixture["root"], fixture["anchor"], checkpoint)["number"] == 1


@pytest.mark.parametrize(
    "mutation",
    ["old-signatures", "new-signatures", "action", "target", "before", "extra", "expiry"],
)
def test_invalid_changes_refuse_before_activation(fixture, mutation):
    proposed = proposal(fixture)
    envelope, _ = signed.read(proposed["change"])
    if mutation == "old-signatures":
        envelope["signatures_before"] = []
    elif mutation == "new-signatures":
        envelope["signatures_after"] = []
    elif mutation == "action":
        envelope["statement"]["action"] = "rollback"
    elif mutation == "target":
        envelope["statement"]["target"] = "f" * 64
    elif mutation == "before":
        envelope["statement"]["installation_before"] = "f" * 64
    elif mutation == "extra":
        envelope["statement"]["ignore_checks"] = True
    else:
        proposed["now"] = NOW + timedelta(hours=2)
    save(proposed["change"], envelope)
    with pytest.raises(ValueError):
        reviewed(proposed)
    assert not (fixture["root"] / "update-pending.json").exists()
    assert not fixture["anchor"].exists()


def test_stale_review_and_wrong_checkpoint_refuse(fixture):
    proposed = proposal(fixture)
    review = reviewed(proposed)
    state = fixture["service"].load()
    fixture["service"].save(state)
    with pytest.raises(ValueError):
        apply(fixture, proposed, review)
    assert not fixture["anchor"].exists()


@pytest.mark.parametrize("mutation", ["sealed", "pointer", "metadata", "archived-policy"])
def test_changed_protected_state_refuses(fixture, mutation):
    apply(fixture, proposal(fixture))
    if mutation == "sealed":
        path = fixture["anchor"] / "checkpoints" / (fixture["checkpoint"] + ".bin")
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    elif mutation == "pointer":
        path = fixture["anchor"] / "head.json"
        value, _ = signed.read(path)
        value["checkpoint"] = "f" * 64
        save(path, value)
    elif mutation == "metadata":
        path = fixture["root"] / "installation.json"
        value, _ = signed.read(path)
        value["generation"] += 1
        save(path, value)
    else:
        (fixture["anchor"] / "policies" / (fixture["pin"] + ".json")).write_text("{}")
    with pytest.raises((ValueError, KeyError)):
        managed.status(fixture["root"], fixture["anchor"], fixture["checkpoint"])


def test_dpapi_round_trip_corruption_and_size():
    raw = b"owned synthetic checkpoint"
    protected = managed.protection.seal(raw)
    assert protected != raw and managed.protection.open_sealed(protected) == raw
    with pytest.raises(ValueError):
        managed.protection.open_sealed(protected[:-1] + bytes([protected[-1] ^ 1]))
    with pytest.raises(ValueError):
        managed.protection.seal(b"x" * (managed.protection.MAX_BYTES + 1))


def test_disabled_policy_and_nested_anchor_refuse(fixture):
    with pytest.raises(ValueError):
        managed.inputs(
            fixture["root"],
            fixture["root"] / "unsafe",
            "new",
            fixture["head"],
            fixture["policy_path"],
            fixture["pin"],
            fixture["windows"],
            fixture["windows_pin"],
        )


def test_policy_file_change_after_review_refuses_before_commit(fixture):
    proposed = proposal(fixture)
    review = reviewed(proposed)

    def changed(*_):
        fixture["policy_path"].write_text("{}")

    with pytest.raises(ValueError, match="trust changed"):
        managed.change(
            proposed["cfg"],
            "enroll",
            proposed["grant"],
            proposed["change"],
            expected_review=review["review_sha256"],
            now=NOW,
            _native_check=changed,
        )
    assert not fixture["anchor"].exists()
    assert not (fixture["root"] / "update-pending.json").exists()


def test_rotation_needs_both_authority_sets(fixture):
    apply(fixture, proposal(fixture))
    next_signer = rotated(fixture)
    proposed = proposal(fixture, "rotate", next_signer=next_signer)
    value, _ = signed.read(proposed["change"])
    value["signatures_after"] = value["signatures_before"]
    save(proposed["change"], value)
    with pytest.raises(ValueError):
        reviewed(proposed)


def test_format_two_recovery_selection_is_retained(fixture):
    state = fixture["service"].load()
    state["format"] = 2
    state["recovery"] = {"format": 1, "installation": state["id"], "slots": {}}
    fixture["service"].save(state)
    apply(fixture, proposal(fixture))
    after, _ = signed.read(fixture["root"] / "installation.json")
    assert after["recovery"] == state["recovery"]


def test_protected_checkpoint_cannot_bind_another_root(fixture):
    apply(fixture, proposal(fixture))
    with pytest.raises(ValueError):
        managed.read_node(fixture["tmp"] / "other", fixture["anchor"], fixture["checkpoint"])


def test_copy_failure_can_be_cancelled_without_deleting_copies(fixture, monkeypatch):
    apply(fixture, proposal(fixture))
    previous = fixture["checkpoint"]
    package, target = new_package(fixture, monkeypatch)
    proposed = proposal(fixture, "update", target, 2, package)
    review = reviewed(proposed)

    def partial(source, destination, **kwargs):
        destination.mkdir()
        (destination / "unknown-partial.txt").write_text("PRESERVE")
        raise OSError("Interrupted copy")

    monkeypatch.setattr(managed.shutil, "copytree", partial)
    with pytest.raises(OSError):
        apply(fixture, proposed, review)
    checkpoint = review["plan"]["checkpoint"]
    abort_review = managed.abort(fixture["root"], fixture["anchor"], checkpoint, previous)
    result = managed.abort(
        fixture["root"], fixture["anchor"], checkpoint, previous, abort_review["review_sha256"]
    )
    assert result["cancelled"] and result["copies_retained"]
    assert managed.status(fixture["root"], fixture["anchor"], previous)["checkpoint"] == previous
    assert (
        fixture["root"] / "transactions" / target / "unknown-partial.txt"
    ).read_text() == "PRESERVE"


@pytest.mark.parametrize("mutation", ["journal", "metadata", "wrong-new-pin", "wrong-old-pin"])
def test_recovery_refuses_changed_evidence(fixture, monkeypatch, mutation):
    proposed = proposal(fixture)
    review = reviewed(proposed)
    original = managed.atomic

    def interrupted(*_):
        raise OSError("Simulated crash before first metadata write")

    monkeypatch.setattr(managed, "atomic", interrupted)
    with pytest.raises(OSError):
        apply(fixture, proposed, review)
    monkeypatch.setattr(managed, "atomic", original)
    journal = fixture["root"] / "update-pending.json"
    if mutation == "journal":
        value, _ = signed.read(journal)
        value["installation_after"] = base64.b64encode(b"{}").decode()
        save(journal, value)
    elif mutation == "metadata":
        path = fixture["root"] / "installation.json"
        value, _ = signed.read(path)
        value["generation"] += 10
        save(path, value)
    checkpoint = "f" * 64 if mutation == "wrong-new-pin" else review["plan"]["checkpoint"]
    previous = "f" * 64 if mutation == "wrong-old-pin" else "new"
    with pytest.raises((ValueError, OSError)):
        managed.resume(
            fixture["root"], fixture["anchor"], checkpoint, previous, now=NOW, _native_check=NATIVE
        )
    assert journal.exists()


def test_cancellation_refuses_after_metadata_commit_started(fixture, monkeypatch):
    proposed = proposal(fixture)
    review = reviewed(proposed)
    original = managed.atomic

    def interrupted(path, raw):
        if path.name == "state.json":
            raise OSError("Interrupted second metadata write")
        original(path, raw)

    monkeypatch.setattr(managed, "atomic", interrupted)
    with pytest.raises(OSError):
        apply(fixture, proposed, review)
    monkeypatch.setattr(managed, "atomic", original)
    with pytest.raises(ValueError, match="commit started"):
        managed.abort(fixture["root"], fixture["anchor"], review["plan"]["checkpoint"], "new")
    path = Path(managed.ROOT) / "docs/RELEASE_TRUST_POLICY.json"
    with pytest.raises(ValueError):
        managed.inputs(
            fixture["root"],
            fixture["anchor"],
            "new",
            fixture["head"],
            path,
            signed.digest_file(path),
            fixture["windows"],
            fixture["windows_pin"],
        )
