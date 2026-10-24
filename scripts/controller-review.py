"""Separate immutable controller review revisions. Assertions never authorize release."""

import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controller_review_provenance", ROOT / "scripts/controller-provenance.py")
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)
signed = provenance.controller.signed
old, audit, trust = signed.review, signed.audit, signed.trust


def snapshot(directory):
    directory = audit.local(directory)
    files, total = [], 0
    for path in audit.package.files_in(directory):
        size = path.stat().st_size
        total += size
        if size > 67_108_864 or total > 268_435_456 or len(files) >= 20000:
            raise ValueError("Excessive evidence inventory")
        files.append({"path": path.relative_to(directory).as_posix(), "bytes": size, "sha256": signed.digest_file(path)})
    return sorted(files, key=lambda x: x["path"])


def base_for(controller, pin, evidence, source=ROOT):
    provenance.run("verify", controller, pin, evidence, source)
    queue, _ = signed.read(Path(evidence) / "controller-review-queue.json")
    subjects = [{key: value for key, value in s.items() if key != "status"} for s in queue["subjects"]]
    if not subjects or len(subjects) > 4096 or len({s["id"] for s in subjects}) != len(subjects):
        raise ValueError("Missing or duplicate controller subjects")
    return {"format": 1, "kind": "inara-controller-review", "controller_manifest_sha256": pin,
            "provenance_inventory_sha256": old.hashed(snapshot(evidence)),
            "review_tool_sha256": signed.digest_file(Path(__file__)), "subjects": subjects}


def descriptor(entry):
    # Keep desktop evidence semantics unchanged; only this controller ledger adds delivery.
    return old.evidence_descriptor({**entry, "kind": "inventory"} if entry.get("kind") == "delivery" else entry)


def validate(decision, subjects):
    old.exact(decision, {"subject_id", "subject_sha256", "status", "reviewer", "rationale", "reviewed_on", "evidence"})
    subject = subjects.get(decision["subject_id"])
    if subject is None or decision["subject_sha256"] != old.hashed(subject) or decision["status"] not in {"pending", "approved", "rejected"}:
        raise ValueError("Unknown/stale controller subject or decision")
    old.text(decision["reviewer"], 160)
    old.text(decision["rationale"])
    if date.fromisoformat(decision["reviewed_on"]).isoformat() != decision["reviewed_on"]:
        raise ValueError("Use an exact review date")
    if not isinstance(decision["evidence"], list) or len(decision["evidence"]) > 32:
        raise ValueError("Excessive attachments")
    seen = set()
    for entry in decision["evidence"]:
        descriptor(entry)
        key = (entry["kind"], entry["sha256"], entry["source"])
        if key in seen:
            raise ValueError("Duplicate evidence")
        seen.add(key)
    if decision["status"] == "approved" and not set(subject["required_evidence"]) <= {e["kind"] for e in decision["evidence"]}:
        raise ValueError("Approval requires every controller-specific evidence kind")


def inspect(controller, pin, evidence, ledger, source=ROOT):
    return inspect_history(ledger, base_for(controller, pin, evidence, source))


def inspect_history(ledger, expected_base):
    """Validate inert history against a caller-authenticated base; never load ledger code."""
    ledger = audit.local(ledger)
    value, _ = signed.read(ledger / "ledger.json")
    old.exact(value, {"base", "events", "head_sha256"})
    if value["base"] != expected_base:
        raise ValueError("Stale controller/provenance/review-tool ledger")
    subjects = {s["id"]: s for s in value["base"]["subjects"]}
    statuses = {key: "pending" for key in subjects}
    if not isinstance(value["events"], list) or len(value["events"]) > old.MAX_EVENTS:
        raise ValueError("Excessive controller review history")
    head, files, total = old.hashed(value["base"]), {"ledger.json"}, 0
    for event in value["events"]:
        old.exact(event, {"parent_sha256", "review_sha256", "decision", "sha256"})
        payload = {k: v for k, v in event.items() if k != "sha256"}
        trust.digest(event["review_sha256"])
        if event["parent_sha256"] != head or event["sha256"] != old.hashed(payload):
            raise ValueError("Controller review history changed")
        validate(event["decision"], subjects)
        for entry in event["decision"]["evidence"]:
            name = descriptor(entry)
            raw = old.read_evidence(ledger, name)
            if len(raw) != entry["bytes"] or trust.sha(raw) != entry["sha256"]:
                raise ValueError("Controller review attachment changed")
            if name not in files:
                total += len(raw)
            files.add(name)
        statuses[event["decision"]["subject_id"]] = event["decision"]["status"]
        head = event["sha256"]
    if total > old.MAX_TOTAL or value["head_sha256"] != head or {p.relative_to(ledger).as_posix() for p in audit.package.files_in(ledger)} != files:
        raise ValueError("Changed controller ledger head/closure or excessive evidence")
    return value, statuses


def summary(value, statuses):
    return {**old.summary(value, statuses), "release_authorized": False, "artifact": "controller"}


def create(controller, pin, evidence, output, source=ROOT):
    output = old.destination(output, controller, evidence)
    base = base_for(controller, pin, evidence, source)
    value = {"base": base, "events": [], "head_sha256": old.hashed(base)}
    old.write_revision(output, value, {})
    return summary(value, {s["id"]: "pending" for s in base["subjects"]})


def plan(controller, pin, evidence, ledger, request, output, source=ROOT):
    output = old.destination(output, controller, evidence, ledger)
    value, statuses = inspect(controller, pin, evidence, ledger, source)
    if len(value["events"]) >= old.MAX_EVENTS:
        raise ValueError("Controller review history full")
    body, raw = signed.read(request, old.MAX_FILE)
    old.exact(body, {"subject_id", "subject_sha256", "status", "reviewer", "rationale", "reviewed_on", "evidence"})
    if not isinstance(body["evidence"], list) or len(body["evidence"]) > 32:
        raise ValueError("Excessive attachments")
    blobs, descriptors = {}, []
    for item in body["evidence"]:
        old.exact(item, {"kind", "file", "source"})
        path = Path(item["file"])
        if not path.is_absolute() or path.suffix.lower() not in {".txt", ".md", ".json", ".html"}:
            raise ValueError("Use explicit local public text evidence, never private keys/profiles")
        content = old.read_evidence(path.parent, path.name)
        if b"-----BEGIN" in content:
            raise ValueError("Key/certificate envelopes do not belong in review text")
        entry = {"kind": item["kind"], "source": item["source"], "bytes": len(content), "sha256": trust.sha(content)}
        blobs[descriptor(entry)] = content
        descriptors.append(entry)
    decision = {**body, "evidence": descriptors}
    validate(decision, {s["id"]: s for s in value["base"]["subjects"]})
    if sum(map(len, blobs.values())) > old.MAX_TOTAL:
        raise ValueError("Excessive controller evidence")
    planned = {"controller_manifest_sha256": pin, "ledger_sha256": signed.digest_file(Path(ledger) / "ledger.json"),
               "head_sha256": value["head_sha256"], "request_sha256": trust.sha(raw), "output": str(output), "decision": decision}
    return {"review_sha256": old.hashed(planned), "plan": planned}, value, blobs, output


def apply(controller, pin, evidence, ledger, request, output, expected_review, source=ROOT):
    ledger = audit.local(ledger)
    reviewed, value, blobs, output = plan(controller, pin, evidence, ledger, request, output, source)
    if reviewed["review_sha256"] != expected_review:
        raise ValueError("Controller review changed; review again")
    for file in audit.package.files_in(Path(ledger)):
        name = file.relative_to(ledger).as_posix()
        if name != "ledger.json":
            blobs[name] = old.read_evidence(Path(ledger), name)
    payload = {"parent_sha256": value["head_sha256"], "review_sha256": expected_review, "decision": reviewed["plan"]["decision"]}
    event = {**payload, "sha256": old.hashed(payload)}
    value = {"base": value["base"], "events": [*value["events"], event], "head_sha256": event["sha256"]}
    old.write_revision(output, value, blobs)
    statuses = {s["id"]: "pending" for s in value["base"]["subjects"]}
    for event in value["events"]:
        statuses[event["decision"]["subject_id"]] = event["decision"]["status"]
    return summary(value, statuses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "status", "review", "apply"))
    for name in ("controller", "evidence", "ledger", "request", "output"):
        parser.add_argument("--" + name, type=Path, required=name in {"controller", "evidence"})
    parser.add_argument("--expected-manifest", required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--expected-review")
    args = parser.parse_args()
    if (args.command != "create" and args.ledger is None) or (args.command != "status" and args.output is None) or (args.command in {"review", "apply"} and args.request is None) or (args.command == "apply" and args.expected_review is None):
        parser.error("Supply the ledger, request, new output and exact review required by the operation")
    try:
        common = (args.controller, args.expected_manifest, args.evidence)
        if args.command == "create":
            result = create(*common, args.output, args.source)
        elif args.command == "status":
            value, statuses = inspect(*common, args.ledger, args.source)
            result = {**summary(value, statuses), "subjects": [{**s, "subject_sha256": old.hashed(s), "status": statuses[s["id"]]} for s in value["base"]["subjects"]]}
        elif args.command == "review":
            result = plan(*common, args.ledger, args.request, args.output, args.source)[0]
        else:
            result = apply(*common, args.ledger, args.request, args.output, args.expected_review, args.source)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(1, "Controller review refused. Preserve evidence and earlier revisions.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
