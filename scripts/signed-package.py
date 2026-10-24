"""Externally controlled authenticated-package admission. Never executes package code."""

import argparse
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import shutil

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


trust = module("signed_trust", "release-trust.py")
manager = module("signed_manager", "desktop-install.py")
review, audit = trust.review, trust.review.audit
DOMAIN = b"INARA:authenticated-package:v1\n"
MANIFEST = "package-manifest.json"
ENVELOPE = "attestation.json"
FIELDS = {
    "format",
    "kind",
    "purpose",
    "policy_sha256",
    "publisher",
    "channel",
    "sequence",
    "issued_at",
    "expires_at",
    "candidate_manifest_sha256",
    "audit_report_sha256",
    "ledger_sha256",
    "files",
}


def read(path, limit=8_388_608):
    return trust.read_json(path, limit)


def digest_file(path):
    # Read/hash using the trusted controller; never resolve an input's scripts/imports.
    plain(path)
    return audit.package.release.sha256(path)


def plain(path, directory=False):
    value = Path(path).absolute()
    if value.drive.startswith("\\\\") or value.resolve() != value:
        raise ValueError("Choose a canonical local package/install path")
    if directory and not value.is_dir():
        raise ValueError("Missing local package directory")
    if value.exists() and not value.is_dir() and value.stat().st_nlink != 1:
        raise ValueError("Shared package/install input")
    return value


def record(base, path):
    plain(path)
    return {
        "path": path.relative_to(base).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest_file(path),
    }


def inventory(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 19998:
        raise ValueError("Missing or excessive authenticated inventory")
    values, folded, total = {}, set(), 0
    for item in items:
        review.exact(item, {"path", "bytes", "sha256"})
        name = audit.relative(item["path"]).as_posix()
        if (
            name.split("/", 1)[0] not in {"payload", "audit", "ledger"}
            or "/" not in name
            or name.casefold() in folded
        ):
            raise ValueError("Unsafe or duplicate authenticated file")
        trust.integer(item["bytes"], 0, 536_870_912)
        trust.digest(item["sha256"])
        total += item["bytes"]
        if total > 2_147_483_648:
            raise ValueError("Authenticated payload exceeded its budget")
        values[name] = item
        folded.add(name.casefold())
    return values


def statement_for(manifest, raw):
    return {
        "format": 1,
        "kind": "inara-package-statement",
        "manifest_sha256": trust.sha(raw),
        **{
            key: manifest[key]
            for key in (
                "purpose",
                "policy_sha256",
                "publisher",
                "channel",
                "sequence",
                "issued_at",
                "expires_at",
            )
        },
    }


def signing_message(statement):
    return DOMAIN + review.encoded(statement)


def verify_signatures(manifest, raw, envelope, policy, pin, sequence, now=None):
    review.exact(envelope, {"format", "kind", "statement", "signatures"})
    if (
        type(envelope["format"]) is not int
        or envelope["format"] != 1
        or envelope["kind"] != "inara-package-attestation"
    ):
        raise ValueError("Unsupported package attestation")
    statement = statement_for(manifest, raw)
    if review.encoded(envelope["statement"]) != review.encoded(statement):
        raise ValueError("Attestation does not bind the exact package manifest")
    if (
        manifest["policy_sha256"] != pin
        or manifest["purpose"] != policy["mode"]
        or manifest["publisher"] != policy["publisher"]
        or manifest["channel"] != policy["channel"]
    ):
        raise ValueError("Wrong package trust context")
    trust.integer(sequence, policy["minimum_sequence"])
    trust.integer(manifest["sequence"], policy["minimum_sequence"])
    if sequence != manifest["sequence"]:
        raise ValueError("Unexpected package sequence")
    issued, expires, current = (
        trust.stamp(manifest["issued_at"]),
        trust.stamp(manifest["expires_at"]),
        trust.utc(now),
    )
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(days=1):
        raise ValueError("Package signing window is invalid")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 32:
        raise ValueError("Missing or excessive package signatures")
    keys = {key["key_id"]: key for key in policy["keys"]}
    seen, counts = set(), {"publisher": 0, "reviewer": 0}
    for signature in signatures:
        review.exact(signature, {"key_id", "signature"})
        key = keys.get(signature["key_id"])
        if key is None or key["state"] != "active" or key["key_id"] in seen:
            raise ValueError("Unknown, revoked or duplicate package signer")
        if not trust.stamp(key["not_before"]) <= issued <= current < trust.stamp(
            key["not_after"]
        ) or expires > trust.stamp(key["not_after"]):
            raise ValueError("Package signer is outside its enrolled window")
        try:
            Ed25519PublicKey.from_public_bytes(trust.b64(key["public_key"], 32)).verify(
                trust.b64(signature["signature"], 64), signing_message(statement)
            )
        except InvalidSignature as error:
            raise ValueError("Package signature mismatch") from error
        seen.add(key["key_id"])
        counts[key["role"]] += 1
    if any(counts[role] < policy["thresholds"][role] for role in counts):
        raise ValueError("Package role thresholds were not met")
    return counts


def expected_subjects(report):
    subjects = []

    def add(category, label, target):
        subject = {
            "category": category,
            "label": label,
            "target": target,
            "required_evidence": sorted(review.REQUIRED[category]),
        }
        subjects.append({"id": review.hashed(subject), **subject})

    for component in report["components"]:
        add(
            "component",
            f"{component['ecosystem']}:{component['name']}@{component['version']}",
            component,
        )
        if component["ecosystem"] == "runtime":
            add(
                "runtime-baseline",
                component["name"] + " support/security/source baseline",
                component,
            )
    for entry in report["asset_reviews"]:
        add("asset", entry["path"], entry)
    for entry in report["missing_notice_components"]:
        add("missing-notice", entry["name"] + "@" + entry["version"], entry)
    add(
        "vendored-native",
        "Bundled native/vendor subcomponent coverage",
        {
            "candidate_inventory_sha256": report["candidate_inventory_sha256"],
            "review_gaps": report["review_gaps"],
        },
    )
    if len(subjects) > 4096 or len({s["id"] for s in subjects}) != len(subjects):
        raise ValueError("Invalid authenticated review inventory")
    return sorted(subjects, key=lambda s: (s["category"], s["label"], s["id"]))


def verify_evidence(root, manifest, payload=None):
    # Replays only data schemas, never audit collection or code from the package.
    payload = root / "payload" if payload is None else payload
    candidate, candidate_raw = read(payload / "desktop-pilot.json")
    report, report_raw = read(root / "audit/distribution-audit.json")
    ledger, ledger_raw = read(root / "ledger/ledger.json")
    if any(
        manifest[key] != trust.sha(raw)
        for key, raw in (
            ("candidate_manifest_sha256", candidate_raw),
            ("audit_report_sha256", report_raw),
            ("ledger_sha256", ledger_raw),
        )
    ):
        raise ValueError("Signed evidence binding differs")
    if report["candidate_manifest_sha256"] != manifest["candidate_manifest_sha256"] or report[
        "candidate_inventory_sha256"
    ] != trust.sha(audit.canonical(candidate["files"]).encode()):
        raise ValueError("Audit belongs to another candidate")
    # Strict pilot/renderer/runtime inventory checks come from this trusted controller.
    audit.package.verify(payload)
    blobs = {}
    for entry in report["license_evidence"]:
        name = audit.relative(entry["copy"]).as_posix()
        if not name.startswith("notices/"):
            raise ValueError("Unsafe audit notice copy")
        raw = audit.read(root / "audit", name, audit.MAX_NOTICE)
        if len(raw) != entry["bytes"] or trust.sha(raw) != entry["sha256"]:
            raise ValueError("Authenticated notice evidence differs")
        blobs[name] = raw
    expected_audit = audit.artifacts(report, blobs)
    actual_audit = {
        p.relative_to(root / "audit").as_posix() for p in audit.package.files_in(root / "audit")
    }
    if actual_audit != set(expected_audit) or any(
        audit.read(root / "audit", name, 67_108_864) != raw for name, raw in expected_audit.items()
    ):
        raise ValueError("Authenticated audit file set/content differs")
    review.exact(ledger, {"base", "events", "head_sha256"})
    base = ledger["base"]
    review.exact(
        base,
        {
            "format",
            "kind",
            "candidate_manifest_sha256",
            "audit_report_sha256",
            "review_tool_sha256",
            "subjects",
        },
    )
    if (
        type(base["format"]) is not int
        or base["format"] != 1
        or base["kind"] != "inara-distribution-review"
        or base["candidate_manifest_sha256"] != manifest["candidate_manifest_sha256"]
        or base["audit_report_sha256"] != manifest["audit_report_sha256"]
        or base["subjects"] != expected_subjects(report)
    ):
        raise ValueError("Authenticated ledger subject inventory differs")
    trust.digest(base["review_tool_sha256"])
    subjects = {s["id"]: s for s in base["subjects"]}
    statuses, head, names = (
        {key: "pending" for key in subjects},
        review.hashed(base),
        {"ledger.json"},
    )
    if not isinstance(ledger["events"], list) or len(ledger["events"]) > review.MAX_EVENTS:
        raise ValueError("Excessive authenticated review history")
    for event in ledger["events"]:
        review.exact(event, {"parent_sha256", "review_sha256", "decision", "sha256"})
        trust.digest(event["review_sha256"])
        payload = {key: value for key, value in event.items() if key != "sha256"}
        if event["parent_sha256"] != head or event["sha256"] != review.hashed(payload):
            raise ValueError("Authenticated review chain differs")
        review.validate_decision(event["decision"], subjects)
        for entry in event["decision"]["evidence"]:
            name = review.evidence_descriptor(entry)
            raw = review.read_evidence(root / "ledger", name)
            if len(raw) != entry["bytes"] or trust.sha(raw) != entry["sha256"]:
                raise ValueError("Authenticated review attachment differs")
            names.add(name)
        statuses[event["decision"]["subject_id"]] = event["decision"]["status"]
        head = event["sha256"]
    actual_ledger = {
        p.relative_to(root / "ledger").as_posix() for p in audit.package.files_in(root / "ledger")
    }
    if head != ledger["head_sha256"] or actual_ledger != names:
        raise ValueError("Authenticated ledger head/file set differs")
    return all(status == "approved" for status in statuses.values()), len(subjects)


def prepare(
    candidate,
    audited,
    ledger,
    policy_path,
    pin,
    sequence,
    output,
    request_output,
    fixture=False,
    now=None,
):
    roots = [candidate, audited, ledger]
    policy_path = trust.outside(policy_path, roots)
    policy = trust.policy(policy_path, pin)
    if policy["mode"] == "disabled" or (policy["mode"] == "fixture" and not fixture):
        raise ValueError("Unconfigured identity or implicit fixture trust")
    trust.integer(sequence, policy["minimum_sequence"])
    output, request_output = trust.outside(output, roots), trust.outside(request_output, roots)
    if (
        output.exists()
        or request_output.exists()
        or output.is_relative_to(request_output)
        or request_output.is_relative_to(output)
    ):
        raise ValueError("Choose separate NEW package and request directories")
    bindings, complete = trust.material(candidate, audited, ledger)
    if policy["mode"] == "production" and not complete:
        raise ValueError("Production review decisions remain pending")
    issued = trust.utc(now)
    expires = issued + timedelta(hours=1)
    if any(
        sum(
            k["role"] == role
            and k["state"] == "active"
            and trust.stamp(k["not_before"]) <= issued
            and expires <= trust.stamp(k["not_after"])
            for k in policy["keys"]
        )
        < policy["thresholds"][role]
        for role in policy["thresholds"]
    ):
        raise ValueError("Insufficient keys cover the package signing window")
    mapping = []
    for prefix, source in (("payload", candidate), ("audit", audited), ("ledger", ledger)):
        source = plain(source, True)
        mapping.extend(
            (p, prefix + "/" + p.relative_to(source).as_posix())
            for p in audit.package.files_in(source)
        )
    records = [
        {"path": name, "bytes": plain(path).stat().st_size, "sha256": digest_file(path)}
        for path, name in mapping
    ]
    inventory(records)
    manifest = {
        "format": 1,
        "kind": "inara-authenticated-package",
        "purpose": policy["mode"],
        "policy_sha256": pin,
        "publisher": policy["publisher"],
        "channel": policy["channel"],
        "sequence": sequence,
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{
            k: bindings[k]
            for k in ("candidate_manifest_sha256", "audit_report_sha256", "ledger_sha256")
        },
        "files": sorted(records, key=lambda r: r["path"]),
    }
    raw = review.encoded(manifest)
    if len(raw) > 8_388_608:
        raise ValueError("Excessive package manifest")
    output.mkdir(parents=True)
    for (source, name), entry in zip(mapping, records):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        plain(source)
        with source.open("rb") as stream, target.open("xb") as destination:
            shutil.copyfileobj(stream, destination)
        if (
            target.stat().st_size != entry["bytes"]
            or digest_file(target) != entry["sha256"]
            or digest_file(source) != entry["sha256"]
        ):
            raise ValueError("Package input changed during assembly")
    copied_complete, _ = verify_evidence(output, manifest)
    if policy["mode"] == "production" and not copied_complete:
        raise ValueError("Copied production review evidence is incomplete")
    with (output / MANIFEST).open("xb") as stream:
        stream.write(raw)
    request_output.mkdir(parents=True)
    statement = statement_for(manifest, raw)
    (request_output / "statement.json").write_bytes(review.encoded(statement))
    (request_output / "signing-message.bin").write_bytes(signing_message(statement))
    return {
        "prepared": True,
        "purpose": policy["mode"],
        "files": len(records),
        "manifest_sha256": trust.sha(raw),
        "signed": False,
        "installable": False,
    }


def verify(package, policy_path, pin, sequence, fixture=False, now=None, *, _payload=None):
    package = plain(package, True)
    policy_path = trust.outside(policy_path, [package] + ([] if _payload is None else [_payload]))
    policy = trust.policy(policy_path, pin)
    if policy["mode"] == "disabled" or (policy["mode"] == "fixture" and not fixture):
        raise ValueError("Unconfigured identity or implicit fixture trust")
    manifest, raw = read(package / MANIFEST)
    review.exact(manifest, FIELDS)
    if (
        type(manifest["format"]) is not int
        or manifest["format"] != 1
        or manifest["kind"] != "inara-authenticated-package"
    ):
        raise ValueError("Unsupported authenticated package format")
    records = inventory(manifest["files"])
    envelope, _ = read(package / ENVELOPE, 262_144)
    counts = verify_signatures(manifest, raw, envelope, policy, pin, sequence, now)
    # Only after policy/role verification: inspect the untrusted payload as inert files.
    actual = {p.relative_to(package).as_posix() for p in audit.package.files_in(package)}
    if _payload is not None:
        if any(name.startswith("payload/") for name in actual):
            raise ValueError("Admission capsule must not contain a second payload")
        _payload = plain(_payload, True)
        actual |= {
            "payload/" + p.relative_to(_payload).as_posix()
            for p in audit.package.files_in(_payload)
        }
    if actual != set(records) | {MANIFEST, ENVELOPE}:
        raise ValueError("Missing or unregistered authenticated package file")
    for name, entry in records.items():
        path = (
            plain(_payload / name.removeprefix("payload/"))
            if (_payload is not None and name.startswith("payload/"))
            else plain(package / name)
        )
        if path.stat().st_size != entry["bytes"] or digest_file(path) != entry["sha256"]:
            raise ValueError("Authenticated payload/evidence changed")
    complete, subjects = verify_evidence(package, manifest, _payload)
    if policy["mode"] == "production" and not complete:
        raise ValueError("Production review ledger is not approved")
    return {
        "integrity": "passed",
        "purpose": policy["mode"],
        "manifest_sha256": trust.sha(raw),
        "attestation_sha256": digest_file(package / ENVELOPE),
        "files": len(records),
        "sequence": sequence,
        "signatures": counts,
        "review_subjects": subjects,
        "reviews_complete": complete,
        "fixture_only": policy["mode"] == "fixture",
        "candidate_code_executed": False,
        "authenticode_verified": False,
        "release_authorized": False,
    }


def install_plan(package, policy_path, pin, sequence, root, now=None, resume=False):
    verified = verify(package, policy_path, pin, sequence, fixture=False, now=now)
    if verified["purpose"] != "production" or not verified["reviews_complete"]:
        raise ValueError("Fixture/incomplete packages can never enter installation")
    root, package = plain(root), plain(package, True)
    if root.is_relative_to(package) or package.is_relative_to(root):
        raise ValueError("Keep installation separate from its signed package")
    if root.exists():
        service = manager.Installation(root)
        service.load()
        state = digest_file(root / "installation.json")
    else:
        state = "new"
    plan = {
        "manifest_sha256": verified["manifest_sha256"],
        "attestation_sha256": verified["attestation_sha256"],
        "policy_sha256": pin,
        "sequence": sequence,
        "root": str(root),
        "installation_state_sha256": state,
        "select": False,
        "launch": False,
        "resume": resume,
    }
    return {"review_sha256": review.hashed(plan), "plan": plan}


def install(package, policy_path, pin, sequence, root, expected_review, now=None, resume=False):
    planned = install_plan(package, policy_path, pin, sequence, root, now, resume)
    if expected_review != planned["review_sha256"]:
        raise ValueError("Installation review changed")
    package = plain(package, True)
    manifest, raw = read(package / MANIFEST)
    if trust.sha(raw) != planned["plan"]["manifest_sha256"]:
        raise ValueError("Authenticated package changed after review")
    records = {
        name.removeprefix("payload/"): entry
        for name, entry in inventory(manifest["files"]).items()
        if name.startswith("payload/")
    }

    def admission(directory):
        # Preserve the signed in-memory inventory across copy and recovery; a rebuilt
        # unsigned manifest cannot substitute different bytes after signature checking.
        trust.policy(trust.outside(policy_path, [package]), pin)
        if (
            not trust.stamp(manifest["issued_at"])
            <= trust.utc(now)
            < trust.stamp(manifest["expires_at"])
        ):
            raise ValueError("Package authorization expired during installation")
        actual = {p.relative_to(directory).as_posix() for p in audit.package.files_in(directory)}
        if actual != set(records):
            raise ValueError("Authenticated installation file set changed")
        for name, entry in records.items():
            path = plain(directory / name)
            if path.stat().st_size != entry["bytes"] or digest_file(path) != entry["sha256"]:
                raise ValueError("Installed copy differs from its signed inventory")

    root = plain(root)
    if resume and not root.exists():
        raise ValueError("Recovery requires an existing managed installation")
    service = manager.Installation(root) if root.exists() else manager.Installation.create(root)

    def receipt(state, slot, target):
        retain_admission(
            package, service, state, slot, target, policy_path, pin, sequence, now, planned["plan"]
        )

    state = planned["plan"]["installation_state_sha256"]
    if state == "new":
        state = digest_file(root / "installation.json")
    # The manager is loaded from the trusted control tree; the payload never supplies it.
    if resume:
        result = service.recover(
            manifest["candidate_manifest_sha256"],
            admission=admission,
            expected_state=state,
            before_register=receipt,
        )
    else:
        result = service.install(
            package / "payload", admission=admission, expected_state=state, before_register=receipt
        )
    return {
        "installed": True,
        "slot": result.get("slot") or result["recovered"],
        "selected": False,
        "launched": False,
        "admission_manifest_sha256": planned["plan"]["manifest_sha256"],
        "release_authorized": False,
    }


def retain_admission(
    package, service, state, slot, target, policy_path, pin, sequence, now, expected
):
    """Under the manager lease, preserve external signatures before slot registration.

    Root/installation binding is local metadata, not an independent owner signature.
    An interrupted, partial receipt is retained and refused; never repaired silently.
    """
    base = plain(service.root / "admissions")
    base.mkdir(exist_ok=True)
    capsule = plain(base / slot)
    binding_path = plain(base / (slot + ".json"))
    manifest, _ = read(package / MANIFEST)
    names = {MANIFEST, ENVELOPE} | {
        name for name in inventory(manifest["files"]) if not name.startswith("payload/")
    }
    binding = {
        "format": 1,
        "kind": "inara-admission-evidence",
        "root": str(service.root),
        "installation": state["id"],
        "slot": slot,
        "policy_sha256": pin,
        "sequence": sequence,
        "manifest_sha256": digest_file(package / MANIFEST),
        "attestation_sha256": digest_file(package / ENVELOPE),
    }
    if any(binding[key] != expected[key] for key in ("manifest_sha256", "attestation_sha256")):
        raise ValueError("Reviewed package authorization changed before receipt")
    if capsule.exists():
        # Recovery may reuse only a complete, byte-identical prior commit.
        existing, _ = read(binding_path)
        if review.encoded(existing) != review.encoded(binding):
            raise ValueError("Retained admission differs; preserve it")
    else:
        if binding_path.exists():
            raise ValueError("Admission is incomplete; preserve it")
        capsule.mkdir()
        for name in sorted(names):
            source, destination = plain(package / name), capsule / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output)
    checked = verify(capsule, policy_path, pin, sequence, now=now, _payload=target)
    if (
        checked["manifest_sha256"] != binding["manifest_sha256"]
        or checked["attestation_sha256"] != binding["attestation_sha256"]
    ):
        raise ValueError("Admission evidence changed during retention")
    if not binding_path.exists():
        with binding_path.open("xb") as output:
            output.write(review.encoded(binding))
    committed, _ = read(binding_path)
    if review.encoded(committed) != review.encoded(binding):
        raise ValueError("Admission binding changed during retention")


def launch_check(root, policy_path, pin, sequence, now=None, *, windows_check=None):
    """Read-only source authorization contract, NOT an execution permission."""
    service = manager.Installation(plain(root, True))
    policy_path = trust.outside(policy_path, [service.root])
    with service.locked() as state:
        slot = state["current"]
        if slot is None:
            raise ValueError("No selected version")
        target = plain(service.root / "versions" / slot, True)
        base = plain(service.root / "admissions", True)
        binding, _ = read(base / (slot + ".json"))
        review.exact(
            binding,
            {
                "format",
                "kind",
                "root",
                "installation",
                "slot",
                "policy_sha256",
                "sequence",
                "manifest_sha256",
                "attestation_sha256",
            },
        )
        if (
            type(binding["format"]) is not int
            or binding["format"] != 1
            or binding["kind"] != "inara-admission-evidence"
            or binding["root"] != str(service.root)
            or binding["installation"] != state["id"]
            or binding["slot"] != slot
            or binding["policy_sha256"] != pin
            or type(binding["sequence"]) is not int
            or binding["sequence"] != sequence
        ):
            raise ValueError("Admission belongs to another root, slot or policy")
        verified = verify(base / slot, policy_path, pin, sequence, now=now, _payload=target)
        service.check(slot)
        service.data(state, slot, create=False)
        manifest, _ = read(base / slot / MANIFEST)
        if manifest["candidate_manifest_sha256"] != slot or any(
            binding[key] != verified[key] for key in ("manifest_sha256", "attestation_sha256")
        ):
            raise ValueError("Admission signatures differ from the selected version")
        native = {} if windows_check is None else windows_check(target)
        return {
            **verified,
            **native,
            "source_authorization_checked": True,
            "slot": slot,
            "installation_metadata_signed": False,
            "launched": False,
            "launch_authorized": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "review-install", "install"))
    for name in (
        "package",
        "candidate",
        "audit",
        "ledger",
        "policy",
        "output",
        "request-output",
        "root",
    ):
        parser.add_argument("--" + name, type=Path, required=name == "policy")
    parser.add_argument("--expected-policy", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--expected-review")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    needed = (
        ("candidate", "audit", "ledger", "output", "request_output")
        if args.command == "prepare"
        else ("package",) + (("root",) if args.command in {"review-install", "install"} else ())
    )
    if (
        any(getattr(args, name) is None for name in needed)
        or (args.command == "install" and not args.expected_review)
        or (args.command in {"review-install", "install"} and args.fixture)
    ):
        parser.error("Supply exact operation inputs; fixture mode is verification/packaging only")
    try:
        if args.command == "prepare":
            result = prepare(
                args.candidate,
                args.audit,
                args.ledger,
                args.policy,
                args.expected_policy,
                args.sequence,
                args.output,
                args.request_output,
                args.fixture,
            )
        elif args.command == "verify":
            result = verify(
                args.package, args.policy, args.expected_policy, args.sequence, args.fixture
            )
        elif args.command == "review-install":
            result = install_plan(
                args.package,
                args.policy,
                args.expected_policy,
                args.sequence,
                args.root,
                resume=args.resume,
            )
        else:
            result = install(
                args.package,
                args.policy,
                args.expected_policy,
                args.sequence,
                args.root,
                args.expected_review,
                resume=args.resume,
            )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Authenticated package refused. Preserve source/package/profile data and inspect external trust, signatures, inventory and reviews.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
