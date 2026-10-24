"""Offline, externally pinned controller provenance and pending owner-review evidence."""

import argparse
from email.parser import Parser
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provenance_controller", ROOT / "scripts/controller-package.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
audit = controller.signed.audit
EXTERNAL = ("scripts/open-trusted-controller.ps1", "scripts/controller-package.py", "scripts/controller-provenance.py",
            "scripts/controller-review.py", "scripts/signing-readiness.py", "scripts/controller-delivery.py",
            "scripts/controller-receive.py")


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def collect(directory, pin, source=ROOT):
    directory, source = audit.local(directory), audit.local(source)
    verified = controller.verify(directory, pin)  # No packaged Python or code execution.
    inputs, evidence, blobs, components = {}, {}, {}, []

    def observe(base, scope, name, notice=False):
        raw = audit.read(base, name, audit.MAX_NOTICE if notice else audit.MAX_TEXT)
        key = scope + ":" + name
        record = {"scope": scope, "path": name, "bytes": len(raw), "sha256": audit.digest(raw)}
        inputs[key] = record
        if notice:
            raw.decode("utf-8-sig")
            target = "notices/" + audit.digest(raw) + ".txt"
            evidence[key] = {**record, "copy": target}
            blobs[target] = raw
            if sum(map(len, blobs.values())) > audit.MAX_EVIDENCE:
                raise ValueError("Excessive notice evidence")
        return raw, key

    # Source comparisons describe these exact packaged bytes, not the current branch name.
    for name in controller.SOURCE:
        if observe(directory, "controller", name)[0] != observe(source, "source", name)[0]:
            raise ValueError("Controller source differs; audit against its exact source snapshot")
    external = []
    for name in EXTERNAL:
        raw, key = observe(source, "source", name)
        target = "external/" + name
        blobs[target] = raw
        external.append({**inputs[key], "copy": target, "shipped_in_controller": name in controller.SOURCE})

    def component(ecosystem, name, version, declared, notices, metadata=None, origins=None):
        components.append({
            "ecosystem": ecosystem, "name": audit.label(name), "version": audit.label(version),
            "declared_license": audit.label(declared), "scope": "controller-distribution",
            "metadata": metadata, "notices": sorted(set(notices)),
            "origin_hints": sorted(origins or []), "origin_authenticated": False,
            "redistribution_decision": "pending_owner_review",
        })

    _, own = observe(directory, "controller", "LICENSE", True)
    component("project", "INARA trusted controller", pin, "SEE_LICENSE_EVIDENCE", [own])
    runtime_raw, _ = observe(directory, "controller", "runtime/runtime-manifest.json")
    runtime = json.loads(runtime_raw)
    _, python_license = observe(directory, "controller", "runtime/LICENSE.txt", True)
    component("runtime", "CPython", runtime["python_version"], "SEE_LICENSE_EVIDENCE", [python_license])
    found = {}
    site = directory / "runtime/Lib/site-packages"
    folders = sorted(site.glob("*.dist-info"))
    if not 1 <= len(folders) <= 512:
        raise ValueError("Missing or excessive Python metadata")
    for folder in folders:
        folder_name = folder.relative_to(directory).as_posix()
        raw, key = observe(directory, "controller", folder_name + "/METADATA")
        meta = Parser().parsestr(raw.decode("utf-8"))
        name = audit.package.runtime_tool().canonical(meta["Name"] or "")
        if name in found or name not in runtime["dependencies"] or meta["Version"] != runtime["dependencies"][name]:
            raise ValueError("Duplicate, unknown or changed dependency metadata")
        found[name] = meta["Version"]
        notices = []
        for path in audit.package.files_in(folder):
            if audit.license_name(path.name):
                _, notice = observe(directory, "controller", path.relative_to(directory).as_posix(), True)
                notices.append(notice)
        for declared in meta.get_all("License-File", []):
            audit.relative(declared)
            options = [folder_name + "/licenses/" + declared, folder_name + "/" + declared]
            chosen = next((name for name in options if (directory / name).is_file()), None)
            if chosen is None:
                raise ValueError("Declared license evidence is missing")
            _, notice = observe(directory, "controller", chosen, True)
            notices.append(notice)
        hints = [audit.label(x) for x in meta.get_all("Project-URL", [])]
        if meta.get("Home-page"):
            hints.append(audit.label(meta["Home-page"]))
        component("pypi", name, meta["Version"], meta.get("License-Expression") or meta.get("License"), notices, key, hints)
    if found != runtime["dependencies"]:
        raise ValueError("Dependency metadata does not cover the controller runtime")

    manifest = json.loads(audit.read(directory, controller.MANIFEST, 4_194_304))
    native = [entry for entry in manifest["files"] if Path(entry["path"]).suffix.lower() in {".exe", ".dll", ".pyd"}]
    missing = [{k: c[k] for k in ("ecosystem", "name", "version", "metadata")} for c in components if not c["notices"]]
    report = {
        "format": 1, "kind": "inara-controller-provenance", "controller_manifest_sha256": pin,
        "collector_sha256": audit.digest(Path(__file__).read_bytes()), "controller_files": verified["files"],
        "components": sorted(components, key=lambda c: (c["ecosystem"], c["name"])),
        "inputs": sorted(inputs.values(), key=lambda x: (x["scope"], x["path"])),
        "license_evidence": sorted(evidence.values(), key=lambda x: (x["scope"], x["path"])),
        "external_delivery_inputs": external, "native_files": native,
        "missing_notice_components": missing,
        "review_gaps": [
            "Metadata URLs and observed versions are hints, not authenticated upstream acquisition evidence.",
            "CPython and wheel native/vendor internals require subcomponent, source and redistribution review; file hashes do not establish that coverage.",
            "Runtime support/security baselines and dependency vulnerability review need authoritative dated evidence.",
            "External bootstrap/build tools are copied as separate evidence; this does not authenticate their delivery or enroll a publisher.",
        ],
        "network_accessed": False, "private_profile_read": False, "runtime_executed": False,
        "release_ready": False, "license_clearance": False, "publisher_authenticated": False,
    }
    subjects = []

    def subject(category, label, target, required):
        value = {"category": category, "label": label, "target": target, "required_evidence": sorted(required)}
        subjects.append({"id": audit.digest(encoded(value)), **value, "status": "pending"})

    for c in report["components"]:
        subject("component", c["ecosystem"] + ":" + c["name"] + "@" + c["version"], c, ["origin", "license", "obligations"])
        if c["ecosystem"] == "runtime":
            subject("runtime-baseline", c["name"], c, ["origin", "security", "support"])
    for c in missing:
        subject("missing-notice", c["name"], c, ["origin", "notice"])
    subject("vendored-native", "Controller native/vendor subcomponent coverage", native, ["inventory", "origin", "license", "obligations"])
    for entry in external:
        subject("delivery-input", entry["path"], entry, ["origin", "license", "obligations", "delivery"])
    report_raw = encoded(report)
    queue = {
        "format": 1, "kind": "inara-controller-review-queue", "controller_manifest_sha256": pin,
        "report_sha256": audit.digest(report_raw), "subjects": subjects,
        "decisions_recorded": 0, "release_authorized": False,
        "note": "Pending evidence checklist only; not the desktop ledger or a release authorization input.",
    }
    files = audit.artifacts(report, blobs)
    files.pop("distribution-audit.json")
    files["controller-provenance.json"] = report_raw
    files["controller-review-queue.json"] = encoded(queue)
    return files, {
        "integrity": "passed", "controller_manifest_sha256": pin, "controller_files": verified["files"],
        "report_sha256": audit.digest(report_raw), "components": len(components),
        "notice_files": len(evidence), "native_files": len(native), "pending_reviews": len(subjects),
        "missing_notice_components": missing, "release_authorized": False,
    }


def run(command, directory, pin, output, source=ROOT):
    directory, source = audit.local(directory), audit.local(source)
    output = audit.output_path(output, directory, source)
    if command == "collect" and output.exists():
        raise ValueError("Choose a NEW evidence output")
    files, result = collect(directory, pin, source)
    if command == "collect":
        output.mkdir(parents=True)
        for name, raw in files.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
    elif command == "verify":
        output = audit.local(output)
        actual = {p.relative_to(output).as_posix() for p in audit.package.files_in(output)}
        if actual != set(files):
            raise ValueError("Missing or unexpected controller evidence")
        for name, raw in files.items():
            if audit.read(output, name, audit.MAX_EVIDENCE) != raw:
                raise ValueError("Controller evidence changed or is stale")
    else:
        raise ValueError("Unknown provenance command")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "verify"))
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--expected-manifest", required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.command, args.controller, args.expected_manifest, args.output, args.source)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(1, "Controller provenance refused; preserve inputs and existing evidence.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
