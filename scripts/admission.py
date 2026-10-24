"""Externally signed, renewable installation grants and process-lifetime launch admission."""

from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        "admission_" + name, ROOT / "scripts" / (name + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


signed, windows, launcher = (
    module("signed-package"),
    module("windows-signature"),
    module("windows-launch"),
)
trust, review = signed.trust, signed.review
DOMAIN = b"INARA:installation-launch-grant:v1\n"
FIELDS = {
    "format",
    "kind",
    "root",
    "installation",
    "slot",
    "manifest_sha256",
    "attestation_sha256",
    "policy_sha256",
    "windows_policy_sha256",
    "sequence",
    "number",
    "previous",
    "issued_at",
    "expires_at",
}


def message(statement):
    return DOMAIN + review.encoded(statement)


def verify_grant(envelope, policy, pin, windows_pin, now=None):
    review.exact(envelope, {"statement", "signatures"})
    value = envelope["statement"]
    review.exact(value, FIELDS)
    if (
        type(value["format"]) is not int
        or value["format"] != 1
        or value["kind"] != "inara-installation-launch-grant"
        or policy["mode"] != "production"
        or value["policy_sha256"] != pin
        or value["windows_policy_sha256"] != windows_pin
    ):
        raise ValueError("Wrong launch grant trust context")
    signed.manager.identifier(value["slot"])
    for key in ("manifest_sha256", "attestation_sha256", "policy_sha256", "windows_policy_sha256"):
        trust.digest(value[key])
    trust.integer(value["sequence"], policy["minimum_sequence"])
    trust.integer(value["number"])
    if value["previous"] != "new":
        trust.digest(value["previous"])
    if (
        not isinstance(value["installation"], str)
        or len(value["installation"]) != 32
        or any(char not in "0123456789abcdef" for char in value["installation"])
    ):
        raise ValueError("Invalid grant installation identity")
    if not isinstance(value["root"], str) or str(signed.plain(value["root"])) != value["root"]:
        raise ValueError("Noncanonical grant root")
    issued, expires, current = (
        trust.stamp(value["issued_at"]),
        trust.stamp(value["expires_at"]),
        trust.utc(now),
    )
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(days=30):
        raise ValueError("Launch grant window invalid or expired")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 32:
        raise ValueError("Missing or excessive launch signatures")
    keys = {key["key_id"]: key for key in policy["keys"]}
    seen, counts = set(), {"publisher": 0, "reviewer": 0}
    for signature in signatures:
        review.exact(signature, {"key_id", "signature"})
        key = keys.get(signature["key_id"])
        if key is None or key["key_id"] in seen or key["state"] != "active":
            raise ValueError("Unknown, revoked or duplicate launch signer")
        if (
            not trust.stamp(key["not_before"])
            <= issued
            <= current
            < expires
            <= trust.stamp(key["not_after"])
        ):
            raise ValueError("Signer enrollment does not cover the complete launch window")
        try:
            Ed25519PublicKey.from_public_bytes(trust.b64(key["public_key"], 32)).verify(
                trust.b64(signature["signature"], 64), message(value)
            )
        except InvalidSignature as error:
            raise ValueError("Launch grant signature mismatch") from error
        seen.add(key["key_id"])
        counts[key["role"]] += 1
    if any(counts[role] < policy["thresholds"][role] for role in counts):
        raise ValueError("Launch grant role thresholds not met")
    return value


def policies(root, policy_path, pin, windows_path, windows_pin):
    policy_path = trust.outside(policy_path, [root])
    windows_path = trust.outside(windows_path, [root])
    policy = trust.policy(policy_path, pin)
    native = windows.policy(windows_path, windows_pin)
    if policy["mode"] != "production" or native["mode"] != "production":
        raise ValueError("Production release and Windows identities are required")
    return policy


def head(service, state, expected):
    path = signed.plain(service.root / "authorizations/state.json")
    if not path.exists():
        if expected != "new":
            raise ValueError("Expected authorization head is missing")
        return None
    trust.digest(expected)
    value, _ = signed.read(path, 16384)
    review.exact(value, {"format", "kind", "installation", "grant_sha256", "number", "sequence"})
    if (
        type(value["format"]) is not int
        or value["format"] != 1
        or value["kind"] != "inara-authorization-head"
        or value["installation"] != state["id"]
        or value["grant_sha256"] != expected
    ):
        raise ValueError("Authorization head changed or belongs to another installation")
    trust.integer(value["number"])
    trust.integer(value["sequence"])
    envelope, raw = signed.read(service.root / "authorizations" / (expected + ".json"), 262144)
    if trust.sha(raw) != expected:
        raise ValueError("Retained grant differs from the external head pin")
    statement = envelope["statement"]
    if (
        statement["number"] != value["number"]
        or statement["sequence"] != value["sequence"]
        or statement["root"] != str(service.root)
        or statement["installation"] != state["id"]
    ):
        raise ValueError("Retained grant/head binding differs")
    return envelope


def source(service, state, policy_path, pin, sequence, statement=None):
    slot = state["current"]
    if slot is None:
        raise ValueError("Select an installed version before requesting launch authorization")
    capsule = signed.plain(service.root / "admissions" / slot, True)
    target = signed.plain(service.root / "versions" / slot, True)
    binding, _ = signed.read(service.root / "admissions" / (slot + ".json"))
    manifest, _ = signed.read(capsule / signed.MANIFEST)
    # The new, independently signed grant explicitly reauthorizes these exact bytes.
    # Original package signatures are still checked at their signed issuance time;
    # this path is never an implicit ignore-expiry switch on the old verifier.
    verified = signed.verify(
        capsule, policy_path, pin, sequence, now=trust.stamp(manifest["issued_at"]), _payload=target
    )
    expected = {
        "format": 1,
        "kind": "inara-admission-evidence",
        "root": str(service.root),
        "installation": state["id"],
        "slot": slot,
        "policy_sha256": pin,
        "sequence": sequence,
        "manifest_sha256": verified["manifest_sha256"],
        "attestation_sha256": verified["attestation_sha256"],
    }
    if (
        review.encoded(binding) != review.encoded(expected)
        or manifest["candidate_manifest_sha256"] != slot
    ):
        raise ValueError("Installed evidence no longer matches its admitted source")
    if statement is not None and any(
        statement[key] != expected[key]
        for key in (
            "root",
            "installation",
            "slot",
            "sequence",
            "manifest_sha256",
            "attestation_sha256",
            "policy_sha256",
        )
    ):
        raise ValueError("Launch grant belongs to different installation bytes")
    service.check(slot)
    data = service.data(state, slot, create=False)
    return verified, target, data


def prepare(
    root,
    policy_path,
    pin,
    windows_path,
    windows_pin,
    sequence,
    expected_head,
    output,
    hours=24,
    now=None,
):
    root = signed.plain(root, True)
    policy = policies(root, policy_path, pin, windows_path, windows_pin)
    trust.integer(hours, 1, 720)
    trust.integer(sequence, policy["minimum_sequence"])
    output = trust.outside(output, [root])
    if output.exists():
        raise ValueError("Choose a NEW external signing-request directory")
    service = signed.manager.Installation(root)
    with service.locked() as state:
        previous = head(service, state, expected_head)
        verified, _, _ = source(service, state, policy_path, pin, sequence)
        issued = trust.utc(now)
        value = {
            "format": 1,
            "kind": "inara-installation-launch-grant",
            "root": str(root),
            "installation": state["id"],
            "slot": state["current"],
            "manifest_sha256": verified["manifest_sha256"],
            "attestation_sha256": verified["attestation_sha256"],
            "policy_sha256": pin,
            "windows_policy_sha256": windows_pin,
            "sequence": sequence,
            "number": 1 if previous is None else previous["statement"]["number"] + 1,
            "previous": expected_head,
            "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (issued + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        transition(previous, value, policy, pin, windows_pin)
        if any(
            sum(
                key["state"] == "active"
                and key["role"] == role
                and trust.stamp(key["not_before"]) <= issued
                and trust.stamp(value["expires_at"]) <= trust.stamp(key["not_after"])
                for key in policy["keys"]
            )
            < policy["thresholds"][role]
            for role in policy["thresholds"]
        ):
            raise ValueError("Enrolled keys do not cover requested authorization window")
        output.mkdir(parents=True)
        (output / "statement.json").write_bytes(review.encoded(value))
        (output / "signing-message.bin").write_bytes(message(value))
    return {"prepared": True, "signed": False, "number": value["number"], "launched": False}


def transition(previous, value, policy, pin, windows_pin):
    if previous is None:
        if value["number"] != 1 or value["previous"] != "new":
            raise ValueError("First authorization must start a new chain")
        return
    old = previous["statement"]
    verify_grant(previous, policy, pin, windows_pin, trust.stamp(old["issued_at"]))
    if (
        value["number"] != old["number"] + 1
        or value["sequence"] < old["sequence"]
        or trust.stamp(value["issued_at"]) < trust.stamp(old["issued_at"])
    ):
        raise ValueError("Authorization number, package sequence or issuance moved backwards")


def inspect(
    service,
    state,
    grant_path,
    policy_path,
    pin,
    windows_path,
    windows_pin,
    sequence,
    expected_head,
    now,
    native_check,
):
    policy = policies(service.root, policy_path, pin, windows_path, windows_pin)
    trust.integer(sequence, policy["minimum_sequence"])
    grant_path = trust.outside(grant_path, [service.root])
    envelope, raw = signed.read(grant_path, 262144)
    value = verify_grant(envelope, policy, pin, windows_pin, now)
    if value["sequence"] != sequence or value["previous"] != expected_head:
        raise ValueError("Unexpected grant sequence or previous authorization")
    previous = head(service, state, expected_head)
    transition(previous, value, policy, pin, windows_pin)
    _, target, data = source(service, state, policy_path, pin, sequence, value)
    native_check(target, windows_path, windows_pin)
    plan = {
        "root": str(service.root),
        "grant_sha256": trust.sha(raw),
        "previous": expected_head,
        "installation_state_sha256": signed.digest_file(service.root / "installation.json"),
        "profile": str(data),
        "number": value["number"],
        "sequence": sequence,
        "select": False,
        "launch": False,
    }
    return {"review_sha256": review.hashed(plan), "plan": plan}, raw


def admit(
    root,
    grant_path,
    policy_path,
    pin,
    windows_path,
    windows_pin,
    sequence,
    expected_head,
    expected_review=None,
    now=None,
    *,
    _native_check=None,
):
    service = signed.manager.Installation(signed.plain(root, True))
    with service.locked() as state:
        planned, raw = inspect(
            service,
            state,
            grant_path,
            policy_path,
            pin,
            windows_path,
            windows_pin,
            sequence,
            expected_head,
            now,
            windows.check if _native_check is None else _native_check,
        )
        if expected_review is None:
            return planned
        if expected_review != planned["review_sha256"]:
            raise ValueError("Authorization review changed")
        policy = policies(service.root, policy_path, pin, windows_path, windows_pin)
        verify_grant(json.loads(raw), policy, pin, windows_pin, now)
        base = signed.plain(service.root / "authorizations")
        base.mkdir(exist_ok=True)
        digest = planned["plan"]["grant_sha256"]
        path = signed.plain(base / (digest + ".json"))
        if path.exists():
            if signed.read(path, 262144)[1] != raw:
                raise ValueError("Retained authorization differs")
        else:
            with path.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        # An exact orphan grant can be reused after interrupted pointer commit.
        signed.manager.write(
            base / "state.json",
            {
                "format": 1,
                "kind": "inara-authorization-head",
                "installation": state["id"],
                "grant_sha256": digest,
                "number": planned["plan"]["number"],
                "sequence": sequence,
            },
        )
        return {
            "admitted": True,
            "expected_head": digest,
            "number": planned["plan"]["number"],
            "selected": False,
            "launched": False,
            "release_authorized": False,
        }


def launch(
    root,
    policy_path,
    pin,
    windows_path,
    windows_pin,
    sequence,
    expected_head,
    resident_only=False,
    now=None,
    *,
    _native_check=None,
    _run=None,
):
    service = signed.manager.Installation(signed.plain(root, True))
    with service.locked() as state:
        policy = policies(service.root, policy_path, pin, windows_path, windows_pin)
        trust.integer(sequence, policy["minimum_sequence"])
        envelope = head(service, state, expected_head)
        if envelope is None:
            raise ValueError("A retained signed launch grant is required")
        value = verify_grant(envelope, policy, pin, windows_pin, now)
        if value["sequence"] != sequence:
            raise ValueError("Unexpected launch package sequence")
        slot = state["current"]
        if slot != value["slot"]:
            raise ValueError("Selected version differs from the signed launch grant")
        # Grant signatures BEFORE payload traversal; leases BEFORE byte verification.
        target = signed.plain(service.root / "versions" / slot, True)
        capsule = signed.plain(service.root / "admissions" / slot, True)
        profile = service.data(state, slot, create=False)
        paths = list(signed.audit.package.files_in(target)) + list(
            signed.audit.package.files_in(capsule)
        )
        paths += [
            signed.plain(policy_path),
            signed.plain(windows_path),
            service.root / "installation.json",
            service.root / "authorizations/state.json",
            service.root / "authorizations" / (expected_head + ".json"),
            service.root / "admissions" / (slot + ".json"),
            profile / ".inara-data.json",
        ]
        if (profile / ".inara-recovery.json").exists():
            paths += [
                profile / ".inara-recovery.json",
                profile / "desktop-profile/resident-identity.json",
            ]
        with launcher.file_leases(paths):
            # Re-read all authorization/state inputs after taking their file leases.
            if review.encoded(service.load()) != review.encoded(state):
                raise ValueError("Installation selection changed before launch leases")
            policy = policies(service.root, policy_path, pin, windows_path, windows_pin)
            value = verify_grant(head(service, state, expected_head), policy, pin, windows_pin, now)
            _, target, data = source(service, state, policy_path, pin, sequence, value)
            (windows.check if _native_check is None else _native_check)(
                target, windows_path, windows_pin
            )
            arguments = ["-I", "-B", str(target / "backend/resident_main.py")]
            if resident_only:
                arguments.append("--resident-only")
            result = (launcher.run if _run is None else _run)(
                target / "runtime/python/python.exe",
                arguments,
                target,
                launcher.environment(data),
                trust.stamp(value["expires_at"]),
            )
        return {
            **result,
            "launched": True,
            "slot": slot,
            "authorization_number": value["number"],
            "expected_head": expected_head,
            "release_authorized": False,
        }
