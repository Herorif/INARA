"""Inert receiving fixtures; signatures are ephemeral, native trust is injected."""

import base64
from datetime import timedelta
import json
import shutil

import pytest

from tests import test_signing_delivery as fixture_tools
from tests.test_controller_trust import load
from tests.test_signed_package import NOW

receiver = load("controller-receive")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    value = fixture_tools.fixture.__wrapped__(tmp_path, monkeypatch)
    delivery = fixture_tools.delivery
    for name, module in (("delivery", delivery), ("reviews", delivery.reviews), ("signed", delivery.signed), ("trust", delivery.trust), ("old", delivery.old)):
        monkeypatch.setattr(receiver, name, module)
    # The attested producer tool must be the one used to create this synthetic ledger.
    (value["source"] / "scripts/controller-review.py").write_bytes(delivery.reviews.provenance.controller.ROOT.joinpath("scripts/controller-review.py").read_bytes())
    value["evidence"] = tmp_path / "receiving-evidence"
    value["ledger"] = tmp_path / "receiving-ledger"
    delivery.reviews.provenance.run("collect", value["controller"], value["pin"], value["evidence"], value["source"])
    delivery.reviews.create(value["controller"], value["pin"], value["evidence"], value["ledger"], value["source"])
    return value


def options():
    return {"now": NOW, "_native_check": fixture_tools.native}


def common(value, envelope):
    return (*fixture_tools.args(value), 1, envelope)


def resign(value, envelope):
    body = json.loads(envelope.read_bytes())
    message = receiver.delivery.DOMAIN + receiver.old.encoded(body["statement"])
    body["signatures"] = [{"key_id": key["key_id"], "signature": base64.b64encode(secret.sign(message)).decode()} for key, secret in zip(value["policy"]["keys"], value["private"])]
    fixture_tools.save(envelope, body)


def bind_snapshot(value, envelope, key, directory):
    body = json.loads(envelope.read_bytes())
    body["statement"][key] = receiver.old.hashed(receiver.reviews.snapshot(directory))
    fixture_tools.save(envelope, body)
    resign(value, envelope)


def test_source_neutral_roundtrip_never_runs_producer_code(fixture, monkeypatch):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    shutil.rmtree(value["source"])  # Synthetic disposable source only.

    def forbidden(*_, **__):
        pytest.fail("Receiver attempted producer source regeneration")

    monkeypatch.setattr(receiver.reviews.provenance, "run", forbidden)
    result = receiver.verify(*common(value, envelope), **options())
    assert result["receiving_verified"] and not result["producer_source_rederived"]
    output = value["tmp"] / "received"
    planned = receiver.plan(*common(value, envelope), output, **options())
    assert not output.exists()
    assert receiver.assemble(*common(value, envelope), output, planned["plan_sha256"], **options())["copied"]
    args = fixture_tools.args(value)
    result = receiver.verify_package(output, args[1], *args[5:], 1, **options())
    assert result["package_complete"] and not result["clean_machine_accepted"] and not result["launched"]
    acceptance = json.loads((output / "acceptance.json").read_bytes())
    assert all(c["status"] == "pending" and not c["evidence"] for c in acceptance["checks"])
    assert not any(p.suffix in {".key", ".pem"} for p in output.rglob("*"))


@pytest.mark.parametrize("kind", ["signature", "expired", "sequence", "disabled", "pin"])
def test_authentication_precedes_payload_traversal(fixture, monkeypatch, kind):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    body = json.loads(envelope.read_bytes())
    kw = options()
    args = list(common(value, envelope))
    if kind == "signature":
        body["signatures"] = []
        fixture_tools.save(envelope, body)
    elif kind == "expired":
        kw["now"] = NOW + timedelta(hours=2)
    elif kind == "sequence":
        args[-2] = 2
    elif kind == "pin":
        args[1] = "f" * 64
    else:
        value["policy"]["mode"] = "disabled"
        fixture_tools.save(value["policy_path"], value["policy"])
        args[7] = receiver.signed.digest_file(value["policy_path"])

    def forbidden(*_):
        pytest.fail("Unauthenticated payload traversed")

    monkeypatch.setattr(receiver.reviews, "snapshot", forbidden)
    with pytest.raises(ValueError):
        receiver.verify(*args, **kw)


@pytest.mark.parametrize("target", ["evidence", "ledger", "enrollment", "bootstrap"])
def test_signed_bytes_drift_refuses(fixture, target):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    if target == "bootstrap":
        path = value["controller"] / "scripts/open-trusted-controller.ps1"
    else:
        path = next(p for p in value[target].rglob("*") if p.is_file())
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        receiver.verify(*common(value, envelope), **options())


@pytest.mark.parametrize("kind", ["queue", "ledger", "review-tool"])
def test_signed_but_inconsistent_evidence_refuses(fixture, kind):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    if kind == "queue":
        path = value["evidence"] / "controller-review-queue.json"
        body = json.loads(path.read_bytes())
        body["subjects"].pop()
        fixture_tools.save(path, body)
        bind_snapshot(value, envelope, "provenance_inventory_sha256", value["evidence"])
    else:
        path = value["ledger"] / "ledger.json"
        body = json.loads(path.read_bytes())
        if kind == "ledger":
            body["events"][0]["parent_sha256"] = "f" * 64
        else:
            body["base"]["review_tool_sha256"] = "f" * 64
        fixture_tools.save(path, body)
        bind_snapshot(value, envelope, "ledger_inventory_sha256", value["ledger"])
    with pytest.raises(ValueError):
        receiver.verify(*common(value, envelope), **options())


def test_native_drift_and_non_cache_acceptance_refuse(fixture):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)

    def native(*_):
        (value["evidence"] / "added.txt").write_text("unexpected")
        return fixture_tools.native()

    with pytest.raises(ValueError):
        receiver.verify(*common(value, envelope), now=NOW, _native_check=native)
    (value["evidence"] / "added.txt").unlink()
    with pytest.raises(ValueError):
        receiver.verify(*common(value, envelope), now=NOW, _native_check=lambda *_: {"authenticode_verified": True, "cache_only": False})


def test_interrupted_copy_preserves_partial_output_and_refuses_reuse(fixture, monkeypatch):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    output = value["tmp"] / "interrupted"
    planned = receiver.plan(*common(value, envelope), output, **options())
    original = receiver.signed.digest_file

    def interrupt(path):
        if str(path).startswith(str(output)):
            raise OSError("Synthetic copy interruption")
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(receiver.signed, "digest_file", interrupt)
        with pytest.raises(OSError):
            receiver.assemble(*common(value, envelope), output, planned["plan_sha256"], **options())
    assert output.exists() and any(p.is_file() for p in output.rglob("*"))
    assert not (output / "receipt.json").exists()
    with pytest.raises(ValueError):
        receiver.assemble(*common(value, envelope), output, planned["plan_sha256"], **options())


@pytest.mark.parametrize("producer", [False, True])
def test_envelope_bytes_changed_during_native_check_refuse(fixture, producer):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)

    def native(*_):
        # Whitespace preserves valid signatures but changes the delivered envelope bytes.
        envelope.write_bytes(envelope.read_bytes() + b"\n")
        return fixture_tools.native()

    with pytest.raises(ValueError, match="envelope|inputs"):
        if producer:
            receiver.delivery.verify(*common(value, envelope), source=value["source"], now=NOW, _native_check=native)
        else:
            receiver.verify(*common(value, envelope), now=NOW, _native_check=native)


@pytest.mark.parametrize("kind", ["stale-plan", "nested", "existing", "policy-contained"])
def test_copy_plan_destination_refusals(fixture, kind):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    output = value["tmp"] / "received"
    if kind == "nested":
        output = value["controller"] / "nested"
    elif kind == "existing":
        output.mkdir()
    elif kind == "policy-contained":
        output = value["policy_path"].parent
    with pytest.raises(ValueError):
        receiver.assemble(*common(value, envelope), output, "f" * 64, **options())
    if kind == "stale-plan":
        assert not output.exists()


@pytest.mark.parametrize("kind", ["extra", "missing-marker", "acceptance", "inventory", "moved"])
def test_package_exact_closure_and_relocation(fixture, kind):
    value = fixture
    envelope = fixture_tools.signed_delivery(value)
    output = value["tmp"] / "received"
    planned = receiver.plan(*common(value, envelope), output, **options())
    receiver.assemble(*common(value, envelope), output, planned["plan_sha256"], **options())
    if kind == "extra":
        (output / "extra.txt").write_text("unexpected")
    elif kind == "missing-marker":
        (output / "receipt.json").unlink()
    elif kind == "acceptance":
        (output / "acceptance.json").write_text('{"clean_machine_accepted":true}')
    elif kind == "inventory":
        path = output / "receipt.json"
        body = json.loads(path.read_bytes())
        body["plan"]["files"].pop()
        body["plan_sha256"] = receiver.old.hashed(body["plan"])
        fixture_tools.save(path, body)
    else:
        moved = value["tmp"] / "relocated"
        output.rename(moved)
        output = moved
    args = fixture_tools.args(value)
    if kind == "moved":
        assert receiver.verify_package(output, args[1], *args[5:], 1, **options())["package_complete"]
    else:
        with pytest.raises((ValueError, OSError)):
            receiver.verify_package(output, args[1], *args[5:], 1, **options())
