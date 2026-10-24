"""Authenticated admission with ephemeral identities and inert synthetic payloads."""

import base64
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

spec = importlib.util.spec_from_file_location(
    "signed", Path(__file__).resolve().parents[1] / "scripts/signed-package.py"
)
signed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signed)
NOW = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(signed.review.encoded(value))


def setup_package(tmp_path, monkeypatch, purpose="fixture", variant=""):
    candidate, audited, ledger = (tmp_path / name for name in ("candidate", "audit", "ledger"))
    candidate.mkdir()
    data = {
        "backend/resident_main.py": "raise RuntimeError('NEVER EXECUTE CANDIDATE')"
        + ("\n# " + variant if variant else ""),
        "runtime/python/python.exe": "INERT FIXTURE",
    }
    for name, text in data.items():
        path = candidate / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    save(candidate / "desktop-pilot.json", {"kind": "desktop-core-pilot", "files": data})

    def check_payload(root):
        value = json.loads((root / "desktop-pilot.json").read_text())
        if any((root / name).read_text() != text for name, text in value["files"].items()):
            raise ValueError("Synthetic pilot integrity changed")
        return {"kind": "desktop-core-pilot", "self_contained": True}

    monkeypatch.setattr(signed.audit.package, "verify", check_payload)
    monkeypatch.setattr(signed.manager.package, "verify", check_payload)
    report = {
        "candidate_manifest_sha256": signed.digest_file(candidate / "desktop-pilot.json"),
        "candidate_inventory_sha256": signed.trust.sha(signed.audit.canonical(data).encode()),
        "components": [
            {
                "ecosystem": "project",
                "name": "fixture",
                "version": "1",
                "scope": "fixture",
                "declared_license": "SYNTHETIC",
                "notices": [],
            }
        ],
        "license_evidence": [],
        "asset_reviews": [],
        "missing_notice_components": [],
        "review_gaps": ["Synthetic test only"],
    }
    audited.mkdir()
    for name, raw in signed.audit.artifacts(report, {}).items():
        (audited / name).write_bytes(raw)
    base = {
        "format": 1,
        "kind": "inara-distribution-review",
        "candidate_manifest_sha256": report["candidate_manifest_sha256"],
        "audit_report_sha256": signed.digest_file(audited / "distribution-audit.json"),
        "review_tool_sha256": "f" * 64,
        "subjects": signed.expected_subjects(report),
    }
    events, head = [], signed.review.hashed(base)
    ledger.mkdir()
    if purpose == "production":
        content = b"SYNTHETIC TEST EVIDENCE ONLY - no actual legal or ownership assertion"
        h = signed.trust.sha(content)
        (ledger / "evidence").mkdir()
        (ledger / "evidence" / (h + ".txt")).write_bytes(content)
        for subject in base["subjects"]:
            decision = {
                "subject_id": subject["id"],
                "subject_sha256": signed.review.hashed(subject),
                "status": "approved",
                "reviewer": "Synthetic test reviewer",
                "rationale": "Protocol fixture only",
                "reviewed_on": "2026-10-22",
                "evidence": [
                    {
                        "kind": k,
                        "sha256": h,
                        "bytes": len(content),
                        "source": "https://example.com/synthetic",
                    }
                    for k in subject["required_evidence"]
                ],
            }
            event = {"parent_sha256": head, "review_sha256": "a" * 64, "decision": decision}
            event["sha256"] = signed.review.hashed(event)
            head = event["sha256"]
            events.append(event)
    save(ledger / "ledger.json", {"base": base, "events": events, "head_sha256": head})
    bindings = {
        "candidate_manifest_sha256": report["candidate_manifest_sha256"],
        "audit_report_sha256": base["audit_report_sha256"],
        "ledger_sha256": signed.digest_file(ledger / "ledger.json"),
    }
    monkeypatch.setattr(signed.trust, "material", lambda *_: (bindings, purpose == "production"))
    private = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    keys = []
    for role, key in zip(("publisher", "reviewer"), private):
        public = key.public_key().public_bytes_raw()
        keys.append(
            {
                "key_id": signed.trust.sha(public),
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
        "mode": purpose,
        "publisher": "SYNTHETIC TEST ONLY",
        "policy_sequence": 1,
        "channel": "pilot",
        "minimum_sequence": 1,
        "thresholds": {"publisher": 1, "reviewer": 1},
        "keys": keys,
    }
    policy_path, package = tmp_path / "policy.json", tmp_path / "package"
    save(policy_path, policy)
    pin = signed.digest_file(policy_path)
    signed.prepare(
        candidate,
        audited,
        ledger,
        policy_path,
        pin,
        1,
        package,
        tmp_path / "request",
        fixture=purpose == "fixture",
        now=NOW,
    )

    def attest(manifest=None):
        if manifest is not None:
            save(package / signed.MANIFEST, manifest)
        m, raw = signed.read(package / signed.MANIFEST)
        statement = signed.statement_for(m, raw)
        envelope = {
            "format": 1,
            "kind": "inara-package-attestation",
            "statement": statement,
            "signatures": [
                {
                    "key_id": k["key_id"],
                    "signature": base64.b64encode(
                        p.sign(signed.signing_message(statement))
                    ).decode(),
                }
                for k, p in zip(keys, private)
            ],
        }
        save(package / signed.ENVELOPE, envelope)

    attest()
    return {
        "package": package,
        "policy_path": policy_path,
        "policy": policy,
        "pin": pin,
        "root": tmp_path / "installation",
        "attest": attest,
        "purpose": purpose,
        "private": private,
    }


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    return setup_package(tmp_path, monkeypatch)


def verified(s):
    return signed.verify(
        s["package"], s["policy_path"], s["pin"], 1, fixture=s["purpose"] == "fixture", now=NOW
    )


def test_fixture_is_self_contained_inert_and_cannot_authorize_install(fixture):
    result = verified(fixture)
    assert result["fixture_only"] and result["review_subjects"] == 2
    assert not result["candidate_code_executed"] and not result["release_authorized"]
    with pytest.raises(ValueError):
        signed.install_plan(
            fixture["package"], fixture["policy_path"], fixture["pin"], 1, fixture["root"], now=NOW
        )
    assert not fixture["root"].exists()


@pytest.mark.parametrize(
    "kind",
    [
        "missing_signature",
        "wrong_signature",
        "missing_reviewer",
        "extra_file",
        "missing_file",
        "payload_changed",
        "notice_changed",
        "ledger_changed",
        "manifest_changed",
        "traversal",
        "duplicate",
        "boolean_statement",
        "shared_file",
        "wrong_sequence",
        "wrong_policy_pin",
    ],
)
def test_untrusted_or_changed_packages_refuse_without_install_effects(fixture, kind):
    root = fixture["package"]
    envelope = root / signed.ENVELOPE
    if kind == "missing_signature":
        envelope.unlink()
    elif kind in {"wrong_signature", "missing_reviewer", "boolean_statement"}:
        value = json.loads(envelope.read_text())
        if kind == "wrong_signature":
            value["signatures"][0]["signature"] = base64.b64encode(b"x" * 64).decode()
        elif kind == "missing_reviewer":
            value["signatures"].pop()
        else:
            value["statement"]["format"] = True
        save(envelope, value)
    elif kind == "extra_file":
        (root / "payload/extra.txt").write_text("extra")
    elif kind == "missing_file":
        (root / "payload/runtime/python/python.exe").unlink()
    elif kind == "payload_changed":
        (root / "payload/backend/resident_main.py").write_text("changed")
    elif kind == "notice_changed":
        (root / "audit/THIRD_PARTY_NOTICES.txt").write_text("changed")
    elif kind == "ledger_changed":
        (root / "ledger/ledger.json").write_text("{}")
    elif kind in {"manifest_changed", "traversal", "duplicate"}:
        value = json.loads((root / signed.MANIFEST).read_text())
        if kind == "manifest_changed":
            value["publisher"] = "Other"
        elif kind == "traversal":
            value["files"][0]["path"] = "payload/../../outside"
        else:
            value["files"].append(value["files"][0])
        fixture["attest"](value)
    elif kind == "shared_file":
        (root.parent / "alias").hardlink_to(root / "payload/backend/resident_main.py")
    elif kind == "wrong_policy_pin":
        fixture["pin"] = "0" * 64
    elif kind == "wrong_sequence":
        with pytest.raises(ValueError):
            signed.verify(root, fixture["policy_path"], fixture["pin"], 2, fixture=True, now=NOW)
        return
    with pytest.raises((ValueError, OSError)):
        verified(fixture)
    assert not fixture["root"].exists()


def test_payload_validators_are_never_loaded_from_candidate(fixture, monkeypatch):
    called = []
    original = signed.audit.package.verify
    monkeypatch.setattr(
        signed.audit.package, "verify", lambda root: (called.append(root), original(root))[1]
    )
    verified(fixture)
    assert called == [fixture["package"] / "payload"]
    assert not (fixture["root"]).exists()


def plan(s, resume=False):
    return signed.install_plan(
        s["package"], s["policy_path"], s["pin"], 1, s["root"], now=NOW, resume=resume
    )


def apply(s, p, resume=False):
    return signed.install(
        s["package"],
        s["policy_path"],
        s["pin"],
        1,
        s["root"],
        p["review_sha256"],
        now=NOW,
        resume=resume,
    )


def test_synthetic_production_admission_installs_without_selecting_or_launching(
    tmp_path, monkeypatch
):
    s = setup_package(tmp_path, monkeypatch, "production")
    p = plan(s)
    assert not s["root"].exists()
    result = apply(s, p)
    state = signed.manager.Installation(s["root"]).load()
    assert result["installed"] and not result["selected"] and not result["launched"]
    assert state["current"] is None and len(state["slots"]) == 1
    before = (s["root"] / "installation.json").read_bytes()
    with pytest.raises(ValueError):
        apply(s, p)
    assert (s["root"] / "installation.json").read_bytes() == before


def test_wrong_review_refuses_before_root_creation(tmp_path, monkeypatch):
    s = setup_package(tmp_path, monkeypatch, "production")
    p = plan(s)
    p["review_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        apply(s, p)
    assert not s["root"].exists()


def test_rebuilt_unsigned_payload_after_verification_cannot_replace_signed_bytes(
    tmp_path, monkeypatch
):
    s = setup_package(tmp_path, monkeypatch, "production")
    p = plan(s)
    original = signed.manager.Installation.install

    def changed(self, source, **kwargs):
        value = json.loads((source / "desktop-pilot.json").read_text())
        value["files"]["backend/resident_main.py"] = "unsigned substitute"
        (source / "backend/resident_main.py").write_text("unsigned substitute")
        save(source / "desktop-pilot.json", value)
        return original(self, source, **kwargs)

    monkeypatch.setattr(signed.manager.Installation, "install", changed)
    with pytest.raises(ValueError):
        apply(s, p)
    assert not signed.manager.Installation(s["root"]).load()["slots"]
    assert not list((s["root"] / "transactions").iterdir())


def test_interrupted_copy_requires_fresh_signed_recovery_review(tmp_path, monkeypatch):
    s = setup_package(tmp_path, monkeypatch, "production")
    p = plan(s)
    original = signed.manager.shutil.copytree

    def crash(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(target).parent == s["root"] / "transactions":
            raise OSError("Synthetic interruption")
        return result

    monkeypatch.setattr(signed.manager.shutil, "copytree", crash)
    with pytest.raises(OSError):
        apply(s, p)
    assert not signed.manager.Installation(s["root"]).load()["slots"]
    monkeypatch.setattr(signed.manager.shutil, "copytree", original)
    recovered = apply(s, plan(s, resume=True), resume=True)
    assert recovered["installed"] and not recovered["selected"] and not recovered["launched"]


def test_correct_signatures_cannot_promote_pending_ledger_to_production(fixture):
    policy = fixture["policy"]
    policy["mode"] = "production"
    save(fixture["policy_path"], policy)
    fixture["pin"] = signed.digest_file(fixture["policy_path"])
    manifest = json.loads((fixture["package"] / signed.MANIFEST).read_text())
    manifest.update(purpose="production", policy_sha256=fixture["pin"])
    fixture["purpose"] = "production"
    fixture["attest"](manifest)
    with pytest.raises(ValueError, match="not approved"):
        verified(fixture)
    assert not fixture["root"].exists()


def test_installation_state_is_rechecked_inside_manager_lock(tmp_path, monkeypatch):
    s = setup_package(tmp_path, monkeypatch, "production")
    p = plan(s)
    original = signed.manager.Installation.install

    def changed(self, source, **kwargs):
        state = self.load()
        self.save(state)
        return original(self, source, **kwargs)

    monkeypatch.setattr(signed.manager.Installation, "install", changed)
    with pytest.raises(ValueError, match="state changed"):
        apply(s, p)
    assert not signed.manager.Installation(s["root"]).load()["slots"]
    assert not list((s["root"] / "transactions").iterdir())


@pytest.mark.parametrize("kind", ["expired", "future", "revoked", "fixture_without_option"])
def test_trust_time_and_fixture_boundaries(fixture, kind):
    if kind == "fixture_without_option":
        with pytest.raises(ValueError):
            signed.verify(fixture["package"], fixture["policy_path"], fixture["pin"], 1, now=NOW)
        return
    manifest = json.loads((fixture["package"] / signed.MANIFEST).read_text())
    if kind == "expired":
        manifest["expires_at"] = "2026-10-21T23:59:59Z"
    elif kind == "future":
        manifest["issued_at"] = "2026-10-22T12:00:00Z"
    else:
        fixture["policy"]["keys"][0]["state"] = "revoked"
        save(fixture["policy_path"], fixture["policy"])
        fixture["pin"] = signed.digest_file(fixture["policy_path"])
        manifest["policy_sha256"] = fixture["pin"]
    fixture["attest"](manifest)
    with pytest.raises(ValueError):
        verified(fixture)
