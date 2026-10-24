"""Immutable, offline, candidate-bound owner review records. Never authorizes release."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "review_audit", ROOT / "scripts/distribution-audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
KINDS = {"origin", "license", "obligations", "inventory", "security", "support", "notice"}
REQUIRED = {
    "component": {"origin", "license", "obligations"},
    "asset": {"origin", "license", "obligations"},
    "missing-notice": {"origin", "notice"},
    "runtime-baseline": {"origin", "security", "support"},
    "vendored-native": {"inventory", "origin", "license", "obligations"},
}
MAX_FILE = 2_097_152
MAX_TOTAL = 33_554_432
MAX_EVENTS = 4096


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def hashed(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Unexpected review fields")


def text(value, limit=4000):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Supply bounded, single-line review text")
    return value


def load(directory, name):
    return json.loads(audit.read(directory, name, 8_388_608))


def read_evidence(directory, name):
    raw = audit.read(directory, name, MAX_FILE)
    decoded = raw.decode("utf-8-sig")
    if not decoded.strip() or "\x00" in decoded:
        raise ValueError("Evidence must be nonempty UTF-8 text")
    return raw


def base_for(candidate, audited):
    candidate, audited = audit.local(candidate), audit.local(audited)
    audit.verify(candidate, audited)
    raw = audit.read(audited, "distribution-audit.json", 8_388_608)
    report = json.loads(raw)
    subjects = []

    def add(category, label, target):
        subject = {
            "category": category,
            "label": label,
            "target": target,
            "required_evidence": sorted(REQUIRED[category]),
        }
        subjects.append({"id": hashed(subject), **subject})

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
        raise ValueError("Duplicate or excessive review subjects")
    return {
        "format": 1,
        "kind": "inara-distribution-review",
        "candidate_manifest_sha256": report["candidate_manifest_sha256"],
        "audit_report_sha256": hashlib.sha256(raw).hexdigest(),
        "review_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "subjects": sorted(subjects, key=lambda s: (s["category"], s["label"], s["id"])),
    }


def evidence_descriptor(entry):
    exact(entry, {"kind", "sha256", "bytes", "source"})
    if (
        entry["kind"] not in KINDS
        or type(entry["bytes"]) is not int
        or not 0 < entry["bytes"] <= MAX_FILE
    ):
        raise ValueError("Invalid review evidence")
    if (
        not isinstance(entry["sha256"], str)
        or len(entry["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in entry["sha256"])
    ):
        raise ValueError("Invalid evidence digest")
    source = text(entry["source"], 1024)
    if source != "local-review":
        parsed = urlsplit(source)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Use a public HTTPS source reference without credentials or query data"
            )
    elif entry["kind"] in {"origin", "license", "notice", "support", "security"}:
        raise ValueError("This evidence kind requires a referenced source")
    return "evidence/" + entry["sha256"] + ".txt"


def validate_decision(decision, subjects):
    exact(
        decision,
        {
            "subject_id",
            "subject_sha256",
            "status",
            "reviewer",
            "rationale",
            "reviewed_on",
            "evidence",
        },
    )
    subject = subjects.get(decision["subject_id"])
    if subject is None or decision["subject_sha256"] != hashed(subject):
        raise ValueError("Review subject changed or is unknown")
    if decision["status"] not in {"pending", "approved", "rejected"}:
        raise ValueError("Invalid review decision")
    text(decision["reviewer"], 160)
    text(decision["rationale"])
    from datetime import date

    if date.fromisoformat(decision["reviewed_on"]).isoformat() != decision["reviewed_on"]:
        raise ValueError("Use an exact ISO review date")
    if not isinstance(decision["evidence"], list) or len(decision["evidence"]) > 32:
        raise ValueError("Excessive evidence attachments")
    seen = set()
    for entry in decision["evidence"]:
        evidence_descriptor(entry)
        key = (entry["kind"], entry["sha256"], entry["source"])
        if key in seen:
            raise ValueError("Duplicate evidence reference")
        seen.add(key)
    if decision["status"] == "approved" and not set(subject["required_evidence"]).issubset(
        {e["kind"] for e in decision["evidence"]}
    ):
        raise ValueError("Approval requires all subject-specific evidence kinds")


def inspect(candidate, audited, ledger):
    ledger = audit.local(ledger)
    value = load(ledger, "ledger.json")
    exact(value, {"base", "events", "head_sha256"})
    base = base_for(candidate, audited)
    if value["base"] != base:
        raise ValueError("Ledger is stale for this candidate/audit/tool")
    subjects = {s["id"]: s for s in base["subjects"]}
    statuses = {key: "pending" for key in subjects}
    if not isinstance(value["events"], list) or len(value["events"]) > MAX_EVENTS:
        raise ValueError("Excessive review history")
    expected, total = {"ledger.json"}, 0
    head = hashed(base)
    for event in value["events"]:
        exact(event, {"parent_sha256", "review_sha256", "decision", "sha256"})
        payload = {key: val for key, val in event.items() if key != "sha256"}
        if event["parent_sha256"] != head or event["sha256"] != hashed(payload):
            raise ValueError("Review history changed or was reordered")
        if (
            not isinstance(event["review_sha256"], str)
            or len(event["review_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in event["review_sha256"])
        ):
            raise ValueError("Invalid review binding")
        validate_decision(event["decision"], subjects)
        for entry in event["decision"]["evidence"]:
            name = evidence_descriptor(entry)
            raw = read_evidence(ledger, name)
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("Review evidence changed")
            if name not in expected:
                total += len(raw)
            expected.add(name)
        statuses[event["decision"]["subject_id"]] = event["decision"]["status"]
        head = event["sha256"]
    if total > MAX_TOTAL or value["head_sha256"] != head:
        raise ValueError("Excessive evidence or changed review head")
    actual = {p.relative_to(ledger).as_posix() for p in audit.package.files_in(ledger)}
    if actual != expected:
        raise ValueError("Missing or unregistered ledger files")
    return value, statuses


def destination(output, candidate, audited, ledger=None):
    output = Path(output).absolute()
    if output.drive.startswith("\\\\") or output.resolve() != output or output.exists():
        raise ValueError("Choose a NEW unlinked local review directory")
    for base in [
        audit.local(candidate),
        audit.local(audited),
        *([audit.local(ledger)] if ledger else []),
    ]:
        if output == base or output.is_relative_to(base) or base.is_relative_to(output):
            raise ValueError(
                "Keep review revisions separate from candidate, audit and prior ledger"
            )
    return output


def write_revision(output, value, blobs):
    raw = encoded(value)
    if len(raw) > 8_388_608 or sum(len(b) for b in blobs.values()) > MAX_TOTAL:
        raise ValueError("Review revision exceeded its bound")
    output.mkdir(parents=True)
    for name, content in blobs.items():
        path = output.joinpath(*audit.relative(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    # Commit marker written last. Interrupted revisions are never mistaken for complete ones.
    with (output / "ledger.json").open("xb") as stream:
        stream.write(raw)


def create(candidate, audited, output):
    output = destination(output, candidate, audited)
    base = base_for(candidate, audited)
    value = {"base": base, "events": [], "head_sha256": hashed(base)}
    write_revision(output, value, {})
    return summary(value, {s["id"]: "pending" for s in base["subjects"]})


def plan(candidate, audited, ledger, request, output):
    output = destination(output, candidate, audited, ledger)
    value, statuses = inspect(candidate, audited, ledger)
    if len(value["events"]) >= MAX_EVENTS:
        raise ValueError("Review history limit reached; preserve this revision")
    request = Path(request).absolute()
    if request.drive.startswith("\\\\"):
        raise ValueError("Choose a local review request")
    raw = audit.read(request.parent, request.name, MAX_FILE)
    body = json.loads(raw)
    exact(
        body,
        {
            "subject_id",
            "subject_sha256",
            "status",
            "reviewer",
            "rationale",
            "reviewed_on",
            "evidence",
        },
    )
    blobs, descriptors = {}, []
    if not isinstance(body["evidence"], list) or len(body["evidence"]) > 32:
        raise ValueError("Excessive review attachments")
    for item in body["evidence"]:
        exact(item, {"kind", "file", "source"})
        path = Path(item["file"])
        if (
            not path.is_absolute()
            or path.drive.startswith("\\\\")
            or path.suffix.lower()
            in {
                ".pem",
                ".key",
                ".pfx",
                ".p12",
                ".db",
                ".sqlite3",
                ".enc",
            }
        ):
            raise ValueError(
                "Select an explicit local text evidence file, never credentials or a profile"
            )
        content = read_evidence(path.parent, path.name)
        descriptor = {
            "kind": item["kind"],
            "source": item["source"],
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        name = evidence_descriptor(descriptor)
        blobs[name] = content
        descriptors.append(descriptor)
    if sum(map(len, blobs.values())) > MAX_TOTAL:
        raise ValueError("Review attachment budget exceeded")
    decision = {**body, "evidence": descriptors}
    subjects = {s["id"]: s for s in value["base"]["subjects"]}
    validate_decision(decision, subjects)
    review = {
        "parent_head_sha256": value["head_sha256"],
        "parent_ledger_sha256": hashlib.sha256(
            audit.read(audit.local(ledger), "ledger.json", 8_388_608)
        ).hexdigest(),
        "request_sha256": hashlib.sha256(raw).hexdigest(),
        "request_file": str(request),
        "output": str(output),
        "decision": decision,
    }
    return (
        {
            "review_sha256": hashed(review),
            "plan": review,
            "previous_status": statuses[decision["subject_id"]],
            "subject": subjects[decision["subject_id"]],
            "notice": "Records a reviewer assertion, not authenticated ownership, legal clearance or release authorization.",
        },
        value,
        blobs,
        output,
    )


def apply(candidate, audited, ledger, request, output, expected_review):
    reviewed, value, blobs, output = plan(candidate, audited, ledger, request, output)
    if reviewed["review_sha256"] != expected_review:
        raise ValueError("Review changed; inspect the exact decision/evidence/destination again")
    ledger = audit.local(ledger)
    for path in (ledger / "evidence").glob("*.txt"):
        name = path.relative_to(ledger).as_posix()
        content = audit.read(ledger, name, MAX_FILE)
        if hashlib.sha256(content).hexdigest() != path.stem:
            raise ValueError("Inherited review evidence changed")
        blobs[name] = content
    payload = {
        "parent_sha256": value["head_sha256"],
        "review_sha256": expected_review,
        "decision": reviewed["plan"]["decision"],
    }
    event = {**payload, "sha256": hashed(payload)}
    updated = {
        "base": value["base"],
        "events": [*value["events"], event],
        "head_sha256": event["sha256"],
    }
    write_revision(output, updated, blobs)
    statuses = {s["id"]: "pending" for s in value["base"]["subjects"]}
    for item in updated["events"]:
        statuses[item["decision"]["subject_id"]] = item["decision"]["status"]
    return summary(updated, statuses)


def summary(value, statuses):
    counts = {
        name: sum(status == name for status in statuses.values())
        for name in ("pending", "approved", "rejected")
    }
    return {
        "integrity": "passed",
        "subjects": len(statuses),
        "decisions": counts,
        "events": len(value["events"]),
        "head_sha256": value["head_sha256"],
        "recorded_reviews_complete": counts["approved"] == len(statuses),
        "reviewer_authenticated": False,
        "redistribution_cleared": False,
        "publisher_authenticated": False,
        "release_ready": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "status", "review", "apply"))
    for name in ("candidate", "audit", "ledger", "request", "output"):
        parser.add_argument("--" + name, type=Path, required=name in {"candidate", "audit"})
    parser.add_argument("--expected-review")
    args = parser.parse_args()
    if (
        (args.command != "create" and args.ledger is None)
        or (args.command in {"create", "review", "apply"} and args.output is None)
        or (args.command in {"review", "apply"} and args.request is None)
        or (args.command == "apply" and args.expected_review is None)
    ):
        parser.error(
            "Provide the ledger/request/new output and review digest required by this operation"
        )
    try:
        if args.command == "create":
            result = create(args.candidate, args.audit, args.output)
        elif args.command == "status":
            value, statuses = inspect(args.candidate, args.audit, args.ledger)
            result = {
                **summary(value, statuses),
                "subjects": [
                    {**s, "subject_sha256": hashed(s), "status": statuses[s["id"]]}
                    for s in value["base"]["subjects"]
                ],
            }
        elif args.command == "review":
            result = plan(args.candidate, args.audit, args.ledger, args.request, args.output)[0]
        else:
            result = apply(
                args.candidate,
                args.audit,
                args.ledger,
                args.request,
                args.output,
                args.expected_review,
            )
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(
            1,
            "Distribution review refused. Preserve prior revisions and review the exact candidate, evidence and request.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
