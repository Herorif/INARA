"""Synthetic public custody/reviews and ephemeral external signatures; never real enrollment."""

import base64
from datetime import timedelta
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests import test_controller_provenance as fixtures
from tests.test_controller_trust import load
from tests.test_signed_package import NOW

delivery = load("controller-delivery")
custody, reviews = delivery.custody, delivery.reviews


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(reviews.old.encoded(value) if isinstance(value, dict) else value)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    controller, pin, evidence, source = fixtures.fixture.__wrapped__(tmp_path, monkeypatch)
    fixtures.write(controller, "scripts/open-trusted-controller.ps1", "INERT FIXTURE BOOTSTRAP / NEVER EXECUTE")
    fixtures.tool.run("collect", controller, pin, evidence, source)
    monkeypatch.setattr(reviews, "provenance", fixtures.tool)
    ledger = tmp_path / "ledger"
    reviews.create(controller, pin, evidence, ledger, source)
    private = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    policy = {"format": 1, "kind": "inara-release-trust-policy", "mode": "production", "publisher": "SYNTHETIC TEST OWNER",
              "channel": "pilot", "policy_sequence": 1, "minimum_sequence": 1,
              "thresholds": {"publisher": 1, "reviewer": 1}, "keys": []}
    for role, secret in zip(("publisher", "reviewer"), private):
        public = secret.public_key().public_bytes_raw()
        policy["keys"].append({"key_id": reviews.trust.sha(public), "public_key": base64.b64encode(public).decode(),
                               "identity": "Synthetic " + role, "role": role, "state": "active",
                               "not_before": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "not_after": (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    policy_path, windows_path = tmp_path / "release.json", tmp_path / "windows.json"
    save(policy_path, policy)
    save(windows_path, {"format": 1, "kind": "inara-windows-signing-policy", "mode": "production", "targets": [{"path": "runtime/python.exe", "signer_sha256": "a" * 64, "timestamp_sha256": "b" * 64}]})
    enrollment = tmp_path / "enrollment"
    custody.draft(enrollment)
    text = b"SYNTHETIC PUBLIC TEST ASSERTIONS. Not legal, hardware or custody evidence."
    digest = reviews.trust.sha(text)
    save(enrollment / "evidence" / (digest + ".txt"), text)
    plan = json.loads((enrollment / "enrollment.json").read_bytes())
    plan.update(state="reviewed", publisher=policy["publisher"], release_policy_sha256=reviews.signed.digest_file(policy_path),
                windows_policy_sha256=reviews.signed.digest_file(windows_path), independence_reviewed=True)
    for key in policy["keys"]:
        plan["custody"].append({"key_id": key["key_id"], "operator": "synthetic-" + key["role"], "custody_ref": "fixture/vault",
                                "recovery_ref": "fixture/recovery", "revocation_ref": "fixture/revocation", "recovery_drill_verified": True,
                                "checked_on": NOW.date().isoformat(), "evidence_sha256": digest})
    plan["windows_custody"] = {"operator": "synthetic-windows", "signing_ref": "fixture/signer", "timestamp_ref": "fixture/timestamp", "recovery_ref": "fixture/recovery", "revocation_ref": "fixture/revocation", "recovery_drill_verified": True, "checked_on": NOW.date().isoformat(), "evidence_sha256": digest}
    plan["bootstrap_delivery"] = {"operator": "synthetic-bootstrap", "independent_channel_ref": "fixture/independent", "verification_ref": "fixture/reviewed-checkout", "checked_on": NOW.date().isoformat(), "evidence_sha256": digest}
    save(enrollment / "enrollment.json", plan)
    return {"tmp": tmp_path, "controller": controller, "pin": pin, "evidence": evidence, "source": source, "ledger": ledger,
            "policy_path": policy_path, "windows_path": windows_path, "policy": policy, "private": private, "enrollment": enrollment}


def args(value):
    return (value["controller"], value["pin"], value["evidence"], value["ledger"], value["enrollment"],
            reviews.signed.digest_file(value["enrollment"] / "enrollment.json"), value["policy_path"], reviews.signed.digest_file(value["policy_path"]),
            value["windows_path"], reviews.signed.digest_file(value["windows_path"]))


def request(value, subject, status="approved", name="request.json"):
    file = value["tmp"] / "public-evidence.txt"
    file.write_text("SYNTHETIC TEST EVIDENCE ONLY; NOT AN ACTUAL APPROVAL.")
    path = value["tmp"] / name
    save(path, {"subject_id": subject["id"], "subject_sha256": reviews.old.hashed(subject), "status": status,
                "reviewer": "Synthetic test reviewer", "rationale": "Test assertion integrity only", "reviewed_on": NOW.date().isoformat(),
                "evidence": [{"kind": kind, "file": str(file), "source": "https://example.invalid/synthetic"} for kind in subject["required_evidence"]]})
    return path


def approved(value):
    base = reviews.inspect(value["controller"], value["pin"], value["evidence"], value["ledger"], value["source"])[0]["base"]
    for index, subject in enumerate(base["subjects"]):
        path = request(value, subject)
        output = value["tmp"] / ("revision-" + str(index))
        common = (value["controller"], value["pin"], value["evidence"], value["ledger"], path, output)
        planned = reviews.plan(*common, source=value["source"])[0]
        result = reviews.apply(*common, planned["review_sha256"], source=value["source"])
        value["ledger"] = output
    assert result["recorded_reviews_complete"] and not result["release_authorized"]


def native(*_):
    return {"authenticode_verified": True, "cache_only": True, "native_files": 1}


def signed_delivery(value):
    approved(value)
    output = value["tmp"] / "unsigned-request"
    delivery.prepare(*args(value), 1, output, source=value["source"], now=NOW, _native_check=native)
    statement = json.loads((output / "statement.json").read_bytes())
    message = delivery.DOMAIN + reviews.old.encoded(statement)
    assert (output / "signing-message.bin").read_bytes() == message
    signatures = [{"key_id": key["key_id"], "signature": base64.b64encode(secret.sign(message)).decode()} for key, secret in zip(value["policy"]["keys"], value["private"])]
    path = value["tmp"] / "signed-delivery.json"
    save(path, {"statement": statement, "signatures": signatures})
    return path


def test_controller_review_revision_preserves_original_and_never_authenticates_owner(fixture):
    value = fixture
    initial = (value["ledger"] / "ledger.json").read_bytes()
    base, statuses = reviews.inspect(value["controller"], value["pin"], value["evidence"], value["ledger"], value["source"])
    assert set(statuses.values()) == {"pending"}
    subject = next(s for s in base["base"]["subjects"] if s["category"] == "delivery-input")
    path = request(value, subject)
    output = value["tmp"] / "reviewed"
    common = (value["controller"], value["pin"], value["evidence"], value["ledger"], path, output)
    planned = reviews.plan(*common, source=value["source"])[0]
    assert not output.exists()
    result = reviews.apply(*common, planned["review_sha256"], source=value["source"])
    assert result["decisions"]["approved"] == 1 and not result["reviewer_authenticated"] and not result["release_ready"]
    assert (value["ledger"] / "ledger.json").read_bytes() == initial
    reviews.inspect(value["controller"], value["pin"], value["evidence"], output, value["source"])


@pytest.mark.parametrize("kind", ["missing-evidence", "request-changed", "attachment-changed", "wrong-review", "existing-output"])
def test_review_apply_refuses_drift_and_missing_kinds(fixture, kind):
    value = fixture
    base, _ = reviews.inspect(value["controller"], value["pin"], value["evidence"], value["ledger"], value["source"])
    path = request(value, base["base"]["subjects"][-1])
    output = value["tmp"] / "new-review"
    common = (value["controller"], value["pin"], value["evidence"], value["ledger"], path, output)
    planned = reviews.plan(*common, source=value["source"])[0]
    expected = planned["review_sha256"]
    if kind in {"missing-evidence", "request-changed"}:
        body = json.loads(path.read_bytes())
        if kind == "missing-evidence":
            body["evidence"] = body["evidence"][:-1]
        else:
            body["rationale"] = "changed"
        save(path, body)
    elif kind == "attachment-changed":
        (value["tmp"] / "public-evidence.txt").write_text("Changed evidence")
    elif kind == "wrong-review":
        expected = "0" * 64
    else:
        output.mkdir()
    with pytest.raises(ValueError):
        reviews.apply(*common, expected, source=value["source"])
    if kind != "existing-output":
        assert not output.exists()


@pytest.mark.parametrize("kind", ["head", "events", "extra", "evidence", "other-controller"])
def test_ledger_history_closure_and_controller_binding(fixture, kind):
    value = fixture
    approved(value)
    file = value["ledger"] / "ledger.json"
    body = json.loads(file.read_bytes())
    if kind == "head":
        body["head_sha256"] = "0" * 64
    elif kind == "events":
        body["events"] = list(reversed(body["events"]))
    elif kind == "extra":
        (value["ledger"] / "foreign.txt").write_text("extra")
    elif kind == "evidence":
        next((value["ledger"] / "evidence").iterdir()).write_text("changed")
    else:
        value["pin"] = "0" * 64
    if kind in {"head", "events"}:
        save(file, body)
    with pytest.raises(ValueError):
        reviews.inspect(value["controller"], value["pin"], value["evidence"], value["ledger"], value["source"])


def test_draft_preserves_disabled_policies_and_reports_blockers(tmp_path):
    directory = tmp_path / "draft"
    result = custody.draft(directory)
    release, windows = Path(custody.ROOT / "docs/RELEASE_TRUST_POLICY.json"), Path(custody.ROOT / "docs/WINDOWS_SIGNING_POLICY.json")
    before = release.read_bytes(), windows.read_bytes()
    report = custody.assess(directory, result["enrollment_sha256"], release, reviews.signed.digest_file(release), windows, reviews.signed.digest_file(windows), NOW)
    assert not report["ready"] and "custody_plan_is_draft" in report["blockers"]
    assert "release_identity_not_configured" in report["blockers"] and "windows_signing_not_configured" in report["blockers"]
    assert before == (release.read_bytes(), windows.read_bytes())
    with pytest.raises(ValueError):
        custody.draft(directory)


@pytest.mark.parametrize("kind", ["same-operator", "missing-key", "recovery-drill", "policy-binding", "missing-bootstrap", "future-date", "wrong-pin", "private-field", "evidence-tamper", "unregistered-key-file"])
def test_public_custody_refuses_incomplete_assertions_or_bad_inputs(fixture, kind):
    value = fixture
    file = value["enrollment"] / "enrollment.json"
    body = json.loads(file.read_bytes())
    if kind == "same-operator":
        body["custody"][1]["operator"] = body["custody"][0]["operator"]
    elif kind == "missing-key":
        body["custody"].pop()
    elif kind == "recovery-drill":
        body["custody"][0]["recovery_drill_verified"] = False
    elif kind == "policy-binding":
        body["release_policy_sha256"] = "0" * 64
    elif kind == "missing-bootstrap":
        body["bootstrap_delivery"] = None
    elif kind == "future-date":
        body["custody"][0]["checked_on"] = "2999-01-01"
    elif kind == "private-field":
        body["private_key"] = "REFUSED"
    elif kind == "evidence-tamper":
        next((value["enrollment"] / "evidence").iterdir()).write_text("changed")
    elif kind == "unregistered-key-file":
        (value["enrollment"] / "private.pfx").write_bytes(b"INERT TEST ONLY")
    save(file, body)
    expected = "0" * 64 if kind == "wrong-pin" else reviews.signed.digest_file(file)
    common = (value["enrollment"], expected, value["policy_path"], reviews.signed.digest_file(value["policy_path"]), value["windows_path"], reviews.signed.digest_file(value["windows_path"]))
    if kind in {"future-date", "wrong-pin", "private-field", "evidence-tamper", "unregistered-key-file"}:
        with pytest.raises(ValueError):
            custody.assess(*common, now=NOW)
    else:
        assert not custody.assess(*common, now=NOW)["ready"]


def test_pending_reviews_block_unsigned_request_and_native_probe(fixture):
    value = fixture
    def no_probe(*_):
        raise AssertionError("Incomplete reviews must not trigger a native check")
    result = delivery.readiness(*args(value), source=value["source"], now=NOW, _native_check=no_probe)
    assert not result["ready_for_signing_request"] and "controller_review_decisions_incomplete" in result["blockers"]
    output = value["tmp"] / "refused"
    with pytest.raises(ValueError):
        delivery.prepare(*args(value), 1, output, source=value["source"], now=NOW, _native_check=no_probe)
    assert not output.exists()


def test_detached_delivery_verifies_exact_bindings_without_launch_or_enrollment(fixture):
    value = fixture
    path = signed_delivery(value)
    result = delivery.verify(*args(value), 1, path, source=value["source"], now=NOW, _native_check=native)
    assert result["delivery_signatures_verified"] and result["bootstrap_detached_binding_verified"]
    assert all(result[key] is False for key in ("release_authorized", "legal_identity_established", "launched", "installed", "policy_enrolled"))


@pytest.mark.parametrize("kind", ["missing-signatures", "wrong-domain", "expired", "sequence", "bootstrap", "policy-pin", "review-change", "custody-change", "native-failure", "mid-check-evidence"])
def test_delivery_refuses_wrong_authority_drift_and_native_failures(fixture, monkeypatch, kind):
    value = fixture
    path = signed_delivery(value)
    envelope = json.loads(path.read_bytes())
    now, sequence, check = NOW, 1, native
    if kind == "missing-signatures":
        envelope["signatures"] = []
        monkeypatch.setattr(delivery, "readiness", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Payload checked before signatures")))
    elif kind == "wrong-domain":
        for item, secret in zip(envelope["signatures"], value["private"]):
            item["signature"] = base64.b64encode(secret.sign(b"WRONG-DOMAIN\n" + reviews.old.encoded(envelope["statement"]))).decode()
    elif kind == "expired":
        now += timedelta(hours=2)
    elif kind == "sequence":
        sequence = 2
    elif kind == "bootstrap":
        (value["controller"] / "scripts/open-trusted-controller.ps1").write_text("changed")
    elif kind == "policy-pin":
        envelope["statement"]["policy_sha256"] = "0" * 64
    elif kind == "review-change":
        (value["ledger"] / "foreign.txt").write_text("changed")
    elif kind == "custody-change":
        body = json.loads((value["enrollment"] / "enrollment.json").read_bytes())
        body["independence_reviewed"] = False
        save(value["enrollment"] / "enrollment.json", body)
    elif kind == "native-failure":
        def check(*_):
            return {"authenticode_verified": False, "cache_only": True}
    else:
        def check(*_):
            (value["ledger"] / "foreign.txt").write_text("changed during native check")
            return native()
    save(path, envelope)
    with pytest.raises(ValueError):
        delivery.verify(*args(value), sequence, path, source=value["source"], now=now, _native_check=check)
