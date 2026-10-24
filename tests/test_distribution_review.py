"""Immutable review revisions with synthetic decisions; no real approval or release."""

import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "review", Path(__file__).resolve().parents[1] / "scripts/distribution-review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    candidate, audited, ledger = (tmp_path / name for name in ("candidate", "audit", "ledger"))
    candidate.mkdir()
    audited.mkdir()
    report = {
        "candidate_manifest_sha256": "a" * 64,
        "candidate_inventory_sha256": "b" * 64,
        "components": [
            {"ecosystem": "runtime", "name": "CPython", "version": "fixture", "notices": []}
        ],
        "asset_reviews": [{"path": "public/fixture.task", "sha256": "c" * 64}],
        "missing_notice_components": [{"name": "fixture", "version": "1"}],
        "review_gaps": ["Fixture only"],
    }
    (audited / "distribution-audit.json").write_text(json.dumps(report))
    monkeypatch.setattr(review.audit, "verify", lambda *_: {"integrity": "passed"})
    result = review.create(candidate, audited, ledger)
    assert result["decisions"] == {"pending": 5, "approved": 0, "rejected": 0}
    return candidate, audited, ledger, tmp_path


def request_for(setup, category="asset", status="approved", previous=None):
    candidate, audited, ledger, root = setup
    ledger = previous or ledger
    state, _ = review.inspect(candidate, audited, ledger)
    subject = next(s for s in state["base"]["subjects"] if s["category"] == category)
    evidence = root / "fixture-evidence.txt"
    evidence.write_text("SYNTHETIC EVIDENCE ONLY. Not a real ownership or license decision.")
    body = {
        "subject_id": subject["id"],
        "subject_sha256": review.hashed(subject),
        "status": status,
        "reviewer": "Synthetic test reviewer",
        "rationale": "Fixture verifies record integrity only.",
        "reviewed_on": "2026-10-22",
        "evidence": [
            {"kind": kind, "file": str(evidence), "source": "https://example.com/fixture"}
            for kind in subject["required_evidence"]
        ],
    }
    request = root / "request.json"
    request.write_text(json.dumps(body))
    return request, body


def perform(setup, category="asset", status="approved", previous=None, name="revision"):
    candidate, audited, ledger, root = setup
    ledger = previous or ledger
    request, _ = request_for(setup, category, status, ledger)
    output = root / name
    planned = review.plan(candidate, audited, ledger, request, output)[0]
    assert not output.exists()
    result = review.apply(candidate, audited, ledger, request, output, planned["review_sha256"])
    return output, result


def test_approval_and_reset_preserve_prior_records_and_never_clear_release(setup):
    candidate, audited, ledger, _ = setup
    original = (ledger / "ledger.json").read_bytes()
    output, result = perform(setup)
    assert result["decisions"]["approved"] == 1 and not result["release_ready"]
    assert not result["reviewer_authenticated"] and not result["redistribution_cleared"]
    assert (ledger / "ledger.json").read_bytes() == original
    prior = (output / "ledger.json").read_bytes()
    newer, result = perform(setup, status="pending", previous=output, name="reset")
    state, statuses = review.inspect(candidate, audited, newer)
    assert len(state["events"]) == 2 and set(statuses.values()) == {"pending"}
    assert (output / "ledger.json").read_bytes() == prior
    assert list((newer / "evidence").glob("*.txt"))


@pytest.mark.parametrize("category", list(review.REQUIRED))
def test_subject_specific_evidence_kinds_are_mandatory(setup, category):
    candidate, audited, ledger, root = setup
    request, body = request_for(setup, category)
    body["evidence"] = body["evidence"][:-1]
    request.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="requires all"):
        review.plan(candidate, audited, ledger, request, root / "blocked")
    assert not (root / "blocked").exists()


@pytest.mark.parametrize("kind", ["request", "evidence", "destination", "subject", "review_digest"])
def test_apply_refuses_stale_exact_review_before_any_output(setup, kind):
    candidate, audited, ledger, root = setup
    request, body = request_for(setup)
    output = root / "new"
    digest = review.plan(candidate, audited, ledger, request, output)[0]["review_sha256"]
    if kind == "request":
        body["rationale"] = "Changed rationale"
    elif kind == "evidence":
        (root / "fixture-evidence.txt").write_text("Changed evidence")
    elif kind == "destination":
        output = root / "different"
    elif kind == "subject":
        body["subject_sha256"] = "0" * 64
    else:
        digest = "0" * 64
    request.write_text(json.dumps(body))
    with pytest.raises(ValueError):
        review.apply(candidate, audited, ledger, request, output, digest)
    assert not output.exists()


@pytest.mark.parametrize(
    "kind",
    [
        "history",
        "head",
        "missing_evidence",
        "changed_evidence",
        "extra",
        "clearance_claim",
        "changed_audit",
    ],
)
def test_verification_refuses_tampered_or_stale_ledgers(setup, kind):
    candidate, audited, _, _ = setup
    output, _ = perform(setup)
    path = output / "ledger.json"
    value = json.loads(path.read_text())
    if kind == "history":
        value["events"][0]["decision"]["status"] = "pending"
    elif kind == "head":
        value["head_sha256"] = "0" * 64
    elif kind == "missing_evidence":
        next((output / "evidence").iterdir()).unlink()
    elif kind == "changed_evidence":
        next((output / "evidence").iterdir()).write_text("Changed")
    elif kind == "extra":
        (output / "extra.txt").write_text("Extra")
    elif kind == "clearance_claim":
        value["release_ready"] = True
    else:
        report = json.loads((audited / "distribution-audit.json").read_text())
        report["review_gaps"].append("new gap")
        (audited / "distribution-audit.json").write_text(json.dumps(report))
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        review.inspect(candidate, audited, output)


def test_rejected_decision_needs_no_approval_evidence_and_is_visible(setup):
    output, result = perform(setup, status="rejected")
    assert result["decisions"]["rejected"] == 1 and not result["recorded_reviews_complete"]


def test_all_recorded_approvals_still_do_not_authenticate_or_authorize_release(setup):
    candidate, audited, ledger, _ = setup
    for index, category in enumerate(review.REQUIRED):
        ledger, result = perform(setup, category, previous=ledger, name=f"revision-{index}")
    assert result["recorded_reviews_complete"]
    assert not result["release_ready"] and not result["redistribution_cleared"]
    assert not result["publisher_authenticated"]
    assert review.inspect(candidate, audited, ledger)[0]["head_sha256"] == result["head_sha256"]


@pytest.mark.parametrize("kind", ["reuse", "inside_candidate", "inside_audit", "inside_prior"])
def test_no_overwrite_or_writes_into_bound_inputs(setup, kind):
    candidate, audited, ledger, root = setup
    output = {
        "reuse": ledger,
        "inside_candidate": candidate / "new",
        "inside_audit": audited / "new",
        "inside_prior": ledger / "new",
    }[kind]
    request, _ = request_for(setup)
    before = (ledger / "ledger.json").read_bytes()
    with pytest.raises(ValueError):
        review.plan(candidate, audited, ledger, request, output)
    assert (ledger / "ledger.json").read_bytes() == before


def test_audit_validation_failure_never_writes_a_ledger(setup, monkeypatch):
    candidate, audited, _, root = setup

    def reject(*_):
        raise ValueError("Changed candidate")

    monkeypatch.setattr(review.audit, "verify", reject)
    with pytest.raises(ValueError):
        review.create(candidate, audited, root / "refused")
    assert not (root / "refused").exists()


def test_interrupted_revision_keeps_parent_usable_and_partial_revision_invalid(setup, monkeypatch):
    candidate, audited, ledger, root = setup
    original = Path.open

    def interrupted(self, *args, **kwargs):
        if self == root / "revision/ledger.json":
            raise OSError("Simulated interruption")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted)
    with pytest.raises(OSError):
        perform(setup)
    monkeypatch.setattr(Path, "open", original)
    assert review.inspect(candidate, audited, ledger)[1]
    with pytest.raises(ValueError):
        review.inspect(candidate, audited, root / "revision")


@pytest.mark.parametrize(
    "kind",
    [
        "private_key",
        "relative_file",
        "network_file",
        "network_request",
        "credential_url",
        "query_url",
        "binary",
        "empty",
        "reviewer",
        "date",
        "extra_field",
        "shared_file",
    ],
)
def test_invalid_or_sensitive_review_inputs_refuse_without_output(setup, kind):
    candidate, audited, ledger, root = setup
    request, body = request_for(setup)
    if kind == "private_key":
        body["evidence"][0]["file"] = str(root / "private.pfx")
    elif kind == "relative_file":
        body["evidence"][0]["file"] = "relative.txt"
    elif kind == "network_file":
        body["evidence"][0]["file"] = "\\\\invalid.example\\share\\evidence.txt"
    elif kind == "network_request":
        request = Path("\\\\invalid.example\\share\\request.json")
    elif kind == "credential_url":
        body["evidence"][0]["source"] = "https://user:password@example.com/license"
    elif kind == "query_url":
        body["evidence"][0]["source"] = "https://example.com/license?token=PRIVATE_FIXTURE"
    elif kind == "binary":
        (root / "fixture-evidence.txt").write_bytes(b"\x00binary")
    elif kind == "empty":
        (root / "fixture-evidence.txt").write_text("   ")
    elif kind == "reviewer":
        body["reviewer"] = ""
    elif kind == "date":
        body["reviewed_on"] = "2026-02-30"
    elif kind == "extra_field":
        body["release_ready"] = True
    else:
        (root / "alias.txt").hardlink_to(root / "fixture-evidence.txt")
    if kind != "network_request":
        request.write_text(json.dumps(body))
    with pytest.raises((ValueError, OSError)):
        review.plan(candidate, audited, ledger, request, root / "invalid")
    assert not (root / "invalid").exists()


def test_history_limit_refuses_before_creating_an_unverifiable_revision(setup, monkeypatch):
    candidate, audited, _, root = setup
    monkeypatch.setattr(review, "MAX_EVENTS", 1)
    ledger, _ = perform(setup)
    request, _ = request_for(setup, previous=ledger)
    before = (ledger / "ledger.json").read_bytes()
    with pytest.raises(ValueError, match="history limit"):
        review.plan(candidate, audited, ledger, request, root / "too-many-events")
    assert not (root / "too-many-events").exists()
    assert (ledger / "ledger.json").read_bytes() == before
